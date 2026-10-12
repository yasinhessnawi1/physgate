"""The escalation modules cannot read the graph, spend a token or read the environment.

ARCH-131 admits a binding only if it spends no tokens on the decision and does not read
or write the design-state graph; the binding is chosen by the run's recorded parameters,
never by the environment. This is a syntax-tree test over the two modules a backend
lives in or is handed: the interface, register and backends, and the state's schema. It
is an allowlist: each module imports only what is listed, so the state package, ``os``,
every provider and network client, and every module nobody thought to name are refused
alike. Names that evaluate code, reach the builtins or read the environment are refused
however they are reached. An import under ``if TYPE_CHECKING:`` never runs; it is held
to its own short list (the state builder's annotation of the replayed run), so a backend
still cannot reach it.

Tokens are held a second way: a token line names who spent it, and no attribution the
event log accepts names the escalation decision, so a token spent on it could not even
be recorded.
"""

from __future__ import annotations

import ast
import re
from pathlib import Path

import pytest

import physgate.orchestrator.escalation as escalation
import physgate.orchestrator.escalation_state as escalation_state
from physgate.orchestrator.events import ATTRIBUTION

SOURCE = Path(escalation.__file__)
STATE_SOURCE = Path(escalation_state.__file__)

#: Every module each escalation module may import at run time, and nothing else.
ALLOWED_MODULES = {
    SOURCE: {
        "__future__",
        "time",
        "collections.abc",
        "typing",
        "pydantic",
        "physgate.orchestrator.budget",
        "physgate.orchestrator.common",
        "physgate.orchestrator.escalation_state",
        "physgate.orchestrator.exceptions",
    },
    STATE_SOURCE: {
        "__future__",
        "re",
        "typing",
        "pydantic",
        "physgate.orchestrator.common",
        "physgate.orchestrator.exceptions",
        "physgate.orchestrator.protocols",
        "physgate.orchestrator.repair",
    },
}
#: Imports for annotations only, which never run.
ANNOTATION_ONLY = {SOURCE: set(), STATE_SOURCE: {"physgate.orchestrator.replay"}}
MODULES = sorted(ALLOWED_MODULES, key=str)
#: Names that evaluate code, reach the builtins, open a file or read the environment.
FORBIDDEN_NAMES = {
    "eval",
    "exec",
    "compile",
    "__import__",
    "breakpoint",
    "builtins",
    "getattr",
    "setattr",
    "globals",
    "locals",
    "vars",
    "open",
    "environ",
    "getenv",
    "putenv",
    "import_module",
    # The interpreter's module table, reachable through an allowed import (``typing.sys``):
    # any module at all, ``os`` included, is one lookup away from it.
    "sys",
    "modules",
}


def _tree(source: Path) -> ast.Module:
    return ast.parse(source.read_text(), filename=str(source))


def _annotation_blocks(tree: ast.Module) -> list[ast.If]:
    return [
        node
        for node in tree.body
        if isinstance(node, ast.If)
        and isinstance(node.test, ast.Name)
        and node.test.id == "TYPE_CHECKING"
    ]


def imported_modules(tree: ast.Module, *, annotations: bool = False) -> set[str]:
    """What ``tree`` imports at run time, or with ``annotations`` only under TYPE_CHECKING."""
    blocks = _annotation_blocks(tree)
    inside = {id(n) for block in blocks for n in ast.walk(block)}
    found: set[str] = set()
    for node in ast.walk(tree):
        if (id(node) in inside) != annotations:
            continue
        if isinstance(node, ast.Import):
            found.update(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom):
            found.add("." * node.level + (node.module or ""))
    return found


def forbidden_names(tree: ast.Module) -> set[str]:
    used: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Name):
            used.add(node.id)
        elif isinstance(node, ast.Attribute):
            used.add(node.attr)
        elif isinstance(node, ast.alias):
            used.add(node.name.rsplit(".", 1)[-1])
    return used & FORBIDDEN_NAMES


@pytest.mark.parametrize("source", MODULES, ids=lambda p: p.name)
def test_each_module_imports_only_what_it_is_allowed(source: Path) -> None:
    imported = imported_modules(_tree(source))
    assert imported, "a fence over nothing proves nothing"
    assert imported <= ALLOWED_MODULES[source], imported - ALLOWED_MODULES[source]
    annotated = imported_modules(_tree(source), annotations=True)
    assert annotated == ANNOTATION_ONLY[source]


@pytest.mark.parametrize("source", MODULES, ids=lambda p: p.name)
def test_each_module_uses_no_name_that_evaluates_code_or_reads_the_environment(
    source: Path,
) -> None:
    assert forbidden_names(_tree(source)) == set()


@pytest.mark.parametrize(
    "planted",
    [
        "import os\n",
        "from physgate.state.store import Store\n",
        "from physgate.gate.runner import PhysicsGate\n",
        "import anthropic\n",
        "import subprocess\n",
        "from . import dispatch\n",
    ],
)
@pytest.mark.parametrize("source", MODULES, ids=lambda p: p.name)
def test_the_fence_refuses_a_planted_import(planted: str, source: Path) -> None:
    imported = imported_modules(ast.parse(source.read_text() + planted))
    assert not imported <= ALLOWED_MODULES[source]


def test_an_annotation_only_import_outside_its_list_is_refused() -> None:
    planted = "if TYPE_CHECKING:\n    from physgate.state.store import Store\n"
    annotated = imported_modules(ast.parse(STATE_SOURCE.read_text() + planted), annotations=True)
    assert annotated != ANNOTATION_ONLY[STATE_SOURCE]


@pytest.mark.parametrize(
    "planted",
    [
        "x = os.environ['B']\n",
        "x = getenv('B')\n",
        "x = eval('1')\n",
        "x = open('f')\n",
        "x = typing.sys.modules['os'].system\n",
        "x = typing.sys\n",
    ],
)
@pytest.mark.parametrize("source", MODULES, ids=lambda p: p.name)
def test_the_fence_refuses_a_planted_name(planted: str, source: Path) -> None:
    assert forbidden_names(ast.parse(source.read_text() + planted))


@pytest.mark.parametrize("who", ["escalation", "rules", "backend", "llm", "decision"])
def test_no_token_line_can_name_the_escalation_decision(who: str) -> None:
    assert re.match(ATTRIBUTION, f"{who}:x") is None
    assert re.match(ATTRIBUTION, "reviewer:x") is not None
