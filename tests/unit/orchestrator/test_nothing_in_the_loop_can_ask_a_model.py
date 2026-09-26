"""The routing fence: the orchestrator package has no way to call a model but one.

ARCH-001 allows one model call per run, at decomposition, and zero tokens on
scheduling, dispatch, merge or reconciliation. The cheapest way to break that is
a well-meant "ask the model" in a place that handles something awkward: a merge
conflict, a garbled session, a repair instruction. This test makes that a
failure rather than a review note, over the package's source:

- no provider client and no network library is imported anywhere in it;
- nothing imports a module by a name computed at run time;
- a process can be spawned only from the modules whose job that is (dispatch,
  decomposition, the git helper);
- the Claude Code binary is named only in the one module that builds a model
  invocation.

An import graph cannot see the route that matters most here, a subprocess
running the ``claude`` binary, which is why this is a syntax-tree check and not
an import linter.
"""

from __future__ import annotations

import ast
from pathlib import Path

import pytest

import physgate.orchestrator

PACKAGE = Path(physgate.orchestrator.__file__).parent

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
}
SPAWNING = {"subprocess", "pty", "multiprocessing", "asyncio.subprocess"}
OS_SPAWN = {"system", "popen", "fork", "forkpty", "posix_spawn", "posix_spawnp"}
OS_SPAWN_PREFIXES = ("exec", "spawn")
DYNAMIC_IMPORT = {"import_module", "__import__"}
MAY_SPAWN = {"dispatch.py", "decompose.py", "git.py"}
MAY_NAME_THE_BINARY = {"invocation.py"}


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
            modules = [node.module] + [f"{node.module}.{a.name}" for a in node.names]
        for module in modules:
            if _root(module) in NETWORK_OR_PROVIDER:
                found.append(f"{name}: imports {module}")
            if (module in SPAWNING or _root(module) in SPAWNING) and name not in MAY_SPAWN:
                found.append(f"{name}: imports {module}, which spawns processes")
            if module in {"importlib", "importlib.import_module"}:
                found.append(f"{name}: imports {module}")
        if isinstance(node, ast.Attribute) and isinstance(node.value, ast.Name):
            if node.value.id == "os" and name not in MAY_SPAWN:
                attr = node.attr
                if attr in OS_SPAWN or attr.startswith(OS_SPAWN_PREFIXES):
                    found.append(f"{name}: calls os.{attr}")
            if node.attr in DYNAMIC_IMPORT:
                found.append(f"{name}: imports by a computed name ({node.attr})")
        if isinstance(node, ast.Name) and node.id in DYNAMIC_IMPORT:
            found.append(f"{name}: imports by a computed name ({node.id})")
        if (
            isinstance(node, ast.Constant)
            and isinstance(node.value, str)
            and (node.value == "claude" or node.value.endswith("/claude"))
            and name not in MAY_NAME_THE_BINARY
        ):
            found.append(f"{name}: names the claude binary")
    return found


def package_violations(package: Path) -> list[str]:
    """Every fence violation under ``package``, one line each."""
    found: list[str] = []
    for path in sorted(package.rglob("*.py")):
        found += violations_in(path.name, path.read_text())
    return found


def test_the_package_has_source_to_check() -> None:
    assert len(list(PACKAGE.rglob("*.py"))) >= 5


def test_the_orchestrator_package_passes_the_fence() -> None:
    assert package_violations(PACKAGE) == []


PLANTED = {
    "a provider client": ("loop.py", "import anthropic\n"),
    "a provider client, from-import": ("merge.py", "from openai import OpenAI\n"),
    "an http client": ("budget.py", "import httpx\n"),
    "the standard library's http": ("queue.py", "from urllib.request import urlopen\n"),
    "a raw socket": ("accounting.py", "import socket\n"),
    "a subprocess in a routing module": ("loop.py", "import subprocess\n"),
    "a subprocess, from-import": ("merge.py", "from subprocess import run\n"),
    "os.system": ("loop.py", "import os\nos.system('claude -p x')\n"),
    "os.execvp": ("repair.py", "import os\nos.execvp('x', ['x'])\n"),
    "os.posix_spawn": ("queue.py", "import os\nos.posix_spawn('x', ['x'], {})\n"),
    "a computed import": ("loop.py", "import importlib\nimportlib.import_module('anthropic')\n"),
    "__import__": ("loop.py", "__import__('anthropic')\n"),
    "the binary named outside the invocation module": ("dispatch.py", "BINARY = 'claude'\n"),
    "the binary by path": ("loop.py", "BINARY = '/usr/local/bin/claude'\n"),
}


@pytest.mark.parametrize("case", sorted(PLANTED))
def test_each_forbidden_route_is_caught_where_it_is_planted(case: str, tmp_path: Path) -> None:
    name, source = PLANTED[case]
    (tmp_path / name).write_text(source)
    assert package_violations(tmp_path) != [], case


def test_the_modules_whose_job_it_is_may_spawn_and_name_the_binary(tmp_path: Path) -> None:
    (tmp_path / "dispatch.py").write_text("import subprocess\n")
    (tmp_path / "git.py").write_text("from subprocess import run\n")
    (tmp_path / "invocation.py").write_text("BINARY = 'claude'\n")
    assert package_violations(tmp_path) == []
