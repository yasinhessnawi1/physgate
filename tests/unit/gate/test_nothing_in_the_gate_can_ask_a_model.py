"""The gate's fence: nothing under the gate can call a model, the network, or a process.

The gate is deterministic tooling, never a model (ARCH-004, ARCH-080). A check
that "needs judgement" is answered by a sourced table or a surfaced decision,
never by asking a model whether 2.4 A is plausible; a gate that asks a model is
the thing it was built to check. This is a syntax-tree test over the package
source rather than an import linter, because an import graph cannot see the
route that matters most, a subprocess running a model binary, and cannot see a
string passed to ``eval``.

It also holds sympy to one module. sympy ships no type information, and the one
typed wrapper is what keeps its untyped values from spreading.
"""

from __future__ import annotations

import ast
from pathlib import Path

import pytest

import physgate.gate

PACKAGE = Path(physgate.gate.__file__).parent

NETWORK_OR_PROVIDER = {
    "anthropic",
    "openai",
    "httpx",
    "requests",
    "urllib",
    "urllib3",
    "http",
    "socket",
    "aiohttp",
    "websockets",
    "ssl",
}
SPAWNING = {"subprocess", "pty", "multiprocessing", "asyncio", "ctypes", "importlib"}
OS_SPAWN = {"system", "popen", "fork", "forkpty", "posix_spawn", "posix_spawnp"}
OS_SPAWN_PREFIXES = ("exec", "spawn")
FORBIDDEN_CALLS = {"eval", "exec", "compile", "__import__"}
#: The one module that may import sympy.
SYMPY_WRAPPER = "symbolic.py"


def _root(name: str) -> str:
    return name.split(".", 1)[0]


def violations_in(name: str, source: str) -> list[str]:
    """Every way the module ``name`` with ``source`` breaks the fence."""
    found: list[str] = []
    for node in ast.walk(ast.parse(source)):
        modules: list[str] = []
        if isinstance(node, ast.Import):
            modules = [alias.name for alias in node.names]
        elif isinstance(node, ast.ImportFrom) and node.module:
            modules = [node.module]
        for module in modules:
            if _root(module) in NETWORK_OR_PROVIDER:
                found.append(f"{name}: imports {module}, a provider or the network")
            if _root(module) in SPAWNING:
                found.append(f"{name}: imports {module}, which runs processes or loads code")
            if _root(module) == "sympy" and name != SYMPY_WRAPPER:
                found.append(f"{name}: imports sympy outside its typed wrapper")
        if (
            isinstance(node, ast.Attribute)
            and isinstance(node.value, ast.Name)
            and node.value.id == "os"
            and (node.attr in OS_SPAWN or node.attr.startswith(OS_SPAWN_PREFIXES))
        ):
            found.append(f"{name}: uses os.{node.attr}, which runs a process")
        if (
            isinstance(node, ast.Call)
            and isinstance(node.func, ast.Name)
            and node.func.id in FORBIDDEN_CALLS
        ):
            found.append(f"{name}: calls {node.func.id}")
        if (
            isinstance(node, ast.Constant)
            and isinstance(node.value, str)
            and "claude" in node.value.lower()
        ):
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
        ("import anthropic\n", "a provider or the network"),
        ("from openai import OpenAI\n", "a provider or the network"),
        ("import urllib.request\n", "a provider or the network"),
        ("import socket\n", "a provider or the network"),
        ("import subprocess\n", "runs processes"),
        ("from importlib import import_module\n", "loads code"),
        ("import os\nos.system('x')\n", "os.system"),
        ("import os\nos.execv('x', [])\n", "os.execv"),
        ("import os\nos.posix_spawn('x', [], {})\n", "os.posix_spawn"),
        ("eval('1 + 1')\n", "calls eval"),
        ("exec('x = 1')\n", "calls exec"),
        ("__import__('os')\n", "calls __import__"),
        ("BINARY = 'Claude'\n", "names the model binary"),
        ("import sympy\n", "outside its typed wrapper"),
        ("from sympy import Symbol\n", "outside its typed wrapper"),
    ],
)
def test_each_forbidden_form_is_caught_when_planted(
    tmp_path: Path, planted: str, expected: str
) -> None:
    (tmp_path / "check_planted.py").write_text(planted)
    found = fence(tmp_path)
    assert len(found) == 1 and expected in found[0], found


def test_sympy_is_allowed_in_its_wrapper_only(tmp_path: Path) -> None:
    (tmp_path / SYMPY_WRAPPER).write_text("import sympy\n")
    assert fence(tmp_path) == []
