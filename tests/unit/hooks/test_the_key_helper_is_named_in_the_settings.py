"""The API key reaches a session through a helper the settings name, never its environment."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest

from physgate.hooks.registry import REGISTRY
from physgate.hooks.settings import InstallRequest, install


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


def test_without_a_helper_the_settings_name_none(tmp_path: Path) -> None:
    settings = json.loads(install(_request(tmp_path), REGISTRY).settings_path.read_text())
    assert "apiKeyHelper" not in settings


@pytest.mark.parametrize("where", ["state", "session"])
def test_a_helper_in_the_sessions_protected_files_is_named(tmp_path: Path, where: str) -> None:
    helper = str(tmp_path / where / "key-helper.sh")
    done = install(_request(tmp_path, api_key_helper=helper), REGISTRY)
    settings = json.loads(done.settings_path.read_text())
    assert settings["apiKeyHelper"] == helper
    assert settings["disableAllHooks"] is False


@pytest.mark.parametrize("where", ["worktree/key.sh", "elsewhere/key.sh"])
def test_a_helper_anywhere_a_session_could_write_is_refused(tmp_path: Path, where: str) -> None:
    with pytest.raises(ValueError, match="key helper"):
        install(_request(tmp_path, api_key_helper=str(tmp_path / where)), REGISTRY)
    assert not (tmp_path / "session").exists()
