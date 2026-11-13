"""A protected task reaches its raw session as its brief alone, and its trial rests in the store.

The runner opens the validation and held-out tiers' ``task.json`` to give the raw session a
protected task's brief. Every field of a stand-in task but its brief carries a marker, so a
plain search finds what of a protected task reached a place: the session's prompt, anything the
round wrote outside the store's withheld places, its output, and every error a protected trial
raises. A protected trial is made inside the store's protected places and moved only within
them, so one that fails at any step leaves nothing of itself in a visible place; its work
record names where it lies, and the store refuses the next round until a person has looked.
"""

from __future__ import annotations

import json
import shutil
import traceback
from collections.abc import Callable
from pathlib import Path
from typing import Any

import pytest
from baseline_fixtures import (
    PRICES,
    SCORED,
    StandInArm,
    StandInStore,
    copied,
    harness_run,
    run_set,
    setup_for,
    stand_in_store,
)
from task_fixtures import controller

from physgate.evaluation.baseline import runner
from physgate.evaluation.baseline.record import BASELINE_RECORD, TIERS_RECORD, write_new
from physgate.evaluation.baseline.runner import (
    BASELINE_DIR,
    TRIALS,
    BaselineError,
    RunSet,
    run_baseline,
)
from physgate.evaluation.observe.cost import load_price_sheet
from physgate.evaluation.per_role.arms import raw
from physgate.evaluation.per_role.arms.raw import RawSetup, held_out_seen
from physgate.evaluation.per_role.exceptions import TaskFormatError
from physgate.evaluation.tiers.store import (
    WORKING,
    role_root,
    version_dir,
    withheld_root,
    work_root,
)
from physgate.evaluation.tiers.task import Task
from physgate.hooks.settings import CONFIG_NAME, PROFILE_TOOLS

API_ERROR = {"is_error": True, "terminal_reason": "api_error", "api_error_status": 529}


@pytest.fixture(scope="module")
def made(tmp_path_factory: pytest.TempPathFactory) -> StandInStore:
    return stand_in_store(tmp_path_factory.mktemp("store"), marked=True)


@pytest.fixture
def store(tmp_path: Path, made: StandInStore) -> StandInStore:
    return copied(made, tmp_path / "store")


def _score(task: Task, answer: Path) -> dict[str, Any]:
    assert answer.is_file()
    return dict(SCORED)


def _round(
    made: StandInStore,
    runs: RunSet,
    out: Path,
    arm: Any,
    score: Any = _score,  # noqa: ANN401
) -> None:
    run_baseline(
        store=made.store,
        role="control",
        version=made.version,
        runs=runs,
        out=out,
        setup_for=setup_for,
        score=score,
        prices=load_price_sheet(PRICES),
        arm=arm,
        sleep=lambda _s: None,
    )


def _protected(made: StandInStore) -> list[Task]:
    return made.tasks["validation"] + made.tasks["held_out"]


def _forbidden(made: StandInStore) -> list[str]:
    """Each protected task's marker (its id's tail, in every field but its brief) and canary."""
    tasks = _protected(made)
    found = [t.id.removeprefix("control.") for t in tasks]
    assert all(m.startswith("zqmark") for m in found), "the store is not a marked one"
    return found + [str(t.canary) for t in tasks]


def _withheld(made: StandInStore) -> list[Path]:
    directory = version_dir(made.store, "control", made.version)
    return [withheld_root(made.store, "control"), directory / "validation", directory / "held_out"]


def _files(root: Path) -> dict[Path, bytes]:
    return {p: p.read_bytes() for p in root.rglob("*") if p.is_file() and not p.is_symlink()}


