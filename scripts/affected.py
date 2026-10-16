"""What a change can reach: the files changed since the merge base, and what they touch.

Two scripts ask it a question each. ``check.sh`` asks whether the operator UI's gate can be
affected, and runs it unless the answer is no. ``check-fast.sh`` asks which tests to run, for
the quick loop between full runs.

Both read the import graph from the source, statically, with nothing imported. Every doubt
answers towards running more: a file this script cannot place, a deleted module, a change to
the suite's shared fixtures or to the environment selects everything there is.

Usage::

    affected.py changed        the changed files, one per line
    affected.py ui             exit 0 when the UI gate can be affected, 3 when it cannot;
                               any other code is a failure, which the caller treats as a yes
    affected.py tests          the test files to run, or ``tests`` for the whole suite
"""

from __future__ import annotations

import ast
import os
import re
import subprocess
import sys
from collections.abc import Iterable
from functools import cache
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]

#: The Python trees the import graph covers. The experiments are frozen and import nothing
#: from here; their own fence test is selected by name below.
TREES = ("src", "tests", "scripts")

#: Changes that reach every test without an import: the suite's shared fixtures and the
#: environment the suite runs in.
EVERYTHING = frozenset(
    {"tests/conftest.py", "pyproject.toml", "uv.lock", ".python-version", "scripts/affected.py"}
)

#: Paths whose change cannot affect the operator UI's gate. That gate builds and checks the
#: app under ``ui/``, and its browser tests serve real runs that the real loop builds through
#: the test rigs. Python tests under these directories are run by the tests gate, not by it;
#: the experiments and the desktop app are not part of it. Anything not listed here, such as
#: a new top-level file, runs the gate.
NOT_UI = ("tests/unit/", "tests/integration/", "tests/injected/", "experiments/", "desktop/")

#: What the UI gate runs, from the Python side: the server's package, and the script that
#: builds the runs its browser tests read. A change in their import closure can change what
#: the gate sees.
UI_ROOTS = ("src/physgate/ui/", "tests/ui_e2e_runs.py")

#: The command line the browser tests start the server through. It imports every other
#: command's module only to offer that command, so it is part of what the gate runs, and the
#: other commands' modules are not: an import error in one of them turns the tests gate red
#: before this gate would have run.
UI_ENTRY = frozenset({"src/physgate/cli.py", "src/physgate/__init__.py"})


#: The exit code that means the UI gate cannot be affected. Not 1, which is also what an
#: uncaught error exits with: a crash here must never read as "skip the gate".
NOT_AFFECTED = 3


class AffectedError(Exception):
    """The changed files could not be worked out; the callers then run everything."""


def _git(*args: str) -> str:
    done = subprocess.run(
        ["git", "-C", str(REPO), *args], capture_output=True, text=True, check=False
    )
    if done.returncode != 0:
        msg = f"git {' '.join(args)} failed: {done.stderr.strip()}"
        raise AffectedError(msg)
    return done.stdout


def base_ref() -> str:
    """The ref the change is measured from: ``PHYSGATE_CHECK_BASE``, else the remote master."""
    named = os.environ.get("PHYSGATE_CHECK_BASE")
    if named:
        return named
    for ref in ("origin/master", "master"):
        if _git("rev-parse", "--verify", "--quiet", ref + "^{commit}", "--").strip():
            return ref
    msg = "no base to compare with: neither origin/master nor master exists"
    raise AffectedError(msg)


def changed_files() -> list[str]:
    """Every file that differs from the merge base: committed, uncommitted and untracked.

    Raises:
        AffectedError: git could not say.
    """
    base = _git("merge-base", "HEAD", base_ref()).strip()
    tracked = _git("diff", "--name-only", "--no-renames", "-z", base, "--").split("\0")
    untracked = _git("ls-files", "--others", "--exclude-standard", "-z").split("\0")
    return sorted({name for name in [*tracked, *untracked] if name})


def _python_files() -> list[Path]:
    return sorted(
        path
        for tree in TREES
        for path in (REPO / tree).rglob("*.py")
        if not any(part in {".venv", "node_modules", "__pycache__"} for part in path.parts)
    )


@cache
def _graph() -> dict[str, frozenset[str]]:
    """Each Python file's direct imports among this repository's files, by relative path."""
    files = _python_files()
    by_module: dict[str, str] = {}
    by_stem: dict[str, list[str]] = {}
    for path in files:
        rel = path.relative_to(REPO).as_posix()
        if rel.startswith("src/"):
            dotted = ".".join(path.relative_to(REPO / "src").with_suffix("").parts)
            by_module[dotted.removesuffix(".__init__")] = rel
        else:
            by_stem.setdefault(path.stem, []).append(rel)
    graph: dict[str, frozenset[str]] = {}
    for path in files:
        rel = path.relative_to(REPO).as_posix()
        graph[rel] = frozenset(_imports(path, rel, by_module, by_stem))
    return graph


