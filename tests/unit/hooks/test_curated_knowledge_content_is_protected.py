"""The whole ``knowledge/`` tree is protected as one root; ``staging/`` is the one carve-out.

Protecting only the domain directories discovered at settings-build time left
a domain with no directory yet (so no curated content yet) completely
unprotected: an ordinary Write call could plant a standards or skill file
there, with no refusal at all, and for a skill file a later real promotion
would never remove it (promotion only appends for that kind). Found live
against the real binary, by an independent review. Fixed the other way
around: ``knowledge/`` is protected whole, whether or not the tree or any
domain beneath it exists on disk yet, and ``knowledge/staging/`` is named as
this one root's one explicit exception.

The bypass suite (``tests/integration/hooks``) proves this against the real
binary through the shell and tool layers, including a domain that does not
pre-exist; this is the fast, direct check of the configuration and the
matcher itself.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from physgate.hooks.paths import protection
from physgate.hooks.reasons import KNOWLEDGE_REASON
from physgate.hooks.settings import InstallRequest, build_config, current_installation


def _request(tmp: Path, **overrides: Any) -> InstallRequest:  # noqa: ANN401 - test fields
    worktree = tmp / "worktree"
    worktree.mkdir(exist_ok=True)
    fields: dict[str, Any] = {
        "profile": "role",
        "role": "electrical",
        "worktree": str(worktree),
        "own_branch": "subtask/e1",
        "store_root": str(tmp / "store"),
        "state_dir": str(tmp / "state"),
        "target_dir": str(tmp / "session"),
        "claude_config_dir": str(tmp / "claude-config"),
        "user_home": str(tmp / "home"),
        "token_ceiling": 4000,
    }
    fields.update(overrides)
    return InstallRequest(**fields)


def _roots(config: Any) -> dict[str, tuple[str, str, tuple[str, ...]]]:  # noqa: ANN401 - test helper
    return {r.path: (r.reason, r.watch, tuple(r.exceptions)) for r in config.protected_roots}


def test_the_whole_knowledge_tree_is_one_protected_root(tmp_path: Path) -> None:
    worktree = tmp_path / "worktree"
    worktree.mkdir()
    (worktree / "knowledge" / "control").mkdir(parents=True)
    (worktree / "knowledge" / "control" / "standards.md").write_text("curated\n")
    config = build_config(_request(tmp_path), current_installation())
    roots = _roots(config)
    knowledge = str(worktree / "knowledge")
    reason, watch, exceptions = roots[knowledge]
    assert (reason, watch) == (KNOWLEDGE_REASON, "revert")
    assert exceptions == (str(worktree / "knowledge" / "staging"),)


def test_no_knowledge_directory_on_disk_yet_is_protected_all_the_same(tmp_path: Path) -> None:
    # A worktree at a commit before any curated content landed: the root is
    # still named, and a write under it is still refused — this is the one
    # case the old, discover-what-exists approach got backwards.
    worktree = tmp_path / "worktree"
    config = build_config(_request(tmp_path), current_installation())
    knowledge = str(worktree / "knowledge")
    assert knowledge in _roots(config)
    reason = protection(
        str(worktree / "knowledge" / "mechanical" / "standards.md"),
        str(worktree),
        config,
        writing=True,
    )
    assert reason == KNOWLEDGE_REASON


def test_a_domain_with_no_directory_yet_is_protected_exactly_like_one_that_exists(
    tmp_path: Path,
) -> None:
    # The live-reproduced gap this fixes: `mechanical` has no directory at all,
    # `control` does — both must refuse a write the same way.
    worktree = tmp_path / "worktree"
    worktree.mkdir()
    (worktree / "knowledge" / "control").mkdir(parents=True)
    config = build_config(_request(tmp_path), current_installation())
    for target in (
        worktree / "knowledge" / "control" / "standards.md",
        worktree / "knowledge" / "mechanical" / "standards.md",
        worktree / "knowledge" / "mechanical" / "skill.md",
    ):
        reason = protection(str(target), str(worktree), config, writing=True)
        assert reason == KNOWLEDGE_REASON, f"{target} was not refused"


def test_a_file_directly_under_knowledge_is_protected_too(tmp_path: Path) -> None:
    # Under the old per-domain-directory discovery this was deliberately
    # exempt (not a domain directory, so not enumerated); under whole-tree
    # protection it is simply inside the one protected root, correctly.
    worktree = tmp_path / "worktree"
    worktree.mkdir()
    (worktree / "knowledge").mkdir()
    (worktree / "knowledge" / "README.md").write_text("not a domain\n")
    config = build_config(_request(tmp_path), current_installation())
    reason = protection(
        str(worktree / "knowledge" / "README.md"), str(worktree), config, writing=True
    )
    assert reason == KNOWLEDGE_REASON


def test_staging_is_never_protected(tmp_path: Path) -> None:
    worktree = tmp_path / "worktree"
    worktree.mkdir()
    (worktree / "knowledge" / "control").mkdir(parents=True)
    (worktree / "knowledge" / "staging" / "skill").mkdir(parents=True)
    (worktree / "knowledge" / "staging" / "skill" / "a.json").write_text("{}\n")
    config = build_config(_request(tmp_path), current_installation())
    reason = protection(
        str(worktree / "knowledge" / "staging" / "skill" / "a.json"),
        str(worktree),
        config,
        writing=True,
    )
    assert reason is None


def test_staging_is_not_protected_even_before_it_exists_on_disk(tmp_path: Path) -> None:
    # The exception is a named path, not a discovered one: it works the same
    # way the root itself does for a path that does not exist yet.
    worktree = tmp_path / "worktree"
    config = build_config(_request(tmp_path), current_installation())
    reason = protection(
        str(worktree / "knowledge" / "staging" / "standards" / "new.json"),
        str(worktree),
        config,
        writing=True,
    )
    assert reason is None


def test_a_path_only_resembling_staging_is_still_protected(tmp_path: Path) -> None:
    # `knowledge/staging-notes/` is not `knowledge/staging/`: the exception is
    # an exact subtree, not a prefix match on the word.
    worktree = tmp_path / "worktree"
    config = build_config(_request(tmp_path), current_installation())
    reason = protection(
        str(worktree / "knowledge" / "staging-notes" / "x.md"), str(worktree), config, writing=True
    )
    assert reason == KNOWLEDGE_REASON
