"""A dispute is arbitrated by a fixed precedence, and the replay computes the ruling again.

``arbitrate()`` is a pure function of the conflict and the standing it is read in: the first row
of the precedence table that applies decides it. The gate outranks every role: an attempt the gate
refused in ``on`` keeps the gate's rejection, and its dispute is recorded and not counted. Sizing
outranks a domain on a quantity of a cross node: the first counted dispute of a quantity, with an
attempt left, leaves sizing's value standing. What survives both goes to a person: a repeat of a
quantity counted before, or a dispute on the subtask's last attempt. The table is data, it ends
in the queue, and no conflict is left without exactly one outcome. No row lets one session's
words reach another: the line names the quantity and holds the graph's value, never a reason.

Each ruling is one ``arbitration_decided`` line, after the attempt's gate line and before its
review, one per dispute in the order recorded. The replay builds the standing again from the lines
before it and refuses a line whose standing or level is not what they give.
"""

from __future__ import annotations

import itertools
import json
import sys
from collections.abc import Sequence
from pathlib import Path
from typing import Any, get_args

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent))
from arbitration_runs import (  # noqa: E402
    BIG,
    TWO,
    events_of,
    refusal,
    resume,
    rig_of,
    run,
)
from loop_fakes import Rig, failing_gate_result, passing_gate_result, plan  # noqa: E402

from physgate import roles  # noqa: E402
from physgate.orchestrator.arbitration import (  # noqa: E402
    TABLE,
    Arbitration,
    DisputeConflict,
    Held,
    Rank,
    Standing,
    always,
    arbitrate,
    dispute_standing,
    require_table,
)
from physgate.orchestrator.events import (  # noqa: E402
    ArbitrationDecided,
    AttemptRejected,
    Event,
    GateRan,
    GateSkipped,
    read_events,
)
from physgate.orchestrator.exceptions import ArbitrationError  # noqa: E402
from physgate.orchestrator.protocols import QuantityRef  # noqa: E402
from physgate.orchestrator.run_config import ModelStrings  # noqa: E402

BUS = DisputeConflict(node_id="sizing.bus", quantity="supply_voltage")
RAIL = DisputeConflict(node_id="sizing.bus", quantity="peak_current")
#: Every standing a dispute can be read in, as far as the table can tell them apart.
STANDINGS = [
    Standing(gate_refused=g, counted_before=c, attempt_left=left)
    for g, c, left in itertools.product((False, True), (0, 1, 2, 7), (False, True))
]


def oracle(standing: Standing) -> str:
    """The level the precedence gives, written out as the architecture states it."""
    if standing.gate_refused:
        return "gate"
    if standing.counted_before == 0 and standing.attempt_left:
        return "sizing"
    return "queue"


# --- the table ----------------------------------------------------------------------------------


def test_the_gate_outranks_every_role() -> None:
    refused = [s for s in STANDINGS if s.gate_refused]
    assert refused
    for standing in refused:
        assert arbitrate(BUS, standing) == Arbitration(level="gate", effect="gate_stands")


def test_sizing_outranks_a_domain_on_a_cross_quantity() -> None:
    first = Standing(gate_refused=False, counted_before=0, attempt_left=True)
    assert arbitrate(BUS, first) == Arbitration(level="sizing", effect="reject_attempt")


@pytest.mark.parametrize(
    "standing",
    [
        Standing(gate_refused=False, counted_before=1, attempt_left=True),
        Standing(gate_refused=False, counted_before=0, attempt_left=False),
        Standing(gate_refused=False, counted_before=3, attempt_left=False),
    ],
    ids=["a repeat", "the last attempt", "both"],
)
def test_what_survives_the_gate_and_sizing_goes_to_a_person(standing: Standing) -> None:
    assert arbitrate(BUS, standing) == Arbitration(level="queue", effect="queue_item")


def test_every_conflict_yields_exactly_one_outcome_the_first_row_that_applies() -> None:
    names = [rank.level for rank in TABLE]
    assert names == ["gate", "sizing", "queue"]
    for conflict, standing in itertools.product((BUS, RAIL), STANDINGS):
        found = arbitrate(conflict, standing)
        assert found.level == oracle(standing), (conflict, standing)
        place = names.index(found.level)
        assert TABLE[place].applies(conflict, standing)
        assert not [r.level for r in TABLE[:place] if r.applies(conflict, standing)]
        assert found.effect == TABLE[place].effect


def _inserted(at: int, applies: Any) -> tuple[Rank, ...]:
    row = Rank(level="declared", effect="reject_attempt", applies=applies)
    return (*TABLE[:at], row, *TABLE[at:])


