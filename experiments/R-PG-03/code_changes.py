"""R-PG-03, CRITERIA.md §3.3: every code change since the practice runs' trees; what the run loads.

Usage (from any checkout of the repository; it reads git objects only, never the work tree)::

    python -I code_changes.py --r <run commit> [--r-k <rubric-only sibling>] [--out <file>]
    python -I code_changes.py --walk <tree> [--seed-inject-only]

**The list.** For each of the three old trees, ``0936f1f`` (R-PG-02's run), ``eae78c0`` (the noise
run) and ``8c51f48`` (the kept round, ``gr2-r1-run-tree``), to ``R``, and from ``R`` to ``R_K``:
every commit that touched a file under ``src/physgate/``, or ``pyproject.toml`` or ``uv.lock``, with
its sha, its PR number where it has one, its subject and every such path it touched; and beside it
``git diff --stat`` of the same paths between the two trees, so the list does not depend on the
walk. A commit's PR number is the one its subject ends with (``(#66)``), else the one of the merge
commit on the target's first-parent line that brought it in (``Merge pull request #66``).

**The marks.** Inside the list each path is marked:

- ``loaded``: a Python file the walk reaches at the old tree or at the target;
- ``may be read``: every non-Python file under ``src/physgate/``, and ``pyproject.toml`` and
  ``uv.lock``;
- ``not loaded``: any other Python file.

**The walk.** Each file is read with Python's ``ast`` module through ``git cat-file``, at the old
tree and at the target. It is seeded with every module of ``physgate.evaluation.inject`` (the
inject runner), ``physgate.cli`` (the console script) and ``physgate.hooks.__main__`` (each
review's hook process), and follows every ``import`` and ``from ... import`` that names a
``physgate`` module, at any depth (inside a function, or under ``if TYPE_CHECKING:``), until no new
file is found:

- ``import p.m`` and ``from p.m import x`` resolve to ``p/m.py``, or ``p/m/__init__.py``;
- ``from p import m`` also resolves to ``p/m.py`` or ``p/m/__init__.py`` where one exists;
- the ``__init__.py`` of every parent package of a module reached counts;
- a relative import resolves against the importing module's package by the same rules;
- an import call whose module argument is a literal ``physgate`` name is followed as an import.

**The dynamic-import stop.** Any of these in a loaded file stops the script (exit 3), since the
mark could then miss a file:

- a call of ``importlib.import_module``, ``importlib.__import__``, ``__import__``,
  ``runpy.run_module`` or ``runpy.run_path`` whose module argument is not a string literal, under
  any name the function is called by;
- a call of the built-in ``exec``, ``eval`` or ``compile`` whose code argument is not a literal;
- a call of ``importlib.util.spec_from_file_location``, or of a loader's ``exec_module``;
- a call of ``importlib.metadata.entry_points``;
- a launch by ``-m`` of a ``physgate`` module whose file the walk does not reach, written as one
  string (``-m physgate.<x>``) or as ``-m`` followed by the module's name in a list.

``importlib.util.find_spec`` locates a module without importing it and is not a stop.

It writes the list to ``--out`` (never over a file) and prints counts only: per tree, the Python
files the walk marks and leaves; per range, the commits and the marked paths. ``--walk`` prints one
tree's walk alone (with ``--seed-inject-only``, seeded with the inject package alone).
"""

from __future__ import annotations

import argparse
import ast
import json
import re
import subprocess
import sys
from collections.abc import Iterable
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

HERE = Path(__file__).resolve().parent
REPO = HERE.parent.parent

SRC = "src/physgate"
PATHS = ("src/physgate", "pyproject.toml", "uv.lock")
TOP_FILES = ("pyproject.toml", "uv.lock")
OLD_TREES = {
    "0936f1f": "0936f1f7a36392cecc2091f28cd7b3dee524b02f",
    "eae78c0": "eae78c09b73d587691d463f7d557929124146094",
    "8c51f48": "8c51f481742cb60dc971586724db718f69ff8508",
}
INJECT_PACKAGE = "physgate.evaluation.inject"
SEED_MODULES = ("physgate.cli", "physgate.hooks.__main__")

