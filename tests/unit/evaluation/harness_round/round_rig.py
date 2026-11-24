"""A harness round over a stand-in tier version, its runs made by the real loop with no model.

The store is the baseline's stand-in (:func:`baseline_fixtures.stand_in_store`): twenty-four
fixture tasks split by the real writer, its check recorded, a run root registered. The target
is a repository with one commit. The driver stands in for the ``physgate`` command: its
``decompose`` does what the command's does with the call's outcome given, not asked of a model
(the run directory refused unless fresh, the parameters recorded, the run started from a plan of
one control module, or recorded as a failed decomposition); its ``drive`` is the real loop with
the real change checker, merger and store keeper, a stand-in session that writes the answer file
in its module's directory, and the command's own refusal of a resume before a usage limit's
reset. A row makes a call fail, end on the machine or be killed, by its number.
"""

from __future__ import annotations

import hashlib
import json
import subprocess
import sys
import uuid
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

EVALUATION_TESTS = Path(__file__).resolve().parents[1]
for _where in (EVALUATION_TESTS, EVALUATION_TESTS / "baseline", EVALUATION_TESTS / "per_role"):
    if str(_where) not in sys.path:
        sys.path.insert(0, str(_where))

from baseline_fixtures import (  # noqa: E402
    BUILT,
    EXAMPLES,
    LAYER,
    MODEL,
    PRICES,
    SCORED,
    StandInStore,
    stand_in_store,
)
from knowledge_fixture import build_fixture_library  # noqa: E402
from observe_rig import FakeSession, Gate, Reviewer, node  # noqa: E402
from task_fixtures import controller  # noqa: E402

from physgate.evaluation.harness_round import Decompose, Drive, Inputs  # noqa: E402
from physgate.evaluation.observe.cost import load_price_sheet  # noqa: E402
from physgate.evaluation.tiers.canaries import store_canaries  # noqa: E402
from physgate.evaluation.tiers.exposure import add_run_root  # noqa: E402
from physgate.evaluation.tiers.heldout import tier_digest  # noqa: E402
from physgate.evaluation.tiers.task import Task  # noqa: E402
from physgate.orchestrator.apply import GitChangeChecker, StoreKeeper  # noqa: E402
from physgate.orchestrator.budget import SessionEnd  # noqa: E402
from physgate.orchestrator.canaries import CanaryCheck  # noqa: E402
from physgate.orchestrator.decompose import (  # noqa: E402
    Outcome,
    Plan,
    PlannedModule,
    mint_id,
    require_fresh,
    start_run,
)
from physgate.orchestrator.design_rounds import decomposition_streams  # noqa: E402
from physgate.orchestrator.escalation import bind  # noqa: E402
from physgate.orchestrator.events import SubtaskPlanned, read_events  # noqa: E402
from physgate.orchestrator.exceptions import LimitNotResetError  # noqa: E402
from physgate.orchestrator.git import head_of  # noqa: E402
from physgate.orchestrator.loop import Loop  # noqa: E402
from physgate.orchestrator.merge import GitMerger, RunGit  # noqa: E402
from physgate.orchestrator.params_record import record_params  # noqa: E402
from physgate.orchestrator.ports import SessionReport, SessionRequest, SpawnHook  # noqa: E402
from physgate.orchestrator.protocols import MessageUsage, Usage  # noqa: E402
from physgate.orchestrator.run_config import RunConfig, load_run_config  # noqa: E402
from physgate.orchestrator.trajectory import seal  # noqa: E402
from physgate.orchestrator.usage_limit import UsageLimit  # noqa: E402
from physgate.orchestrator.waiting import (  # noqa: E402
    EXIT_WAITING_FOR_LIMIT,
    limit_wait,
    printed_step,
)
from physgate.state.schema import Node  # noqa: E402

__all__ = ["PRICES", "SCORED", "Killed", "Rig", "StandInDriver", "make_rig"]


class Killed(BaseException):  # noqa: N818 - stands for the process being killed, as an interrupt is
    """The round's process killed at the point a row names."""


