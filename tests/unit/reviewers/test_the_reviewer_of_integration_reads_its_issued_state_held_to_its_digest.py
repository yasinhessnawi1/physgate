"""The reviewer of integration's attempt reads the issued state its session read, to its digest.

The packet of an attempt of integration's subtask carries ``integration_state.md``: the document
the session was handed, byte for byte, as the attempt carries it with the digest and length its
line records. It is required reading after the issued specification, named in the listing,
recorded by digest and held to it before the review starts. A packet of any other attempt holds no
such file and records exactly what it recorded before.
"""

from __future__ import annotations

import hashlib
import json
from pathlib import Path

import pytest
from knowledge_fixture import write_fixture
from packet_fixture import ISSUED, SPEC, artefact_of, make_attempt, stream
from pydantic import ValidationError
from rubric_fixture import PLACEHOLDER

from physgate.orchestrator.protocols import IssuedSpec, IssuedState
from physgate.reviewers.packet import (
    INTEGRATION_STATE_NAME,
    SPEC_AS_ISSUED_NAME,
    Packet,
    PacketError,
    build_packet,
    check_parts,
    joined_parts,
    listed_paths,
)
from physgate.reviewers.rubric import Rubric

RUBRIC = Rubric(
    role="control", text=PLACEHOLDER, sha256=hashlib.sha256(PLACEHOLDER.encode()).hexdigest()
)
TEXT = "# Integration's issued state\n\nThe run's gate mode is \"observe\". ⏎\n"


def state_of(text: str) -> IssuedState:
    data = text.encode("utf-8")
    return IssuedState(text=text, sha256=hashlib.sha256(data).hexdigest(), length=len(data))


def _build(tmp_path: Path, state: IssuedState | None) -> tuple[Packet, Path, Path, str]:
    attempt = make_attempt(tmp_path, stream())
    library = tmp_path / "harness"
    write_fixture(library, ("cross", "control"))
    review = tmp_path / "reviews" / "r0123456789ab"
    artefact = artefact_of(attempt).model_copy(update={"integration_state": state})
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
    return packet, review / "read", attempt.worktree, attempt.spec_commit


def test_the_reviewer_packet_holds_the_state_to_its_digest(tmp_path: Path) -> None:
    state = state_of(TEXT)
    packet, read, repo, base = _build(tmp_path, state)
    path = read / INTEGRATION_STATE_NAME
    assert path.is_file(), "the packet holds no issued state"
    assert path.read_bytes() == TEXT.encode("utf-8")
    assert packet.integration_state_sha256 == state.sha256
    # Required reading, straight after the issued specification, and named in the listing.
    reading = list(packet.required_reading)
    assert reading.index(str(path)) == reading.index(str(read / SPEC_AS_ISSUED_NAME)) + 1
    assert str(path) in listed_paths(joined_parts(read, packet.files_parts).decode())
    check_parts(packet, repo=repo, base_commit=base)


@pytest.mark.parametrize("change", ["rewritten", "removed"])
def test_a_changed_or_removed_state_is_refused_before_the_review(
    tmp_path: Path, change: str
) -> None:
    packet, read, repo, base = _build(tmp_path, state_of(TEXT))
    path = read / INTEGRATION_STATE_NAME
    assert path.is_file(), "the packet holds no issued state"
    if change == "removed":
        path.unlink()
    else:
        path.write_text(TEXT.replace("observe", "on"))
    with pytest.raises(PacketError, match="issued state"):
        check_parts(packet, repo=repo, base_commit=base)


def test_a_packet_whose_record_names_another_digest_is_refused(tmp_path: Path) -> None:
    packet, _, repo, base = _build(tmp_path, state_of(TEXT))
    other = packet.model_copy(update={"integration_state_sha256": "0" * 64})
    with pytest.raises(PacketError, match="issued state"):
        check_parts(other, repo=repo, base_commit=base)


def test_a_state_whose_text_is_not_its_digest_is_no_issued_state() -> None:
    good = state_of(TEXT)
    with pytest.raises(ValidationError, match="digest and length"):
        IssuedState(text=TEXT + "x", sha256=good.sha256, length=good.length)
    with pytest.raises(ValidationError, match="digest and length"):
        IssuedState(text=TEXT, sha256=good.sha256, length=good.length + 1)


def test_a_packet_of_any_other_attempt_holds_no_state_and_records_as_before(
    tmp_path: Path,
) -> None:
    packet, read, repo, base = _build(tmp_path, None)
    assert not (read / INTEGRATION_STATE_NAME).exists()
    recorded = json.loads(packet.model_dump_json())
    assert "integration_state_sha256" not in recorded
    assert recorded["artefact"] is not None and "integration_state" not in recorded["artefact"]
    check_parts(packet, repo=repo, base_commit=base)


def test_a_state_file_in_a_packet_of_another_attempt_is_refused(tmp_path: Path) -> None:
    packet, read, repo, base = _build(tmp_path, None)
    (read / INTEGRATION_STATE_NAME).write_text(TEXT)
    with pytest.raises(PacketError):
        check_parts(packet, repo=repo, base_commit=base)