@pytest.mark.parametrize("at", [0, 1, 2], ids=["above the gate", "below the gate", "below sizing"])
def test_a_precedence_level_inserted_into_the_table_changes_the_outcome_only_where_it_ranks(
    at: int,
) -> None:
    def applies(_: DisputeConflict, standing: Standing) -> bool:
        return standing.counted_before >= 1 or standing.gate_refused

    table = _inserted(at, applies)
    changed = 0
    for standing in STANDINGS:
        before = arbitrate(BUS, standing)
        after = arbitrate(BUS, standing, table)
        above = [r for r in TABLE[:at] if r.applies(BUS, standing)]
        if applies(BUS, standing) and not above:
            assert after == Arbitration(level="declared", effect="reject_attempt"), standing
            changed += before != after
        else:
            assert after == before, standing
    # The row decided something somewhere, and below sizing it is still reached by a repeat.
    assert changed


@pytest.mark.parametrize(
    "table",
    [
        (),
        TABLE[:-1],
        (TABLE[0], TABLE[0], TABLE[1], TABLE[2]),
        (*TABLE[:-1], Rank(level="queue", effect="queue_item", applies=lambda c, s: False)),
        (TABLE[2], TABLE[0], TABLE[1]),
        (Rank(level="early", effect="queue_item", applies=always), *TABLE),
    ],
    # Each table breaks one rule alone, so each refusal is that rule's: a level twice in a table
    # that otherwise ends in the queue, and the queue's rule above a table that otherwise is whole.
    ids=[
        "empty",
        "no queue",
        "a level twice",
        "a queue that can decline",
        "the queue first",
        "the queue's rule above the last row",
    ],
)
def test_a_table_that_could_leave_a_conflict_without_one_outcome_is_refused(
    table: tuple[Rank, ...],
) -> None:
    try:
        require_table(table)
        refused = False
    except ArbitrationError:
        refused = True
    assert refused
    try:
        arbitrate(BUS, STANDINGS[0], table)
        refused = False
    except ArbitrationError:
        refused = True
    assert refused


def test_the_recorded_levels_are_the_table_s_names_in_order() -> None:
    recorded = get_args(ArbitrationDecided.model_fields["level"].annotation)
    assert recorded == tuple(rank.level for rank in TABLE)


# --- the standing -------------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("gate", "refused"),
    [
        (failing_gate_result("on"), True),
        (failing_gate_result("observe"), False),
        (passing_gate_result("on"), False),
        (None, False),
    ],
    ids=["refused in on", "failed in observe", "passed", "skipped"],
)
def test_the_gate_refused_only_where_it_blocks(gate: Any, refused: bool) -> None:
    standing = dispute_standing(BUS, gate=gate, earlier=(), attempt=1, fix=False)
    assert standing.gate_refused is refused


def test_a_dispute_counts_earlier_attempts_of_its_quantity_unless_the_gate_decided_them() -> None:
    earlier = [(BUS, "gate"), (RAIL, "sizing"), (BUS, "sizing"), (BUS, "queue")]
    standing = dispute_standing(BUS, gate=None, earlier=earlier, attempt=2, fix=False)
    assert standing.counted_before == 2
    assert (
        dispute_standing(RAIL, gate=None, earlier=earlier, attempt=2, fix=False).counted_before == 1
    )
    only_gate = dispute_standing(BUS, gate=None, earlier=[(BUS, "gate")], attempt=2, fix=False)
    assert only_gate.counted_before == 0


@pytest.mark.parametrize(
    ("attempt", "fix", "left"),
    [(1, False, True), (2, False, True), (3, False, False), (4, True, False)],
    ids=["first", "second", "third, the budget's last", "the person's fix"],
)
def test_an_attempt_is_left_unless_this_is_the_subtask_s_last(
    attempt: int, fix: bool, left: bool
) -> None:
    standing = dispute_standing(BUS, gate=None, earlier=(), attempt=attempt, fix=fix)
    assert standing.attempt_left is left


# --- the line, and the replay -------------------------------------------------------------------
#
# Every log below is one the loop wrote; a forged log edits the loop's own lines, never inserts
# rulings into a run the loop drove through review, which the stage now makes impossible.


