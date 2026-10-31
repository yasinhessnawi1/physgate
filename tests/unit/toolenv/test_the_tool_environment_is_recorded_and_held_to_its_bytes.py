"""The tool environment is recorded as measured, refused where it may not lie, held to its bytes.

Each refusal has a failing input beside a passing one. The interpreter and the native tools are
answered by a stand-in runner, so what is tested is the judgement, not a machine's Python.
"""

from __future__ import annotations

import json
import os
from collections.abc import Sequence
from pathlib import Path

import pytest

from physgate.toolenv.exceptions import ToolEnvironmentError
from physgate.toolenv.manifest import manifest, scan
from physgate.toolenv.record import (
    Runner,
    ToolEnvironment,
    measure,
    require_same,
    require_unchanged,
)


def _environment(tmp_path: Path) -> tuple[Path, Path, Path]:
    """A tree shaped like an environment: an interpreter, a library file, a native tool."""
    root = tmp_path / "env"
    (root / "bin").mkdir(parents=True)
    (root / "lib" / "control").mkdir(parents=True)
    python = root / "bin" / "python3"
    python.write_text("#!/bin/sh\n")
    python.chmod(0o755)
    tool = root / "bin" / "avr-gcc"
    tool.write_text("#!/bin/sh\n")
    tool.chmod(0o755)
    (root / "lib" / "control" / "margins.py").write_text("def margin(): return 1\n")
    return root, python, tool


def _runner(root: Path, *, physgate: bool = False, prefix: str | None = None) -> Runner:
    answer = {
        "version": "3.12.9",
        "prefix": prefix or str(root),
        "base_prefix": str(root),
        "physgate": physgate,
        "distributions": [["control", "0.10.1"], ["numpy", "2.1.2"]],
    }

    def run(argv: Sequence[str]) -> str | None:
        if argv[1:2] == ["--version"]:
            return "avr-gcc (GCC) 7.3.0\nCopyright\n"
        return json.dumps(answer)

    return run


def _measure(
    root: Path,
    python: Path,
    tool: Path,
    *,
    runner: Runner | None = None,
    forbidden: dict[str, Path] | None = None,
) -> ToolEnvironment:
    if forbidden is None:
        forbidden = {"the harness checkout": root.parent / "harness"}
    return measure(
        str(python),
        [str(root)],
        native={"avr-gcc": str(tool)},
        forbidden=forbidden,
        runner=runner or _runner(root),
    )


def test_the_record_says_what_was_measured(tmp_path: Path) -> None:
    root, python, tool = _environment(tmp_path)
    env = _measure(root, python, tool)
    assert env.python_version == "3.12.9"
    assert [(d.name, d.version) for d in env.distributions] == [
        ("control", "0.10.1"),
        ("numpy", "2.1.2"),
    ]
    assert env.native_tools[0].version == "avr-gcc (GCC) 7.3.0"
    assert env.manifest_digest == manifest([root]).digest
    assert env.entries == manifest([root]).entries


def test_a_library_file_edited_after_the_record_is_refused(tmp_path: Path) -> None:
    root, python, tool = _environment(tmp_path)
    env = _measure(root, python, tool)
    require_same(env, forbidden={}, runner=_runner(root))
    (root / "lib" / "control" / "margins.py").write_text("def margin(): return 2\n")
    with pytest.raises(ToolEnvironmentError) as refused:
        require_same(env, forbidden={}, runner=_runner(root))
    assert "manifest_digest" in refused.value.context["changed"]


def test_a_write_that_puts_the_modification_time_back_is_still_seen(tmp_path: Path) -> None:
    root, python, tool = _environment(tmp_path)
    env = _measure(root, python, tool)
    at_start = scan([root])
    require_unchanged(env, at_start)
    library = root / "lib" / "control" / "margins.py"
    before = os.stat(library)
    library.write_text("def margin(): return 3\n")  # same size, other bytes
    os.utime(library, ns=(before.st_atime_ns, before.st_mtime_ns))
    with pytest.raises(ToolEnvironmentError):
        require_unchanged(env, at_start)


def test_an_added_or_removed_file_changes_the_scan(tmp_path: Path) -> None:
    root, _, _ = _environment(tmp_path)
    at_start = scan([root])
    (root / "lib" / "control" / "planted.pth").write_text("import os\n")
    assert scan([root]) != at_start
    (root / "lib" / "control" / "planted.pth").unlink()
    (root / "lib" / "control" / "margins.py").unlink()
    assert scan([root]) != at_start


