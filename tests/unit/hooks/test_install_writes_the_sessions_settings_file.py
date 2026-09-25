"""The generator writes the session's settings and configuration outside the worktree.

Nothing it writes may be changeable from inside the session: a settings file in
the worktree was measured to be switchable off with one write.
"""

from __future__ import annotations

import json
import os
import shlex
import subprocess
from pathlib import Path
from typing import Any

import pytest

from physgate.hooks.config import digest, load_config
from physgate.hooks.runtime import ALLOW, Decision, HookSpec
from physgate.hooks.settings import (
    PROFILE_TOOLS,
    InstallRequest,
    build_config,
    current_installation,
    install,
)
from physgate.hooks.views import ConfigView, InputView


def _allow(_: InputView, __: ConfigView) -> Decision:
    return ALLOW


REGISTRY = {
    "alpha": HookSpec("alpha", {"PreToolUse": _allow, "SessionStart": _allow}),
    "beta": HookSpec("beta", {"PreToolUse": _allow, "PostToolUseFailure": _allow}),
}


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


def test_the_settings_name_every_hook_for_every_event_it_handles(tmp_path: Path) -> None:
    done = install(_request(tmp_path), REGISTRY)
    settings = json.loads(done.settings_path.read_text())
    assert settings["disableAllHooks"] is False
    wired = {
        event: shlex.split(groups[0]["hooks"][0]["command"])
        for event, groups in settings["hooks"].items()
    }
    assert set(wired) == {"PreToolUse", "SessionStart", "PostToolUseFailure"}
    assert wired["PreToolUse"][wired["PreToolUse"].index("--hooks") + 1] == "alpha,beta"
    assert wired["SessionStart"][wired["SessionStart"].index("--hooks") + 1] == "alpha"
    assert settings["hooks"]["PreToolUse"][0]["matcher"] == "*"
    assert "matcher" not in settings["hooks"]["SessionStart"][0]


def test_each_command_is_trampolined_isolated_and_carries_the_configs_digest(
    tmp_path: Path,
) -> None:
    done = install(_request(tmp_path), REGISTRY)
    settings = json.loads(done.settings_path.read_text())
    installation = current_installation()
    for groups in settings["hooks"].values():
        hook = groups[0]["hooks"][0]
        argv = shlex.split(hook["command"])
        assert argv[:4] == [
            "/bin/sh",
            str(Path(installation.package_dir) / "hooks" / "trampoline.sh"),
            "5",
            installation.interpreter,
        ]
        assert argv[4:7] == ["-I", "-m", "physgate.hooks"]
        assert argv[-4:] == [
            "--config",
            str(done.config_path),
            "--config-sha256",
            digest(done.config_path.read_bytes()),
        ]
        assert hook["timeout"] == 30
    config = load_config(str(done.config_path), digest(done.config_path.read_bytes()))
    assert config.watchdog_seconds + 10 <= config.hook_timeout_seconds


def test_a_second_run_writes_the_same_bytes(tmp_path: Path) -> None:
    first = install(_request(tmp_path), REGISTRY)
    before = (first.settings_path.read_bytes(), first.config_path.read_bytes())
    second = install(_request(tmp_path), REGISTRY)
    assert (second.settings_path.read_bytes(), second.config_path.read_bytes()) == before


def test_the_order_a_request_lists_its_paths_in_does_not_change_the_bytes(tmp_path: Path) -> None:
    # The spawner builds its lists from whatever it read them from; a session is
    # the same session whichever order they arrive in, and its digest must be too.
    paths = {
        name: tuple(str(tmp_path / f"{name}-{n}") for n in range(3))
        for name in ("extra_protected", "held_out", "required_reading", "always_loaded")
    }
    outputs = []
    for reverse in (False, True):
        listed = {name: tuple(reversed(v)) if reverse else v for name, v in paths.items()}
        done = install(_request(tmp_path, **listed), REGISTRY)
        outputs.append((done.settings_path.read_bytes(), done.config_path.read_bytes()))
    assert outputs[0] == outputs[1]


def test_the_session_is_spawned_with_no_worktree_settings_and_this_file_by_flag(
    tmp_path: Path,
) -> None:
    done = install(_request(tmp_path), REGISTRY)
    assert done.spawn_args == ("--setting-sources", "", "--settings", str(done.settings_path))
    assert done.spawn_env == {"CLAUDE_CONFIG_DIR": str(tmp_path / "claude-config")}
    assert not (tmp_path / "worktree" / ".claude").exists()


@pytest.mark.parametrize("field", ["target_dir", "state_dir", "claude_config_dir"], ids=lambda f: f)
def test_a_session_file_inside_the_worktree_is_refused(tmp_path: Path, field: str) -> None:
    request = _request(tmp_path, **{field: str(tmp_path / "worktree" / "inside")})
    with pytest.raises(ValueError, match="inside the worktree"):
        build_config(request, current_installation())