#: The functions whose module argument must be a literal, by their qualified names.
IMPORT_CALLS = frozenset(
    {
        "importlib.import_module",
        "importlib.__import__",
        "builtins.__import__",
        "runpy.run_module",
        "runpy.run_path",
    }
)
#: The built-ins whose code argument must be a literal.
CODE_CALLS = frozenset({"builtins.exec", "builtins.eval", "builtins.compile"})
FILE_LOADERS = frozenset({"importlib.util.spec_from_file_location"})
ENTRY_POINTS = frozenset({"importlib.metadata.entry_points", "importlib_metadata.entry_points"})
_BUILTINS = {"__import__", "exec", "eval", "compile"}
_M_ONE_STRING = re.compile(r"(?:^|\s)-m\s+(physgate(?:\.[A-Za-z_][A-Za-z0-9_]*)*)(?![A-Za-z0-9_])")
_MODULE_NAME = re.compile(r"physgate(?:\.[A-Za-z_][A-Za-z0-9_]*)*")
_PR_SUBJECT = re.compile(r"\(#([0-9]+)\)\s*$")
_PR_MERGE = re.compile(r"^Merge pull request #([0-9]+)\b")


class StopError(Exception):
    """A dynamic import in a loaded file: the mark could miss a file."""


def git(repo: Path, *args: str) -> str:
    """One git command in ``repo``; its output. Raises on failure."""
    return subprocess.run(
        ["git", "-C", str(repo), *args], capture_output=True, text=True, check=True
    ).stdout


# ---------------------------------------------------------------- one tree's files


@dataclass
class Tree:
    """One tree's files under ``src/physgate``, read through git's object store only."""

    repo: Path
    rev: str
    files: list[str] = field(default_factory=list)
    _text: dict[str, str] = field(default_factory=dict)

    @classmethod
    def at(cls, repo: Path, rev: str) -> Tree:
        """The tree at ``rev``: its file names, and every Python file's text."""
        names = git(repo, "ls-tree", "-r", "--name-only", rev, "--", SRC).splitlines()
        tree = cls(repo=repo, rev=rev, files=sorted(n for n in names if n))
        tree._load([n for n in tree.files if n.endswith(".py")])
        return tree

    def _load(self, paths: list[str]) -> None:
        """Every Python file's text, in one ``git cat-file --batch`` call."""
        if not paths:
            return
        request = "".join(f"{self.rev}:{p}\n" for p in paths).encode()
        out = subprocess.run(
            ["git", "-C", str(self.repo), "cat-file", "--batch"],
            input=request,
            capture_output=True,
            check=True,
        ).stdout
        at = 0
        for path in paths:
            head_end = out.index(b"\n", at)
            head = out[at:head_end].split()
            if len(head) != 3 or head[1] != b"blob":
                raise StopError(f"{path} is not a blob at {self.rev[:12]}")
            size = int(head[2])
            body = out[head_end + 1 : head_end + 1 + size]
            self._text[path] = body.decode("utf-8")
            at = head_end + 1 + size + 1

    @property
    def python(self) -> list[str]:
        """Its Python files."""
        return [f for f in self.files if f.endswith(".py")]

    @property
    def others(self) -> list[str]:
        """Its other files."""
        return [f for f in self.files if not f.endswith(".py")]

    def text(self, path: str) -> str:
        """One Python file's text."""
        return self._text[path]

    def module_file(self, name: str) -> str | None:
        """The file a module name resolves to: ``p/m.py``, or ``p/m/__init__.py`` for a package."""
        if not _MODULE_NAME.fullmatch(name):
            return None
        base = "src/" + name.replace(".", "/")
        for candidate in (base + ".py", base + "/__init__.py"):
            if candidate in self._text:
                return candidate
        return None


def module_of(path: str) -> str:
    """The module a file under ``src/`` is: ``physgate/a/b.py`` is ``physgate.a.b``."""
    rel = path.removeprefix("src/").removesuffix(".py")
    return rel.removesuffix("/__init__").replace("/", ".")


def package_of(path: str) -> str:
    """The package a file's relative imports resolve against."""
    module = module_of(path)
    return module if path.endswith("/__init__.py") else module.rpartition(".")[0]


