"""A hold or release line owed again with no line of another kind between halts the run.

The wait lines change nothing but the open, let-go and mutual sets, so a sound rule never owes
the same one twice in a row. A rule that does (a let-go that is not kept, a hold that is not taken
off) would have the loop write it for ever: the loop halts on an incident, ``no_progress``, that
names the step, and writes no more. A long streak of distinct lines is no such repeat.
"""

from __future__ import annotations

import itertools
from typing import Any

import pytest
from accounted import forged_account_before_each_open  # noqa: F401 - the rig's forger
from sign_off_rig import before_the_sign_off_rule  # noqa: F401 - the fixture, by name
from test_a_choice_on_a_failed_contract_reopens_the_other_module import of
from test_a_failed_contract_is_ruled_by_clause_and_goes_to_a_person_as_one_item import (
    lines,
    refusal,
)
from test_a_queue_decision_acts_at_a_boundary import decide
from test_a_reader_is_let_go_by_a_producer_that_waits_for_it import REAL, item_of
from wait_cycle_rig import (
    CONTROL,
    CONTROL2,
    ELECTRICAL,
    FIRMWARE,
    FIRMWARE2,
    SIZING,
    Shape,
    bounded,
    first_run,
    resumed,
    under_release,  # noqa: F401 - the fixture, by name
)

from physgate import roles
from physgate.orchestrator import producer_wait, wait_cycle
from physgate.orchestrator.events import read_events
from physgate.orchestrator.replay import replay

pytestmark = pytest.mark.usefixtures("before_the_sign_off_rule")


@pytest.fixture(autouse=True)
def _sizing_registered(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setitem(roles.ROLES, roles.SIZING.name, roles.SIZING)


@pytest.mark.usefixtures("under_release")
def test_a_release_owed_again_halts_the_run_on_an_incident_that_names_the_step(
    tmp_path: Any,  # noqa: ANN401
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The let-go is not kept (a fresh key each time), so the same release is owed again."""
    fresh = itertools.count()

    def never_kept(_state: object, reader: str, producer: str) -> tuple[str, str, int]:
        return (reader, producer, next(fresh))

    monkeypatch.setattr(producer_wait, "let_go_key", never_kept)
    monkeypatch.setattr(wait_cycle, "let_go_key", never_kept)
    rig = REAL.rig(tmp_path)
    assert first_run(rig, monkeypatch, REAL) == "halted"
    rows = lines(rig)
    released = of(rows, "dispatch_released")
    assert len(released) == 1, "the line is written once, never a second time"
    (incident,) = of(rows, "incident")
    assert incident["cause"] == "no_progress"
    assert incident["subtask_id"] is None
    assert "release for drive-0a1b2c" in incident["detail"]
    assert "dispatch_released" in incident["detail"]
    # The halt is final, and it says what a person does: a new run, and this record reported.
    assert "This halt is final: the run is not resumed" in incident["detail"]
    assert "starts a new run from the plan and reports this record" in incident["detail"]
    assert of(rows, "halted")[0]["detail"].startswith("no_progress")
    assert rows.index(incident) == rows.index(released[0]) + 1


@pytest.mark.usefixtures("under_release")
def test_the_halted_record_replays_and_its_next_step_is_the_halt(
    tmp_path: Any,  # noqa: ANN401
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    fresh = itertools.count()
    monkeypatch.setattr(producer_wait, "let_go_key", lambda _s, r, p: (r, p, next(fresh)))
    monkeypatch.setattr(wait_cycle, "let_go_key", lambda _s, r, p: (r, p, next(fresh)))
    rig = REAL.rig(tmp_path)
    assert first_run(rig, monkeypatch, REAL) == "halted"
    monkeypatch.undo()
    assert refusal(lines(rig)) is None
    state = replay(read_events(rig.run_dir / "events.jsonl"))
    assert state.next_step().kind == "halted"
    assert state.halted is not None
    assert state.halted.reason == "incident"


def test_a_long_streak_of_distinct_wait_lines_does_not_trip_the_guard(
    tmp_path: Any,  # noqa: ANN401
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Five readers of sizing held one after another, then released as sizing merged."""
    shape = Shape(
        order=(SIZING, CONTROL, FIRMWARE, ELECTRICAL, CONTROL2, FIRMWARE2),
        reads=tuple((SIZING, c) for c in (CONTROL, FIRMWARE, ELECTRICAL, CONTROL2, FIRMWARE2)),
    )
    rig = shape.rig(tmp_path)
    assert first_run(rig, monkeypatch, shape) == "wait"
    rows = lines(rig)
    decide(rig.run_dir, "approve", item_id=item_of(rows, SIZING))
    assert resumed(rig, monkeypatch, shape) == "done"
    rows = lines(rig)
    assert of(rows, "incident") == []
    kinds = [r["kind"] for r in rows]
    holds = [i for i, k in enumerate(kinds) if k == "dispatch_held"]
    releases = [i for i, k in enumerate(kinds) if k == "dispatch_released"]
    assert len(holds) == len(releases) == 5
    assert holds == list(range(holds[0], holds[0] + 5)), "five holds written one after another"
    assert refusal(rows) is None


def test_the_rig_s_bound_fails_a_loop_that_writes_without_end_as_an_assertion() -> None:
    class Spinning:
        def _emit(self, _event: object) -> None:
            return None

    class Line:
        kind = "dispatch_released"

    loop: Any = bounded(Spinning(), limit=5)  # type: ignore[arg-type]
    for _ in range(5):
        loop._emit(Line())  # noqa: SLF001
    with pytest.raises(AssertionError, match="not going to stop"):
        loop._emit(Line())  # noqa: SLF001
