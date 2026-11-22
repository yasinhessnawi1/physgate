"""Check a mutant list's entries: each find string once, each entry's files enough for its rows.

Run from a checkout's root: ``python scripts/mutation/check_entry_files.py <list.json>...``. A list
whose name ends ``_scoring.json`` is collected with ``.venv-evaluation``'s Python, any other with
``.venv``'s. Nothing is mutated and no row is run; the rows are only imported and collected.

For each entry, in order:

1. its ``file`` holds ``old`` exactly once, and ``old`` is not ``new`` (baselines apply nothing);
2. every file it names under ``tests`` and ``data`` exists;
3. every sibling test module a named row file imports (``import x``, ``from x import``,
   ``importlib.import_module("x")``) is named, and every fixture file or fixture directory a row
   file (or such a sibling) names as a string is named (a directory: every file in it);
4. in a copy of the tree made from ``src``, ``scripts``, ``pyproject.toml``, the files directly
   under ``tests`` and the named files only, the named row files import and collect without error
   (one copy per distinct set of files).

Exits 1 when any entry fails, printing each failure; prints one line per list.
"""

from __future__ import annotations

import ast
import json
import os
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path
from typing import Any


def _fixtures(root: Path) -> tuple[dict[str, list[str]], dict[str, list[str]]]:
    """Every ``.json``/``.jsonl`` file under ``tests`` by its name, and each directory of them."""
    by_file: dict[str, list[str]] = {}
    by_dir: dict[str, list[str]] = {}
    for path in sorted((root / "tests").rglob("*")):
        if not path.is_file() or path.suffix not in {".json", ".jsonl"}:
            continue
        rel = str(path.relative_to(root))
        by_file.setdefault(path.name, []).append(rel)
        directory = path.parent
        if not any(p.suffix == ".py" for p in directory.iterdir()):
            by_dir.setdefault(directory.name, []).append(rel)
    return by_file, by_dir


def _modules(root: Path) -> dict[str, str]:
    """Every test module below the top of ``tests`` by its module name (the file's stem)."""
    return {
        p.stem: str(p.relative_to(root))
        for p in sorted((root / "tests").rglob("*.py"))
        if "__pycache__" not in p.parts and p.parent != root / "tests"
    }


