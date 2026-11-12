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
from typing import Any

import pytest

from physgate.hooks.registry import REGISTRY
from physgate.hooks.settings import (
    OS_LAYER_TEMP_LIMIT,
    InstallRequest,
    build_config,
    install,
)
from physgate.hooks.settings import current_installation as installation

OWN_TEMP = "/var/tmp/pgs/01234567cd"


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
        sessions_root=str(out / "sessions"),
        os_layer_temp_dir=temp,
        # Without the layer the session still has a temporary directory of its own.
        temp_dir=None if temp is not None else OWN_TEMP,
        spawns_with_canary=True,
    )


def test_with_a_temporary_directory_the_settings_carry_the_sandbox(outside_tmp: Path) -> None:
    done = install(_request(outside_tmp, "/var/tmp/pgs/0123456789"), REGISTRY)
    settings = json.loads(done.settings_path.read_text())
    assert settings["sandbox"]["enabled"] is True
    assert settings["sandbox"]["failIfUnavailable"] is True
    assert settings["hooks"]  # the hooks are still there, the first layer
    assert done.spawn_env["CLAUDE_CODE_TMPDIR"] == "/var/tmp/pgs/0123456789"


def test_without_one_nothing_changes_but_the_session_s_own_temporary_directory(
    tmp_path: Path,
) -> None:
    done = install(_request(tmp_path, None), REGISTRY)
    settings = json.loads(done.settings_path.read_text())
    assert "sandbox" not in settings
    # The one permission rule is the web tools' deny, which every session carries.
    assert settings.get("permissions") == {"deny": ["WebFetch", "WebSearch"]}
    assert done.spawn_env["CLAUDE_CODE_TMPDIR"] == OWN_TEMP


def test_with_the_layer_the_settings_still_deny_the_web_tools(outside_tmp: Path) -> None:
    done = install(_request(outside_tmp, "/var/tmp/pgs/0123456789"), REGISTRY)
    settings = json.loads(done.settings_path.read_text())
    assert settings["sandbox"]["enabled"] is True
    assert settings.get("permissions") == {"deny": ["WebFetch", "WebSearch"]}


