"""The circuit library imports without a GPL library, and its built packages repeat.

On a provisioned environment: ``import skidl`` in the environment's interpreter loads no module
of InSpice (the GPL simulator the project overrides out); no installed distribution states a
GPL licence, or one off the allowed list, by its own metadata; and the three packages built from
source at provisioning are recorded with their source digests (the lock's) and the digests of
the wheels built from them, which a second provisioning from a fresh download cache repeats.

``PHYSGATE_TOOL_ENVIRONMENT`` names a provisioned environment (``toolenv/provision.py``); with
none named one is built here, which needs the network (``PHYSGATE_TOOLENV_CACHE`` keeps the
downloads). The second provisioning always takes a fresh cache, so its wheels are built anew.
"""

from __future__ import annotations

import importlib.util
import json
import os
import subprocess
import sys
import tomllib
from collections.abc import Iterator
from pathlib import Path
from types import ModuleType

import pytest

pytestmark = pytest.mark.integration

REPO = Path(__file__).resolve().parents[3]
NAMED = os.environ.get("PHYSGATE_TOOL_ENVIRONMENT", "")
SOURCE_ONLY = ("hierplace", "kinet2pcb", "skidl")
IMPORTED = (
    "import importlib.metadata as m, json, sys\n"
    "import skidl\n"
    "print(json.dumps({'version': m.version('skidl'),\n"
    "    'inspice': sorted(k for k in sys.modules if k.split('.')[0].lower() == 'inspice')}))\n"
)


def _provision() -> ModuleType:
    spec = importlib.util.spec_from_file_location(
        "toolenv_provision", REPO / "toolenv" / "provision.py"
    )
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def _writable(root: Path) -> None:
    for directory, dirs, _ in os.walk(root):
        for name in [".", *dirs]:
            path = Path(directory, name)
            if not path.is_symlink():
                path.chmod(0o755)


@pytest.fixture(scope="module")
def env(tmp_path_factory: pytest.TempPathFactory) -> Iterator[Path]:
    if NAMED:
        yield Path(NAMED)
        return
    built = tmp_path_factory.mktemp("built") / "env"
    kept = os.environ.get("PHYSGATE_TOOLENV_CACHE")
    cache = Path(kept) if kept else tmp_path_factory.mktemp("toolenv-cache")
    _provision().provision(built, cache)
    yield built
    _writable(built)


def _site(env: Path) -> Path:
    found = sorted((env / "venv" / "lib").glob("python3.*/site-packages"))
    assert len(found) == 1, found
    return found[0]


def _record(env: Path) -> dict[str, object]:
    loaded = json.loads((env / "provisioned.json").read_text(encoding="utf-8"))
    assert isinstance(loaded, dict)
    return loaded


def test_importing_the_circuit_library_loads_no_module_of_the_gpl_simulator(
    env: Path, tmp_path: Path
) -> None:
    home = tmp_path / "home"
    home.mkdir()
    done = subprocess.run(
        [str(env / "venv" / "bin" / "python"), "-I", "-c", IMPORTED],
        cwd=tmp_path,
        env={
            "PATH": "/usr/bin:/bin",
            "HOME": str(home),
            "TMPDIR": str(tmp_path),
            "LANG": "C.UTF-8",
            "XDG_CACHE_HOME": str(tmp_path / "xdg-cache"),
            "XDG_DATA_HOME": str(tmp_path / "xdg-data"),
        },
        capture_output=True,
        text=True,
        timeout=300,
        check=False,
    )
    assert done.returncode == 0, done.stderr[-3000:]
    told = json.loads(done.stdout.strip().splitlines()[-1])
    assert told == {"version": "3.0.0", "inspice": []}
    assert not list(_site(env).glob("[Ii]n[Ss]pice*")), "the simulator is installed"


def test_no_distribution_in_the_environment_states_a_gpl_licence_or_one_off_the_list(
    env: Path,
) -> None:
    provision = _provision()
    site = _site(env)
    infos = sorted(site.glob("*.dist-info"))
    assert len(infos) > 90, f"only {len(infos)} distributions read"
    refusals = getattr(provision, "licence_refusals", lambda _site: ["no licence check"])
    assert refusals(site) == []
    names = {info.name.split("-", 1)[0].lower() for info in infos}
    assert {"skidl", "kinet2pcb", "hierplace", "numpy"} <= names


def test_the_packages_built_from_source_are_recorded_with_both_digests(env: Path) -> None:
    lock = tomllib.loads((REPO / "toolenv" / "uv.lock").read_text(encoding="utf-8"))
    found = {package["name"]: package for package in lock["package"]}
    built = _record(env).get("built_from_source")
    assert isinstance(built, dict), "the record names no package built from source"
    assert sorted(built) == list(SOURCE_ONLY)
    for name in SOURCE_ONLY:
        entry = built[name]
        assert entry["version"] == found[name]["version"], name
        assert f"sha256:{entry['sdist_sha256']}" == found[name]["sdist"]["hash"], name
        assert entry["wheel"].startswith(f"{name}-{entry['version']}-"), entry
        assert entry["wheel"].endswith("-none-any.whl"), entry
        assert len(entry["wheel_sha256"]) == 64, entry
    held = _record(env).get("build_constraints")
    project = tomllib.loads((REPO / "toolenv" / "pyproject.toml").read_text(encoding="utf-8"))
    assert held == project["tool"]["uv"]["build-constraint-dependencies"]


def test_a_second_provisioning_from_a_fresh_cache_builds_the_same_wheels(
    env: Path, tmp_path_factory: pytest.TempPathFactory
) -> None:
    first = _record(env).get("built_from_source")
    assert isinstance(first, dict), "the record names no package built from source"
    again = tmp_path_factory.mktemp("again") / "env"
    try:
        second = _provision().provision(again, tmp_path_factory.mktemp("fresh-cache"))
        assert second.get("built_from_source") == first, (
            f"first {json.dumps(first, sort_keys=True)}; "
            f"second {json.dumps(second.get('built_from_source'), sort_keys=True)}"
        )
    finally:
        _writable(again)
