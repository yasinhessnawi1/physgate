"""A run that asks writes what the parts decisions stated, then releases, then dispatches.

ARCH-122. Once every part is decided the loop writes each part's stated values onto its node
(the component's own names on the component's node, the plan's shared names on the node sizing
holds for it), each behind an intent, through the store's ``declare``; then one release line
names every component with what it stated and the record a role reads. Replay derives each
payload and the record from the plan and the decisions, and refuses a write or a release that is
not that derivation, and a dispatch before the release.
"""

from __future__ import annotations

import hashlib
from pathlib import Path
from typing import Any

import pytest
from design_review_rig import refusal
from parts_rig import (
    COMPONENTS,
    body,
    decide,
    dispatch,
    find_all,
    log_of,
    rig,
    started,
)
from plan_hold_rig import again, dispatched, kinds

from physgate.orchestrator.queue import QueueResolution

IDS = ["run-1-parts-1", "run-1-parts-2", "run-1-parts-3"]
UNRELEASED = "before the parts are released"
STATED = {"mass": (0.4, "kg"), "stall_current": (2.4, "A")}
SIZING_NODE = "sizing.control_motor_left"


def _decided(tmp_path: Path) -> Path:
    """A run whose three parts are decided as have, make and find, and that has not run on."""
    return _decided_with(tmp_path)[0]


def _decided_with(tmp_path: Path) -> tuple[Path, Any]:
    the_rig = started(tmp_path / "run")
    assert again(the_rig) == "wait"
    run_dir = the_rig.run_dir
    assert isinstance(decide(run_dir, IDS[0], "have", body(STATED)), QueueResolution)
    made = body({"mass": (0.1, "kg")}, texts=("printed in PETG",))
    assert isinstance(decide(run_dir, IDS[1], "make", made), QueueResolution)
    assert isinstance(decide(run_dir, IDS[2], "find"), QueueResolution)
    return run_dir, the_rig


def _run(tmp_path: Path) -> tuple[Path, Any]:
    run_dir, the_rig = _decided_with(tmp_path)
    assert again(the_rig) == "done"
    return run_dir, the_rig


def _of(log: list[dict[str, Any]], kind: str) -> list[dict[str, Any]]:
    return [one for one in log if one["kind"] == kind]


def _first(log: list[dict[str, Any]], kind: str) -> dict[str, Any]:
    found = _of(log, kind)
    assert found, f"the log holds no {kind} line"
    return found[0]


# --- the loop ---------------------------------------------------------------------------------


def test_each_stated_value_is_written_once_behind_an_intent_and_the_run_is_released(
    tmp_path: Path,
) -> None:
    run_dir, _ = _run(tmp_path)
    log = log_of(run_dir)
    intended = _of(log, "parts_write_intended")
    assert [one["node_id"] for one in intended] == [
        "control.motor_left",
        SIZING_NODE,
        "control.imu",
    ]
    assert [one["item_id"] for one in intended] == [IDS[0], IDS[0], IDS[1]]
    assert [one["expected_revision"] for one in intended] == [2, 3, 4]
    assert [one["revision"] for one in _of(log, "parts_write_done")] == [2, 3, 4]
    order = kinds(run_dir)
    assert order.count("parts_released") == 1
    assert order.index("parts_released") > max(
        i for i, k in enumerate(order) if k == "parts_write_done"
    )
    assert order.index("stage_entered") > order.index("parts_released")
    assert "incident" not in order


def test_a_value_is_written_where_the_plan_says_and_carries_its_decision(tmp_path: Path) -> None:
    run_dir, the_rig = _run(tmp_path)
    assert len(the_rig.diff.declared) == 3
    own, shared, made = the_rig.diff.declared
    assert (own["id"], own["kind"], own["domain"], own["owner_role"]) == (
        "control.motor_left",
        "component",
        "control",
        "control",
    )
    assert set(own["quantities"]) == {"mass"}
    assert (shared["id"], shared["domain"], shared["owner_role"]) == (
        SIZING_NODE,
        "cross",
        "sizing",
    )
    assert set(shared["quantities"]) == {"stall_current"}
    assert shared["constrains"] == ["control.motor_left"]
    quantity = own["quantities"]["mass"]
    assert (quantity["value"], quantity["unit"]) == (0.4, "kg")
    assert quantity["source"] == "declared by the person"
    assert quantity["written_by"] == "control"
    taken = _first(log_of(run_dir), "decision_taken")
    assert quantity["declared"] == {
        "item_id": IDS[0],
        "decision_sha256": taken["parts_sha256"],
        "operator": "yasin",
    }
    assert quantity["declared"]["item_id"] == IDS[0]
    assert set(made["quantities"]) == {"mass"}