class RecordingSession:
    """``run_session`` as the raw arm calls it: what a session is given, recorded; no binary."""

    def __init__(self) -> None:
        self.given: list[tuple[str, RawSetup]] = []

    def __call__(
        self,
        prompt: str,
        setup: RawSetup,
        work: Path,
        *,
        cap: int,
        files: Any = None,  # noqa: ANN401
        check: Any = None,  # noqa: ANN401
    ) -> dict[str, Any]:
        self.given.append((prompt, setup))
        assert files is None and check is None
        (work / "worktree").mkdir(parents=True)
        (work / "worktree" / "answer.json").write_text(json.dumps(controller()))
        (work / "session" / "session").mkdir(parents=True)
        installed = {"profile": "baseline", "role": None}
        installed["tools_allowed"] = list(PROFILE_TOOLS["baseline"])  # type: ignore[assignment]
        (work / "session" / "session" / CONFIG_NAME).write_text(json.dumps(installed))
        usage = {
            "input_tokens": 300,
            "output_tokens": 100,
            "cache_read_input_tokens": 0,
            "cache_creation_input_tokens": 0,
        }
        n = len(self.given)
        result = {"is_error": False, "terminal_reason": "completed"}
        lines = [
            {"type": "assistant", "message": {"id": "m", "model": setup.model, "usage": usage}},
            {"type": "result", "session_id": f"s-{n}", **result},
        ]
        stream = work / "session" / "stdout.jsonl"
        stream.write_text("".join(json.dumps(line) + "\n" for line in lines))
        return {
            "session_id": f"s-{n}",
            "end": "ended",
            "exit_code": 0,
            "left_running": [],
            "wall_clock_s": 12.0,
            "tokens": 400,
            "cap": cap,
            "answered_by": [setup.model],
            "held_out_seen": held_out_seen(stream, setup.held_out_canaries),
            "watch_failure": None,
            "sentinel_after_stop": None,
        }


def test_a_protected_task_s_other_fields_reach_neither_its_session_nor_a_visible_place(
    tmp_path: Path,
    store: StandInStore,
    monkeypatch: pytest.MonkeyPatch,
    capfd: pytest.CaptureFixture[str],
) -> None:
    """The real raw arm, its session recorded in place of the binary.

    The prompt is the brief, byte for byte; nothing the round wrote outside the withheld places,
    and nothing it printed, holds a protected task's marker or canary. The marker is found
    beneath the withheld root, so the search would have found it anywhere.
    """
    tasks = [t for tier in ("visible", "validation", "held_out") for t in store.tasks[tier]]
    runs = run_set(*((harness_run(tmp_path / "runs", t, store), 0) for t in tasks))
    session = RecordingSession()
    monkeypatch.setattr(raw, "run_session", session)
    before = _files(tmp_path)
    out = tmp_path / "round"
    _round(store, runs, out, raw.run_raw)
    forbidden = _forbidden(store)
    briefs = {t.brief for t in tasks}
    assert len(session.given) == len(tasks) == 24
    for prompt, setup in session.given:
        assert prompt in briefs
        assert not [m for m in forbidden if m in prompt]
        markers = [m for m in forbidden if m.startswith("zqmark")]
        assert not [m for m in markers if m in repr(setup)]
    withheld = _withheld(store)
    written = {
        p: data
        for p, data in _files(tmp_path).items()
        if before.get(p) != data and not any(p.is_relative_to(w) for w in withheld)
    }
    assert {out / TRIALS, out / BASELINE_RECORD, out / TIERS_RECORD} <= set(written)
    for path, data in written.items():
        assert not [m for m in forbidden if m.encode() in data], f"{path} holds a protected task"
    printed = capfd.readouterr()
    assert not [m for m in forbidden if m in printed.out + printed.err]
    beneath = withheld_root(store.store, "control") / BASELINE_DIR
    held = b"".join(p.read_bytes() for p in beneath.rglob("raw.json"))
    assert all(t.id.encode() in held for t in _protected(store)), "the search finds nothing"


STEPS = ["session", "score", "machine", "compare", "assemble"]


def _inject(
    step: str, error: Exception, monkeypatch: pytest.MonkeyPatch, reached: list[str]
) -> tuple[StandInArm, Callable[..., Any]]:
    """A stand-in arm and scorer, with ``error`` raised at ``step`` of the trial."""

    def fail(*_args: Any, **_kwargs: Any) -> Any:  # noqa: ANN401
        reached.append(step)
        raise error

    arm = StandInArm(ended={1: API_ERROR, 2: API_ERROR} if step == "machine" else {})
    if step == "session":
        arm.raises[1] = error
        reached.append(step)
    patched = {"machine": "raw_ended_by_infrastructure", "compare": "differences"}
    patched["assemble"] = "raw_trial"
    if step in patched:
        monkeypatch.setattr(runner, patched[step], fail)
    return arm, fail if step == "score" else _score


