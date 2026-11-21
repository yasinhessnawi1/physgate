"""One combination of the ablation switches, started by the command and driven by the real loop.

A run here is what ``physgate decompose`` and then ``physgate run`` produce with no model and no
binary behind them:

- **decompose** is the command itself, with the composition root's requirements registered as it
  registers them. Its one model call is a stand-in that answers a fixed plan (one module, one
  interface node), and the plan's reviewer, where the run reviews its plan, is a stand-in that
  passes it. Three facts of the machine are given rather than measured, because the matrix is
  about the switches and not the machine: the OS layer is present, the harness checkout is clean
  at its commit, and the stand-in binary counts as a listed build. Each is the condition a
  measured run needs, so no combination is refused for where the suite happens to run.
- **run** is the real loop over the run's own record, with the real store, change checker and
  merger on real git. The role session is a stand-in that writes one module file and one node
  proposal into its worktree; before it writes, it is installed as the dispatcher installs every
  role session, through the dispatcher's own installation and the real installer, so what the
  session would have been given (its reading, the hooks wired for it) is what the run's record
  makes of it. The gate refuses each subtask's first attempt, so every gate mode shows what it
  does with a refusal. The role reviewers are the ones the command builds from the run's
  configuration, each answering a pass with the rubric it was built with, so a review line names
  the arm's own rubric.

Nothing here reads a credential, starts a model session or runs the Claude binary.
"""

from __future__ import annotations

import contextlib
import io
import itertools
import json
import shlex
import shutil
import subprocess
import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import pytest
from harness_pin import measured_harness
from knowledge_fixture import build_fixture_library
from test_the_physgate_command_starts_and_decides import PARAMS, _promoted, _run_args, fake_binary

import physgate.flags as flags
import physgate.orchestrator.cli as orchestrator_cli
from physgate.cli import main
from physgate.orchestrator import binaries
from physgate.orchestrator.apply import GitChangeChecker, StoreKeeper
from physgate.orchestrator.canaries import CanaryCheck
from physgate.orchestrator.credentials import Credential
from physgate.orchestrator.decompose import Outcome
from physgate.orchestrator.dispatch import ClaudeDispatcher
from physgate.orchestrator.escalation import bind
from physgate.orchestrator.events import OsLayerChecked, SubtaskPlanned, read_events
from physgate.orchestrator.loop import Loop
from physgate.orchestrator.merge import GitMerger, RunGit
from physgate.orchestrator.plan import Plan
from physgate.orchestrator.ports import Leftover, SessionReport, SessionRequest, SpawnHook
from physgate.orchestrator.protocols import Artefact, MessageUsage, ReviewResult, Usage
from physgate.orchestrator.run_config import HarnessState, RunConfig, load_run_config
from physgate.orchestrator.trajectory import seal
from physgate.oslayer.probe import Present
from physgate.oslayer.session_temp import make_session_temp
from physgate.reviewers.claude import ReviewerSetup, claude_reviewers

EVALUATION_TESTS = Path(__file__).resolve().parents[1] / "evaluation"
if str(EVALUATION_TESTS) not in sys.path:
    sys.path.insert(0, str(EVALUATION_TESTS))
import observe_rig  # noqa: E402 - importable once the observability tests' directory is on the path

ROLE = "electrical"
DECOMPOSITION = "claude-sonnet-5"
#: The role reviewers' pin and the plan reviewer's: a model other than every role's.
REVIEWER = "claude-opus-5-5"
BRIEF = "Build a robot.\n\n## Acceptance criteria\n\n1. It is powered.\n"
#: The OS layer every combination is configured, driven and installed under.
LAYER = Present(mechanism="seatbelt", claude_version="2.1.301")
DUMMY_KEY = "sk-ant-test-dummy-not-a-credential"

#: The switches ARCH-140 names that are built, each with every value the register gives it.
SWITCHES: dict[str, tuple[str, ...]] = {
    "gate_mode": flags.GATE_MODE.values,
    "design_review": flags.DESIGN_REVIEW.values,
    "reviewers": flags.REVIEWERS.values,
    "skills": flags.SKILLS.values,
    "hooks": flags.HOOKS.values,
}

