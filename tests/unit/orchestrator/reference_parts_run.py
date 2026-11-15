"""The scripted run on the reference brief that asks which parts a person has, and its re-run.

ARCH-122. One run of the reference brief (``briefs/balboa-32u4.md``, its bytes and digest as the
repository holds them) through the real loop, the real store, real git and the real physics
gate. Three things are stand-ins, labelled as such, and no model is called:

- the decomposition's answer, a fixed plan with two modules and six components of the robot;
- each role session, which writes one node of its own role into its worktree, as a session's
  proposal is written, and is handed the parts record the release names;
- the reviewer, which passes, as the observability tests' stand-in does.

A person decides the parts through the command, as the operator would without the UI: the
gearmotors are owned (``have``, two values), the bumper cage is made (``make``, a value and a
text), and the rest are found (``queue parts --find-remaining``). The values are what a person
would type from the parts' own pages; nothing here measures them.

The clock is the record's own, ticking from one fixed instant: a part's item carries the time
of the decomposition's line, and a decision binds to the digest of the item's line, so a run
whose clock read the wall could never be made again line for line.

A re-run reads the recorded configuration (``run.json``) and nothing else of the run: the same
brief (held to the configuration's digest), the same stand-in answer and sessions, and the
person's decisions as the recorded decisions file states them, fed back through the queue's
one decision function. It is made under the recorded run id, in a run directory of its own and
against a clone of the target repository at the recorded head, since a run's branches live in
its target and two runs of one id cannot share one.
"""

from __future__ import annotations

import hashlib
import json
import subprocess
import sys
from collections.abc import Callable, Iterator
from contextlib import contextmanager
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

import pytest
from knowledge_fixture import build_fixture_library
from plan_hold_rig import PRESENT

from physgate.cli import main
from physgate.gate.runner import PhysicsGate
from physgate.orchestrator import common
from physgate.orchestrator import git as orchestrator_git
from physgate.orchestrator.apply import GitChangeChecker, StoreKeeper
from physgate.orchestrator.budget import SessionEnd
from physgate.orchestrator.canaries import CanaryCheck
from physgate.orchestrator.decompose import Outcome, PlannedModule, mint_id, start_run
from physgate.orchestrator.escalation import bind
from physgate.orchestrator.events import OsLayerChecked
from physgate.orchestrator.loop import Loop
from physgate.orchestrator.merge import GitMerger, RunGit, commit_attempt
from physgate.orchestrator.plan import Component, PartsPlan
from physgate.orchestrator.ports import Leftover, SessionReport, SessionRequest, SpawnHook
from physgate.orchestrator.protocols import MessageUsage, Usage
from physgate.orchestrator.queue import (
    DECISIONS_NAME,
    PersonDecision,
    QueueResolution,
    ShownItem,
    read_queue,
    record_decision,
    statuses_now,
)
from physgate.orchestrator.run_config import ModelStrings, RunConfig, load_run_config
from physgate.orchestrator.trajectory import seal
from physgate.state.schema import Node

EVALUATION_TESTS = Path(__file__).resolve().parents[1] / "evaluation"
if str(EVALUATION_TESTS) not in sys.path:
    sys.path.insert(0, str(EVALUATION_TESTS))
import observe_rig  # noqa: E402 - importable once the observability tests' directory is on the path

#: The scripted endpoint every run here names: a loopback address, so a comparison is exact.
ENDPOINT = observe_rig.ENDPOINT
REPO = Path(__file__).resolve().parents[3]
BRIEF = REPO / "briefs" / "balboa-32u4.md"
RUN_ID = "run-balboa"
SEED = 11
OPERATOR = "yasin"
DECOMPOSITION = "claude-sonnet-5"
REVIEWER = "claude-opus-5-5"
ROLES = ("control", "firmware")
#: The instant the record's clock starts from, in every run this rig makes.
START = datetime(2026, 11, 15, 8, 0, 0, tzinfo=UTC)