def target_repo(root: Path) -> Path:
    """A target repository with one commit and a clean worktree."""
    repo = root / "design"
    (repo / "modules").mkdir(parents=True)
    (repo / "README.md").write_text("design\n")
    (repo / "modules" / "keep.txt").write_text("x\n")
    for args in (
        ["init", "-q", "-b", "master"],
        ["add", "-A"],
        ["commit", "-q", "-m", "i"],
    ):
        subprocess.run(
            ["git", "-c", "user.email=t@example.invalid", "-c", "user.name=t", *args],
            cwd=repo,
            check=True,
            capture_output=True,
        )
    return repo


def params(made: StandInStore, **changes: Any) -> dict[str, Any]:  # noqa: ANN401
    """A measured single-role run's parameters on the store, with what the command measures.

    The stand-in ``decompose`` takes these as the run's configuration, adding what a run is
    given (its id, seed, brief digest and target commit); the real one measures the rest.
    """
    fields: dict[str, Any] = json.loads((EXAMPLES / "params.subscription.json").read_text())
    fields.update(
        claude_version="2.1.301",
        endpoint="default",
        reportable=True,
        harness={"commit": "c" * 40, "clean": True, "uncommitted_sha256": None},
        git_binary=None,
        binary=BUILT.model_dump(),
        account={"name": fields["account"], "token_sha256_prefix": "e" * 12},
        os_layer=LAYER.model_dump(),
        # A stand-in loop records no OS-layer line: allowed, as for every rig of the loop.
        os_layer_absent="allow",
        network="none",
        network_enforced=True,
        tool_servers=None,
        tool_search="denied",
        # The plan's review is a model call; the stand-in makes none.
        design_review="off",
        models={
            "decomposition": MODEL,
            "roles": {"control": MODEL},
            "reviewers": {"control": "claude-sonnet-5"},
        },
        held_out=list(made.held_out),
        held_out_sha256=[tier_digest(Path(root)) for root in made.held_out],
        held_out_canaries=sorted(set(made.canaries) | set(store_canaries(made.store))),
    )
    fields["bounds"]["infra_retry_delays_s"] = [7.0]
    fields.update(changes)
    return fields


@dataclass
class AnswerSession(FakeSession):
    """The loop's stand-in session, writing the task's answer file in its module's directory."""

    answer_name: str = "answer.json"
    #: The calls that write no answer (a call that ends on the machine writes none either).
    silent: set[int] = field(default_factory=set)
    #: The calls the process is killed in, before the session runs.
    killed: set[int] = field(default_factory=set)
    #: The calls that end on the account's usage limit, its reset not read.
    limited: set[int] = field(default_factory=set)
    #: The calls whose credential is refused.
    refused_credential: set[int] = field(default_factory=set)
    #: Counted across every drive of the row, so a call's number names it in any process.
    counter: list[int] = field(default_factory=lambda: [0])

    def run(self, request: SessionRequest, on_spawn: SpawnHook | None = None) -> SessionReport:
        self.counter[0] += 1
        call = self.counter[0]
        if call in self.killed:
            raise Killed
        self.calls = call - 1  # the stand-in numbers its own calls from here
        worktree = self.layout.open_subtask(request.subtask_id)
        if call in self.refused_credential:
            return SessionReport(
                session_id=f"cred-{call}",
                end=SessionEnd(outcome="infrastructure", cause="credential_refused"),
                attempt_commit=None,
                trajectory=None,
                trajectory_seal=None,
                worktree=str(worktree),
                reading_verified=False,
                node_files_halted=False,
                usage=(),
            )
        if call in self.limited:
            stream = self.layout.run_dir / "sessions" / f"limit-{call}" / "stdout.jsonl"
            stream.parent.mkdir(parents=True, exist_ok=True)
            stream.write_text(json.dumps({"type": "result", "session_id": f"limit-{call}"}) + "\n")
            return SessionReport(
                session_id=f"limit-{call}",
                end=SessionEnd(outcome="infrastructure", cause="usage_limit"),
                attempt_commit=None,
                trajectory=str(stream),
                trajectory_seal=seal(stream.read_bytes()),
                worktree=str(worktree),
                reading_verified=False,
                node_files_halted=False,
                usage=(),
                usage_limit=UsageLimit(resets="later"),
            )
        if call not in self.silent and call not in self.infra:
            module = worktree / request.module_dir
            module.mkdir(parents=True, exist_ok=True)
            (module / self.answer_name).write_text(json.dumps(controller()))
        return super().run(request, on_spawn)


