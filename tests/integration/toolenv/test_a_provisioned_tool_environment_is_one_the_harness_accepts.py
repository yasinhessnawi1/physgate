"""Provisioning builds a tool environment the harness measures and accepts, or leaves nothing.

These tests fetch the environment's pinned downloads, so they need the network, once per cache;
naming a kept download cache in ``PHYSGATE_TOOLENV_CACHE`` saves the fetch. Provisioning is
the only time the environment meets the network: once built, it is checked here offline, by
using it and finding it unchanged.
"""

from __future__ import annotations

import copy
import importlib.util
import json
import os
import stat
import subprocess
import sys
from collections.abc import Iterator
from pathlib import Path
from types import ModuleType

import pytest

from physgate.toolenv.manifest import scan
from physgate.toolenv.record import ToolEnvironment, measure

pytestmark = pytest.mark.integration

REPO = Path(__file__).resolve().parents[3]
PINNED = {
    "control": "0.10.1",
    "numpy": "2.1.2",
    "scipy": "1.14.1",
    "mujoco": "3.17.0",
    "platformio": "6.2.0",
}


def _provision() -> ModuleType:
    spec = importlib.util.spec_from_file_location(
        "toolenv_provision", REPO / "toolenv" / "provision.py"
    )
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def _cache(tmp_path_factory: pytest.TempPathFactory) -> Path:
    named = os.environ.get("PHYSGATE_TOOLENV_CACHE")
    return Path(named) if named else tmp_path_factory.mktemp("toolenv-cache")


def _writable(root: Path) -> None:
    for directory, dirs, _ in os.walk(root):
        for name in [".", *dirs]:
            path = Path(directory, name)
            if not path.is_symlink():
                path.chmod(0o755)


def _native(env: Path) -> dict[str, str]:
    return {
        "avr-gcc": str(env / "platformio" / "packages" / "toolchain-atmelavr" / "bin" / "avr-gcc"),
        "node": str(env / "node" / "bin" / "node"),
    }


@pytest.fixture(scope="module")
def provisioned(
    tmp_path_factory: pytest.TempPathFactory,
) -> Iterator[tuple[Path, dict[str, object]]]:
    env = tmp_path_factory.mktemp("built") / "env"
    record = _provision().provision(env, _cache(tmp_path_factory))
    yield env, record
    _writable(env)


def _measured(env: Path) -> ToolEnvironment:
    return measure(
        str(env / "venv" / "bin" / "python"),
        [str(env)],
        native=_native(env),
        forbidden={"the harness checkout": REPO},
    )


def test_the_harness_measures_the_environment_at_its_pins(
    provisioned: tuple[Path, dict[str, object]],
) -> None:
    env, _ = provisioned
    measured = _measured(env)
    assert measured.python_version == "3.12.9"
    assert Path(measured.resolved).is_relative_to(env / "python")
    versions = {d.name: d.version for d in measured.distributions}
    assert {name: versions.get(name) for name in PINNED} == PINNED
    tools = {tool.name: tool.version for tool in measured.native_tools}
    assert tools["node"] == "v24.22.1"
    assert tools["avr-gcc"].startswith("avr-gcc (GCC) 7.3.0")
    assert measured.entries > 10_000


def test_every_file_is_read_only_and_has_one_name(
    provisioned: tuple[Path, dict[str, object]],
) -> None:
    env, _ = provisioned
    files = 0
    for directory, dirs, names in os.walk(env):
        for name in [*dirs, *names]:
            found = Path(directory, name).lstat()
            if stat.S_ISLNK(found.st_mode):
                continue
            files += 1
            assert found.st_mode & 0o222 == 0, Path(directory, name)
            assert stat.S_ISDIR(found.st_mode) or found.st_nlink == 1, Path(directory, name)
    assert files > 10_000


