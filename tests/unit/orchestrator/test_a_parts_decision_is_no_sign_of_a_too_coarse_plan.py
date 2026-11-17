"""A part's choice that takes over a minute is not logged as a too-coarse decomposition.

ARCH-130 logs a decision written over one minute after its view was shown as a sign that the
decomposition is too coarse, and counts it in the review-time median. A parts decision (have,
make, find; ARCH-122) is exempt: typing a part's values is data entry, not a judgement of the
plan. The writer never marks one, the record's validator admits one unmarked over a minute, and
every other decision is marked as before. A parts line written before the exemption, marked,
still reads back, is taken by the run and follows in the replay.
"""

from __future__ import annotations

import json
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

import pytest
from design_review_rig import refusal
from parts_rig import (
    body,
    item_id,
    listed,
    log_of,
    person,
    rig,
    shown,
    started,
)
from plan_hold_rig import again, dispatched, kinds

from physgate.orchestrator.queue import (
    DECISIONS_NAME,
    QUEUE_NAME,
    PersonDecision,
    QueueItem,
    QueueResolution,
    ShownItem,
    read_queue,
    record_decision,
    statuses_now,
)

NOW = datetime(2026, 11, 17, 9, 10, 0, 250_000, tzinfo=UTC)
LATE = timedelta(minutes=5)
ITEM_IDS = tuple(item_id(n) for n in (1, 2, 3))
STATED = {
    "have": body({"mass": (0.4, "kg")}),
    "make": body(texts=("printed in PETG",)),
    "find": None,
}


def _late(run_dir: Path, decided: str, the_person: Any, by: str = "operator") -> Any:  # noqa: ANN401
    """Decide ``decided`` five minutes after its view was shown: the line, or the refusal."""
    view = read_queue(run_dir)
    try:
        return record_decision(
            run_dir,
            decided,
            person=the_person,
            resolved_by=by,
            clock=lambda: NOW,
            shown=ShownItem(
                item_sha256=view.digests[decided], trajectories=statuses_now(run_dir, decided)
            ),
            shown_at=NOW - LATE,
        )
    except Exception as exc:  # noqa: BLE001 - a refusal is what a row asserts against
        return exc


@pytest.mark.parametrize("position", ["have", "make", "find"])
def test_a_parts_choice_over_a_minute_after_its_view_is_not_marked(
    tmp_path: Path, position: str
) -> None:
    run_dir = listed(tmp_path / "run")
    line = _late(run_dir, ITEM_IDS[0], person(position, STATED[position]))
    assert isinstance(line, QueueResolution), line
    assert line.shown_at == "2026-11-17T09:05:00.250000Z"
    assert line.decomposition_defect is None
    written = json.loads((run_dir / DECISIONS_NAME).read_bytes())
    assert "decomposition_defect" not in written
    assert written["shown_at"] == "2026-11-17T09:05:00.250000Z"
    ((_, read),) = read_queue(run_dir).decisions
    assert read == line


def _other_item(run_dir: Path) -> str:
    run_dir.mkdir(parents=True)
    item = QueueItem(
        item_id="run-1-s1", ts="2026-11-17T09:00:00.000000Z", run_id="run-1", subtask_id="s1",
        source="review_unavailable", decision_required="Decide.", artefact_diff="",
        triggering_finding="a finding", quantities=(), trajectories=("sessions/a/stdout.jsonl",),
    )  # fmt: skip
    (run_dir / QUEUE_NAME).write_bytes(item.model_dump_json().encode() + b"\n")
    (run_dir / DECISIONS_NAME).write_bytes(b"")
    return item.item_id


def test_any_other_decision_over_a_minute_is_marked_as_before(tmp_path: Path) -> None:
    run_dir = tmp_path / "run"
    other = _other_item(run_dir)
    rejected = PersonDecision(verb="reject", note="not as the plan asked")
    line = _late(run_dir, other, rejected, by="yasin")
    assert isinstance(line, QueueResolution), line
    assert line.decomposition_defect is True
    assert json.loads((run_dir / DECISIONS_NAME).read_bytes())["decomposition_defect"] is True


# --- the record's validator -------------------------------------------------------------------

