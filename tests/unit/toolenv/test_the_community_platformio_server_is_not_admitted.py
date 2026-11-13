"""The community PlatformIO tool server is not admitted, and firmware is built with ``pio run``.

Why, in one sentence: that server writes its own state into the project directory it is asked to
build, and its wrapper lets it only read the session's worktree, so a build through it fails before
it starts (measured on the pinned binary, inside the OS layer). Widening the wrapper to let it
write there would let a project file's own scripts write the module outside the hooks, so it is
left out instead. A firmware session builds with the PlatformIO core of the recorded environment,
by its own ``pio run`` inside the OS layer, which the environment's rows show on both platforms.

So: the register holds no such server, no profile is offered one, a run records none, and a call
to one of its tools is refused by the register's own rule even when a session's list names it.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest

from physgate.hooks import settings, tools
from physgate.hooks.config import HookInput, Profile, SessionConfig
from physgate.hooks.settings import PROFILE_SERVERS, InstallRequest, build_config
from physgate.hooks.settings import current_installation as installation
from physgate.orchestrator.tool_environment import recorded_servers
from physgate.toolenv.register import REGISTER_FILE, load_register

OWN = "pgs-0123456789abcdef"
#: The tools it offered that a build asks for, each as a session's list would name it.
ITS_BUILD_TOOLS = (
    "mcp__platformio__build_project",
    "mcp__platformio__size_report",
    "mcp__platformio__check_project",
    "mcp__platformio__get_project_config",
    "mcp__platformio__system_info",
)


def test_the_register_holds_the_control_and_mujoco_servers_only() -> None:
    assert set(load_register().servers) == {"control", "mujoco"}
    named = json.loads(REGISTER_FILE.read_text(encoding="utf-8"))["servers"]
    assert "platformio" not in named


def test_no_profile_is_offered_it_and_a_run_records_none() -> None:
    for profile, servers in PROFILE_SERVERS.items():
        assert "platformio" not in servers, profile
    recorded = recorded_servers()
    assert dict(recorded.profiles) == {"role": ("control", "mujoco"), "baseline": ("control", "mujoco")}


@pytest.fixture
def root(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    base = tmp_path.resolve()
    (base / "run" / "worktrees" / "s1").mkdir(parents=True)
    (base / "run" / "sessions").mkdir(parents=True)
    (base / "temps" / OWN).mkdir(parents=True)
    monkeypatch.setattr(settings, "session_temps_root", lambda: str(base / "temps"), raising=False)
    return base


def _request(root: Path, profile: str, servers: tuple[str, ...]) -> InstallRequest:
    sdir = root / "run" / "sessions" / "s"
    fields: dict[str, Any] = {
        "profile": profile,
        "role": "firmware" if profile == "role" else None,
        "worktree": str(root / "run" / "worktrees" / "s1"),
        "own_branch": None,
        "store_root": None,
        "state_dir": str(sdir / "state"),
        "target_dir": str(sdir / "session"),
        "claude_config_dir": str(sdir / "config"),
        "user_home": str(sdir / "home"),
        "token_ceiling": 1000,
        "tool_servers": servers,
        "temp_dir": str(root / "temps" / OWN),
        "sessions_root": str(root / "run" / "sessions"),
    }
    return InstallRequest.model_validate(fields)


@pytest.mark.parametrize("profile", ["role", "baseline"])
def test_a_session_that_asks_to_be_offered_it_is_not_installed(root: Path, profile: Profile) -> None:
    with pytest.raises(ValueError, match="tool server 'platformio'"):
        build_config(_request(root, profile, ("platformio",)), installation())
    # Offered every server there is, its list names none of that server's tools.
    every = tuple(sorted(load_register().servers))
    config = build_config(_request(root, profile, every), installation())
    assert not [t for t in config.tools_allowed if t.startswith("mcp__platformio__")]


def test_a_call_to_one_of_its_tools_is_refused_by_the_register_though_the_list_names_it(
    root: Path,
) -> None:
    # A list written by hand that names its tools admits none of them: the register does not.
    config = build_config(_request(root, "role", ()), installation())
    listed = SessionConfig.model_validate(
        {**config.model_dump(), "tools_allowed": (*config.tools_allowed, *ITS_BUILD_TOOLS)}
    )
    project = str(Path(listed.worktree) / "firmware")
    for tool in ITS_BUILD_TOOLS:
        arguments = {} if tool.endswith("system_info") else {"projectDir": project}
        hook_input = HookInput.model_validate(
            {
                "hook_event_name": "PreToolUse",
                "session_id": "0f1e2d3c-4b5a-6978-8796-a5b4c3d2e1f0",
                "cwd": listed.worktree,
                "tool_name": tool,
                "tool_input": arguments,
            }
        )
        decision = tools.pre_tool_use(hook_input, listed)
        assert not decision.allow, tool
        assert "not in the tool-server register" in decision.reason, (tool, decision.reason)
