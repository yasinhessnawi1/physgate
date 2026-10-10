"""The UI server's fence: it imports only what is listed, so it cannot connect out or spawn.

Nor can it load code by name. A syntax-tree test over the package source, beside the runtime
guard: the guard aborts such an operation when a request makes it, and this refuses the code
that would make it before it is ever run. It is an allowlist, so a module nobody thought to
name is refused too. What it does not see is what an allowed in-repository module imports in
turn; that reach is what the runtime guard is for.
"""

from __future__ import annotations

import ast
from pathlib import Path

import physgate.ui

PACKAGE = Path(physgate.ui.__file__).parent

#: Every module the server package may import, and nothing else.
ALLOWED_MODULES = {
    "__future__",
    "argparse",
    "collections.abc",
    "contextlib",
    "contextvars",
    "dataclasses",
    "hashlib",
    "http",
    "http.server",
    "ipaddress",
    "json",
    "os",
    "pathlib",
    "re",
    "socket",
    "sys",
    "threading",
    "typing",
    "urllib.parse",
    "physgate",
    "physgate.hooks.paths",
    "physgate.orchestrator.credentials",
    "physgate.orchestrator.exceptions",
    "physgate.orchestrator.run_config",
    # The readers the command line uses, and their exceptions. Each is imported for its
    # read function only. Two of these modules can start a process elsewhere (the manifest
    # runs git to check commits, the run configuration measures a checkout); the server
    # calls neither of those functions, and inside a request the guard refuses a spawn.
    "physgate.evaluation.observe.cost",
    "physgate.evaluation.observe.exceptions",
    "physgate.evaluation.observe.manifest",
    "physgate.gate.exceptions",
    "physgate.gate.graph",
    "physgate.orchestrator.common",
    "physgate.orchestrator.events",
    "physgate.orchestrator.gate_events",
    "physgate.orchestrator.replay",
    "physgate.orchestrator.trajectory",
    "physgate.state.exceptions",
    "physgate.state.store",
    # The graph and run views' readers. The decision sequence's module can also run git (to
    # map commits to trees for a rerun's comparison); the server calls only its pure
    # ``decisions``, and inside a request the guard refuses a spawn. The rest read records.
    "physgate.evaluation.observe.sequence",
    "physgate.evaluation.observe.trace",
    "physgate.orchestrator.accounting",
    "physgate.orchestrator.change_sets",
    "physgate.state.schema",
}
#: Names that load or evaluate code however they are reached.
FORBIDDEN_NAMES = {"eval", "exec", "compile", "__import__", "import_module", "breakpoint"}


def _sources() -> list[Path]:
    found = sorted(PACKAGE.rglob("*.py"))
    assert found, "a fence over no files proves nothing"
    return found


def _problems(path: Path) -> list[str]:
    tree = ast.parse(path.read_text(), filename=str(path))
    found: list[str] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            modules = [alias.name for alias in node.names]
        elif isinstance(node, ast.ImportFrom):
            modules = [node.module or ""] if node.level == 0 else []
        else:
            modules = []
        for module in modules:
            if module not in ALLOWED_MODULES and not module.startswith("physgate.ui"):
                found.append(f"{path.name}: imports {module}")
        # A bare name is the builtin; an attribute is forbidden only where it loads code by
        # name, so a regular expression's ``re.compile`` is not mistaken for the builtin.
        if isinstance(node, ast.Name) and node.id in FORBIDDEN_NAMES:
            found.append(f"{path.name}: uses {node.id}")
        if isinstance(node, ast.Attribute) and node.attr in {"import_module", "__import__"}:
            found.append(f"{path.name}: uses {node.attr}")
    return found


def test_the_server_package_imports_only_what_is_listed() -> None:
    problems = [p for source in _sources() for p in _problems(source)]
    assert problems == []


def test_the_fence_catches_a_planted_outbound_import(tmp_path: Path) -> None:
    planted = tmp_path / "planted.py"
    planted.write_text("import urllib.request\nfrom subprocess import run\nx = eval('1')\n")
    assert _problems(planted) == [
        "planted.py: imports urllib.request",
        "planted.py: imports subprocess",
        "planted.py: uses eval",
    ]