#: The register's other flags: run conditions rather than switches ARCH-140 names, each held at
#: the one value every measured run takes, with the reason.
CONDITIONS: dict[str, tuple[str, str]] = {
    "queue_decisions": (
        "record",
        "a measured run records a person's decisions and acts on none",
    ),
    "os_layer_absent": (
        "refuse",
        "the allowance is for development, and no measured run names it",
    ),
    "parts_on_hand": (
        "off",
        "asking about parts holds the run for a person's decisions, which only a run that acts on "
        "them takes, and no measured run does",
    ),
    "review_compaction": (
        "off",
        "a setting of a reviewer's own session, measured per pin; the matrix's reviewers run no "
        "session",
    ),
    "escalation_backend": (
        "rules",
        "the one backend that ships; every other is refused in every run",
    ),
}

#: A run's kind, by its two recorded booleans: (reportable, ablation).
KINDS: dict[str, tuple[bool, bool]] = {
    "ordinary": (False, False),
    "reportable": (True, False),
    "ablation": (False, True),
    "both": (True, True),
}


@dataclass(frozen=True)
class Combination:
    """One point of the matrix: a value of every switch, and the run's kind."""

    gate_mode: str
    design_review: str
    reviewers: str
    skills: str
    hooks: str
    kind: str

    @property
    def switches(self) -> dict[str, str]:
        return {name: getattr(self, name) for name in SWITCHES}

    @property
    def reportable(self) -> bool:
        return KINDS[self.kind][0]

    @property
    def ablation(self) -> bool:
        return KINDS[self.kind][1]

    @property
    def label(self) -> str:
        return "-".join([*self.switches.values(), self.kind])


def every_combination() -> list[Combination]:
    """Every combination of every switch's values and every run kind, in a fixed order."""
    return [
        Combination(gate, review, reviewers, skills, hooks, kind)
        for gate, review, reviewers, skills, hooks, kind in itertools.product(
            *SWITCHES.values(), KINDS
        )
    ]


# -- the rules a combination is refused by, as the architecture states them -------------------

#: What a refusal by each rule says, word for word: the fixed part of its message.
RULES: dict[str, str] = {
    "a run is one kind": "an ablation run is never reportable",
    "a re-plan is an experiment's arm": "re-plans a rejected plan, an experiment arm",
    "reviewers' arm is an ablation run's": "is an ablation arm: only an ablation run takes it",
    "skills' arm is an ablation run's": "is an ablation arm: only an ablation run takes it",
    "hooks' arm is an ablation run's": "is an ablation arm: only an ablation run takes it",
    "a measured run reviews its plan": "records its plan's review: design_review: observe",
}


def configuration_rules(c: Combination) -> list[str]:
    """The configuration's rules ``c`` breaks, stated apart from the code that holds them.

    A run is one kind or neither; a re-plan is an experiment's arm, and an experiment's runs are
    reportable; each arm that removes a component is an ablation run's alone.
    """
    broken = []
    if c.reportable and c.ablation:
        broken.append("a run is one kind")
    if c.design_review.startswith("repair:") and not c.reportable:
        broken.append("a re-plan is an experiment's arm")
    if c.reviewers != "paired" and not c.ablation:
        broken.append("reviewers' arm is an ablation run's")
    if c.skills == "off" and not c.ablation:
        broken.append("skills' arm is an ablation run's")
    if c.hooks == "off" and not c.ablation:
        broken.append("hooks' arm is an ablation run's")
    return broken


def requirement_rules(c: Combination) -> list[str]:
    """The evaluation's rules ``c`` breaks: a measured run records its plan's review."""
    measured = c.reportable or c.ablation
    return ["a measured run reviews its plan"] if measured and c.design_review == "off" else []


def expected_rules(c: Combination) -> list[str]:
    """The rules one of which names ``c``'s refusal; none for a combination that runs.

    The configuration's are asked first, then the evaluation's.
    """
    return configuration_rules(c) or requirement_rules(c)


def rule_text(rule: str, c: Combination) -> str:
    """What a refusal of ``c`` by ``rule`` says."""
    for name in ("reviewers", "skills", "hooks"):
        if rule == f"{name}' arm is an ablation run's":
            return f"{name}: {getattr(c, name)} {RULES[rule]}"
    if rule == "a re-plan is an experiment's arm":
        return f"design_review: {c.design_review} {RULES[rule]}"
    return RULES[rule]


# -- the machine, built once per process ------------------------------------------------------


