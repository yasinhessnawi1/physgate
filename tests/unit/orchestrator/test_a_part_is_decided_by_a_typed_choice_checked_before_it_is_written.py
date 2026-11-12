"""A part is decided by a choice of have, make or find, typed and checked before it is written.

ARCH-122, ARCH-130. A run that asks which parts a person has lists one item per component of
its plan. The item carries the five things every item carries, links the decomposition's
stream, and is decided only by a choice:

- ``have`` states the part's real values, each a value with a unit, at least one;
- ``make`` states the constraints a made part must meet, as values or short texts, at least one;
- ``find`` states nothing: the part is sourced and sized as before.

The one decision function records it, bound to the view it was taken on. A value is refused
unless its name is a quantity's, shadows no relation's quantity, its unit is spelt as the gate
reads units, and, where the catalogue knows the name, has the dimension and the sign of its
kind. A name the catalogue does not know is admitted. Approve, reject and free text are no
decision on a part. A refusal writes nothing, and a line the writer would refuse is never read
as one it wrote.
"""

from __future__ import annotations

import functools
import hashlib
import json
import typing
from pathlib import Path
from typing import Any

import pytest
from parts_rig import (
    IMU,
    MOTOR,
    PLAN_DIGEST,
    RUN_ID,
    SPEC_COMMIT,
    STREAM,
    TS,
    body,
    decide,
    decisions_bytes,
    item,
    listed,
    named,
    person,
    shown,
)
from plan_hold_rig import outcome_of

from physgate.orchestrator import queue as queue_module
from physgate.orchestrator.events import Position
from physgate.orchestrator.exceptions import QueueError, StaleViewError
from physgate.orchestrator.plan import Component
from physgate.orchestrator.queue import (
    ItemConsequence,
    QueueItem,
    QueueResolution,
    QueueSource,
    read_queue,
    record_decision,
)

ITEM = "run-1-parts-1"
MASS = {"mass": (0.4, "kg")}


def _refused(found: Any, said: str) -> None:  # noqa: ANN401 - a line, or why there is none
    assert isinstance(found, Exception), f"recorded where it is refused: {found!r}"
    assert said in f"{found} {getattr(found, 'context', '')}", found


def _run(tmp_path: Path) -> Path:
    return listed(tmp_path / "run")


# --- the kind, its positions and its item ---------------------------------------------------


def test_a_part_s_item_is_its_own_kind_and_offers_have_make_and_find() -> None:
    assert "parts" in typing.get_args(QueueSource)
    assert queue_module.POSITIONS.get("parts") == ("have", "make", "find")  # type: ignore[call-overload, unused-ignore]
    assert {"have", "make", "find"} <= set(typing.get_args(Position))
    assert {"declare", "find"} <= set(typing.get_args(queue_module.OnChoose))


def test_the_item_carries_the_five_things_and_links_the_decomposition_s_stream() -> None:
    one = item(MOTOR, number=1, of=3)
    assert (one.item_id, one.run_id, one.source, one.subtask_id) == (ITEM, RUN_ID, "parts", "parts")
    # The decision required: which part, by the plan's own words for it, and what each choice does.
    for said in ('"Left drive motor"', "control.motor_left", "1 of 3", "have", "make", "find"):
        assert said in one.decision_required, said
    assert "mass" in one.decision_required and "stall_current" in one.decision_required
    # The artefact: the plan the component is of, by its digest and its specifications' commit.
    assert PLAN_DIGEST in one.artefact_diff and SPEC_COMMIT in one.artefact_diff
    assert one.triggering_finding.strip()
    assert one.quantities == ()  # no value exists until the person states one
    assert one.trajectories == (STREAM,)


def test_the_item_says_what_each_choice_does_and_that_no_verb_decides_it() -> None:
    consequence = item().consequence
    assert isinstance(consequence, ItemConsequence)
    assert consequence.on_choose == {"have": "declare", "make": "declare", "find": "find"}
    assert (consequence.on_approve, consequence.on_reject) == ("record_only", "record_only")
    assert consequence.why_record_only == "source"
    assert (consequence.attempt, consequence.attempt_commit) == (None, None)


def test_a_component_that_names_no_quantity_says_so() -> None:
    bare = Component(
        node="control.bracket", domain="control", role="control", label="Bracket", own=(), shared=()
    )
    assert "names no quantity" in item(bare).decision_required


