"""The approval queue: five fields per item, append-only, decisions as their own lines."""

from __future__ import annotations

import os
from pathlib import Path

import pytest
from orch_helpers import ticking_clock

from physgate.orchestrator import queue as queue_module
from physgate.orchestrator.exceptions import QueueError
from physgate.orchestrator.protocols import NumericOutput, QuantityRef
from physgate.orchestrator.queue import ApprovalQueue, escalation_item
from physgate.orchestrator.repair import Finding

Q = QuantityRef(node_id="motor.left", name="stall_current", value=3.1, unit="A")
FINDINGS = (
    Finding(source="gate", text="first", failing_check="bounds", quantities=(Q,)),
    Finding(source="review", text="second"),
    Finding(
        source="gate",
        text="third",
        failing_check="bounds",
        numeric_output=NumericOutput(value=3.4, unit="A"),
        quantities=(Q, Q),
    ),
)
TRAJECTORIES = ("sessions/a/stdout.jsonl", "sessions/b/stdout.jsonl", "sessions/c/stdout.jsonl")
TS = "2026-09-26T12:00:00.000000Z"


def item(item_id: str = "q1", findings: tuple[Finding, ...] = FINDINGS) -> queue_module.QueueItem:
    return escalation_item(
        item_id=item_id,
        run_id="run-1",
        subtask_id="s1",
        findings=findings,
        artefact_diff="diff --git a/modules/power/x.py b/modules/power/x.py\n",
        trajectories=TRAJECTORIES,
        ts=TS,
    )


def test_an_exhausted_budget_is_escalated_with_all_five_things() -> None:
    got = item()
    assert got.source == "repair_budget_exhausted"
    assert "rejected on all 3 attempts" in got.decision_required
    assert got.artefact_diff.startswith("diff --git")
    assert got.triggering_finding == "third"
    assert got.quantities == (Q, Q)
    assert got.trajectories == TRAJECTORIES


def test_the_quantities_come_from_the_latest_finding_that_has_any() -> None:
    findings = (FINDINGS[2], FINDINGS[0], FINDINGS[1])
    assert item(findings=findings).quantities == (Q,)


def test_an_escalation_without_every_attempt_is_refused() -> None:
    with pytest.raises(QueueError):
        item(findings=FINDINGS[:2])


def test_items_and_decisions_are_appended_and_read_back_by_a_fresh_handle(tmp_path: Path) -> None:
    path = tmp_path / "queue.jsonl"
    queue = ApprovalQueue(path, clock=ticking_clock())
    queue.add(item("q1"))
    queue.add(item("q2"))
    queue.resolve("q1", decision="split the subtask", resolved_by="yasin")
    fresh = ApprovalQueue(path)
    assert [i.item_id for i in fresh.items()] == ["q1", "q2"]
    assert [i.item_id for i in fresh.open_items()] == ["q2"]
    # Items in one file, a person's decisions in another.
    assert path.read_bytes().count(b"\n") == 2
    assert fresh.decisions_path.read_bytes().count(b"\n") == 1


def test_every_queue_write_is_synced(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    synced: list[int] = []
    real = os.fsync

    def counting(fd: int) -> None:
        synced.append(fd)
        real(fd)

    monkeypatch.setattr(os, "fsync", counting)
    queue = ApprovalQueue(tmp_path / "queue.jsonl", clock=ticking_clock())
    queue.add(item())
    queue.resolve("q1", decision="accept", resolved_by="yasin")
    assert len(synced) == 2


def test_what_the_record_forbids_is_refused_and_writes_nothing(tmp_path: Path) -> None:
    path = tmp_path / "queue.jsonl"
    queue = ApprovalQueue(path, clock=ticking_clock())
    queue.add(item("q1"))
    before = path.read_bytes()
    with pytest.raises(QueueError, match="listed twice"):
        queue.add(item("q1"))
    with pytest.raises(QueueError, match="not an open item"):
        queue.resolve("q9", decision="accept", resolved_by="yasin")
    queue.resolve("q1", decision="accept", resolved_by="yasin")
    with pytest.raises(QueueError, match="not an open item"):
        queue.resolve("q1", decision="accept again", resolved_by="yasin")
    assert path.read_bytes() == before
    assert queue.decisions_path.read_bytes().count(b"\n") == 1


@pytest.mark.parametrize(
    "tail",
    [
        b"\xff\xfe\n",
        b"{not json}\n",
        b'{"kind": "resolution", "item_id": "q9", "ts": "' + TS.encode() + b'",'
        b' "decision": "x", "resolved_by": "y"}\n',
        b'{"kind": "item", "item_id": "q2"}\n',
    ],
    ids=["not utf-8", "not json", "a decision on no item", "an item missing its fields"],
)
def test_a_line_this_package_could_not_have_written_refuses_the_queue(
    tmp_path: Path, tail: bytes
) -> None:
    path = tmp_path / "queue.jsonl"
    ApprovalQueue(path, clock=ticking_clock()).add(item("q1"))
    path.write_bytes(path.read_bytes() + tail)
    with pytest.raises(QueueError):
        ApprovalQueue(path)


def test_an_unterminated_final_line_is_dropped(tmp_path: Path) -> None:
    path = tmp_path / "queue.jsonl"
    ApprovalQueue(path, clock=ticking_clock()).add(item("q1"))
    whole = path.read_bytes()
    path.write_bytes(whole + b'{"kind": "item", "item_')
    assert [i.item_id for i in ApprovalQueue(path).items()] == ["q1"]
    assert path.read_bytes() == whole


DECISION = (
    b'{"kind": "resolution", "item_id": "q1", "ts": "' + TS.encode() + b'",'
    b' "decision": "x", "resolved_by": "y"}\n'
)


def test_a_decision_in_the_items_file_is_refused(tmp_path: Path) -> None:
    path = tmp_path / "queue.jsonl"
    ApprovalQueue(path, clock=ticking_clock()).add(item("q1"))
    path.write_bytes(path.read_bytes() + DECISION)
    with pytest.raises(QueueError):
        ApprovalQueue(path)


def test_an_item_in_the_decisions_file_is_refused(tmp_path: Path) -> None:
    path = tmp_path / "queue.jsonl"
    queue = ApprovalQueue(path, clock=ticking_clock())
    queue.add(item("q2"))
    queue.decisions_path.write_bytes(path.read_bytes())
    with pytest.raises(QueueError):
        ApprovalQueue(path)


def test_a_decision_must_name_an_item_that_is_open(tmp_path: Path) -> None:
    path = tmp_path / "queue.jsonl"
    queue = ApprovalQueue(path, clock=ticking_clock())
    queue.add(item("q1"))
    for decisions in (DECISION.replace(b'"q1"', b'"q9"'), DECISION + DECISION):
        queue.decisions_path.write_bytes(decisions)
        with pytest.raises(QueueError) as caught:
            ApprovalQueue(path)
        assert "not an open item" in caught.value.context["reason"]


def test_a_decision_written_by_another_process_is_seen_on_refresh(tmp_path: Path) -> None:
    path = tmp_path / "queue.jsonl"
    queue = ApprovalQueue(path, clock=ticking_clock())
    queue.add(item("q1"))
    ApprovalQueue(path, clock=ticking_clock()).resolve("q1", decision="x", resolved_by="y")
    assert [i.item_id for i in queue.open_items()] == ["q1"]
    queue.refresh()
    assert queue.open_items() == []