@dataclass(frozen=True)
class Machine:
    """What every combination is configured and driven with: built once, read by every one."""

    library: Path
    binary: Path
    install_args: tuple[str, ...]
    #: A target repository with one commit, copied for each combination, and its refs.
    target: Path
    target_refs: str
    #: The harness as a measured run needs it: clean, at the commit this suite measured.
    harness: HarnessState

    @property
    def install(self) -> Path:
        return Path(self.install_args[self.install_args.index("--install") + 1])


def build_machine(root: Path) -> Machine:
    """What every combination is configured and driven with, built under ``root``.

    The harness library is the suite's fixture library with the role's promoted rubric, so the
    command finds every curated file and the role reviewers their rubric; the binary is a
    stand-in that answers its version; the installation is a stand-in of the package as it is.
    """
    library = build_fixture_library(root / "harness")
    _promoted(library, ROLE)
    run_args = _run_args(root)
    target = observe_rig.target_repo(root / "template")
    return Machine(
        library=library,
        binary=fake_binary(root, "2.1.272"),
        install_args=tuple(run_args[run_args.index("--install") :]),
        target=target,
        target_refs=refs(target),
        harness=HarnessState(commit=measured_harness().commit, clean=True, uncommitted_sha256=None),
    )


def on_the_machine(monkeypatch: pytest.MonkeyPatch, machine: Machine) -> None:
    """The facts of the machine a measured run needs, given: none is what the matrix varies."""
    monkeypatch.setenv("ANTHROPIC_API_KEY", DUMMY_KEY)
    monkeypatch.setenv("PHYSGATE_CLAUDE_BIN", str(machine.binary))
    monkeypatch.setattr(orchestrator_cli, "_library_root", lambda: machine.library)
    monkeypatch.setattr(orchestrator_cli, "judge_here", lambda **_kw: LAYER)
    monkeypatch.setattr(orchestrator_cli, "harness_state", lambda _root: machine.harness)
    monkeypatch.setattr(binaries, "require_listed", lambda *_a: None)


# -- decompose --------------------------------------------------------------------------------


def _usage(n: int) -> Usage:
    return Usage(
        input_tokens=n, output_tokens=n, cache_read_input_tokens=0, cache_creation_input_tokens=0
    )


def the_plan() -> Plan:
    """The stand-in decomposition's answer: one module of the role, one interface node."""
    spec = "Power it.\n\n## Acceptance criteria\n\n1. It is powered.\n"
    answer = {
        "modules": [{"name": "power", "role": ROLE, "module_dir": "modules/power", "spec": spec}],
        "interface_nodes": [observe_rig.node("iface.bus", kind="interface", role=ROLE)],
    }
    return Plan.model_validate_json(json.dumps(answer))


@dataclass
class Call:
    """The one model call: it writes its stream where the call does, and answers the plan."""

    made: int = 0

    def __call__(self, brief: str, *, workdir: Path, **given: Any) -> Outcome:  # noqa: ANN401
        self.made += 1
        workdir.mkdir(parents=True, exist_ok=True)
        message = {"id": "m1", "model": DECOMPOSITION, "content": []}
        (workdir / "stdout.jsonl").write_text(json.dumps({"type": "assistant", "message": message}))
        return Outcome(
            session_id=given.get("session_id") or "decomposition-session-1",
            ok=True,
            cause=None,
            detail="a plan",
            plan=the_plan(),
            usage=(MessageUsage(message_id="d1", usage=_usage(10)),),
            model=DECOMPOSITION,
            num_turns=1,
            stream_seal=seal((workdir / "stdout.jsonl").read_bytes()),
        )


@dataclass
class PlanReviewer:
    """The plan's reviewer: it passes the plan, and counts how often it was asked."""

    asked: int = 0

    @property
    def model(self) -> str:
        return REVIEWER

    def review_plan(self, under: Any) -> ReviewResult:  # noqa: ANN401
        self.asked += 1
        return ReviewResult(
            verdict="pass",
            finding="the plan allocates every criterion",
            reviewer_model=REVIEWER,
            session_id="design-review-session-1",
            usage=(MessageUsage(message_id="r1", usage=_usage(5)),),
        )

    def factory(self, setup: Any, config: Any) -> PlanReviewer:  # noqa: ANN401
        return self