@pytest.fixture
def _sizing(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setitem(roles.ROLES, roles.SIZING.name, roles.SIZING)


def driven(tmp_path: Path, **rigged: Any) -> list[Event]:  # noqa: ANN401 - the rig's fields
    """A loop-written run whose domain subtask disputes the bus current and voltage each time."""
    rig = rig_of(tmp_path / "run", **rigged)
    run(rig)
    return events_of(rig)


def rulings(events: Sequence[Event], attempt: int | None = None) -> list[ArbitrationDecided]:
    return [e for e in events if isinstance(e, ArbitrationDecided) and attempt in (None, e.attempt)]


def edited(events: Sequence[Event], line: Event, **fields: Any) -> list[Event]:  # noqa: ANN401
    """``events`` up to and with ``line`` edited, where the replay meets it first."""
    at = list(events).index(line)
    return [*events[:at], line.model_copy(update=fields)]


#: Attempt 1 refused by the gate, attempt 2 left to sizing, attempt 3 the last: the levels.
GATE = ["fail"]
HONEST = [(1, "gate"), (1, "gate"), (2, "sizing"), (2, "sizing"), (3, "queue"), (3, "queue")]


@pytest.mark.usefixtures("_sizing")
def test_every_arbitration_line_is_recomputed_on_replay(tmp_path: Path) -> None:
    events = driven(tmp_path, gate=GATE)
    assert refusal(events) is None
    lines = rulings(events)
    assert [(e.attempt, e.level) for e in lines] == HONEST
    assert [e.standing.counted_before for e in lines] == [0, 0, 0, 0, 1, 1]


@pytest.mark.usefixtures("_sizing")
@pytest.mark.parametrize(
    ("attempt", "level"),
    [(1, "sizing"), (2, "queue"), (2, "gate"), (3, "sizing")],
    ids=["a gate refusal ruled for sizing", "a first counted for the queue", "no gate", "a repeat"],
)
def test_a_line_whose_level_is_not_the_table_s_does_not_open(
    tmp_path: Path, attempt: int, level: str
) -> None:
    events = driven(tmp_path, gate=GATE)
    said = refusal(edited(events, rulings(events, attempt)[0], level=level))
    assert said is not None and "level" in said, said


@pytest.mark.usefixtures("_sizing")
@pytest.mark.parametrize(
    "change",
    [{"counted_before": 1}, {"gate_refused": True}, {"attempt_left": False}],
    ids=["counted", "the gate", "the last attempt"],
)
def test_a_line_about_a_standing_the_lines_before_it_do_not_give_does_not_open(
    tmp_path: Path, change: dict[str, Any]
) -> None:
    events = driven(tmp_path, gate=GATE)
    line = rulings(events, 2)[0]
    standing = line.standing.model_copy(update=change)
    said = refusal(edited(events, line, standing=standing, level=oracle(standing)))
    assert said is not None and "standing" in said, said


@pytest.mark.usefixtures("_sizing")
def test_a_line_comes_only_after_the_gate_line_and_before_anything_else(tmp_path: Path) -> None:
    events = driven(tmp_path)
    first = rulings(events, 1)[0]
    at = events.index(first)
    gate = events[at - 1]
    assert isinstance(gate, GateRan | GateSkipped)
    assert refusal(events[: at + 1]) is None
    said = refusal([*events[: at - 1], first])  # before its gate line
    assert said is not None and "arbitration" in said, said
    rejected = next(e for e in events if isinstance(e, AttemptRejected))
    after = events.index(rejected) + 1
    said = refusal([*events[:after], first])  # after the attempt's decision
    assert said is not None and "arbitration" in said, said


@pytest.mark.usefixtures("_sizing")
def test_a_line_answers_the_disputes_in_order_each_once(tmp_path: Path) -> None:
    events = driven(tmp_path)
    rail, bus = rulings(events, 1)
    at = events.index(rail)
    said = refusal([*events[:at], bus])
    assert said is not None and "next dispute" in said, said
    said = refusal([*events[: at + 2], bus])
    assert said is not None and "arbitration" in said, said


def test_a_line_for_an_attempt_that_disputes_nothing_does_not_open(tmp_path: Path) -> None:
    models = ModelStrings(
        decomposition="claude-sonnet-5",
        roles={"electrical": "claude-sonnet-5"},
        reviewers={"electrical": "claude-opus-5-5"},
    )
    rig = Rig(tmp_path, config_overrides={"models": models})
    loop = rig.open()
    loop.start(plan("s1"))
    loop.run()
    loop.close()
    events = read_events(tmp_path / "events.jsonl")
    gate = next(i for i, e in enumerate(events) if isinstance(e, GateRan | GateSkipped))
    first = Standing(gate_refused=False, counted_before=0, attempt_left=True)
    held = Held(
        position=QuantityRef(node_id="sizing.bus", name="peak_current", value=3, unit="A"),
        source="datasheet",
        written_by="sizing",
        revision=1,
    )
    line = ArbitrationDecided(
        seq=0, ts=events[gate].ts, run_id=events[gate].run_id, gate_mode=events[gate].gate_mode,
        subtask_id="s1", attempt=1, conflict=RAIL, standing=first, level="sizing", held=held,
    )  # fmt: skip
    assert refusal([*events[: gate + 1], line]) is not None


@pytest.mark.usefixtures("_sizing")
@pytest.mark.parametrize(
    "position",
    [
        QuantityRef(node_id="sizing.bus", name="mass", value=1, unit="kg"),
        QuantityRef(node_id="sizing.other", name="peak_current", value=3, unit="A"),
    ],
    ids=["another quantity", "another node"],
)
def test_a_line_must_hold_the_disputed_quantity_as_the_graph_had_it(
    tmp_path: Path, position: QuantityRef
) -> None:
    events = driven(tmp_path)
    line = rulings(events, 1)[0]
    said = refusal(edited(events, line, held=line.held.model_copy(update={"position": position})))
    assert said is not None and "held" in said, said


@pytest.mark.usefixtures("_sizing")
@pytest.mark.parametrize("mode", ["observe", "off"])
def test_without_a_blocking_gate_the_first_dispute_is_sizing_s(tmp_path: Path, mode: str) -> None:
    events = driven(tmp_path, gate=GATE, mode=mode)
    assert refusal(events) is None
    assert [e.level for e in rulings(events, 1)] == ["sizing", "sizing"]
    line = rulings(events, 1)[0]
    refused = Standing(gate_refused=True, counted_before=0, attempt_left=True)
    assert refusal(edited(events, line, standing=refused, level="gate")) is not None


@pytest.mark.usefixtures("_sizing")
def test_the_line_keeps_a_400_digit_value_exact_and_never_holds_the_reason(tmp_path: Path) -> None:
    rig = rig_of(tmp_path / "run", gate=GATE)
    run(rig)
    data = (rig.run_dir / "events.jsonl").read_bytes()
    assert b"REASON-CANARY" in data  # the dispute's own line holds its reason, for a person
    lines = [json.loads(raw) for raw in data.splitlines() if b'"arbitration_decided"' in raw]
    assert lines and not [r for r in lines if "REASON-CANARY" in json.dumps(r)]
    events = events_of(rig)
    assert refusal(events) is None
    values = [e.held.position.value for e in rulings(events) if e.conflict == BUS]
    assert values == [BIG, BIG, BIG]
    assert {type(v) for v in values} == {int}


@pytest.mark.usefixtures("_sizing")
def test_a_killed_and_resumed_attempt_is_ruled_in_its_last_window_alone(tmp_path: Path) -> None:
    # Attempt 1 is killed between its two rulings and resumed: two windows, each with its gate
    # line. Each window is ruled as a first dispute; a ruling of the first window is never counted
    # by the second, and a first-window line written after the resume does not open.
    rig = rig_of(tmp_path / "run")
    seen: list[Event] = []

    def second_ruling(line: Event) -> bool:
        seen.extend([line] if isinstance(line, ArbitrationDecided) else [])
        return len(seen) == 2

    assert run(rig, kill=second_ruling) == "killed"
    resume(rig)
    events = events_of(rig)
    assert refusal(events) is None
    gates = [e for e in events if isinstance(e, GateRan | GateSkipped) and e.subtask_id == "s1"]
    assert [e.attempt for e in gates[:2]] == [1, 1]
    first_window, *later = rulings(events, 1)
    assert [e.standing.counted_before for e in later] == [0, 0]
    assert [e.level for e in later] == ["sizing", "sizing"]
    counted = later[0].standing.model_copy(update={"counted_before": 1})
    said = refusal(edited(events, later[0], standing=counted, level="queue"))
    assert said is not None and "standing" in said, said
    resumed = next(e for e in events if e.kind == "resumed")
    at = events.index(resumed) + 1
    said = refusal([*events[:at], events[at], first_window])
    assert said is not None and "arbitration" in said, said


@pytest.mark.usefixtures("_sizing")
def test_a_dispute_on_the_fix_a_person_ordered_has_no_attempt_left(tmp_path: Path) -> None:
    # The fix is always a subtask's last attempt: its dispute goes to a person, never to sizing.
    from test_a_blocked_review_is_a_review_that_goes_to_a_person import blocked_review
    from test_a_queue_decision_acts_at_a_boundary import decide

    rig = rig_of(tmp_path / "run", script=[(), TWO])
    rig.reviewer.results[2] = blocked_review()
    run(rig)
    decide(rig.run_dir, "reject", "the bus needs a margin the specification gives")
    resume(rig)
    events = events_of(rig)
    assert refusal(events) is None
    honest = rulings(events, 2)
    assert [(e.level, e.standing.attempt_left) for e in honest] == [("queue", False)] * 2
    forged = honest[0].standing.model_copy(update={"attempt_left": True})
    said = refusal(edited(events, honest[0], standing=forged, level="sizing"))
    assert said is not None and "standing" in said, said
