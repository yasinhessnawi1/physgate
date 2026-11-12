"""An attempt that left build artefacts in its module is refused before the gate.

The orchestrator commits everything a session left in its worktree, so a build that wrote
into the module would put a build tree into the attempt, the review's diff and the run
branch. Builds belong in the session's temporary directory. An attempt whose commit adds a
build directory or a built file inside its module is therefore out of scope, like a change
outside the module: refused with the paths named, at no gate run and no review. A repair that
removes them is in scope again.
"""

from __future__ import annotations

from collections.abc import Mapping
from pathlib import Path

import pytest
from git_rig import ScopeChecker, run_layout

from physgate.orchestrator import merge
from physgate.orchestrator.git import head_of
from physgate.orchestrator.merge import RunGit, commit_attempt, write_scope_violations

pytestmark = pytest.mark.integration

MODULE = "modules/power"
BUILT = getattr(merge, "BUILD_ARTEFACT", "(the reason for a built file is not written yet)")
TREE = getattr(merge, "BUILD_DIRECTORY", "(the reason for a build directory is not written yet)")
MOST = getattr(merge, "MAX_ARTEFACTS_NAMED", 20)


def attempt(run: RunGit, files: Mapping[str, str | None], number: int = 1) -> tuple[str, str]:
    """Write ``files`` (None deletes) in the subtask's worktree; return (base, commit)."""
    worktree = run.open_subtask("s1")
    base = head_of(worktree, "HEAD")
    for rel, content in files.items():
        path = worktree / rel
        if content is None:
            path.unlink()
        else:
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(content)
    return base, commit_attempt(worktree, "s1", number, f"sess-{number}", repo=run.repo)


def found_in(tmp_path: Path, files: Mapping[str, str | None]) -> list[str]:
    run = run_layout(tmp_path)
    base, commit = attempt(run, files)
    return write_scope_violations(run.repo, base, commit, MODULE)


@pytest.mark.parametrize(
    "path",
    [
        f"{MODULE}/firmware.elf",
        f"{MODULE}/firmware.hex",
        f"{MODULE}/out/release/firmware.hex",
        f"{MODULE}/FIRMWARE.ELF",
        f"{MODULE}/build/main.cpp.o",
        f"{MODULE}/build/libFrameworkArduino.a",
        f"{MODULE}/firmware.eep",
    ],
)
def test_a_built_file_in_the_module_is_named(tmp_path: Path, path: str) -> None:
    assert found_in(tmp_path, {path: "built\n"}) == [f"{path} ({BUILT})"]


@pytest.mark.parametrize(
    ("files", "directory", "count"),
    [
        ({f"{MODULE}/.pio/build/balboa/firmware.elf": "x\n"}, f"{MODULE}/.pio", 1),
        (
            {
                f"{MODULE}/.pio/build/balboa/firmware.elf": "x\n",
                f"{MODULE}/.pio/build/balboa/firmware.hex": "x\n",
                f"{MODULE}/.pio/build/balboa/src/main.cpp.o": "x\n",
                f"{MODULE}/.pio/libdeps/balboa/readme.md": "x\n",
                f"{MODULE}/.pio/build/project.checksum": "x\n",
            },
            f"{MODULE}/.pio",
            5,
        ),
        ({f"{MODULE}/firmware/.pio/build/idedata.json": "{}\n"}, f"{MODULE}/firmware/.pio", 1),
        ({f"{MODULE}/.PIO/build/notes.txt": "x\n"}, f"{MODULE}/.PIO", 1),
    ],
    ids=["one file", "a whole tree, named once", "below the module's top", "another case"],
)
def test_a_build_directory_in_the_module_is_named_once_with_its_size(
    tmp_path: Path, files: dict[str, str | None], directory: str, count: int
) -> None:
    assert found_in(tmp_path, files) == [f"{directory}/ ({TREE}, {count} files)"]


@pytest.mark.parametrize(
    "path",
    [
        f"{MODULE}/src/main.cpp",
        f"{MODULE}/platformio.ini",
        f"{MODULE}/notes/hex.md",
        f"{MODULE}/elf.py",
        f"{MODULE}/pio/readme.md",
        f"{MODULE}/x.pio/readme.md",
        f"{MODULE}/.pioneer/readme.md",
        f"{MODULE}/firmware.hex.md",
        f"{MODULE}/table.o.txt",
    ],
)
def test_a_source_file_named_like_one_is_in_scope(tmp_path: Path, path: str) -> None:
    assert found_in(tmp_path, {path: "source\n"}) == []


