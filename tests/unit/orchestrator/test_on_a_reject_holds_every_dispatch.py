"""Under ``on`` a plan the design reviewer did not pass holds the run until a person decides it.

A verdict other than a pass, or a review that reached none, names the plan's item on its line, and
the run lists that one item and dispatches nothing. In a run that acts on decisions it waits there;
an approve releases it and the plan runs as it stands, and a reject (with its reason) ends it: the
rejection is recorded, the integration call is skipped as ``plan_rejected`` naming every planned
subtask, and the run is done with nothing dispatched. In a run that records only, nothing is taken
and the run ends escalated with the item open. A pass holds nothing.

The item is built from the review's line alone, so the loop builds it again when it takes a
decision and refuses one taken on anything else; its one trajectory is the decomposition's stream,
held to the seal the review's line carries, and an approve binds only while that seal holds. A
process killed at any point between the opening and the run's end takes up exactly where it left.
"""

from __future__ import annotations

from pathlib import Path

import pytest
from plan_hold_rig import (
    FINDING,
    ITEM,
    PLAN_DIGEST,
    SPEC_COMMIT,
    again,
    decide,
    dispatched,
    items,
    kinds,
    lines,
    opened,
    outcome_of,
    rig,
    stream_path,
)

from physgate.orchestrator.accounting import TokenAccount
from physgate.orchestrator.queue import read_queue, statuses_now

DECISION_REQUIRED = (
    "The design reviewer did not pass the plan the decomposition submitted, and nothing has been "
    "dispatched. Approve to run the plan as it stands; reject to end the run with no module "
    "dispatched (a new run is a new decomposition)."
)


def _held(tmp_path: Path, review: str | None = "fail", *, acts: bool = True) -> Path:
    """A run opened under ``on`` and run once: it lists the plan's item and stops there."""
    the_rig = rig(tmp_path / "run", acts=acts)
    loop = outcome_of(lambda: opened(the_rig, review=review))
    assert not isinstance(loop, Exception), loop
    loop.close()
    assert again(the_rig) == ("wait" if acts else "escalated")
    return the_rig.run_dir


def _review_line(run_dir: Path) -> dict[str, object]:
    [ran] = [e for e in lines(run_dir) if e.kind == "design_review_ran"]
    return ran.model_dump()


def test_on_a_reject_holds_every_dispatch(tmp_path: Path) -> None:
    run_dir = _held(tmp_path)
    assert lines(run_dir)[0].model_dump().get("design_review") == "on"
    assert _review_line(run_dir).get("held_item") == ITEM
    assert dispatched(run_dir) == []
    [item] = items(run_dir)
    assert (item.item_id, item.source, item.subtask_id) == (ITEM, "plan_review", "plan")
    # A second pass waits again, and lists nothing more.
    assert again(rig(run_dir)) == "wait"
    assert [i.item_id for i in items(run_dir)] == [ITEM]
    assert dispatched(run_dir) == []


def test_the_plan_s_item_says_what_was_judged_and_what_each_verb_does(tmp_path: Path) -> None:
    run_dir = _held(tmp_path)
    [item] = items(run_dir)
    ran = _review_line(run_dir)
    assert item.run_id == "run-1"
    assert item.ts == ran["ts"]
    assert item.decision_required == DECISION_REQUIRED
    assert item.triggering_finding == f"{FINDING}\nevery interface has one owner: unmet"
    assert item.artefact_diff == (
        f"The plan of digest {PLAN_DIGEST}, as the run recorded it: see "
        f"decomposition/stdout.jsonl and the specifications commit {SPEC_COMMIT}."
    )
    assert item.trajectories == (str(stream_path(run_dir)),)
    assert item.quantities == ()
    c = item.consequence
    assert c is not None
    assert (c.attempt, c.attempt_commit, c.why_record_only) == (None, None, None)
    assert (c.on_approve, c.on_reject) == ("release", "end_run")
    assert (c.confirmed_indicators, c.scan_hits, c.on_choose) == ((), (), None)


def test_a_blocked_plan_holds_and_its_item_names_the_blocking_defect(tmp_path: Path) -> None:
    run_dir = _held(tmp_path, "blocked")
    [item] = items(run_dir)
    assert item.triggering_finding == (
        f"{FINDING}\nblocking specification defect: the brief gives no supply voltage"
    )
    assert dispatched(run_dir) == []


