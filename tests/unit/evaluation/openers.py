"""What reads a tier's files: found in the source alone, every import followed to where it points.

A function reads a tier when it uses one of the functions that read a tier's bytes or a task's
file, wherever it took that function from and under whatever name, or when it joins a path onto a
protected tier's name. Read from the source alone, so no row needs the evaluation's numerical
libraries, and nothing is imported or run.
"""

from __future__ import annotations

import ast
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
        base = ".".join([*package[: len(package) - node.level], *([base] if base else [])])
    for alias in node.names:
        scope.names[alias.asname or alias.name] = f"{base}.{alias.name}"


def _is_reader(target: str | None) -> bool:
    if target is None:
        return False
    module, _, name = target.rpartition(".")
    return name in READERS.get(module, frozenset())


def _joins_a_tier_name(node: ast.BinOp, scope: _Scope) -> bool:
    if not isinstance(node.op, ast.Div):
        return False
    right = node.right
    if isinstance(right, ast.Constant):
        return right.value in TIER_NAMES
    target = scope.resolve(right)
    if target is None or not target.startswith("physgate.evaluation.tiers."):
        return False
    return target.rpartition(".")[2] in TIER_NAME_CONSTANTS


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


def readers_in(tree: ast.Module, module: str) -> dict[str, set[str]]:
    """Each function (by its dotted place in ``module``) that reads a tier, and how."""
    scope = _Scope(module)
    for node in ast.walk(tree):
        if isinstance(node, ast.Import | ast.ImportFrom):
            _bind(scope, node)
    found: dict[str, set[str]] = {}

    def visit(node: ast.AST, place: list[str]) -> None:
        if isinstance(node, ast.FunctionDef | ast.AsyncFunctionDef | ast.ClassDef):
            for child in ast.iter_child_nodes(node):
                visit(child, [*place, node.name])
            return
        where = ".".join(place) or "<module>"
        if isinstance(node, ast.Name | ast.Attribute) and isinstance(node.ctx, ast.Load):
            target = scope.resolve(node)
            if _is_reader(target):
                found.setdefault(where, set()).add(str(target).rpartition(".")[2])
                return
        if isinstance(node, ast.BinOp) and _joins_a_tier_name(node, scope):
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


def readers_under(src: Path) -> dict[str, set[str]]:
    """Every function beneath ``src`` that reads a tier: ``module:function`` and how."""
    found: dict[str, set[str]] = {}
    for path in sorted(src.rglob("*.py")):
        module = module_name(path, src)
        tree = ast.parse(path.read_text(), filename=str(path))
        for where, how in readers_in(tree, module).items():
            found[f"{module}:{where}"] = how
    return found