BOUND = {
    "item_id": "run-1-parts-1",
    "kind": "resolution",
    "resolved_by": "operator",
    "verb": "choose",
    "shown_sha256": "a" * 64,
    "shown_at": "2026-11-17T09:00:00.000000Z",
}
OVER = "2026-11-17T09:05:00.000000Z"
UNDER = "2026-11-17T09:00:30.000000Z"
PARTS_FIELDS = {
    "have": {"parts": {"declared": {"mass": {"value": 0.4, "unit": "kg"}}, "texts": []}},
    "make": {"parts": {"declared": {}, "texts": ["printed in PETG"]}},
    "find": {},
}


def _line(position: str, ts: str, **more: Any) -> dict[str, Any]:  # noqa: ANN401
    return {
        **BOUND,
        "decision": f"choose {position}",
        "position": position,
        "ts": ts,
        **PARTS_FIELDS[position],
        **more,
    }


def _read(fields: dict[str, Any]) -> QueueResolution | str:
    """The line as a reader of the file reads it, or why it is refused."""
    try:
        return QueueResolution.model_validate_json(json.dumps(fields))
    except ValueError as exc:
        return str(exc)


@pytest.mark.parametrize("position", ["have", "make", "find"])
def test_a_parts_line_over_a_minute_unmarked_is_admitted(position: str) -> None:
    line = _read(_line(position, OVER))
    assert isinstance(line, QueueResolution), line
    assert line.decomposition_defect is None
    assert "decomposition_defect" not in line.model_dump_json()


@pytest.mark.parametrize("position", ["have", "make", "find"])
def test_a_parts_line_written_before_the_exemption_still_validates(position: str) -> None:
    # The writer marked a part's choice over a minute until the exemption: those lines stand.
    line = _read(_line(position, OVER, decomposition_defect=True))
    assert isinstance(line, QueueResolution), line
    assert line.decomposition_defect is True
    assert json.loads(line.model_dump_json())["decomposition_defect"] is True


@pytest.mark.parametrize("position", ["have", "make", "find"])
def test_a_parts_line_marked_within_a_minute_or_with_no_view_is_refused(position: str) -> None:
    for fields in (
        _line(position, UNDER, decomposition_defect=True),
        {
            **{k: v for k, v in _line(position, OVER).items() if k != "shown_at"},
            "decomposition_defect": True,
        },
    ):
        said = _read(fields)
        assert isinstance(said, str) and "exactly when" in said, said


def test_another_line_over_a_minute_unmarked_is_still_refused() -> None:
    fields = {
        **BOUND,
        "item_id": "run-1-s1",
        "verb": "reject",
        "decision": "reject: not as the plan asked",
        "note": "not as the plan asked",
        "ts": OVER,
    }
    said = _read(fields)
    assert isinstance(said, str) and "exactly when" in said, said
    assert isinstance(_read({**fields, "decomposition_defect": True}), QueueResolution)


# --- a run whose parts lines were written before the exemption ---------------------------------


def test_a_run_whose_parts_lines_are_marked_is_taken_and_follows_in_the_replay(
    tmp_path: Path,
) -> None:
    the_rig = started(tmp_path / "run")
    run_dir = the_rig.run_dir
    assert again(the_rig) == "wait"
    # Each part decided on its view, then its line as the writer wrote it before the exemption:
    # shown five minutes before, and marked.
    lines = []
    for part, position in zip(ITEM_IDS, ("have", "make", "find"), strict=True):
        line = record_decision(
            run_dir,
            part,
            person=person(position, STATED[position]),
            resolved_by="operator",
            shown=shown(run_dir, part),
        )
        decided = datetime.strptime(line.ts, "%Y-%m-%dT%H:%M:%S.%fZ").replace(tzinfo=UTC)
        earlier = (decided - LATE).strftime("%Y-%m-%dT%H:%M:%S.%fZ")
        old = _read(
            {
                **json.loads(line.model_dump_json()),
                "shown_at": earlier,
                "decomposition_defect": True,
            }
        )
        assert isinstance(old, QueueResolution), old
        lines.append(old)
    (run_dir / DECISIONS_NAME).write_bytes(
        b"".join(one.model_dump_json().encode() + b"\n" for one in lines)
    )
    assert [read for _, read in read_queue(run_dir).decisions] == lines
    assert again(rig(run_dir)) == "done"
    assert kinds(run_dir).count("decision_taken") == 3
    assert "stage_entered" in dispatched(run_dir)
    assert "incident" not in kinds(run_dir)
    assert refusal(tmp_path, log_of(run_dir)) == ""
