"""Stand-ins for a baseline round: a tier-set store, harness runs on its tasks, and a raw arm.

The store is written by the real split from a pool of fixture tasks, each with a brief of its
own, so every run's task is found by its brief. Each harness run is laid out as the loop and
the hook installer leave one: its configuration, an event log that ended, and a role session's
generated settings. The raw arm stand-in leaves what :func:`.arms.raw.run_raw` leaves (its
record, its stream, its generated settings and its answer), with every pin taken from the
setup it is given, so a pair differs only where a row makes it differ.
"""

from __future__ import annotations

import hashlib
import json
import shutil
import sys
from collections.abc import Callable
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

PER_ROLE_TESTS = Path(__file__).resolve().parents[1] / "per_role"
if str(PER_ROLE_TESTS) not in sys.path:
    sys.path.insert(0, str(PER_ROLE_TESTS))

from task_fixtures import controller, own_task, write_task_dir  # noqa: E402

from physgate.evaluation.baseline.runner import RunSet, setup_from_run  # noqa: E402
from physgate.evaluation.per_role.arms.raw import RawSetup, held_out_seen, pins  # noqa: E402
from physgate.evaluation.tiers.heldout import tier_digest  # noqa: E402
from physgate.evaluation.tiers.store import (  # noqa: E402
    withheld_root,
    work_root,
    write_version,
)
from physgate.evaluation.tiers.task import Role, Task, canonical_json, parse_task  # noqa: E402
from physgate.hooks.settings import CONFIG_NAME, PROFILE_TOOLS  # noqa: E402
from physgate.orchestrator.binaries import measure  # noqa: E402
from physgate.orchestrator.credentials import Credential  # noqa: E402
from physgate.orchestrator.events import (  # noqa: E402
    EventLog,
    IntegrationGateSkipped,
    RunStarted,
    TokensUsed,
)
from physgate.orchestrator.protocols import Usage  # noqa: E402
from physgate.orchestrator.run_config import RunConfig  # noqa: E402
from physgate.oslayer.probe import Present  # noqa: E402

EXAMPLES = Path(__file__).parents[4] / "src/physgate/orchestrator/examples"
MODEL = "claude-opus-5-5"
LAYER = Present(mechanism="bubblewrap", claude_version="2.1.301")
TIERS = ("visible", "validation", "held_out")
SCORED = {"passed": True, "flags": {"no_gain_crossover": True}, "specs": []}
PRICES = "2026-10-16"
#: The stand-in for the session binary: a file of the suite's own, measured as the command
#: measures the binary it runs, so the harness runs record the build the raw session is given.
BINARY = Path(__file__).resolve()
BUILT = measure(str(BINARY))


@dataclass(frozen=True)
class StandInStore:
    """A store with one version of the control role's tiers, and what the fixture put in it."""

    store: Path
    version: str
    #: Each tier's tasks, read back from the fixture's own version.
    tasks: dict[str, list[Task]]
    #: The canaries of the version's protected tiers, which a run on the store looks for.
    canaries: tuple[str, ...]
    #: The roots a run on the store withholds.
    held_out: tuple[str, ...]


def marker(i: int) -> str:
    """The string fixture task ``i`` carries in every field but its brief (``marked`` stores)."""
    return f"zqmark{i:02d}zq"


def _marked(i: int) -> dict[str, Any]:
    """Task ``i``'s fields other than its brief, each carrying :func:`marker`."""
    task = own_task()
    for spec in task["specs"]:
        spec["name"] = f"{marker(i)}_{spec['name']}"
        spec["composes"] = [f"{marker(i)}_{req}" for req in spec["composes"]]
    return {"id": f"control.{marker(i)}", "specs": task["specs"]}