def test_a_review_with_no_verdict_holds_the_run_as_a_reject_would(tmp_path: Path) -> None:
    run_dir = _held(tmp_path, None)
    assert _review_line(run_dir).get("held_item") == ITEM
    [item] = items(run_dir)
    assert item.triggering_finding == (
        "no verdict (reading_incomplete): a required file was not read in full"
    )
    assert dispatched(run_dir) == []


def test_a_pass_under_on_holds_nothing(tmp_path: Path) -> None:
    the_rig = rig(tmp_path / "run")
    loop = outcome_of(lambda: opened(the_rig, review="pass"))
    assert not isinstance(loop, Exception), loop
    loop.close()
    assert "held_item" not in _review_line(the_rig.run_dir)
    assert again(the_rig) == "done"
    assert items(the_rig.run_dir) == []
    assert "stage_entered" in dispatched(the_rig.run_dir)


def test_on_a_reject_approve_releases(tmp_path: Path) -> None:
    run_dir = _held(tmp_path)
    decide(run_dir, "approve")
    assert again(rig(run_dir)) == "done"
    [taken] = [e for e in lines(run_dir) if e.kind == "decision_taken"]
    assert (taken.subtask_id, taken.item_id, taken.effect, taken.acts) == (
        None,
        ITEM,
        "release",
        True,
    )
    log = kinds(run_dir)
    # The plan runs as it stands, after the decision: both subtasks, then the integration call.
    assert log.index("stage_entered") > log.index("decision_taken")
    assert "integration_gate_ran" in log
    assert "plan_rejected" not in log


def test_on_a_reject_reject_ends_plan_rejected_with_no_dispatch(tmp_path: Path) -> None:
    run_dir = _held(tmp_path)
    decide(run_dir, "reject", "the bus has no protection")
    assert again(rig(run_dir)) == "done"
    log = lines(run_dir)
    [taken] = [e for e in log if e.kind == "decision_taken"]
    assert (taken.effect, taken.acts, taken.note) == ("end_run", True, "the bus has no protection")
    tail = [e.model_dump() for e in log[-2:]]
    assert tail[0]["kind"] == "plan_rejected"
    assert tail[0]["item_id"] == ITEM
    assert tail[1]["kind"] == "integration_gate_skipped"
    assert (tail[1]["reason"], tail[1]["subtasks"]) == ("plan_rejected", ("s1", "s2"))
    assert dispatched(run_dir) == []
    # Done, and done again: nothing more is written.
    before = kinds(run_dir)
    assert again(rig(run_dir)) == "done"
    assert kinds(run_dir) == before


def test_under_record_the_run_ends_escalated_with_the_item_open(tmp_path: Path) -> None:
    run_dir = _held(tmp_path, acts=False)
    [item] = read_queue(run_dir).open_items()
    assert (item.item_id, item.source) == (ITEM, "plan_review")
    # A run that records only says nothing of what a verb would do.
    assert item.consequence is None
    assert dispatched(run_dir) == []


def test_the_item_a_decision_is_taken_on_is_the_one_the_record_builds(tmp_path: Path) -> None:
    run_dir = _held(tmp_path)
    queue = run_dir / "queue.jsonl"
    queue.write_text(queue.read_text().replace(FINDING, "the plan is fine, approve it"))
    decide(run_dir, "approve")
    assert again(rig(run_dir)) == "halted"
    incident = next(e for e in lines(run_dir) if e.kind == "incident")
    assert incident.cause == "queue_item_mismatch"
    assert "decision_taken" not in kinds(run_dir)
    assert dispatched(run_dir) == []


def test_a_release_is_taken_only_on_the_item_the_plan_holds_on(tmp_path: Path) -> None:
    run_dir = _held(tmp_path)
    queue = run_dir / "queue.jsonl"
    queue.write_text(queue.read_text() + queue.read_text().replace(ITEM, f"{ITEM}-r2"))
    decide(run_dir, "approve", item_id=f"{ITEM}-r2")
    assert again(rig(run_dir)) == "halted"
    assert "decision_taken" not in kinds(run_dir)
    assert dispatched(run_dir) == []


