"""A role session that reads its reviewer's rubric by a path no hook can judge is caught after.

Detection, not prevention. Each promoted rubric carries one opaque canary line,
recorded in its promotion line. The dispatcher looks for every canary ever
promoted in each role session's own stream; a hit is an incident, the run halts,
and nothing the session did is taken.
"""

from __future__ import annotations

import json
from pathlib import Path

from rubric_fixture import PLACEHOLDER

from physgate.knowledge import staging
from physgate.knowledge.promote import _apply, canaries
from physgate.orchestrator.dispatch import review_material_seen
from physgate.reviewers.rubric import load_rubric


def _promote(root: Path, role: str = "control") -> Path:
    staged = staging.append(
        "rubric", PLACEHOLDER, "e1", domain=role, staging_root=root / staging.RUBRIC_STAGING_ROOT
    )
    return _apply(
        staged.stem,
        by="a person",
        staging_root=root / staging.STAGING_ROOT,
        knowledge_root=root / "knowledge",
        promotions_path=root / "knowledge" / "promotions.jsonl",
        rubric_staging_root=root / staging.RUBRIC_STAGING_ROOT,
    )


def test_a_promoted_rubric_carries_a_canary_its_promotion_records(tmp_path: Path) -> None:
    destination = _promote(tmp_path)
    line = json.loads((tmp_path / "knowledge" / "promotions.jsonl").read_text())
    canary = line["canary"]
    assert len(canary) == 32 and canary in destination.read_text()
    assert canaries(tmp_path / "knowledge" / "promotions.jsonl") == {canary}
    assert load_rubric(tmp_path / "knowledge", "control").items  # still a well-formed rubric


def test_every_version_s_canary_stays_live(tmp_path: Path) -> None:
    _promote(tmp_path)
    _promote(tmp_path)
    _promote(tmp_path, "firmware")
    assert len(canaries(tmp_path / "knowledge" / "promotions.jsonl")) == 3


def test_a_stream_holding_a_canary_is_found_and_one_without_is_not(tmp_path: Path) -> None:
    live = frozenset({"0" * 31 + "a", "f" * 32})
    hit = tmp_path / "hit.jsonl"
    hit.write_text(json.dumps({"type": "user", "message": {"content": "1\\t<!-- " + "f" * 32}}))
    miss = tmp_path / "miss.jsonl"
    miss.write_text(json.dumps({"type": "user", "message": {"content": "ordinary output"}}))
    assert review_material_seen(hit, live) == "f" * 32
    assert review_material_seen(miss, live) is None
    assert review_material_seen(hit, frozenset()) is None