def test_a_file_with_a_second_name_is_refused(tmp_path: Path) -> None:
    root, python, tool = _environment(tmp_path)
    _measure(root, python, tool)
    os.link(root / "lib" / "control" / "margins.py", tmp_path / "cache-copy.py")
    with pytest.raises(ToolEnvironmentError, match="another name"):
        _measure(root, python, tool)


def test_a_link_out_of_the_roots_is_refused_and_one_inside_is_kept(tmp_path: Path) -> None:
    root, python, tool = _environment(tmp_path)
    (root / "lib" / "inside").symlink_to(root / "lib" / "control")
    _measure(root, python, tool)
    outside = tmp_path / "elsewhere"
    outside.mkdir()
    (root / "lib" / "outside").symlink_to(outside)
    with pytest.raises(ToolEnvironmentError, match="leads outside"):
        _measure(root, python, tool)


def test_a_pipe_in_the_environment_is_refused(tmp_path: Path) -> None:
    root, python, tool = _environment(tmp_path)
    _measure(root, python, tool)
    os.mkfifo(root / "lib" / "pipe")
    with pytest.raises(ToolEnvironmentError, match="not a file"):
        _measure(root, python, tool)


@pytest.mark.parametrize("where", ["inside", "holding"])
def test_an_environment_overlapping_a_forbidden_place_is_refused(
    tmp_path: Path, where: str
) -> None:
    root, python, tool = _environment(tmp_path)
    _measure(root, python, tool, forbidden={"a session's worktree": tmp_path / "worktree"})
    place = tmp_path if where == "inside" else root / "lib"
    with pytest.raises(ToolEnvironmentError, match="overlaps a session's worktree"):
        _measure(root, python, tool, forbidden={"a session's worktree": place})


def test_an_interpreter_that_can_import_the_harness_is_refused(tmp_path: Path) -> None:
    root, python, tool = _environment(tmp_path)
    with pytest.raises(ToolEnvironmentError, match="import the harness"):
        _measure(root, python, tool, runner=_runner(root, physgate=True))


def test_programs_and_the_prefix_must_lie_inside_the_roots(tmp_path: Path) -> None:
    root, python, tool = _environment(tmp_path)
    stray = tmp_path / "stray"
    stray.write_text("#!/bin/sh\n")
    stray.chmod(0o755)
    with pytest.raises(ToolEnvironmentError, match="outside its roots"):
        _measure(root, python, stray)
    with pytest.raises(ToolEnvironmentError, match="prefix lies outside"):
        _measure(root, python, tool, runner=_runner(root, prefix=str(tmp_path)))


def test_a_relative_path_and_a_linked_root_are_refused(tmp_path: Path) -> None:
    root, python, tool = _environment(tmp_path)
    with pytest.raises(ToolEnvironmentError, match="absolute"):
        measure("bin/python3", [str(root)], native={}, forbidden={}, runner=_runner(root))
    (tmp_path / "alias").symlink_to(root)
    with pytest.raises(ToolEnvironmentError, match="through a link"):
        manifest([tmp_path / "alias"])


def test_nested_roots_are_refused(tmp_path: Path) -> None:
    root, _, _ = _environment(tmp_path)
    (tmp_path / "other").mkdir()
    manifest([root, tmp_path / "other"])
    with pytest.raises(ToolEnvironmentError, match="inside another"):
        manifest([root, root / "lib"])


def test_an_interpreter_that_answers_no_json_object_is_refused(tmp_path: Path) -> None:
    root, python, tool = _environment(tmp_path)
    for answer in ("not json", "[1, 2]", None):

        def run(argv: Sequence[str], answer: str | None = answer) -> str | None:
            return "tool 1.0\n" if argv[1:2] == ["--version"] else answer

        with pytest.raises(ToolEnvironmentError):
            _measure(root, python, tool, runner=run)


def test_a_native_tool_without_a_printable_version_line_is_refused(tmp_path: Path) -> None:
    root, python, tool = _environment(tmp_path)
    good = _runner(root)

    def run(argv: Sequence[str]) -> str | None:
        return "\x1b[31mred\n" if argv[1:2] == ["--version"] else good(argv)

    with pytest.raises(ToolEnvironmentError, match="version line"):
        _measure(root, python, tool, runner=run)
