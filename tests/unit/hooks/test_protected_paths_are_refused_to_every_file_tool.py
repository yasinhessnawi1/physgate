"""No file tool writes a protected path, however the path is spelt.

The protected set comes from the settings generator, so these tests exercise
the rule data a real session gets, not a list written for the test.
"""

from __future__ import annotations

import os
import sys
from pathlib import Path

import pytest
from hook_helpers import event

from physgate.hooks import paths, tools
from physgate.hooks.config import SessionConfig
from physgate.hooks.runtime import HookInput
from physgate.hooks.settings import GATE_REASON, STORE_REASON, InstallRequest, build_config
from physgate.hooks.settings import current_installation as installation

FILES = {
    "worktree/src/physgate/gate/check.py": "CHECK = True\n",
    "worktree/src/physgate/electrical/driver.py": "x = 1\n",
    "worktree/README.md": "readme\n",
    "worktree/experiments/R-OP-01/RESULT.md": "result\n",
    "worktree/experiments/R-OP-01/CRITERIA.md": "criteria\n",
    "worktree/experiments/R-OP-01/src/store.py": "code\n",
    "worktree/experiments/R-TM-01/R-TM-01_README.md": "readme\n",
    "worktree/experiments/R-TM-01/complete/run02/RESULT.md": "nested result\n",
    "worktree/experiments/R-NEW-01/CRITERIA.md": "criteria, no result yet\n",
    "worktree/experiments/R-NEW-01/notes.md": "notes\n",
    "store/journal.jsonl": "",
    "store/nodes/electrical.motor.json": "{}\n",
    "heldout/scenario_01.json": "{}\n",
}


@pytest.fixture
def layout(tmp_path: Path) -> Path:
    for rel, content in FILES.items():
        path = tmp_path / rel
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(content)
    return tmp_path


def _config(root: Path, profile: str = "role") -> SessionConfig:
    return build_config(
        InstallRequest(
            profile=profile,  # type: ignore[arg-type]
            role="electrical" if profile == "role" else None,
            worktree=str(root / "worktree"),
            own_branch="subtask/electrical-1",
            store_root=str(root / "store"),
            state_dir=str(root / "outside" / "state"),
            target_dir=str(root / "outside" / "session"),
            claude_config_dir=str(root / "outside" / "cfg"),
            user_home=str(root / "outside" / "home"),
            token_ceiling=1000,
            held_out=(str(root / "heldout"),),
        ),
        installation(),
    )


def _call(root: Path, tool: str, target: str, profile: str = "role") -> str:
    key = "notebook_path" if tool == "NotebookEdit" else "file_path"
    hook_input = HookInput.model_validate(
        event(tool_name=tool, cwd=str(root / "worktree"), tool_input={key: target})
    )
    decision = paths.pre_tool_use(hook_input, _config(root, profile))
    return "allow" if decision.allow else decision.reason


REFUSED = [
    ("src/physgate/gate/check.py", GATE_REASON),
    ("src/physgate/gate/new_check.py", GATE_REASON),
    ("src/physgate/gate", GATE_REASON),
    ("src/../src/physgate/./gate/x.py", GATE_REASON),
    ("src/physgate/GATE/CHECK.PY", GATE_REASON),
    ("@/store/journal.jsonl", STORE_REASON),
    ("@/store/nodes/electrical.motor.json", STORE_REASON),
    ("@/store/nodes/new.node.json", STORE_REASON),
    ("experiments/R-OP-01/RESULT.md", paths.FROZEN_RESULT),
    ("experiments/R-OP-01/src/store.py", paths.FROZEN_RESULT),
    ("experiments/R-OP-01/src/new_file.py", paths.FROZEN_RESULT),
    ("experiments/R-TM-01/R-TM-01_README.md", paths.FROZEN_RESULT),
    ("experiments/r-tm-01/r-tm-01_readme.md", paths.FROZEN_RESULT),
    ("experiments/R-NEW-01/CRITERIA.md", paths.FROZEN_CRITERIA),
    ("experiments/R-NEW-01/deeper/CRITERIA.md", paths.FROZEN_CRITERIA),
    ("@/heldout/scenario_01.json", paths.HELD_OUT_REASON),
    ("@/heldout/new.json", paths.HELD_OUT_REASON),
    (".claude/settings.local.json", "a settings write can switch the hooks off"),
    (".env", "secrets"),
    ("src/physgate/hooks/runtime.py", "hook layer's source"),
    ("@/outside/session/session-config.json", "settings and configuration"),
    ("@/outside/state/hooks.log.jsonl", "own records"),
    ("@/outside/home/.claude/settings.json", "later sessions read"),
]
ALLOWED = [
    "src/physgate/electrical/driver.py",
    "src/physgate/electrical/new.py",
    "src/physgate/gateway.py",
    "README.md",
    "experiments/R-NEW-01/notes.md",
    "experiments/R-NEW-02/plan.md",
    "@/elsewhere/scratch.txt",
]


def _resolve(root: Path, target: str) -> str:
    return str(root) + target[1:] if target.startswith("@") else target