def stand_in_store(root: Path, *, marked: bool = False) -> StandInStore:
    """Twenty-four fixture tasks, each with its own brief, split into one version.

    ``marked``: every field of task ``i`` but its brief carries :func:`marker` ``(i)``, so
    what of a task reached a place can be found by a plain search.
    """
    store = root.resolve() / "store"
    pool = store / "control" / "withheld" / "pool"
    for i in range(24):
        fields = _marked(i) if marked else {"id": f"control.t{i:02d}"}
        slow = f"{marker(i)}_settling" if marked else "settling"
        write_task_dir(
            pool / str(fields["id"]),
            own_task(**fields, brief=f"Stabilise plant number {i}. Answer here."),
            {"good": (controller(), None), "bad_slow": (controller(), slow)},
        )
    chosen = sorted(p for p in pool.iterdir() if p.is_dir())
    manifest, _ = write_version(
        store / "control",
        chosen,
        role="control",
        seed=5,
        model="claude-sonnet-5",
        runtime="2.1.301",
        provenance=canonical_json({"sessions": [{"session_id": "s-1", "end": "ended"}]}),
        retire=pool,
        generated="2026-11-08",
    )
    directory = store / "control" / manifest.version
    tasks = {
        tier: [
            parse_task((d / "task.json").read_bytes())
            for d in sorted((directory / tier).iterdir())
            if d.is_dir()
        ]
        for tier in TIERS
    }
    canaries = tuple(
        c
        for tier in TIERS[1:]
        for c in json.loads((directory / tier / "canaries.json").read_text())
    )
    held_out = (
        str(withheld_root(store, "control")),
        str(work_root(store, "control")),
        *(str(directory / tier) for tier in TIERS[1:]),
    )
    return StandInStore(store, manifest.version, tasks, canaries, held_out)


def copied(made: StandInStore, copy: Path) -> StandInStore:
    """``made``'s store copied to ``copy``, so a row's round leaves its records there."""
    shutil.copytree(made.store, copy, symlinks=True)
    old, new = str(made.store), str(copy)
    return StandInStore(
        copy,
        made.version,
        made.tasks,
        made.canaries,
        tuple(h.replace(old, new) for h in made.held_out),
    )


def config(task: Task, made: StandInStore, **changes: Any) -> RunConfig:  # noqa: ANN401
    """A reportable harness run's configuration, given ``task``'s brief, withholding the store."""
    params = json.loads((EXAMPLES / "params.subscription.json").read_text())
    params.update(
        run_id="r",
        seed=1,
        brief_sha256=hashlib.sha256(task.brief.encode()).hexdigest(),
        target_head="b" * 40,
        claude_version="2.1.301",
        endpoint="default",
        reportable=True,
        harness={"commit": "c" * 40, "clean": True, "uncommitted_sha256": None},
        git_binary=None,
        # As the command records them: the bytes it measured, and the account by its name and
        # the fingerprint of the credential it was given.
        binary=BUILT.model_dump(),
        account={"name": params["account"], "token_sha256_prefix": "e" * 12},
        os_layer=LAYER.model_dump(),
        network="none",
        network_enforced=True,
        held_out=list(made.held_out),
        held_out_sha256=[tier_digest(Path(root)) for root in made.held_out],
        held_out_canaries=list(made.canaries),
    )
    params["models"]["roles"]["control"] = MODEL
    params.update(changes)
    return RunConfig.model_validate_json(json.dumps(params))


def harness_run(
    root: Path, task: Task, made: StandInStore, *, ended: bool = True, **changes: Any
) -> Path:
    """A harness run on ``task`` that spent 1000 tokens and, unless ``ended`` is false, ended."""
    run_dir = root / f"run-{hashlib.sha256(task.id.encode()).hexdigest()[:8]}"
    while run_dir.exists():
        run_dir = run_dir.with_name(run_dir.name + "x")
    run_dir.mkdir(parents=True)
    (run_dir / "run.json").write_text(config(task, made, **changes).model_dump_json())
    log = EventLog(run_dir / "events.jsonl", run_id="r", gate_mode="on")
    log.append(RunStarted(**log.envelope(), config_sha256="0" * 64))
    usage = Usage(
        input_tokens=100,
        output_tokens=200,
        cache_read_input_tokens=600,
        cache_creation_input_tokens=100,
    )
    log.append(
        TokensUsed(**log.envelope(), attribution="session:role-1", message_id="m1", usage=usage)
    )
    if ended:
        log.append(IntegrationGateSkipped(**log.envelope(), reason="nothing_planned", subtasks=()))
    log.close()
    settings = run_dir / "sessions" / "role-1" / "session"
    settings.mkdir(parents=True)
    body = {"profile": "role", "role": "control", "tools_allowed": list(PROFILE_TOOLS["role"])}
    (settings / CONFIG_NAME).write_text(json.dumps(body))
    return run_dir


