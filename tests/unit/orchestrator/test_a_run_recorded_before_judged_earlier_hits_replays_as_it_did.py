"""A run recorded before reviews judged earlier attempts' hits replays, and is decided, as it was.

A review line that names no earlier attempt judged its own attempt's streams and nothing else, as
every review line written before did; an item whose hits name no attempt reads, writes back and
is taken byte for byte as it was listed. The new fields are left out of a line when empty, so no
line written before changes. A review line that names an earlier attempt is held to the log: an
attempt before its own, never one a review had already judged.

A run recorded before and resumed after: what its log records stays as it was, and the rule
applies to each review that runs after the resume. Its earlier attempts that no review line
judged are given to that review; an item already listed is decided as it was listed.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest
from accounted import forged_account_before_each_open  # noqa: F401 - the rig's forger
from loop_fakes import FakeReviewer
from test_an_unreviewed_attempt_s_scan_hits_go_to_the_next_review import (
    _dismissed_then_blocked,
    _of,
    _resume,
    _rig,
    _run,
    decide,
    hit,
    judged,
    result,
)

from physgate.orchestrator.events import DecisionTaken, Incident, ReviewRan, read_events
from physgate.orchestrator.exceptions import CorruptEventLogError
from physgate.orchestrator.queue import QUEUE_NAME, QueueItem
from physgate.orchestrator.replay import replay

EVENTS = "events.jsonl"

#: A review line, byte for byte as the writer before this change wrote it.
OLD_REVIEW = (
    '{"seq":40,"ts":"2026-11-12T10:00:00.000000Z","run_id":"run-1","gate_mode":"on",'
    '"kind":"review_ran","subtask_id":"s1","attempt":2,"result":{"verdict":"fail",'
    '"finding":"the gain changed silently","reviewer_model":"claude-opus-5-5",'
    '"session_id":"rev-1","usage":[],"failing_item":null,"subject":null,"numeric_output":null,'
    '"items":[],"criteria":[],"indicators":[],"spec_defects":[],"rubric_sha256":null,'
    '"rubric_kind":null,"packet_sha256":null,"reading_verified":null,'
    '"peak_context_tokens":null,"schema_refusals":null,"max_output_tokens":null,'
    '"context_window":null,"repair_resumes":null}}'
)

#: An item line with a scan hit, byte for byte as the writer before this change wrote it.
OLD_ITEM = (
    '{"item_id":"run-1-s1","ts":"2026-11-12T10:00:00.000000Z","kind":"item","run_id":"run-1",'
    '"subtask_id":"s1","source":"review_unavailable","decision_required":"The review of '
    'subtask s1, attempt 2, reached no verdict. Decide.","artefact_diff":"--- a/x\\n+++ b/x\\n",'
    '"triggering_finding":"no verdict","quantities":[],'
    '"trajectories":["/r/sessions/sess-2/stdout.jsonl"],"consequence":{"attempt":2,'
    '"attempt_commit":"cccccccccccccccccccccccccccccccccccccccc","on_approve":"record_only",'
    '"on_reject":"retry","why_record_only":"scan_hit","confirmed_indicators":[],'
    '"scan_hits":[{"kind":"disabled_checks","evidence":"toolu_1",'
    '"what":"a lint rule suppressed"}]}}'
)


def test_a_review_line_written_before_reads_and_writes_back_byte_for_byte() -> None:
    event = ReviewRan.model_validate_json(OLD_REVIEW)
    assert event.model_dump_json() == OLD_REVIEW
    assert tuple(event.model_dump().get("judged_earlier", ())) == ()


def test_an_item_line_written_before_reads_and_writes_back_byte_for_byte() -> None:
    item = QueueItem.model_validate_json(OLD_ITEM)
    assert item.model_dump_json() == OLD_ITEM
    assert item.consequence is not None
    assert [h.model_dump().get("attempt") for h in item.consequence.scan_hits] == [None]
    assert item.consequence.model_dump().get("judged_earlier", ()) in ((), [])


def test_a_review_line_that_names_no_earlier_attempt_judged_its_own_alone(tmp_path: Path) -> None:
    # Attempt 2's review answered attempt 1's hit, but a line written before says nothing of
    # attempt 1: it is read as judging attempt 2 alone, so the item listed from the log as it
    # now stands is no longer the one the person approved, and the run halts on it.
    run_dir = tmp_path / "run"
    rig = _dismissed_then_blocked(run_dir)
    _run(rig, "s1")
    decide(run_dir, "approve")
    path = run_dir / EVENTS
    lines = []
    for raw in path.read_bytes().splitlines():
        data = json.loads(raw)
        if data.get("kind") == "review_ran":
            # As the writer before wrote it: no earlier attempt named, shown or answered by one.
            data.pop("judged_earlier", None)
            data.pop("earlier_hits", None)
            for answered in data["result"]["indicators"]:
                answered.pop("attempt", None)
            raw = ReviewRan.model_validate_json(json.dumps(data)).model_dump_json().encode()
        lines.append(raw)
    path.write_bytes(b"\n".join(lines) + b"\n")
    assert _resume(rig) == "halted"
    assert [i.cause for i in _of(run_dir, Incident)] == ["queue_item_mismatch"]
    assert _of(run_dir, DecisionTaken) == [] and rig.merger.merges == []


def _named(run_dir: Path, judged_earlier: list[int], attempt: int | None = None) -> list[Any]:
    """The run's events, with its last review line naming ``judged_earlier``."""
    assert "judged_earlier" in ReviewRan.model_fields, "a review line names no earlier attempt"
    events = list(read_events(run_dir / EVENTS))
    last = max(n for n, e in enumerate(events) if isinstance(e, ReviewRan))
    data = json.loads(events[last].model_dump_json())
    data["judged_earlier"] = judged_earlier
    if attempt is not None:
        data["attempt"] = attempt
    events[last] = ReviewRan.model_validate_json(json.dumps(data))
    return events


