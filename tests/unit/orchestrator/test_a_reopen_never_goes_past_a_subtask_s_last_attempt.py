"""No reopen, fix or follow-up takes a subtask past the highest attempt number it can reach.

A module that merged on attempt 3 and was followed up after sizing's closing pass merged on attempt
4: the subtask's last number, though no fix a person ordered. When the follow-up's retest fails
and a person keeps the other module's work, the choice records only, as one on a module that
merged on its fix does: the item says the module has no attempt left, the run goes on to its end,
and replay accepts the line and refuses a reopen forged past the cap. Each other way to a next
attempt stops at the cap too: the fix a person orders after a review that blocked on attempt 3 is
attempt 4 and the subtask's last, and a follow-up at attempt 4 that does not merge ends.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest
from accounted import forged_account_before_each_open  # noqa: F401 - the rig's forger
from arbitration_runs import CLOSING as SLICE
from arbitration_runs import PerAttempt, events_of
from loop_fakes import FakeDispatcher, FakeReviewer, Rig, sha
from test_a_blocked_review_is_a_review_that_goes_to_a_person import blocked_review
from test_a_choice_on_a_failed_contract_reopens_the_other_module import (
    ACTS,
    again,
    choose,
    of,
    requests_of,
)
from test_a_failed_contract_is_ruled_by_clause_and_goes_to_a_person_as_one_item import (
    kinds,
    lines,
    refusal,
)
from test_a_follow_up_after_the_closing_pass_is_recorded_and_replayed_as_the_record_owes import (
    ended,
    follow_ups,
    slice_rig,
)
from test_a_pairs_contract_is_tested_once_both_its_modules_merged_and_blocks_nothing import (
    BUDGET,
    CLOSING,
    DRIVE,
    FW,
    hooked,
    node,
    rig_for,
    start,
)
from test_a_queue_decision_acts_at_a_boundary import _layer, _of, _resume
from test_a_reject_on_a_blocked_review_gets_one_fix import _blocked_then

from physgate.orchestrator import decisions as deciding
from physgate.orchestrator.budget import ATTEMPT_LIMIT
from physgate.orchestrator.events import EscalationDecided, SubtaskRejected, read_events
from physgate.orchestrator.queue import read_queue
from physgate.orchestrator.replay import replay

BOTH = ("iface.drive", "iface.tilt")
DECLARED = (BUDGET, DRIVE, FW)
#: The item of fw's pair with drive, the plan's second pair, once the follow-up's retest failed.
ITEM = "run-1-contract-2"


def _per_attempt(rig: Rig, target: str, by_attempt: dict[int, dict[str, Any]]) -> None:
    """``target`` writes ``by_attempt[n]`` from its attempt ``n``'s commit, else its own."""
    graph = rig.diff
    original = graph.proposals
    # The fake dispatcher names each session's commit by its subtask, attempt and call.
    commits = {sha(f"{target}-{n}-{call}"): n for n in by_attempt for call in range(1, 40)}

    def proposals(subtask_id: str, attempt_commit: str, role: str) -> list[dict[str, Any]]:
        n = commits.get(attempt_commit) if subtask_id == target else None
        if n is not None:
            return [by_attempt[n]]
        return list(original(subtask_id, attempt_commit, role))

    graph.proposals = proposals  # type: ignore[method-assign]


