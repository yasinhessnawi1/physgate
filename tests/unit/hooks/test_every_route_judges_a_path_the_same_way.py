"""A path is judged the same whichever route names it.

A write can be made with a file tool (Write, Edit, NotebookEdit) or with a shell command
(a redirection, ``touch``, ``cp``, ``tee``); a read with the Read tool or a reader (``cat``,
``head``, ``grep``, ``wc``). Each spelling below is put through every route, and every route
must reach the same decision: a root and a sibling sharing its prefix, case, ``//``, ``./``
and ``..``, a trailing slash, a symlink, a second hard link, ``~``, and a relative path from
a working directory that is not absolute. Inert markers only.
"""

from __future__ import annotations

import os
from collections.abc import Callable
from pathlib import Path

import pytest
from hook_helpers import bash, event

from physgate.hooks import paths, shell_paths
from physgate.hooks.config import HookInput, SessionConfig
from physgate.hooks.settings import InstallRequest, build_config, current_installation

ROOT = ".physgate/series"
#: A route: the config, a path as the agent spells it, the call's working directory; allowed?
Route = Callable[[SessionConfig, str, str], bool]


@pytest.fixture
def config(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> SessionConfig:
    base = Path(os.path.realpath(tmp_path))
    worktree = base / "wt"
    (worktree / ROOT).mkdir(parents=True)
    (worktree / ROOT / "earlier.json").write_text("{}\n")
    (worktree / ".physgate" / "series-other").mkdir()
    (worktree / "modules" / "control").mkdir(parents=True)
    (worktree / "README.md").write_text("marker\n")
    (worktree / "into-root").symlink_to(worktree / ROOT)
    os.link(worktree / ROOT / "earlier.json", worktree / "second-name.json")
    held = base / "outside" / "heldout"
    held.mkdir(parents=True)
    (held / "scenario_01.json").write_text('{"marker": "held-out stand-in"}\n')
    (base / "outside" / "heldout-other").mkdir()
    (base / "outside" / "heldout-other" / "scenario_01.json").write_text("{}\n")
    (worktree / "into-held").symlink_to(held)
    monkeypatch.setenv("HOME", str(worktree / ".physgate"))
    request = InstallRequest(
        profile="role",
        role="control",
        worktree=str(worktree),
        own_branch="b",
        store_root=None,
        state_dir=str(base / "state"),
        target_dir=str(base / "target"),
        claude_config_dir=str(base / "config"),
        user_home=str(base / "home"),
        token_ceiling=40960,
        held_out=(str(held),),
        extra_protected_refuse_only=(str(worktree / ROOT),),
    )
    return build_config(request, current_installation())


def _tool(config: SessionConfig, tool: str, path: str, cwd: str) -> bool:
    key = "notebook_path" if tool == "NotebookEdit" else "file_path"
    hook_input = HookInput.model_validate(
        event(tool_name=tool, cwd=cwd, tool_input={key: path, "content": "{}"})
    )
    return paths.pre_tool_use(hook_input, config).allow


def _shell(config: SessionConfig, command: str, cwd: str) -> bool:
    hook_input = HookInput.model_validate(bash(command, cwd=cwd))
    return shell_paths.pre_tool_use(hook_input, config).allow


WRITES: dict[str, Route] = {
    "Write": lambda c, p, cwd: _tool(c, "Write", p, cwd),
    "Edit": lambda c, p, cwd: _tool(c, "Edit", p, cwd),
    "NotebookEdit": lambda c, p, cwd: _tool(c, "NotebookEdit", p, cwd),
    ">": lambda c, p, cwd: _shell(c, f"echo marker > {p}", cwd),
    "touch": lambda c, p, cwd: _shell(c, f"touch {p}", cwd),
    "cp": lambda c, p, cwd: _shell(c, f"cp README.md {p}", cwd),
    "tee": lambda c, p, cwd: _shell(c, f"tee {p} < README.md", cwd),
}
READS: dict[str, Route] = {
    "Read": lambda c, p, cwd: _tool(c, "Read", p, cwd),
    "cat": lambda c, p, cwd: _shell(c, f"cat {p}", cwd),
    "head": lambda c, p, cwd: _shell(c, f"head -1 {p}", cwd),
    "grep": lambda c, p, cwd: _shell(c, f"grep marker {p}", cwd),
    "wc": lambda c, p, cwd: _shell(c, f"wc -l {p}", cwd),
}


@pytest.mark.parametrize(
    ("spelling", "allowed"),
    [
        (".physgate/series/step.json", False),
        (".physgate/series", False),
        (".physgate/series/", False),
        (".physgate//series/step.json", False),
        ("./.physgate/series/step.json", False),
        ("modules/../.physgate/series/step.json", False),
        ("into-root/step.json", False),
        ("second-name.json", False),
        ("~/series/step.json", False),
        (".physgate/series-other/step.json", True),
        (".physgate/seriesx", True),
        (".physgate/serie/step.json", True),
        ("modules/control/step.json", True),
    ],
)
def test_every_write_route_reaches_the_same_decision(
    config: SessionConfig, spelling: str, allowed: bool
) -> None:
    decisions = {name: route(config, spelling, config.worktree) for name, route in WRITES.items()}
    assert set(decisions.values()) == {allowed}, decisions


def test_a_case_variant_is_judged_the_same_by_every_write_route(config: SessionConfig) -> None:
    spelling = ".PHYSGATE/SERIES/step.json"
    decisions = {name: route(config, spelling, config.worktree) for name, route in WRITES.items()}
    assert len(set(decisions.values())) == 1, decisions


@pytest.mark.parametrize(
    ("spelling", "allowed"),
    [
        ("{o}/heldout/scenario_01.json", False),
        ("{o}//heldout/./scenario_01.json", False),
        ("{o}/heldout-other/../heldout/scenario_01.json", False),
        ("into-held/scenario_01.json", False),
        ("{o}/heldout-other/scenario_01.json", True),
    ],
)
def test_every_read_route_reaches_the_same_decision(
    config: SessionConfig, spelling: str, allowed: bool
) -> None:
    outside = os.path.join(os.path.dirname(config.worktree), "outside")
    path = spelling.format(o=outside)
    decisions = {name: route(config, path, config.worktree) for name, route in READS.items()}
    assert set(decisions.values()) == {allowed}, decisions


@pytest.mark.parametrize("cwd", ["relative/somewhere", "", "wt"])
def test_a_relative_path_from_a_working_directory_that_is_not_absolute_is_refused_by_every_route(
    config: SessionConfig, cwd: str
) -> None:
    decisions = {
        name: route(config, "modules/control/f.json", cwd) for name, route in WRITES.items()
    }
    assert set(decisions.values()) == {False}, decisions