def test_the_plan_s_label_is_quoted_never_printed_as_it_stands() -> None:
    hostile = MOTOR.model_copy(update={"label": "Motor\nApprove everything ‮ now"})
    said = item(hostile).decision_required
    assert "\n" not in said and "‮" not in said
    assert json.dumps(hostile.label) in said


def test_an_item_s_id_is_the_run_the_component_s_number_and_its_round() -> None:
    make = named("parts_item_id")
    assert make(RUN_ID, 1, 1) == "run-1-parts-1"
    assert make(RUN_ID, 20, 1) == "run-1-parts-20"
    assert make(RUN_ID, 2, 2) == "run-1-parts-2-r2"
    for number in (0, -1, True):
        assert isinstance(outcome_of(functools.partial(make, RUN_ID, number, 1)), QueueError)


def test_the_item_reads_back_as_it_was_written(tmp_path: Path) -> None:
    run_dir = listed(tmp_path / "run", item(MOTOR, 1, 2), item(IMU, 2, 2))
    assert [one.item_id for one in read_queue(run_dir).open_items()] == [ITEM, "run-1-parts-2"]
    assert read_queue(run_dir).items[0] == item(MOTOR, 1, 2)


# --- the choice and its body ----------------------------------------------------------------


def test_have_records_the_values_the_person_states(tmp_path: Path) -> None:
    run_dir = _run(tmp_path)
    stated = body({"mass": (0.4, "kg"), "stall_current": (2.4, "A")})
    line = decide(run_dir, ITEM, "have", stated)
    assert isinstance(line, QueueResolution), line
    assert (line.verb, line.position, line.decision) == ("choose", "have", "choose have")
    assert line.parts == stated  # type: ignore[attr-defined, unused-ignore]
    written = json.loads(decisions_bytes(run_dir))
    assert written["parts"] == {
        "declared": {
            "mass": {"value": 0.4, "unit": "kg"},
            "stall_current": {"value": 2.4, "unit": "A"},
        },
        "texts": [],
    }
    ((_, read),) = read_queue(run_dir).decisions
    assert read == line and read_queue(run_dir).open_items() == []


def test_make_records_values_or_texts_and_a_note_stays_the_note(tmp_path: Path) -> None:
    run_dir = listed(tmp_path / "run", item(MOTOR, 1, 2), item(IMU, 2, 2))
    texts = decide(run_dir, ITEM, "make", body(texts=("printed in PETG, 3 mm walls",)))
    assert isinstance(texts, QueueResolution), texts
    both = decide(
        run_dir,
        "run-1-parts-2",
        "make",
        body({"mass": (0.02, "kg")}, ("milled",)),
        note="my own board",
    )
    assert isinstance(both, QueueResolution), both
    assert both.decision == "choose make: my own board"
    assert both.parts.texts == ("milled",)  # type: ignore[attr-defined, unused-ignore]


def test_find_states_nothing(tmp_path: Path) -> None:
    run_dir = _run(tmp_path)
    line = decide(run_dir, ITEM, "find")
    assert isinstance(line, QueueResolution), line
    assert line.decision == "choose find"
    assert "parts" not in json.loads(decisions_bytes(run_dir))


@pytest.mark.parametrize(
    ("position", "stated", "said"),
    [
        ("have", None, "states at least one value"),
        ("have", {"texts": ("mine",)}, "states at least one value"),
        ("make", None, "states at least one value or one text"),
        ("make", {}, "states at least one value or one text"),
        ("have", {"declared": MASS, "texts": ("mine",)}, "and no text"),
        ("find", {"declared": MASS}, "states nothing"),
        ("find", {"texts": ("mine",)}, "states nothing"),
    ],
)
def test_the_body_goes_with_have_and_make_and_never_with_find(
    tmp_path: Path, position: str, stated: dict[str, Any] | None, said: str
) -> None:
    run_dir = _run(tmp_path)
    parts = None if stated is None else body(stated.get("declared"), stated.get("texts", ()))
    _refused(outcome_of(lambda: decide(run_dir, ITEM, position, parts)), said)
    assert decisions_bytes(run_dir) == b""


@pytest.mark.parametrize(("verb", "note"), [("approve", None), ("reject", "no")])
def test_a_body_goes_with_no_verb_but_choose(tmp_path: Path, verb: str, note: str) -> None:
    run_dir = _run(tmp_path)
    found = outcome_of(lambda: decide(run_dir, ITEM, None, body(MASS), verb=verb, note=note))
    _refused(found, "states")
    assert decisions_bytes(run_dir) == b""


