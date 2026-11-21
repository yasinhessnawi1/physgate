"""The reviewer of an attempt in a run that asked about parts reads the record its session read.

The packet carries the files the record is rendered to (``parts-01-of-01.md``), beside
``person_order.md``: the same bytes the session was handed, recorded by digest and held to it
before the review starts. They are required reading and named in the listing. A packet of an
attempt that carries no record holds no such file and records exactly what it recorded before.
"""

from __future__ import annotations

import hashlib
import json
from pathlib import Path

import pytest
from knowledge_fixture import write_fixture
from packet_fixture import ISSUED, SPEC, artefact_of, make_attempt, stream
from rubric_fixture import PLACEHOLDER

from physgate.orchestrator.parts_reading import parts_files
from physgate.orchestrator.protocols import IssuedSpec, IssuedState
from physgate.reviewers.packet import (
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
RECORD = json.dumps(
    {
        "components": [
            {
                "node": "control.motor_left",
                "label": "Left drive motor",
                "choice": "make",
                "declared": {"mass": {"value": 0.1, "unit": "kg"}},
                "texts": ["printed in PETG"],
            }
        ]
    },
    sort_keys=True,
    separators=(",", ":"),
).encode()


def record_of(data: bytes = RECORD) -> IssuedState:
    return IssuedState(
        text=data.decode(), sha256=hashlib.sha256(data).hexdigest(), length=len(data)
    )


def _build(tmp_path: Path, held: IssuedState | None) -> tuple[Packet, Path, Path, str]:
    attempt = make_attempt(tmp_path, stream())
    library = tmp_path / "harness"
    write_fixture(library, ("cross", "control"))
    review = tmp_path / "reviews" / "r0123456789ab"
    artefact = artefact_of(attempt).model_copy(update={"parts_record": held})
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


def test_the_packet_holds_the_files_the_session_read_to_their_digests(tmp_path: Path) -> None:
    packet, read, repo, base = _build(tmp_path, record_of())
    files = parts_files(RECORD)
    held = getattr(packet, "parts_record_sha256", {})
    assert [(n, hashlib.sha256(d).hexdigest()) for n, d in files] == sorted(held.items())
    for name, data in files:
        assert (read / name).read_bytes() == data
        assert str(read / name) in packet.required_reading
        assert str(read / name) in listed_paths(joined_parts(read, packet.files_parts).decode())
    check_parts(packet, repo=repo, base_commit=base)


@pytest.mark.parametrize("change", ["rewritten", "removed"])
def test_a_changed_or_removed_file_is_refused_before_the_review(
    tmp_path: Path, change: str
) -> None:
    packet, read, repo, base = _build(tmp_path, record_of())
    path = read / parts_files(RECORD)[0][0]
    assert path.is_file(), "the packet holds no parts file"
    if change == "removed":
        path.unlink()
    else:
        path.write_text(path.read_text().replace("PETG", "steel"))
    with pytest.raises(PacketError, match="parts record"):
        check_parts(packet, repo=repo, base_commit=base)


def test_a_packet_whose_record_names_other_digests_is_refused(tmp_path: Path) -> None:
    packet, _, repo, base = _build(tmp_path, record_of())
    name = parts_files(RECORD)[0][0]
    other = packet.model_copy(update={"parts_record_sha256": {name: "0" * 64}})
    with pytest.raises(PacketError, match="parts record"):
        check_parts(other, repo=repo, base_commit=base)


def test_a_packet_of_an_attempt_with_no_record_holds_none_and_records_as_before(
    tmp_path: Path,
) -> None:
    packet, read, repo, base = _build(tmp_path, None)
    assert not list(read.glob("parts-*"))
    recorded = json.loads(packet.model_dump_json())
    assert "parts_record_sha256" not in recorded
    assert recorded["artefact"] is not None and "parts_record" not in recorded["artefact"]
    check_parts(packet, repo=repo, base_commit=base)


def test_a_parts_file_in_a_packet_of_an_attempt_with_no_record_is_refused(tmp_path: Path) -> None:
    packet, read, repo, base = _build(tmp_path, None)
    (read / "parts-01-of-01.md").write_text("x")
    with pytest.raises(PacketError, match="parts record for an attempt that carries none"):
        check_parts(packet, repo=repo, base_commit=base)


def test_a_packet_that_names_a_record_for_an_attempt_that_carries_none_is_refused(
    tmp_path: Path,
) -> None:
    packet, _, repo, base = _build(tmp_path, None)
    named = packet.model_copy(update={"parts_record_sha256": {"parts-01-of-01.md": "0" * 64}})
    with pytest.raises(PacketError, match="parts record for an attempt that carries none"):
        check_parts(named, repo=repo, base_commit=base)
