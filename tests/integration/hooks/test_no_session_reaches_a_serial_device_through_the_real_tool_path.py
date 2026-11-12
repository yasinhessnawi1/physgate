"""Through the real binary: no session opens a serial device, or is let to start an upload.

A command or a file tool that names a serial device, and a command that uploads, are refused
by the hooks, with the OS layer or without it. A program that builds the device's name as it
runs names nothing the hooks can read: inside the OS layer the kernel refuses the open, to
read and to write, while the machine's other devices stay usable; without the layer the same
program opens the device, which shows the probe would see a reach.

The device is one of this machine's own, found by the patterns the OS layer denies, and one
the test's own user can open. A machine with none (a board is not plugged in, and nothing
stands in for one) has nothing to refuse, and the test says so by skipping. Nothing is ever
written to the device: it is opened and closed.
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


@pytest.fixture
def device() -> str:
    """A serial device of this machine that its user can open: the quietest one there is."""
    found = sorted(
        (path for pattern in board_devices(sys.platform) for path in glob.glob(pattern)),
        key=lambda path: ("debug" not in path and "ttyUSB" not in path, path),
    )
    for path in found:
        if _opens(path):
            return path
    pytest.skip(f"no serial device here that this user can open (found {found})")


@pytest.fixture
def layer() -> None:
    if not layer_here():
        pytest.skip("the OS layer cannot run here")


@pytest.fixture
def layout(tmp_path: Path) -> Iterator[Layout]:
    with make_layout(tmp_path) as made:
        yield made


def _built_open(device: str) -> dict[str, object]:
    """Open the device both ways by a name no text layer reads a path from."""
    program = (
        "import os\n"
        f"target = os.sep.join({device.split(os.sep)!r})\n"
        "for mode, name in ((os.O_RDONLY, 'READ'), (os.O_WRONLY, 'WRITE')):\n"
        "    try:\n"
        "        os.close(os.open(target, mode | os.O_NONBLOCK | os.O_NOCTTY))\n"
        "        print('DEVICE-' + name + '-OPENED')\n"
        "    except OSError as exc:\n"
        "        print('DEVICE-' + name + '-DENIED', exc.errno)\n"
    )
    return tool("Bash", command=python(program))


def _named(device: str) -> list[dict[str, object]]:
    # Each shell form only opens and closes the device, should it ever run.
    return [
        tool("Bash", command=f": < {device}"),
        tool("Bash", command=f": >> {device}"),
        tool("Read", file_path=device),
        tool("Bash", command="pio run -t upload"),
        tool("Bash", command=f"avrdude -p atmega32u4 -c avr109 -P {device}"),
    ]


def _said(done: dict[str, object]) -> list[str]:
    told = done["told"]
    assert isinstance(told, list)
    return [str(said) for said in told]


def _held_by_the_hooks(said: list[str]) -> None:
    read, written, by_tool, upload, flasher = said
    for refused in (read, written, by_tool, flasher):
        assert "Opening a board's device is refused" in refused
    assert "Uploading or flashing to hardware is refused" in upload


@pytest.mark.usefixtures("layer")
def test_inside_the_layer_no_open_reaches_the_device_and_other_devices_still_work(
    layout: Layout, device: str
) -> None:
    ordinary = tool("Bash", command="echo x > /dev/null && head -c 4 /dev/urandom | wc -c")
    done = run_session(layout, [*_named(device), _built_open(device), ordinary], layer=True)
    *named, built, others = _said(done)
    _held_by_the_hooks(named)
    assert "DEVICE-READ-DENIED" in built and "DEVICE-WRITE-DENIED" in built
    assert "OPENED" not in built
    assert "4" in others
    settings = done["settings"]
    assert isinstance(settings, dict)
    filesystem = settings["sandbox"]["filesystem"]
    for pattern in board_devices(sys.platform):
        assert pattern in filesystem["denyRead"] and pattern in filesystem["denyWrite"]


def test_without_the_layer_the_hooks_refuse_what_names_it_and_a_built_name_opens_it(
    layout: Layout, device: str
) -> None:
    done = run_session(layout, _named(device), layer=False)
    _held_by_the_hooks(_said(done))
    # The red control: the built name is an open no text layer sees, and it succeeds.
    done = run_session(layout, [_built_open(device)], layer=False)
    (built,) = _said(done)
    assert "DEVICE-READ-OPENED" in built
