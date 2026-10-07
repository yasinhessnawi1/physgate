"""Only a person's promotion makes a rubric the one a review is held to.

Promotion stands for a person's approval. These are the ways a rubric could reach
the live path without it, each refused, and the ones that cannot be refused here,
pinned so they stay visible:

- a candidate written where a session may write (the general staging directory)
  is never promoted as a rubric;
- a candidate whose own kind disagrees with the directory it was found in is
  refused, so a file cannot change kind by being moved;
- a candidate id that walks out of the staging directory is refused;
- a staged candidate, or a destination, that is a symlink is refused, so a write
  cannot be redirected;
- every session's hooks refuse writes to the reviewer tree and the promotion log,
  with no exception beneath them, and put back what changed;
- the terminal check is not authentication: a pseudo-terminal satisfies it. It
  keeps a script from promoting by accident; what keeps a session from promoting
  on purpose is that the files a promotion writes are protected from it.
"""

from __future__ import annotations

import json
import os
import sys
from pathlib import Path

import pytest
from rubric_fixture import PLACEHOLDER

from physgate.hooks.settings import InstallRequest, build_config, current_installation
from physgate.knowledge import staging
from physgate.knowledge.promote import PromotionError, _apply, require_interactive, rubric_path


def _apply_in(root: Path, candidate_id: str) -> Path:
    return _apply(
        candidate_id,
        by="a person",
        staging_root=root / staging.STAGING_ROOT,
        knowledge_root=root / "knowledge",
        promotions_path=root / "knowledge" / "promotions.jsonl",
        rubric_staging_root=root / staging.RUBRIC_STAGING_ROOT,
    )


def _stage(root: Path, kind: staging.Kind, staging_root: Path, domain: str = "control") -> Path:
    return staging.append(kind, PLACEHOLDER, "episode-1", domain=domain, staging_root=staging_root)


def test_a_rubric_staged_where_a_session_may_write_is_never_promoted(tmp_path: Path) -> None:
    staged = _stage(tmp_path, "rubric", tmp_path / staging.STAGING_ROOT)
    with pytest.raises(PromotionError, match="no staged candidate"):
        _apply_in(tmp_path, staged.stem)
    assert not rubric_path(tmp_path / "knowledge", "control").exists()


def test_a_candidate_moved_into_another_kind_s_directory_is_refused(tmp_path: Path) -> None:
    staged = _stage(tmp_path, "skill", tmp_path / staging.RUBRIC_STAGING_ROOT)
    moved = tmp_path / staging.RUBRIC_STAGING_ROOT / "rubric" / staged.name
    moved.parent.mkdir(parents=True, exist_ok=True)
    staged.rename(moved)
    with pytest.raises(PromotionError, match="kind"):
        _apply_in(tmp_path, moved.stem)
    assert not rubric_path(tmp_path / "knowledge", "control").exists()


@pytest.mark.parametrize("candidate_id", ["../../x", "a/b", "", ".hidden"])
def test_a_candidate_id_that_is_not_a_plain_id_is_refused(
    tmp_path: Path, candidate_id: str
) -> None:
    with pytest.raises(PromotionError, match="plain id"):
        _apply_in(tmp_path, candidate_id)


def test_a_staged_candidate_that_is_a_symlink_is_refused(tmp_path: Path) -> None:
    elsewhere = tmp_path / "elsewhere.json"
    staged = _stage(tmp_path, "rubric", tmp_path / staging.RUBRIC_STAGING_ROOT)
    elsewhere.write_bytes(staged.read_bytes())
    staged.unlink()
    staged.symlink_to(elsewhere)
    with pytest.raises(PromotionError, match="link"):
        _apply_in(tmp_path, staged.stem)


def test_a_destination_that_is_a_symlink_is_refused(tmp_path: Path) -> None:
    target = tmp_path / "somewhere" / "else.md"
    target.parent.mkdir()
    target.write_text("untouched\n")
    destination = rubric_path(tmp_path / "knowledge", "control")
    destination.parent.mkdir(parents=True)
    destination.symlink_to(target)
    staged = _stage(tmp_path, "rubric", tmp_path / staging.RUBRIC_STAGING_ROOT)
    with pytest.raises(PromotionError, match="link"):
        _apply_in(tmp_path, staged.stem)
    assert target.read_text() == "untouched\n"


def test_the_promotion_line_records_what_was_written(tmp_path: Path) -> None:
    staged = _stage(tmp_path, "rubric", tmp_path / staging.RUBRIC_STAGING_ROOT)
    destination = _apply_in(tmp_path, staged.stem)
    line = json.loads((tmp_path / "knowledge" / "promotions.jsonl").read_text())
    import hashlib

    assert line["sha256"] == hashlib.sha256(destination.read_bytes()).hexdigest()


@pytest.mark.parametrize("profile", ["role", "orchestrator"])
def test_no_session_may_write_the_reviewer_tree_or_the_promotion_log(
    tmp_path: Path, profile: str
) -> None:
    worktree = tmp_path / "w"
    worktree.mkdir()
    config = build_config(
        InstallRequest(
            profile=profile,  # type: ignore[arg-type]
            role="control" if profile == "role" else None,
            worktree=str(worktree),
            own_branch=None,
            store_root=None,
            state_dir=str(tmp_path / "o" / "state"),
            target_dir=str(tmp_path / "o" / "settings"),
            claude_config_dir=str(tmp_path / "o" / "config"),
            user_home=str(tmp_path / "o" / "home"),
            token_ceiling=1000,
            harness_root=str(tmp_path / "harness"),
        ),
        current_installation(),
    )
    from physgate.hooks import paths

    for base in (worktree, tmp_path / "harness"):
        for rel in (
            "knowledge/reviewers/control/rubric.md",
            "knowledge/reviewers/staging/rubric/x.json",
            "knowledge/promotions.jsonl",
        ):
            assert paths.protection(str(base / rel), str(worktree), config, writing=True), rel
    # The one exception beneath the knowledge tree is the general staging directory,
    # and a rubric found there is never promoted (the first test above).
    watched = {r.path: r for r in config.protected_roots}
    knowledge = watched[str(worktree / "knowledge")]
    assert knowledge.watch == "revert"
    assert knowledge.exceptions == (str(worktree / "knowledge" / "staging"),)


def test_the_documented_residual_a_pseudo_terminal_satisfies_the_terminal_check(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    primary, secondary = os.openpty()
    try:
        with os.fdopen(secondary, "r") as tty:
            monkeypatch.setattr(sys, "stdin", tty)
            require_interactive()
    finally:
        os.close(primary)
