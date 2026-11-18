"""No product module reaches the tiers or the gaps, by any chain of imports, at any depth.

The tiers and the gaps are thesis machinery (the tier sets, the exposure register, the probe, the
gaps and their trend), and the product never imports them, so the product is whole without them.
A module outside the evaluation imports none of them, and none of the evaluation's modules it does
import leads to them either: every import is followed, at module level and inside functions, from
every product module through every module of the package. Nor does a product module import them by
a string. Only the command's composition root, which wires the evaluation into the ``physgate``
command, reaches them, and only through the evaluation's own command modules and requirements. Read
from the source alone, so no row needs the evaluation's numerical libraries.
"""

from __future__ import annotations

import ast
import textwrap
from collections.abc import Mapping
from pathlib import Path

import pytest

SRC = Path(__file__).resolve().parents[3] / "src"
PACKAGE = SRC / "physgate"
HOMES = ("physgate.evaluation.tiers", "physgate.evaluation.gaps")
EVALUATION = "physgate.evaluation"
ROOT_MODULE = "physgate.cli"
DYNAMIC = ("import_module", "__import__")


def _name(path: Path) -> str:
    parts = list(path.relative_to(SRC).with_suffix("").parts)
    if parts[-1] == "__init__":
        parts.pop()
    return ".".join(parts)


def _in_a_home(module: str) -> bool:
    return any(module == home or module.startswith(home + ".") for home in HOMES)


def _imports(tree: ast.Module, module: str, known: frozenset[str]) -> set[str]:
    """Every module of the package this tree imports, at any depth, with each package on the way."""
    named: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            named |= {alias.name for alias in node.names}
        elif isinstance(node, ast.ImportFrom):
            base = node.module or ""
            if node.level:
                package = module.split(".")
                base = ".".join([*package[: len(package) - node.level], *([base] if base else [])])
            named.add(base)
            named |= {f"{base}.{alias.name}" for alias in node.names}
        elif isinstance(node, ast.Call) and _dynamic(node) is not None:
            named.add(str(_dynamic(node)))
    found: set[str] = set()
    for name in named:
        parts = name.split(".")
        found |= {".".join(parts[:i]) for i in range(1, len(parts) + 1)} & known
    return found


def _dynamic(node: ast.Call) -> str | None:
    """The module a call imports by a string, if it is one."""
    func = node.func
    called = func.id if isinstance(func, ast.Name) else getattr(func, "attr", None)
    if called in DYNAMIC and node.args and isinstance(node.args[0], ast.Constant):
        value = node.args[0].value
        return value if isinstance(value, str) else None
    return None


def _graph(sources: Mapping[str, str]) -> dict[str, set[str]]:
    known = frozenset(sources)
    return {m: _imports(ast.parse(text), m, known) for m, text in sources.items()}


def _reach(graph: Mapping[str, set[str]], start: str) -> list[str] | None:
    """The chain of imports from ``start`` to the tiers or the gaps, if there is one."""
    came_from: dict[str, str] = {}
    seen, stack = {start}, [start]
    while stack:
        here = stack.pop()
        for there in sorted(graph.get(here, ())):
            if there in seen:
                continue
            seen.add(there)
            came_from[there] = here
            if _in_a_home(there):
                chain = [there]
                while chain[-1] != start:
                    chain.append(came_from[chain[-1]])
                return chain[::-1]
            stack.append(there)
    return None


def _product(graph: Mapping[str, set[str]]) -> list[str]:
    return sorted(
        m
        for m in graph
        if m != ROOT_MODULE and not (m == EVALUATION or m.startswith(EVALUATION + "."))
    )


def _package_sources() -> dict[str, str]:
    return {_name(p): p.read_text() for p in sorted(PACKAGE.rglob("*.py"))}


def test_no_product_module_reaches_the_tiers_or_the_gaps() -> None:
    graph = _graph(_package_sources())
    reaching = {m: _reach(graph, m) for m in _product(graph)}
    assert {m: chain for m, chain in reaching.items() if chain} == {}


def test_the_composition_root_reaches_them_only_through_the_evaluation() -> None:
    graph = _graph(_package_sources())
    assert sorted(m for m in graph[ROOT_MODULE] if _in_a_home(m)) == []


def _planted(**sources: str) -> dict[str, set[str]]:
    base = {"physgate.evaluation.tiers.heldout": "", "physgate.evaluation.gaps.stats": ""}
    base["physgate.evaluation.observe.manifest"] = ""
    base.update({name.replace("__", "."): textwrap.dedent(text) for name, text in sources.items()})
    return _graph(base)


@pytest.mark.parametrize(
    "product",
    [
        "import physgate.evaluation.tiers.heldout\n",
        "from physgate.evaluation.gaps import stats\n",
        "def f():\n    from physgate.evaluation.tiers.heldout import snapshot\n    return 0\n",
        "import importlib as i\ndef f():\n    i.import_module('physgate.evaluation.gaps.stats')\n",
        "def f():\n    return __import__('physgate.evaluation.tiers.heldout')\n",
        "from physgate.evaluation.observe import between\n",
    ],
    ids=[
        "at module level",
        "a module of the gaps by its package",
        "inside a function",
        "by a string",
        "by the builtin",
        "through an evaluation module that imports them lazily",
    ],
)
def test_a_product_module_that_reaches_them_is_found(product: str) -> None:
    graph = _planted(
        physgate__ui__planted=product,
        physgate__evaluation__observe__between=(
            "def f():\n    from physgate.evaluation.tiers import heldout\n    return heldout\n"
        ),
    )
    chain = _reach(graph, "physgate.ui.planted")
    assert chain is not None and _in_a_home(chain[-1])


def test_a_product_module_that_imports_only_the_rest_of_the_evaluation_is_not_found() -> None:
    graph = _planted(physgate__ui__planted="from physgate.evaluation.observe import manifest\n")
    assert _reach(graph, "physgate.ui.planted") is None
