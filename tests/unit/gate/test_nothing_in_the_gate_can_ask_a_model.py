"""The gate's fence: the gate imports only what it is allowed, so it can call no model.

The gate is deterministic tooling, never a model (ARCH-004, ARCH-080). A check
that "needs judgement" is answered by a sourced table or a surfaced decision,
never by asking a model whether 2.4 A is plausible; a gate that asks a model is
the thing it was built to check. This is a syntax-tree test over the package
source rather than an import linter, because an import graph cannot see a string
passed to ``eval`` or a name looked up on the path.

It is an allowlist. The gate imports only the modules listed, and from the state
package only its read-only reader, so the repository's own model-calling code,
an aliased ``os``, ``posix`` and every module nobody thought to name are refused
alike. Names that evaluate code, reach the builtins or look a binary up are
refused however they are reached, and a string naming the model binary is
refused even when it is split and joined with ``+``.

It also holds sympy to one module. sympy ships no type information, and the one
typed wrapper is what keeps its untyped values from spreading.
"""

from __future__ import annotations

import ast
from pathlib import Path

import pytest

import physgate.gate

PACKAGE = Path(physgate.gate.__file__).parent

#: Every module the gate may import, and nothing else: the standard library's
#: modules it needs, pint, pydantic, and the in-repository modules that do no I/O
#: beyond reading. Anything not listed is refused, so a way out nobody thought of
#: is refused too; a denylist has to name every one.
ALLOWED_MODULES = {
    "__future__",
    "collections.abc",
    "dataclasses",
    "datetime",
    "fractions",
    "hashlib",
    "json",
    "pathlib",
    "tomllib",
    "types",
    "typing",
    "pint",
    "pydantic",
    "physgate.orchestrator.protocols",
    "physgate.orchestrator.common",
    "physgate.state.schema",
}
#: Modules the gate may take named things from, and only those things.
ALLOWED_NAMES = {"physgate.state.store": {"journal_records_after"}}
GATE = "physgate.gate"
#: The one module that may import sympy.
SYMPY_WRAPPER = "symbolic.py"
#: Names that evaluate code, reach the builtins, or look a binary up on the path,
#: whatever they are reached through.
FORBIDDEN_NAMES = {
    "eval",
    "exec",
    "compile",
    "__import__",
    "breakpoint",
    "builtins",
    "getattr",
    "setattr",
    "delattr",
    "globals",
    "locals",
    "vars",
    "which",
    "get_exec_path",
    "find_executable",
    "environ",
    "getenv",
}
#: Dunder attributes the gate uses; any other is a way into the interpreter.
ALLOWED_DUNDERS = {"__file__", "__init__", "__name__", "__version__"}


def _module_allowed(module: str, file: str) -> bool:
    if module == "sympy" or module.startswith("sympy."):
        return file == SYMPY_WRAPPER
    return module in ALLOWED_MODULES or module == GATE or module.startswith(GATE + ".")


def _imports(name: str, node: ast.AST) -> list[str]:
    found: list[str] = []
    if isinstance(node, ast.Import):
        for alias in node.names:
            if not _module_allowed(alias.name, name):
                found.append(f"{name}: imports {alias.name}, which the gate may not import")
    elif isinstance(node, ast.ImportFrom):
        module = node.module or ""
        if node.level > 1:
            found.append(f"{name}: imports from outside the gate by a relative import")
        elif node.level == 1:
            pass  # a module of the gate itself
        elif module in ALLOWED_NAMES:
            found.extend(
                f"{name}: imports {alias.name} from {module}, which the gate may not import"
                for alias in node.names
                if alias.name not in ALLOWED_NAMES[module]
            )
        elif not _module_allowed(module, name):
            found.append(f"{name}: imports from {module}, which the gate may not import")
    return found


def _folded(node: ast.AST) -> str | None:
    """A string built from constants by ``+``, folded, so a split name is seen whole."""
    if isinstance(node, ast.Constant) and isinstance(node.value, str):
        return node.value
    if isinstance(node, ast.BinOp) and isinstance(node.op, ast.Add):
        left, right = _folded(node.left), _folded(node.right)
        if left is not None and right is not None:
            return left + right
    return None


