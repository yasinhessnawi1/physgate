"""No product module reaches the tiers or the gaps, by any chain of imports, at any depth.

The tiers and the gaps are thesis machinery (the tier sets, the exposure register, the probe, the
gaps and their trend), and the product never imports them, so the product is whole without them.
A module outside the evaluation imports none of them, and none of the evaluation's modules it does
import leads to them either: every import is followed, at module level and inside functions, from
every product module through every module of the package. A module imported by a literal string
is followed like any import. Only the command's composition root, which wires the evaluation into
the ``physgate`` command, reaches them, and only through the evaluation's own command modules and
requirements. Read from the source alone, so no row needs the evaluation's numerical libraries.

What the import graph cannot follow is refused outright in a product module: an import by a name
computed at run time (any argument to ``import_module`` or ``__import__``, under any alias, that is
not a literal string), and any string naming the tiers' or the gaps' commands or modules, which is
how a product module would run them as a program of its own.

What these rows cannot see: an attribute taken by name from a package already imported
(``getattr(evaluation, "tiers")``, which works only once something else has imported it); a
module loaded by other means (``runpy`` or ``importlib.util`` with a computed name, a path given to
the interpreter); a command word put together at run time or read from a file or the environment;
and a program outside the package (a script, a hook, the interface's own code) that runs the
commands.
"""

from __future__ import annotations

import ast
import re
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
    importers = _importers(tree)
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
        elif isinstance(node, ast.Call) and _dynamic(node, importers) is not None:
            named.add(str(_dynamic(node, importers)))
    found: set[str] = set()
    for name in named:
        parts = name.split(".")
        found |= {".".join(parts[:i]) for i in range(1, len(parts) + 1)} & known
    return found


def _dynamic(node: ast.Call, importers: frozenset[str]) -> str | None:
    """The module a call imports by a literal string, if it is one."""
    if _imports_by_a_string(node, importers) and node.args:
        first = node.args[0]
        if isinstance(first, ast.Constant) and isinstance(first.value, str):
            return first.value
    return None


def _importers(tree: ast.Module) -> frozenset[str]:
    """The names a module calls to import by a string: the two, and any alias it gives them."""
    names = set(DYNAMIC)
    for node in ast.walk(tree):
        if isinstance(node, ast.ImportFrom) and node.module in ("importlib", "builtins"):
            names |= {alias.asname or alias.name for alias in node.names if alias.name in DYNAMIC}
    return frozenset(names)


def _imports_by_a_string(node: ast.Call, importers: frozenset[str]) -> bool:
    func = node.func
    if isinstance(func, ast.Name):
        return func.id in importers
    return isinstance(func, ast.Attribute) and func.attr in DYNAMIC


def _computed(tree: ast.Module) -> list[int]:
    """The lines where a module is imported by a name computed at run time."""
    importers = _importers(tree)
    return sorted(
        node.lineno
        for node in ast.walk(tree)
        if isinstance(node, ast.Call)
        and _imports_by_a_string(node, importers)
        and not (
            node.args
            and isinstance(node.args[0], ast.Constant)
            and isinstance(node.args[0].value, str)
        )
    )


#: A string that runs the tiers' or the gaps' commands: a command word given alone, the command
#: with its word, or one of their modules by its dotted name.
COMMAND_WORDS = ("tiers", "gaps")
COMMAND = re.compile(r"\bphysgate\s+(?:tiers|gaps)\b|\bphysgate\.evaluation\.(?:tiers|gaps)\b")


def _command_words(tree: ast.Module) -> list[str]:
    """The strings that name the tiers' or the gaps' commands, or their modules."""
    return [
        node.value
        for node in ast.walk(tree)
        if isinstance(node, ast.Constant)
        and isinstance(node.value, str)
        and (node.value.strip() in COMMAND_WORDS or COMMAND.search(node.value))
    ]


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


# ------------------------------------------- what the import graph cannot follow, refused outright
#
# A module imported by a name computed at run time cannot be followed from the source, so a
# product module imports nothing that way. Nor does a product module run the tiers' or the gaps'
# commands as a program of their own: no string of a product module names them.


def _product_sources() -> dict[str, str]:
    sources = _package_sources()
    return {m: sources[m] for m in _product(_graph(sources))}


def test_no_product_module_imports_a_module_by_a_name_it_computes() -> None:
    found = {m: _computed(ast.parse(text)) for m, text in _product_sources().items()}
    assert {m: lines for m, lines in found.items() if lines} == {}


@pytest.mark.parametrize(
    "product",
    [
        "import importlib\ndef f(name):\n    return importlib.import_module(name)\n",
        "def f():\n    return __import__('physgate.' + 'evaluation.tiers')\n",
        "from importlib import import_module as load\n"
        "def f(n):\n    return load(f'physgate.{n}')\n",
        "import importlib\nPLACE = 'physgate.evaluation.gaps'\n"
        "M = importlib.import_module(PLACE)\n",
        "import builtins\ndef f(*names):\n    return builtins.__import__(*names)\n",
    ],
    ids=[
        "by a variable",
        "by a sum",
        "by an alias and a format",
        "by a constant's name",
        "unpacked",
    ],
)
def test_an_import_by_a_computed_name_is_found(product: str) -> None:
    assert _computed(ast.parse(textwrap.dedent(product))) != []


def test_an_import_by_a_literal_name_is_followed_not_refused() -> None:
    product = "import importlib\nM = importlib.import_module('physgate.ui.paths')\n"
    assert _computed(ast.parse(product)) == []
    aliased = _planted(
        physgate__ui__planted=(
            "from importlib import import_module as load\n"
            "M = load('physgate.evaluation.gaps.stats')\n"
        )
    )
    chain = _reach(aliased, "physgate.ui.planted")
    assert chain is not None and _in_a_home(chain[-1])


def test_no_product_module_runs_the_tiers_or_the_gaps_commands() -> None:
    found = {m: _command_words(ast.parse(text)) for m, text in _product_sources().items()}
    assert {m: words for m, words in found.items() if words} == {}


@pytest.mark.parametrize(
    "product",
    [
        "import subprocess\ndef f(v):\n    subprocess.run(['physgate', 'tiers', 'probe', v])\n",
        "import os\ndef f():\n    os.system('uv run physgate gaps --append trend.jsonl')\n",
        "import sys, subprocess\nARGS = [sys.executable, '-m', 'physgate', 'gaps']\n",
        "import subprocess\ndef f(w):\n    subprocess.run(f'physgate tiers status --store {w}')\n",
        "import runpy\ndef f():\n    runpy.run_module('physgate.evaluation.tiers.probe')\n",
    ],
    ids=["as words", "through a shell", "as a module's command", "in a format", "as a module"],
)
def test_a_product_module_that_runs_their_commands_is_found(product: str) -> None:
    assert _command_words(ast.parse(textwrap.dedent(product))) != []


def test_a_product_module_running_another_command_is_not_found() -> None:
    product = "import subprocess\ndef f():\n    subprocess.run(['physgate', 'run', 'gate'])\n"
    assert _command_words(ast.parse(product)) == []