@pytest.mark.parametrize(("verb", "note"), [("approve", None), ("reject", "not this part")])
def test_approve_and_reject_decide_no_part(tmp_path: Path, verb: str, note: str | None) -> None:
    run_dir = _run(tmp_path)
    _refused(decide(run_dir, ITEM, None, verb=verb, note=note), "choosing have, make or find")
    assert decisions_bytes(run_dir) == b""
    assert [one.item_id for one in read_queue(run_dir).open_items()] == [ITEM]


def test_free_text_decides_no_part(tmp_path: Path) -> None:
    run_dir = _run(tmp_path)
    found = outcome_of(
        lambda: record_decision(run_dir, ITEM, decision="I have one", resolved_by="yasin")
    )
    _refused(found, "choosing have, make or find")
    assert decisions_bytes(run_dir) == b""


def test_a_part_s_item_offers_no_other_kind_s_position(tmp_path: Path) -> None:
    run_dir = _run(tmp_path)
    _refused(decide(run_dir, ITEM, "sizing"), "does not offer")
    assert decisions_bytes(run_dir) == b""


def _arbitration(run_dir: Path) -> str:
    """An item of another kind that offers positions, listed beside nothing else."""
    consequence = ItemConsequence(
        attempt=1,
        attempt_commit="c" * 40,
        on_approve="record_only",
        on_reject="record_only",
        why_record_only="source",
        confirmed_indicators=(),
        scan_hits=(),
        on_choose={"sizing": "retry", "domain": "record_only"},
    )
    other = QueueItem(
        item_id="run-1-s1",
        ts=TS,
        run_id=RUN_ID,
        subtask_id="s1",
        source="arbitration",
        decision_required="Decide which value stands.",
        artefact_diff="",
        triggering_finding="a dispute",
        quantities=(),
        trajectories=("sessions/a/stdout.jsonl",),
        consequence=consequence,
    )
    listed(run_dir, other)
    return other.item_id


@pytest.mark.parametrize("position", ["have", "make", "find"])
def test_no_other_kind_of_item_takes_a_part_s_choice(tmp_path: Path, position: str) -> None:
    run_dir = tmp_path / "run"
    other = _arbitration(run_dir)
    parts = None if position == "find" else body(MASS)
    _refused(decide(run_dir, other, position, parts), "does not offer")
    assert decisions_bytes(run_dir) == b""


def test_a_choice_is_bound_to_the_view_it_was_taken_on(tmp_path: Path) -> None:
    run_dir = _run(tmp_path)
    stale = shown(run_dir, ITEM).model_copy(update={"item_sha256": "0" * 64})
    found = outcome_of(
        lambda: record_decision(
            run_dir, ITEM, person=person("have", body(MASS)), resolved_by="yasin", shown=stale
        )
    )
    assert isinstance(found, StaleViewError), found
    assert decisions_bytes(run_dir) == b""
    unbound = outcome_of(
        lambda: record_decision(run_dir, ITEM, person=person("find"), resolved_by="yasin")
    )
    _refused(unbound, "bound to the view")


def test_a_choice_binds_whatever_the_stream_s_seal_reads(tmp_path: Path) -> None:
    # The values are the person's own, never a session's: no stream vouches for them.
    run_dir = _run(tmp_path)
    assert shown(run_dir, ITEM).trajectories == ("no_seal",)
    assert isinstance(decide(run_dir, ITEM, "have", body(MASS)), QueueResolution)


# --- each value: its name, its unit, its dimension -------------------------------------------


@pytest.mark.parametrize(
    ("name", "value", "unit"),
    [
        ("mass", 0.4, "kg"),
        ("mass", 400, "g"),
        ("stall_current", 2.4, "A"),
        ("energy_capacity", 20, "W*h"),
        # Outside any plausible range, and still a quantity of its kind: the gate judges that.
        ("efficiency", 1.5, "1"),
        # A name the catalogue does not know is admitted, in any unit the gate reads.
        ("fnord", 3, "m"),
    ],
)
def test_a_value_of_its_kind_s_dimension_is_recorded(
    tmp_path: Path, name: str, value: float, unit: str
) -> None:
    run_dir = _run(tmp_path)
    line = decide(run_dir, ITEM, "have", body({name: (value, unit)}))
    assert isinstance(line, QueueResolution), line
    assert json.loads(decisions_bytes(run_dir))["parts"]["declared"][name] == {
        "value": value,
        "unit": unit,
    }


