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

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "hooks"))
from loop_fakes import (  # noqa: E402
    FakeChanges,
    FakeGate,
    FakeReviewer,
    Rig,
    failing_gate_result,
    passing_gate_result,
    plan,
)

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
from physgate.orchestrator.dispute import Dispute  # noqa: E402
from physgate.orchestrator.events import (  # noqa: E402
    ArbitrationDecided,
    Event,
    GateRan,
    GateSkipped,
    StageEntered,
    parse_events,
)
from physgate.orchestrator.exceptions import ArbitrationError, CorruptEventLogError  # noqa: E402
from physgate.orchestrator.protocols import QuantityRef  # noqa: E402
from physgate.orchestrator.replay import replay  # noqa: E402
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

BIG = 10**399 + 7


def disputed(value: float, name: str, unit: str) -> Dispute:
    position = QuantityRef(node_id="sizing.bus", name=name, value=value, unit=unit)
    return Dispute(position=position, reason="a canary that never reaches the line")


TWO = (disputed(5, "peak_current", "A"), disputed(24, "supply_voltage", "V"))
GRAPH = {"peak_current": (3, "A"), "supply_voltage": (BIG, "V")}


def held(conflict: DisputeConflict) -> Held:
    value, unit = GRAPH[conflict.quantity]
    position = QuantityRef(node_id=conflict.node_id, name=conflict.quantity, value=value, unit=unit)
    return Held(position=position, source="datasheet", written_by="sizing", revision=1)


def driven(
    tmp_path: Path, *, gate: Sequence[str] = (), review: Sequence[str] = (), mode: str = "on"
) -> list[Event]:
    """A run of ``s1`` whose every attempt disputes the two quantities; its lines."""
    models = ModelStrings(
        decomposition="claude-sonnet-5",
        roles={"electrical": "claude-sonnet-5"},
        reviewers={"electrical": "claude-opus-5-5"},
    )
    changes = FakeChanges()
    changes.disputes["s1"] = TWO
    rig = Rig(
        tmp_path,
        gate_mode=mode,  # type: ignore[arg-type]
        gate=FakeGate(verdicts=list(gate)),
        reviewer=FakeReviewer(verdicts=list(review)),
        changes=changes,
        config_overrides={"models": models},
    )
    loop = rig.open()
    loop.start(plan("s1"))
    loop.run()
    loop.close()
    from physgate.orchestrator.events import read_events

    return read_events(tmp_path / "events.jsonl")


def ruled(
    after: Event, conflict: DisputeConflict, standing: Standing, level: str, **fields: Any
) -> ArbitrationDecided:
    values: dict[str, Any] = {
        "subtask_id": "s1",
        "attempt": getattr(after, "attempt", 1),
        "conflict": conflict,
        "standing": standing,
        "level": level,
        "held": held(conflict),
    } | fields
    return ArbitrationDecided(
        seq=0, ts=after.ts, run_id=after.run_id, gate_mode=after.gate_mode, **values
    )


def resequenced(events: Sequence[Event]) -> list[Event]:
    return [e.model_copy(update={"seq": i}) for i, e in enumerate(events)]


def with_rulings(events: Sequence[Event], levels: Sequence[Sequence[str]]) -> list[Event]:
    """``events`` with each attempt's rulings after its gate line, standings as the record gives.

    ``levels[n]`` is attempt ``n + 1``'s, one per dispute in recorded order (peak current, then
    supply voltage); the standing is computed here from those levels, not by the code under test.
    """
    out: list[Event] = []
    earlier: list[tuple[DisputeConflict, str]] = []
    for event in events:
        out.append(event)
        if not isinstance(event, GateRan | GateSkipped) or event.subtask_id != "s1":
            continue
        refused = (
            isinstance(event, GateRan)
            and event.result.mode == "on"
            and event.result.verdict == "fail"
        )
        mine = []
        for conflict, level in zip((RAIL, BUS), levels[event.attempt - 1], strict=True):
            counted = sum(1 for c, lv in earlier if c == conflict and lv != "gate")
            standing = Standing(
                gate_refused=refused, counted_before=counted, attempt_left=event.attempt < 3
            )
            out.append(ruled(event, conflict, standing, level))
            mine.append((conflict, level))
        earlier += mine
    return resequenced(out)