def test_both_kinds_and_a_change_outside_the_module_are_all_named(tmp_path: Path) -> None:
    # Three faults at once: each is named for what it is, none hides another.
    found = found_in(
        tmp_path,
        {
            "README.md": "changed\n",
            f"{MODULE}/.pio/build/a.o": "x\n",
            f"{MODULE}/firmware.hex": "x\n",
            f"{MODULE}/src/main.cpp": "int main() {}\n",
        },
    )
    assert sorted(found) == sorted(
        [
            f"README.md (outside {MODULE})",
            f"{MODULE}/.pio/ ({TREE}, 1 files)",
            f"{MODULE}/firmware.hex ({BUILT})",
        ]
    )


def test_a_build_tree_outside_the_module_is_named_as_outside_only(tmp_path: Path) -> None:
    found = found_in(tmp_path, {"modules/control/.pio/build/a.elf": "x\n"})
    assert found == [f"modules/control/.pio/build/a.elf (outside {MODULE})"]


def test_a_repair_that_removes_the_artefacts_is_in_scope(tmp_path: Path) -> None:
    run = run_layout(tmp_path)
    files: dict[str, str | None] = {
        f"{MODULE}/.pio/build/firmware.elf": "x\n",
        f"{MODULE}/firmware.hex": "x\n",
        f"{MODULE}/src/main.cpp": "int main() {}\n",
    }
    base, first = attempt(run, files)
    assert len(write_scope_violations(run.repo, base, first, MODULE)) == 2
    removed: dict[str, str | None] = {
        f"{MODULE}/.pio/build/firmware.elf": None,
        f"{MODULE}/firmware.hex": None,
    }
    _, second = attempt(run, removed, number=2)
    assert write_scope_violations(run.repo, base, second, MODULE) == []
    # And from the first attempt's commit the removal itself is a change in scope.
    assert write_scope_violations(run.repo, first, second, MODULE) == []


def test_no_more_built_files_are_named_than_the_bound_and_the_rest_are_counted(
    tmp_path: Path,
) -> None:
    at_the_bound = {f"{MODULE}/out/f{n:02d}.hex": "x\n" for n in range(MOST)}
    found = found_in(tmp_path / "at", at_the_bound)
    assert found == [f"{path} ({BUILT})" for path in sorted(at_the_bound)]
    past_it = {f"{MODULE}/out/f{n:02d}.hex": "x\n" for n in range(MOST + 3)}
    found = found_in(tmp_path / "past", past_it)
    assert found[:MOST] == [f"{path} ({BUILT})" for path in sorted(past_it)[:MOST]]
    assert found[MOST:] == [f"{MODULE} (3 more built files, not named)"]


def test_the_change_check_refuses_such_an_attempt_and_its_reason_names_the_paths(
    tmp_path: Path,
) -> None:
    # As the loop asks it: a refusal by the scope check, before any gate run or review, whose
    # reason is what the repair instruction then carries to the next attempt.
    run = run_layout(tmp_path)
    _, commit = attempt(
        run,
        {
            f"{MODULE}/.pio/build/balboa/firmware.elf": "x\n",
            f"{MODULE}/firmware.hex": "x\n",
            f"{MODULE}/src/main.cpp": "int main() {}\n",
        },
    )
    checked = ScopeChecker(run, {"s1": MODULE}).check("s1", commit, "firmware")
    assert checked.refused_by == "write_scope"
    assert checked.reason is not None
    assert f"{MODULE}/.pio/ ({TREE}, 1 files)" in checked.reason
    assert f"{MODULE}/firmware.hex ({BUILT})" in checked.reason
    assert "main.cpp" not in checked.reason
    clean = run_layout(tmp_path / "clean")
    _, commit = attempt(clean, {f"{MODULE}/src/main.cpp": "int main() {}\n"})
    assert ScopeChecker(clean, {"s1": MODULE}).check("s1", commit, "firmware").refused_by is None