@pytest.mark.parametrize(
    ("name", "value", "unit", "said"),
    [
        ("mass", 0.4, "A", "mass"),  # another dimension than the kind's
        ("stall_current", 2.4, "kg", "stall_current"),
        ("efficiency", 0.9, "W", "efficiency"),
        ("mass", -0.4, "kg", "never negative"),  # the kind's sign
        ("mass", 0.4, "", "unit"),  # no unit at all
        ("mass", 0.4, " ", "unit"),
        ("mass", 0.4, "10**10**10*kg", "unit"),  # arithmetic no parser is handed
        ("fnord", 3, "10**10**10*m", "unit"),
        ("fnord", 3, "notaunit", "fnord"),
        ("stall_currnt", 2.4, "A", "shadows"),  # one letter from a relation's quantity
        ("Mass", 0.4, "kg", "pattern"),
        ("mass.total", 0.4, "kg", "pattern"),
    ],
)
def test_a_value_that_is_not_one_of_its_kind_is_refused_and_nothing_is_written(
    tmp_path: Path, name: str, value: float, unit: str, said: str
) -> None:
    run_dir = _run(tmp_path)
    found = outcome_of(lambda: decide(run_dir, ITEM, "have", body({name: (value, unit)})))
    _refused(found, said)
    assert decisions_bytes(run_dir) == b""
    assert [one.item_id for one in read_queue(run_dir).open_items()] == [ITEM]


@pytest.mark.parametrize("value", [float("nan"), float("inf"), -float("inf"), True, "0.4", None])
def test_a_value_is_a_finite_number(tmp_path: Path, value: Any) -> None:  # noqa: ANN401
    run_dir = _run(tmp_path)
    found = outcome_of(lambda: decide(run_dir, ITEM, "have", body({"mass": (value, "kg")})))
    assert isinstance(found, Exception), found
    assert decisions_bytes(run_dir) == b""


def test_a_wrong_value_beside_a_good_one_refuses_the_whole_decision(tmp_path: Path) -> None:
    run_dir = _run(tmp_path)
    both = {"mass": (0.4, "kg"), "stall_current": (2, "V")}
    _refused(outcome_of(lambda: decide(run_dir, ITEM, "have", body(both))), "stall_current")
    assert decisions_bytes(run_dir) == b""


# --- the bounds, each crossed by one ---------------------------------------------------------


def _names(count: int) -> dict[str, tuple[float, str]]:
    return {f"own_note_{k}": (1.0, "m") for k in range(count)}


def test_a_body_holds_at_most_twelve_values(tmp_path: Path) -> None:
    assert named("MAX_DECLARED") == 12
    run_dir = _run(tmp_path)
    over = outcome_of(lambda: decide(run_dir, ITEM, "have", body(_names(13))))
    assert isinstance(over, Exception), over
    assert decisions_bytes(run_dir) == b""
    assert isinstance(decide(run_dir, ITEM, "have", body(_names(12))), QueueResolution)


def test_a_body_holds_at_most_eight_texts_of_five_hundred_characters(tmp_path: Path) -> None:
    assert (named("MAX_TEXTS"), named("MAX_TEXT")) == (8, 500)
    run_dir = listed(tmp_path / "run", item(MOTOR, 1, 2), item(IMU, 2, 2))

    def over(texts: tuple[str, ...]) -> Any:  # noqa: ANN401 - a line, or why there is none
        return outcome_of(lambda: decide(run_dir, ITEM, "make", body(texts=texts)))

    for texts in (("a",) * 9, ("x" * 501,)):
        assert isinstance(over(texts), Exception), texts
    assert decisions_bytes(run_dir) == b""
    assert isinstance(decide(run_dir, ITEM, "make", body(texts=("a",) * 8)), QueueResolution)
    longest = decide(run_dir, "run-1-parts-2", "make", body(texts=("x" * 500,)))
    assert isinstance(longest, QueueResolution), longest