#: The plan's two modules, by name, role and what each builds.
MODULES = (
    (
        "balance",
        "control",
        "Design the balance controller for the brief's criteria 8 and 15 to 19.",
    ),
    ("firmware", "firmware", "Write the balance firmware for the brief's criteria 9 to 14."),
)
#: The robot's parts, as the stand-in decomposition lists them.
GEARMOTORS = Component(
    node="electrical.gearmotors",
    domain="electrical",
    role="control",
    label="Drive gearmotors, 50:1 Micro Metal HPCB 6V",
    own=("mass", "stall_current"),
    shared=(),
)
BUMPER = Component(
    node="mechanical.bumper_cage",
    domain="mechanical",
    role="control",
    label="Bumper cage",
    own=("mass",),
    shared=(),
)
DRIVER = Component(
    node="electrical.motor_driver",
    domain="electrical",
    role="control",
    label="Motor driver, DRV8838",
    own=(),
    shared=(),
)
IMU = Component(
    node="firmware.imu",
    domain="firmware",
    role="firmware",
    label="Inertial sensor, LSM6DS33",
    own=(),
    shared=(),
)
CELLS = Component(
    node="electrical.cells",
    domain="electrical",
    role="control",
    label="Six AA NiMH cells",
    own=("energy_capacity",),
    shared=(),
)
ENCODERS = Component(
    node="electrical.encoders",
    domain="electrical",
    role="control",
    label="Wheel encoders",
    own=(),
    shared=(),
)
COMPONENTS = (GEARMOTORS, BUMPER, DRIVER, IMU, CELLS, ENCODERS)

#: What the person states, as the command's flags: the one part they have, the one they make.
HAVE = ("--declare", "mass=0.0095:kg", "--declare", "stall_current=1.6:A")
MAKE_TEXT = "printed in PETG, walls at least 2 mm"
MAKE = ("--declare", "mass=0.012:kg", "--text", MAKE_TEXT)


class Clock:
    """The record's clock, a tick per reading from :data:`START`, the same in every run."""

    TICK = timedelta(milliseconds=1)

    def __init__(self) -> None:
        self.now = START

    def reading(self) -> datetime:
        found = self.now
        self.now += self.TICK
        return found


@contextmanager
def ticking(monkeypatch: pytest.MonkeyPatch) -> Iterator[Clock]:
    """Every ``utc_now`` of the orchestrator reads a fresh :class:`Clock` within the block.

    Every commit the orchestrator makes is dated :data:`START` as well. A commit's id carries its
    time, and a part's item names the specification commit, so an item made a second later would
    be another line, with another digest for the person's decision to bind to.
    """
    clock = Clock()

    class _Ticking(datetime):
        @classmethod
        def now(cls, tz: Any = None) -> Any:  # noqa: ANN401 - as ``datetime.now``
            return clock.reading()

    dated = START.strftime("%Y-%m-%dT%H:%M:%S+0000")
    with monkeypatch.context() as patch:
        patch.setattr(common, "datetime", _Ticking)
        patch.setitem(orchestrator_git._ENV, "GIT_AUTHOR_DATE", dated)
        patch.setitem(orchestrator_git._ENV, "GIT_COMMITTER_DATE", dated)
        yield clock


def models() -> ModelStrings:
    return ModelStrings(
        decomposition=DECOMPOSITION,
        roles=dict.fromkeys(ROLES, DECOMPOSITION),
        reviewers=dict.fromkeys(ROLES, REVIEWER),
    )


def brief_sha256() -> str:
    return hashlib.sha256(BRIEF.read_bytes()).hexdigest()


def config(repo: Path, run_id: str = RUN_ID) -> RunConfig:
    """The run's configuration: it asks about parts, acts on decisions, inside the OS layer."""
    return observe_rig.config(
        run_id,
        repo,
        "control",
        seed=SEED,
        brief_sha256=brief_sha256(),
        models=models(),
        parts_on_hand="on",
        queue_decisions="act",
        os_layer=PRESENT,
    )