@pytest.mark.parametrize("tool", ["Write", "Edit", "NotebookEdit"])
@pytest.mark.parametrize(("target", "reason"), REFUSED, ids=[t for t, _ in REFUSED])
def test_a_protected_path_is_refused(layout: Path, tool: str, target: str, reason: str) -> None:
    told = _call(layout, tool, _resolve(layout, target))
    assert told != "allow"
    assert reason in told
    assert tool in told


@pytest.mark.parametrize("tool", ["Write", "Edit", "NotebookEdit"])
@pytest.mark.parametrize("target", ALLOWED)
def test_an_ordinary_path_is_allowed(layout: Path, tool: str, target: str) -> None:
    assert _call(layout, tool, _resolve(layout, target)) == "allow"


def test_the_gate_is_refused_to_every_profile(layout: Path) -> None:
    for profile in ("role", "reviewer", "orchestrator"):
        assert GATE_REASON in _call(layout, "Write", "src/physgate/gate/x.py", profile)


def test_a_symlinked_directory_into_the_gate_is_refused(layout: Path) -> None:
    (layout / "worktree" / "innocent").symlink_to(layout / "worktree" / "src" / "physgate" / "gate")
    assert GATE_REASON in _call(layout, "Write", "innocent/x.py")


def test_a_symlinked_file_onto_a_gate_file_is_refused(layout: Path) -> None:
    link = layout / "worktree" / "notes.py"
    link.symlink_to(layout / "worktree" / "src" / "physgate" / "gate" / "check.py")
    assert GATE_REASON in _call(layout, "Edit", "notes.py")


def test_a_symlinked_directory_into_the_store_is_refused(layout: Path) -> None:
    (layout / "worktree" / "graph").symlink_to(layout / "store")
    assert STORE_REASON in _call(layout, "Write", "graph/journal.jsonl")


def test_a_hard_link_to_a_protected_file_is_refused(layout: Path) -> None:
    os.link(
        layout / "worktree" / "src" / "physgate" / "gate" / "check.py",
        layout / "worktree" / "src" / "physgate" / "electrical" / "twin.py",
    )
    assert paths.HARD_LINKED in _call(layout, "Write", "src/physgate/electrical/twin.py")


def test_the_held_out_tier_cannot_be_read_by_a_role_or_a_reviewer(layout: Path) -> None:
    target = str(layout / "heldout" / "scenario_01.json")
    for profile in ("role", "reviewer"):
        assert paths.HELD_OUT_REASON in _call(layout, "Read", target, profile)
    assert _call(layout, "Read", target, "orchestrator") == "allow"


def test_reading_any_other_protected_path_is_allowed(layout: Path) -> None:
    for target in ("src/physgate/gate/check.py", "experiments/R-OP-01/RESULT.md"):
        assert _call(layout, "Read", target) == "allow"


def test_a_file_tool_without_a_path_is_refused(layout: Path) -> None:
    hook_input = HookInput.model_validate(event(tool_name="Write", tool_input={"content": "x"}))
    assert not paths.pre_tool_use(hook_input, _config(layout)).allow


def test_a_protected_root_that_contains_the_worktree_is_refused_at_install(layout: Path) -> None:
    with pytest.raises(ValueError, match="contains the worktree"):
        build_config(
            InstallRequest(
                profile="role",
                role="electrical",
                worktree=str(layout / "worktree"),
                own_branch=None,
                store_root=str(layout),
                state_dir=str(layout / "outside" / "state"),
                target_dir=str(layout / "outside" / "session"),
                claude_config_dir=str(layout / "outside" / "cfg"),
                user_home=str(layout / "outside" / "home"),
                token_ceiling=1000,
            ),
            installation(),
        )


@pytest.mark.parametrize(
    ("profile", "tool", "allowed"),
    [
        ("role", "Bash", True),
        ("role", "Write", True),
        ("role", "TaskCreate", True),
        ("role", "Agent", False),
        ("role", "Workflow", False),
        ("role", "CronCreate", False),
        ("role", "WebFetch", False),
        ("role", "WebSearch", False),
        ("role", "EnterWorktree", False),
        ("role", "mcp__server__write_file", False),
        ("role", "SomeToolFromTheFuture", False),
        ("reviewer", "Read", True),
        ("reviewer", "Write", False),
        ("reviewer", "Bash", False),
        ("orchestrator", "Bash", True),
    ],
)
def test_each_profile_runs_on_its_closed_tool_list(
    layout: Path, profile: str, tool: str, allowed: bool
) -> None:
    decision = tools.pre_tool_use(
        HookInput.model_validate(event(tool_name=tool, tool_input={})), _config(layout, profile)
    )
    assert decision.allow is allowed
    if not allowed:
        assert f"The {tool} tool is not available to a {profile} session" in decision.reason


@pytest.mark.skipif(
    sys.platform != "darwin", reason="the case trick needs a case-insensitive volume"
)
def test_on_this_volume_the_case_variant_really_reaches_the_gate(layout: Path) -> None:
    variant = layout / "worktree" / "src" / "physgate" / "GATE" / "CHECK.PY"
    assert variant.read_text() == "CHECK = True\n"