@pytest.mark.parametrize("tier", ["validation", "held_out"])
@pytest.mark.parametrize("step", STEPS)
def test_an_error_inside_a_protected_trial_names_its_tier_and_nothing_of_its_task(
    tmp_path: Path, store: StandInStore, monkeypatch: pytest.MonkeyPatch, step: str, tier: str
) -> None:
    """An error from any step is said by the tier: as raised, as printed, and as chained.

    The error raised is one a scorer raises on a task it cannot judge, naming the task and a
    spec, so an error passed on as raised would show a protected task to the operator's log.
    """
    task = store.tasks[tier][0]
    error = TaskFormatError(f"the task {task.id!r} names {task.specs[0].name!r}", task=task.id)
    reached: list[str] = []
    arm, score = _inject(step, error, monkeypatch, reached)
    runs = run_set((harness_run(tmp_path / "runs", task, store), 0))
    with pytest.raises(Exception) as raised:  # noqa: PT011 - the type is asserted below
        _round(store, runs, tmp_path / "round", arm, score)
    assert reached, "the error was never raised"
    shown = "".join(traceback.format_exception(raised.value))
    shown += json.dumps(getattr(raised.value, "context", {}))
    assert not [m for m in _forbidden(store) if m in shown], shown
    assert isinstance(raised.value, BaselineError)
    assert raised.value.context.get("tier") == tier


FAILURES = [
    "session",
    "score",
    "score file",
    "machine",
    "compare",
    "assemble",
    "move",
    "move after a machine end",
    "record removal",
    "trial line",
]


def _fail_at(
    step: str, monkeypatch: pytest.MonkeyPatch, reached: list[str]
) -> tuple[StandInArm, Callable[..., Any]]:
    """A stand-in arm and scorer, with the trial failing at ``step``."""
    error = OSError(f"injected at {step}")
    if step in STEPS:
        return _inject(step, error, monkeypatch, reached)
    arm = StandInArm(ended={1: API_ERROR} if step == "move after a machine end" else {})
    if step == "score file":

        def no_score(path: Path, data: bytes) -> None:  # the round's records still written
            if path.name == runner.SCORE:
                reached.append(step)
                raise error
            write_new(path, data)

        monkeypatch.setattr(runner, "write_new", no_score)
    elif step.startswith("move"):

        def midway(src: str, dst: str) -> None:
            """One file copied, then the move stops: the work is in both places, or neither."""
            reached.append(step)
            first = next(p for p in sorted(Path(src).rglob("*")) if p.is_file())
            Path(dst).mkdir(parents=True)
            (Path(dst) / first.name).write_bytes(first.read_bytes())
            raise error

        monkeypatch.setattr(shutil, "move", midway)
    elif step == "record removal":
        unlink = Path.unlink

        def kept(path: Path, missing_ok: bool = False) -> None:  # noqa: FBT001, FBT002
            if path.name.endswith(WORKING):
                reached.append(step)
                raise error
            unlink(path, missing_ok=missing_ok)

        monkeypatch.setattr(Path, "unlink", kept)
    elif step == "trial line":

        def no_line(*_args: Any) -> None:  # noqa: ANN401
            reached.append(step)
            raise error

        monkeypatch.setattr(runner, "_append", no_line)
    return arm, _score


#: Steps past which the trial is whole beneath the withheld root and its record is cleared.
SECURED = {"trial line"}
#: Steps at which no raw session has run, so the trial has written nothing yet.
NOT_RUN = {"session"}


def _paths(root: Path) -> set[Path]:
    return set(root.rglob("*"))


def _protected_places(made: StandInStore) -> list[Path]:
    """The store's places every run withholds: the withheld and work roots, the tiers."""
    return [*_withheld(made), work_root(made.store, "control")]


