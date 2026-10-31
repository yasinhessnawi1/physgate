"""Replay holds a plan's hold, its decision and a rejected plan's end to what the code writes.

``decompose`` under ``on`` writes the review's line naming the plan's item exactly where the
review did not pass, and lists that item once. Replay refuses the line naming it anywhere else,
any dispatch while the hold is open, a decision on the item that this code could not have taken
(in a run that records only, with a subtask, an attempt or a position, an effect its verb does not
give, a reject that acts with no reason), and a rejected plan's end other than its one rejection
line followed by the integration call skipped as ``plan_rejected``, naming every planned subtask,
with nothing dispatched after it. The decision function refuses a decision on any other item.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest
from design_review_rig import (
    line,
    lines,
    outcome_of,
    refusal,
    result,
    reviewed,
    started,
)
from plan_hold_rig import PRESENT

from physgate.orchestrator.events import read_events
from physgate.orchestrator.queue import read_queue
from physgate.orchestrator.replay import replay

ACT = {"queue_decisions": "act", "os_layer": PRESENT}
ITEM = "run-1-plan"
HELD = "on the plan's item"
DISPATCH_HELD = "while the plan's review holds the run"
REJECTED_ONCE = "a plan is rejected once"
NOTHING_AFTER = "whose plan a person rejected"
SKIPPED = "skipped as plan_rejected"
DECIDED = "the plan's item"


def _run(tmp_path: Path, design_review: str = "on", verdict: str = "fail", **kw: Any) -> Path:
    run_dir = outcome_of(
        lambda: started(
            tmp_path,
            design_review,
            review=lambda d: reviewed(d, result=result(verdict)),
            **{**ACT, **kw},
        )
    )
    assert isinstance(run_dir, Path), run_dir
    return run_dir


def _log(tmp_path: Path, **kw: Any) -> list[dict[str, Any]]:
    log = lines(_run(tmp_path, **kw))
    assert refusal(tmp_path, log) == ""  # the opening as written follows
    return log


def _planned(log: list[dict[str, Any]]) -> tuple[str, ...]:
    return tuple(one["subtask_id"] for one in log if one["kind"] == "subtask_planned")


def _decision(log: list[dict[str, Any]], verb: str = "reject", **fields: Any) -> dict[str, Any]:
    effect = {"approve": "release", "reject": "end_run"}[verb]
    taken: dict[str, Any] = {
        "subtask_id": None,
        "item_id": ITEM,
        "verb": verb,
        "note": "the bus has no protection" if verb == "reject" else None,
        "resolved_by": "yasin",
        "decided_ts": log[-1]["ts"],
        "decision_offset": 0,
        "shown_sha256": "a" * 64,
        "attempt": None,
        "attempt_commit": None,
        "effect": effect,
        "acts": True,
        "why_not": None,
    }
    return line("decision_taken", log[-1], **{**taken, **fields})


def _rejected(log: list[dict[str, Any]]) -> list[dict[str, Any]]:
    return [*log, _decision(log), line("plan_rejected", log[-1], item_id=ITEM)]


def _skip(log: list[dict[str, Any]], reason: str = "plan_rejected", **kw: Any) -> dict[str, Any]:
    subtasks = kw.get("subtasks", _planned(log))
    return line("integration_gate_skipped", log[-1], reason=reason, subtasks=subtasks)


def _dispatch(log: list[dict[str, Any]]) -> dict[str, Any]:
    first = _planned(log)[0]
    return line("stage_entered", log[-1], subtask_id=first, attempt=1, stage="resolve")


def test_decompose_under_on_lists_the_plan_s_item_once_and_holds(tmp_path: Path) -> None:
    run_dir = _run(tmp_path)
    assert lines(run_dir)[-1].get("held_item") == ITEM
    [item] = read_queue(run_dir).open_items()
    assert (item.item_id, item.source, item.subtask_id) == (ITEM, "plan_review", "plan")
    assert item.trajectories == (str(run_dir / "decomposition" / "stdout.jsonl"),)
    state = replay(read_events(run_dir / "events.jsonl"))
    assert state.next_step().kind == "wait"


def test_under_record_decompose_lists_the_item_and_the_run_is_escalated(tmp_path: Path) -> None:
    run_dir = _run(tmp_path, queue_decisions="record", os_layer=None)
    [item] = read_queue(run_dir).open_items()
    assert item.consequence is None
    assert replay(read_events(run_dir / "events.jsonl")).next_step().kind == "escalated"


def test_a_pass_under_on_names_no_item_and_lists_none(tmp_path: Path) -> None:
    run_dir = _run(tmp_path, verdict="pass")
    assert "held_item" not in lines(run_dir)[-1]
    assert read_queue(run_dir).items == []
    assert replay(read_events(run_dir / "events.jsonl")).next_step().kind == "attempt"


# -- the review's line names the item exactly where the plan is held --------------------------


def test_a_held_review_names_the_plan_s_item(tmp_path: Path) -> None:
    log = _log(tmp_path)
    ran = {k: v for k, v in log[-1].items() if k != "held_item"}
    assert HELD in refusal(tmp_path, [*log[:-1], ran])


def test_the_review_names_no_other_item(tmp_path: Path) -> None:
    log = _log(tmp_path)
    assert HELD in refusal(tmp_path, [*log[:-1], {**log[-1], "held_item": "run-1-s1"}])


def test_a_pass_under_on_names_no_item(tmp_path: Path) -> None:
    log = _log(tmp_path, verdict="pass")
    assert HELD in refusal(tmp_path, [*log[:-1], {**log[-1], "held_item": ITEM}])


def test_an_observed_review_holds_nothing(tmp_path: Path) -> None:
    log = _log(tmp_path, design_review="observe")
    assert HELD in refusal(tmp_path, [*log[:-1], {**log[-1], "held_item": ITEM}])


# -- nothing is dispatched while the plan is held, or after it was rejected -------------------


@pytest.mark.parametrize("kind", ["stage", "integration_gate_skipped"])
def test_nothing_is_dispatched_while_the_plan_s_review_holds_the_run(
    tmp_path: Path, kind: str
) -> None:
    log = _log(tmp_path)
    found = _dispatch(log) if kind == "stage" else _skip(log, "not_all_merged")
    assert DISPATCH_HELD in refusal(tmp_path, [*log, found])


def test_an_approve_releases_the_hold(tmp_path: Path) -> None:
    log = _log(tmp_path)
    assert refusal(tmp_path, [*log, _decision(log, "approve"), _dispatch(log)]) == ""


def test_a_rejected_plan_ends_with_its_rejection_and_the_skip(tmp_path: Path) -> None:
    log = _log(tmp_path)
    ended = [*_rejected(log), _skip(log)]
    assert refusal(tmp_path, ended) == ""
    assert NOTHING_AFTER in refusal(tmp_path, [*_rejected(log), _dispatch(log)])
    assert refusal(tmp_path, [*ended, _dispatch(log)]) != ""


def test_a_plan_is_rejected_only_after_a_reject_was_taken(tmp_path: Path) -> None:
    log = _log(tmp_path)
    assert REJECTED_ONCE in refusal(tmp_path, [*log, line("plan_rejected", log[-1], item_id=ITEM)])
    approved = [*log, _decision(log, "approve"), line("plan_rejected", log[-1], item_id=ITEM)]
    assert REJECTED_ONCE in refusal(tmp_path, approved)


def test_a_plan_is_rejected_once(tmp_path: Path) -> None:
    log = _log(tmp_path)
    twice = [*_rejected(log), line("plan_rejected", log[-1], item_id=ITEM)]
    assert REJECTED_ONCE in refusal(tmp_path, twice)


def test_a_rejected_plan_names_its_item(tmp_path: Path) -> None:
    log = _log(tmp_path)
    other = [*log, _decision(log), line("plan_rejected", log[-1], item_id="run-1-s1")]
    assert REJECTED_ONCE in refusal(tmp_path, other)


def test_the_skip_follows_the_rejection(tmp_path: Path) -> None:
    log = _log(tmp_path)
    assert SKIPPED in refusal(tmp_path, [*log, _decision(log), _skip(log)])


@pytest.mark.parametrize(
    "skip",
    [
        lambda log: _skip(log, "not_all_merged"),
        lambda log: _skip(log, "nothing_planned", subtasks=()),
        lambda log: _skip(log, subtasks=_planned(log)[:1]),
    ],
    ids=["not_all_merged", "nothing_planned", "one_subtask"],
)
def test_a_rejected_plan_s_skip_is_plan_rejected_naming_every_planned_subtask(
    tmp_path: Path, skip: Any
) -> None:
    log = _log(tmp_path)
    assert SKIPPED in refusal(tmp_path, [*_rejected(log), skip(log)])


def test_no_skip_is_plan_rejected_in_a_run_whose_plan_was_not_rejected(tmp_path: Path) -> None:
    log = _log(tmp_path, verdict="pass")
    assert SKIPPED in refusal(tmp_path, [*log, _skip(log)])


# -- the decision on the plan's item ---------------------------------------------------------


def test_a_run_that_records_only_takes_no_decision_on_the_plan_s_item(tmp_path: Path) -> None:
    log = _log(tmp_path, queue_decisions="record", os_layer=None)
    assert DECIDED in refusal(tmp_path, [*log, _decision(log, "approve")])


@pytest.mark.parametrize(
    "forged",
    [
        {"verb": "approve", "effect": "end_run"},
        {"effect": "release"},
        {"attempt": 1},
        {"subtask_id": "s1"},
        {"effect": "merge"},
    ],
    ids=["approve_ends", "reject_releases", "attempt", "subtask", "merge"],
)
def test_a_decision_on_the_plan_s_item_does_what_its_verb_gives_and_names_nothing_else(
    tmp_path: Path, forged: dict[str, Any]
) -> None:
    log = _log(tmp_path)
    assert refusal(tmp_path, [*log, _decision(log, **forged)]) != ""
    assert refusal(tmp_path, [*log, _decision(log)]) == ""


def test_a_reject_of_the_plan_that_acts_carries_its_note(tmp_path: Path) -> None:
    log = _log(tmp_path)
    assert "note" in refusal(tmp_path, [*log, _decision(log, note=None)])


def test_a_release_names_the_item_the_plan_holds_on(tmp_path: Path) -> None:
    log = _log(tmp_path)
    other = _decision(log, "approve", item_id=f"{ITEM}-r2")
    assert refusal(tmp_path, [*log, other]) != ""


def test_the_decision_function_refuses_a_decision_on_another_plan_item(tmp_path: Path) -> None:
    from physgate.orchestrator.decisions import decision_effect
    from physgate.orchestrator.exceptions import QueueItemMismatchError
    from physgate.orchestrator.queue import QueueResolution

    run_dir = _run(tmp_path)
    [item] = read_queue(run_dir).items
    state = replay(read_events(run_dir / "events.jsonl"))
    other = item.model_copy(update={"item_id": f"{ITEM}-r2"})

    def taken(on: Any) -> Any:  # noqa: ANN401
        resolution = QueueResolution(
            item_id=on.item_id,
            ts=item.ts,
            decision="approve",
            resolved_by="yasin",
            verb="approve",
            shown_sha256="a" * 64,
        )
        return outcome_of(
            lambda: decision_effect(
                state, on, resolution, line_sha256="a" * 64, scan_hits=(), held=False
            )
        )

    found = taken(item)
    assert (getattr(found, "effect", None), getattr(found, "acts", None)) == ("release", True)
    assert isinstance(taken(other), QueueItemMismatchError)
    reshaped = item.model_copy(
        update={"consequence": item.consequence.model_copy(update={"on_reject": "record_only"})}  # type: ignore[union-attr]
    )
    assert isinstance(taken(reshaped), QueueItemMismatchError)