def test_a_part_to_find_is_written_nowhere_and_a_text_only_body_writes_nothing(
    tmp_path: Path,
) -> None:
    run_dir = _decided_only(tmp_path, "make", body(texts=("printed in PETG",)))
    assert again(rig(run_dir)) == "done"
    log = log_of(run_dir)
    assert _of(log, "parts_write_intended") == []
    released = _first(log, "parts_released")
    assert [c["choice"] for c in released["components"]] == ["make", "find", "find"]


def test_an_empty_plan_says_that_it_asked_with_one_release(tmp_path: Path) -> None:
    the_rig = started(tmp_path / "run", components=())
    assert again(the_rig) == "done"
    log = log_of(the_rig.run_dir)
    released = _of(log, "parts_released")
    assert len(released) == 1
    assert released[0]["components"] == []
    record = b'{"components":[]}'
    assert released[0]["record_sha256"] == hashlib.sha256(record).hexdigest()
    assert released[0]["record_length"] == len(record)
    assert "stage_entered" in dispatched(the_rig.run_dir)


def test_the_release_names_the_record_a_role_reads(tmp_path: Path) -> None:
    run_dir, _ = _run(tmp_path)
    released = _first(log_of(run_dir), "parts_released")
    assert [c["node"] for c in released["components"]] == [c.node for c in COMPONENTS]
    assert [c["choice"] for c in released["components"]] == ["have", "make", "find"]
    assert released["components"][2]["parts"] is None
    assert released["components"][0]["parts"]["declared"]["mass"] == {"value": 0.4, "unit": "kg"}
    assert released["record_length"] > 1


def test_the_run_is_released_once_and_a_resume_writes_nothing_again(tmp_path: Path) -> None:
    run_dir, the_rig = _run(tmp_path)
    before = log_of(run_dir)
    # The next process reads the same journal: the store outlives the process that wrote it.
    assert again(the_rig) == "done"
    after = log_of(run_dir)
    for kind in ("parts_write_intended", "parts_write_done", "parts_released"):
        assert len(_of(after, kind)) == len(_of(before, kind))


def test_a_process_killed_between_an_intent_and_its_write_intends_the_same_write(
    tmp_path: Path,
) -> None:
    run_dir, the_rig = _decided_with(tmp_path)
    assert again(the_rig, kill_after="parts_write_intended") == "killed"
    first = _of(log_of(run_dir), "parts_write_intended")
    assert len(first) == 1
    assert the_rig.diff.declared == []
    assert again(the_rig) == "done"
    log = log_of(run_dir)
    # The first process wrote nothing; the next intends the same node again and the run goes on.
    assert [one["node_id"] for one in _of(log, "parts_write_intended")][0:2] == [
        "control.motor_left",
        "control.motor_left",
    ]
    assert len(_of(log, "parts_write_done")) == 3
    assert len(_of(log, "parts_released")) == 1
    assert "incident" not in kinds(run_dir)


def test_a_process_killed_after_a_write_and_before_its_release_writes_nothing_twice(
    tmp_path: Path,
) -> None:
    run_dir, the_rig = _decided_with(tmp_path)
    assert again(the_rig, kill_after="parts_write_done") == "killed"
    assert again(the_rig) == "done"
    log = log_of(run_dir)
    nodes = [one["node_id"] for one in _of(log, "parts_write_intended")]
    assert len(nodes) == len(set(nodes)) == 3
    assert len(_of(log, "parts_released")) == 1


def test_a_decisions_file_that_no_longer_states_what_was_taken_halts_the_run(
    tmp_path: Path,
) -> None:
    run_dir = _decided(tmp_path)
    assert again(rig(run_dir), kill_after="decision_taken") == "killed"
    path = run_dir / "queue_decisions.jsonl"
    text = path.read_text().replace('"value":0.4', '"value":0.5')
    path.write_text(text)
    again(rig(run_dir))
    assert "incident" in kinds(run_dir) or _of(log_of(run_dir), "parts_released") == []
    assert _of(log_of(run_dir), "parts_write_intended") == []


# --- replay -----------------------------------------------------------------------------------


def _released_log(tmp_path: Path) -> list[dict[str, Any]]:
    run_dir, _ = _run(tmp_path)
    log = log_of(run_dir)
    cut = next(i for i, one in enumerate(log) if one["kind"] == "stage_entered")
    assert refusal(tmp_path, log[:cut]) == ""
    return log[:cut]


def _index(log: list[dict[str, Any]], kind: str, nth: int = 0) -> int:
    found = [i for i, one in enumerate(log) if one["kind"] == kind]
    assert len(found) > nth, f"the log holds no {kind} line number {nth}"
    return found[nth]


