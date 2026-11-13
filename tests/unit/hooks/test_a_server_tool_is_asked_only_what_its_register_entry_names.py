"""A tool server's admitted tool is asked only what its register entry names.

An argument the entry does not name, or of another kind, refuses the call. An argument the entry
marks as a path is judged as a file tool's read or write of that path would be, and must lie
inside the session's worktree however it is spelt: relative, through ``..``, through a link, or
by a case variant of the worktree's own spelling. A tool of the register's denied set is refused
by name, as is any tool the register does not hold.
"""

from __future__ import annotations

import os
from pathlib import Path
from typing import Any

import pytest
from hook_helpers import event, volume_is_case_insensitive, write_config

from physgate.hooks import tools
from physgate.hooks.config import HookInput, SessionConfig
from physgate.hooks.registry import REGISTRY
from physgate.hooks.runtime import dispatch

BUILD = "mcp__platformio__build_project"
CONFIG = "mcp__platformio__get_project_config"
LOAD = "mcp__mujoco__load_model"
STEP = "mcp__mujoco__step"
MARGINS = "mcp__control__margins"
ADMITTED = [
    BUILD,
    CONFIG,
    LOAD,
    STEP,
    MARGINS,
    "mcp__platformio__system_info",
    "mcp__platformio__check_project",
    "mcp__mujoco__state",
]
BASE = ["Bash", "Edit", "NotebookEdit", "Read", "Write"]


@pytest.fixture
def config(tmp_path: Path) -> SessionConfig:
    root = tmp_path.resolve()
    worktree = root / "worktree"
    (worktree / "firmware").mkdir(parents=True)
    (worktree / "held").mkdir()
    (root / "outside").mkdir()
    return write_config(
        root,
        tools_allowed=sorted([*BASE, *ADMITTED]),
        held_out=[str(worktree / "held")],
    )[2]


def _call(config: SessionConfig, tool: str, arguments: Any, cwd: str | None = None) -> str:  # noqa: ANN401
    hook_input = HookInput.model_validate(
        event(tool_name=tool, cwd=cwd or config.worktree, tool_input=arguments)
    )
    decision = tools.pre_tool_use(hook_input, config)
    return "allow" if decision.allow else decision.reason


def _firmware(config: SessionConfig) -> str:
    return str(Path(config.worktree) / "firmware")


# ---- what an admitted tool may be asked ------------------------------------------------------


def test_an_admitted_tool_given_only_named_arguments_inside_the_worktree_is_allowed(
    config: SessionConfig,
) -> None:
    assert _call(config, BUILD, {"projectDir": _firmware(config), "environment": "a_star"}) == (
        "allow"
    )
    assert _call(config, BUILD, {"projectDir": _firmware(config), "jobs": 2, "verbose": True}) == (
        "allow"
    )
    assert _call(config, CONFIG, {"projectDir": _firmware(config)}) == "allow"
    assert _call(config, "mcp__platformio__system_info", {}) == "allow"
    assert _call(config, STEP, {"steps": 10, "controls": [0.1, -0.2]}) == "allow"
    assert _call(config, LOAD, {"xml": "<mujoco/>"}) == "allow"
    system = {"transfer_function": {"num": [1], "den": [1, 2, 1]}}
    assert _call(config, MARGINS, {"system": system}) == "allow"


@pytest.mark.parametrize(
    ("tool", "arguments", "named"),
    [
        (BUILD, {"projectDir": "{fw}", "approvalId": "a1"}, "approvalId"),
        (BUILD, {"projectDir": "{fw}", "background": True}, "background"),
        (BUILD, {"projectDir": "{fw}", "sessionId": "s"}, "sessionId"),
        ("mcp__platformio__check_project", {"projectDir": "{fw}", "tool": "x"}, "tool"),
        (STEP, {"steps": 1, "viewer": True}, "viewer"),
        ("mcp__mujoco__state", {"path": "x"}, "path"),
    ],
)
def test_an_argument_the_entry_does_not_name_refuses_the_call(
    config: SessionConfig, tool: str, arguments: dict[str, Any], named: str
) -> None:
    given = {k: (_firmware(config) if v == "{fw}" else v) for k, v in arguments.items()}
    reason = _call(config, tool, given)
    assert reason != "allow"
    assert named in reason and "does not name" in reason, reason


