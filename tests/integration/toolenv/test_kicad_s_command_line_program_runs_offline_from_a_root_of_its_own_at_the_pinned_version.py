"""KiCad's command-line program runs offline from a root of its own, at the pinned version.

KiCad is provisioned beside the tool environment, in a root of its own that the harness's measure
accepts: no file with a second name, no link leaving the root or looping, nothing but files,
directories and links, and the two roots apart. The program answers the pinned version with the
network taken away, and asking it writes nothing into its root.

``PHYSGATE_KICAD_ROOT`` names a provisioned KiCad root (``toolenv/provision.py --kicad-dest``);
without it one is provisioned here, which needs the network once per download cache
(``PHYSGATE_TOOLENV_CACHE`` names a kept one). ``PHYSGATE_TOOL_ENVIRONMENT`` names the
environment's other root, with which the harness measures this one as a run names them both.
"""

from __future__ import annotations

import importlib.util
import json
import os
import socket
import stat
import subprocess
import sys
from collections.abc import Iterator
from pathlib import Path
from types import ModuleType

import pytest
from design_fixtures import offline_prefix

from physgate.toolenv.manifest import manifest, scan
from physgate.toolenv.record import measure

pytestmark = pytest.mark.integration

REPO = Path(__file__).resolve().parents[3]
VERSION = "10.0.8"
NAMED_ROOT = os.environ.get("PHYSGATE_KICAD_ROOT", "")
NAMED_ENVIRONMENT = os.environ.get("PHYSGATE_TOOL_ENVIRONMENT", "")
#: An outside address the tests' own network probes name.
OUTSIDE = ("140.82.121.4", 443)


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
def built(tmp_path_factory: pytest.TempPathFactory) -> Iterator[Path | None]:
    if NAMED_ROOT:
        yield Path(NAMED_ROOT)
        return
    build = getattr(_provision(), "provision_kicad", None)
    if build is None:
        yield None
        return
    named = os.environ.get("PHYSGATE_TOOLENV_CACHE")
    cache = Path(named) if named else tmp_path_factory.mktemp("toolenv-cache")
    root = tmp_path_factory.mktemp("built") / "kicad"
    build(root, cache)
    yield root
    _writable(root)


def _root(built: Path | None) -> Path:
    assert built is not None, "provisioning builds no KiCad root"
    return built


def _cli(root: Path) -> Path:
    place = getattr(_provision(), "kicad_cli", None)
    assert callable(place), "provisioning names no place for KiCad's program"
    return Path(str(place(root, "Linux" if sys.platform.startswith("linux") else "Darwin")))


def test_the_harness_s_measure_accepts_the_root(built: Path | None) -> None:
    kicad_root = _root(built)
    found = manifest([kicad_root])
    assert found.entries > 10_000
    files = 0
    for directory, dirs, names in os.walk(kicad_root):
        for name in [*dirs, *names]:
            entry = Path(directory, name).lstat()
            if stat.S_ISLNK(entry.st_mode):
                continue
            assert entry.st_mode & 0o222 == 0, Path(directory, name)
            if stat.S_ISREG(entry.st_mode):
                files += 1
                assert entry.st_nlink == 1, Path(directory, name)
    assert files > 10_000


def test_the_record_names_the_pin_the_licence_and_what_the_copy_took(built: Path | None) -> None:
    kicad_root = _root(built)
    provision = _provision()
    record = json.loads((kicad_root / "provisioned.json").read_text(encoding="utf-8"))
    linux = sys.platform.startswith("linux")
    machine = ("Linux", "x86_64") if linux else ("Darwin", "arm64")
    assert record.get("kicad") == VERSION
    assert record.get("pin") == provision.kicad_pin(provision.load_pins(), *machine)
    assert "GPL-3.0-or-later" in record.get("licence", "")
    assert record.get("self_check", {}).get("version") == VERSION
    assert kicad_root / record.get("program", "") == _cli(kicad_root)
    copied = record.get("copied", {})
    assert copied.get("files", 0) > 10_000
    if linux:
        assert copied.get("dropped") == [
            "usr/share/kicad/demos",
            "shared/lib/python3.11/sitecustomize.py",
            "shared/lib/python3.11/config-3.11-x86_64-linux-gnu/libpython3.11.so",
        ]
        assert copied.get("names_copied_apart", 0) > 0
        assert not (kicad_root / "app" / "usr" / "share" / "kicad" / "demos").exists()
        assert (kicad_root / "app" / "usr" / "share" / "kicad" / "symbols").is_dir()
    else:
        shared = kicad_root / "app" / "KiCad.app" / "Contents" / "SharedSupport"
        assert (shared / "symbols").is_dir()


def _offline() -> list[str]:
    """A prefix that takes the network away, or none where this process already has none."""
    prefix = offline_prefix()
    if prefix:
        return prefix
    try:
        socket.create_connection(OUTSIDE, 5).close()
    except OSError:
        return []
    pytest.skip("this machine can take the network from no single process, and has it")


def test_the_program_answers_the_pinned_version_offline_and_writes_nothing_into_its_root(
    built: Path | None, tmp_path: Path
) -> None:
    kicad_root = _root(built)
    before = scan([kicad_root])
    prefix = _offline()
    for name in ("home", "tmp", "config"):
        (tmp_path / name).mkdir()
    env = {
        "PATH": "/usr/bin:/bin",
        "HOME": str(tmp_path / "home"),
        "TMPDIR": str(tmp_path / "tmp"),
        "KICAD_CONFIG_HOME": str(tmp_path / "config"),
        "LANG": "C.UTF-8",
    }
    for asked in ("--version", "version"):
        done = subprocess.run(
            [*prefix, str(_cli(kicad_root)), asked],
            env=env,
            capture_output=True,
            text=True,
            timeout=120,
            check=False,
        )
        assert done.returncode == 0, (asked, done.stderr[-2000:])
        assert done.stdout.strip().splitlines()[0] == VERSION, (asked, done.stdout[-500:])
    assert scan([kicad_root]) == before


def test_the_harness_measures_both_roots_and_records_the_program_at_its_version(
    built: Path | None,
) -> None:
    kicad_root = _root(built)
    if not NAMED_ENVIRONMENT:
        pytest.skip("PHYSGATE_TOOL_ENVIRONMENT names no environment to measure beside it")
    env = Path(NAMED_ENVIRONMENT)
    measured = measure(
        str(env / "venv" / "bin" / "python"),
        [str(env), str(kicad_root)],
        native={"kicad-cli": str(_cli(kicad_root))},
        forbidden={"the harness checkout": REPO},
    )
    tools = {tool.name: tool.version for tool in measured.native_tools}
    assert tools == {"kicad-cli": VERSION}
    assert measured.roots == (str(env), str(kicad_root))
    alone = manifest([env])
    assert measured.entries > alone.entries + 10_000


def test_the_root_carries_the_session_file_provisioning_writes(built: Path | None) -> None:
    kicad_root = _root(built)
    provision = _provision()
    session = getattr(provision, "kicad_session", None)
    assert callable(session), "provisioning writes no session file for KiCad"
    system = "Linux" if sys.platform.startswith("linux") else "Darwin"
    assert (kicad_root / "session.json").is_file(), "provisioning wrote no session file"
    written = json.loads((kicad_root / "session.json").read_text(encoding="utf-8"))
    assert written == session(system)
    assert (kicad_root / "session.json").stat().st_mode & 0o222 == 0
