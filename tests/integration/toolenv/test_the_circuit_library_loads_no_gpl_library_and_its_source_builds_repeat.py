"""The circuit library imports without a GPL library, and its built packages repeat.

On a provisioned environment: ``import skidl`` in the environment's interpreter loads no module
of InSpice (the GPL simulator the project overrides out); no installed distribution states a
GPL licence, or one off the allowed list, by its own metadata; and the three packages built from
source at provisioning are recorded with their source digests (the lock's) and the digests of
the wheels built from them, which a second provisioning from a fresh build cache repeats.

``PHYSGATE_TOOL_ENVIRONMENT`` names a provisioned environment (``toolenv/provision.py``); with
none named one is built here, which needs the network (``PHYSGATE_TOOLENV_CACHE`` keeps the
downloads). The second provisioning always takes a cache with no folder of uv's, so its wheels
are built anew; the pinned archives (Node, the display-library packages, the published model)
are copied into it from the first cache where they are kept there, since provisioning holds each
to its pin's sha256 whichever cache it is found in. Where every one of them was kept, the second
provisioning may fetch none of them: the claim is about the wheels, not the archive's servers.
"""

from __future__ import annotations

import importlib.util
import json
import os
import platform
import shutil
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
def downloads(tmp_path_factory: pytest.TempPathFactory) -> Path:
    """The download cache the first provisioning used, or would have: kept, or one of its own."""
    kept = os.environ.get("PHYSGATE_TOOLENV_CACHE")
    return Path(kept) if kept else tmp_path_factory.mktemp("toolenv-cache")


@pytest.fixture(scope="module")
def env(downloads: Path, tmp_path_factory: pytest.TempPathFactory) -> Iterator[Path]:
    if NAMED:
        yield Path(NAMED)
        return
    built = tmp_path_factory.mktemp("built") / "env"
    _provision().provision(built, downloads)
    yield built
    _writable(built)


def _pinned_archives(provision: ModuleType) -> list[str]:
    """Each pinned archive provisioning fetches on this machine, as its place in a cache."""
    pins = provision.load_pins()
    system, machine = platform.system(), platform.machine()
    node, _ = provision.node_archive(pins, system, machine)
    packages = provision.system_packages(pins, system, machine)
    return [
        f"node/{pins['node']['version']}/{node}",
        *(f"system-libraries/{p['file']}" for p in packages),
        *(f"{provision.REFERENCE}/{m['file']}" for m in provision.reference_models(pins)),
    ]


def _build_cache_with_the_kept_archives(
    provision: ModuleType, downloads: Path, fresh: Path
) -> bool:
    """Copy each pinned archive kept in ``downloads`` into ``fresh``; whether all of them were.

    Only the pinned archives: never uv's folder, which holds the wheels built from source and
    the first provisioning's other wheels, so the second provisioning builds its own. Copied,
    not linked, so nothing the second provisioning does reaches the kept files; provisioning
    holds each copy to its pin's sha256 before it uses it, as it does a file it fetched.
    """
    wanted = _pinned_archives(provision)
    for place in wanted:
        if (downloads / place).is_file():
            (fresh / place).parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(downloads / place, fresh / place)
            print(f"kept: {place}")
    return all((fresh / place).is_file() for place in wanted)


def _refuse_every_fetch(url: str, *_args: object, **_kwargs: object) -> Path:
    raise AssertionError(f"{url} was fetched although every pinned archive was kept")


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


def test_provisioning_read_every_licence_and_imported_the_circuit_library_itself(
    env: Path,
) -> None:
    record = _record(env)
    read = record.get("licences_read")
    assert isinstance(read, int), "the record does not say how many licences were read"
    assert read == len(list(_site(env).glob("*.dist-info")))
    # A distribution accepted by name (chardet, on macOS on ARM) is recorded with its reason,
    # and nothing else is.
    accepted = getattr(_provision(), "licences_accepted", lambda _site: None)
    assert record.get("licences_accepted_by_name") == accepted(_site(env))
    checks = record.get("self_check")
    assert isinstance(checks, dict)
    assert checks.get("circuit") == {"skidl": "3.0.0", "inspice_modules": []}


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


def test_a_second_provisioning_from_a_fresh_cache_builds_wheels_of_the_same_contents(
    env: Path, downloads: Path, tmp_path_factory: pytest.TempPathFactory
) -> None:
    # Measured on UiA (15.11): the wheel files themselves differ between two builds (the zip
    # holds each file's time), so the claim is the sources' digests and the wheels' contents,
    # by the file list each wheel carries, which names every file with its digest. The two
    # wheel files' digests are printed, not compared.
    first = _record(env).get("built_from_source")
    assert isinstance(first, dict), "the record names no package built from source"
    provision = _provision()
    fresh = tmp_path_factory.mktemp("fresh-build-cache")
    if _build_cache_with_the_kept_archives(provision, downloads, fresh):
        # The archive the display libraries come from answers 502 and 503 under load: with
        # every pinned archive at hand, a fetch would only say something about its servers.
        vars(provision)["fetch"] = _refuse_every_fetch
    assert not (fresh / "uv").exists(), "the second provisioning would not build its own wheels"
    again = tmp_path_factory.mktemp("again") / "env"
    try:
        second = provision.provision(again, fresh)
        # The second provisioning read every licence and imported the circuit library too.
        assert second.get("licences_read") == _record(env).get("licences_read")
        assert second["self_check"]["circuit"] == {"skidl": "3.0.0", "inspice_modules": []}
        built = second.get("built_from_source")
        assert isinstance(built, dict)
        assert sorted(built) == sorted(first) == list(SOURCE_ONLY)
        for name in SOURCE_ONLY:
            digests = (first[name]["wheel_sha256"], built[name]["wheel_sha256"])
            print(f"{name}: wheel sha256 {digests[0]} then {digests[1]}")
            for field in ("version", "sdist_sha256", "wheel", "wheel_record_sha256", "built_by"):
                assert built[name][field] == first[name][field], (name, field)
    finally:
        _writable(again)
