"""Sizing's closing pass, while a person's chosen values wait: what it is told, and what holds.

On an automated repair of the closing pass the session is told the values wrapping the repair
instruction, and its reviewer is told the values alone: the repair instruction is no person's
order, and a long finding quoted in it must never make what the reviewer reads overflow one read.
A person's order on the closing pass is wrapped in the values and screened whole, its session kind
is the wrapped order's, and its fit is measured with the values in it. A value is held as chosen
only exactly and in a unit the gate's parser reads as the same items. The closing pass waits for
a dispute's item alone, never for another kind of item.
"""

from __future__ import annotations

import sys
from pathlib import Path
from typing import Any

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent))
from arbitration_runs import (  # noqa: E402
    CLOSING,
    NODE,
    driven,
    events_of,
    refusal,
    resume,
    rig_of,
    run,
)
from loop_fakes import FakeMaterial, FakeReviewer, Rig, usage  # noqa: E402
from test_a_blocked_review_is_a_review_that_goes_to_a_person import blocked_review  # noqa: E402
from test_a_person_chooses_a_position_only_on_an_arbitration_item import (  # noqa: E402
    chose,
    one,
    taken,
)
from test_a_queue_decision_acts_at_a_boundary import decide  # noqa: E402
from test_choosing_the_domain_s_value_waits_for_the_closing_pass_and_returns_to_the_gate import (  # noqa: E402
    ORDER,
    _graph,
    at_the_item,
    resized,
)

from physgate import roles  # noqa: E402
from physgate.orchestrator import decisions as decisions_module  # noqa: E402
from physgate.orchestrator.events import ArbitrationDecided, Incident, Merged  # noqa: E402
from physgate.orchestrator.protocols import MessageUsage, ReviewResult  # noqa: E402
from physgate.orchestrator.replay import replay  # noqa: E402
from physgate.reviewers.packet import fits_one_read, person_order_text  # noqa: E402