def parents_of(module: str) -> list[str]:
    """Every parent package of a module: ``physgate.a.b`` gives ``physgate`` and ``physgate.a``."""
    parts = module.split(".")
    return [".".join(parts[:k]) for k in range(1, len(parts))]


# ---------------------------------------------------------------- one file's imports and calls


def _dotted(node: ast.expr) -> list[str] | None:
    """An attribute chain's names, ``a.b.c`` as ``["a", "b", "c"]``; ``None`` if not a chain."""
    names: list[str] = []
    while isinstance(node, ast.Attribute):
        names.append(node.attr)
        node = node.value
    if isinstance(node, ast.Name):
        names.append(node.id)
        return list(reversed(names))
    return None


@dataclass
class FileFacts:
    """What one file imports, and the dynamic imports and ``-m`` launches it holds."""

    imports: set[str] = field(default_factory=set)
    from_imports: set[tuple[str, str]] = field(default_factory=set)
    stops: list[str] = field(default_factory=list)
    m_launches: set[str] = field(default_factory=set)


def _literal(node: ast.expr | None) -> str | None:
    return node.value if isinstance(node, ast.Constant) and isinstance(node.value, str) else None


def _arg(call: ast.Call, position: int, *names: str) -> ast.expr | None:
    if len(call.args) > position:
        return call.args[position]
    for kw in call.keywords:
        if kw.arg in names:
            return kw.value
    return None


def _resolve_relative(level: int, module: str | None, path: str) -> str:
    """A relative import's absolute name, against the importing module's package."""
    package = package_of(path).split(".")
    if level > 1:
        package = package[: len(package) - (level - 1)]
    base = ".".join(package)
    return f"{base}.{module}" if module else base


def facts_of(path: str, text: str) -> FileFacts:
    """Every import, and every stop and ``-m`` launch, in one file's syntax tree.

    Raises:
        StopError: the file does not parse, so what it imports is not known.
    """
    try:
        tree = ast.parse(text, filename=path)
    except SyntaxError as exc:
        raise StopError(f"{path} does not parse ({exc.msg}): what it imports is not known") from exc
    found = FileFacts()
    aliases: dict[str, str] = {}
    bound: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                found.imports.add(alias.name)
                if alias.asname:
                    aliases[alias.asname] = alias.name
                else:
                    top = alias.name.split(".")[0]
                    aliases.setdefault(top, top)
        elif isinstance(node, ast.ImportFrom):
            module = (
                _resolve_relative(node.level, node.module, path)
                if node.level
                else (node.module or "")
            )
            for alias in node.names:
                found.from_imports.add((module, alias.name))
                aliases[alias.asname or alias.name] = f"{module}.{alias.name}"
        elif isinstance(node, ast.FunctionDef | ast.AsyncFunctionDef | ast.ClassDef):
            bound.add(node.name)
        elif isinstance(node, ast.Assign):
            for target in node.targets:
                if isinstance(target, ast.Name):
                    bound.add(target.id)
                    chain = _dotted(node.value)
                    if chain is not None:
                        aliases[target.id] = ".".join(chain)
    for local in list(aliases):
        if local in _BUILTINS:
            bound.add(local)

    def qualified(func: ast.expr) -> str | None:
        chain = _dotted(func)
        if chain is None:
            return None
        head = chain[0]
        seen = 0
        while head in aliases and seen < 8:
            expanded = aliases[head].split(".")
            if expanded[0] == head and len(expanded) == 1:
                break
            chain = [*expanded, *chain[1:]]
            head = chain[0]
            seen += 1
        if len(chain) == 1 and chain[0] in _BUILTINS and chain[0] not in bound:
            return f"builtins.{chain[0]}"
        return ".".join(chain)

    for node in ast.walk(tree):
        if isinstance(node, ast.Call):
            name = qualified(node.func)
            where = f"{path}:{node.lineno}"
            if name in IMPORT_CALLS:
                literal = _literal(_arg(node, 0, "name", "mod_name", "path_name"))
                if literal is None:
                    found.stops.append(f"{where}: {name} with a module that is not a literal")
                elif name != "runpy.run_path":
                    if literal.startswith("."):
                        package = _literal(_arg(node, 1, "package"))
                        if package is None:
                            found.stops.append(f"{where}: {name} of a relative name, no package")
                            continue
                        level = len(literal) - len(literal.lstrip("."))
                        parts = package.split(".")
                        parts = parts[: len(parts) - (level - 1)] if level > 1 else parts
                        rest = literal.lstrip(".")
                        literal = ".".join(parts) + (f".{rest}" if rest else "")
                    if _MODULE_NAME.fullmatch(literal):
                        found.imports.add(literal)
            elif name in CODE_CALLS:
                if _literal(_arg(node, 0, "source")) is None:
                    found.stops.append(f"{where}: {name} of code that is not a literal")
            elif name in FILE_LOADERS:
                found.stops.append(f"{where}: {name}, a module loaded by its file path")
            elif name in ENTRY_POINTS:
                found.stops.append(f"{where}: {name}, a module loaded by a plug-in name")
            elif isinstance(node.func, ast.Attribute) and node.func.attr == "exec_module":
                found.stops.append(f"{where}: a loader's exec_module")
            found.m_launches |= _m_in_sequence(node.args)
        elif isinstance(node, ast.List | ast.Tuple | ast.Set):
            found.m_launches |= _m_in_sequence(node.elts)
        elif isinstance(node, ast.Constant) and isinstance(node.value, str):
            found.m_launches |= {m.group(1) for m in _M_ONE_STRING.finditer(node.value)}
    return found


