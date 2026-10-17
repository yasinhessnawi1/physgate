"""A tripwire on the held-out tier and the answer keys: a second name, a change, or doubt halts.

A hard link is the same file under another name, and the OS layer judges a read
by the name it is given. The OS layer's read denial and the hooks keep these
files unread; this tripwire stands behind them and claims only what it checks:
at the session's start and end (and, in the orchestrator, before the commit),
every file has one name and, at the end, is still the file it was by inode.
Anything it cannot check is a problem, never a pass. A name made and removed
between two checks is its residual. The harness never makes a second name.
"""

from __future__ import annotations

import ast
import os
from pathlib import Path

import pytest
from hook_helpers import bash

from physgate.hooks import sentinel
from physgate.hooks.config import HookInput, SessionConfig
from physgate.hooks.settings import InstallRequest, build_config
from physgate.hooks.settings import current_installation as installation

MARKER = "STANDIN-HELDOUT-MARKER\n"
SRC = Path(__file__).resolve().parents[3] / "src" / "physgate"


@pytest.fixture
def root(tmp_path: Path) -> Path:
    for rel in ("heldout/scenario.json", "worktree/corpora/answers.json", "worktree/README.md"):
        path = tmp_path / rel
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(MARKER)
    return tmp_path


def _config(root: Path) -> SessionConfig:
    return build_config(
        InstallRequest(
            profile="role",
            role="electrical",
            worktree=str(root / "worktree"),
            own_branch=None,
            store_root=None,
            state_dir=str(root / "outside" / "state"),
            target_dir=str(root / "outside" / "session"),
            claude_config_dir=str(root / "outside" / "cfg"),
            user_home=str(root / "outside" / "home"),
            token_ceiling=1000,
            held_out=(str(root / "heldout"),),
        ),
        installation(),
    )


def _check(root: Path, name: str = "PostToolUse") -> str:
    hook_input = HookInput.model_validate(
        bash("x", cwd=str(root / "worktree")) | {"hook_event_name": name}
    )
    decision = sentinel.check(hook_input, _config(root))
    return "allow" if decision.allow else decision.reason


def test_files_with_one_name_each_pass(root: Path) -> None:
    assert _check(root, "SessionStart") == "allow"
    assert _check(root) == "allow"


def test_a_held_out_file_with_a_second_name_at_the_start_refuses_the_session(root: Path) -> None:
    os.link(root / "heldout" / "scenario.json", root / "outside-name.json")
    reason = _check(root, "SessionStart")
    assert "more than one name" in reason and "scenario.json" in reason
    assert _check(root) == reason  # and every later call


def test_a_second_name_made_during_the_session_halts_it_at_the_end(root: Path) -> None:
    assert _check(root, "SessionStart") == "allow"
    os.link(root / "worktree" / "corpora" / "answers.json", root / "worktree" / "copy.json")
    assert _check(root) == "allow", "checked at the start and the end only, by design"
    reason = _check(root, "SessionEnd")
    assert "more than one name" in reason and "answers.json" in reason
    os.unlink(root / "worktree" / "copy.json")
    assert _check(root) == reason, "a halt holds once the link is gone"


def test_a_file_swapped_for_another_halts_at_the_end(root: Path) -> None:
    assert _check(root, "SessionStart") == "allow"
    held = root / "heldout" / "scenario.json"
    replacement = root / "heldout" / "swap.tmp"
    replacement.write_text(MARKER)  # the same bytes, another file
    os.replace(replacement, held)
    reason = _check(root, "SessionEnd")
    assert "scenario.json: not the file it was" in reason


def test_what_cannot_be_checked_halts_rather_than_passes(root: Path) -> None:
    locked = root / "heldout" / "locked"
    locked.mkdir()
    (locked / "inner.json").write_text(MARKER)
    locked.chmod(0)
    try:
        reason = _check(root, "SessionStart")
    finally:
        locked.chmod(0o755)
    assert "cannot be" in reason and "locked" in reason


def test_a_link_inside_the_tier_is_not_followed_and_is_flagged(root: Path) -> None:
    outside = root / "outside-marker"
    outside.write_text(MARKER)
    (root / "heldout" / "pointer").symlink_to(outside)
    reason = _check(root, "SessionStart")
    assert "pointer: not a regular file" in reason


def test_the_harness_never_links_a_file() -> None:
    # os.link and os.linkat make a second name; so does Path.hardlink_to.
    found = []
    for path in SRC.rglob("*.py"):
        for node in ast.walk(ast.parse(path.read_text())):
            if not (isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute)):
                continue
            func = node.func
            on_os = isinstance(func.value, ast.Name) and func.value.id == "os"
            if (on_os and func.attr in {"link", "linkat"}) or func.attr == "hardlink_to":
                found.append(f"{path.relative_to(SRC)}:{node.lineno} {func.attr}")
    assert found == [], found


def test_the_tripwire_never_costs_a_put_back(root: Path) -> None:
    # Parity with the sentinel without the tripwire: a protected file changed in the same
    # session as a second name appears is still put back, and the session still halts.
    gate = root / "worktree" / "src" / "physgate" / "gate" / "check.py"
    gate.parent.mkdir(parents=True)
    gate.write_text("CHECK = True\n")
    assert _check(root, "SessionStart") == "allow"
    gate.write_text("CHECK = False\n")
    os.link(root / "heldout" / "scenario.json", root / "outside-name.json")
    reason = _check(root, "SessionEnd")
    assert gate.read_text() == "CHECK = True\n", "the changed gate file was not put back"
    assert "more than one name" in reason
    assert _check(root) == reason
