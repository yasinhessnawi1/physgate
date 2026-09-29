"""Every curated domain directory under ``knowledge/`` is protected; ``staging/`` is not.

The bypass suite (``tests/integration/hooks``) proves this against the real
binary through the shell and tool layers; this is the fast, direct check of
the discovery rule itself.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

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


def _roots(config: Any) -> dict[str, tuple[str, str]]:  # noqa: ANN401 - test helper
    return {r.path: (r.reason, r.watch) for r in config.protected_roots}


def test_a_curated_domain_directory_is_protected_whole(tmp_path: Path) -> None:
    worktree = tmp_path / "worktree"
    worktree.mkdir()
    (worktree / "knowledge" / "control").mkdir(parents=True)
    (worktree / "knowledge" / "control" / "standards.md").write_text("curated\n")
    (worktree / "knowledge" / "control" / "skill.md").write_text("curated\n")
    config = build_config(_request(tmp_path), current_installation())
    roots = _roots(config)
    control = str(worktree / "knowledge" / "control")
    assert roots[control] == (KNOWLEDGE_REASON, "revert")


def test_multiple_curated_domains_are_each_protected(tmp_path: Path) -> None:
    worktree = tmp_path / "worktree"
    worktree.mkdir()
    for domain in ("control", "firmware", "cross"):
        (worktree / "knowledge" / domain).mkdir(parents=True)
    config = build_config(_request(tmp_path), current_installation())
    roots = _roots(config)
    for domain in ("control", "firmware", "cross"):
        assert str(worktree / "knowledge" / domain) in roots


def test_staging_is_never_protected(tmp_path: Path) -> None:
    worktree = tmp_path / "worktree"
    worktree.mkdir()
    (worktree / "knowledge" / "control").mkdir(parents=True)
    (worktree / "knowledge" / "staging" / "skill").mkdir(parents=True)
    (worktree / "knowledge" / "staging" / "skill" / "a.json").write_text("{}\n")
    config = build_config(_request(tmp_path), current_installation())
    roots = _roots(config)
    staging = str(worktree / "knowledge" / "staging")
    assert staging not in roots
    assert not any(Path(path).is_relative_to(Path(staging)) for path in roots)


def test_a_file_directly_under_knowledge_is_not_treated_as_a_domain(tmp_path: Path) -> None:
    worktree = tmp_path / "worktree"
    worktree.mkdir()
    (worktree / "knowledge").mkdir()
    (worktree / "knowledge" / "README.md").write_text("not a domain\n")
    config = build_config(_request(tmp_path), current_installation())
    assert str(worktree / "knowledge" / "README.md") not in _roots(config)


def test_no_knowledge_directory_yet_adds_no_roots_and_does_not_raise(tmp_path: Path) -> None:
    # A worktree at a commit before any curated content landed: nothing to
    # protect yet, and building the configuration must not fail over it. (Not a
    # bare substring check on "knowledge": the hook interpreter's own
    # installation may itself sit under a path spelling the word, as it does
    # in this checkout.)
    worktree = tmp_path / "worktree"
    config = build_config(_request(tmp_path), current_installation())
    knowledge_dir = worktree / "knowledge"
    assert not any(Path(path).is_relative_to(knowledge_dir) for path in _roots(config))
