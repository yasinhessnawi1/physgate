"""A role session computes and builds with the tool environment offline, inside the OS layer.

A real session, through the real binary against the scripted endpoint, under the generated
settings with ``network: none``: its shell runs module scripts on the provisioned tool
environment's interpreter (python-control margins of a fixture loop, a MuJoCo pendulum stepped)
and builds the Balboa firmware with PlatformIO, its core directory in the session's temp and
linked into the environment's read-only store. In the same session git is refused, the
worktree's git directory cannot be written and the network cannot be reached, so what
succeeded needed none of them (that the build calls no git at all is shown with a stand-in git
by the provisioning test). With the layer off,
the same two probes reach, which shows they would see a reach. The environment measures the
same after the session as before: nothing the session ran wrote into it.

``PHYSGATE_TOOL_ENVIRONMENT`` names a provisioned environment (``toolenv/provision.py``).
"""

from __future__ import annotations

import json
import os
from collections.abc import Iterator
from pathlib import Path

import pytest
from fake_messages_api import tool
from os_layer_rig import Layout, layer_here, make_layout, python, run_session

from physgate.toolenv.manifest import scan

pytestmark = pytest.mark.integration

NAMED = os.environ.get("PHYSGATE_TOOL_ENVIRONMENT", "")

MARGINS = """
import json, control
gm, pm, sm, wpc, wgc, wms = control.stability_margins(control.tf([4, 4], [1, 2, 1, 0]))
print("MARGINS " + json.dumps({"phase_margin_deg": float(pm), "gain_crossover_rad_s": float(wgc)}))
"""
PENDULUM_SCRIPT = """
import json, mujoco
model = mujoco.MjModel.from_xml_path("pendulum.xml")
data = mujoco.MjData(model)
data.qpos[0] = 0.3
for _ in range(500):
    mujoco.mj_step(model, data)
print("MUJOCO " + json.dumps({"time_s": float(data.time), "angle_rad": float(data.qpos[0])}))
"""
PENDULUM = """<mujoco><worldbody><body pos="0 0 1"><joint type="hinge" axis="0 1 0"/>
<geom type="capsule" size=".05" fromto="0 0 0 0 0 -0.5" mass="1"/></body></worldbody></mujoco>
"""
FIRMWARE_INI = """[env:balboa]
platform = platformio/atmelavr@5.3.0
board = a-star32U4
framework = arduino
build_src_flags = -Wall -Wextra -Werror
"""
FIRMWARE_MAIN = """#include <Arduino.h>
#include <Balboa32U4.h>
Balboa32U4Motors motors;
Balboa32U4Encoders encoders;
void setup() { Serial.begin(115200); }
void loop() {
  int16_t l = encoders.getCountsLeft();
  motors.setSpeeds(l > 100 ? -50 : 50, 50);
  Serial.println(l);
  delay(10);
}
"""
GIT_PROBE = "git status --short >/dev/null 2>&1 && echo GIT-REACHED || echo GIT-REFUSED"


def _git_write(common: Path) -> str:
    """A shell command writing into the worktree's git directory by a path built at run time."""
    parts = [part for part in common.parts if part != "/"]
    return python(
        "import os\n"
        f"path = os.path.join(os.sep, *{parts!r}, 'probe-written')\n"
        "try:\n"
        "    open(path, 'w').write('x')\n"
        "    print('GITDIR-WRITTEN')\n"
        "except OSError:\n"
        "    print('GITDIR-DENIED')"
    )


NET_PROBE = (
    "python3 -c 'import socket; socket.create_connection((\"1.1.1.1\", 443), timeout=5)' "
    ">/dev/null 2>&1 && echo NET-REACHED || echo NET-REFUSED"
)


@pytest.fixture
def env() -> Path:
    if not NAMED:
        pytest.skip("no provisioned tool environment named")
    if not layer_here():
        pytest.skip("the OS layer cannot run here")
    return Path(NAMED)


