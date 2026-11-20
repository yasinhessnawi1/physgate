"""Through the real binary: a session reads and runs the tool environment and writes none of it.

The environment's roots reach the session as the dispatcher gives them to the installer. A file
tool's write into one and a command that names one are refused by the hooks, with the OS layer
or without it. A command that builds the path as it runs names nothing the hooks can read:
inside the OS layer the write is refused by the kernel, and the environment scans as it did
before the session; without the layer the same command writes the file, which shows the command
works, and the scan every session is held to then differs, so the next session is refused.
Reading a library file and running a program of the environment succeed inside the layer.
"""

from __future__ import annotations

import os
from collections.abc import Iterator
from pathlib import Path

import pytest
from fake_messages_api import tool
from os_layer_rig import Layout, layer_here, make_layout, python, run_session

from physgate.toolenv.exceptions import ToolEnvironmentError
from physgate.toolenv.manifest import scan
from physgate.toolenv.record import ToolEnvironment, require_unchanged

pytestmark = pytest.mark.integration

LIBRARY = "def margin(): return 1\n"


@pytest.fixture
def layer() -> None:
    if not layer_here():
        pytest.skip("the OS layer cannot run here")


@pytest.fixture
def layout(tmp_path: Path) -> Iterator[Layout]:
    with make_layout(tmp_path) as made:
        yield made


@pytest.fixture
def environment(layout: Layout) -> Path:
    root = Path(os.path.realpath(layout.root)) / "tools" / "env"
    (root / "bin").mkdir(parents=True)
    (root / "lib").mkdir()
    (root / "lib" / "margins.py").write_text(LIBRARY)
    program = root / "bin" / "report"
    program.write_text("#!/bin/sh\necho TOOL-RAN\n")
    program.chmod(0o755)
    return root


def _recorded(root: Path) -> ToolEnvironment:
    """A record naming ``root``; only its roots and programs matter to the scan's check."""
    return ToolEnvironment(
        interpreter=str(root / "bin" / "report"),
        resolved=str(root / "bin" / "report"),
        python_version="3.12.9",
        prefix=str(root),
        distributions=(),
        native_tools=(),
        roots=(str(root),),
        manifest_digest="0" * 64,
        entries=1,
        total_bytes=0,
    )


def _parts(path: Path) -> str:
    """``path`` as an expression no text layer reads a path from."""
    return "os.sep.join(" + repr(str(path).split(os.sep)) + ")"


def _built_write(root: Path) -> dict[str, object]:
    program = (
        "import os\n"
        f"target = {_parts(root / 'lib' / 'margins.py')}\n"
        "try:\n"
        "    open(target, 'w').write('def margin(): return 2\\n')\n"
        "    print('ENV-WRITTEN')\n"
        "except OSError as exc:\n"
        "    print('ENV-DENIED', exc.errno)\n"
    )
    return tool("Bash", command=python(program))


def _built_add(root: Path) -> dict[str, object]:
    program = (
        "import os\n"
        f"target = {_parts(root / 'lib' / 'sitecustomize.py')}\n"
        "try:\n"
        "    open(target, 'w').write('import os\\n')\n"
        "    print('ENV-ADDED')\n"
        "except OSError as exc:\n"
        "    print('ENV-DENIED', exc.errno)\n"
    )
    return tool("Bash", command=python(program))


def _read_and_run(root: Path) -> dict[str, object]:
    program = (
        "import os, subprocess\n"
        f"print(open({_parts(root / 'lib' / 'margins.py')}).read().strip())\n"
        f"print(subprocess.run([{_parts(root / 'bin' / 'report')}], capture_output=True,"
        " text=True).stdout.strip())\n"
    )
    return tool("Bash", command=python(program))


def _said(done: dict[str, object]) -> list[str]:
    told = done["told"]
    assert isinstance(told, list)
    return [str(said) for said in told]


@pytest.mark.usefixtures("layer")
def test_inside_the_layer_it_is_read_and_run_and_no_write_reaches_it(
    layout: Layout, environment: Path
) -> None:
    before = scan([environment])
    library = environment / "lib" / "margins.py"
    steps = [
        _read_and_run(environment),
        _built_write(environment),
        _built_add(environment),
        # A new file: the binary itself turns down a write over a file the session has not
        # read, before any hook is asked.
        tool("Write", file_path=str(library.with_name("by_tool.py")), content="x = 3\n"),
        tool("Bash", command=f"echo 'def margin(): return 4' > {library}"),
        tool("Bash", command=f"cat {library}"),
    ]
    done = run_session(layout, steps, layer=True, tool_environment=(str(environment),))
    used, written, added, by_tool, by_name, read = _said(done)
    assert "def margin(): return 1" in used and "TOOL-RAN" in used
    assert "ENV-DENIED" in written and "ENV-WRITTEN" not in written
    assert "ENV-DENIED" in added and "ENV-ADDED" not in added
    assert "recorded tool environment" in by_tool
    assert "recorded tool environment" in by_name
    assert "def margin(): return 1" in read
    assert library.read_text() == LIBRARY
    assert sorted(p.name for p in library.parent.iterdir()) == ["margins.py"]
    assert scan([environment]) == before
    require_unchanged(_recorded(environment), before)
    settings = done["settings"]
    assert isinstance(settings, dict)
    filesystem = settings["sandbox"]["filesystem"]
    assert str(environment) in filesystem["denyWrite"]
    assert not [p for p in filesystem["denyRead"] if p.startswith(str(environment))]


def test_without_the_layer_the_hooks_refuse_what_names_it_and_the_scan_sees_what_does_not(
    layout: Layout, environment: Path
) -> None:
    before = scan([environment])
    library = environment / "lib" / "margins.py"
    named = [
        # A new file: the binary itself turns down a write over a file the session has not
        # read, before any hook is asked.
        tool("Write", file_path=str(library.with_name("by_tool.py")), content="x = 3\n"),
        tool("Bash", command=f"echo 'def margin(): return 4' > {library}"),
        tool("Bash", command=f"cp README.md {environment}/lib/extra.py"),
    ]
    done = run_session(layout, named, layer=False, tool_environment=(str(environment),))
    for said in _said(done):
        assert "recorded tool environment" in said
    assert library.read_text() == LIBRARY
    assert sorted(p.name for p in library.parent.iterdir()) == ["margins.py"]
    assert scan([environment]) == before
    require_unchanged(_recorded(environment), before)
    # The red control: the built path is a write no text layer sees, and it lands.
    done = run_session(
        layout, [_built_write(environment)], layer=False, tool_environment=(str(environment),)
    )
    (written,) = _said(done)
    assert "ENV-WRITTEN" in written
    assert library.read_text() != LIBRARY
    # What holds then: the next session is refused, because an entry changed.
    with pytest.raises(ToolEnvironmentError, match="changed since the run started"):
        require_unchanged(_recorded(environment), before)
