"""Nothing in the operator UI's package writes a file: the one write is the queue's own.

A syntax-tree scan of every module under ``src/physgate/ui``. It is the third measure behind
"the UI writes only through the approval queue's decision function", beside the guard's fixed
write rule and its run-time caller check: a route that wrote the decisions file itself would
have to call one of the primitives below, and the scan finds it in the source before any test
runs it.

Two exceptions, each named with its reason:

- the build step's stamp writer (``assets.write_stamp``), which runs from the build script,
  never inside the server;
- the guard's import of the decisions file's name, which is the write rule's own constant.
"""

from __future__ import annotations

import ast
from pathlib import Path

import physgate.ui

#: The package scanned.
PACKAGE = Path(physgate.ui.__file__).resolve().parent

#: Calls on a path or a file object that create, change or remove a file.
WRITING_METHODS = frozenset(
    {
        "write_text",
        "write_bytes",
        "touch",
        "mkdir",
        "unlink",
        "rmdir",
        "rename",
        "symlink_to",
        "hardlink_to",
        "chmod",
        "truncate",
    }
)

#: Functions of ``os`` that create, change or remove a file, or write to a descriptor.
WRITING_OS = frozenset(
    {
        "write",
        "pwrite",
        "writev",
        "truncate",
        "ftruncate",
        "remove",
        "unlink",
        "rename",
        "replace",
        "mkdir",
        "makedirs",
        "rmdir",
        "removedirs",
        "symlink",
        "link",
        "chmod",
        "chown",
        "utime",
        "mkfifo",
    }
)

#: Flags that make an ``os.open`` more than a read.
WRITING_FLAGS = frozenset({"O_WRONLY", "O_RDWR", "O_CREAT", "O_APPEND", "O_TRUNC", "O_EXCL"})

#: Names whose import is a write path's: the queue's file names.
QUEUE_NAMES = frozenset({"DECISIONS_NAME", "QUEUE_NAME"})

#: (module, function or import) pairs allowed, each for the reason in the module docstring.
ALLOWED = frozenset({("assets.py", "write_stamp"), ("guard.py", "DECISIONS_NAME")})


def _mode(call: ast.Call, position: int = 1) -> str | None:
    """The literal mode of an open call, ``"r"`` when it has none, ``None`` if unknown.

    ``position`` is where the mode sits among the call's arguments: second for the built-in
    ``open``, first for a path's ``open`` method.
    """
    given = call.args[position] if len(call.args) > position else None
    for keyword in call.keywords:
        if keyword.arg == "mode":
            given = keyword.value
    if given is None:
        return "r"
    return given.value if isinstance(given, ast.Constant) and isinstance(given.value, str) else None


def _names(node: ast.AST) -> set[str]:
    return {n.attr for n in ast.walk(node) if isinstance(n, ast.Attribute)} | {
        n.id for n in ast.walk(node) if isinstance(n, ast.Name)
    }


def writes_in(source: str, module: str) -> list[str]:
    """Every write primitive in ``source``, as ``module:line: what``, less the allowed ones."""
    tree = ast.parse(source)
    found: list[str] = []
    enclosing: dict[ast.AST, str] = {}
    for fn in ast.walk(tree):
        if isinstance(fn, ast.FunctionDef | ast.AsyncFunctionDef):
            for inner in ast.walk(fn):
                enclosing.setdefault(inner, fn.name)

    def note(node: ast.AST, what: str, key: str | None = None) -> None:
        owner = key if key is not None else enclosing.get(node, "<module>")
        if (module, owner) not in ALLOWED:
            found.append(f"{module}:{getattr(node, 'lineno', 0)}: {what}")

    for node in ast.walk(tree):
        if isinstance(node, ast.ImportFrom):
            for alias in node.names:
                if alias.name in QUEUE_NAMES:
                    note(node, f"imports {alias.name}", key=alias.name)
        if not isinstance(node, ast.Call):
            continue
        func = node.func
        if isinstance(func, ast.Name) and func.id == "open":
            mode = _mode(node)
            if mode is None or set(mode) & set("wax+"):
                note(node, f"open with mode {mode!r}")
        elif isinstance(func, ast.Attribute):
            owner = func.value.id if isinstance(func.value, ast.Name) else None
            if owner == "os" and func.attr in WRITING_OS:
                note(node, f"os.{func.attr}")
            elif owner == "os" and func.attr == "open":
                flags = set().union(*(_names(arg) for arg in node.args[1:2]))
                if flags & WRITING_FLAGS or len(node.args) < 2:
                    note(node, "os.open for writing")
            elif owner == "shutil":
                note(node, f"shutil.{func.attr}")
            elif func.attr in WRITING_METHODS:
                note(node, f".{func.attr}()")
            elif func.attr == "open":
                mode = _mode(node, position=0)
                if mode is None or set(mode) & set("wax+"):
                    note(node, f".open with mode {mode!r}")
    return found


def test_the_ui_package_holds_no_write_but_the_two_named() -> None:
    modules = sorted(PACKAGE.glob("*.py"))
    assert len(modules) >= 9, "the scan found too few modules to mean anything"
    found = [w for path in modules for w in writes_in(path.read_text(), path.name)]
    assert found == []


def test_the_two_exceptions_are_really_there() -> None:
    """A stale exception would hide nothing today and anything tomorrow: each must still match."""
    assert "def write_stamp" in (PACKAGE / "assets.py").read_text()
    assert "DECISIONS_NAME" in (PACKAGE / "guard.py").read_text()


PLANTED = {
    "open(path, 'ab')": "open with mode 'ab'",
    "open(path, mode='w')": "open with mode 'w'",
    "open(path, mode)": "open with mode None",
    "path.open('a')": ".open with mode 'a'",
    "path.write_text('x')": ".write_text()",
    "path.write_bytes(b'x')": ".write_bytes()",
    "path.touch()": ".touch()",
    "path.mkdir()": ".mkdir()",
    "path.unlink()": ".unlink()",
    "handle.truncate(0)": ".truncate()",
    "os.write(fd, b'x')": "os.write",
    "os.ftruncate(fd, 0)": "os.ftruncate",
    "os.replace(a, b)": "os.replace",
    "os.open(name, os.O_WRONLY | os.O_APPEND, dir_fd=fd)": "os.open for writing",
    "os.open(name, os.O_RDONLY | os.O_CREAT)": "os.open for writing",
    "shutil.copyfile(a, b)": "shutil.copyfile",
}


def test_every_planted_write_is_found() -> None:
    for line, what in PLANTED.items():
        header = "import os, shutil\n\ndef route(path, fd, name, handle, a, b, mode):\n"
        source = f"{header}    {line}\n"
        assert writes_in(source, "readers.py") == [f"readers.py:4: {what}"], line


def test_a_planted_import_of_a_queue_file_name_is_found() -> None:
    for name in sorted(QUEUE_NAMES):
        source = f"from physgate.orchestrator.queue import {name}\n"
        assert writes_in(source, "routes.py") == [f"routes.py:1: imports {name}"]


def test_reads_are_not_writes() -> None:
    source = (
        "import os\n\n"
        "def route(path, fd, name):\n"
        "    open(path)\n"
        "    open(path, 'rb')\n"
        "    path.open('rb')\n"
        "    path.read_bytes()\n"
        "    os.open(name, os.O_RDONLY | os.O_NOFOLLOW, dir_fd=fd)\n"
    )
    assert writes_in(source, "readers.py") == []