def module_dirs(seed: int) -> dict[str, str]:
    """Each planned subtask's id and its module's directory."""
    return {mint_id(seed, i, name): f"modules/{name}" for i, (name, _, _) in enumerate(MODULES)}


def _interface() -> Node:
    return Node.model_validate(
        {
            "id": "iface.motor_supply",
            "kind": "interface",
            "domain": "control",
            "owner_role": "control",
            "quantities": {
                "v_bus": {"value": 7.2, "unit": "V", "source": "brief", "written_by": "control"}
            },
            "requirements": [],
            "constrains": [],
            "model": None,
            "geometry_hash": "sha256:0",
            "updated": "2026-11-15T00:00:00Z",
        }
    )


def plan() -> PartsPlan:
    """The stand-in decomposition's answer on the reference brief."""
    return PartsPlan(
        modules=tuple(
            PlannedModule(name=name, role=role, module_dir=f"modules/{name}", spec=spec)
            for name, role, spec in MODULES
        ),
        interface_nodes=(_interface(),),
        components=COMPONENTS,
    )


def outcome(run_dir: Path) -> Outcome:
    """The call's outcome, its stream written where the call writes it and sealed."""
    stream = run_dir / "decomposition" / "stdout.jsonl"
    stream.parent.mkdir(parents=True, exist_ok=True)
    message = {"id": "m1", "model": DECOMPOSITION, "content": []}
    stream.write_text(
        json.dumps({"type": "assistant", "message": message})
        + "\n"
        + json.dumps({"type": "result", "subtype": "success", "num_turns": 1})
        + "\n"
    )
    return Outcome(
        session_id="decomposition-stand-in",
        ok=True,
        cause=None,
        detail="a plan",
        plan=plan(),
        usage=(MessageUsage(message_id="d1", usage=_usage(100)),),
        model=DECOMPOSITION,
        num_turns=1,
        stream_seal=seal(stream.read_bytes()),
    )


def _usage(tokens: int) -> Usage:
    return Usage(
        input_tokens=tokens,
        output_tokens=tokens // 10,
        cache_read_input_tokens=0,
        cache_creation_input_tokens=0,
    )


def _node(node_id: str, role: str) -> dict[str, Any]:
    return {
        "id": node_id,
        "kind": "component",
        "domain": role,
        "owner_role": role,
        "quantities": {
            "current_draw": {"value": 0.05, "unit": "A", "source": "datasheet", "written_by": role}
        },
        "requirements": [],
        "constrains": [],
        "model": None,
        "geometry_hash": "sha256:0",
        "updated": "2026-11-15T00:00:00Z",
    }


@dataclass
class StandInSession:
    """Writes one node of the session's own role into its worktree; the orchestrator commits it.

    Every request it is handed is kept, so a test can see what each session was given to read.
    """

    layout: RunGit
    requests: list[SessionRequest] = field(default_factory=list)

    def environment(self) -> None:
        return None

    def stop_leftovers(self) -> list[Leftover]:
        return []

    def end_leftovers(self) -> None:
        return None

    def run(self, request: SessionRequest, on_spawn: SpawnHook | None = None) -> SessionReport:
        self.requests.append(request)
        role = request.assigned_role
        worktree = self.layout.open_subtask(request.subtask_id)
        module = worktree / request.module_dir
        module.mkdir(parents=True, exist_ok=True)
        (module / "design.py").write_text(f"# stand-in {role} session, attempt {request.attempt}\n")
        node_id = f"{role}.{request.module_dir.rsplit('/', 1)[-1]}_stage"
        proposal = worktree / ".physgate" / "proposals" / f"{node_id}.json"
        proposal.parent.mkdir(parents=True, exist_ok=True)
        proposal.write_text(json.dumps(_node(node_id, role)))
        sid = f"stand-in-{request.subtask_id}-{request.attempt}"
        stream = self.layout.run_dir / "sessions" / sid / "stdout.jsonl"
        stream.parent.mkdir(parents=True, exist_ok=True)
        stream.write_text(json.dumps({"type": "result", "session_id": sid}) + "\n")
        commit = commit_attempt(
            worktree, request.subtask_id, request.attempt, sid, repo=self.layout.repo
        )
        return SessionReport(
            session_id=sid,
            end=SessionEnd(outcome="completed", cause=None),
            attempt_commit=commit,
            trajectory=str(stream),
            trajectory_seal=seal(stream.read_bytes()),
            worktree=str(worktree),
            reading_verified=True,
            node_files_halted=False,
            usage=(MessageUsage(message_id=f"{sid}-m1", usage=_usage(1000)),),
        )