def _imports(
    path: Path, rel: str, by_module: dict[str, str], by_stem: dict[str, list[str]]
) -> set[str]:
    try:
        tree = ast.parse(path.read_text(encoding="utf-8"))
    except (OSError, SyntaxError, UnicodeDecodeError):
        return set()
    names: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            names.update(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module and node.level == 0:
            names.add(node.module)
            names.update(f"{node.module}.{alias.name}" for alias in node.names)
    found: set[str] = set()
    here = str(Path(rel).parent)
    for name in names:
        parts = name.split(".")
        # A module and every package above it: importing a.b.c runs a/__init__ and a/b/__init__.
        for end in range(1, len(parts) + 1):
            target = by_module.get(".".join(parts[:end]))
            if target is not None:
                found.add(target)
        # The test tree has no packages: a helper is imported by its bare name, from the
        # importing file's own directory or from the directory the shared fixtures live in.
        candidates = by_stem.get(parts[0], [])
        same_dir = [c for c in candidates if str(Path(c).parent) == here]
        found.update(same_dir or candidates)
    found.discard(rel)
    return found


@cache
def _closure(rel: str) -> frozenset[str]:
    graph = _graph()
    seen: set[str] = set()
    stack = [rel]
    while stack:
        current = stack.pop()
        if current in seen:
            continue
        seen.add(current)
        stack.extend(graph.get(current, ()))
    return frozenset(seen)


def _test_files() -> list[str]:
    return [
        rel for rel in _graph() if rel.startswith("tests/") and Path(rel).name.startswith("test_")
    ]


def _reaches_everything(changed: Iterable[str]) -> bool:
    graph = _graph()
    # The shared fixtures run around every test, so the test-tree helpers they import do too.
    shared = {rel for rel in _closure("tests/conftest.py") if rel.startswith("tests/")}
    for rel in changed:
        if rel in EVERYTHING or rel in shared:
            return True
        # A Python file that no longer exists cannot be placed in the graph by its imports.
        if rel.endswith(".py") and rel.split("/")[0] in TREES and rel not in graph:
            return True
    return False


def _mentions(test: str, top: str) -> bool:
    text = (REPO / test).read_text(encoding="utf-8", errors="replace")
    return re.search(rf"[\"'/]{re.escape(top)}[\"'/]", text) is not None


def tests_for(changed: list[str]) -> list[str] | None:
    """The test files a change can reach, or ``None`` for the whole suite.

    A test is selected when it is changed itself, when its import closure holds a changed
    Python file, or when it names the top-level directory of a changed file that is not
    Python (a fixture file, the knowledge library, the frozen experiments).
    """
    if _reaches_everything(changed):
        return None
    tests = _test_files()
    graph = _graph()
    picked: set[str] = set()
    for rel in changed:
        if rel in graph:
            picked.update(test for test in tests if rel in _closure(test))
        elif "/" in rel:
            top = rel.split("/")[0]
            picked.update(test for test in tests if _mentions(test, top))
    return sorted(picked)


def ui_affected(changed: list[str]) -> str | None:
    """Why the UI gate can be affected by this change, or ``None`` when it cannot."""
    graph = _graph()
    roots = [rel for rel in graph if rel.startswith(UI_ROOTS)]
    reach = set(UI_ENTRY).union(*(_closure(root) for root in roots))
    for rel in changed:
        if rel in EVERYTHING:
            return f"{rel} changes what every gate runs under"
        if rel in reach:
            return f"{rel} is imported by the UI server or by the runs its browser tests read"
        if rel in graph or rel.startswith(NOT_UI):
            continue
        return f"{rel} is not a file this script knows cannot reach the UI gate"
    return None


def main(argv: list[str]) -> int:
    """Answer one question; see the module docstring."""
    if len(argv) != 1 or argv[0] not in {"changed", "ui", "tests"}:
        print(__doc__, file=sys.stderr)
        return 2
    try:
        changed = changed_files()
    except AffectedError as exc:
        print(f"affected: {exc}; treating everything as changed", file=sys.stderr)
        if argv[0] == "ui":
            return 0
        print({"changed": "", "tests": "tests"}[argv[0]])
        return 0
    if argv[0] == "changed":
        print("\n".join(changed))
        return 0
    if argv[0] == "ui":
        reason = ui_affected(changed)
        print(reason or "nothing changed since the merge base can reach the UI gate")
        return 0 if reason else NOT_AFFECTED
    tests = tests_for(changed)
    print("tests" if tests is None else "\n".join(tests))
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
