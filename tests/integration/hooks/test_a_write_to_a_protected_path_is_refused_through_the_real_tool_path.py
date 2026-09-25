"""Through the real binary: a file tool aimed at a protected path is refused and nothing moves.

Every case asserts on the hook layer's decision log, on what the agent was told,
and on the bytes of the target, before and after.

An existing file is read before it is written, in every case. Claude Code's own
Write and Edit refuse a file the session has not read, before any hook runs, and
a test that stopped there would see the bytes unchanged and prove nothing about
the hook. The first version of this file did exactly that for three cases, and
only the assertion on the decision log caught it.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import Any

import pytest
from fake_messages_api import Script, text, tool
from hook_session import SessionRun, run_session

from physgate.hooks import paths
from physgate.hooks.settings import GATE_REASON, HELD_OUT_REASON, STORE_REASON

pytestmark = pytest.mark.integration

WORKTREE_FILES = {
    "README.md": "a worktree\n",
    "src/physgate/gate/check.py": "CHECK = True\n",
    "src/physgate/electrical/driver.py": "x = 1\n",
    "experiments/R-OP-01/CRITERIA.md": "frozen criteria\n",
    "experiments/R-OP-01/RESULT.md": "published result\n",
}
OUTSIDE_FILES = {
    "store/journal.jsonl": '{"rev":1}\n',
    "store/nodes/electrical.motor.json": '{"rev":1}\n',
    "heldout/scenario_01.json": '{"secret": "the answer"}\n',
}


def _placed(step: dict[str, Any], root: Path) -> dict[str, Any]:
    """``@W`` is the worktree and ``@O`` the directory outside it, in every string."""
    raw = json.dumps(step)
    raw = raw.replace("@W", str(root / "worktree")).replace("@O", str(root / "outside"))
    placed: dict[str, Any] = json.loads(raw)
    return placed


def _session(root: Path, *steps: dict[str, Any], profile: str = "role") -> SessionRun:
    return run_session(
        root,
        Script(main=[*(_placed(s, root) for s in steps), text("end")]),
        files=WORKTREE_FILES,
        outside_files=OUTSIDE_FILES,
        profile=profile,
        role="electrical" if profile == "role" else None,
        held_out=(str(root / "outside" / "heldout"),),
    )


def _refusals(run: SessionRun) -> list[tuple[str, str]]:
    return [(e["hook"], e["reason"]) for e in run.hook_log if e.get("decision") == "refuse"]


@pytest.mark.parametrize("profile", ["role", "orchestrator"])
def test_a_write_into_the_gate_is_refused_and_the_file_never_exists(
    tmp_path: Path, profile: str
) -> None:
    run = _session(
        tmp_path,
        tool("Write", file_path="@W/src/physgate/gate/anything.py", content="PASS = True\n"),
        profile=profile,
    )
    assert not (run.worktree / "src" / "physgate" / "gate" / "anything.py").exists()
    ((hook, reason),) = _refusals(run)
    assert hook == "paths" and GATE_REASON in reason
    assert GATE_REASON in run.told_after(1)


def test_an_edit_of_an_existing_gate_file_is_refused_and_its_bytes_are_unchanged(
    tmp_path: Path,
) -> None:
    run = _session(
        tmp_path,
        tool("Read", file_path="@W/src/physgate/gate/check.py"),
        tool(
            "Edit",
            file_path="@W/src/physgate/gate/check.py",
            old_string="CHECK = True",
            new_string="CHECK = False",
        ),
    )
    assert (run.worktree / "src" / "physgate" / "gate" / "check.py").read_text() == "CHECK = True\n"
    assert [h for h, _ in _refusals(run)] == ["paths"]


def test_a_published_result_cannot_be_written(tmp_path: Path) -> None:
    run = _session(
        tmp_path,
        tool("Read", file_path="@W/experiments/R-OP-01/RESULT.md"),
        tool("Write", file_path="@W/experiments/R-OP-01/RESULT.md", content="rewritten\n"),
    )
    assert (run.worktree / "experiments" / "R-OP-01" / "RESULT.md").read_text() == (
        "published result\n"
    )
    ((hook, reason),) = _refusals(run)
    assert hook == "paths" and paths.FROZEN_RESULT in reason


def test_the_graph_journal_and_node_files_cannot_be_written(tmp_path: Path) -> None:
    run = _session(
        tmp_path,
        tool("Read", file_path="@O/store/journal.jsonl"),
        tool("Write", file_path="@O/store/journal.jsonl", content='{"rev":1}\n{"rev":2}\n'),
        tool("Read", file_path="@O/store/nodes/electrical.motor.json"),
        tool("Write", file_path="@O/store/nodes/electrical.motor.json", content="{}\n"),
    )
    assert (tmp_path / "outside" / "store" / "journal.jsonl").read_text() == '{"rev":1}\n'
    assert (tmp_path / "outside" / "store" / "nodes" / "electrical.motor.json").read_text() == (
        '{"rev":1}\n'
    )
    assert [h for h, _ in _refusals(run)] == ["paths", "paths"]
    assert all(STORE_REASON in r for _, r in _refusals(run))


def test_the_held_out_tier_cannot_be_read(tmp_path: Path) -> None:
    run = _session(tmp_path, tool("Read", file_path="@O/heldout/scenario_01.json"))
    ((hook, reason),) = _refusals(run)
    assert hook == "paths" and HELD_OUT_REASON in reason
    assert "the answer" not in run.told_after(1)


def test_a_tool_off_the_roles_list_is_refused_before_it_runs(tmp_path: Path) -> None:
    run = _session(tmp_path, tool("WebFetch", url="https://example.com", prompt="x"))
    ((hook, reason),) = _refusals(run)
    assert hook == "tools" and "WebFetch tool is not available to a role session" in reason


def test_an_ordinary_write_still_lands(tmp_path: Path) -> None:
    run = _session(
        tmp_path,
        tool("Write", file_path="@W/src/physgate/electrical/new.py", content="y = 2\n"),
    )
    assert (run.worktree / "src" / "physgate" / "electrical" / "new.py").read_text() == "y = 2\n"
    assert _refusals(run) == []


@pytest.mark.skipif(sys.platform != "darwin", reason="needs a case-insensitive volume")
def test_on_a_case_insensitive_volume_a_case_variant_of_the_gate_is_refused(
    tmp_path: Path,
) -> None:
    run = _session(
        tmp_path,
        tool("Read", file_path="@W/src/physgate/GATE/CHECK.PY"),
        tool("Write", file_path="@W/src/physgate/GATE/CHECK.PY", content="CHECK = False\n"),
    )
    assert (run.worktree / "src" / "physgate" / "gate" / "check.py").read_text() == "CHECK = True\n"
    assert [h for h, _ in _refusals(run)] == ["paths"]
