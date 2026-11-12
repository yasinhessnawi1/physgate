"""A plain build whose own project file starts a flash finds no device inside the OS layer.

A session writes its project file, and a project file can name a script the build runs. The
command is then a plain build by every word of it, so the hooks let it run: no reading of a
command's words can tell what the files it builds from will do. What stops the flash is the OS
layer's denial of the device. Here the build tool of the provisioned tool environment runs a
real build in a real session, the project's script opens a board's device to write by a name
it builds as it runs, and the open is refused; the same script run without the layer opens
the device, which shows it would have reached.

``PHYSGATE_TOOL_ENVIRONMENT`` names a provisioned environment (``toolenv/provision.py``). The
device is one of this machine's own that its user can open, or a stand-in for one. Nothing is
written to it: it is opened and closed.
"""

from __future__ import annotations

import glob
import os
import sys
from collections.abc import Iterator
from pathlib import Path

import pytest
from fake_messages_api import tool
from os_layer_rig import Layout, layer_here, make_layout, run_session

from physgate.oslayer.policy import board_devices

pytestmark = pytest.mark.integration

NAMED = os.environ.get("PHYSGATE_TOOL_ENVIRONMENT", "")

PROJECT = """[env:balboa]
platform = platformio/atmelavr@5.3.0
board = a-star32U4
framework = arduino
extra_scripts = pre:flash.py
"""
MAIN = """#include <Arduino.h>
void setup() {}
void loop() {}
"""


def _flash(device: str) -> str:
    """A build script that opens the device to write, by a name no text layer reads."""
    return (
        "import os\n"
        f"target = os.sep.join({device.split(os.sep)!r})\n"
        "try:\n"
        "    os.close(os.open(target, os.O_WRONLY | os.O_NONBLOCK | os.O_NOCTTY))\n"
        "    print('FLASH-OPENED')\n"
        "except OSError as exc:\n"
        "    print('FLASH-DENIED', exc.errno)\n"
    )


def _opens_to_write(path: str) -> bool:
    try:
        os.close(os.open(path, os.O_WRONLY | os.O_NONBLOCK | os.O_NOCTTY))
    except OSError:
        return False
    return True


@pytest.fixture
def device() -> str:
    found = sorted(
        path
        for pattern in board_devices(sys.platform)
        for path in glob.glob(pattern)
        if not os.path.isdir(path)
    )
    for path in sorted(found, key=lambda path: ("debug" not in path, path)):
        if _opens_to_write(path):
            return path
    pytest.skip(f"no board's device here that this user can open to write (found {found})")


@pytest.fixture
def layout(tmp_path: Path, device: str) -> Iterator[Layout]:
    with make_layout(tmp_path) as made:
        firmware = made.worktree / "modules" / "firmware"
        (firmware / "src").mkdir(parents=True)
        (firmware / "platformio.ini").write_text(PROJECT)
        (firmware / "src" / "main.cpp").write_text(MAIN)
        (firmware / "flash.py").write_text(_flash(device))
        yield made


def _said(done: dict[str, object]) -> list[str]:
    told = done["told"]
    assert isinstance(told, list)
    return [str(said) for said in told]


def test_the_build_s_own_script_is_refused_the_device_by_the_os_layer(layout: Layout) -> None:
    if not NAMED:
        pytest.skip("no provisioned tool environment named")
    if not layer_here():
        pytest.skip("the OS layer cannot run here")
    env, temp = Path(NAMED), layout.temp.resolve()
    core = temp / "pio-core"
    links = " && ".join(
        f"ln -s {env}/platformio/{name} {core}/{name}" for name in ("platforms", "packages", "lib")
    )
    build = (
        f"PLATFORMIO_CORE_DIR={core} PLATFORMIO_BUILD_DIR={temp}/pio-build "
        f"PLATFORMIO_WORKSPACE_DIR={temp}/pio-workspace PLATFORMIO_CACHE_DIR={temp}/pio-cache "
        "PLATFORMIO_SETTING_ENABLE_TELEMETRY=no PLATFORMIO_SETTING_CHECK_PLATFORMIO_INTERVAL=36500 "
        f"{env}/venv/bin/pio run"
    )
    firmware = layout.worktree / "modules" / "firmware"
    command = f"mkdir -p {core} && {links} && cd {firmware} && {build} 2>&1 | tail -40"
    done = run_session(
        layout, [tool("Bash", command=command)], layer=True, network="none", timeout=600
    )
    (built,) = _said(done)
    # The build ran, as a plain build: the hooks refused nothing, and its script was run.
    assert "is refused" not in built
    assert "FLASH-DENIED" in built, built
    assert "FLASH-OPENED" not in built
    assert "[SUCCESS]" in built


def test_without_the_layer_the_same_script_opens_the_device(layout: Layout) -> None:
    script = layout.worktree / "modules" / "firmware" / "flash.py"
    done = run_session(layout, [tool("Bash", command=f"python3 {script}")], layer=False)
    (ran,) = _said(done)
    assert "FLASH-OPENED" in ran
