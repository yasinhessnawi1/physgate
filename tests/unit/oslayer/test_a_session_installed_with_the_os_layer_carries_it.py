"""The hook installer writes the OS layer into a session's settings only when asked to.

With a temporary directory for the session, the settings carry the sandbox
generated from the session's configuration, and the session starts with that
directory as Claude Code's temporary directory. Without one, nothing changes.
A directory too long for Claude Code to keep is refused, because the binary
would silently replace it with the one every session of the user shares. A session
installed with the layer is placed outside every place the layer makes writable, as the
installer requires.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from physgate.hooks.registry import REGISTRY
from physgate.hooks.settings import OS_LAYER_TEMP_LIMIT, InstallRequest, install


def _request(tmp_path: Path, temp: str | None) -> InstallRequest:
    worktree = tmp_path / "worktree"
    worktree.mkdir(exist_ok=True)
    out = tmp_path / "outside"
    return InstallRequest(
        profile="role",
        role="electrical",
        worktree=str(worktree),
        own_branch="subtask/e-1",
        store_root=str(out / "store"),
        state_dir=str(out / "state"),
        target_dir=str(out / "session"),
        claude_config_dir=str(out / "config"),
        user_home=str(out / "home"),
        token_ceiling=1000,
        os_layer_temp_dir=temp,
    )


def test_with_a_temporary_directory_the_settings_carry_the_sandbox(outside_tmp: Path) -> None:
    done = install(_request(outside_tmp, "/tmp/pg-0123456789ab"), REGISTRY)
    settings = json.loads(done.settings_path.read_text())
    assert settings["sandbox"]["enabled"] is True
    assert settings["sandbox"]["failIfUnavailable"] is True
    assert settings["hooks"]  # the hooks are still there, the first layer
    assert done.spawn_env["CLAUDE_CODE_TMPDIR"] == "/tmp/pg-0123456789ab"


def test_without_one_nothing_changes(tmp_path: Path) -> None:
    done = install(_request(tmp_path, None), REGISTRY)
    settings = json.loads(done.settings_path.read_text())
    assert "sandbox" not in settings and "permissions" not in settings
    assert "CLAUDE_CODE_TMPDIR" not in done.spawn_env


def test_a_directory_claude_code_would_replace_is_refused(outside_tmp: Path) -> None:
    long = "/tmp/" + "p" * OS_LAYER_TEMP_LIMIT
    with pytest.raises(ValueError, match="shares"):
        install(_request(outside_tmp, long), REGISTRY)
    assert OS_LAYER_TEMP_LIMIT == 32


def test_offline_the_sandbox_refuses_every_host_in_every_permission_mode(outside_tmp: Path) -> None:
    request = _request(outside_tmp, "/tmp/pg-0123456789ab").model_copy(
        update={"os_layer_network": "none"}
    )
    settings = json.loads(install(request, REGISTRY).settings_path.read_text())
    assert settings["sandbox"]["network"] == {
        "strictAllowlist": True,
        "allowedDomains": [],
        "allowLocalBinding": True,
    }


def test_open_the_sandbox_names_no_network_block(outside_tmp: Path) -> None:
    done = install(_request(outside_tmp, "/tmp/pg-0123456789ab"), REGISTRY)
    assert "network" not in json.loads(done.settings_path.read_text())["sandbox"]