@pytest.mark.parametrize(
    ("tool", "arguments", "named"),
    [
        (BUILD, {"projectDir": "{fw}", "jobs": "4"}, "jobs"),
        (BUILD, {"projectDir": "{fw}", "jobs": True}, "jobs"),
        (BUILD, {"projectDir": "{fw}", "jobs": 1.5}, "jobs"),
        (BUILD, {"projectDir": "{fw}", "verbose": 1}, "verbose"),
        (BUILD, {"projectDir": "{fw}", "environment": ["a"]}, "environment"),
        (BUILD, {"projectDir": 7}, "projectDir"),
        (STEP, {"steps": 1, "controls": {"a": 1}}, "controls"),
        (MARGINS, {"system": "1/(s+1)"}, "system"),
    ],
)
def test_an_argument_of_another_kind_refuses_the_call(
    config: SessionConfig, tool: str, arguments: dict[str, Any], named: str
) -> None:
    given = {k: (_firmware(config) if v == "{fw}" else v) for k, v in arguments.items()}
    reason = _call(config, tool, given)
    assert reason != "allow"
    assert named in reason and "kind" in reason, reason


@pytest.mark.parametrize("arguments", [["projectDir"], "projectDir", None, 3])
def test_arguments_that_are_not_an_object_refuse_the_call(
    config: SessionConfig,
    arguments: Any,  # noqa: ANN401
) -> None:
    hook_input = HookInput.model_validate(
        event(tool_name=BUILD, cwd=config.worktree, tool_input={"projectDir": _firmware(config)})
    )
    object.__setattr__(hook_input, "tool_input", arguments)
    decision = tools.pre_tool_use(hook_input, config)
    assert not decision.allow
    assert "object" in decision.reason, decision.reason


# ---- a path argument -------------------------------------------------------------------------


def _outside_spellings(config: SessionConfig) -> list[str]:
    worktree = Path(config.worktree)
    return [
        str(worktree.parent / "outside"),
        "/etc",
        f"{worktree}/../outside",
        f"{worktree}/firmware/../../outside",
        f"{worktree}/..",
        "/",
        # A sibling whose name begins with the worktree's.
        f"{worktree}-other",
        f"{worktree}2/firmware",
    ]


def test_a_path_outside_the_worktree_is_refused_however_it_is_spelt(config: SessionConfig) -> None:
    for spelling in _outside_spellings(config):
        reason = _call(config, BUILD, {"projectDir": spelling})
        assert "outside the session's worktree" in reason, (spelling, reason)
        reason = _call(config, LOAD, {"path": spelling})
        assert "outside the session's worktree" in reason, (spelling, reason)


def test_a_path_through_a_link_out_of_the_worktree_is_refused(config: SessionConfig) -> None:
    worktree = Path(config.worktree)
    (worktree / "out").symlink_to(worktree.parent / "outside")
    (worktree / "firmware" / "up").symlink_to("..")
    for spelling in (
        str(worktree / "out"),
        str(worktree / "out" / "model.xml"),
        f"{worktree}/firmware/up/../outside",
        "out/model.xml",
    ):
        reason = _call(config, LOAD, {"path": spelling})
        assert "outside the session's worktree" in reason, (spelling, reason)
    reason = _call(config, BUILD, {"projectDir": str(worktree / "out")})
    assert "outside the session's worktree" in reason, reason


def test_a_case_variant_of_the_worktree_s_spelling_is_outside_it(config: SessionConfig) -> None:
    worktree = Path(config.worktree)
    variant = str(worktree.parent / "WORKTREE" / "firmware")
    reason = _call(config, BUILD, {"projectDir": variant})
    assert "outside the session's worktree" in reason, reason
    if volume_is_case_insensitive(worktree):
        # The variant names the same directory here, and is refused all the same.
        assert os.path.samefile(variant, worktree / "firmware")