@dataclass
class StandInDriver:
    """Decomposes and drives as the command does; each call numbered from 1 across the row."""

    library: Path
    answer_name: str
    #: Per decomposition: the cause its call ends on instead of a plan.
    fails: dict[int, str] = field(default_factory=dict)
    #: The decompositions the process is killed in, after the parameters are recorded.
    killed_in_decompose: set[int] = field(default_factory=set)
    #: The decompositions the command refuses (exit 2) before it writes anything.
    refused: set[int] = field(default_factory=set)
    #: The drives the process is killed in, before the loop is built.
    killed_in_drive: set[int] = field(default_factory=set)
    #: Session calls (across the row) that end on an API error, that write no answer, or in
    #: which the process is killed.
    infra: set[int] = field(default_factory=set)
    silent: set[int] = field(default_factory=set)
    killed: set[int] = field(default_factory=set)
    limited: set[int] = field(default_factory=set)
    refused_credential: set[int] = field(default_factory=set)
    #: The module directory the plan gives, from the minted id; ``modules/<id>`` by default.
    module_dir: Callable[[str], str] = lambda minted: f"modules/{minted}"
    decomposed: list[Decompose] = field(default_factory=list)
    drives: list[Drive] = field(default_factory=list)
    sessions: list[int] = field(default_factory=lambda: [0])
    clock: Callable[[], datetime] = lambda: datetime.now(UTC)

    def decompose(self, call: Decompose) -> int:
        self.decomposed.append(call)
        n = len(self.decomposed)
        if n in self.refused:
            return 2
        require_fresh(call.run_dir)
        record_params(call.run_dir, call.params)
        if n in self.killed_in_decompose:
            raise Killed
        fields = json.loads(call.params.read_bytes())
        fields.update(
            run_id=call.run_id,
            seed=call.seed,
            brief_sha256=hashlib.sha256(call.brief.read_bytes()).hexdigest(),
            target_head=head_of(call.target, "HEAD"),
        )
        config = RunConfig.model_validate_json(json.dumps(fields))
        cause = self.fails.get(n)
        minted = mint_id(config.seed, 0, "ctl")
        plan = Plan(
            modules=(
                PlannedModule(
                    name="ctl",
                    role="control",
                    module_dir=self.module_dir(minted),
                    spec="Design the controller. Answer here.",
                ),
            ),
            interface_nodes=(Node.model_validate(node("iface.bus", kind="interface")),),
        )
        usage = Usage(
            input_tokens=50,
            output_tokens=20,
            cache_read_input_tokens=0,
            cache_creation_input_tokens=0,
        )
        outcome = Outcome(
            session_id=f"plan-{n}",
            ok=cause is None,
            cause=cause,  # type: ignore[arg-type]
            detail="stand-in",
            plan=plan if cause is None else None,
            usage=(MessageUsage(message_id=f"plan-{n}", usage=usage),),
            model=MODEL,
            num_turns=1,
        )
        start_run(
            outcome,
            config=config,
            run_dir=call.run_dir,
            target_repo=call.target,
            library=self.library,
        ).close()
        # The call's stream, where the log names it: a protected trial's is scanned for its canary.
        for place in decomposition_streams(read_events(call.run_dir / "events.jsonl")):
            stream = call.run_dir / place
            stream.parent.mkdir(parents=True, exist_ok=True)
            stream.write_text(json.dumps({"type": "result", "session_id": f"plan-{n}"}) + "\n")
        return 0 if cause is None else 1

    def drive(self, call: Drive) -> int:
        self.drives.append(call)
        if len(self.drives) in self.killed_in_drive:
            raise Killed
        run_dir = call.run_dir
        if call.resume:
            # As the command refuses it: before anything is built, written or started.
            waiting = limit_wait(run_dir, self.clock(), limit_reset=call.limit_reset)
            if waiting is not None:
                return EXIT_WAITING_FOR_LIMIT
        config = load_run_config(run_dir / "run.json")
        run = RunGit(repo=call.target, run_dir=run_dir, run_id=config.run_id)
        plan = [e for e in read_events(run_dir / "events.jsonl") if isinstance(e, SubtaskPlanned)]
        keeper = StoreKeeper(run, run_dir / "store")
        session = AnswerSession(
            run,
            role="control",
            infra=self.infra,
            limited=self.limited,
            refused_credential=self.refused_credential,
            answer_name=self.answer_name,
            silent=self.silent,
            killed=self.killed,
            counter=self.sessions,
        )
        loop = Loop(
            config=config,
            run_dir=run_dir,
            gate=Gate(),
            reviewers={
                r: Reviewer(model=m, ids=uuid.uuid4().hex[:6])
                for r, m in config.models.reviewers.items()
            },
            dispatcher=session,
            changes=GitChangeChecker(
                run, run_dir / "store", {e.subtask_id: e.module_dir for e in plan}
            ),
            merger=GitMerger(run, removal_timeout_s=60.0),
            graph=keeper,
            escalation=bind("rules"),
            material=CanaryCheck(
                held_out=frozenset(config.held_out_canaries), review_material=frozenset()
            ),
            sleep=lambda _: None,
            clock=self.clock,
        )
        word = "a person" if call.limit_reset else None
        try:
            step = loop.resume(limit_reset_by=word) if call.resume else loop.run()
        except LimitNotResetError:
            return EXIT_WAITING_FOR_LIMIT
        finally:
            loop.close()
            keeper.close()
        # The command's own exit status for the step the run stopped at.
        return printed_step(step.kind, loop.state)[1]


