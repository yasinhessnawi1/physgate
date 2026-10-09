"""A packet issues the attempt's whole trajectory, every session of it, in whole-readable parts.

An attempt whose session ended for infrastructure was carried on by a fresh session in
the same worktree; its trajectory is every session, in order, each under its own data
marker and held to its own seal. The transcript and the diff are issued as numbered
parts cut at line boundaries, each small enough for one read to show whole, and every
part is required reading. Before a review starts, the parts joined are held to the
sealed sessions' rendering and to the repository's diff: nothing trimmed, nothing
changed. A line too long for one read is refused when the packet is built.
"""

from __future__ import annotations

import hashlib
import sys
from pathlib import Path

import pytest

# The hook layer's own test helpers build its session configuration; this file holds a
# packet's required reading to that layer, so it borrows them.
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "hooks"))
from hook_helpers import SESSION, event, write_config  # noqa: E402
from knowledge_fixture import write_fixture
from packet_fixture import CONTENT, ISSUED, SPEC, Attempt, artefact_of, make_attempt, stream
from rubric_fixture import PLACEHOLDER

from physgate.hooks import reading
from physgate.hooks.config import HookInput, SessionConfig
from physgate.hooks.runtime import Decision
from physgate.orchestrator.protocols import Artefact, IssuedSpec, SessionTrajectory
from physgate.orchestrator.trajectory import seal
from physgate.reviewers.packet import (
    PART_MAX_BYTES,
    PART_MAX_LINES,
    Packet,
    PacketError,
    build_packet,
    check_parts,
    joined_parts,
    split_parts,
)
from physgate.reviewers.rubric import Rubric
from physgate.reviewers.transcript import joined

RUBRIC = Rubric(
    role="control", text=PLACEHOLDER, sha256=hashlib.sha256(PLACEHOLDER.encode()).hexdigest()
)
FIRST_WORDS = "the first session wrote the tuning loop and ran out of turns"


def _earlier(tmp_path: Path, words: str = FIRST_WORDS) -> SessionTrajectory:
    path = tmp_path / "earlier" / "stdout.jsonl"
    path.parent.mkdir(parents=True)
    path.write_text(
        stream(with_checks_off=False).replace(CONTENT[6], words).replace('"m9"', '"m9-first"')
    )
    sealed = seal(path.read_bytes())
    return SessionTrajectory(
        session_id="sess-1",
        trajectory=str(path),
        trajectory_sha256=sealed.sha256,
        trajectory_length=sealed.length,
    )