def _edited(
    log: list[dict[str, Any]],
    kind: str,
    nth: int = 0,
    **fields: Any,  # noqa: ANN401
) -> list[dict[str, Any]]:
    at = _index(log, kind, nth)
    return [*log[:at], {**log[at], **fields}, *log[at + 1 :]]


def test_a_dispatch_before_the_release_is_refused(tmp_path: Path) -> None:
    log = _released_log(tmp_path)
    cut = _index(log, "parts_released")
    assert UNRELEASED in refusal(tmp_path, [*log[:cut], dispatch(log)])
    assert refusal(tmp_path, [*log, dispatch(log)]) == ""


def test_a_release_before_the_writes_have_landed_is_refused(tmp_path: Path) -> None:
    log = _released_log(tmp_path)
    cut = _index(log, "parts_write_intended")
    assert refusal(tmp_path, [*log[:cut], log[_index(log, "parts_released")]]) != ""


def test_a_release_after_all_but_one_write_is_refused(tmp_path: Path) -> None:
    log = _released_log(tmp_path)
    last = _index(log, "parts_write_done", 2)
    short = [*log[: last - 1], log[_index(log, "parts_released")]]
    assert refusal(tmp_path, short) != ""


def test_a_second_release_is_refused(tmp_path: Path) -> None:
    log = _released_log(tmp_path)
    assert refusal(tmp_path, [*log, log[_index(log, "parts_released")]]) != ""


@pytest.mark.parametrize(
    "fields",
    [
        {"payload_sha256": "0" * 64},
        {"node_id": "control.other"},
        {"actor_role": "electrical"},
        {"expected_revision": 9},
        {"item_id": IDS[2]},
        {"item_id": "run-1-parts-9"},
    ],
)
def test_a_write_that_is_not_the_derivation_of_its_decision_is_refused(
    tmp_path: Path, fields: dict[str, Any]
) -> None:
    log = _released_log(tmp_path)
    assert refusal(tmp_path, _edited(log, "parts_write_intended", **fields)) != ""


def test_a_write_that_states_another_value_than_the_decision_did_is_refused(
    tmp_path: Path,
) -> None:
    log = _released_log(tmp_path)
    first = log[_index(log, "parts_write_intended")]
    said = {**first["parts"], "declared": {**first["parts"]["declared"]}}
    said["declared"]["mass"] = {"value": 0.5, "unit": "kg"}
    assert "what its decision stated" in refusal(
        tmp_path, _edited(log, "parts_write_intended", parts=said)
    )


def test_a_write_out_of_the_plan_s_order_or_repeated_is_refused(tmp_path: Path) -> None:
    log = _released_log(tmp_path)
    intended, done = _index(log, "parts_write_intended", 1), _index(log, "parts_write_done", 1)
    again_ = [*log[: done + 1], {**log[intended - 0], "expected_revision": 4}]
    assert refusal(tmp_path, again_) != ""
    first = log[_index(log, "parts_write_intended", 0)]
    repeat = [*log[: done + 1], {**first, "expected_revision": 4}]
    assert refusal(tmp_path, repeat) != ""


def test_a_write_landed_at_another_revision_or_unintended_is_refused(tmp_path: Path) -> None:
    log = _released_log(tmp_path)
    assert refusal(tmp_path, _edited(log, "parts_write_done", revision=7)) != ""
    assert refusal(tmp_path, _edited(log, "parts_write_done", node_id="control.imu")) != ""
    alone = _index(log, "parts_write_intended")
    assert refusal(tmp_path, [*log[:alone], log[_index(log, "parts_write_done")]]) != ""


@pytest.mark.parametrize("field", ["record_sha256", "record_length"])
def test_a_release_whose_record_is_not_the_decisions_is_refused(tmp_path: Path, field: str) -> None:
    log = _released_log(tmp_path)
    changed: Any = "1" * 64 if field == "record_sha256" else 5
    assert "record" in refusal(tmp_path, _edited(log, "parts_released", **{field: changed}))


def test_a_release_that_names_a_part_as_it_was_not_decided_is_refused(tmp_path: Path) -> None:
    log = _released_log(tmp_path)
    released = log[_index(log, "parts_released")]
    swapped = [{**c} for c in released["components"]]
    swapped[0]["choice"] = "make"
    assert refusal(tmp_path, _edited(log, "parts_released", components=swapped)) != ""
    short = released["components"][:2]
    assert refusal(tmp_path, _edited(log, "parts_released", components=short)) != ""
    found = [{**c} for c in released["components"]]
    found[2]["choice"], found[2]["parts"] = "have", released["components"][0]["parts"]
    assert refusal(tmp_path, _edited(log, "parts_released", components=found)) != ""


