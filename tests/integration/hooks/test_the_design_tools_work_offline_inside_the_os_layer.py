"""A role session builds, exports, measures and hashes a chassis offline, inside the OS layer.

A real session, through the real binary against the scripted endpoint, under the generated
settings with ``network: none``: its shell runs the chassis part script of ``design_fixtures``
on the provisioned tool environment's interpreter, with the helpers as provisioned. The script
builds three parts with the CAD kernel, exports each as STEP and STL into the module's exports
folder, and writes each part's mass properties and geometry hash, the interference and
clearance of two of them, and two closed-form load cases as result files beside itself. In
the same session git is refused, the worktree's git directory cannot be written and the
network cannot be reached, so what succeeded needed none of them; with the layer off the same
two probes reach. The environment measures the same after the session as before.

``PHYSGATE_TOOL_ENVIRONMENT`` names a provisioned environment (``toolenv/provision.py``).
"""

from __future__ import annotations

import hashlib
import json
import os
from collections.abc import Iterator
from pathlib import Path

import pytest
from design_fixtures import CHASSIS, DENSITY_KG_M3, GEOMETRY_HASH, PUSHED_IN_MM3, VOLUME_MM3
from fake_messages_api import tool
from os_layer_rig import Layout, layer_here, make_layout, python, run_session

from physgate.toolenv.manifest import scan

pytestmark = pytest.mark.integration

NAMED = os.environ.get("PHYSGATE_TOOL_ENVIRONMENT", "")
PARTS = ("plate", "motor_mount", "battery_holder")
GIT_PROBE = "git status --short >/dev/null 2>&1 && echo GIT-REACHED || echo GIT-REFUSED"
NET_PROBE = (
    "python3 -c 'import socket; socket.create_connection((\"1.1.1.1\", 443), timeout=5)' "
    ">/dev/null 2>&1 && echo NET-REACHED || echo NET-REFUSED"
)


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
        module = made.worktree / "modules" / "chassis"
        module.mkdir(parents=True)
        (module / "chassis.py").write_text(CHASSIS, encoding="utf-8")
        yield made


def test_a_session_builds_exports_and_measures_a_chassis_with_git_and_the_network_refused(
    env: Path, layout: Layout
) -> None:
    before = scan([env])
    temp = layout.temp.resolve()
    module = layout.worktree / "modules" / "chassis"
    # First-use caches of the libraries go to the session's own temporary directory.
    quiet = f"MPLBACKEND=Agg MPLCONFIGDIR={temp}/mpl XDG_CACHE_HOME={temp}/cache"
    script = f"{env}/venv/bin/python -I chassis.py {env}/helpers"
    steps = [
        tool("Bash", command=f"cd {module} && {quiet} {script} | cut -c1-200"),
        tool("Bash", command=GIT_PROBE),
        tool("Bash", command=_git_write(layout.common)),
        tool("Bash", command=NET_PROBE),
    ]
    done = run_session(layout, steps, layer=True, network="none", timeout=900)
    told = done["told"]
    assert isinstance(told, list)
    built, git, gitdir, net = (str(said) for said in told)
    assert "CHASSIS {" in built, built[-2000:]
    for name in PARTS:
        result = json.loads((module / f"{name}.result.json").read_text(encoding="utf-8"))
        assert result["geometry_hash"] == GEOMETRY_HASH[name], name
        volume = VOLUME_MM3[name] * 1e-9
        assert result["values"]["volume"]["value"] == pytest.approx(volume, rel=1e-12)
        assert result["values"]["mass"] == {
            "value": pytest.approx(volume * DENSITY_KG_M3, rel=1e-12),
            "unit": "kg",
        }
        for entry in result["exports"]:
            path = module / entry["file"]
            assert path.parent == module / "exports"
            assert entry["sha256"] == hashlib.sha256(path.read_bytes()).hexdigest()
            assert entry["size"]["value"] == path.stat().st_size > 1000
    pushed = json.loads((module / "plate-motor_mount-pushed-in.result.json").read_text())
    assert pushed["values"]["interference_volume"]["value"] == pytest.approx(
        PUSHED_IN_MM3 * 1e-9, rel=1e-9
    )
    lifted = json.loads((module / "plate-motor_mount-lifted.result.json").read_text())
    assert lifted["values"]["clearance"]["value"] == pytest.approx(2.5e-3, rel=1e-9)
    arm = json.loads((module / "mount-arm.result.json").read_text())
    assert arm["values"]["tip_deflection"]["value"] == pytest.approx(
        1.3913043478260868e-3, rel=1e-12
    )
    assert "does not run git" in git
    assert "GITDIR-DENIED" in gitdir
    assert not (layout.common / "probe-written").exists()
    assert "NET-REFUSED" in net
    # Nothing was written in the worktree but the module's results and exports.
    files = sorted(p.name for p in module.rglob("*") if p.is_file())
    assert len(files) == 1 + 8 + 6, files
    others = [
        p
        for p in layout.worktree.rglob("*")
        if p.is_file() and module not in p.parents and ".git" not in p.parts
    ]
    assert [p.name for p in others] == ["README.md"]
    settings = done["settings"]
    assert isinstance(settings, dict) and settings["sandbox"]["enabled"] is True
    assert scan([env]) == before


def test_with_the_layer_off_the_git_directory_and_the_network_are_reached(
    env: Path, layout: Layout
) -> None:
    probes = [tool("Bash", command=_git_write(layout.common)), tool("Bash", command=NET_PROBE)]
    done = run_session(layout, probes, layer=False)
    told = done["told"]
    assert isinstance(told, list)
    gitdir, net = (str(said) for said in told)
    assert "GITDIR-WRITTEN" in gitdir
    # The hooks' after-command sentinel may already have taken the write back out.
    (layout.common / "probe-written").unlink(missing_ok=True)
    assert "NET-REACHED" in net
