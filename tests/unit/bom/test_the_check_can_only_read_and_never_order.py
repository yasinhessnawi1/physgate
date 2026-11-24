"""The check can query and cannot order (ARCH-121), and it makes no network call.

Every function, class and method the package defines is listed, and none is named for placing an
order, a purchase or a cart; no module of the package imports a network library. A distributor
adapter, when there is one, is a separate decision and comes with its own rows.
"""

from __future__ import annotations

import ast
import importlib
import inspect
import pkgutil
from pathlib import Path

import physgate.build
import physgate.build.bom

ORDERING = ("order", "place", "purchase", "buy", "checkout", "cart", "submit", "reserve")
NETWORK = (
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
    "subprocess",
)


def _modules() -> list[str]:
    found = ["physgate.build", "physgate.build.bom"]
    found += [
        f"physgate.build.bom.{one.name}"
        for one in pkgutil.iter_modules(physgate.build.bom.__path__)
    ]
    return found


def _sources() -> list[Path]:
    # This package's own files and the build package's marker: the drawing package beside it
    # runs the tool environment's interpreter and has rows of its own.
    root = Path(physgate.build.__file__).parent
    return sorted([root / "__init__.py", *(root / "bom").rglob("*.py")])


def _defined_names() -> list[str]:
    names: list[str] = []
    for name in _modules():
        module = importlib.import_module(name)
        for held_name, held in vars(module).items():
            if getattr(held, "__module__", None) != name:
                continue
            if inspect.isfunction(held):
                names.append(held_name)
            elif inspect.isclass(held):
                names.append(held_name)
                names.extend(n for n, v in vars(held).items() if callable(v))
    return names


def test_the_package_s_modules_are_the_ones_listed() -> None:
    assert sorted(_modules()) == sorted(
        [
            "physgate.build",
            "physgate.build.bom",
            "physgate.build.bom.check",
            "physgate.build.bom.cli",
            "physgate.build.bom.sheet",
        ]
    )


def test_no_function_class_or_method_is_named_for_ordering() -> None:
    names = _defined_names()
    assert "check_line" in names and "load_sheet" in names  # the listing sees the surface
    for name in names:
        bare = name.lstrip("_").lower()
        assert not bare.startswith(ORDERING), name


def test_no_module_imports_a_network_library() -> None:
    sources = _sources()
    assert len(sources) == 5
    for path in sources:
        tree = ast.parse(path.read_text())
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                imported = [alias.name for alias in node.names]
            elif isinstance(node, ast.ImportFrom):
                imported = [node.module or ""]
            else:
                continue
            for name in imported:
                assert name.split(".")[0] not in NETWORK, (path.name, name)