def _m_in_sequence(elements: Iterable[ast.expr]) -> set[str]:
    """``-m`` followed by a literal ``physgate`` module name, in a list of literals."""
    items = list(elements)
    out = set()
    for first, second in zip(items, items[1:], strict=False):
        if _literal(first) == "-m":
            name = _literal(second)
            if name is not None and _MODULE_NAME.fullmatch(name):
                out.add(name)
    return out


# ---------------------------------------------------------------- the walk


@dataclass
class Walk:
    """One tree's walk: the files it reaches, and the stops found in them."""

    tree: Tree
    reached: set[str] = field(default_factory=set)
    stops: list[str] = field(default_factory=list)

    @property
    def unreached(self) -> list[str]:
        """The Python files the walk leaves."""
        return sorted(set(self.tree.python) - self.reached)


def seeds(tree: Tree, inject_only: bool = False) -> list[str]:
    """The walk's seeds at a tree: every module of the inject package, and the two entry points.

    Raises:
        StopError: a seed's file is not in the tree.
    """
    prefix = "src/" + INJECT_PACKAGE.replace(".", "/") + "/"
    found = [p for p in tree.python if p.startswith(prefix)]
    if not found:
        raise StopError(f"no module of {INJECT_PACKAGE} at {tree.rev[:12]}")
    if not inject_only:
        for name in SEED_MODULES:
            path = tree.module_file(name)
            if path is None:
                raise StopError(f"the seed {name} is not at {tree.rev[:12]}")
            found.append(path)
    return sorted(set(found))


def walk(tree: Tree, inject_only: bool = False) -> Walk:
    """§3.3's walk at one tree, and §3.3's stops in every file it reaches."""
    out = Walk(tree)
    queue = list(seeds(tree, inject_only))
    facts: dict[str, FileFacts] = {}

    def reach(path: str | None) -> None:
        if path is not None and path not in out.reached:
            out.reached.add(path)
            queue.append(path)

    while queue:
        path = queue.pop()
        out.reached.add(path)
        if path in facts:
            continue
        f = facts_of(path, tree.text(path))
        facts[path] = f
        for parent in parents_of(module_of(path)):
            reach(tree.module_file(parent))
        for name in f.imports:
            if name == "physgate" or name.startswith("physgate."):
                reach(tree.module_file(name))
                for parent in parents_of(name):
                    reach(tree.module_file(parent))
        for module, name in f.from_imports:
            if not (module == "physgate" or module.startswith("physgate.")):
                continue
            reach(tree.module_file(module))
            for parent in parents_of(module):
                reach(tree.module_file(parent))
            reach(tree.module_file(f"{module}.{name}"))
    for path in sorted(out.reached):
        out.stops += facts[path].stops
    for path in sorted(out.reached):
        for module in sorted(facts[path].m_launches):
            target = tree.module_file(module)
            main = tree.module_file(f"{module}.__main__")
            runs = main if target is not None and target.endswith("/__init__.py") else target
            if (
                target is None
                or runs is None
                or target not in out.reached
                or runs not in out.reached
            ):
                out.stops.append(
                    f"{path}: a launch by -m of {module}, a file the walk does not reach"
                )
    return out