@dataclass
class Rig:
    """A stand-in store with a registered run root, a target and the round's other inputs."""

    root: Path
    made: StandInStore
    target: Path
    run_root: Path
    params: Path
    library: Path

    def inputs(self, **changes: Any) -> Inputs:  # noqa: ANN401
        fields: dict[str, Any] = {
            "store": self.made.store,
            "role": "control",
            "version": self.made.version,
            "tiers": ("visible",),
            "trials": 2,
            "seed_base": 100,
            "params": self.params,
            "run_root": self.run_root,
            "target_from": self.target,
            "install": self.root / "install",
            "prices": load_price_sheet(PRICES),
            "out": self.root / "out",
            "tasks": 1,
        }
        fields.update(changes)
        return Inputs(**fields)

    def task(self, tier: str = "visible") -> Task:
        """The first task of ``tier`` in the round's order: by its brief's digest."""
        return min(
            self.made.tasks[tier], key=lambda t: hashlib.sha256(t.brief.encode()).hexdigest()
        )

    def driver(self, **how: Any) -> StandInDriver:  # noqa: ANN401
        return StandInDriver(library=self.library, answer_name=self.task().answer.path, **how)


def make_rig(tmp_path: Path, *, store: dict[str, Any] | None = None, **params_changes: Any) -> Rig:  # noqa: ANN401
    """The rig; ``store`` is given to the stand-in store, the rest to the run parameters."""
    root = tmp_path.resolve()
    made = stand_in_store(root, **(store or {}))
    run_root = root / "runs"
    run_root.mkdir()
    add_run_root(made.store, "control", run_root)
    target = target_repo(root)
    path = root / "params.json"
    path.write_text(json.dumps(params(made, **params_changes)))
    library = build_fixture_library(root / "library")
    return Rig(root, made, target, run_root, path, library)
