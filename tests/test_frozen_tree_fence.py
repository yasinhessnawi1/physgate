"""The toolchain does not reach into the directories holding measured results.

Those directories are frozen. The code in them produced numbers that are
cited, and it is kept byte for byte as it was when it produced them. Three
configuration settings keep the linter, the formatter and the type checker
out, and every one of them can be deleted with the rest of the suite still
green. These tests are what notices.

They run the real tools as subprocesses rather than inspecting the
configuration, because what matters is where the tools actually go, not what a
settings file appears to say. Each test below goes red when exactly one of the
three settings is removed; that correspondence is verified by deleting them
one at a time, and is the only reason to trust this file.
"""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
FROZEN = REPO_ROOT / "experiments"
TOOL_DIR = Path(sys.executable).parent


def _run(tool: str, *args: str) -> subprocess.CompletedProcess[str]:
    """Run one of the project's own tools from the repository root."""
    executable = TOOL_DIR / tool
    assert executable.exists(), (
        f"{tool} is not installed in this environment at {executable}; "
        "this test must fail rather than skip, because a fence test that "
        "quietly does not run is worse than no fence test"
    )
    return subprocess.run(
        [str(executable), *args],
        cwd=REPO_ROOT,
        capture_output=True,
        text=True,
        check=False,
    )


def _frozen_paths_in(text: str) -> list[str]:
    """Return the lines of ``text`` that name something inside the frozen tree."""
    return [line for line in text.splitlines() if "experiments/" in line or "experiments\\" in line]


def test_there_is_frozen_python_for_the_fence_to_protect() -> None:
    # Guard against every other test in this file passing vacuously. If the
    # directories were empty or renamed, "the tools found nothing there" would
    # be true and would mean nothing.
    assert FROZEN.is_dir(), f"{FROZEN} does not exist; the rest of this file proves nothing"
    frozen_python = list(FROZEN.rglob("*.py"))
    assert len(frozen_python) > 0, (
        "no Python under the frozen tree; the rest of this file proves nothing"
    )


def test_lint_over_the_whole_tree_reads_no_frozen_file() -> None:
    result = _run("ruff", "check", ".", "--show-files")
    # It must have read something, or "it read nothing frozen" is vacuous.
    assert result.stdout.strip(), (
        "the linter listed no files at all; it cannot have been fenced, only idle"
    )
    assert _frozen_paths_in(result.stdout) == []


def test_lint_named_directly_at_the_frozen_tree_reads_nothing() -> None:
    # A path given on the command line overrides an ordinary exclusion. This is
    # the shape the fence will actually be crossed in: someone tidying one
    # directory, by name.
    result = _run("ruff", "check", "experiments", "--show-files")
    assert _frozen_paths_in(result.stdout) == []


def test_formatter_named_directly_at_the_frozen_tree_would_rewrite_nothing() -> None:
    result = _run("ruff", "format", "--check", "experiments")
    combined = result.stdout + result.stderr
    assert "would be reformatted" not in combined, combined
    assert "already formatted" not in combined, combined


def test_type_checker_named_at_the_frozen_tree_reads_no_file_there() -> None:
    result = _run("mypy", "--strict", "experiments")
    combined = result.stdout + result.stderr
    reported = [
        line for line in _frozen_paths_in(combined) if ": error:" in line or ": note:" in line
    ]
    assert reported == [], combined


def test_the_type_checker_command_the_gate_runs_reads_no_frozen_file() -> None:
    result = _run("mypy", "--strict", "src", "tests")
    combined = result.stdout + result.stderr
    assert "checked" in combined or "Success" in combined, combined
    assert _frozen_paths_in(combined) == []