def _strings_and_imports(path: Path) -> tuple[set[str], set[str]]:
    """The string constants of a file, and the module names it imports (``import_module`` too)."""
    tree = ast.parse(path.read_text())
    strings: set[str] = set()
    imports: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Constant) and isinstance(node.value, str):
            strings.add(node.value)
        elif isinstance(node, ast.Import):
            imports.update(a.name.split(".")[0] for a in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module:
            imports.add(node.module.split(".")[0])
        elif (
            isinstance(node, ast.Call)
            and getattr(node.func, "attr", getattr(node.func, "id", "")) == "import_module"
            and node.args
            and isinstance(node.args[0], ast.Constant)
            and isinstance(node.args[0].value, str)
        ):
            imports.add(node.args[0].value.split(".")[0])
    return strings, imports


def _needed(
    root: Path,
    start: list[str],
    modules: dict[str, str],
    by_file: dict[str, list[str]],
    by_dir: dict[str, list[str]],
) -> set[str]:
    """The test modules and fixture files the row files ``start`` read or import, closed."""
    needed: set[str] = set()
    todo = list(start)
    seen: set[str] = set()
    while todo:
        current = todo.pop()
        if current in seen:
            continue
        seen.add(current)
        strings, imports = _strings_and_imports(root / current)
        for name in sorted(imports):
            if name in modules and modules[name] != current:
                needed.add(modules[name])
                todo.append(modules[name])
        for text in strings:
            for part in {text, *text.replace("\\", "/").split("/")}:
                if part in by_file and by_file[part]:
                    needed.update(by_file[part])
                if part in by_dir:
                    needed.update(by_dir[part])
    return needed


def _collect(root: Path, python: Path, tests: list[str], data: list[str]) -> str | None:
    """``None`` if the row files collect in a tree made of only the named files, else why not."""
    with tempfile.TemporaryDirectory(prefix="chk-") as work:
        tree = Path(os.path.realpath(work)) / "tree"
        tree.mkdir()
        ignore = shutil.ignore_patterns("__pycache__", "*.pyc")
        shutil.copytree(root / "src", tree / "src", ignore=ignore)
        shutil.copytree(root / "scripts", tree / "scripts", ignore=ignore)
        shutil.copy(root / "pyproject.toml", tree / "pyproject.toml")
        for path in (root / "tests").iterdir():
            if path.is_file():
                (tree / "tests").mkdir(exist_ok=True)
                shutil.copy(path, tree / "tests" / path.name)
        for name in [*tests, *data]:
            target = tree / name
            target.parent.mkdir(parents=True, exist_ok=True)
            if not target.exists():
                shutil.copy(root / name, target)
        env = {
            **os.environ,
            "PYTHONPATH": str(tree / "src"),
            "PYTHONPYCACHEPREFIX": str(Path(work) / "pycache"),
        }
        done = subprocess.run(
            [
                str(python),
                "-m",
                "pytest",
                "--collect-only",
                "-q",
                "-p",
                "no:cacheprovider",
                "-n",
                "0",
                *tests,
            ],
            cwd=tree,
            env=env,
            capture_output=True,
            text=True,
            check=False,
        )
        if done.returncode != 0:
            return (done.stdout + done.stderr)[-400:]
        if not any(line.startswith(tuple(tests)) for line in done.stdout.splitlines()):
            return "nothing was collected"
    return None


def check(path: Path, root: Path) -> list[str]:
    """Every failure of the list at ``path``, each as a line."""
    entries: list[dict[str, Any]] = json.loads(path.read_text())
    python = (
        root / (".venv-evaluation" if path.stem.endswith("_scoring") else ".venv") / "bin/python"
    )
    by_file, by_dir = _fixtures(root)
    modules = _modules(root)
    failures: list[str] = []
    names = [e["name"] for e in entries]
    if len(set(names)) != len(names):
        failures.append("a name is used twice")
    groups: dict[tuple[tuple[str, ...], tuple[str, ...]], list[str]] = {}
    for entry in entries:
        name = entry["name"]
        if not name.startswith("baseline"):
            text = (root / entry["file"]).read_text()
            if text.count(entry["old"]) != 1:
                failures.append(f"{name}: the find string occurs {text.count(entry['old'])} times")
            if entry["old"] == entry["new"]:
                failures.append(f"{name}: old and new are the same")
        named = [*entry["tests"], *entry.get("data", [])]
        missing = [f for f in named if not (root / f).exists()]
        if missing:
            failures.append(f"{name}: names a file that does not exist: {missing[0]}")
            continue
        needed = _needed(root, entry["tests"], modules, by_file, by_dir)
        lacking = sorted(needed - set(named))
        if lacking:
            failures.append(
                f"{name}: does not name {len(lacking)} file(s) its rows read, e.g. {lacking[0]}"
            )
        groups.setdefault((tuple(entry["tests"]), tuple(entry.get("data", []))), []).append(name)
    for (tests, data), members in groups.items():
        why = _collect(root, python, list(tests), list(data))
        if why is not None:
            failures.append(
                f"{len(members)} entries (e.g. {members[0]}): rows do not collect: {why}"
            )
    counts = f"{len(entries)} entries, {len(groups)} sets of files, {len(failures)} failures"
    print(f"{path.name}: {counts}")
    return failures


def main(argv: list[str]) -> int:
    """Check each list named in ``argv``; the exit status is 1 if any entry failed."""
    root = Path.cwd()
    failed = False
    for name in argv[1:]:
        for line in check(Path(name), root):
            failed = True
            print(f"  {line}")
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