def followed_up_at_the_cap(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Rig:
    """The run until it waits: fw merged on attempt 3, and its follow-up merged deviating."""
    rig = rig_for(tmp_path, dispatcher=FakeDispatcher(trajectories=tmp_path / "run" / "sessions"))
    rig.config_overrides.update(ACTS)
    # The closing pass changes the supply's period and constrains fw's node: a follow-up is owed.
    closing = node("budget.supply", "sizing", "iface.drive", "fw.main", v=12, period=20)
    rig.diff.writes[CLOSING] = [closing]  # type: ignore[attr-defined]
    # Reviews: budget, drive, then fw's first two rejected; every later one passes.
    rig.reviewer.verdicts[:] = ["pass", "pass", "fail", "fail"]
    _per_attempt(rig, FW, {ATTEMPT_LIMIT: node("fw.main", "firmware", *BOTH, v=11, period=10)})
    loop = rig.open()
    hooked(monkeypatch, loop, declared=DECLARED)
    start(loop, sizing=True)
    _layer(loop)
    assert loop.run().kind == "wait"  # the integration call waits for the contract's item
    loop.close()
    return rig


def test_a_choice_that_would_reopen_a_module_at_the_cap_records_only(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    rig = followed_up_at_the_cap(tmp_path, monkeypatch)
    rows = lines(rig)
    (followed,) = of(rows, "subtask_reopened", cause="follow_up")
    assert (followed["subtask_id"], followed["attempt"]) == (FW, ATTEMPT_LIMIT)
    state = replay(read_events(rig.run_dir / "events.jsonl"))
    choices = deciding.contract_choices(state, state.contract_items[ITEM])
    assert (choices["producer"].why, choices["producer"].subtask) == ("spent", FW)
    (item,) = (i for i in read_queue(rig.run_dir).items if i.item_id == ITEM)
    assert item.consequence is not None
    assert item.consequence.on_choose == {"producer": "record_only", "consumer": "record_only"}
    assert 'Choosing the producer records only: module "fw" has no attempt left.' in (
        item.decision_required
    )
    choose(rig.run_dir, "producer", item_id=ITEM)
    assert again(rig, monkeypatch, declared=DECLARED) == "done"
    rows = lines(rig)
    (taken,) = of(rows, "decision_taken", item_id=ITEM)
    assert (taken["effect"], taken["acts"], taken.get("reopens")) == ("none", False, None)
    assert taken["why_not"] == "record_only_source"
    assert [r["attempt"] for r in of(rows, "subtask_reopened", subtask_id=FW)] == [ATTEMPT_LIMIT]
    assert [r.attempt for r in requests_of(rig, FW)] == [1, 2, 3, ATTEMPT_LIMIT]
    # The run goes on to its end: integration runs, and the pair that failed completes neither.
    assert "integration_gate_ran" in kinds(rows)
    assert [r["subtask_id"] for r in of(rows, "module_completed")] == [BUDGET]
    assert refusal(rows) is None


def test_replay_refuses_a_choice_that_reopens_a_module_at_the_cap(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    rig = followed_up_at_the_cap(tmp_path, monkeypatch)
    choose(rig.run_dir, "producer", item_id=ITEM)
    again(rig, monkeypatch, declared=DECLARED)
    rows = lines(rig)
    at = next(i for i, r in enumerate(rows) if r["kind"] == "decision_taken")
    forged = {**rows[at], "effect": "reopen", "acts": True, "why_not": None, "reopens": FW}
    said = refusal([*rows[:at], forged])
    assert said is not None and "does other than the record allows" in said, said
    # Nor does a reopen past the cap replay after it: its attempt is outside the schema.
    reopen = {
        **{k: rows[at][k] for k in ("ts", "run_id", "gate_mode", "shown_sha256")},
        "kind": "subtask_reopened",
        "subtask_id": FW,
        "item_id": ITEM,
        "merge_commit": of(rows, "merged", subtask_id=FW)[-1]["merge_commit"],
        "attempt": ATTEMPT_LIMIT + 1,
    }
    said = refusal([*rows[: at + 1], reopen])
    assert said is not None and "attempt" in said, said


# --- each other way to a next attempt stops at the cap ------------------------------------------


@pytest.mark.parametrize("how", ["review blocked", "review fail"])
def test_the_fix_after_a_block_on_attempt_three_is_the_last_attempt(
    tmp_path: Path, how: str
) -> None:
    run_dir = tmp_path / "run"
    # Reviews 1 and 2 reject, 3 blocks, and the fix's own review (4) is not accepted.
    verdicts = ["fail", "fail", "pass", "pass" if how == "review blocked" else "fail"]
    results = {3: blocked_review()} | ({4: blocked_review()} if how == "review blocked" else {})
    rig = _blocked_then(run_dir, on=3, reviewer=FakeReviewer(verdicts=verdicts, results=results))
    after, kind = _resume(rig)
    assert kind == "done"
    assert [(r.attempt, r.kind) for r in rig.dispatcher.requests] == [
        (1, "attempt"),
        (2, "attempt"),
        (3, "attempt"),
        (ATTEMPT_LIMIT, "fix"),
    ]
    ended_by = _of(run_dir, SubtaskRejected)
    assert [(e.by, e.attempt) for e in ended_by] == [("fix_not_accepted", ATTEMPT_LIMIT)]
    assert ATTEMPT_LIMIT not in [e.attempt for e in _of(run_dir, EscalationDecided)]
    assert len(read_queue(run_dir).items) == 1
    assert after.state.subtasks["s1"].status == "rejected"


@pytest.mark.parametrize("how", ["review fail", "review blocked"])
def test_a_follow_up_at_the_cap_that_does_not_merge_ends(tmp_path: Path, how: str) -> None:
    # s1 merges on attempt 3 (the gate failed 1 and 2); its follow-up, attempt 4, is not accepted.
    # The reviews are z0's, s1's third attempt's, the closing pass's, then the follow-up's.
    rig = slice_rig(tmp_path)
    rig.gate = PerAttempt(verdicts=["fail", "fail"])
    rig.reviewer = FakeReviewer(
        verdicts=["pass", "pass", "pass", "fail"],
        results={4: blocked_review()} if how == "review blocked" else {},
    )
    assert ended(rig, plan=SLICE) == "done"
    events = events_of(rig)
    assert [f["attempt"] for f in follow_ups(events)] == [ATTEMPT_LIMIT]
    rows = [e.model_dump(mode="json") for e in events]
    (end,) = of(rows, "follow_up_ended", subtask_id="s1")
    assert (end["attempt"], end["why"]) == (
        ATTEMPT_LIMIT,
        "blocked" if how == "review blocked" else "rejected",
    )
    assert max(r.attempt for r in rig.dispatcher.requests if r.subtask_id == "s1") == ATTEMPT_LIMIT
    assert of(rows, "escalation_decided", subtask_id="s1", attempt=ATTEMPT_LIMIT) == []
    assert replay(events).subtasks["s1"].status == "done"
    assert refusal(rows) is None