@pytest.mark.parametrize("step", [*FAILURES, "place taken", "interrupt"])
def test_a_protected_trial_that_fails_at_any_step_never_rests_in_a_visible_place(
    tmp_path: Path, store: StandInStore, monkeypatch: pytest.MonkeyPatch, step: str
) -> None:
    """Whatever step fails, nothing of a held-out trial is outside the store's protected places.

    The round's directory is listed and held to what it must hold (nothing, the round being
    one held-out trial), and so is everything new outside the protected places (the work
    record alone, in the role's root, until the trial is secured). The trial's own files are
    found inside the protected places, so the listings are not empty for want of a trial; and
    the work record names a place inside them, which the next round refuses as leftovers.
    """
    task = store.tasks["held_out"][0]
    runs = run_set((harness_run(tmp_path / "runs", task, store), 0))
    out = tmp_path / "round"
    reached: list[str] = []
    if step == "place taken":
        monkeypatch.setattr(runner.secrets, "token_hex", lambda _n: "f" * 16)
        place = withheld_root(store.store, "control") / BASELINE_DIR / ("f" * 16) / "0000-1"
        place.mkdir(parents=True)
        arm, score = StandInArm(), _score
        reached.append(step)
    elif step == "interrupt":

        def interrupted(_task: Task, _answer: Path) -> dict[str, Any]:
            reached.append(step)
            raise KeyboardInterrupt

        arm, score = StandInArm(), interrupted
    else:
        arm, score = _fail_at(step, monkeypatch, reached)
    before = _paths(tmp_path)
    with pytest.raises(BaseException):  # noqa: B017, PT011 - any failure; where the work is, is asserted
        _round(store, runs, out, arm, score)
    monkeypatch.undo()
    assert reached, "the failure was never injected"
    places = _protected_places(store)
    records = set(role_root(store.store, "control").glob(f"*{WORKING}"))
    new_outside = {
        p for p in _paths(tmp_path) - before if not any(p.is_relative_to(w) for w in places)
    }
    assert {p.relative_to(out) for p in _paths(out)} == set(), "the round's directory holds a trial"
    # The round's directory, made empty before any trial, and the record: nothing else.
    assert new_outside == {out} | records, sorted(map(str, new_outside - records - {out}))
    kept = [p for w in places for p in w.rglob("raw.json")]
    assert step in NOT_RUN or kept, "the trial's files are nowhere: the listings prove nothing"
    again = StandInArm()
    if step in SECURED:
        assert records == set()
        _round(store, runs, tmp_path / "again", again)
        assert again.calls
        return
    (record,) = records
    work = Path(json.loads(record.read_text())["work"])
    assert any(work.is_relative_to(w) for w in places), f"the record names {work}"
    with pytest.raises(BaselineError) as refused:
        _round(store, runs, tmp_path / "again", again)
    assert refused.value.context.get("refused_because") == "work_left"
    assert again.calls == []


def test_a_protected_trial_refused_before_its_session_leaves_no_record_of_work(
    tmp_path: Path, store: StandInStore
) -> None:
    """A setup that cannot be made (no credential, another binary) leaves the store open.

    The refusal comes before any session and any work, so no record of work out of the role's
    root is left to refuse the next round until a person removes it.
    """
    task = store.tasks["held_out"][0]
    runs = run_set((harness_run(tmp_path / "runs", task, store), 0))

    def no_credential(_config: Any, _role: str) -> RawSetup:  # noqa: ANN401
        msg = "the credential variable is not set"
        raise BaselineError(msg)

    arm = StandInArm()
    with pytest.raises(BaselineError, match="the credential variable is not set"):
        run_baseline(
            store=store.store,
            role="control",
            version=store.version,
            runs=runs,
            out=tmp_path / "round",
            setup_for=no_credential,
            score=_score,
            prices=load_price_sheet(PRICES),
            arm=arm,
            sleep=lambda _s: None,
        )
    assert arm.calls == []
    assert list(role_root(store.store, "control").glob(f"*{WORKING}")) == []
    again = StandInArm()
    _round(store, runs, tmp_path / "again", again)
    assert len(again.calls) == 1
