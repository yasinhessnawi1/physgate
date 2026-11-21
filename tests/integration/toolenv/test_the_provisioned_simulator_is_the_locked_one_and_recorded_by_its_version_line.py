"""The provisioned simulator is the locked one, found by name and recorded by its version line.

A run records ``avrsim`` as a native tool of the environment: its path inside the roots, where it
leads, and its own version line, asked from an empty environment at the filesystem root. A
session finds it by name through the link its wiring makes. What runs is the environment's own:
avr8js exactly as the lock names it, nothing beside it, the rig's files byte for byte the
checkout's, and the self-check's known answers recorded at provisioning.
"""

from __future__ import annotations

import importlib.util
import json
import subprocess
import sys
from pathlib import Path
from types import ModuleType

import pytest
from avrsim_rig import EMPTY, avrsim, environment

from physgate.toolenv.record import measure
from physgate.toolenv.session import wire

pytestmark = pytest.mark.integration

REPO = Path(__file__).resolve().parents[3]
VERSION = "avrsim 0.4.0 avr8js 0.21.1 node 24.22.1"


def _provision() -> ModuleType:
    spec = importlib.util.spec_from_file_location(
        "toolenv_provision", REPO / "toolenv" / "provision.py"
    )
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def test_avr8js_is_installed_exactly_as_locked_and_nothing_beside_it() -> None:
    env = environment()
    lock = json.loads(
        (REPO / "toolenv" / "avrsim" / "package-lock.json").read_text(encoding="utf-8")
    )
    installed = json.loads(
        (env / "avrsim" / "node_modules" / ".package-lock.json").read_text(encoding="utf-8")
    )
    assert installed["packages"] == {
        name: entry for name, entry in lock["packages"].items() if name
    }
    package = json.loads(
        (env / "avrsim" / "node_modules" / "avr8js" / "package.json").read_text(encoding="utf-8")
    )
    assert (package["name"], package["version"], package["license"]) == ("avr8js", "0.21.1", "MIT")
    assert sorted(path.name for path in (env / "avrsim" / "node_modules").iterdir()) == [
        ".package-lock.json",
        "avr8js",
    ]
    for name in _provision().avrsim_files():
        assert (env / "avrsim" / name).read_bytes() == (
            REPO / "toolenv" / "avrsim" / name
        ).read_bytes(), name


def test_a_run_records_the_simulator_by_its_own_version_line() -> None:
    env = environment()
    recorded = measure(
        str(env / "venv" / "bin" / "python"),
        [str(env)],
        native={"avrsim": str(avrsim(env))},
        forbidden={"the harness checkout": REPO},
    )
    (tool,) = recorded.native_tools
    assert (tool.name, tool.path, tool.resolved) == (
        "avrsim",
        str(avrsim(env)),
        str(avrsim(env).resolve()),
    )
    assert tool.version == VERSION


def test_provisioning_recorded_the_known_answers_and_what_the_simulator_was_built_from() -> None:
    env = environment()
    written = json.loads((env / "provisioned.json").read_text(encoding="utf-8"))
    simulated = written["self_check"]["avrsim"]
    assert simulated["version"] == VERSION
    assert simulated["oc1a_frequency_hz"] == pytest.approx(20_000, rel=0.01)
    assert simulated["encoder_counts"] == {"left": 30, "right": -15}
    assert (simulated["who_am_i"], simulated["ctrl2_g"], simulated["icr1"]) == ("69", "58", 400)
    for name in _provision().built_from():
        assert name in written["locks_sha256"], name


def test_a_session_wired_to_the_environment_finds_the_simulator_by_name(tmp_path: Path) -> None:
    env = environment()
    recorded = measure(
        str(env / "venv" / "bin" / "python"),
        [str(env)],
        native={},
        forbidden={"the harness checkout": REPO},
    )
    temp = tmp_path / "temp"
    temp.mkdir()
    wire(recorded, bin_dir=tmp_path / "bin", temp=temp, taken=set())
    assert (tmp_path / "bin" / "avrsim").resolve() == avrsim(env).resolve()
    done = subprocess.run(
        ["avrsim", "--version"],
        cwd="/", env={**EMPTY, "PATH": f"{tmp_path / 'bin'}:/usr/bin:/bin"},
        capture_output=True, text=True, timeout=60, check=False,
    )  # fmt: skip
    assert done.returncode == 0, done.stderr
    assert done.stdout.strip() == VERSION
