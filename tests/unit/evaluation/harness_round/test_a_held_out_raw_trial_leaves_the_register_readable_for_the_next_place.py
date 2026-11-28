"""A held-out raw trial leaves the register readable, and its exposure read, for the next place.

A protected trial's whole directory is moved beneath the role's withheld root once it is
recorded (``withheld/baseline/<round>/<iiii>-<n>/``): the harness's directory, where its raw
record lies, and beside it the session's own place, which holds whatever the session and its
client made, as deep as they made it. The client alone nests its caches and the sentinel's
records nine and ten directories beneath that root. So the register's walk does not enter a raw
trial's place, as it enters nothing inside a run: the next harness place of the cell starts. What
the session showed is not lost by it: the session's stream was scanned for the held-out canaries
into the raw record beside the place, which is read, so a session that showed one still marks its
version exposed and the next place is refused for that. A place a kill left, with no record yet,
is not entered either; and a directory named as a place with no harness's directory beside it is
no trial's, and is walked as any other.

Both arms on the rig, the harness round its real driver, the raw trial the baseline's own runner
with the stand-in arm, which leaves in the session's place the tree a real raw session's client
left in a practice round, by the same names.
"""

from __future__ import annotations

import json
import os
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import pytest
from round_rig import PRICES, SCORED, Rig, StandInArm, make_rig, setup_for
from test_the_two_arms_wait_for_the_usage_limit_alike_and_count_a_pair_once import _installed

from physgate.evaluation.baseline.runner import BaselineError, RunSet, run_baseline
from physgate.evaluation.harness_round import RoundError, run_round
from physgate.evaluation.observe.cost import load_price_sheet
from physgate.evaluation.per_role.arms.raw import RawSetup
from physgate.evaluation.per_role.exceptions import PerRoleError
from physgate.evaluation.tiers import exposure
from physgate.evaluation.tiers.store import BASELINE_DIR, PLACE, withheld_root
from physgate.evaluation.tiers.task import Task

#: The session id a real client names its records by, and a canary-free file it writes.
SESSION_ID = "ae42bd8c-0bbd-41b7-a872-b5512f034641"


def _score(_task: Any, _answer: Path) -> dict[str, Any]:  # noqa: ANN401
    return dict(SCORED)


def _client_tree(work: Path, said: str = "") -> None:
    """What a real raw session's client leaves in its place, by the names it uses.

    Its project folders are named from the worktree's path, every ``/`` a ``-``, as the client
    names them. ``said`` is written in the deepest file, where a session's tool server logs.
    """
    project = str(work / "worktree").replace("/", "-")
    session = work / "session"
    logs = session / "home" / "Library" / "Caches" / "claude-cli-nodejs" / project
    for server in ("mcp-logs-control", "mcp-logs-mujoco"):
        (logs / server).mkdir(parents=True)
        (logs / server / "log.txt").write_text(f"started {said}".strip())
    (session / "state" / "sessions" / SESSION_ID / "sentinel" / "blobs").mkdir(parents=True)
    (session / "config" / "projects" / project / "memory").mkdir(parents=True)
    (work / "worktree" / ".git" / "objects" / "pack").mkdir(parents=True)


def _deepest(root: Path) -> int:
    """How many directories deep the deepest one lies beneath ``root``."""
    return max(len(Path(here).relative_to(root).parts) for here, _dirs, _files in os.walk(root))


def _first_place(rig: Rig) -> RunSet:
    """The cell's first place taken on alone, and its one-entry set, which the raw pair runs."""
    status, summary = _place(rig, 0)
    assert status == "trial_assembled", summary
    runs = RunSet.model_validate_json(Path(summary["trial"]["runs"]).read_bytes())
    for entry in runs.trials:
        _installed(Path(entry.run_dir))
    return runs


def _place(rig: Rig, only: int) -> tuple[str, dict[str, Any]]:
    return run_round(
        rig.inputs(tiers=("held_out",), trials=1, tasks=2, seed_base=1, order_seed=1124),
        driver=rig.driver(),
        scorer=_score,
        sleep=lambda _: None,
        only=only,
        resume=only > 0,
    )


def _next_place(rig: Rig) -> tuple[str, dict[str, Any]] | RoundError:
    try:
        return _place(rig, 1)
    except RoundError as exc:
        return exc


def _raw(rig: Rig, runs: RunSet, arm: Callable[..., dict[str, Any]], **how: Any) -> Any:  # noqa: ANN401
    try:
        return run_baseline(
            store=rig.made.store,
            role="control",
            version=rig.made.version,
            runs=runs,
            out=rig.root / "raw",
            setup_for=setup_for,
            score=_score,
            prices=load_price_sheet(PRICES),
            arm=arm,
            sleep=lambda _s: None,
            **how,
        )
    except BaselineError as exc:
        return exc


def _baseline(rig: Rig) -> Path:
    return withheld_root(rig.made.store, "control") / BASELINE_DIR