def test_the_offline_self_check_built_the_firmware_and_ran_the_libraries(
    provisioned: tuple[Path, dict[str, object]],
) -> None:
    env, record = provisioned
    written = json.loads((env / "provisioned.json").read_text(encoding="utf-8"))
    assert written == json.loads(json.dumps(record))
    check = written["self_check"]
    assert check["firmware"] == {"flash_used_bytes": 4798, "ram_used_bytes": 173}
    assert check["libraries"]["versions"] == PINNED
    assert check["libraries"]["phase_margin_deg"] == pytest.approx(28.0202, abs=1e-3)
    assert check["platformio_server"] == "3.1.0"
    assert not (env / "platformio" / ".cache").exists()
    own = sorted(p.name for p in (REPO / "toolenv" / "servers").glob("*.py"))
    assert written["own_servers"] == own
    assert {"control_server.py", "mujoco_server.py"} <= set(own)
    for name in own:
        assert (env / "servers" / name).read_bytes() == (
            REPO / "toolenv" / "servers" / name
        ).read_bytes()


def test_using_the_environment_writes_nothing_into_it(
    provisioned: tuple[Path, dict[str, object]], tmp_path: Path
) -> None:
    env, _ = provisioned
    before = scan([env])
    home = tmp_path / "home"
    home.mkdir()
    provision = _provision()
    run_env = {"PATH": "/usr/bin:/bin", "HOME": str(home), "MPLBACKEND": "Agg"}
    done = subprocess.run(
        [str(env / "venv" / "bin" / "python"), "-I", "-c", provision.LIBRARY_CHECK],
        env=run_env,
        capture_output=True,
        text=True,
        timeout=300,
        check=False,
    )
    assert done.returncode == 0, done.stderr[-2000:]
    core = tmp_path / "core"
    core.mkdir()
    for name in ("platforms", "packages", "lib"):
        (core / name).symlink_to(env / "platformio" / name)
    sketch = tmp_path / "sketch"
    (sketch / "src").mkdir(parents=True)
    (sketch / "platformio.ini").write_text(provision.FIXTURE_INI)
    (sketch / "src" / "main.cpp").write_text(provision.FIXTURE_MAIN)
    pio_env = provision.pio_environment(core, tmp_path, offline=True) | {
        "HOME": str(home),
        "PLATFORMIO_BUILD_DIR": str(tmp_path / "build"),
        "PLATFORMIO_WORKSPACE_DIR": str(tmp_path / "workspace"),
        "PLATFORMIO_CACHE_DIR": str(tmp_path / "pio-cache"),
    }
    built = subprocess.run(
        [str(env / "venv" / "bin" / "pio"), "run"],
        env=pio_env,
        cwd=sketch,
        capture_output=True,
        text=True,
        timeout=600,
        check=False,
    )
    assert built.returncode == 0, built.stdout[-2000:]
    assert "used 4798 bytes from 28672 bytes" in built.stdout
    assert scan([env]) == before


def test_a_wrong_node_pin_stops_provisioning_and_leaves_nothing(
    tmp_path_factory: pytest.TempPathFactory,
) -> None:
    provision = _provision()
    pins = copy.deepcopy(provision.load_pins())
    for archive in pins["node"]["archives"].values():
        archive["sha256"] = "0" * 64
    env = tmp_path_factory.mktemp("wrong-node") / "env"
    with pytest.raises(provision.ProvisionError, match="digest"):
        provision.provision(env, _cache(tmp_path_factory), pins)
    assert not env.exists()


def test_an_interpreter_that_cannot_be_installed_stops_provisioning_and_says_so(
    tmp_path_factory: pytest.TempPathFactory,
) -> None:
    provision = _provision()
    pins = copy.deepcopy(provision.load_pins())
    pins["python"] = "3.12.999"
    env = tmp_path_factory.mktemp("no-python") / "env"
    with pytest.raises(provision.ProvisionError, match="cannot be installed"):
        provision.provision(env, _cache(tmp_path_factory), pins)
    assert not env.exists()
