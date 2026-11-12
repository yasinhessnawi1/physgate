"""A run that asks which parts a person has dispatches nothing until every part is decided.

ARCH-122. The run lists one item per component of its plan, once the plan's own hold, if it
has one, is released, and lists them again at every drive, so a process killed before it listed
them loses none. While one is undecided the loop waits and the replay refuses any dispatch.
Each choice is taken into the run's record as one line, naming the digest of the values it
stated; a plan with no component holds nothing.

Approve, reject and free text decide no part: the run that finds such a line on a part's item
halts on it, and the replay refuses a taken line that is not a bound choice of a position the
item offers.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest
from design_review_rig import refusal
from parts_rig import (
    COMPONENTS,
    PLAN_DIGEST,
    SPEC_COMMIT,
    STREAM,
    body,
    decide,
    dispatch,
    find_all,
    item,
    log_of,
    named,
    opened,
    opened_reviewed,
    parts_items,
    rig,
    started,
    taken,
)
from plan_hold_rig import again, dispatched, items, kinds, outcome_of
from plan_hold_rig import decide as decide_plan

from physgate.orchestrator.loop import Loop
from physgate.orchestrator.queue import QueueResolution, read_queue

IDS = ["run-1-parts-1", "run-1-parts-2", "run-1-parts-3"]
HELD = "while a part is undecided"
NOT_A_CHOICE = "a part's item"


def _waiting(tmp_path: Path) -> Path:
    the_rig = started(tmp_path / "run")
    assert again(the_rig) == "wait"
    return the_rig.run_dir


def _taken(run_dir: Path) -> list[dict[str, Any]]:
    return [one for one in log_of(run_dir) if one["kind"] == "decision_taken"]


# --- the hold in the loop --------------------------------------------------------------------


def test_one_item_per_component_is_listed_before_any_dispatch_and_the_run_waits(
    tmp_path: Path,
) -> None:
    run_dir = _waiting(tmp_path)
    assert [one.item_id for one in parts_items(run_dir)] == IDS
    assert [one.item_id for one in items(run_dir)] == IDS
    assert dispatched(run_dir) == []


def test_each_item_is_the_one_the_record_builds_for_its_component(tmp_path: Path) -> None:
    run_dir = _waiting(tmp_path)
    decomposed = next(one for one in log_of(run_dir) if one["kind"] == "decomposed")
    for number, (listed, component) in enumerate(
        zip(parts_items(run_dir), COMPONENTS, strict=True), start=1
    ):
        expected = item(component, number, 3).model_copy(update={"ts": decomposed["ts"]})
        assert listed == expected
        assert PLAN_DIGEST in listed.artefact_diff and SPEC_COMMIT in listed.artefact_diff
        assert listed.trajectories == (STREAM,)


def test_a_process_that_died_before_it_listed_the_items_loses_none(tmp_path: Path) -> None:
    the_rig = started(tmp_path / "run")
    assert items(the_rig.run_dir) == []  # the opening wrote the plan and listed nothing
    assert again(the_rig) == "wait"
    assert [one.item_id for one in items(the_rig.run_dir)] == IDS
    assert again(rig(the_rig.run_dir)) == "wait"  # and a third process lists none twice
    assert [one.item_id for one in items(the_rig.run_dir)] == IDS


def test_the_run_waits_while_one_part_is_undecided(tmp_path: Path) -> None:
    run_dir = _waiting(tmp_path)
    assert isinstance(decide(run_dir, IDS[0], "find"), QueueResolution)
    assert isinstance(decide(run_dir, IDS[2], "have", body({"mass": (0.1, "kg")})), QueueResolution)
    assert again(rig(run_dir)) == "wait"
    assert dispatched(run_dir) == []
    assert [one["item_id"] for one in _taken(run_dir)] == [IDS[0], IDS[2]]
    assert [one.item_id for one in read_queue(run_dir).open_items()] == [IDS[1]]


def test_the_last_decision_releases_the_run(tmp_path: Path) -> None:
    run_dir = _waiting(tmp_path)
    find_all(run_dir)
    assert again(rig(run_dir)) == "done"
    assert "stage_entered" in dispatched(run_dir)
    assert "incident" not in kinds(run_dir)
    # Nothing was dispatched before the last of the three was taken.
    order = kinds(run_dir)
    last_taken = max(i for i, kind in enumerate(order) if kind == "decision_taken")
    assert order.index("stage_entered") > last_taken
    assert order.count("decision_taken") == 3


def test_each_choice_is_taken_as_one_line_naming_what_it_stated(tmp_path: Path) -> None:
    run_dir = _waiting(tmp_path)
    stated = body({"mass": (0.4, "kg"), "stall_current": (2.4, "A")})
    made = body(texts=("printed in PETG",))
    assert isinstance(decide(run_dir, IDS[0], "have", stated), QueueResolution)
    assert isinstance(decide(run_dir, IDS[1], "make", made, note="mine"), QueueResolution)
    assert isinstance(decide(run_dir, IDS[2], "find"), QueueResolution)
    assert again(rig(run_dir)) == "done"
    have, make, find = _taken(run_dir)
    digest = named("parts_sha256")
    assert (have["position"], have["effect"], have["acts"]) == ("have", "declare", True)
    assert have["parts_sha256"] == digest(stated)
    assert (make["position"], make["effect"], make["note"]) == ("make", "declare", "mine")
    assert make["parts_sha256"] == digest(made)
    assert (find["position"], find["effect"], find["acts"]) == ("find", "find", True)
    assert "parts_sha256" not in find  # left out where nothing was stated
    for line in (have, make, find):
        assert (line["subtask_id"], line["attempt"], line["why_not"]) == (None, None, None)
        assert line["shown_sha256"] == read_queue(run_dir).digests[line["item_id"]]


def test_a_decision_taken_once_is_not_taken_again(tmp_path: Path) -> None:
    run_dir = _waiting(tmp_path)
    assert isinstance(decide(run_dir, IDS[0], "find"), QueueResolution)
    assert again(rig(run_dir)) == "wait"
    assert again(rig(run_dir)) == "wait"
    assert len(_taken(run_dir)) == 1


def test_a_plan_with_no_component_holds_nothing(tmp_path: Path) -> None:
    the_rig = started(tmp_path / "run", components=())
    assert again(the_rig) == "done"
    assert items(the_rig.run_dir) == []
    assert "stage_entered" in dispatched(the_rig.run_dir)


def test_a_run_that_does_not_ask_lists_no_part(tmp_path: Path) -> None:
    the_rig = rig(tmp_path / "run", parts="off")
    loop = outcome_of(lambda: opened(the_rig, None))
    assert isinstance(loop, Loop), loop
    loop.close()
    assert again(the_rig) == "done"
    assert items(the_rig.run_dir) == []


# --- the plan's own hold comes first ---------------------------------------------------------


def _plan_held(tmp_path: Path) -> Path:
    the_rig = rig(tmp_path / "run", design_review="on")
    loop = outcome_of(lambda: opened_reviewed(the_rig))
    assert isinstance(loop, Loop), loop
    loop.close()
    assert again(the_rig) == "wait"
    return the_rig.run_dir


def test_the_parts_are_listed_only_once_the_plan_s_hold_is_released(tmp_path: Path) -> None:
    run_dir = _plan_held(tmp_path)
    assert [one.source for one in items(run_dir)] == ["plan_review"]
    decide_plan(run_dir, "approve")
    assert again(rig(run_dir, design_review="on")) == "wait"
    assert [one.item_id for one in parts_items(run_dir)] == IDS
    assert dispatched(run_dir) == []
    find_all(run_dir)
    assert again(rig(run_dir, design_review="on")) == "done"
    assert "stage_entered" in dispatched(run_dir)


def test_a_rejected_plan_lists_no_part(tmp_path: Path) -> None:
    run_dir = _plan_held(tmp_path)
    decide_plan(run_dir, "reject", "the bus has no protection")
    assert again(rig(run_dir, design_review="on")) == "done"
    assert parts_items(run_dir) == []
    assert "stage_entered" not in kinds(run_dir)


# --- a line no function wrote ----------------------------------------------------------------


def _forged(run_dir: Path, **fields: Any) -> None:  # noqa: ANN401
    line: dict[str, Any] = {
        "item_id": IDS[0],
        "ts": "2026-11-12T10:00:00.000000Z",
        "kind": "resolution",
        "resolved_by": "yasin",
        "shown_sha256": read_queue(run_dir).digests[IDS[0]],
    }
    line.update(fields)
    kept = {key: value for key, value in line.items() if value is not None}
    # Appended by hand, in the one form the queue's writer writes: the reader refuses a line
    # in any other, and this row is about a line it reads and the run refuses.
    written = QueueResolution.model_validate(kept).model_dump_json()
    with (run_dir / "queue_decisions.jsonl").open("a") as handle:
        handle.write(written + "\n")


@pytest.mark.parametrize(
    "fields",
    [
        {"decision": "approve", "verb": "approve"},
        {"decision": "reject: no", "verb": "reject", "note": "no"},
        {"decision": "I have one", "shown_sha256": None},
    ],
)
def test_a_line_that_is_no_choice_halts_the_run_and_releases_nothing(
    tmp_path: Path, fields: dict[str, Any]
) -> None:
    run_dir = _waiting(tmp_path)
    for other in IDS[1:]:
        assert isinstance(decide(run_dir, other, "find"), QueueResolution)
    _forged(run_dir, **fields)
    assert again(rig(run_dir)) == "halted"
    assert dispatched(run_dir) == []
    incident = next(one for one in log_of(run_dir) if one["kind"] == "incident")
    assert incident["cause"] == "queue_item_mismatch"
    assert IDS[0] not in [one["item_id"] for one in _taken(run_dir)]


# --- the hold in the replay ------------------------------------------------------------------


def _log(tmp_path: Path, components: Any = COMPONENTS) -> list[dict[str, Any]]:  # noqa: ANN401
    the_rig = started(tmp_path / "run", components=components)
    log = log_of(the_rig.run_dir)
    assert refusal(tmp_path, log) == ""  # the opening as written follows
    return log


def test_a_dispatch_while_a_part_is_undecided_is_refused(tmp_path: Path) -> None:
    log = _log(tmp_path)
    assert HELD in refusal(tmp_path, [*log, dispatch(log)])
    two = [*log, taken(log, 1), taken(log, 2, "have")]
    assert refusal(tmp_path, two) == ""
    assert HELD in refusal(tmp_path, [*two, dispatch(log)])


def test_the_integration_call_is_held_as_a_dispatch_is(tmp_path: Path) -> None:
    log = _log(tmp_path)
    skip = {**dispatch(log), "kind": "integration_gate_skipped", "reason": "not_all_merged"}
    skip = {k: v for k, v in skip.items() if k not in ("subtask_id", "attempt", "stage")}
    assert HELD in refusal(tmp_path, [*log, {**skip, "subtasks": ["s1", "s2"]}])


def test_a_dispatch_follows_the_last_part_s_decision(tmp_path: Path) -> None:
    log = _log(tmp_path)
    all_three = [*log, taken(log, 1), taken(log, 2, "have"), taken(log, 3, "make")]
    assert refusal(tmp_path, [*all_three, dispatch(log)]) == ""


def test_a_plan_with_no_component_is_dispatched_at_once(tmp_path: Path) -> None:
    log = _log(tmp_path, components=())
    assert refusal(tmp_path, [*log, dispatch(log)]) == ""


@pytest.mark.parametrize(
    "fields",
    [
        {
            "verb": "approve",
            "position": ...,
            "effect": "none",
            "acts": False,
            "why_not": "record_only_source",
        },
        {
            "verb": "reject",
            "position": ...,
            "note": "no",
            "effect": "none",
            "acts": False,
            "why_not": "record_only_source",
        },
        {
            "verb": None,
            "position": ...,
            "shown_sha256": None,
            "effect": "none",
            "acts": False,
            "why_not": "not_bound",
        },
        {"position": "sizing", "effect": "retry"},
        {"effect": "declare"},  # find declares nothing
        {"effect": "none", "acts": False, "why_not": "record_only_source"},
        {"acts": False, "why_not": "held_os_layer_off"},
        {"shown_sha256": None},
        {"subtask_id": "s1"},
        {"attempt": 1},
        {"attempt_commit": "c" * 40},
        {"parts_sha256": "b" * 64},  # find states nothing
    ],
)
def test_a_taken_line_on_a_part_is_a_bound_choice_and_nothing_else(
    tmp_path: Path, fields: dict[str, Any]
) -> None:
    log = _log(tmp_path)
    assert refusal(tmp_path, [*log, taken(log, 1)]) == ""
    found = refusal(tmp_path, [*log, taken(log, 1, **fields)])
    assert found != "", fields


@pytest.mark.parametrize(
    "fields",
    [
        {"position": "have", "effect": "find"},
        {"position": "make", "effect": "find"},
        {"position": "have", "parts_sha256": ...},  # have states values: their digest is named
        {"position": "make", "parts_sha256": ...},
    ],
)
def test_a_taken_have_or_make_declares_and_names_its_digest(
    tmp_path: Path, fields: dict[str, Any]
) -> None:
    log = _log(tmp_path)
    position = fields["position"]
    assert refusal(tmp_path, [*log, taken(log, 1, position)]) == ""
    assert refusal(tmp_path, [*log, taken(log, 1, **fields)]) != "", fields


def test_what_a_taken_line_on_a_part_is_refused_for(tmp_path: Path) -> None:
    log = _log(tmp_path)
    approve = taken(
        log,
        1,
        verb="approve",
        position=...,
        effect="none",
        acts=False,
        why_not="record_only_source",
    )
    said = refusal(tmp_path, [*log, approve])
    assert NOT_A_CHOICE in said
    assert "choice of have, make or find" in said  # refused as no choice, not as a bad one
    assert "taken once" in refusal(tmp_path, [*log, taken(log, 1), taken(log, 1)])


def test_a_part_is_decided_only_once_the_plan_s_hold_is_released(tmp_path: Path) -> None:
    the_rig = rig(tmp_path / "run", design_review="on")
    loop = outcome_of(lambda: opened_reviewed(the_rig))
    assert isinstance(loop, Loop), loop
    loop.close()
    log = log_of(the_rig.run_dir)
    assert refusal(tmp_path, log) == ""
    assert "the plan" in refusal(tmp_path, [*log, taken(log, 1)])


# --- the record says whether the run asks, and of which parts --------------------------------


def test_a_run_that_asks_acts_on_decisions(tmp_path: Path) -> None:
    log = _log(tmp_path)
    assert (log[0]["kind"], log[0]["parts_on_hand"], log[0]["queue_decisions"]) == (
        "run_started",
        "on",
        "act",
    )
    recording = {k: v for k, v in log[0].items() if k != "queue_decisions"}
    assert "acts on" in refusal(tmp_path, [recording, *log[1:]])


def test_the_decomposition_s_line_names_the_components_exactly_when_the_run_asks(
    tmp_path: Path,
) -> None:
    log = _log(tmp_path)
    at = next(i for i, one in enumerate(log) if one["kind"] == "decomposed")
    assert [one["node"] for one in log[at]["components"]] == [c.node for c in COMPONENTS]
    bare = {k: v for k, v in log[at].items() if k != "components"}
    assert "components" in refusal(tmp_path, [*log[:at], bare, *log[at + 1 :]])
    silent = [{k: v for k, v in log[0].items() if k != "parts_on_hand"}, *log[1:]]
    assert "components" in refusal(tmp_path, silent)