def test_replay_reads_a_review_line_that_names_an_earlier_unjudged_attempt(tmp_path: Path) -> None:
    run_dir = tmp_path / "run"
    _run(_dismissed_then_blocked(run_dir), "s1")
    state = replay(_named(run_dir, [1]))
    assert [
        tuple(r.model_dump().get("judged_earlier", ())) for r in state.subtasks["s1"].reviews
    ] == [(1,)]


@pytest.mark.parametrize(
    "named",
    [[2], [3], [1, 1], [0]],
    ids=["its own attempt", "a later attempt", "one attempt twice", "no attempt"],
)
def test_replay_refuses_a_review_line_that_names_no_earlier_unjudged_attempt(
    tmp_path: Path, named: list[int]
) -> None:
    run_dir = tmp_path / "run"
    _run(_dismissed_then_blocked(run_dir), "s1")
    with pytest.raises((ValueError, CorruptEventLogError)):
        replay(_named(run_dir, named))


def test_replay_refuses_naming_an_attempt_a_review_already_judged(tmp_path: Path) -> None:
    # Attempt 2's review judged attempt 1; attempt 3's review line may not name it again, nor
    # attempt 2, which has a review line of its own.
    run_dir = tmp_path / "run"
    both = (judged(hit("sess-1"), attempt=1), judged(hit("sess-2")))
    reviewer = FakeReviewer(
        results={1: result("fail", 1, *both), 2: result("blocked", 2, judged(hit("sess-3")))}
    )
    _run(_rig(run_dir, reviewer=reviewer), "s1")
    for named in ([1], [2]):
        with pytest.raises((ValueError, CorruptEventLogError)):
            replay(_named(run_dir, named))


def test_a_run_recorded_before_and_resumed_after_gives_its_next_review_the_earlier_hits(
    tmp_path: Path,
) -> None:
    # Recorded before: attempt 1 refused before review; attempt 2's review, never given attempt 1,
    # answered its own hit alone and blocked; the item listed attempt 1's hit with no attempt.
    run_dir = tmp_path / "run"
    reviewer = FakeReviewer(
        results={
            1: result("blocked", 1, judged(hit("sess-2"))),
            2: result("blocked", 2, judged(hit("sess-1"), attempt=1), judged(hit("sess-3"))),
        }
    )
    rig = _rig(run_dir, reviewer=reviewer)
    _run(rig, "s1")
    items = run_dir / QUEUE_NAME
    data = json.loads(items.read_bytes())
    assert [h["evidence"] for h in data["consequence"]["scan_hits"]] == [hit("sess-1")]
    for listed in data["consequence"]["scan_hits"]:
        listed.pop("attempt", None)
    old = QueueItem.model_validate_json(json.dumps(data)).model_dump_json().encode() + b"\n"
    items.write_bytes(old)
    assert "judged_earlier" not in (run_dir / EVENTS).read_text()
    # Resumed after: the person orders another attempt; its review is the first under the rule.
    decide(run_dir, "reject")
    _resume(rig)
    given = rig.reviewer.seen[1].model_dump().get("unjudged")
    assert given is not None, "the review after the resume was given no earlier attempt"
    assert [u["attempt"] for u in given] == [1]
    assert [
        (r.attempt, tuple(r.model_dump().get("judged_earlier", ())))
        for r in _of(run_dir, ReviewRan)
    ] == [(2, ()), (3, (1,))]
    assert items.read_bytes().startswith(old), "the item listed before changed"