@pytest.mark.parametrize(
    "text",
    ["", "   ", "line\x1b[2Jcleared", "right‮left", "a b", "<<<DATA", "ends >>>"],
)
def test_a_text_is_held_to_the_rules_a_note_is(tmp_path: Path, text: str) -> None:
    run_dir = _run(tmp_path)
    found = outcome_of(lambda: decide(run_dir, ITEM, "make", body(texts=(text,))))
    assert isinstance(found, Exception), found
    assert decisions_bytes(run_dir) == b""


# --- every read holds a line to what the writer writes ---------------------------------------


def _line(tmp_path: Path, **changes: Any) -> Path:  # noqa: ANN401
    """A run whose decisions file holds one line no call of the function wrote."""
    run_dir = _run(tmp_path)
    line: dict[str, Any] = {
        "item_id": ITEM,
        "ts": TS,
        "kind": "resolution",
        "decision": "choose have",
        "resolved_by": "yasin",
        "verb": "choose",
        "position": "have",
        "shown_sha256": read_queue(run_dir).digests[ITEM],
        "parts": {"declared": {"mass": {"value": 0.4, "unit": "kg"}}, "texts": []},
    }
    line.update(changes)
    kept = {key: value for key, value in line.items() if value is not None}
    (run_dir / "queue_decisions.jsonl").write_text(json.dumps(kept, separators=(",", ":")) + "\n")
    return run_dir


def test_a_line_as_the_writer_writes_it_is_read(tmp_path: Path) -> None:
    assert "parts" in QueueResolution.model_fields, "a decision's line carries no parts body"
    run_dir = _line(tmp_path)
    ((_, read),) = read_queue(run_dir).decisions
    assert read.parts.declared["mass"].unit == "kg"  # type: ignore[attr-defined, unused-ignore]


@pytest.mark.parametrize(
    "changes",
    [
        {"parts": {"declared": {"mass": {"value": 0.4, "unit": "A"}}, "texts": []}},
        {"parts": {"declared": {"stall_currnt": {"value": 1, "unit": "A"}}, "texts": []}},
        {"parts": {"declared": {"mass": {"value": 0.4}}, "texts": []}},  # a bare number
        {"parts": {"declared": {"mass": 0.4}, "texts": []}},
        {"parts": {"declared": {}, "texts": []}},
        {"parts": {"declared": {"mass": {"value": 0.4, "unit": "kg"}}}},  # not the one form
        {"parts": None},
        {"position": "find", "decision": "choose find"},  # a body where find states nothing
        {"verb": "approve", "position": None, "decision": "approve"},  # a body with no choice
    ],
)
def test_a_line_the_writer_would_refuse_is_never_read(
    tmp_path: Path, changes: dict[str, Any]
) -> None:
    assert "parts" in QueueResolution.model_fields, "a decision's line carries no parts body"
    run_dir = _line(tmp_path, **changes)
    found = outcome_of(lambda: read_queue(run_dir))
    assert isinstance(found, QueueError), found


def test_an_approve_on_a_part_s_line_reads_and_is_the_run_s_to_refuse(tmp_path: Path) -> None:
    # The decisions file is a person's: a line no function wrote that is a well-formed approve
    # reads, as one on a plan's item does, and the run that takes it refuses it.
    run_dir = _line(tmp_path, verb="approve", position=None, decision="approve", parts=None)
    ((_, read),) = read_queue(run_dir).decisions
    assert read.verb == "approve"


# --- the body's digest ------------------------------------------------------------------------


def test_the_body_s_digest_is_of_its_canonical_form() -> None:
    digest = named("parts_sha256")
    stated = body({"stall_current": (2.4, "A"), "mass": (0.4, "kg")}, ("as is",))
    canonical = json.dumps(
        {
            "declared": {
                "mass": {"unit": "kg", "value": 0.4},
                "stall_current": {"unit": "A", "value": 2.4},
            },
            "texts": ["as is"],
        },
        sort_keys=True,
        separators=(",", ":"),
    )
    assert digest(stated) == hashlib.sha256(canonical.encode()).hexdigest()
    reordered = body({"mass": (0.4, "kg"), "stall_current": (2.4, "A")}, ("as is",))
    assert digest(reordered) == digest(stated)
    assert digest(body({"mass": (0.5, "kg")})) != digest(body({"mass": (0.4, "kg")}))
    assert digest(body({"mass": (0.4, "kg")}, ("a", "b"))) != digest(
        body({"mass": (0.4, "kg")}, ("b", "a"))
    )
