"""A packet lists every file the reviewer may read, so the reviewer never guesses a name.

A reviewer has the Read tool and nothing that lists a directory: a read of a
directory fails, and a name it guesses may not exist. The packet therefore issues a
listing of every file under its read directory, by full path, in whole-readable
parts, first in the required reading, and the prompt points at it. Before a review
starts, the listing is held to the read directory as it then stands: a file added
or removed after the listing was cut, or a listing rewritten with its record, is
refused.
"""

from __future__ import annotations

import hashlib
from pathlib import Path

import pytest
from knowledge_fixture import write_fixture
from packet_fixture import ISSUED, SPEC, artefact_of, make_attempt, stream
from rubric_fixture import PLACEHOLDER

from physgate.orchestrator.protocols import IssuedSpec
from physgate.reviewers.claude import review_prompt
from physgate.reviewers.packet import (
    FILES_PART,
    PART_MAX_BYTES,
    PART_MAX_LINES,
    WORKTREE_NAME,
    Packet,
    PacketError,
    build_packet,
    check_parts,
    file_listing,
    joined_parts,
    listed_paths,
    split_parts,
)
from physgate.reviewers.rubric import Rubric, evaluation_words

RUBRIC = Rubric(
    role="control", text=PLACEHOLDER, sha256=hashlib.sha256(PLACEHOLDER.encode()).hexdigest()
)


def _build(tmp_path: Path) -> tuple[Packet, Path, Path, str]:
    attempt = make_attempt(tmp_path, stream())
    library = tmp_path / "harness"
    write_fixture(library, ("cross", "control"))
    review = tmp_path / "reviews" / "r0123456789ab"
    packet = build_packet(
        review,
        artefact_of(attempt),
        repo=attempt.worktree,
        base_commit=attempt.spec_commit,
        rubric=RUBRIC,
        library=library,
        spec=IssuedSpec(
            commit=attempt.spec_commit,
            path=SPEC,
            sha256=hashlib.sha256(ISSUED.encode()).hexdigest(),
        ),
    )
    return packet, review / "read", attempt.worktree, attempt.spec_commit


def _files_under(read: Path, packet: Packet) -> set[str]:
    own = {str(read / part.name) for part in packet.files_parts}
    return {str(p) for p in read.rglob("*") if p.is_file()} - own


def test_the_listing_names_every_file_under_the_read_directory_and_nothing_else(
    tmp_path: Path,
) -> None:
    packet, read, _, _ = _build(tmp_path)
    assert packet.files_parts
    listed = listed_paths(joined_parts(read, packet.files_parts).decode())
    assert len(listed) == len(set(listed)), "a file is listed twice"
    assert set(listed) == _files_under(read, packet)
    # The worktree export, the library copies, the rubric and every part are all named.
    assert str(read / WORKTREE_NAME / "m" / "ctl.py") in listed
    assert any("/knowledge/" in p for p in listed)
    assert all(str(read / part.name) in listed for part in packet.diff_parts)


def test_the_listing_is_read_first(tmp_path: Path) -> None:
    packet, read, _, _ = _build(tmp_path)
    first = [str(read / part.name) for part in packet.files_parts]
    assert first
    assert list(packet.required_reading[: len(first)]) == first


def test_the_prompt_points_at_the_listing_and_says_an_unlisted_name_does_not_exist(
    tmp_path: Path,
) -> None:
    packet, read, _, _ = _build(tmp_path)
    prompt = review_prompt("control", packet)
    assert str(read / packet.files_parts[0].name) in prompt
    assert "a name it does not list does not exist" in prompt
    listing = joined_parts(read, packet.files_parts).decode()
    assert "a name it does not list does not exist" in listing.lower()


def test_the_listing_says_nothing_about_being_evaluated(tmp_path: Path) -> None:
    packet, read, _, _ = _build(tmp_path)
    listing = joined_parts(read, packet.files_parts).decode()
    header = listing.split("\n- ", 1)[0]
    assert header.strip() and header != listing
    assert evaluation_words(header) == []


def test_a_long_listing_is_issued_in_whole_readable_parts(tmp_path: Path) -> None:
    read = tmp_path / "read"
    for n in range(900):
        path = read / WORKTREE_NAME / "design" / "nodes" / f"node_{n:04d}_{'x' * 60}.json"
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text("{}\n")
    parts = split_parts(file_listing(read, set()), FILES_PART)
    assert len(parts) > 1
    for _, body in parts:
        assert len(body) <= PART_MAX_BYTES and body.count(b"\n") <= PART_MAX_LINES
    joined = b"".join(body for _, body in parts).decode()
    assert len(listed_paths(joined)) == 900


def test_a_file_added_after_the_listing_is_refused_before_the_review(tmp_path: Path) -> None:
    packet, read, repo, base = _build(tmp_path)
    check_parts(packet, repo=repo, base_commit=base)
    (read / WORKTREE_NAME / "added.md").write_text("not in the commit\n")
    with pytest.raises(PacketError, match="listing"):
        check_parts(packet, repo=repo, base_commit=base)


def test_a_file_removed_after_the_listing_is_refused_before_the_review(tmp_path: Path) -> None:
    packet, read, repo, base = _build(tmp_path)
    (read / WORKTREE_NAME / "m" / "ctl.py").unlink()
    with pytest.raises(PacketError, match="listing"):
        check_parts(packet, repo=repo, base_commit=base)


def test_a_listing_rewritten_with_its_record_is_still_held_to_the_directory(
    tmp_path: Path,
) -> None:
    packet, read, repo, base = _build(tmp_path)
    part = read / packet.files_parts[0].name
    victim = str(read / WORKTREE_NAME / "m" / "ctl.py")
    part.write_text(
        "".join(line for line in part.read_text().splitlines(True) if victim not in line)
    )
    rewritten = packet.model_copy(
        update={
            "files_parts": (
                packet.files_parts[0].model_copy(
                    update={"sha256": hashlib.sha256(part.read_bytes()).hexdigest()}
                ),
                *packet.files_parts[1:],
            )
        }
    )
    with pytest.raises(PacketError, match="listing"):
        check_parts(rewritten, repo=repo, base_commit=base)
