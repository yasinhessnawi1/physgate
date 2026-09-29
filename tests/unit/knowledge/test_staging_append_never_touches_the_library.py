"""``staging.append``/``candidates`` (ARCH-100): the emit half, never the library."""

from __future__ import annotations

from pathlib import Path

import pytest

from physgate.knowledge import staging
from physgate.knowledge.exceptions import StagingError


def test_a_written_candidate_round_trips_through_candidates(tmp_path: Path) -> None:
    path = staging.append("skill", "always check units first", "ep-1", staging_root=tmp_path)
    assert path.is_file() and path.parent == tmp_path / "skill"
    (found,) = staging.candidates("skill", staging_root=tmp_path)
    assert found.kind == "skill"
    assert found.content == "always check units first"
    assert found.episode_id == "ep-1"
    assert found.candidate_id == path.stem
    assert staging.candidates("antipattern", staging_root=tmp_path) == ()


def test_append_never_creates_or_modifies_anything_outside_staging_root(tmp_path: Path) -> None:
    staging_root = tmp_path / "staging"
    before = {p for p in tmp_path.rglob("*") if staging_root not in p.parents and p != staging_root}
    staging.append("antipattern", "never skip a source", "ep-2", staging_root=staging_root)
    after = {p for p in tmp_path.rglob("*") if staging_root not in p.parents and p != staging_root}
    assert after == before  # nothing appeared beside `staging_root` itself


def test_two_appends_never_collide(tmp_path: Path) -> None:
    first = staging.append("skill", "a", "ep-1", staging_root=tmp_path)
    second = staging.append("skill", "a", "ep-1", staging_root=tmp_path)
    assert first != second
    assert len(staging.candidates("skill", staging_root=tmp_path)) == 2


@pytest.mark.parametrize("content", ["", "   ", "\n\t"])
def test_empty_content_is_refused_before_any_file_is_written(tmp_path: Path, content: str) -> None:
    with pytest.raises(StagingError, match="empty"):
        staging.append("skill", content, "ep-1", staging_root=tmp_path)
    assert not tmp_path.exists() or list(tmp_path.rglob("*")) == []


@pytest.mark.parametrize("episode_id", ["", "has a space", "has/slash", "a" * 129])
def test_an_unsafe_episode_id_is_refused(tmp_path: Path, episode_id: str) -> None:
    with pytest.raises(StagingError):
        staging.append("skill", "content", episode_id, staging_root=tmp_path)


def test_the_default_staging_root_is_a_subtree_of_the_tracked_knowledge_directory() -> None:
    assert Path("knowledge/staging") == staging.STAGING_ROOT