def _read(rig: Rig) -> dict[str, frozenset[str]] | PerRoleError:
    try:
        return exposure.exposure_sources(rig.made.store, "control")
    except PerRoleError as exc:
        return exc


@pytest.fixture
def rig(tmp_path_factory: pytest.TempPathFactory) -> Rig:
    # A directory of its own, not named after the row: a run root's path names nothing it holds.
    return make_rig(tmp_path_factory.mktemp("rig"))


def test_the_next_place_starts_once_a_held_out_raw_trial_lies_deep_beneath_the_withheld_root(
    rig: Rig,
) -> None:
    runs = _first_place(rig)
    raw = _raw(rig, runs, StandInArm(left=lambda work, _harness: _client_tree(work)))
    assert not isinstance(raw, BaselineError), raw.context
    (trial,) = [p.parent for p in _baseline(rig).glob(f"*/*/{PLACE}")]
    assert (trial / "harness" / "raw.json").is_file(), "the trial lies where the runner puts it"
    assert _deepest(_baseline(rig)) > exposure.MOST_DEPTH, "the row's tree is as deep as a real one"
    after = _next_place(rig)
    assert not isinstance(after, RoundError), after.context
    # The cell's last place: assembled, the round ends.
    assert after[0] == "done", after
    read = _read(rig)
    assert not isinstance(read, PerRoleError), read.context
    assert rig.made.version not in read


def test_a_canary_the_session_showed_while_it_wrote_deep_still_marks_its_version_exposed(
    rig: Rig,
) -> None:
    runs = _first_place(rig)
    arm = StandInArm(seen={1})

    def leave(work: Path, _harness: Path) -> None:
        # The trial's own task's canary, which the stand-in session also shows in its stream.
        (task,) = [t for t in rig.made.tasks["held_out"] if t.id == arm.calls[-1][0]]
        assert task.canary is not None, "a held-out task has a canary"
        _client_tree(work, said=task.canary)

    arm.left = leave
    _raw(rig, runs, arm)
    (record,) = _baseline(rig).glob("*/*/harness/raw.json")
    assert json.loads(record.read_bytes())["held_out_seen"] is True
    read = _read(rig)
    assert not isinstance(read, PerRoleError), read.context
    assert read.get(rig.made.version) == frozenset({"raw_record"}), read
    after = _next_place(rig)
    assert isinstance(after, RoundError), "a place was taken on on an exposed version"
    assert after.context["refused_because"] == "version_exposed", after.context


class Killed(BaseException):  # noqa: N818 - stands for the process being killed
    """The baseline round's process killed while its session runs."""


@dataclass
class KilledInTheDeepSession(StandInArm):
    """Killed while its first session runs: the client's deep tree there, and no record."""

    def __call__(
        self, task: Task, setup: RawSetup, work: Path, *, cap: int, harness: Path | None = None
    ) -> dict[str, Any]:
        if self.calls:
            return super().__call__(task, setup, work, cap=cap, harness=harness)
        self.calls.append((task.id, cap, work))
        _client_tree(work)
        # A process that has ended: no such pid runs, and no process runs in its group.
        facts = {"pid": 2**22 + 7, "started": "Thu Jan  1 00:00:00 1970", "session_id": "s-1"}
        (work / "session" / "process.json").write_text(json.dumps(facts))
        (work / "session" / "stdout.jsonl").write_text('{"type": "user"}\n')
        raise Killed


def test_a_place_a_kill_left_with_no_record_beside_it_is_not_entered_either(rig: Rig) -> None:
    runs = _first_place(rig)
    arm = KilledInTheDeepSession()
    with pytest.raises(Killed):
        _raw(rig, runs, arm)
    raw = _raw(rig, runs, arm, resume=True)
    assert not isinstance(raw, BaselineError), raw.context
    killed = [p.parent for p in _baseline(rig).glob(f"*/*/{PLACE}")]
    assert len(killed) == 2, killed
    assert [(p / "harness" / "raw.json").exists() for p in sorted(killed)] == [False, True]
    assert _deepest(sorted(killed)[0]) + 2 > exposure.MOST_DEPTH
    after = _next_place(rig)
    assert not isinstance(after, RoundError), after.context


@pytest.mark.parametrize("beside", ["nothing", "a file of the harness's name"])
def test_a_directory_named_as_a_place_with_no_harness_s_beside_it_is_walked(
    rig: Rig, beside: str
) -> None:
    # A raw record in it is read, as anywhere else: only a harness's directory makes a trial.
    place = _baseline(rig) / "r" / "0000-1" / PLACE
    place.mkdir(parents=True)
    if beside != "nothing":
        (place.parent / exposure.TRIAL_HARNESS).write_text("")
    (place / exposure.RAW_RECORD).write_text(json.dumps({"held_out_seen": True}))
    read = _read(rig)
    assert not isinstance(read, PerRoleError), read.context
    assert read.get(rig.made.version) == frozenset({"raw_record"}), read