def run_set(*runs: tuple[Path, int]) -> RunSet:
    """The run set naming each harness run by its directory and trial number."""
    trials = [{"run_dir": str(r), "trial": t} for r, t in runs]
    return RunSet.model_validate_json(json.dumps({"format": 1, "trials": trials}))


def setup_for(config: RunConfig, role: Role) -> RawSetup:
    """The raw arm's setup from the harness run's record, on a machine like the run's."""
    return setup_from_run(
        config,
        role,
        binary=str(BINARY),
        credential=Credential(mode="subscription", secret="not-a-token"),
        install_bin=Path("/nowhere/bin/physgate"),
        os_layer=LAYER,
        role_python=None,
        base_url=None,
    )


@dataclass
class StandInArm:
    """The raw arm, leaving what it leaves; a row changes one thing it does."""

    #: Per call (from 1): a result the session ended on instead of answering.
    ended: dict[int, dict[str, Any]] = field(default_factory=dict)
    #: Per call: a model that answered instead of the pinned one.
    answered: dict[int, str] = field(default_factory=dict)
    #: Per call: a held-out canary seen in the stream.
    seen: set[int] = field(default_factory=set)
    #: Per call: an error the arm raises.
    raises: dict[int, Exception] = field(default_factory=dict)
    calls: list[tuple[str, int, Path]] = field(default_factory=list)
    #: Called with the session's place and the harness's directory once the session has
    #: ended and before the arm writes its own files: what a session could have left.
    left: Callable[[Path, Path], None] | None = None

    def __call__(
        self, task: Task, setup: RawSetup, work: Path, *, cap: int, harness: Path | None = None
    ) -> dict[str, Any]:
        self.calls.append((task.id, cap, work))
        n = len(self.calls)
        if n in self.raises:
            raise self.raises[n]
        work.mkdir(parents=True)
        session = work / "session"
        (session / "session").mkdir(parents=True)
        installed = {"profile": "baseline", "role": None}
        installed["tools_allowed"] = list(PROFILE_TOOLS["baseline"])  # type: ignore[assignment]
        (session / "session" / CONFIG_NAME).write_text(json.dumps(installed))
        model = self.answered.get(n, setup.model)
        usage = {
            "input_tokens": 300,
            "output_tokens": 100,
            "cache_read_input_tokens": 0,
            "cache_creation_input_tokens": 0,
        }
        result = self.ended.get(n, {"is_error": False, "terminal_reason": "completed"})
        content = f"tool output {task.canary}" if n in self.seen else "tool output"
        lines = [
            {"type": "assistant", "message": {"id": "m", "model": model, "usage": usage}},
            {"type": "user", "message": {"content": content}},
            {"type": "result", "session_id": f"s-{n}", **result},
        ]
        stream = session / "stdout.jsonl"
        stream.write_text("".join(json.dumps(line) + "\n" for line in lines))
        kept = work if harness is None else harness
        if self.left is not None:
            self.left(work, kept)
        answered = n not in self.ended
        if answered:
            (kept / "answer").mkdir()
            (kept / "answer" / task.answer.path).write_text(json.dumps(controller()))
        record: dict[str, Any] = {
            "session_id": f"s-{n}",
            "end": "ended",
            "exit_code": 0 if answered else 1,
            "left_running": [],
            "wall_clock_s": 12.0,
            "tokens": 400,
            "cap": cap,
            "answered_by": [model],
            "held_out_seen": held_out_seen(stream, setup.held_out_canaries),
            "watch_failure": None,
            "sentinel_after_stop": None,
            "task": task.id,
            "answer": "found" if answered else "no_answer",
            "pins": pins(task, setup),
        }
        (kept / "raw.json").write_text(json.dumps(record))
        return record