def test_a_hook_installation_inside_the_worktree_is_refused(tmp_path: Path) -> None:
    here = current_installation()
    inside = here.model_copy(update={"package_dir": str(tmp_path / "worktree" / "src")})
    with pytest.raises(ValueError, match="the hook package"):
        build_config(_request(tmp_path), inside)


def test_everything_that_decides_a_refusal_is_a_protected_path(tmp_path: Path) -> None:
    config = build_config(_request(tmp_path), current_installation())
    installation = current_installation()
    must = {
        installation.package_dir,
        installation.environment_root,
        installation.base_prefix,
        str(tmp_path / "session"),
        str(tmp_path / "state"),
        str(tmp_path / "claude-config"),
        str(tmp_path / "store"),
        str(tmp_path / "home" / ".claude" / "settings.json"),
        str(tmp_path / "home" / ".claude.json"),
        str(tmp_path / "worktree" / ".claude"),
        str(tmp_path / "worktree" / "src" / "physgate" / "gate"),
        str(tmp_path / "worktree" / "src" / "physgate" / "hooks"),
        str(tmp_path / "worktree" / ".env"),
    }
    assert must <= {root.path for root in config.protected_roots}
    assert all(root.reason for root in config.protected_roots)


@pytest.mark.parametrize("profile", ["role", "reviewer", "orchestrator"])
def test_each_profile_gets_its_closed_tool_list(tmp_path: Path, profile: str) -> None:
    config = build_config(_request(tmp_path, profile=profile), current_installation())
    assert config.tools_allowed == tuple(sorted(PROFILE_TOOLS[profile]))  # type: ignore[index]
    for refused in ("Agent", "Workflow", "CronCreate", "WebFetch", "WebSearch"):
        assert refused not in config.tools_allowed


def test_the_command_line_writes_the_files_and_prints_the_spawn_arguments(tmp_path: Path) -> None:
    (tmp_path / "worktree").mkdir()
    proc = subprocess.run(
        [
            "uv",
            "run",
            "--no-sync",
            "physgate",
            "hooks",
            "install",
            "--profile=role",
            "--role=control",
            f"--worktree={tmp_path / 'worktree'}",
            f"--state-dir={tmp_path / 'state'}",
            f"--target={tmp_path / 'session'}",
            f"--claude-config-dir={tmp_path / 'cfg'}",
            f"--user-home={tmp_path / 'home'}",
            "--ceiling=8000",
        ],
        capture_output=True,
        text=True,
        check=True,
    )
    printed = json.loads(proc.stdout)
    assert printed["spawn_args"][:2] == ["--setting-sources", ""]
    config = json.loads(Path(printed["config"]).read_text())
    assert (config["profile"], config["role"], config["token_ceiling"]) == ("role", "control", 8000)


def test_two_processes_with_different_hash_seeds_write_the_same_bytes(tmp_path: Path) -> None:
    # The spawner regenerates these files in a fresh process at every spawn, and
    # a set's iteration order changes with the hash seed between processes. A
    # same-process rerun cannot see an ordering that depends on it.
    (tmp_path / "worktree").mkdir()
    outputs = []
    for seed in ("1", "2"):
        target = tmp_path / f"session-{seed}"
        subprocess.run(
            [
                "uv",
                "run",
                "--no-sync",
                "physgate",
                "hooks",
                "install",
                "--profile=role",
                "--role=control",
                f"--worktree={tmp_path / 'worktree'}",
                f"--store-root={tmp_path / 'store'}",
                f"--state-dir={tmp_path / 'state'}",
                f"--target={tmp_path / 'session'}",
                f"--claude-config-dir={tmp_path / 'cfg'}",
                f"--user-home={tmp_path / 'home'}",
                f"--protect={tmp_path / 'p1'}",
                f"--protect={tmp_path / 'p2'}",
                "--ceiling=8000",
            ],
            capture_output=True,
            text=True,
            check=True,
            env={**os.environ, "PYTHONHASHSEED": seed},
        )
        target.mkdir()
        for name in ("settings.json", "session-config.json"):
            (target / name).write_bytes((tmp_path / "session" / name).read_bytes())
        outputs.append(
            ((target / "settings.json").read_bytes(), (target / "session-config.json").read_bytes())
        )
    assert outputs[0] == outputs[1]


def test_an_interpreter_installed_inside_the_worktree_is_refused(tmp_path: Path) -> None:
    here = current_installation()
    inside = here.model_copy(update={"base_prefix": str(tmp_path / "worktree" / "python")})
    with pytest.raises(ValueError, match="own installation"):
        build_config(_request(tmp_path), inside)