def opened(events: Sequence[Event]) -> list[Event]:
    """The lines as a fresh process reads them from disk: serialised, parsed, replayed."""
    data = b"".join(e.model_dump_json().encode() + b"\n" for e in resequenced(events))
    read: list[Event] = parse_events(data, log="events.jsonl")
    replay(read)
    return read


def refusal(events: Sequence[Event]) -> str | None:
    try:
        opened(events)
    except CorruptEventLogError as exc:
        reason: str = exc.context.get("reason", str(exc))
        return reason
    return None


#: Attempt 1 refused by the gate, attempt 2 rejected by its review, attempt 3 merged.
GATE, REVIEW = ["fail"], ["fail"]
#: The levels that run's three attempts are ruled at.
HONEST = [("gate", "gate"), ("sizing", "sizing"), ("queue", "queue")]


def test_every_arbitration_line_is_recomputed_on_replay(tmp_path: Path) -> None:
    events = with_rulings(driven(tmp_path, gate=GATE, review=REVIEW), HONEST)
    lines = [e for e in opened(events) if isinstance(e, ArbitrationDecided)]
    assert [(e.attempt, e.level) for e in lines] == [
        (1, "gate"),
        (1, "gate"),
        (2, "sizing"),
        (2, "sizing"),
        (3, "queue"),
        (3, "queue"),
    ]
    assert [e.standing.counted_before for e in lines] == [0, 0, 0, 0, 1, 1]


@pytest.mark.parametrize(
    ("attempt", "level"),
    [(1, "sizing"), (2, "queue"), (2, "gate"), (3, "sizing")],
    ids=["a gate refusal ruled for sizing", "a first counted for the queue", "no gate", "a repeat"],
)
def test_a_line_whose_level_is_not_the_table_s_does_not_open(
    tmp_path: Path, attempt: int, level: str
) -> None:
    levels = [list(pair) for pair in HONEST]
    levels[attempt - 1][1] = level
    events = with_rulings(driven(tmp_path, gate=GATE, review=REVIEW), levels)
    said = refusal(events)
    assert said is not None and "level" in said, said


@pytest.mark.parametrize(
    "change",
    [
        {"counted_before": 1},
        {"gate_refused": True},
        {"attempt_left": False},
    ],
    ids=["counted", "the gate", "the last attempt"],
)
def test_a_line_about_a_standing_the_lines_before_it_do_not_give_does_not_open(
    tmp_path: Path, change: dict[str, Any]
) -> None:
    events = with_rulings(driven(tmp_path, gate=GATE, review=REVIEW), HONEST)
    place = next(
        i for i, e in enumerate(events) if isinstance(e, ArbitrationDecided) and e.attempt == 2
    )
    line = events[place]
    assert isinstance(line, ArbitrationDecided)
    standing = line.standing.model_copy(update=change)
    level = oracle(standing)
    events[place] = line.model_copy(update={"standing": standing, "level": level})
    said = refusal(events)
    assert said is not None and "standing" in said, said


def _first_gate(events: Sequence[Event]) -> int:
    return next(i for i, e in enumerate(events) if isinstance(e, GateRan | GateSkipped))


def test_a_line_comes_only_after_the_gate_line_and_before_the_review(tmp_path: Path) -> None:
    events = driven(tmp_path)
    gate = _first_gate(events)
    first = Standing(gate_refused=False, counted_before=0, attempt_left=True)
    assert refusal([*events[: gate + 1], ruled(events[gate], RAIL, first, "sizing")]) is None
    for cut in (gate, gate + 1 + 1):
        head = list(events[:cut])
        said = refusal(resequenced([*head, ruled(events[gate], RAIL, first, "sizing")]))
        assert said is not None and "arbitration" in said, (cut, said)
    entered = events[gate + 1]
    assert isinstance(entered, StageEntered) and entered.stage == "review"


