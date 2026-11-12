"""An attempt's packet holds its rubric and library copies, and cuts long specification lines.

The packet records each copied file's digest. Before the review starts, the rubric and every
library copy are held to those digests, so a same-size edit after the build is refused as a
changed listing or part is. The specification as issued is written with every line cut to what one
read shows, as the plan's brief is, and held to the cut of the commit's own blob: a line one read
would truncate reaches the reviewer whole in pieces, and a line too long for one part no longer
leaves the packet unprepared. A specification with no long line is written byte for byte.
"""

from __future__ import annotations

import hashlib
from pathlib import Path

import pytest
from knowledge_fixture import write_fixture
from packet_fixture import SPEC, Attempt, _git, artefact_of, stream
from rubric_fixture import PLACEHOLDER

from physgate.orchestrator.protocols import IssuedSpec
from physgate.reviewers.packet import (
    KNOWLEDGE_NAME,
    RUBRIC_NAME,
    SPEC_AS_ISSUED_NAME,
    Packet,
    PacketError,
    build_packet,
    check_parts,
)
from physgate.reviewers.rubric import Rubric
from physgate.reviewers.transcript import CONTINUED, WIDTH, joined

RUBRIC = Rubric(
    role="control", text=PLACEHOLDER, sha256=hashlib.sha256(PLACEHOLDER.encode()).hexdigest()
)
SHORT = "# s1\n\n## Acceptance criteria\n\n1. The loop gain is between 0.5 and 2.\n"


def _attempt(root: Path, issued: str) -> Attempt:
    """A repository whose decomposition issued ``issued`` at SPEC, and an attempt after it."""
    repo = root / "target"
    (repo / ".physgate" / "specs").mkdir(parents=True)
    _git(repo, "init", "-q", "-b", "run")
    (repo / SPEC).write_text(issued)
    _git(repo, "add", "-A")
    _git(repo, "commit", "-q", "-m", "issued")
    spec_commit = _git(repo, "rev-parse", "HEAD")
    (repo / "m").mkdir()
    (repo / "m" / "ctl.py").write_text("gain = 0.8\n")
    _git(repo, "add", "-A")
    _git(repo, "commit", "-q", "-m", "attempt")
    trajectory = root / "session" / "stdout.jsonl"
    trajectory.parent.mkdir(parents=True)
    trajectory.write_text(stream())
    return Attempt(repo, spec_commit, _git(repo, "rev-parse", "HEAD"), trajectory)


def _built(tmp_path: Path, issued: str = SHORT) -> tuple[Packet, Path, Attempt]:
    attempt = _attempt(tmp_path, issued)
    library = tmp_path / "harness"
    write_fixture(library, ("cross", "control"))
    spec = IssuedSpec(
        commit=attempt.spec_commit, path=SPEC, sha256=hashlib.sha256(issued.encode()).hexdigest()
    )
    review = tmp_path / "reviews" / "r0123456789ab"
    packet = build_packet(
        review,
        artefact_of(attempt, issued_spec=spec),
        repo=attempt.worktree,
        base_commit=attempt.spec_commit,
        rubric=RUBRIC,
        library=library,
        spec=spec,
    )
    return packet, review / "read", attempt


def _same_size_edit(path: Path) -> None:
    data = bytearray(path.read_bytes())
    data[-2] = ord("X") if data[-2] != ord("X") else ord("Y")
    path.write_bytes(bytes(data))


def test_a_same_size_edit_of_the_rubric_copy_is_refused_before_the_review(tmp_path: Path) -> None:
    packet, read, attempt = _built(tmp_path)
    check_parts(packet, repo=attempt.worktree, base_commit=attempt.spec_commit)
    _same_size_edit(read / RUBRIC_NAME)
    with pytest.raises(PacketError):
        check_parts(packet, repo=attempt.worktree, base_commit=attempt.spec_commit)


def test_a_same_size_edit_of_a_library_copy_is_refused_before_the_review(tmp_path: Path) -> None:
    packet, read, attempt = _built(tmp_path)
    copies = sorted(p for p in (read / KNOWLEDGE_NAME).rglob("*") if p.is_file())
    assert copies, "the packet copied no library file"
    for copy in copies:
        before = copy.read_bytes()
        _same_size_edit(copy)
        with pytest.raises(PacketError):
            check_parts(packet, repo=attempt.worktree, base_commit=attempt.spec_commit)
        copy.write_bytes(before)
    check_parts(packet, repo=attempt.worktree, base_commit=attempt.spec_commit)


def test_a_long_specification_line_is_issued_in_pieces_one_read_shows_whole(
    tmp_path: Path,
) -> None:
    long = "2. " + "the loop gain stays between 0.5 and 2 " * 66  # 2,511 characters
    issued = SHORT + long + "\n"
    packet, read, attempt = _built(tmp_path, issued)
    written = (read / SPEC_AS_ISSUED_NAME).read_text()
    assert max(len(line) for line in written.split("\n")) <= WIDTH + len(CONTINUED), (
        "a specification line is issued longer than one read shows"
    )
    assert joined(written) == issued
    check_parts(packet, repo=attempt.worktree, base_commit=attempt.spec_commit)


def test_a_cut_specification_line_changed_after_the_build_is_refused(tmp_path: Path) -> None:
    issued = SHORT + "2. " + "x" * 2_500 + "\n"
    packet, read, attempt = _built(tmp_path, issued)
    _same_size_edit(read / SPEC_AS_ISSUED_NAME)
    with pytest.raises(PacketError):
        check_parts(packet, repo=attempt.worktree, base_commit=attempt.spec_commit)


def test_a_specification_line_longer_than_one_part_still_prepares_the_packet(
    tmp_path: Path,
) -> None:
    issued = SHORT + "2. " + "y" * 20_500 + "\n"
    packet, read, attempt = _built(tmp_path, issued)
    check_parts(packet, repo=attempt.worktree, base_commit=attempt.spec_commit)
    assert joined((read / SPEC_AS_ISSUED_NAME).read_text()) == issued


def test_a_specification_with_no_long_line_is_issued_byte_for_byte(tmp_path: Path) -> None:
    packet, read, attempt = _built(tmp_path)
    assert (read / SPEC_AS_ISSUED_NAME).read_text() == SHORT
    check_parts(packet, repo=attempt.worktree, base_commit=attempt.spec_commit)