def start(root: Path, cfg: RunConfig, repo: Path) -> Path:
    """Start the run from the stand-in answer, as ``decompose`` does; its parts' items listed."""
    run_dir = root / cfg.run_id
    start_run(
        outcome(run_dir),
        config=cfg,
        run_dir=run_dir,
        target_repo=repo,
        library=build_fixture_library(root / "library"),
        brief=BRIEF.read_text(),
    ).close()
    return run_dir


def drive(
    root: Path, cfg: RunConfig, repo: Path, requests: list[SessionRequest] | None = None
) -> tuple[str, list[SessionRequest]]:
    """One process drives the run, as ``physgate run`` does: the step it ends on, the requests.

    Each request a session is handed is kept in ``requests`` as it is handed over.
    """
    run_dir = root / cfg.run_id
    run = RunGit(repo=repo, run_dir=run_dir, run_id=cfg.run_id)
    keeper = StoreKeeper(run, run_dir / "store")
    session = StandInSession(run, [] if requests is None else requests)
    loop = Loop(
        config=cfg,
        run_dir=run_dir,
        gate=PhysicsGate(),
        reviewers={
            role: observe_rig.Reviewer(model=model, ids=role)
            for role, model in cfg.models.reviewers.items()
        },
        dispatcher=session,
        changes=GitChangeChecker(run, run_dir / "store", module_dirs(cfg.seed)),
        merger=GitMerger(run, removal_timeout_s=60.0),
        graph=keeper,
        escalation=bind("rules"),
        material=CanaryCheck(held_out=frozenset(), review_material=frozenset()),
        sleep=lambda _: None,
    )
    # As the command does before it drives: the OS layer where the sessions run, recorded.
    loop.record.emit(OsLayerChecked(**loop.record.envelope(), state=PRESENT, as_recorded=True))
    try:
        step = loop.run()
    finally:
        loop.close()
        keeper.close()
    return step.kind, session.requests


def command(argv: list[str]) -> int:
    """``physgate`` with ``argv``: its exit code."""
    try:
        return main(argv)
    except SystemExit as exc:
        return int(exc.code or 0)


def decide_as_a_person(run_dir: Path) -> None:
    """The person's decisions, through the command: have, make, then find for the rest."""
    view = read_queue(run_dir)
    open_parts = [item.item_id for item in view.open_items() if item.source == "parts"]
    assert len(open_parts) == len(COMPONENTS), open_parts
    for item_id, flags in ((open_parts[0], ("have", *HAVE)), (open_parts[1], ("make", *MAKE))):
        view = read_queue(run_dir)
        code = command(
            ["queue", "resolve", item_id, "--run-dir", str(run_dir), "--choose", flags[0],
             *flags[1:], "--sha256", view.digests[item_id], "--by", OPERATOR]
        )  # fmt: skip
        assert code == 0, item_id
    code = command(
        ["queue", "parts", "--run-dir", str(run_dir), "--find-remaining", "--by", OPERATOR]
    )
    assert code == 0


