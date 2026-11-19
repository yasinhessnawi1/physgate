"""Through the real binary: under ``skills: off`` a session reads the standards and acts.

A role session of an ablation run's ``skills: off`` arm is installed with what the dispatcher gives
it under that arm: the two standards files and the module specification to read, in a worktree
that holds no skill file, since decomposition put none into the run's target. Every call is a
real Claude Code tool call, driven by the scripted endpoint so no model can decline it, and judged
mechanically: the reading rule still holds the session until the smaller set is read, and then the
session acts without waiting for a file that is not there.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest
from fake_messages_api import Script, text, tool
from hook_session import SessionRun, run_session

from physgate.knowledge import loader

pytestmark = pytest.mark.integration

ROLE = "electrical"
SPEC = Path(".physgate/specs/e1.md")
DOC = "A line of required reading.\n" * 12

#: The worktree as the arm's specification commit checks it out: no skill file in it.
FILES = {
    "knowledge/cross/standards.md": DOC,
    f"knowledge/{ROLE}/standards.md": DOC,
    SPEC.as_posix(): DOC,
}


def bash(command: str) -> dict[str, Any]:
    return tool("Bash", command=command, description="x")


def _session(root: Path, steps: list[dict[str, Any]]) -> SessionRun:
    given = loader.session_reading(ROLE, SPEC, skills="off")
    worktree = root / "worktree"
    record = root / "outside" / "run" / "run.json"
    record.parent.mkdir(parents=True, exist_ok=True)
    record.write_text("{}\n")
    return run_session(
        root,
        Script(main=[*steps, text("end")]),
        files=FILES,
        required_reading=tuple(str(worktree / p) for p in given.required),
        always_loaded=tuple(str(worktree / p) for p in given.always_loaded),
        withheld=(str(record),),
    )


def _reads(root: Path) -> list[dict[str, Any]]:
    """The Read calls of the files a session under the arm must read, in full."""
    worktree = root / "worktree"
    return [tool("Read", file_path=str(worktree / name)) for name in FILES]


def test_a_call_waits_for_the_standards_and_the_session_acts_without_the_skill_file(
    tmp_path: Path,
) -> None:
    steps = [bash("echo early > early.txt"), *_reads(tmp_path), bash("echo done > done.txt")]
    run = _session(tmp_path, steps)
    refused = [e for e in run.hook_log if e.get("decision") == "refuse"]
    assert not (run.worktree / "early.txt").exists(), "a call ran before the standards were read"
    assert [e["hook"] for e in refused] == ["reading"]
    assert (run.worktree / "done.txt").exists(), "the session waited for a skill file"
    assert not (run.worktree / "knowledge" / ROLE / loader.SKILL_NAME).exists()
