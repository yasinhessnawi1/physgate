"""What reads a tier's files: found in the source alone, every import followed to where it points.

A function reads a tier when it uses one of the functions that read a tier's bytes or a task's
file, wherever it took that function from and under whatever name (a module that imports one, or
binds it to a name of its own, re-exports it, and a caller taking it from there is found too), or
when it joins a path onto a protected tier's name: by ``/``, ``os.path.join``, ``joinpath``, a
path's constructor, a string's ``join`` over a literal list, or a format string. Read from the
source alone, so no row needs the evaluation's numerical libraries, and nothing is imported or run.

What it cannot see: a function that is given a tier's path as an argument and reads it with the
standard library (it reads a tier only where its caller chose the path); a tier's name put
together at run time or read from a file; and a caller of a function that reads a tier, unless that
function is one of the primitives below (the function itself is found, and named or refused).
"""

from __future__ import annotations

import ast
import re
from collections.abc import Collection, Mapping
from dataclasses import dataclass, field
from pathlib import Path

#: The functions that read a tier's bytes or a task's file, by the module that defines them.
READERS: dict[str, frozenset[str]] = {
    "physgate.evaluation.tiers.heldout": frozenset({"snapshot", "tier_digest", "scan", "digest"}),
    "physgate.evaluation.tiers.manifest": frozenset({"tier_record", "read_version"}),
    "physgate.evaluation.tiers.task": frozenset({"parse_task", "load_task", "task_from_files"}),
    "physgate.evaluation.tiers.canaries": frozenset(
        {"_canary_list", "root_canaries", "store_canaries"}
    ),
}
#: A protected tier's name, as a path is joined onto it: a string, or a name of the tiers that
#: holds one; and the names of the files only a protected tier holds.
TIER_NAMES = frozenset({"held_out", "validation"})
TIER_NAME_CONSTANTS = frozenset(
    {"PROTECTED", "PROTECTED_TIERS", "PROBED_TIER", "SUMS_NAME", "CANARIES_NAME"}
)
#: The modules whose names, imported by a string, reach a reader without an import statement.
DYNAMIC = ("import_module", "__import__")


def module_name(path: Path, src: Path) -> str:
    """The dotted name of the module at ``path`` beneath ``src``."""
    parts = list(path.relative_to(src).with_suffix("").parts)
    if parts[-1] == "__init__":
        parts.pop()
    return ".".join(parts)


@dataclass
class _Scope:
    """What each name of a module stands for: a module, or a function of one."""

    module: str
    names: dict[str, str] = field(default_factory=dict)
    #: Whether the module is a package's own (its ``__init__``), which a relative import
    #: starts from.
    package: bool = False

    def resolve(self, node: ast.expr) -> str | None:
        """The dotted target ``node`` names, followed through the module's imports."""
        if isinstance(node, ast.Name):
            if node.id in self.names:
                return self.names[node.id]
            return f"{self.module}.{node.id}"
        if isinstance(node, ast.Attribute):
            base = self.resolve(node.value)
            return None if base is None else f"{base}.{node.attr}"
        return None


def _bind(scope: _Scope, node: ast.Import | ast.ImportFrom) -> None:
    if isinstance(node, ast.Import):
        for alias in node.names:
            if alias.asname:
                scope.names[alias.asname] = alias.name
            else:
                top = alias.name.split(".")[0]
                scope.names[top] = top
        return
    base = node.module or ""
    if node.level:
        package = scope.module.split(".")
        up = node.level - 1 if scope.package else node.level
        base = ".".join([*package[: len(package) - up], *([base] if base else [])])
    for alias in node.names:
        scope.names[alias.asname or alias.name] = f"{base}.{alias.name}"


Readers = Mapping[str, Collection[str]]


def _is_reader(target: str | None, readers: Readers = READERS) -> bool:
    if target is None:
        return False
    module, _, name = target.rpartition(".")
    return name in readers.get(module, frozenset())