def test_a_line_answers_the_disputes_in_order_each_once(tmp_path: Path) -> None:
    events = driven(tmp_path)
    gate = _first_gate(events)
    head = list(events[: gate + 1])
    first = Standing(gate_refused=False, counted_before=0, attempt_left=True)
    # The held value is the first dispute's, so only the order is wrong.
    wrong_order = [*head, ruled(events[gate], BUS, first, "sizing", held=held(RAIL))]
    said = refusal(resequenced(wrong_order))
    assert said is not None and "next dispute" in said, said
    three = [*head, *(ruled(events[gate], c, first, "sizing") for c in (RAIL, BUS, BUS))]
    assert refusal(resequenced(three[:-1])) is None
    assert refusal(resequenced(three)) is not None


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
    from physgate.orchestrator.events import read_events

    events = read_events(tmp_path / "events.jsonl")
    gate = _first_gate(events)
    first = Standing(gate_refused=False, counted_before=0, attempt_left=True)
    assert refusal([*events[: gate + 1], ruled(events[gate], RAIL, first, "sizing")]) is not None


@pytest.mark.parametrize(
    "fields",
    [
        {
            "held": Held(
                position=QuantityRef(node_id="sizing.bus", name="mass", value=1, unit="kg"),
                source="datasheet",
                written_by="sizing",
                revision=1,
            )
        },
        {
            "held": Held(
                position=QuantityRef(
                    node_id="sizing.other", name="peak_current", value=3, unit="A"
                ),
                source="datasheet",
                written_by="sizing",
                revision=1,
            )
        },
    ],
    ids=["another quantity", "another node"],
)
def test_a_line_must_hold_the_disputed_quantity_as_the_graph_had_it(
    tmp_path: Path, fields: dict[str, Any]
) -> None:
    events = driven(tmp_path)
    gate = _first_gate(events)
    first = Standing(gate_refused=False, counted_before=0, attempt_left=True)
    line = ruled(events[gate], RAIL, first, "sizing", **fields)
    said = refusal([*events[: gate + 1], line])
    assert said is not None and "held" in said, said


@pytest.mark.parametrize("mode", ["observe", "off"])
def test_without_a_blocking_gate_the_first_dispute_is_sizing_s(tmp_path: Path, mode: str) -> None:
    events = driven(tmp_path, gate=["fail"], mode=mode)
    gate = _first_gate(events)
    first = Standing(gate_refused=False, counted_before=0, attempt_left=True)
    lines = [ruled(events[gate], c, first, "sizing") for c in (RAIL, BUS)]
    assert refusal(resequenced([*events[: gate + 1], *lines])) is None
    refused = Standing(gate_refused=True, counted_before=0, attempt_left=True)
    lines = [ruled(events[gate], c, refused, "gate") for c in (RAIL, BUS)]
    assert refusal(resequenced([*events[: gate + 1], *lines])) is not None


def test_the_line_keeps_a_400_digit_value_exact_and_never_holds_the_reason(tmp_path: Path) -> None:
    events = with_rulings(driven(tmp_path, gate=GATE, review=REVIEW), HONEST)
    data = b"".join(e.model_dump_json().encode() + b"\n" for e in events)
    assert b"canary" in data  # the dispute's own line holds its reason, for a person
    rulings = [json.loads(raw) for raw in data.splitlines() if b'"arbitration_decided"' in raw]
    assert rulings and not [r for r in rulings if "canary" in json.dumps(r)]
    read = [e for e in opened(events) if isinstance(e, ArbitrationDecided)]
    values = [e.held.position.value for e in read if e.conflict == BUS]
    assert values == [BIG, BIG, BIG]
    assert {type(v) for v in values} == {int}


def test_a_restarted_window_forgets_its_own_lines(tmp_path: Path) -> None:
    # Two lines of the same attempt in two windows count as the attempt's, never as a repeat:
    # the replay keeps only the lines of an attempt's last window.
    events = with_rulings(driven(tmp_path, gate=GATE, review=REVIEW), HONEST)
    state = replay(opened(events))
    sub = state.subtasks["s1"]
    assert [len(a.arbitrations) for a in sub.attempts] == [2, 2, 2]
    sub.attempts[-1].restart("resolve")
    assert sub.attempts[-1].arbitrations == []