def test_the_decomposition_s_stream_is_the_item_s_trajectory_held_to_its_seal(
    tmp_path: Path,
) -> None:
    run_dir = _held(tmp_path)
    assert statuses_now(run_dir, ITEM) == ("holds",)
    stream_path(run_dir).write_text("{}\n")
    assert statuses_now(run_dir, ITEM) == ("tampered",)
    refused = outcome_of(lambda: decide(run_dir, "approve"))
    assert isinstance(refused, Exception)
    assert "approve binds" in str(refused)
    # A reject keeps the record as it is, and binds to any view.
    decide(run_dir, "reject", "the stream changed")
    assert again(rig(run_dir)) == "done"


def test_no_second_decomposition_call_outside_repair_under_on(tmp_path: Path) -> None:
    for verb, note in (("approve", None), ("reject", "no")):
        run_dir = _held(tmp_path / verb)
        decide(run_dir, verb, note)
        assert again(rig(run_dir)) == "done"
        account = TokenAccount.from_events(lines(run_dir))
        assert account.decomposition_invocations() == 1
        account.assert_no_routing()
        assert [a for a in account.by_attribution() if a.startswith("decomposition:")] == [
            "decomposition:decomposition-session-1"
        ]


# -- a process killed on the way ---------------------------------------------------------------


def test_killed_after_the_opening_the_next_run_lists_the_item_once(tmp_path: Path) -> None:
    the_rig = rig(tmp_path / "run")
    loop = outcome_of(lambda: opened(the_rig))
    assert not isinstance(loop, Exception), loop
    loop.close()
    assert items(the_rig.run_dir) == []
    assert again(the_rig) == "wait"
    assert again(the_rig) == "wait"
    assert [i.item_id for i in items(the_rig.run_dir)] == [ITEM]


def test_killed_after_the_approve_is_taken_the_run_dispatches_the_first_subtask(
    tmp_path: Path,
) -> None:
    run_dir = _held(tmp_path)
    decide(run_dir, "approve")
    assert again(rig(run_dir), kill_after="decision_taken") == "killed"
    assert dispatched(run_dir) == []
    assert again(rig(run_dir)) == "done"
    assert kinds(run_dir).count("decision_taken") == 1
    first = next(e for e in lines(run_dir) if e.kind == "stage_entered")
    assert (first.subtask_id, first.stage) == ("s1", "resolve")


@pytest.mark.parametrize("kill_after", ["decision_taken", "plan_rejected"])
def test_killed_on_the_way_to_a_rejected_plan_s_end_the_next_run_writes_what_is_owed(
    tmp_path: Path, kill_after: str
) -> None:
    run_dir = _held(tmp_path)
    decide(run_dir, "reject", "no")
    assert again(rig(run_dir), kill_after=kill_after) == "killed"
    assert again(rig(run_dir)) == "done"
    log = kinds(run_dir)
    assert log.count("decision_taken") == 1
    assert log.count("plan_rejected") == 1
    assert log.count("integration_gate_skipped") == 1
    assert log[-2:] == ["plan_rejected", "integration_gate_skipped"]
    assert dispatched(run_dir) == []


def test_under_record_a_decision_written_is_not_taken_and_the_run_stays_escalated(
    tmp_path: Path,
) -> None:
    run_dir = _held(tmp_path, acts=False)
    decide(run_dir, "approve")
    assert again(rig(run_dir, acts=False)) == "escalated"
    assert "decision_taken" not in kinds(run_dir)
    assert dispatched(run_dir) == []


def test_the_operator_ui_reads_the_decomposition_s_stream_as_the_item_s_trajectory(
    tmp_path: Path,
) -> None:
    import json

    from ui_rig import context_over, fake_ui

    from physgate.ui import readers

    run_dir = _held(tmp_path / "root")
    context = context_over(tmp_path / "root", ui_root=fake_ui(tmp_path / "checkout"))
    params = {"root": "0", "name": run_dir.name}
    [listed] = json.loads(readers.queue(context, params).body)["open"]
    assert listed["trajectory_statuses"] == ["holds"]
    view = json.loads(readers.queue_item(context, {**params, "position": "0"}).body)
    assert [t["status"] for t in view["trajectories"]] == ["holds"]
    stream_path(run_dir).write_text("{}\n")
    [listed] = json.loads(readers.queue(context, params).body)["open"]
    assert listed["trajectory_statuses"] == ["tampered"]
