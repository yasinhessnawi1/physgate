"""A corrected skill file replaces the promoted one whole; an episode's skill still adds to it.

ARCH-100's skill file accumulates one episode at a time, so a skill candidate is
appended. A correction of the whole file, drafted and reviewed as one, must not
be: appended, the corrected text would sit after the words it corrects. Staged as
a replacement, it is written whole, like a standards file, and its promotion line
says so. Only a skill is staged that way; and a rubric that would not load is
refused at promotion, in the promotion's own terms.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from physgate.knowledge import staging
from physgate.knowledge.exceptions import StagingError
from physgate.knowledge.promote import PromotionError, _apply


def _promote(root: Path, staged: Path) -> Path:
    return _apply(
        staged.stem,
        by="a person",
        staging_root=root / staging.STAGING_ROOT,
        knowledge_root=root / "knowledge",
        promotions_path=root / "knowledge" / "promotions.jsonl",
        rubric_staging_root=root / staging.RUBRIC_STAGING_ROOT,
    )


def _stage(root: Path, kind: staging.Kind, text: str, *, replaces: bool = False) -> Path:
    where = staging.RUBRIC_STAGING_ROOT if kind == "rubric" else staging.STAGING_ROOT
    return staging.append(
        kind, text, "drafted", domain="control", staging_root=root / where, replaces=replaces
    )


def test_a_correction_replaces_the_skill_and_an_episode_adds_to_it(tmp_path: Path) -> None:
    skill = _promote(tmp_path, _stage(tmp_path, "skill", "# Skill\n\nThe first version.\n"))
    _promote(tmp_path, _stage(tmp_path, "skill", "One episode's lesson.\n"))
    assert "The first version." in skill.read_text() and "lesson" in skill.read_text()
    corrected = "# Skill\n\nThe corrected version, whole.\n"
    _promote(tmp_path, _stage(tmp_path, "skill", corrected, replaces=True))
    assert skill.read_text() == corrected
    lines = [json.loads(x) for x in (tmp_path / "knowledge" / "promotions.jsonl").open()]
    assert [line.get("replaces", False) for line in lines] == [False, False, True]


@pytest.mark.parametrize("kind", ["standards", "antipattern", "rubric"])
def test_only_a_skill_is_staged_as_a_replacement(tmp_path: Path, kind: staging.Kind) -> None:
    with pytest.raises(StagingError):
        _stage(tmp_path, kind, "text\n", replaces=True)


def test_a_rubric_that_would_not_load_is_refused_at_promotion(tmp_path: Path) -> None:
    staged = _stage(tmp_path, "rubric", "# Not a rubric\n\nNo sections at all.\n")
    with pytest.raises(PromotionError, match="would not load"):
        _promote(tmp_path, staged)
    assert not (tmp_path / "knowledge" / "reviewers" / "control" / "rubric.md").exists()