def params(c: Combination) -> dict[str, Any]:
    """The run's parameters file for ``c``: its switches, its kind and the fixed conditions."""
    return {
        **PARAMS,
        "models": {
            "decomposition": DECOMPOSITION,
            "roles": {ROLE: DECOMPOSITION},
            "reviewers": {ROLE: REVIEWER, "design": REVIEWER},
        },
        **{name: value for name, (value, _) in CONDITIONS.items()},
        **c.switches,
        "reportable": c.reportable,
        "ablation": c.ablation,
    }


@dataclass
class Decomposed:
    """What the command did with a combination: its exit, its refusal, and what it asked."""

    code: int
    error: dict[str, Any] | None
    calls: int
    plan_reviews: int
    #: The target's refs before the command and after it.
    refs_before: str
    refs_after: str


def refs(repo: Path) -> str:
    """Every ref of ``repo`` and what it names."""
    return str(observe_rig.git(repo, "for-each-ref", "--format=%(refname) %(objectname)"))


def files_at(repo: Path, commit: str) -> list[str]:
    """Every file the tree of ``commit`` in ``repo`` holds."""
    return str(observe_rig.git(repo, "ls-tree", "-r", "--name-only", commit)).splitlines()


def decompose(root: Path, c: Combination, machine: Machine) -> Decomposed:
    """``physgate decompose`` for ``c``, against a target of its own under ``root``."""
    repo = root / "target"
    shutil.copytree(machine.target, repo, symlinks=True)
    (root / "brief.md").write_text(BRIEF)
    (root / "params.json").write_text(json.dumps(params(c)))
    call, reviewer = Call(), PlanReviewer()
    argv = [
        "decompose",
        str(root / "brief.md"),
        "--seed",
        "7",
        "--run-id",
        "run-1",
        "--params",
        str(root / "params.json"),
        "--target",
        str(repo),
        "--run-dir",
        str(root / "run"),
        *machine.install_args,
    ]
    registrations = orchestrator_cli.Registrations(plan_reviewer_factory=reviewer.factory)
    err, out = io.StringIO(), io.StringIO()
    with pytest.MonkeyPatch.context() as patch:
        patch.setattr(orchestrator_cli, "call", call)
        with contextlib.redirect_stderr(err), contextlib.redirect_stdout(out):
            code = main(argv, registrations)
    said = [line for line in err.getvalue().splitlines() if line.startswith("{")]
    return Decomposed(
        code=code,
        error=json.loads(said[-1]) if code != 0 and said else None,
        calls=call.made,
        plan_reviews=reviewer.asked,
        refs_before=machine.target_refs,
        refs_after=refs(repo),
    )


# -- run --------------------------------------------------------------------------------------


@dataclass
class Installed:
    """What one role session was installed with: the installer's arguments and its settings."""

    argv: list[str]
    settings: dict[str, Any]

    def values(self, flag: str) -> list[str]:
        return [self.argv[i + 1] for i, arg in enumerate(self.argv) if arg == flag]

    def wired(self) -> set[str]:
        """Every hook the settings wire, on any event."""
        names: set[str] = set()
        for groups in self.settings["hooks"].values():
            argv = shlex.split(groups[0]["hooks"][0]["command"])
            names |= set(argv[argv.index("--hooks") + 1].split(","))
        return names


@dataclass
class Session:
    """A role session: installed as the dispatcher installs one, then the stand-in's work.

    The installation is the dispatcher's own (``ClaudeDispatcher._install``) and the installer the
    real one, run in this process in place of its subprocess; nothing is spawned.
    """

    work: observe_rig.FakeSession
    dispatcher: ClaudeDispatcher
    root: Path
    installed: list[Installed] = field(default_factory=list)
    requests: list[SessionRequest] = field(default_factory=list)

    def environment(self) -> None:
        return None

    def stop_leftovers(self) -> list[Leftover]:
        return []

    def end_leftovers(self) -> None:
        return None

    def run(self, request: SessionRequest, on_spawn: SpawnHook | None = None) -> SessionReport:
        self.requests.append(request)
        worktree = self.work.layout.open_subtask(request.subtask_id)
        sdir = self.root / f"session-{len(self.requests)}"
        real = subprocess.run
        seen: list[list[str]] = []

        def installer(argv: list[str], **kwargs: Any) -> subprocess.CompletedProcess[str]:  # noqa: ANN401
            if argv[1:3] != ["hooks", "install"]:
                return real(argv, **kwargs)
            seen.append(list(argv))
            out, err = io.StringIO(), io.StringIO()
            with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
                code = main(argv[1:])
            return subprocess.CompletedProcess(argv, code, out.getvalue(), err.getvalue())

        # The session's own temporary directory, where every one is made; removed once installed.
        temp = make_session_temp()
        try:
            with pytest.MonkeyPatch.context() as patch:
                patch.setattr(subprocess, "run", installer)
                done = self.dispatcher._install(request, worktree, sdir, temp, own_temp=temp)
        finally:
            shutil.rmtree(temp)
        settings = json.loads(Path(done.settings).read_text())
        self.installed.append(Installed(argv=seen[0], settings=settings))
        return self.work.run(request, on_spawn)