def decide_as_recorded(recorded: Path, run_dir: Path, recorded_id: str) -> None:
    """The decisions the recorded run's file states, fed back through the one decision function.

    Each line's item is the same part of the re-run (its id under the re-run's run id), decided
    on the re-run's own view of it, by the same person, with the same choice and the same body.
    """
    rerun_id = json.loads((run_dir / "run.json").read_text())["run_id"]
    for raw in (recorded / DECISIONS_NAME).read_text().splitlines():
        line = QueueResolution.model_validate_json(raw)
        assert line.verb is not None, "a recorded decision on a part names its verb"
        item_id = rerun_id + line.item_id.removeprefix(recorded_id)
        view = read_queue(run_dir)
        record_decision(
            run_dir,
            item_id,
            person=PersonDecision(
                verb=line.verb, note=line.note, position=line.position, parts=line.parts
            ),
            resolved_by=line.resolved_by,
            shown=ShownItem(
                item_sha256=view.digests[item_id], trajectories=statuses_now(run_dir, item_id)
            ),
        )


@dataclass(frozen=True)
class Made:
    """A run this rig made: where it is, the step each process ended on, what sessions read."""

    run_dir: Path
    repo: Path
    steps: tuple[str, str]
    requests: tuple[SessionRequest, ...]


def made(
    monkeypatch: pytest.MonkeyPatch,
    root: Path,
    cfg: RunConfig,
    repo: Path,
    decide: Callable[[Path], None],
) -> Made:
    """Start the run, drive it to its parts' hold, ``decide``, then drive it to its end.

    A process that raises ends on the step ``raised <its error>``, so a row asserts on how the
    run ended rather than erroring before it can say.
    """
    with ticking(monkeypatch):
        run_dir = start(root, cfg, repo)
        held, _ = drive(root, cfg, repo)
        decide(run_dir)
        requests: list[SessionRequest] = []
        try:
            ended, requests = drive(root, cfg, repo, requests)
        except Exception as exc:  # noqa: BLE001 - how the run ended is what a row asserts on
            ended = f"raised {type(exc).__name__}: {exc}"
    return Made(run_dir, repo, (held, ended), tuple(requests))


def recorded_run(monkeypatch: pytest.MonkeyPatch, root: Path) -> Made:
    """The run on the reference brief, with a target repository of its own."""
    repo = observe_rig.target_repo(root)
    return made(monkeypatch, root / "runs", config(repo), repo, decide_as_a_person)


def clone_at(repo: Path, head: str, where: Path) -> Path:
    """A clone of ``repo``'s master, at the same commit and holding none of its run branches."""
    subprocess.run(
        ["git", "clone", "-q", "--single-branch", "-b", "master", str(repo), str(where)],
        check=True,
        capture_output=True,
    )
    assert observe_rig.git(where, "rev-parse", "HEAD").strip() == head
    return where


def rerun_from_config(monkeypatch: pytest.MonkeyPatch, recorded: Made, root: Path) -> Made:
    """The run made again from its recorded configuration alone, and the recorded decisions."""
    cfg = load_run_config(recorded.run_dir / "run.json")
    assert hashlib.sha256(BRIEF.read_bytes()).hexdigest() == cfg.brief_sha256
    repo = clone_at(recorded.repo, cfg.target_head, root / "target")
    return made(
        monkeypatch,
        root / "runs",
        cfg,
        repo,
        lambda run_dir: decide_as_recorded(recorded.run_dir, run_dir, cfg.run_id),
    )


def driven_once_more(monkeypatch: pytest.MonkeyPatch, run: Made) -> str:
    """A further process drives the run, as ``physgate run`` would again: the step it ends on."""
    cfg = load_run_config(run.run_dir / "run.json")
    with ticking(monkeypatch):
        try:
            step, _ = drive(run.run_dir.parent, cfg, run.repo)
        except Exception as exc:  # noqa: BLE001 - how the process ended is what a row asserts on
            step = f"raised {type(exc).__name__}: {exc}"
    return step