def _is_tier_name(node: ast.expr, scope: _Scope) -> bool:
    """A protected tier's name: as a string, or as a name of the tiers that holds one."""
    if isinstance(node, ast.Constant):
        return node.value in TIER_NAMES
    target = scope.resolve(node)
    if target is None or not target.startswith("physgate.evaluation.tiers."):
        return False
    return target.rpartition(".")[2] in TIER_NAME_CONSTANTS


def _joins_a_tier_name(node: ast.BinOp, scope: _Scope) -> bool:
    return isinstance(node.op, ast.Div) and _is_tier_name(node.right, scope)


#: The calls that join their arguments into a path.
PATH_JOINS = frozenset(
    {
        "os.path.join",
        "posixpath.join",
        "pathlib.Path",
        "pathlib.PurePath",
        "pathlib.PosixPath",
        "pathlib.PurePosixPath",
    }
)
#: A protected tier's name as one segment of a path a format string writes out.
TIER_SEGMENT = re.compile(r"(?:^|/)(?:held_out|validation)(?:/|$)")


def _joins_by_a_call(node: ast.Call, scope: _Scope) -> bool:
    """A path joined onto a protected tier's name by a call."""
    func = node.func
    parts: list[ast.expr] = list(node.args)
    if (
        isinstance(func, ast.Attribute)
        and func.attr == "join"
        and isinstance(func.value, ast.Constant)
    ):
        # ``"/".join([...])``: the parts are the literal list's items.
        listed = node.args[0] if node.args else None
        parts = list(listed.elts) if isinstance(listed, ast.List | ast.Tuple) else []
    elif not (
        (isinstance(func, ast.Attribute) and func.attr == "joinpath")
        or scope.resolve(func) in PATH_JOINS
    ):
        return False
    return any(_is_tier_name(part, scope) for part in parts)


def _formats_a_tier_path(node: ast.JoinedStr, scope: _Scope) -> bool:
    """A format string that writes a protected tier's name as a segment of a path.

    A name of the tiers formatted in counts only beside a ``/``: a name compared with a file's
    name (``f".{CANARIES_NAME}"``) is no path.
    """
    written = "".join(str(p.value) for p in node.values if isinstance(p, ast.Constant))
    if TIER_SEGMENT.search(written):
        return True
    return "/" in written and any(
        isinstance(part, ast.FormattedValue) and _is_tier_name(part.value, scope)
        for part in node.values
    )


def _dynamic_reach(node: ast.Call) -> bool:
    """A module of the tiers imported by a string, by whatever name."""
    func = node.func
    name = func.id if isinstance(func, ast.Name) else getattr(func, "attr", None)
    if name not in DYNAMIC or not node.args:
        return False
    first = node.args[0]
    return isinstance(first, ast.Constant) and str(first.value).startswith(
        "physgate.evaluation.tiers"
    )


def _scope_of(tree: ast.Module, module: str, *, package: bool = False) -> _Scope:
    scope = _Scope(module, package=package)
    for node in ast.walk(tree):
        if isinstance(node, ast.Import | ast.ImportFrom):
            _bind(scope, node)
    return scope