@pytest.fixture(autouse=True)
def _sizing_registered(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setitem(roles.ROLES, roles.SIZING.name, roles.SIZING)


#: A reviewer's finding longer than one read shows whole, by itself.
LONG = "the gain changed silently. " * 1000


def _failing(finding: str) -> ReviewResult:
    return ReviewResult(
        verdict="fail",
        finding=finding,
        reviewer_model="claude-opus-5-5",
        session_id="rev-long",
        usage=(MessageUsage(message_id="r-long", usage=usage(7)),),
    )


def _sessions(rig: Rig) -> list[tuple[str, int, str]]:
    return [(r.subtask_id, r.attempt, r.kind) for r in rig.dispatcher.requests]


# --- what the closing pass's reviewer is told on an automated repair ---------------------------


def test_the_reviewer_of_an_automated_repair_of_the_closing_pass_is_told_the_values_alone(
    tmp_path: Path,
) -> None:
    # Review 1 is z0's; review 2, the closing pass's first attempt, fails with a long finding.
    reviewer = FakeReviewer(verdicts=["pass", "fail", "pass", "pass"], results={2: _failing(LONG)})
    rig = resized(tmp_path, reviewer=reviewer)
    second = rig.dispatcher.requests[-1]
    assert (second.subtask_id, second.attempt, second.kind) == ("zc", 2, "attempt")
    # The session is told the values wrapping the automated repair, finding and all.
    assert "This attempt also starts from:" in (second.repair_instruction or "")
    assert LONG.strip() in (second.repair_instruction or "")
    # Its reviewer is told the person's part alone: the values, which fit one read.
    seen = reviewer.seen[2]
    assert (seen.subtask_id, seen.attempt) == ("zc", 2)
    order = seen.ordered_by_person
    assert order is not None
    assert (order.kind, order.instruction) == ("arbitration_value", ORDER)
    assert fits_one_read(person_order_text(order))
    merged = [(m.subtask_id, m.attempt) for m in events_of(rig) if isinstance(m, Merged)]
    assert merged == [("z0", 1), ("zc", 2), ("s1", 2)]


# --- a person's order on the closing pass ------------------------------------------------------


def _fixed_closing_pass(tmp_path: Path, material: tuple[str, ...]) -> Rig:
    """The closing pass's review blocks; a person rejects it with a note: its one fix follows."""
    reviewer = FakeReviewer(verdicts=["pass", "blocked"], results={2: blocked_review()})
    rig = resized(tmp_path, reviewer=reviewer)
    rig.material = FakeMaterial(review_material=material)
    decide(rig.run_dir, "reject", "see row 4 of the table", item_id="run-1-zc")
    driven(rig, resume)
    return rig


def test_a_person_s_note_on_the_closing_pass_is_screened_inside_the_values(tmp_path: Path) -> None:
    rig = _fixed_closing_pass(tmp_path, ("row 4",))
    events = events_of(rig)
    incident = one(e for e in events if isinstance(e, Incident))
    assert incident.cause == "review_material_read"
    assert ("zc", 2, "fix") not in _sessions(rig)
    assert [s[:2] for s in _sessions(rig)].count(("zc", 2)) == 0


def test_the_closing_pass_s_fix_wrapped_in_the_values_is_dispatched_as_the_fix(
    tmp_path: Path,
) -> None:
    rig = _fixed_closing_pass(tmp_path, ())
    closing = [s for s in _sessions(rig) if s[0] == "zc"]
    assert closing == [("zc", 1, "attempt"), ("zc", 2, "fix")]
    merged = [(m.subtask_id, m.attempt) for m in events_of(rig) if isinstance(m, Merged)]
    assert merged == [("z0", 1), ("zc", 2), ("s1", 2)]
    assert refusal(events_of(rig)) is None


def test_a_person_s_order_on_the_closing_pass_is_measured_with_the_values_in_it(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    # One read takes anything but the person's note beside the values block: the fix's own order
    # fits, and so does the resize already taken; the fix wrapped in the values does not.
    reviewer = FakeReviewer(verdicts=["pass", "blocked"], results={2: blocked_review()})
    rig = resized(tmp_path, reviewer=reviewer)
    monkeypatch.setattr(
        decisions_module,
        "fits_one_read",
        lambda data: not (b"The values chosen:" in data and b"see the table" in data),
    )
    decide(rig.run_dir, "reject", "see the table", item_id="run-1-zc")
    driven(rig, resume)
    events = events_of(rig)
    line = next(e for e in taken(events) if e.item_id == "run-1-zc")
    assert (line.effect, line.acts, line.order_too_long) == ("end_subtask", True, True)
    assert ("zc", 2) not in [s[:2] for s in _sessions(rig)]
    # Replay asks the same measure and holds the line to it.
    assert refusal(events) is None


# --- a value held as chosen ---------------------------------------------------------------------


def _node(volts: Any, volt_unit: str, amps: Any, amp_unit: str) -> dict[str, Any]:  # noqa: ANN401
    def q(value: Any, unit: str) -> dict[str, Any]:  # noqa: ANN401
        return {"value": value, "unit": unit, "source": "datasheet", "written_by": "sizing"}

    return {
        "id": NODE,
        "kind": "component",
        "domain": "cross",
        "owner_role": "sizing",
        "quantities": {"peak_current": q(amps, amp_unit), "supply_voltage": q(volts, volt_unit)},
        "geometry_hash": "g0",
        "updated": "2026-10-30T00:00:00Z",
    }


@pytest.mark.parametrize(
    ("written", "levels"),
    [
        (_node(24, "kV", 5, "A"), [("peak_current", "person"), ("supply_voltage", "queue")]),
        (
            _node(24, "volt", 5, "ampere"),
            [("peak_current", "person"), ("supply_voltage", "person")],
        ),
        (_node(24.0, "V", 5, "A"), [("peak_current", "person"), ("supply_voltage", "person")]),
        (_node(24.000001, "V", 5, "A"), [("peak_current", "person"), ("supply_voltage", "queue")]),
    ],
    ids=["kV is not V", "spelt as names", "a float equal", "a float near"],
)
def test_a_value_is_held_as_chosen_only_exactly_and_in_the_same_unit(
    tmp_path: Path, written: dict[str, Any], levels: list[tuple[str, str]]
) -> None:
    rig = at_the_item(tmp_path)
    _graph(rig).writes["zc"] = [written]
    chose(rig.run_dir, "domain")
    driven(rig, resume)
    events = events_of(rig)
    returned = next(i for i, e in enumerate(events) if e.kind == "attempt_returned")
    ruled = [
        (e.conflict.quantity, e.level)
        for e in events[returned:]
        if isinstance(e, ArbitrationDecided)
    ]
    assert ruled == levels
    assert refusal(events) is None


# --- what the closing pass waits for -------------------------------------------------------------


def test_the_closing_pass_does_not_wait_for_an_item_that_is_no_dispute_s(tmp_path: Path) -> None:
    # No dispute: s1's review blocks, its item is open in a run that acts, and the closing pass
    # still runs.
    reviewer = FakeReviewer(verdicts=["pass", "blocked"], results={2: blocked_review()})
    rig = rig_of(tmp_path / "run", reviewer=reviewer, script=[()])
    driven(rig, lambda r: run(r, plan=CLOSING))
    assert [s[:2] for s in _sessions(rig)] == [("z0", 1), ("s1", 1), ("zc", 1)]
    state = replay(events_of(rig))
    assert state.subtasks["s1"].status == "escalated"
    assert state.next_step().kind != "wait"