# ---------------------------------------------------------------- the list


def pr_numbers(repo: Path, start: str, end: str) -> dict[str, str]:
    """Each commit between ``start`` and ``end``: the PR that brought it to ``end``'s line."""
    out: dict[str, str] = {}
    merges = git(
        repo, "log", "--first-parent", "--merges", "--format=%H %P%x09%s", f"{start}..{end}"
    ).splitlines()
    for line in merges:
        head, _, subject = line.partition("\t")
        shas = head.split()
        hit = _PR_MERGE.match(subject)
        if hit is None or len(shas) < 3:
            continue
        for sha in git(repo, "rev-list", f"{shas[1]}..{shas[2]}").split():
            out.setdefault(sha, hit.group(1))
    return out


def commits(repo: Path, start: str, end: str) -> list[dict[str, Any]]:
    """Every commit from ``start`` to ``end`` that touched one of :data:`PATHS`, oldest first.

    Every non-merge commit that changed such a path against its parent, with no history
    simplification; and every merge whose result differs from each of its parents on such a path
    (a conflict resolved, or a change made in the merge itself), which no other commit shows.
    """
    window = f"{start}..{end}"
    plain = git(
        repo, "log", "--full-history", "--no-merges", "--format=%H", window, "--", *PATHS
    ).split()
    merges = git(
        repo, "log", "--full-history", "--merges", "--format=%H", window, "--", *PATHS
    ).split()
    touched: dict[str, list[str]] = {}
    for sha in plain:
        touched[sha] = git(
            repo, "diff-tree", "--no-commit-id", "-r", "--name-only", sha, "--", *PATHS
        ).splitlines()
    for sha in merges:
        own = git(repo, "diff-tree", "--no-commit-id", "--cc", "--name-only", sha, "--", *PATHS)
        if own.strip():
            touched[sha] = own.splitlines()
    order = git(repo, "rev-list", "--reverse", "--topo-order", window).split()
    prs = pr_numbers(repo, start, end)
    out = []
    for sha in order:
        if sha not in touched:
            continue
        subject = git(repo, "log", "-1", "--format=%s", sha).rstrip("\n")
        own_pr = _PR_SUBJECT.search(subject) or _PR_MERGE.match(subject)
        out.append(
            {
                "sha": sha,
                "pr": own_pr.group(1) if own_pr else prs.get(sha),
                "subject": subject,
                "paths": sorted({p for p in touched[sha] if p}),
            }
        )
    return out


def mark(path: str, old: Walk, new: Walk) -> str:
    """A path's mark: loaded, may be read, or not loaded."""
    if path in TOP_FILES or (path.startswith(SRC + "/") and not path.endswith(".py")):
        return "may be read"
    if path in old.reached or path in new.reached:
        return "loaded"
    return "not loaded"


def one_range(repo: Path, start: str, end: str, old: Walk, new: Walk) -> dict[str, Any]:
    """The list from one tree to another, with every path marked, and the diff's stat."""
    listed = commits(repo, start, end)
    marks: dict[str, str] = {}
    for c in listed:
        c["paths"] = [{"path": p, "mark": mark(p, old, new)} for p in c["paths"]]
        for p in c["paths"]:
            marks[p["path"]] = p["mark"]
    stat = git(repo, "diff", "--stat=200", start, end, "--", *PATHS).rstrip("\n")
    return {
        "from": start,
        "to": end,
        "commits": listed,
        "diff_stat": stat.splitlines(),
        "paths_by_mark": {
            k: sum(v == k for v in marks.values()) for k in ("loaded", "may be read", "not loaded")
        },
    }


def tree_counts(w: Walk) -> dict[str, Any]:
    """One walk's counts: Python files marked and left, and the others."""
    return {
        "python_files": len(w.tree.python),
        "other_files": len(w.tree.others),
        "marked": len(w.reached),
        "unmarked": len(w.unreached),
        "unmarked_modules": [module_of(p) for p in w.unreached],
    }