def violations_in(name: str, source: str) -> list[str]:
    """Every way the module ``name`` with ``source`` breaks the fence."""
    found: list[str] = []
    for node in ast.walk(ast.parse(source)):
        found.extend(_imports(name, node))
        used = (
            node.id
            if isinstance(node, ast.Name)
            else node.attr
            if isinstance(node, ast.Attribute)
            else None
        )
        if used in FORBIDDEN_NAMES:
            found.append(f"{name}: uses {used}, which evaluates code or looks a binary up")
        elif (
            used is not None
            and used.startswith("__")
            and used.endswith("__")
            and used not in ALLOWED_DUNDERS
        ):
            found.append(f"{name}: uses {used}, a way into the interpreter")
        text = _folded(node)
        if text is not None and "claude" in text.lower():
            found.append(f"{name}: names the model binary")
    return found


def fence(root: Path) -> list[str]:
    """Every violation in every module under ``root``."""
    return [
        problem
        for path in sorted(root.rglob("*.py"))
        for problem in violations_in(path.name, path.read_text())
    ]


def test_the_fence_sees_the_gate_s_modules() -> None:
    modules = sorted(p.name for p in PACKAGE.rglob("*.py"))
    assert {"runner.py", "registry.py", "graph.py", "tolerances.py"} <= set(modules)


def test_nothing_in_the_gate_can_ask_a_model_or_reach_out() -> None:
    assert fence(PACKAGE) == []


@pytest.mark.parametrize(
    ("planted", "expected"),
    [
        ("import anthropic\n", "imports anthropic"),
        ("from openai import OpenAI\n", "imports from openai"),
        ("import urllib.request\n", "imports urllib.request"),
        ("import socket\n", "imports socket"),
        ("import subprocess\n", "imports subprocess"),
        ("from importlib import import_module\n", "imports from importlib"),
        ("import concurrent.futures\n", "imports concurrent.futures"),
        ("import posix\n", "imports posix"),
        ("import os as o\n", "imports os"),
        ("from os import system\n", "imports from os"),
        ("import builtins\n", "imports builtins"),
        ("x.eval('1 + 1')\n", "uses eval"),
        ("eval('1 + 1')\n", "uses eval"),
        ("exec('x = 1')\n", "uses exec"),
        ("__import__('os')\n", "uses __import__"),
        ("getattr(x, 'y')\n", "uses getattr"),
        ("x.__globals__\n", "a way into the interpreter"),
        ("x.__subclasses__\n", "a way into the interpreter"),
        ("x.which('y')\n", "looks a binary up"),
        ("x.environ\n", "looks a binary up"),
        ("BINARY = 'Claude'\n", "names the model binary"),
        ("BINARY = 'cla' + 'ude'\n", "names the model binary"),
        ("import sympy\n", "imports sympy"),
        ("from sympy import Symbol\n", "imports from sympy"),
        (
            "from physgate.orchestrator.invocation import claude_binary\n",
            "imports from physgate.orchestrator.invocation",
        ),
        ("from physgate.orchestrator import dispatch\n", "imports from physgate.orchestrator"),
        ("import physgate.orchestrator.decompose\n", "imports physgate.orchestrator.decompose"),
        ("from physgate.state.store import Store\n", "imports Store from physgate.state.store"),
        ("from .. import orchestrator\n", "by a relative import"),
    ],
)
def test_each_forbidden_form_is_caught_when_planted(
    tmp_path: Path, planted: str, expected: str
) -> None:
    (tmp_path / "check_planted.py").write_text(planted)
    found = fence(tmp_path)
    assert found and any(expected in problem for problem in found), found


def test_what_the_gate_needs_passes_the_fence(tmp_path: Path) -> None:
    (tmp_path / "check_planted.py").write_text(
        "from fractions import Fraction\n"
        "import pint\n"
        "from physgate.gate.units import measure\n"
        "from physgate.state.store import journal_records_after\n"
        "from physgate.orchestrator.protocols import CheckRecord\n"
        "from . import units\n"
        "VERSION = pint.__version__\n"
    )
    assert fence(tmp_path) == []


def test_sympy_is_allowed_in_its_wrapper_only(tmp_path: Path) -> None:
    (tmp_path / SYMPY_WRAPPER).write_text("import sympy\n")
    assert fence(tmp_path) == []
