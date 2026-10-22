"""A queue item says, before anyone decides it, what approve and reject will do to it, and why.

ARCH-133: the item names the attempt and the commit it concerns, what each verb will do, and
why approve only records when it does. All of that is in the item's line, so it is in the
digest a decision binds to: a person decides on the consequence as well as the work. An item
written before the consequence existed carries none of it, reads and writes exactly as it did,
and is taken as recording only.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from orch_helpers import ticking_clock
from pydantic import ValidationError

from physgate.orchestrator.exceptions import QueueError
from physgate.orchestrator.queue import (
    ApprovalQueue,
    ConfirmedIndicator,
    ItemConsequence,
    QueueItem,
    escalation_item,
    item_id_for,
    item_sha256,
    queue_listing,
    read_queue,
    unavailable_item,
)
from physgate.orchestrator.repair import Finding
from physgate.reviewers.scan import ScanHit

TS = "2026-10-21T12:00:00.000000Z"
COMMIT = "c" * 40
LEGACY = (
    b'{"item_id":"run-1-s1","ts":"2026-10-21T12:00:00.000000Z","kind":"item","run_id":"run-1",'
    b'"subtask_id":"s1","source":"review_unavailable","decision_required":"decide",'
    b'"artefact_diff":"diff","triggering_finding":"no verdict","quantities":[],'
    b'"trajectories":["sessions/a/stdout.jsonl"]}'
)


def _unavailable(consequence: ItemConsequence | None = None) -> QueueItem:
    return unavailable_item(
        item_id="run-1-s1",
        run_id="run-1",
        subtask_id="s1",
        attempt=2,
        source="review_unavailable",
        cause="invalid_verdict",
        detail="the verdict did not validate",
        spec_defects=(),
        artefact_diff="diff --git a/m/x b/m/x\n",
        trajectory="sessions/a/stdout.jsonl",
        ts=TS,
        consequence=consequence,
    )


MERGES = ItemConsequence(
    attempt=2,
    attempt_commit=COMMIT,
    on_approve="merge_attempt",
    on_reject="retry",
    why_record_only=None,
    confirmed_indicators=(),
    scan_hits=(),
)
INDICATED = ItemConsequence(
    attempt=2,
    attempt_commit=COMMIT,
    on_approve="record_only",
    on_reject="retry",
    why_record_only="indicator_in_history",
    confirmed_indicators=(ConfirmedIndicator(attempt=1, kind="disabled_checks"),),
    scan_hits=(),
)


# -- the legacy line ----------------------------------------------------------------------


def test_an_item_written_before_the_consequence_existed_reads_and_writes_as_before() -> None:
    item = QueueItem.model_validate_json(LEGACY)
    assert item.consequence is None
    assert item.model_dump_json().encode() == LEGACY


def test_an_item_built_without_a_consequence_is_byte_identical_to_today_s() -> None:
    line = _unavailable().model_dump_json()
    assert "consequence" not in line
    assert "on_approve" not in line


# -- what the consequence carries -------------------------------------------------------


def test_the_item_names_its_confirmed_indicators_before_the_decision(tmp_path: Path) -> None:
    queue = ApprovalQueue(tmp_path / "queue.jsonl", clock=ticking_clock())
    queue.add(_unavailable(INDICATED))
    line = (tmp_path / "queue.jsonl").read_bytes().removesuffix(b"\n")
    record = json.loads(line)["consequence"]
    assert record["on_approve"] == "record_only"
    assert record["why_record_only"] == "indicator_in_history"
    assert record["confirmed_indicators"] == [{"attempt": 1, "kind": "disabled_checks"}]
    # In the digest: the same item stating another consequence is another item.
    other = _unavailable(MERGES).model_dump_json().encode()
    assert item_sha256(line) != item_sha256(other)
    listed = queue_listing(tmp_path)["open"]
    assert isinstance(listed, list) and len(listed) == 1
    assert listed[0]["consequence"]["why_record_only"] == "indicator_in_history"
    assert listed[0]["item_sha256"] == item_sha256(line)


def test_the_listing_shows_each_open_item_s_trajectory_statuses(tmp_path: Path) -> None:
    queue = ApprovalQueue(tmp_path / "queue.jsonl", clock=ticking_clock())
    queue.add(_unavailable(MERGES))
    listed = queue_listing(tmp_path)["open"]
    assert isinstance(listed, list)
    # No event log, so the session the link names has no seal on record.
    assert listed[0]["trajectory_statuses"] == ["no_seal"]


@pytest.mark.parametrize(
    "fields",
    [
        # Approve records only, and says nothing of why.
        {"on_approve": "record_only", "on_reject": "retry"},
        # Approve merges, and gives a reason it would not.
        {"on_approve": "merge_attempt", "on_reject": "retry", "why_record_only": "gate"},
        # Approve merges, with no attempt or commit named.
        {"on_approve": "merge_attempt", "on_reject": "retry", "attempt_commit": None},
        {"on_approve": "merge_attempt", "on_reject": "retry", "attempt": None},
    ],
    ids=["no reason", "a reason it merges anyway", "no commit", "no attempt"],
)
def test_a_consequence_that_does_not_hold_together_is_refused(fields: dict[str, object]) -> None:
    base: dict[str, object] = {
        "attempt": 2,
        "attempt_commit": COMMIT,
        "why_record_only": None,
        "confirmed_indicators": (),
        "scan_hits": (),
    }
    with pytest.raises(ValidationError) as refused:
        ItemConsequence.model_validate({**base, **fields})
    # Refused by the rule, not for a missing field: the case reaches the validator.
    assert all(e["type"] != "missing" for e in refused.value.errors())


@pytest.mark.parametrize("left_out", ["why_record_only", "confirmed_indicators", "scan_hits"])
def test_a_consequence_that_leaves_a_field_out_is_refused_not_read_as_none(left_out: str) -> None:
    line = json.loads(INDICATED.model_dump_json())
    del line[left_out]
    with pytest.raises(ValidationError) as refused:
        ItemConsequence.model_validate_json(json.dumps(line))
    assert [e["type"] for e in refused.value.errors()] == ["missing"]


def test_scan_hits_are_carried_as_the_scan_reported_them() -> None:
    hit = ScanHit(kind="disabled_checks", evidence="toolu_1", what="a test skipped")
    consequence = INDICATED.model_copy(
        update={"why_record_only": "scan_hit", "confirmed_indicators": (), "scan_hits": (hit,)}
    )
    item = _unavailable(consequence)
    assert QueueItem.model_validate_json(item.model_dump_json()).consequence == consequence


# -- item ids carry a round -------------------------------------------------------------


def test_the_first_item_of_a_subtask_keeps_today_s_id_and_later_ones_carry_their_round() -> None:
    assert item_id_for("run-1", "s1", 1) == "run-1-s1"
    assert item_id_for("run-1", "s1", 2) == "run-1-s1-r2"
    assert item_id_for("run-1", "integration", 3) == "run-1-integration-r3"
    with pytest.raises(QueueError):
        item_id_for("run-1", "s1", 0)


# -- an exhausted budget whose attempts include one a person spent --------------------------

TRAJECTORIES = ("sessions/a/stdout.jsonl", "sessions/b/stdout.jsonl", "sessions/c/stdout.jsonl")


def test_an_exhausted_budget_counts_an_attempt_a_person_spent() -> None:
    findings = (Finding(source="review", text="first"), Finding(source="gate", text="third"))
    item = escalation_item(
        item_id="q1",
        run_id="run-1",
        subtask_id="s1",
        findings=findings,
        artefact_diff="diff",
        trajectories=TRAJECTORIES,
        ts=TS,
        spent_by_person=1,
    )
    assert item.triggering_finding == "third"
    assert "rejected on all 3 attempts" not in item.decision_required
    assert "a person rejected 1" in item.decision_required
    with pytest.raises(QueueError):
        escalation_item(
            item_id="q1",
            run_id="run-1",
            subtask_id="s1",
            findings=findings,
            artefact_diff="diff",
            trajectories=TRAJECTORIES,
            ts=TS,
        )


def test_an_item_read_back_keeps_its_consequence(tmp_path: Path) -> None:
    ApprovalQueue(tmp_path / "queue.jsonl", clock=ticking_clock()).add(_unavailable(INDICATED))
    assert read_queue(tmp_path).items[0].consequence == INDICATED