@pytest.fixture
def layout(tmp_path: Path) -> Iterator[Layout]:
    with make_layout(tmp_path) as made:
        control, firmware = (
            made.worktree / "modules" / "control",
            made.worktree / "modules" / "firmware",
        )
        (firmware / "src").mkdir(parents=True)
        control.mkdir(parents=True)
        (control / "margins.py").write_text(MARGINS)
        (control / "pendulum.py").write_text(PENDULUM_SCRIPT)
        (control / "pendulum.xml").write_text(PENDULUM)
        (firmware / "platformio.ini").write_text(FIRMWARE_INI)
        (firmware / "src" / "main.cpp").write_text(FIRMWARE_MAIN)
        yield made


def _steps(env: Path, temp: Path, layout: Layout) -> list[dict[str, object]]:
    interpreter = env / "venv" / "bin" / "python"
    modules = layout.worktree / "modules"
    quiet = f"MPLBACKEND=Agg MPLCONFIGDIR={temp}/mpl"
    core = temp / "pio-core"
    links = " && ".join(
        f"ln -s {env}/platformio/{name} {core}/{name}" for name in ("platforms", "packages", "lib")
    )
    pio = (
        f"PLATFORMIO_CORE_DIR={core} PLATFORMIO_BUILD_DIR={temp}/pio-build "
        f"PLATFORMIO_WORKSPACE_DIR={temp}/pio-workspace PLATFORMIO_CACHE_DIR={temp}/pio-cache "
        "PLATFORMIO_SETTING_ENABLE_TELEMETRY=no PLATFORMIO_SETTING_CHECK_PLATFORMIO_INTERVAL=36500 "
        f"{env}/venv/bin/pio run"
    )
    return [
        tool("Bash", command=f"cd {modules}/control && {quiet} {interpreter} -I margins.py"),
        tool("Bash", command=f"cd {modules}/control && {quiet} {interpreter} -I pendulum.py"),
        tool(
            "Bash",
            command=f"mkdir -p {core} && {links} && cd {modules}/firmware && {pio} 2>&1 | tail -4",
        ),
        tool("Bash", command=GIT_PROBE),
        tool("Bash", command=_git_write(layout.common)),
        tool("Bash", command=NET_PROBE),
    ]


def _line(said: str, tag: str) -> dict[str, float]:
    line = next(line for line in said.splitlines() if line.startswith(tag + " "))
    found = json.loads(line[len(tag) + 1 :])
    assert isinstance(found, dict)
    return found


def test_a_session_computes_and_builds_offline_with_git_and_the_network_refused(
    env: Path, layout: Layout
) -> None:
    before = scan([env])
    steps = _steps(env, layout.temp.resolve(), layout)
    done = run_session(layout, steps, layer=True, network="none", timeout=600)
    margins, simulated, built, git, gitdir, net = done["told"]  # type: ignore[misc]
    assert _line(margins, "MARGINS")["phase_margin_deg"] == pytest.approx(28.0202, abs=1e-3)
    assert _line(simulated, "MUJOCO")["time_s"] == pytest.approx(1.0)
    assert "used 4798 bytes from 28672 bytes" in built and "used 173 bytes from 2560 bytes" in built
    assert "[SUCCESS]" in built
    assert "does not run git" in git
    assert "GITDIR-DENIED" in gitdir
    assert not (layout.common / "probe-written").exists()
    assert "NET-REFUSED" in net
    firmware = layout.worktree / "modules" / "firmware"
    assert not (firmware / ".pio").exists()
    built_out = [p for p in layout.worktree.rglob("*") if p.suffix in (".elf", ".hex", ".o")]
    assert built_out == []
    assert (layout.temp / "pio-build" / "balboa" / "firmware.elf").is_file()
    settings = done["settings"]
    assert isinstance(settings, dict) and settings["sandbox"]["enabled"] is True
    assert scan([env]) == before


def test_with_the_layer_off_the_git_directory_and_the_network_are_reached(
    env: Path, layout: Layout
) -> None:
    probes = [tool("Bash", command=_git_write(layout.common)), tool("Bash", command=NET_PROBE)]
    done = run_session(layout, probes, layer=False)
    gitdir, net = done["told"]  # type: ignore[misc]
    assert "GITDIR-WRITTEN" in gitdir
    # The hooks' after-command sentinel may already have taken the write back out.
    (layout.common / "probe-written").unlink(missing_ok=True)
    assert "NET-REACHED" in net
