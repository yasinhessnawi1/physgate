"""The drawing package asks no model and reaches no network, and its checker runs nothing.

A drawing is checked by rules and never judged by a model, so no module of the package imports a
model client or a network library. Only the module that hands scripts to the tool environment's
interpreter starts a process; the checker and everything it imports start none, so a check runs
anywhere, with no kernel and no environment.
"""

from __future__ import annotations

import ast
from pathlib import Path

import physgate.build.drawings

ROOT = Path(physgate.build.drawings.__file__).parent
MODEL_OR_NETWORK = (
    "anthropic",
    "openai",
    "socket",
    "ssl",
    "http",
    "urllib",
    "requests",
    "httpx",
    "aiohttp",
    "ftplib",
    "smtplib",
    "asyncio",
)
#: The harness's own modules that reach a model or a session.
HARNESS_MODEL = ("physgate.orchestrator", "physgate.reviewers", "physgate.roles", "physgate.hooks")
PROCESS = ("subprocess", "multiprocessing", "pty", "os.system")


def _imports(path: Path) -> list[str]:
    found: list[str] = []
    for node in ast.walk(ast.parse(path.read_text(encoding="utf-8"))):
        if isinstance(node, ast.Import):
            found += [alias.name for alias in node.names]
        elif isinstance(node, ast.ImportFrom):
            found.append(node.module or "")
    return found


def test_the_package_s_files_are_the_ones_listed() -> None:
    assert sorted(p.name for p in ROOT.glob("*.py")) == [
        "__init__.py",
        "check.py",
        "cli.py",
        "kernel.py",
        "record.py",
        "sheet.py",
    ]


def test_no_module_imports_a_model_client_or_a_network_library() -> None:
    for path in sorted(ROOT.glob("*.py")):
        for name in _imports(path):
            assert name.split(".")[0] not in MODEL_OR_NETWORK, (path.name, name)
            assert not name.startswith(HARNESS_MODEL), (path.name, name)


def test_only_the_kernel_s_module_starts_a_process() -> None:
    starting = sorted(
        path.name
        for path in ROOT.glob("*.py")
        if any(name.split(".")[0] in PROCESS for name in _imports(path))
    )
    assert starting == ["kernel.py"]


def test_the_checker_imports_nothing_that_starts_a_process() -> None:
    checker = _imports(ROOT / "check.py")
    own = [name for name in checker if name.startswith("physgate.")]
    assert sorted(set(own)) == ["physgate.build.drawings.record", "physgate.build.drawings.sheet"]
    for name in ("record.py", "sheet.py", "check.py"):
        assert not any(i.split(".")[0] in PROCESS for i in _imports(ROOT / name)), name
