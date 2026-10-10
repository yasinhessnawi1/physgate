"""The escalation module cannot read the graph, spend a token or read the environment.

ARCH-131 admits a binding only if it spends no tokens on the decision and does not read
or write the design-state graph; the binding is chosen by the run's recorded
parameters, never by the environment. This is a syntax-tree test over the module that
holds the interface, the register and the backends, and it is an allowlist: the module
imports only what is listed, so the state package, ``os``, every provider and network
client, and every module nobody thought to name are refused alike. Names that evaluate
code, reach the builtins or read the environment are refused however they are reached.

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
from physgate.orchestrator.events import ATTRIBUTION

SOURCE = Path(escalation.__file__)

#: Every module the escalation module may import, and nothing else.
ALLOWED_MODULES = {
    "__future__",
    "time",
    "collections.abc",
    "typing",
    "pydantic",
    "physgate.orchestrator.budget",
    "physgate.orchestrator.common",
    "physgate.orchestrator.exceptions",
}
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
}


def _tree() -> ast.Module:
    return ast.parse(SOURCE.read_text(), filename=str(SOURCE))


def imported_modules(tree: ast.Module) -> set[str]:
    found: set[str] = set()
    for node in ast.walk(tree):
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


def test_the_module_imports_only_what_it_is_allowed() -> None:
    imported = imported_modules(_tree())
    assert imported, "a fence over nothing proves nothing"
    assert imported <= ALLOWED_MODULES, imported - ALLOWED_MODULES


def test_the_module_uses_no_name_that_evaluates_code_or_reads_the_environment() -> None:
    assert forbidden_names(_tree()) == set()


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
def test_the_fence_refuses_a_planted_import(planted: str) -> None:
    imported = imported_modules(ast.parse(SOURCE.read_text() + planted))
    assert not imported <= ALLOWED_MODULES


@pytest.mark.parametrize(
    "planted",
    ["x = os.environ['B']\n", "x = getenv('B')\n", "x = eval('1')\n", "x = open('f')\n"],
)
def test_the_fence_refuses_a_planted_name(planted: str) -> None:
    assert forbidden_names(ast.parse(SOURCE.read_text() + planted))


@pytest.mark.parametrize("who", ["escalation", "rules", "backend", "llm", "decision"])
def test_no_token_line_can_name_the_escalation_decision(who: str) -> None:
    assert re.match(ATTRIBUTION, f"{who}:x") is None
    assert re.match(ATTRIBUTION, "reviewer:x") is not None
