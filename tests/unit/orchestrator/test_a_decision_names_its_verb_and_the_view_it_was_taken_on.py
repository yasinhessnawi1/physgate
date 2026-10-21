"""A person's decision names its verb, its note and the item line it was taken on.

ARCH-133: an approve binds to what was shown. The decision function records the verb, the
note and the digest of the item line the person saw, beside the free-text decision every
reader already knows; it refuses a bound approve on a view any of whose trajectories did not
hold its seal, and an approve of a blocked review that does not say how the blocked check is
decided. The note is bounded and clean before anything is written. ``physgate queue resolve``
binds the same way, by the digest ``queue list`` printed; its free-text form still records,
and binds to nothing.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from loop_fakes import FakeDispatcher, FakeGate, FakeReviewer, Rig, plan
from pydantic import ValidationError

from physgate.cli import main
from physgate.orchestrator.events import read_events
from physgate.orchestrator.exceptions import QueueError
from physgate.orchestrator.protocols import ReviewResult, SpecDefect
from physgate.orchestrator.queue import (
    DECISIONS_NAME,
    MAX_NOTE,
    PersonDecision,
    QueueResolution,
    ShownItem,
    queue_listing,
    read_queue,
    record_decision,
    trajectory_statuses,
)

ITEM = "run-1-s1"


@pytest.fixture
def run_dir(tmp_path: Path) -> Path:
    """One subtask escalated after three gate failures, its streams real and sealed."""
    run = tmp_path / "runs" / "run"
    run.mkdir(parents=True)
    rig = Rig(run, dispatcher=FakeDispatcher(trajectories=run / "sessions"))
    rig.gate = FakeGate(verdicts=["fail"] * 3)
    loop = rig.open()
    loop.start(plan("s1"))
    loop.run()
    loop.close()
    return run


@pytest.fixture
def blocked_dir(tmp_path: Path) -> Path:
    """One subtask whose review blocked on the specification."""
    run = tmp_path / "runs" / "blocked"
    run.mkdir(parents=True)
    blocked = ReviewResult(
        verdict="blocked",
        finding="the mass is not given",
        reviewer_model="claude-opus-5-5",
        session_id="rev-1",
        usage=(),
        spec_defects=(SpecDefect(finding="no mass", blocking=True),),
    )
    rig = Rig(
        run,
        dispatcher=FakeDispatcher(trajectories=run / "sessions"),
        reviewer=FakeReviewer(results={1: blocked}),
    )
    loop = rig.open()
    loop.start(plan("s1"))
    loop.run()
    loop.close()
    return run


def _shown(run: Path, item: str = ITEM) -> ShownItem:
    view = read_queue(run)
    found = next(i for i in view.items if i.item_id == item)
    events = read_events(run / "events.jsonl")

    def read(session_id: str) -> bytes | None:
        path = run / "sessions" / session_id / "stdout.jsonl"
        return path.read_bytes() if path.exists() else None

    return ShownItem(
        item_sha256=view.digests[item], trajectories=trajectory_statuses(found, events, read)
    )


def _lines(run: Path) -> list[dict[str, object]]:
    return [json.loads(line) for line in (run / DECISIONS_NAME).read_bytes().splitlines()]


# -- the structured decision ----------------------------------------------------------------


def test_a_person_s_decision_is_its_verb_and_a_clean_bounded_note() -> None:
    assert PersonDecision(verb="approve", note=None).text() == "approve"
    assert PersonDecision(verb="reject", note="split it").text() == "reject: split it"
    assert PersonDecision(verb="approve", note="line one\n\tline two").note is not None
    PersonDecision(verb="approve", note="x" * MAX_NOTE)


@pytest.mark.parametrize(
    ("verb", "note"),
    [
        ("reject", None),
        ("reject", "   \n"),
        ("approve", "  "),
        ("approve", "x" * (MAX_NOTE + 1)),
        ("approve", "a bell \x07 in it"),
        ("reject", "an escape \x1b[31m"),
        ("reject", "a carriage return \r here"),
        ("reject", "a C1 control \x85 here"),
        ("defer", "x"),
    ],
    ids=[
        "reject, no note",
        "reject, blank note",
        "a blank note",
        "a note past its cap",
        "a bell",
        "an escape",
        "a carriage return",
        "a C1 control",
        "no such verb",
    ],
)
def test_a_decision_that_is_not_clean_is_refused(verb: str, note: str | None) -> None:
    with pytest.raises(ValidationError):
        PersonDecision.model_validate({"verb": verb, "note": note})


def test_the_note_cap_is_four_thousand_characters() -> None:
    assert MAX_NOTE == 4000


# -- recorded bound -------------------------------------------------------------------------


def test_a_bound_decision_records_its_verb_note_and_the_digest_shown(run_dir: Path) -> None:
    shown = _shown(run_dir)
    record = record_decision(
        run_dir,
        ITEM,
        person=PersonDecision(verb="reject", note="split the subtask"),
        resolved_by="yasin",
        shown=shown,
    )
    assert record.verb == "reject"
    assert record.note == "split the subtask"
    assert record.shown_sha256 == shown.item_sha256
    assert record.decision == "reject: split the subtask"
    assert _lines(run_dir)[-1] == json.loads(record.model_dump_json())


def test_a_free_text_decision_is_written_exactly_as_before(run_dir: Path) -> None:
    record = record_decision(run_dir, ITEM, decision="approve", resolved_by="yasin")
    line = _lines(run_dir)[-1]
    assert set(line) == {"item_id", "ts", "kind", "decision", "resolved_by"}
    assert record.verb is None and record.shown_sha256 is None


def test_a_legacy_decision_line_reads() -> None:
    raw = (
        b'{"item_id":"q","ts":"2026-10-21T12:00:00.000000Z","kind":"resolution",'
        b'"decision":"approve: fine","resolved_by":"yasin"}'
    )
    record = QueueResolution.model_validate_json(raw)
    assert record.verb is None and record.note is None and record.shown_sha256 is None
    assert record.model_dump_json().encode() == raw


def test_a_verb_decision_without_a_view_is_refused_and_writes_nothing(run_dir: Path) -> None:
    before = (run_dir / DECISIONS_NAME).read_bytes()
    with pytest.raises(QueueError, match="bound to the view"):
        record_decision(
            run_dir, ITEM, person=PersonDecision(verb="approve", note=None), resolved_by="yasin"
        )
    with pytest.raises(QueueError, match="one of"):
        record_decision(run_dir, ITEM, resolved_by="yasin")
    assert (run_dir / DECISIONS_NAME).read_bytes() == before


def test_an_approve_on_a_view_whose_trajectory_does_not_hold_is_refused(run_dir: Path) -> None:
    item = next(i for i in read_queue(run_dir).items if i.item_id == ITEM)
    Path(item.trajectories[0]).unlink()
    shown = _shown(run_dir)
    assert shown.trajectories[0] == "missing"
    before = (run_dir / DECISIONS_NAME).read_bytes()
    with pytest.raises(QueueError, match="every trajectory"):
        record_decision(
            run_dir,
            ITEM,
            person=PersonDecision(verb="approve", note=None),
            resolved_by="yasin",
            shown=shown,
        )
    assert (run_dir / DECISIONS_NAME).read_bytes() == before
    # A rejection on the same view is a person's word and is recorded: it merges nothing.
    record_decision(
        run_dir,
        ITEM,
        person=PersonDecision(verb="reject", note="the record is gone"),
        resolved_by="yasin",
        shown=shown,
    )


def test_approving_a_blocked_review_says_how_the_blocked_check_is_decided(
    blocked_dir: Path,
) -> None:
    shown = _shown(blocked_dir)
    with pytest.raises(QueueError, match="blocked"):
        record_decision(
            blocked_dir,
            ITEM,
            person=PersonDecision(verb="approve", note=None),
            resolved_by="yasin",
            shown=shown,
        )
    record_decision(
        blocked_dir,
        ITEM,
        person=PersonDecision(verb="approve", note="the mass is 1.2 kg, from the frame drawing"),
        resolved_by="yasin",
        shown=shown,
    )


# -- the command ----------------------------------------------------------------------------


def _resolve(run: Path, *extra: str) -> int:
    return main(["queue", "resolve", ITEM, "--run-dir", str(run), "--by", "yasin", *extra])


def test_the_command_binds_a_verb_by_the_digest_the_listing_printed(
    run_dir: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    assert main(["queue", "list", "--run-dir", str(run_dir)]) == 0
    listed = json.loads(capsys.readouterr().out)["open"][0]
    digest = listed["item_sha256"]
    assert listed["trajectory_statuses"] == ["holds", "holds", "holds"]
    assert _resolve(run_dir, "--reject", "--note", "split it", "--sha256", digest) == 0
    printed = json.loads(capsys.readouterr().out)["resolved"]
    assert printed["verb"] == "reject" and printed["shown_sha256"] == digest
    assert printed["note"] == "split it"


def test_the_command_refuses_a_stale_digest_and_writes_nothing(
    run_dir: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    before = (run_dir / DECISIONS_NAME).read_bytes()
    assert _resolve(run_dir, "--approve", "--sha256", "0" * 64) == 2
    assert "no longer the one that was shown" in capsys.readouterr().err
    assert (run_dir / DECISIONS_NAME).read_bytes() == before


@pytest.mark.parametrize(
    "args",
    [
        ["--approve"],  # no digest
        ["--reject", "--sha256", "0" * 64],  # no note
        ["--approve", "--decision", "approve", "--sha256", "0" * 64],  # two forms
        [],  # no form
        ["--decision", "approve", "--sha256", "0" * 64],  # a digest for free text
    ],
    ids=["approve without a digest", "reject without a note", "two forms", "none", "free text"],
)
def test_the_command_refuses_a_decision_it_cannot_bind_or_read(
    run_dir: Path, args: list[str], capsys: pytest.CaptureFixture[str]
) -> None:
    before = (run_dir / DECISIONS_NAME).read_bytes()
    try:
        code = _resolve(run_dir, *args)
    except SystemExit as exc:  # argparse's own refusal
        code = int(exc.code or 0)
    assert code == 2
    assert (run_dir / DECISIONS_NAME).read_bytes() == before
    capsys.readouterr()


def test_the_listing_names_the_decision_s_verb_and_digest(run_dir: Path) -> None:
    shown = _shown(run_dir)
    record_decision(
        run_dir,
        ITEM,
        person=PersonDecision(verb="reject", note="split"),
        resolved_by="yasin",
        shown=shown,
    )
    decided = queue_listing(run_dir)["decided"]
    assert isinstance(decided, list)
    assert decided[0]["verb"] == "reject"
    assert decided[0]["shown_sha256"] == shown.item_sha256
