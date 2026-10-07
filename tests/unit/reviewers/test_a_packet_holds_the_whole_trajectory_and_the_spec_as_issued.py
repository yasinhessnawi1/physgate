"""A review's packet: the sealed trajectory whole, the commit, the diff, and the spec as issued.

The packet is everything a reviewer may read. It is built only from a trajectory
held to its session's seal, so a review never reads bytes the session did not
write, and never runs without one. The specification is the one the
decomposition issued, read from the commit that issued it: the attempt in the
fixture edits its own acceptance criteria, and the packet's issued copy is the
original while the worktree's copy carries the edit.
"""

from __future__ import annotations

import hashlib
import json
from pathlib import Path

import pytest
from knowledge_fixture import write_fixture
from packet_fixture import CONTENT, EDITED, ISSUED, SPEC, artefact_of, make_attempt, stream
from rubric_fixture import PLACEHOLDER

from physgate.orchestrator.protocols import IssuedSpec
from physgate.reviewers.packet import (
    DIFF_NAME,
    RECORD_NAME,
    RUBRIC_NAME,
    SPEC_AS_ISSUED_NAME,
    TRANSCRIPT_NAME,
    WORKTREE_NAME,
    Packet,
    PacketError,
    build_packet,
)
from physgate.reviewers.rubric import Rubric
from physgate.reviewers.transcript import CONTINUED, WIDTH, joined

ISSUED_SHA = hashlib.sha256(ISSUED.encode()).hexdigest()
RUBRIC = Rubric(
    role="control", text=PLACEHOLDER, sha256=hashlib.sha256(PLACEHOLDER.encode()).hexdigest()
)


def _build(tmp_path: Path, text: str | None = None, **overrides: object) -> tuple[Packet, Path]:
    attempt = make_attempt(tmp_path, stream() if text is None else text)
    library = tmp_path / "harness"
    write_fixture(library, ("cross", "control"))
    review = tmp_path / "reviews" / "r0123456789ab"
    packet = build_packet(
        review,
        artefact_of(attempt, **overrides),
        repo=attempt.worktree,
        base_commit=attempt.spec_commit,
        rubric=RUBRIC,
        library=library,
        spec=IssuedSpec(commit=attempt.spec_commit, path=SPEC, sha256=ISSUED_SHA),
    )
    return packet, review / "read"


def test_the_issued_specification_is_the_decomposition_s_not_the_worktree_s(tmp_path: Path) -> None:
    packet, read = _build(tmp_path)
    assert (read / SPEC_AS_ISSUED_NAME).read_text() == ISSUED
    assert (read / WORKTREE_NAME / SPEC).read_text() == EDITED
    assert "+2. A loop gain of 40 is accepted" in (read / DIFF_NAME).read_text()
    assert packet.spec_as_issued_sha256 == hashlib.sha256(ISSUED.encode()).hexdigest()


def test_every_piece_of_the_session_s_content_is_in_the_transcript(tmp_path: Path) -> None:
    _, read = _build(tmp_path)
    rendered = (read / TRANSCRIPT_NAME).read_text()
    whole = joined(rendered)
    for piece in CONTENT:
        assert piece in whole, piece
    assert '"hook_name": "SessionStart"' not in whole  # a hook beginning: no content
    assert "content_block_delta" not in whole and "rate_limit" not in whole


def test_no_line_of_the_transcript_is_longer_than_the_reader_shows(tmp_path: Path) -> None:
    long_text = stream().replace(CONTENT[6], CONTENT[6] + " " + "x" * 5000)
    _, read = _build(tmp_path, long_text)
    rendered = (read / TRANSCRIPT_NAME).read_text()
    assert max(len(line) for line in rendered.splitlines()) <= WIDTH + len(CONTINUED)
    assert CONTENT[6] + " " + "x" * 5000 in joined(rendered)


def test_the_observable_disabled_checks_are_listed(tmp_path: Path) -> None:
    packet, _ = _build(tmp_path)
    assert {(h.evidence, h.what) for h in packet.indicators} == {
        ("t2", "a lint rule suppressed"),
        ("t3", "an assertion removed"),
        ("t4", "a write to a protected path, refused by the hook layer"),
    }
    assert all(h.kind == "disabled_checks" for h in packet.indicators)


def test_a_clean_trajectory_lists_none(tmp_path: Path) -> None:
    packet, _ = _build(tmp_path, stream(with_checks_off=False))
    assert packet.indicators == ()