def changes(
    repo: Path, r: str, r_k: str | None, old: dict[str, str] | None = None
) -> dict[str, Any]:
    """§3.3's whole list: three old trees to R, and R to R_K.

    ``old`` names other trees to list from: a correction (§11) lists from R ("Commits filled") to
    its R' and R_K' (``checks.py correction-check``).

    Raises:
        StopError: a dynamic import in a loaded file at any tree read.
    """
    r = git(repo, "rev-parse", "--verify", f"{r}^{{commit}}").strip()
    old = OLD_TREES if old is None else old
    walks: dict[str, Walk] = {"R": walk(Tree.at(repo, r))}
    for name, sha in old.items():
        walks[name] = walk(Tree.at(repo, sha))
    stops = sorted({s for w in walks.values() for s in w.stops})
    if stops:
        raise StopError("; ".join(stops))
    ranges = [one_range(repo, sha, r, walks[name], walks["R"]) for name, sha in old.items()]
    out: dict[str, Any] = {"R": r, "R_K": None, "paths": list(PATHS)}
    if r_k is not None:
        r_k = git(repo, "rev-parse", "--verify", f"{r_k}^{{commit}}").strip()
        walks["R_K"] = walk(Tree.at(repo, r_k))
        if walks["R_K"].stops:
            raise StopError("; ".join(walks["R_K"].stops))
        ranges.append(one_range(repo, r, r_k, walks["R"], walks["R_K"]))
        out["R_K"] = r_k
    out["seeds"] = [f"every module of {INJECT_PACKAGE}", *SEED_MODULES]
    out["trees"] = {name: tree_counts(w) for name, w in walks.items()}
    out["ranges"] = ranges
    out["stops"] = []
    return out


def counts(found: dict[str, Any]) -> dict[str, Any]:
    """What the script prints: counts only."""
    return {
        "R": found["R"],
        "R_K": found["R_K"],
        "trees": {
            k: {x: v[x] for x in ("python_files", "other_files", "marked", "unmarked")}
            for k, v in found["trees"].items()
        },
        "ranges": [
            {
                "from": g["from"][:7],
                "to": g["to"][:7],
                "commits": len(g["commits"]),
                "paths_by_mark": g["paths_by_mark"],
            }
            for g in found["ranges"]
        ],
    }


def main(argv: list[str] | None = None) -> int:
    """Write the list and print its counts; exit 3 on a stop, 1 on a refusal."""
    parser = argparse.ArgumentParser(description=(__doc__ or "").splitlines()[0])
    parser.add_argument("--repo", type=Path, default=REPO)
    parser.add_argument("--r")
    parser.add_argument("--r-k")
    parser.add_argument("--out", type=Path)
    parser.add_argument("--walk")
    parser.add_argument("--seed-inject-only", action="store_true")
    args = parser.parse_args(argv)
    try:
        if args.walk is not None:
            w = walk(Tree.at(args.repo, args.walk), inject_only=args.seed_inject_only)
            if w.stops and not args.seed_inject_only:
                raise StopError("; ".join(w.stops))
            # Seeded with the inject package alone, the hook process's -m launch is not reached:
            # that walk is a count for comparison, never the list's, so its stops are reported.
            shown = {"tree": args.walk, **tree_counts(w), "stops": len(w.stops)}
            print(json.dumps(shown, sort_keys=True))
            return 0
        if args.r is None:
            parser.error("--r names the run commit")
        if args.out is not None and args.out.exists():
            print(json.dumps({"refused": "the output exists; a list is never written over"}))
            return 1
        found = changes(args.repo, args.r, args.r_k)
    except StopError as exc:
        print(json.dumps({"stopped": str(exc)}))
        return 3
    except subprocess.CalledProcessError as exc:
        print(json.dumps({"refused": f"git failed: {' '.join(map(str, exc.cmd[3:5]))}"}))
        return 1
    if args.out is not None:
        args.out.write_text(json.dumps(found, indent=1, sort_keys=True) + "\n")
    print(json.dumps(counts(found), sort_keys=True))
    return 0


if __name__ == "__main__":
    sys.exit(main())
