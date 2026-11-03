"""The reviewer of an attempt whose nodes revise an interface is shown each change (D-A2-37).

The packet carries ``interface-followed.md``, built by code from the change check's derivation: one
line per changed quantity, old -> new, with the node and attempt it followed. It is required
reading, named in the listing, recorded by digest and held to it before the review starts. A
packet of any other attempt holds no such file and records exactly what it recorded before.
"""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any

import pytest
from knowledge_fixture import write_fixture
from packet_fixture import ISSUED, SPEC, artefact_of, make_attempt, stream
from rubric_fixture import PLACEHOLDER

from physgate.orchestrator.follow import follow
from physgate.orchestrator.protocols import IssuedSpec
from physgate.reviewers.packet import (
    FOLLOWED_NAME,
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


def _q(value: float, unit: str, source: str) -> dict[str, Any]:
    return {"value": value, "unit": unit, "source": source, "written_by": "sizing"}


INTERFACE: dict[str, Any] = {
    "id": "drive.motor", "kind": "interface", "domain": "cross", "owner_role": "sizing",
    "quantities": {"stall_current": _q(1.44, "A", "plan"), "current_limit": _q(1.8, "A", "plan")},
    "requirements": [], "constrains": [], "model": None, "geometry_hash": "none",
    "updated": "2026-11-03",
}  # fmt: skip
SIZED: dict[str, Any] = {
    **INTERFACE, "id": "sizing.drive", "kind": "component", "constrains": ["drive.motor"],
    "quantities": {"stall_current": _q(1.35, "A", "fit"), "current_limit": _q(1.8, "A", "sheet")},
}  # fmt: skip


def _build(tmp_path: Path, *, followed: bool) -> tuple[Packet, Path, Path, str]:
    attempt = make_attempt(tmp_path, stream())
    library = tmp_path / "harness"
    write_fixture(library, ("cross", "control"))
    review = tmp_path / "reviews" / "r0123456789ab"
    entry = follow(INTERFACE, {"sizing.drive": SIZED}, "sizing", 1)
    assert entry is not None
    artefact = artefact_of(attempt).model_copy(update={"followed": (entry,) if followed else ()})
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


def test_the_packet_shows_each_changed_quantity_and_holds_it_to_its_digest(tmp_path: Path) -> None:
    packet, read, repo, base = _build(tmp_path, followed=True)
    path = read / FOLLOWED_NAME
    assert path.is_file()
    text = path.read_text()
    assert "- drive.motor.stall_current: 1.44 A -> 1.35 A" in text
    assert "followed from sizing.drive at attempt 1" in text
    assert str(path) in packet.required_reading
    assert str(path) in listed_paths(joined_parts(read, packet.files_parts).decode())
    assert packet.followed_sha256 == hashlib.sha256(text.encode()).hexdigest()
    check_parts(packet, repo=repo, base_commit=base)


def test_a_changed_or_removed_list_of_changes_is_refused_before_the_review(tmp_path: Path) -> None:
    packet, read, repo, base = _build(tmp_path, followed=True)
    path = read / FOLLOWED_NAME
    assert path.is_file()
    path.write_text(path.read_text().replace("1.35 A", "1.30 A"))
    with pytest.raises(PacketError, match="interface revisions"):
        check_parts(packet, repo=repo, base_commit=base)


def test_a_packet_that_follows_nothing_holds_no_list_and_records_as_before(tmp_path: Path) -> None:
    packet, read, repo, base = _build(tmp_path, followed=False)
    assert not (read / FOLLOWED_NAME).exists()
    recorded = json.loads(packet.model_dump_json())
    assert "followed_sha256" not in recorded
    assert recorded["artefact"] is not None and "followed" not in recorded["artefact"]
    check_parts(packet, repo=repo, base_commit=base)