def test_the_web_deny_survives_a_layer_whose_settings_carry_permissions(
    outside_tmp: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    # The layer's settings are merged into the session's: a permissions block of its own (a
    # deny, a directory) must add to the web tools' deny, never replace it.
    from physgate.hooks import settings as module
    from physgate.oslayer.policy import sandbox_policy as real

    def with_permissions(*args: Any, **kwargs: Any) -> Any:  # noqa: ANN401 - the policy's own
        policy = real(*args, **kwargs)
        policy.settings["permissions"] = {
            "deny": ["Bash(curl:*)"],
            "additionalDirectories": ["/var/tmp/pgs/extra"],
        }
        return policy

    monkeypatch.setattr(module, "sandbox_policy", with_permissions)
    done = install(_request(outside_tmp, "/var/tmp/pgs/0123456789"), REGISTRY)
    permissions = json.loads(done.settings_path.read_text()).get("permissions", {})
    assert set(permissions.get("deny", ())) >= {"WebFetch", "WebSearch", "Bash(curl:*)"}
    assert permissions.get("additionalDirectories") == ["/var/tmp/pgs/extra"]


def _layered(monkeypatch: pytest.MonkeyPatch, permissions: object) -> None:
    """The layer's settings carry ``permissions``, whatever it is."""
    from physgate.hooks import settings as module
    from physgate.oslayer.policy import sandbox_policy as real

    def with_permissions(*args: Any, **kwargs: Any) -> Any:  # noqa: ANN401 - the policy's own
        policy = real(*args, **kwargs)
        policy.settings["permissions"] = permissions
        return policy

    monkeypatch.setattr(module, "sandbox_policy", with_permissions)


def test_the_web_deny_survives_a_layer_whose_deny_is_a_tuple(
    outside_tmp: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    # This module's own deny lists are tuples: a layer handing one on adds to the deny as a
    # list does, and is never the whole deny once written.
    _layered(monkeypatch, {"deny": ("Bash(curl:*)",)})
    done = install(_request(outside_tmp, "/var/tmp/pgs/0123456789"), REGISTRY)
    permissions = json.loads(done.settings_path.read_text()).get("permissions", {})
    assert permissions.get("deny") == ["WebFetch", "WebSearch", "Bash(curl:*)"]


@pytest.mark.parametrize(
    "permissions",
    [
        None,
        [],
        "deny",
        ("WebFetch",),
        {"deny": None},
        {"deny": "Bash(curl:*)"},
        {"deny": {"WebFetch": False}},
        {"deny": [["Bash(curl:*)"]]},
        {"deny": [None]},
        {"deny": [7]},
        # Any rule list of the block: one the binary cannot read may cost the file its deny.
        {"allow": "Bash(ls:*)"},
        {"ask": None},
        {"deny": ["Bash(curl:*)"], "additionalDirectories": "/var/tmp/pgs/extra"},
    ],
    ids=repr,
)
def test_a_layer_whose_permissions_are_not_of_the_form_is_refused_and_nothing_is_written(
    outside_tmp: Path, monkeypatch: pytest.MonkeyPatch, permissions: object
) -> None:
    # A block that is no mapping, or a deny that is no list of rule names, is no rule the binary
    # reads as written: the install refuses it, and no settings file is left without the deny.
    _layered(monkeypatch, permissions)
    request = _request(outside_tmp, "/var/tmp/pgs/0123456789")
    with pytest.raises(ValueError, match="permissions"):
        install(request, REGISTRY)
    assert not list(Path(request.target_dir).glob("settings*.json"))


@pytest.mark.parametrize("left", [[], ["WebFetch"], ["WebSearch", "Bash(curl:*)"]], ids=repr)
def test_settings_that_do_not_deny_the_web_tools_are_never_written(
    outside_tmp: Path, monkeypatch: pytest.MonkeyPatch, left: list[str]
) -> None:
    # Whatever a merge did: the settings are held to their profile's deny before they are written.
    from physgate.hooks import settings as module

    def replacing(settings: dict[str, object], more: object) -> None:
        settings["permissions"] = {"deny": left}

    monkeypatch.setattr(module, "_merge", replacing)
    request = _request(outside_tmp, "/var/tmp/pgs/0123456789")
    with pytest.raises(ValueError, match="deny"):
        install(request, REGISTRY)
    assert not list(Path(request.target_dir).glob("settings*.json"))


def test_a_directory_claude_code_would_replace_is_refused(outside_tmp: Path) -> None:
    long = "/var/tmp/pgs/" + "p" * OS_LAYER_TEMP_LIMIT
    with pytest.raises(ValueError, match="shares"):
        install(_request(outside_tmp, long), REGISTRY)
    assert OS_LAYER_TEMP_LIMIT == 32


def test_offline_the_sandbox_refuses_every_host_in_every_permission_mode(outside_tmp: Path) -> None:
    request = _request(outside_tmp, "/var/tmp/pgs/0123456789").model_copy(
        update={"os_layer_network": "none"}
    )
    settings = json.loads(install(request, REGISTRY).settings_path.read_text())
    # Local binding stays off: with it, every service listening on the machine's
    # loopback is reachable from the session's shell, which is not "offline".
    assert settings["sandbox"]["network"] == {
        "strictAllowlist": True,
        "allowedDomains": [],
        "allowLocalBinding": False,
    }


def test_each_session_gets_its_own_copy_of_the_offline_block(outside_tmp: Path) -> None:
    from physgate.oslayer import policy

    request = _request(outside_tmp, "/var/tmp/pgs/0123456789").model_copy(
        update={"os_layer_network": "none"}
    )
    before = dict(policy.OFFLINE)
    done = policy.sandbox_policy(
        build_config(request, installation()),
        home=str(outside_tmp / "home"),
        temp_dir="/var/tmp/pgs/0123456789",
        network="none",
    )
    done.settings["sandbox"]["network"]["allowedDomains"].append("example.invalid")
    done.settings["sandbox"]["network"]["probe"] = 1
    assert dict(policy.OFFLINE) == before


def test_open_the_sandbox_names_no_network_block(outside_tmp: Path) -> None:
    done = install(_request(outside_tmp, "/var/tmp/pgs/0123456789"), REGISTRY)
    assert "network" not in json.loads(done.settings_path.read_text())["sandbox"]