def test_a_relative_path_is_read_from_the_worktree_where_the_server_resolves_it_so(
    config: SessionConfig,
) -> None:
    # The MuJoCo server is started on the worktree and reads a relative path from it.
    assert _call(config, LOAD, {"path": "firmware/model.xml"}, cwd="/") == "allow"
    reason = _call(config, LOAD, {"path": "../outside/model.xml"})
    assert "outside the session's worktree" in reason, reason
    reason = _call(config, LOAD, {"path": "firmware/../../outside/model.xml"})
    assert "outside the session's worktree" in reason, reason


def test_a_relative_path_is_refused_where_the_server_decides_what_it_names(
    config: SessionConfig,
) -> None:
    for spelling in ("firmware", ".", "./firmware", "~/firmware"):
        reason = _call(config, BUILD, {"projectDir": spelling})
        assert "relative" in reason, (spelling, reason)


@pytest.mark.parametrize("spelling", ["", "firmware\x00", "\n"])
def test_a_path_that_names_nothing_usable_is_refused(config: SessionConfig, spelling: str) -> None:
    assert _call(config, BUILD, {"projectDir": spelling}) != "allow"


def test_a_path_is_judged_as_a_file_tool_s_read_or_write_of_it(config: SessionConfig) -> None:
    worktree = Path(config.worktree)
    gate = worktree / "src" / "physgate" / "gate"
    gate.mkdir(parents=True)
    # The gate is protected from writes, not reads: a build there would write, a read would not.
    reason = _call(config, BUILD, {"projectDir": str(gate)})
    assert "it holds the gate" in reason, reason
    assert _call(config, CONFIG, {"projectDir": str(gate)}) == "allow"
    reason = _call(config, BUILD, {"projectDir": str(worktree / "SRC" / "physgate" / "GATE")})
    assert reason != "allow", reason
    # The held-out tier: neither read nor written by a role session, by any spelling.
    for spelling in (str(worktree / "held"), str(worktree / "held" / "m.xml"), "held/m.xml"):
        reason = _call(config, LOAD, {"path": spelling})
        assert "held-out" in reason.casefold() or "held out" in reason.casefold(), reason
    reason = _call(config, CONFIG, {"projectDir": str(worktree / "held")})
    assert reason != "allow", reason


def test_a_path_through_a_link_to_a_protected_place_inside_the_worktree_is_refused(
    config: SessionConfig,
) -> None:
    worktree = Path(config.worktree)
    (worktree / "firmware" / "h").symlink_to(worktree / "held")
    reason = _call(config, LOAD, {"path": str(worktree / "firmware" / "h" / "m.xml")})
    assert reason != "allow", reason


# ---- the closed list -------------------------------------------------------------------------


@pytest.mark.parametrize(
    "tool",
    [
        "mcp__platformio__upload_firmware",
        "mcp__platformio__serial_session_start",
        "mcp__platformio__debug_cmd",
        "mcp__platformio__pkg_install",
        "mcp__platformio__get_dashboard_url",
        "mcp__platformio__list_boards",
        "mcp__platformio__no_such_tool",
        "mcp__nosuchserver__build_project",
    ],
)
def test_a_tool_not_admitted_is_refused_by_name(config: SessionConfig, tool: str) -> None:
    reason = _call(config, tool, {"projectDir": _firmware(config)})
    assert reason != "allow"
    assert tool in reason, reason


def test_an_admitted_name_given_to_the_session_without_a_register_entry_is_refused(
    tmp_path: Path,
) -> None:
    # A closed list naming a server tool the register does not hold admits nothing by it.
    config = write_config(tmp_path.resolve(), tools_allowed=[*BASE, "mcp__other__run"])[2]
    reason = _call(config, "mcp__other__run", {})
    assert reason != "allow"
    assert "register" in reason, reason


def test_the_rule_holds_on_the_hooks_own_path(config: SessionConfig) -> None:
    # Through the dispatcher on the hot path's own views, not the pydantic models alone.
    hook_input = HookInput.model_validate(
        event(tool_name=BUILD, cwd=config.worktree, tool_input={"projectDir": "/etc"})
    )
    decision = dispatch([REGISTRY["tools"]], hook_input, config)
    assert not decision.allow
    assert "outside the session's worktree" in decision.reason, decision.reason
