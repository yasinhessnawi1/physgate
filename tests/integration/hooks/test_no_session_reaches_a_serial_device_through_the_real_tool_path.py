"""Through the real binary: no session opens a board's device, or is let to start an upload.

A command or a file tool that names such a device, and a command that uploads, are refused by
the hooks, with the OS layer or without it. A program that builds the device's name as it
runs names nothing the hooks can read: inside the OS layer the kernel refuses the open, to
read and to write, while the machine's other devices stay usable; without the layer the same
program opens the device, which shows the probe would see a reach.

The devices are this machine's own, one for each pattern the OS layer denies on this
platform, each one the test's own user can open. A machine that lacks one for some pattern (no
board is plugged in, and nothing stands in for one) cannot show that pattern holding, and the
test says so by skipping. Nothing is ever written to a device: it is opened and closed.
"""

from __future__ import annotations

import glob
import os
import sys
from collections.abc import Iterator
from pathlib import Path

import pytest
from fake_messages_api import tool
from os_layer_rig import Layout, layer_here, make_layout, python, run_session

from physgate.oslayer.policy import board_devices

pytestmark = pytest.mark.integration

FLAGS = os.O_NONBLOCK | os.O_NOCTTY


def _opens(path: str) -> bool:
    try:
        os.close(os.open(path, os.O_RDONLY | FLAGS))
    except OSError:
        return False
    return True


def _nodes(pattern: str) -> list[str]:
    """Every node a pattern names: what it matches, and what lies beneath a directory it names."""
    found: list[str] = []
    for path in sorted(glob.glob(pattern)):
        if os.path.isdir(path):
            found += sorted(os.path.join(d, f) for d, _, files in os.walk(path) for f in files)
        else:
            found.append(path)
    # The quietest first: a debug console before a radio's port.
    return sorted(found, key=lambda path: ("debug" not in path, path))


@pytest.fixture
def devices() -> list[str]:
    """One device this user can open for each pattern the OS layer denies here."""
    chosen = []
    for pattern in board_devices(sys.platform):
        openable = [path for path in _nodes(pattern) if _opens(path)]
        if not openable:
            pytest.skip(f"no device here for {pattern} that this user can open")
        chosen.append(openable[0])
    assert chosen, "no pattern is denied on this platform"
    return chosen


@pytest.fixture
def layer() -> None:
    if not layer_here():
        pytest.skip("the OS layer cannot run here")


@pytest.fixture
def layout(tmp_path: Path) -> Iterator[Layout]:
    with make_layout(tmp_path) as made:
        yield made


def _built_open(devices: list[str]) -> dict[str, object]:
    """Open each device both ways by a name no text layer reads a path from."""
    program = (
        "import os\n"
        f"for parts in {[device.split(os.sep) for device in devices]!r}:\n"
        "    target = os.sep.join(parts)\n"
        "    for mode, name in ((os.O_RDONLY, 'READ'), (os.O_WRONLY, 'WRITE')):\n"
        "        try:\n"
        "            os.close(os.open(target, mode | os.O_NONBLOCK | os.O_NOCTTY))\n"
        "            print('BOARD-' + name + '-OPENED', parts[-1])\n"
        "        except OSError as exc:\n"
        "            print('BOARD-' + name + '-DENIED', parts[-1], exc.errno)\n"
    )
    return tool("Bash", command=python(program))


def _named(device: str) -> list[dict[str, object]]:
    # Each shell form only opens and closes the device, should it ever run.
    return [
        tool("Bash", command=f": < {device}"),
        tool("Bash", command=f": >> {device}"),
        tool("Read", file_path=device),
        tool("Bash", command=f"cd / && : < {device.lstrip(os.sep)}"),
        tool("Bash", command=f"avrdude -p atmega32u4 -c avr109 -P {device}"),
        tool("Bash", command="pio run -t upload"),
        tool("Bash", command="pio test"),
        tool("Bash", command="openocd -f board.cfg"),
    ]


def _said(done: dict[str, object]) -> list[str]:
    told = done["told"]
    assert isinstance(told, list)
    return [str(said) for said in told]


def _held_by_the_hooks(said: list[str]) -> None:
    read, written, by_tool, relative, flasher, upload, on_target, probe = said
    for refused in (read, written, by_tool, relative, flasher):
        assert "Opening a board's device is refused" in refused
    assert "Uploading or flashing to hardware is refused" in upload
    assert "Uploading or flashing to hardware is refused" in probe
    assert "This use of pio is refused" in on_target


@pytest.mark.usefixtures("layer")
def test_inside_the_layer_no_open_reaches_a_device_and_other_devices_still_work(
    layout: Layout, devices: list[str]
) -> None:
    ordinary = tool("Bash", command="echo x > /dev/null && head -c 4 /dev/urandom | wc -c")
    steps = [*_named(devices[0]), _built_open(devices), ordinary]
    done = run_session(layout, steps, layer=True)
    *named, built, others = _said(done)
    _held_by_the_hooks(named)
    for device in devices:
        name = os.path.basename(device)
        assert f"BOARD-READ-DENIED {name}" in built and f"BOARD-WRITE-DENIED {name}" in built
    assert "OPENED" not in built
    assert "4" in others
    settings = done["settings"]
    assert isinstance(settings, dict)
    filesystem = settings["sandbox"]["filesystem"]
    for pattern in board_devices(sys.platform):
        assert pattern in filesystem["denyRead"] and pattern in filesystem["denyWrite"]


def test_without_the_layer_the_hooks_refuse_what_names_one_and_a_built_name_opens_each(
    layout: Layout, devices: list[str]
) -> None:
    done = run_session(layout, _named(devices[0]), layer=False)
    _held_by_the_hooks(_said(done))
    # The red control: the built name is an open no text layer sees, and it succeeds.
    done = run_session(layout, [_built_open(devices)], layer=False)
    (built,) = _said(done)
    for device in devices:
        assert f"BOARD-READ-OPENED {os.path.basename(device)}" in built
