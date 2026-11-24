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
#: The modules that start a process.
PROCESS = ("subprocess", "multiprocessing", "pty", "concurrent")
#: What of ``os`` starts a process: reachable through a plain ``import os``, so held by name.
OS_PROCESS = ("system", "popen", "fork", "forkpty", "posix_spawn", "posix_spawnp")
OS_PROCESS_PREFIXES = ("exec", "spawn")


def _imports(path: Path) -> list[str]:
    found: list[str] = []
    for node in ast.walk(ast.parse(path.read_text(encoding="utf-8"))):
        if isinstance(node, ast.Import):
            found += [alias.name for alias in node.names]
        elif isinstance(node, ast.ImportFrom):
            found.append(node.module or "")
    return found


def _starts_a_process_of_os(name: str) -> bool:
    return name in OS_PROCESS or name.startswith(OS_PROCESS_PREFIXES)


def _os_process_uses(path: Path) -> list[str]:
    """Every ``os.<name>`` and ``from os import <name>`` in the file that starts a process."""
    found: list[str] = []
    for node in ast.walk(ast.parse(path.read_text(encoding="utf-8"))):
        if (
            isinstance(node, ast.Attribute)
            and isinstance(node.value, ast.Name)
            and node.value.id == "os"
            and _starts_a_process_of_os(node.attr)
        ):
            found.append(f"os.{node.attr}")
        elif isinstance(node, ast.ImportFrom) and node.module == "os":
            found += [f"os.{a.name}" for a in node.names if _starts_a_process_of_os(a.name)]
    return found


def _starts_a_process(path: Path) -> bool:
    imported = any(name.split(".")[0] in PROCESS for name in _imports(path))
    return imported or bool(_os_process_uses(path))


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
    starting = sorted(path.name for path in ROOT.glob("*.py") if _starts_a_process(path))
    assert starting == ["kernel.py"]


def test_no_module_starts_a_process_through_os() -> None:
    # The kernel's module starts its process through subprocess alone.
    for path in sorted(ROOT.glob("*.py")):
        assert _os_process_uses(path) == [], path.name


def test_the_rule_on_os_finds_a_process_started_through_os(tmp_path: Path) -> None:
    sample = tmp_path / "sample.py"
    sample.write_text(
        "import os\nfrom os import execv, getcwd\nos.system('true')\nos.popen('true')\n",
        encoding="utf-8",
    )
    assert sorted(_os_process_uses(sample)) == ["os.execv", "os.popen", "os.system"]
    assert _starts_a_process(sample)


def test_the_checker_imports_nothing_that_starts_a_process() -> None:
    checker = _imports(ROOT / "check.py")
    own = [name for name in checker if name.startswith("physgate.")]
    assert sorted(set(own)) == ["physgate.build.drawings.record", "physgate.build.drawings.sheet"]
    for name in ("record.py", "sheet.py", "check.py"):
        assert not _starts_a_process(ROOT / name), name