def readers_in(
    tree: ast.Module, module: str, readers: Readers = READERS, *, package: bool = False
) -> dict[str, set[str]]:
    """Each function (by its dotted place in ``module``) that reads a tier, and how.

    ``readers``: the functions that read a tier, by the module a caller takes them from.
    ``package``: the module is a package's own, where a relative import starts.
    """
    scope = _scope_of(tree, module, package=package)
    found: dict[str, set[str]] = {}

    def visit(node: ast.AST, place: list[str]) -> None:
        if isinstance(node, ast.FunctionDef | ast.AsyncFunctionDef | ast.ClassDef):
            for child in ast.iter_child_nodes(node):
                visit(child, [*place, node.name])
            return
        where = ".".join(place) or "<module>"
        if isinstance(node, ast.Name | ast.Attribute) and isinstance(node.ctx, ast.Load):
            target = scope.resolve(node)
            if _is_reader(target, readers):
                found.setdefault(where, set()).add(str(target).rpartition(".")[2])
                return
        joined = (isinstance(node, ast.BinOp) and _joins_a_tier_name(node, scope)) or (
            isinstance(node, ast.Call) and _joins_by_a_call(node, scope)
        )
        if joined or (isinstance(node, ast.JoinedStr) and _formats_a_tier_path(node, scope)):
            found.setdefault(where, set()).add("a protected tier's path")
        if isinstance(node, ast.Call) and _dynamic_reach(node):
            found.setdefault(where, set()).add("a tier module imported by a string")
        for child in ast.iter_child_nodes(node):
            visit(child, place)

    for node in tree.body:
        if isinstance(node, ast.Import | ast.ImportFrom):
            continue
        visit(node, [])
    return found


def _bound_to_a_reader(
    tree: ast.Module, module: str, readers: Readers, *, package: bool
) -> set[str]:
    """The names ``module`` binds at its top level to a reader: an import, or an assignment."""
    scope = _scope_of(tree, module, package=package)
    names: set[str] = set()
    for node in tree.body:
        if isinstance(node, ast.ImportFrom):
            own = _Scope(module, package=package)
            _bind(own, node)
            names |= {name for name, target in own.names.items() if _is_reader(target, readers)}
        elif isinstance(node, ast.Assign | ast.AnnAssign) and node.value is not None:
            if _is_reader(scope.resolve(node.value), readers):
                targets = node.targets if isinstance(node, ast.Assign) else [node.target]
                names |= {t.id for t in targets if isinstance(t, ast.Name)}
    return names


def _packages(modules: Collection[str]) -> frozenset[str]:
    """The modules that are a package's own: those another module lies beneath."""
    return frozenset(m for m in modules if any(o.startswith(m + ".") for o in modules))


def _readers_with_reexports(trees: Mapping[str, ast.Module]) -> dict[str, set[str]]:
    """The primitives, and every name a module binds to one, followed until nothing is added."""
    readers: dict[str, set[str]] = {module: set(names) for module, names in READERS.items()}
    packages = _packages(trees)
    added = True
    while added:
        added = False
        for module, tree in trees.items():
            bound = _bound_to_a_reader(tree, module, readers, package=module in packages)
            new = bound - readers.get(module, set())
            if new:
                readers.setdefault(module, set()).update(new)
                added = True
    return readers


def _trees(sources: Mapping[str, str]) -> dict[str, ast.Module]:
    return {module: ast.parse(text) for module, text in sorted(sources.items())}


def readers_of(sources: Mapping[str, str]) -> dict[str, set[str]]:
    """Every function of ``sources`` (source by module name) that reads a tier, and how."""
    trees = _trees(sources)
    readers = _readers_with_reexports(trees)
    packages = _packages(trees)
    found: dict[str, set[str]] = {}
    for module, tree in trees.items():
        for where, how in readers_in(tree, module, readers, package=module in packages).items():
            found[f"{module}:{where}"] = how
    return found


def reexports_of(sources: Mapping[str, str]) -> dict[str, frozenset[str]]:
    """Each module's names that stand for a reader defined in another module."""
    readers = _readers_with_reexports(_trees(sources))
    return {
        module: frozenset(extra)
        for module, names in sorted(readers.items())
        if (extra := names - READERS.get(module, frozenset()))
    }


def sources_under(src: Path) -> dict[str, str]:
    """The source of every module beneath ``src``, by its dotted name."""
    return {module_name(p, src): p.read_text() for p in sorted(src.rglob("*.py"))}


def readers_under(src: Path) -> dict[str, set[str]]:
    """Every function beneath ``src`` that reads a tier: ``module:function`` and how."""
    return readers_of(sources_under(src))