def _build(tmp_path: Path, artefact: Artefact, attempt: Attempt) -> tuple[Packet, Path]:
    library = tmp_path / "harness"
    write_fixture(library, ("cross", "control"))
    review = tmp_path / "reviews" / "r0123456789ab"
    packet = build_packet(
        review,
        artefact,
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
    return packet, review / "read"


def test_a_retried_attempt_s_transcript_holds_both_sessions_in_order(tmp_path: Path) -> None:
    attempt = make_attempt(tmp_path, stream())
    earlier = _earlier(tmp_path)
    packet, read = _build(tmp_path, artefact_of(attempt, earlier_sessions=(earlier,)), attempt)
    text = joined(joined_parts(read, packet.transcript_parts).decode())
    first, second = text.index(FIRST_WORDS), text.index(CONTENT[6])
    assert "This attempt ran in 2 sessions" in text
    assert text.index("# Session 1 of 2") < first < text.index("# Session 2 of 2") < second
    assert len(packet.session_seals) == 2 and packet.session_seals[-1] == packet.trajectory_seal
    assert packet.session_seals[0].sha256 == earlier.trajectory_sha256
    nonces = packet.transcript_nonces
    assert len(nonces) == 2 and nonces[0] != nonces[1] and packet.transcript_nonce == nonces[1]
    for nonce in nonces:
        assert f"<<<DATA {nonce}" in text
    # The indicators of every session are listed: the later one switched checks off.
    assert {h.evidence for h in packet.indicators} == {"t2", "t3", "t4"}


def test_a_single_session_reads_as_it_always_did(tmp_path: Path) -> None:
    attempt = make_attempt(tmp_path, stream())
    packet, read = _build(tmp_path, artefact_of(attempt), attempt)
    text = joined_parts(read, packet.transcript_parts).decode()
    assert "sessions, shown in order" not in text and "# Session" not in text
    assert text.startswith("The implementing session, in order")


def test_an_earlier_session_changed_since_it_ended_is_refused(tmp_path: Path) -> None:
    attempt = make_attempt(tmp_path, stream())
    earlier = _earlier(tmp_path)
    Path(earlier.trajectory).write_text("rewritten\n")
    with pytest.raises(PacketError, match="not what it was"):
        _build(tmp_path, artefact_of(attempt, earlier_sessions=(earlier,)), attempt)


def test_the_parts_joined_are_the_rendering_and_the_diff_byte_for_byte(tmp_path: Path) -> None:
    long_stream = stream().replace(CONTENT[6], CONTENT[6] + " " + "word " * 12_000)
    attempt = make_attempt(tmp_path, long_stream)
    packet, read = _build(tmp_path, artefact_of(attempt), attempt)
    assert len(packet.transcript_parts) > 1
    for part in (*packet.transcript_parts, *packet.diff_parts):
        body = (read / part.name).read_bytes()
        assert len(body) <= PART_MAX_BYTES and body.count(b"\n") <= PART_MAX_LINES
        assert str(read / part.name) in packet.required_reading
    whole = joined_parts(read, packet.transcript_parts)
    assert hashlib.sha256(whole).hexdigest() == packet.transcript_sha256
    assert "word " * 100 in joined(whole.decode())
    check_parts(packet, repo=attempt.worktree, base_commit=attempt.spec_commit)


def test_a_part_changed_or_missing_is_refused_before_the_review(tmp_path: Path) -> None:
    attempt = make_attempt(tmp_path, stream())
    packet, read = _build(tmp_path, artefact_of(attempt), attempt)
    first = read / packet.transcript_parts[0].name
    first.write_bytes(first.read_bytes().replace(b"session", b"sessien", 1))
    with pytest.raises(PacketError, match="not what was issued"):
        check_parts(packet, repo=attempt.worktree, base_commit=attempt.spec_commit)
    first.unlink()
    with pytest.raises(PacketError, match="missing"):
        check_parts(packet, repo=attempt.worktree, base_commit=attempt.spec_commit)


def test_a_line_too_long_for_one_read_is_refused_when_the_packet_is_built(
    tmp_path: Path,
) -> None:
    with pytest.raises(PacketError, match="longer than one read can show"):
        split_parts(
            b"short\n" + b"x" * (PART_MAX_BYTES + 1) + b"\n", "diff-{n:02d}-of-{total:02d}.patch"
        )
    assert split_parts(b"a\nb\n", "diff-{n:02d}-of-{total:02d}.patch") == [
        ("diff-01-of-01.patch", b"a\nb\n")
    ]


def test_parts_are_cut_at_line_boundaries_and_numbered_in_order() -> None:
    data = b"".join(f"{n:05d} {'y' * 90}\n".encode() for n in range(1, 801))
    parts = split_parts(data, "transcript-{n:02d}-of-{total:02d}.md")
    assert b"".join(body for _, body in parts) == data
    assert all(body.endswith(b"\n") and len(body) <= PART_MAX_BYTES for _, body in parts)
    total = len(parts)
    assert [name for name, _ in parts] == [
        f"transcript-{n:02d}-of-{total:02d}.md" for n in range(1, total + 1)
    ]


def _config(tmp_path: Path, packet: Packet) -> SessionConfig:
    _, _, config = write_config(tmp_path / "hooks", required_reading=list(packet.required_reading))
    return config


def _read_whole(config: SessionConfig, path: str) -> None:
    lines = reading.content_lines(Path(path).read_bytes())
    total = lines + 1 if Path(path).read_bytes().endswith(b"\n") else lines
    hook_input = HookInput.model_validate(
        event(
            "PostToolUse",
            session_id=SESSION,
            tool_name="Read",
            tool_input={"file_path": path},
            tool_response={
                "type": "text",
                "file": {
                    "filePath": path,
                    "content": "...",
                    "numLines": total,
                    "startLine": 1,
                    "totalLines": total,
                },
            },
        )
    )
    assert reading.post_tool_use(hook_input, config).allow


def _verdict(config: SessionConfig) -> Decision:
    return reading.pre_tool_use(
        HookInput.model_validate(
            event(tool_name="StructuredOutput", session_id=SESSION, tool_input={})
        ),
        config,
    )


def test_a_reviewer_that_skips_the_first_session_is_refused_its_verdict(tmp_path: Path) -> None:
    long_first = FIRST_WORDS + " " + "step " * 8_000
    attempt = make_attempt(tmp_path, stream())
    earlier = _earlier(tmp_path, long_first)
    packet, read = _build(tmp_path, artefact_of(attempt, earlier_sessions=(earlier,)), attempt)
    first_part = str(read / packet.transcript_parts[0].name)
    assert FIRST_WORDS in (read / packet.transcript_parts[0].name).read_text()
    config = _config(tmp_path, packet)
    for path in packet.required_reading:
        if path != first_part:
            _read_whole(config, path)
    refused = _verdict(config)
    assert not refused.allow and first_part in refused.reason
    _read_whole(config, first_part)
    assert _verdict(config).allow


def test_an_unread_or_missing_part_refuses_the_verdict(tmp_path: Path) -> None:
    attempt = make_attempt(tmp_path, stream())
    packet, read = _build(tmp_path, artefact_of(attempt), attempt)
    config = _config(tmp_path, packet)
    diff_part = str(read / packet.diff_parts[-1].name)
    for path in packet.required_reading:
        if path != diff_part:
            _read_whole(config, path)
    assert diff_part in _verdict(config).reason
    Path(diff_part).unlink()
    assert "cannot be read" in _verdict(config).reason