def test_the_export_holds_the_commit_and_no_link(tmp_path: Path) -> None:
    packet, read = _build(tmp_path)
    exported = read / WORKTREE_NAME
    assert not (exported / ".git").exists()
    assert (exported / "m" / "ctl.py").read_text() == "gain = 0.8\n"
    note = exported / "m" / "link"
    assert not note.is_symlink() and note.read_text() == "[a symbolic link to: /etc/hosts]\n"
    assert packet.worktree_files == 3


def test_the_rubric_and_library_are_copied_and_required(tmp_path: Path) -> None:
    packet, read = _build(tmp_path)
    assert (read / RUBRIC_NAME).read_text() == PLACEHOLDER
    assert packet.rubric_sha256 == RUBRIC.sha256
    assert set(packet.knowledge_sha256) == {
        "knowledge/cross/standards.md",
        "knowledge/control/standards.md",
        "knowledge/control/skill.md",
    }
    required = [Path(p) for p in packet.required_reading]
    assert all(p.is_relative_to(read) and p.is_file() for p in required)
    assert {p.name for p in required} >= {TRANSCRIPT_NAME, RUBRIC_NAME, SPEC_AS_ISSUED_NAME}
    record = json.loads((read.parent / RECORD_NAME).read_text())
    assert record == json.loads(packet.model_dump_json())


def test_no_seal_no_review(tmp_path: Path) -> None:
    with pytest.raises(PacketError, match="carries none"):
        _build(tmp_path, trajectory_sha256=None, trajectory_length=None)


def test_a_trajectory_changed_after_its_seal_is_refused(tmp_path: Path) -> None:
    attempt = make_attempt(tmp_path, stream())
    artefact = artefact_of(attempt)
    attempt.trajectory.write_text(stream(with_checks_off=False))
    with pytest.raises(PacketError, match="not what it was"):
        build_packet(
            tmp_path / "r",
            artefact,
            repo=attempt.worktree,
            base_commit=attempt.spec_commit,
            rubric=RUBRIC,
            library=tmp_path,
            spec=IssuedSpec(commit=attempt.spec_commit, path=SPEC, sha256=ISSUED_SHA),
        )
    assert not (tmp_path / "r").exists()


def test_a_missing_trajectory_is_refused(tmp_path: Path) -> None:
    attempt = make_attempt(tmp_path, stream())
    artefact = artefact_of(attempt)
    attempt.trajectory.unlink()
    with pytest.raises(PacketError, match="gone"):
        build_packet(
            tmp_path / "r",
            artefact,
            repo=attempt.worktree,
            base_commit=attempt.spec_commit,
            rubric=RUBRIC,
            library=tmp_path,
            spec=None,
        )


def test_an_empty_trajectory_is_refused(tmp_path: Path) -> None:
    with pytest.raises(PacketError, match="empty"):
        _build(tmp_path, "\n")


def test_a_rubric_not_as_loaded_is_refused(tmp_path: Path) -> None:
    attempt = make_attempt(tmp_path, stream())
    library = tmp_path / "harness"
    write_fixture(library, ("cross", "control"))
    changed = RUBRIC.model_copy(update={"text": PLACEHOLDER + "\nmore\n"})
    with pytest.raises(PacketError, match="not the one that was loaded"):
        build_packet(
            tmp_path / "r",
            artefact_of(attempt),
            repo=attempt.worktree,
            base_commit=attempt.spec_commit,
            rubric=changed,
            library=library,
            spec=None,
        )


def test_a_written_account_is_shown_as_it_is(tmp_path: Path) -> None:
    account = "# A proposed revision of the design\n\nIt wrote the nodes below.\n"
    packet, read = _build(tmp_path, account, trajectory_form="account")
    assert (read / TRANSCRIPT_NAME).read_text() == account
    assert packet.indicators == ()


def test_a_packet_is_prepared_once(tmp_path: Path) -> None:
    attempt = make_attempt(tmp_path, stream())
    library = tmp_path / "harness"
    write_fixture(library, ("cross", "control"))
    review = tmp_path / "r"
    (review / "read").mkdir(parents=True)
    with pytest.raises(PacketError, match="new"):
        build_packet(
            review,
            artefact_of(attempt),
            repo=attempt.worktree,
            base_commit=attempt.spec_commit,
            rubric=RUBRIC,
            library=library,
            spec=None,
        )


def test_a_stream_line_the_scan_cannot_read_stops_the_review(tmp_path: Path) -> None:
    with pytest.raises(PacketError, match="not one event"):
        _build(tmp_path, stream() + "this line is not an event\n")