def test_a_write_before_every_part_is_decided_is_refused(tmp_path: Path) -> None:
    log = _released_log(tmp_path)
    first_taken = _index(log, "decision_taken")
    early = [*log[: first_taken + 1], log[_index(log, "parts_write_intended")]]
    assert refusal(tmp_path, early) != ""


def test_a_plan_with_no_part_is_released_by_a_line_that_names_none(tmp_path: Path) -> None:
    the_rig = started(tmp_path / "run", components=())
    assert again(the_rig) == "done"
    log = log_of(the_rig.run_dir)
    cut = _index(log, "stage_entered")
    assert refusal(tmp_path, log[:cut]) == ""
    assert UNRELEASED in refusal(tmp_path, [*log[: cut - 1], dispatch(log)])
    stray = _edited(log[:cut], "parts_released", record_length=2)
    assert refusal(tmp_path, stray) != ""


# --- each refusal of the replay is pinned by its own reason ---------------------------------------
# A line that ends the log is held by the check that names it alone: no later line can refuse it.


def _ending_at(log: list[dict[str, Any]], at: int, **fields: Any) -> list[dict[str, Any]]:  # noqa: ANN401
    return [*log[:at], {**log[at], **fields}]


def test_an_intent_for_a_revision_that_does_not_follow_the_journal_s_is_refused(
    tmp_path: Path,
) -> None:
    log = _released_log(tmp_path)
    at = _index(log, "parts_write_intended")
    assert "does not follow" in refusal(tmp_path, _ending_at(log, at, expected_revision=9))


def test_an_intent_whose_node_is_not_the_one_its_payload_names_is_refused(tmp_path: Path) -> None:
    log = _released_log(tmp_path)
    at = _index(log, "parts_write_intended", 1)
    assert "not the derivation" in refusal(tmp_path, _ending_at(log, at, node_id="control.other"))


def test_a_cross_node_intended_by_another_role_than_sizing_s_is_refused(tmp_path: Path) -> None:
    from physgate.orchestrator.parts_write import parts_payload
    from physgate.orchestrator.queue import PartsBody
    from physgate.state.store import payload_digest

    log = _released_log(tmp_path)
    at = _index(log, "parts_write_intended", 1)
    taken = log[_index(log, "decision_taken")]
    payload = parts_payload(
        COMPONENTS[0],
        shared=True,
        owner_role="control",
        item_id=IDS[0],
        body=PartsBody.model_validate(
            {**log[at]["parts"], "texts": tuple(log[at]["parts"]["texts"])}
        ),
        operator=taken["resolved_by"],
        decided_ts=taken["decided_ts"],
    )
    assert payload is not None
    forged = _ending_at(log, at, actor_role="control", payload_sha256=payload_digest(payload))
    assert "its cross node by sizing's role" in refusal(tmp_path, forged)


def test_a_write_that_landed_at_another_revision_than_intended_is_refused_by_that_reason(
    tmp_path: Path,
) -> None:
    log = _released_log(tmp_path)
    at = _index(log, "parts_write_done")
    assert "another revision" in refusal(tmp_path, _ending_at(log, at, revision=7))


def test_a_write_that_landed_for_another_node_than_intended_is_refused(tmp_path: Path) -> None:
    log = _released_log(tmp_path)
    at = _index(log, "parts_write_done")
    assert "was not intended" in refusal(tmp_path, _ending_at(log, at, node_id="control.imu"))


def test_a_release_while_a_write_is_not_done_is_refused_by_that_reason(tmp_path: Path) -> None:
    log = _released_log(tmp_path)
    pending = _index(log, "parts_write_intended", 2)
    cut = [*log[: pending + 1], log[_index(log, "parts_released")]]
    assert "while a write is not done" in refusal(tmp_path, cut)


def test_a_release_naming_fewer_components_or_another_choice_is_refused_by_its_reason(
    tmp_path: Path,
) -> None:
    log = _released_log(tmp_path)
    released = log[_index(log, "parts_released")]
    short = released["components"][:2]
    assert "every component" in refusal(tmp_path, _edited(log, "parts_released", components=short))
    swapped = [{**c} for c in released["components"]]
    swapped[0]["choice"] = "make"
    assert "as it was not decided" in refusal(
        tmp_path, _edited(log, "parts_released", components=swapped)
    )


# --- helpers ----------------------------------------------------------------------------------


def _decided_only(tmp_path: Path, position: str, stated: Any) -> Path:  # noqa: ANN401
    the_rig = started(tmp_path / "run")
    assert again(the_rig) == "wait"
    run_dir = the_rig.run_dir
    assert isinstance(decide(run_dir, IDS[0], position, stated), QueueResolution)
    find_all(run_dir)
    return run_dir