@dataclass
class Reviewer:
    """A role reviewer the command built: it passes, judged with the rubric it was built with."""

    built: Any
    seen: list[Artefact] = field(default_factory=list)

    @property
    def model(self) -> str:
        return str(self.built.model)

    def review(self, artefact: Artefact) -> ReviewResult:
        self.seen.append(artefact)
        rubric = self.built.rubric
        return ReviewResult(
            verdict="pass",
            finding="sound",
            reviewer_model=self.model,
            session_id=f"rev-{len(self.seen)}",
            usage=(MessageUsage(message_id=f"rv-{len(self.seen)}", usage=_usage(4)),),
            rubric_sha256=rubric.sha256,
            rubric_kind=rubric.kind,
        )


def reviewers_of(config: RunConfig, root: Path, machine: Machine) -> dict[str, Reviewer]:
    """The role reviewers the command builds for ``config``, each answering through its rubric."""
    setup = ReviewerSetup.of_run(
        config,
        review_root=root / "rs",
        repo=root / "target",
        install_bin=machine.install / "bin" / "physgate",
        binary="/nonexistent/claude",
        base_url=None,
        credential=Credential("api_key", DUMMY_KEY),
        library=machine.library,
    )
    return {role: Reviewer(built) for role, built in claude_reviewers(setup).items()}


@dataclass
class Driven:
    """What the loop did with a started run."""

    step: str
    config: RunConfig
    session: Session
    gate: observe_rig.Gate
    reviewers: dict[str, Reviewer]


def drive(root: Path, machine: Machine) -> Driven:
    """Drive the run started in ``root`` with the real loop, as ``physgate run`` does."""
    run_dir = root / "run"
    config = load_run_config(run_dir / "run.json")
    run = RunGit(repo=root / "target", run_dir=run_dir, run_id=config.run_id)
    store_root = run_dir / "store"
    keeper = StoreKeeper(run, store_root)
    plan = [e for e in read_events(run_dir / "events.jsonl") if isinstance(e, SubtaskPlanned)]
    dispatcher = ClaudeDispatcher(
        config=config,
        run=run,
        store_root=store_root,
        install_bin=machine.install / "bin" / "physgate",
        binary="/nonexistent/claude",
        base_url=None,
        credential=Credential("api_key", DUMMY_KEY),
        review_root=root / "rs",
    )
    session = Session(
        work=observe_rig.FakeSession(run, role=ROLE), dispatcher=dispatcher, root=root / "sessions"
    )
    gate = observe_rig.Gate(fail_on={1})
    reviewers = reviewers_of(config, root, machine)
    loop = Loop(
        config=config,
        run_dir=run_dir,
        gate=gate,
        reviewers=reviewers,
        dispatcher=session,
        changes=GitChangeChecker(run, store_root, {e.subtask_id: e.module_dir for e in plan}),
        merger=GitMerger(run, removal_timeout_s=60.0),
        graph=keeper,
        escalation=bind("rules"),
        material=CanaryCheck(held_out=frozenset(), review_material=frozenset()),
        sleep=lambda _: None,
    )
    # As the command does before it drives: the OS layer where the sessions run, recorded.
    loop.record.emit(OsLayerChecked(**loop.record.envelope(), state=LAYER, as_recorded=True))
    try:
        step = loop.run()
    finally:
        loop.close()
        keeper.close()
    return Driven(step=step.kind, config=config, session=session, gate=gate, reviewers=reviewers)


def lines(run_dir: Path) -> list[dict[str, Any]]:
    return [json.loads(raw) for raw in (run_dir / "events.jsonl").read_text().splitlines()]
