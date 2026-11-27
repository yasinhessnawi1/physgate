"""The tool environment is built from its own locks, apart from the harness, copied, never linked.

The environment's pins live beside its provisioning script in the repository's ``toolenv/``
directory: a uv project of its own with a lock taken a week back, the pinned Node release with
its digest for each platform, the PlatformIO store's exact packages, and the PlatformIO tool
server's npm lock with an integrity hash for every package. The script is read here as a file
and its judgements are tested on their own; building a real environment needs the network and
is the integration test's.
"""

from __future__ import annotations

import datetime as dt
import importlib.util
import json
import os
import re
import sys
import tarfile
import tomllib
from pathlib import Path
from types import ModuleType

import pytest

REPO = Path(__file__).resolve().parents[3]
TOOLENV = REPO / "toolenv"

#: The libraries a role session computes and builds with, at the versions the scorer shares.
LIBRARIES = {
    "control": "0.10.1",
    "numpy": "2.1.2",
    "scipy": "1.14.1",
    "mujoco": "3.17.0",
    "platformio": "6.2.0",
}
#: How long a release must have been public before the environment may take it.
COOLDOWN = dt.timedelta(days=7)


def _provision() -> ModuleType:
    path = TOOLENV / "provision.py"
    assert path.is_file(), "the tool environment has no provisioning script"
    spec = importlib.util.spec_from_file_location("toolenv_provision", path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def _pins() -> dict[str, object]:
    path = TOOLENV / "pins.json"
    assert path.is_file(), "the tool environment has no pins file"
    loaded = json.loads(path.read_text(encoding="utf-8"))
    assert isinstance(loaded, dict)
    return loaded


def _when(text: object) -> dt.datetime:
    assert isinstance(text, str)
    return dt.datetime.fromisoformat(text.replace("Z", "+00:00"))


# ---- the Python side ------------------------------------------------------------------------


def test_the_environment_is_a_project_of_its_own_with_exactly_the_pinned_libraries() -> None:
    path = TOOLENV / "pyproject.toml"
    assert path.is_file(), "the tool environment has no project file"
    project = tomllib.loads(path.read_text(encoding="utf-8"))
    assert sorted(project["project"]["dependencies"]) == sorted(
        f"{name}=={version}" for name, version in LIBRARIES.items()
    )
    assert project["project"]["requires-python"] == "==3.12.9"
    assert project["tool"]["uv"]["package"] is False
    assert _when(project["tool"]["uv"]["exclude-newer"])


def test_the_lock_was_taken_a_week_back_and_holds_every_pin_with_its_hashes() -> None:
    path = TOOLENV / "uv.lock"
    assert path.is_file(), "the tool environment has no lock"
    project = tomllib.loads((TOOLENV / "pyproject.toml").read_text(encoding="utf-8"))
    lock = tomllib.loads(path.read_text(encoding="utf-8"))
    newest = _when(project["tool"]["uv"]["exclude-newer"])
    assert _when(lock["options"]["exclude-newer"]) == newest
    pins = _pins()
    assert newest <= _when(pins["locked"]) - COOLDOWN
    found = {package["name"]: package for package in lock["package"]}
    for name, version in LIBRARIES.items():
        assert found[name]["version"] == version, name
    assert len(found) > len(LIBRARIES)
    for name, package in found.items():
        if "virtual" in package["source"]:
            continue  # the environment's own project, which installs nothing
        files = list(package.get("wheels", []))
        if "sdist" in package:
            files.append(package["sdist"])
        assert files, f"{name} names no file"
        for file in files:
            assert re.fullmatch(r"sha256:[0-9a-f]{64}", file["hash"]), name


def test_the_harness_lock_and_interpreter_hold_none_of_the_tool_libraries() -> None:
    # pint changes how it handles units when numpy is importable, so the tools' libraries
    # never enter the harness's own environment.
    # The lock also holds the evaluation side's group, which names some of them for the scorers
    # and is installed only into an environment of its own; what is held here is everything
    # the harness's own installation brings in: the project's dependencies and the development
    # group, with all they depend on.
    harness = tomllib.loads((REPO / "uv.lock").read_text(encoding="utf-8"))
    packages = {package["name"]: package for package in harness["package"]}
    project = packages["physgate"]
    waiting = [dep["name"] for dep in project["dependencies"]]
    waiting += [dep["name"] for dep in project["dev-dependencies"]["dev"]]
    installed: set[str] = set()
    while waiting:
        name = waiting.pop()
        if name not in installed:
            installed.add(name)
            waiting += [dep["name"] for dep in packages[name].get("dependencies", [])]
    assert {"pint", "pytest"} <= installed, "the harness's own installation was not read"
    assert not installed & set(LIBRARIES)
    for name in LIBRARIES:
        assert importlib.util.find_spec(name) is None, name


# ---- Node, the PlatformIO tool server and the PlatformIO store ------------------------------


def test_node_is_an_lts_release_past_the_cooldown_with_a_digest_for_each_platform() -> None:
    pins = _pins()
    node = pins["node"]
    assert isinstance(node, dict)
    version = node["version"]
    assert isinstance(version, str)
    major = int(version.split(".")[0])
    assert major >= 20 and major % 2 == 0, version
    assert _when(node["released"]) <= _when(pins["locked"]) - COOLDOWN
    archives = node["archives"]
    assert set(archives) == {"darwin-arm64", "linux-x64", "linux-arm64"}
    for platform_name, archive in archives.items():
        assert archive["file"] == f"node-v{version}-{platform_name}.tar.gz"
        assert re.fullmatch(r"[0-9a-f]{64}", archive["sha256"]), platform_name


def test_the_platformio_server_is_locked_with_an_integrity_hash_for_every_package() -> None:
    server = TOOLENV / "platformio-server"
    assert (server / "package.json").is_file(), "the PlatformIO server has no package file"
    package = json.loads((server / "package.json").read_text(encoding="utf-8"))
    assert package["dependencies"] == {"platformio-mcp": "3.1.0"}
    lock = json.loads((server / "package-lock.json").read_text(encoding="utf-8"))
    assert lock["lockfileVersion"] == 3
    entries = {name: entry for name, entry in lock["packages"].items() if name}
    assert entries["node_modules/platformio-mcp"]["version"] == "3.1.0"
    assert len(entries) > 1
    for name, entry in entries.items():
        assert entry["resolved"].startswith("https://registry.npmjs.org/"), name
        assert re.fullmatch(r"sha512-[A-Za-z0-9+/]+={0,2}", entry["integrity"]), name
    policy = (server / "policy.yaml").read_text(encoding="utf-8")
    # The server's build_only profile, its allow list narrowed to the register's tools.
    assert policy.splitlines()[0] == "profile: build_only"


def test_the_platformio_store_is_named_package_by_package() -> None:
    store = _pins()["platformio"]
    assert store == {
        "platform": "platformio/atmelavr@5.3.0",
        "tools": [
            "platformio/framework-arduino-avr@5.4.0",
            "platformio/tool-scons@4.41101.0",
            "platformio/toolchain-atmelavr@1.70300.191015",
        ],
        "libraries": ["pololu/Balboa32U4@1.1.2"],
    }


# ---- what the script decides ----------------------------------------------------------------


@pytest.mark.parametrize(
    ("system", "machine", "expected"),
    [
        ("Darwin", "arm64", "darwin-arm64"),
        ("Linux", "x86_64", "linux-x64"),
        ("Linux", "aarch64", "linux-arm64"),
    ],
)
def test_node_s_archive_is_chosen_for_the_machine(system: str, machine: str, expected: str) -> None:
    provision = _provision()
    file, digest = provision.node_archive(_pins(), system, machine)
    archives = _pins()["node"]["archives"]  # type: ignore[index]
    assert (file, digest) == (archives[expected]["file"], archives[expected]["sha256"])


@pytest.mark.parametrize(("system", "machine"), [("Darwin", "x86_64"), ("Windows", "AMD64")])
def test_a_machine_with_no_pinned_node_is_refused(system: str, machine: str) -> None:
    provision = _provision()
    with pytest.raises(provision.ProvisionError, match="no pinned Node"):
        provision.node_archive(_pins(), system, machine)


def test_a_download_whose_digest_differs_is_refused(tmp_path: Path) -> None:
    provision = _provision()
    archive = tmp_path / "node.tar.gz"
    archive.write_bytes(b"not the release")
    with pytest.raises(provision.ProvisionError, match="digest"):
        provision.require_digest(archive, "0" * 64)
    provision.require_digest(archive, provision.sha256_of(archive))


def test_the_destination_is_absolute_new_and_outside_the_harness(tmp_path: Path) -> None:
    provision = _provision()
    with pytest.raises(provision.ProvisionError, match="absolute"):
        provision.check_destination(Path("relative/env"), REPO)
    with pytest.raises(provision.ProvisionError, match="harness"):
        provision.check_destination(REPO / "toolenv" / "env", REPO)
    with pytest.raises(provision.ProvisionError, match="harness"):
        provision.check_destination(REPO.parent, REPO)
    full = tmp_path / "full"
    full.mkdir()
    (full / "left").write_text("x")
    with pytest.raises(provision.ProvisionError, match="empty"):
        provision.check_destination(full, REPO)
    assert provision.check_destination(tmp_path / "new", REPO) == tmp_path / "new"
    (tmp_path / "empty").mkdir()
    assert provision.check_destination(tmp_path / "empty", REPO) == tmp_path / "empty"


def test_uv_copies_downloads_python_only_on_request_and_reads_none_of_the_machine_s_settings(
    tmp_path: Path,
) -> None:
    provision = _provision()
    before = dict(os.environ)
    env = provision.uv_environment(tmp_path / "env", tmp_path / "cache", tmp_path / "work")
    assert dict(os.environ) == before
    assert env.get("UV_LINK_MODE") == "copy"
    assert env.get("UV_PYTHON_DOWNLOADS") == "manual"
    assert env.get("UV_PYTHON_PREFERENCE") == "only-managed"
    assert env.get("UV_PYTHON_INSTALL_DIR") == str(tmp_path / "env" / "python")
    assert env.get("UV_PROJECT_ENVIRONMENT") == str(tmp_path / "env" / "venv")
    assert env.get("UV_CACHE_DIR") == str(tmp_path / "cache" / "uv")
    # uv may place python executables in a bin directory; never the user's.
    assert env.get("UV_PYTHON_BIN_DIR") == str(tmp_path / "work" / "bin")
    # The machine's own uv settings are not read: they live under the user's home or the
    # configuration home, and neither is the one uv is given. uv's switch for ignoring
    # configuration is not used, because it drops the project's own settings as well, its
    # lock cooldown among them.
    assert env.get("HOME") == str(tmp_path / "work" / "home")
    assert "UV_NO_CONFIG" not in env
    assert not {"VIRTUAL_ENV", "PYTHONPATH", "PYTHONHOME", "UV_INDEX_URL", "XDG_CONFIG_HOME"} & set(
        env
    )


def _fake_uv(folder: Path, says: str, status: int = 0) -> Path:
    """A program named ``uv`` that answers ``--version`` with ``says``."""
    folder.mkdir(parents=True, exist_ok=True)
    uv = folder / "uv"
    uv.write_text(f"#!/bin/sh\necho '{says}'\nexit {status}\n", encoding="utf-8")
    uv.chmod(0o755)
    return uv


@pytest.mark.parametrize(
    ("says", "status", "named"),
    [
        # The uv earlier environments on a laptop were built with, and the last release before
        # the one that holds the lock's build constraints.
        ("uv 0.6.9 (3d9460278 2025-03-20)", 0, "0.6.9"),
        ("uv 0.6.10 (f2a2d982b 2025-03-25)", 0, "0.6.10"),
        ("uv 0.5.31", 0, "0.5.31"),
        ("not a version", 0, "not a version"),
        ("uv 0.12.17", 2, "uv 0.12.17"),
    ],
)
def test_a_uv_that_does_not_hold_the_lock_s_build_constraints_is_refused_naming_the_one_needed(
    tmp_path: Path, says: str, status: int, named: str
) -> None:
    provision = _provision()
    uv = _fake_uv(tmp_path / "bin", says, status)
    with pytest.raises(provision.ProvisionError) as raised:
        provision.require_uv(str(uv))
    words = str(raised.value)
    assert named in words
    assert str(uv) in words
    # The version needed, why, and how to have it without a system-wide install.
    assert "uv 0.6.11 or later" in words
    assert "build constraints" in words
    assert "uv pip install uv==" in words


@pytest.mark.parametrize(
    ("says", "named"),
    [
        ("uv 0.6.11 (0632e24d1 2025-03-30)", "0.6.11"),
        ("uv 0.12.17 (635500036 2026-09-18 aarch64-apple-darwin)", "0.12.17"),
        ("uv 1.0.0", "1.0.0"),
    ],
)
def test_a_uv_from_the_one_that_holds_the_build_constraints_on_is_taken(
    tmp_path: Path, says: str, named: str
) -> None:
    provision = _provision()
    assert provision.require_uv(str(_fake_uv(tmp_path / "bin", says))) == named


def test_provisioning_refuses_an_older_uv_on_the_search_path_before_it_makes_anything(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    provision = _provision()
    _fake_uv(tmp_path / "bin", "uv 0.6.9 (3d9460278 2025-03-20)")
    monkeypatch.setenv("PATH", f"{tmp_path / 'bin'}:/usr/bin:/bin")
    dest, cache = tmp_path / "env", tmp_path / "cache"
    raised = None
    try:
        provision.provision(dest, cache, pins={})
    except Exception as exc:  # noqa: BLE001 - a wrong kind must fail the assertion below
        raised = exc
    assert isinstance(raised, provision.ProvisionError), raised
    assert "0.6.9" in str(raised)
    assert "0.6.11" in str(raised)
    assert not dest.exists()
    assert not cache.exists()


def test_the_linux_workflow_s_uv_is_past_the_floor_and_the_one_the_script_names() -> None:
    provision = _provision()
    workflow = (REPO / ".github" / "workflows" / "tool-environment.yml").read_text(encoding="utf-8")
    found = re.search(r"setup-uv@[0-9a-f]{40}.*\n\s+with:\n\s+version: \"([0-9.]+)\"", workflow)
    assert found, "the workflow names no uv version"
    version = found.group(1)
    assert tuple(int(part) for part in version.split(".")) >= provision.UV_FLOOR
    script = (TOOLENV / "provision.py").read_text(encoding="utf-8")
    assert f"uv pip install uv=={version}" in script


def test_the_server_s_packages_are_installed_from_the_lock_with_no_script_and_nothing_optional(
    tmp_path: Path,
) -> None:
    provision = _provision()
    argv = provision.npm_ci_argv(tmp_path / "npm", tmp_path / "cache")
    assert argv[:2] == [str(tmp_path / "npm"), "ci"]
    for flag in ("--ignore-scripts", "--omit=optional", "--omit=dev", "--no-audit", "--no-fund"):
        assert flag in argv
    assert f"--cache={tmp_path / 'cache' / 'npm'}" in argv


def test_the_store_is_installed_package_by_package_without_their_own_dependencies(
    tmp_path: Path,
) -> None:
    provision = _provision()
    pio = tmp_path / "pio"
    assert provision.pio_install_argvs(pio, _pins()) == [
        [str(pio), "pkg", "install", "-g", "--skip-dependencies", "-p",
         "platformio/atmelavr@5.3.0"],
        [str(pio), "pkg", "install", "-g", "--skip-dependencies", "-t",
         "platformio/framework-arduino-avr@5.4.0"],
        [str(pio), "pkg", "install", "-g", "--skip-dependencies", "-t",
         "platformio/tool-scons@4.41101.0"],
        [str(pio), "pkg", "install", "-g", "--skip-dependencies", "-t",
         "platformio/toolchain-atmelavr@1.70300.191015"],
        [str(pio), "pkg", "install", "-g", "--skip-dependencies", "-l",
         "pololu/Balboa32U4@1.1.2"],
    ]  # fmt: skip


@pytest.mark.parametrize("kind", ["file", "link"])
def test_an_archive_member_that_leaves_its_directory_is_refused(tmp_path: Path, kind: str) -> None:
    provision = _provision()
    archive = tmp_path / "bad.tar.gz"
    payload = tmp_path / "payload"
    payload.write_text("x")
    with tarfile.open(archive, "w:gz") as tar:
        if kind == "file":
            tar.add(payload, arcname="../escaped")
        else:
            member = tarfile.TarInfo("node-v1/bin/escaped")
            member.type, member.linkname = tarfile.SYMTYPE, str(tmp_path / "payload")
            tar.addfile(member)
    into = tmp_path / "into"
    into.mkdir()
    with pytest.raises(provision.ProvisionError, match="archive"):
        provision.extract(archive, into)
    assert not (tmp_path / "escaped").exists()
    assert not (into / "node-v1" / "bin" / "escaped").is_symlink()


def test_a_file_with_a_second_name_is_refused(tmp_path: Path) -> None:
    provision = _provision()
    root = tmp_path / "env"
    root.mkdir()
    (root / "one").write_text("x")
    provision.require_one_name_each(root)
    os.link(root / "one", tmp_path / "elsewhere")
    with pytest.raises(provision.ProvisionError, match="second name"):
        provision.require_one_name_each(root)


def test_a_link_out_of_the_environment_is_refused(tmp_path: Path) -> None:
    provision = _provision()
    root = tmp_path / "env"
    (root / "bin").mkdir(parents=True)
    (root / "bin" / "tool").write_text("x")
    os.symlink("tool", root / "bin" / "alias")
    os.symlink(root / "bin" / "tool", root / "bin" / "absolute")
    provision.require_links_inside(root)
    os.symlink(tmp_path, root / "bin" / "out")
    with pytest.raises(provision.ProvisionError, match="outside"):
        provision.require_links_inside(root)


def test_the_finished_environment_is_left_read_only(tmp_path: Path) -> None:
    provision = _provision()
    root = tmp_path / "env"
    (root / "lib").mkdir(parents=True)
    (root / "lib" / "a.py").write_text("x")
    (root / "lib" / "tool").write_text("x")
    (root / "lib" / "tool").chmod(0o755)
    provision.make_read_only(root)
    try:
        for path in (root, root / "lib", root / "lib" / "a.py", root / "lib" / "tool"):
            assert path.stat().st_mode & 0o222 == 0, path
        assert (root / "lib" / "tool").stat().st_mode & 0o100
    finally:
        for path in (root, root / "lib"):
            path.chmod(0o755)


def test_platformio_is_quiet_and_its_offline_check_refuses_every_download(tmp_path: Path) -> None:
    provision = _provision()
    online = provision.pio_environment(tmp_path / "core", tmp_path / "work", offline=False)
    offline = provision.pio_environment(tmp_path / "core", tmp_path / "work", offline=True)
    for env in (online, offline):
        assert env.get("PLATFORMIO_CORE_DIR") == str(tmp_path / "core")
        assert env.get("PLATFORMIO_SETTING_ENABLE_TELEMETRY") == "no"
        assert int(env.get("PLATFORMIO_SETTING_CHECK_PLATFORMIO_INTERVAL", "0")) >= 3650
    assert not {"HTTP_PROXY", "HTTPS_PROXY", "ALL_PROXY"} & set(online)
    for name in ("HTTP_PROXY", "HTTPS_PROXY", "ALL_PROXY"):
        assert offline.get(name) == "http://127.0.0.1:9"


# ---- the AVR simulator ------------------------------------------------------------------------

#: avr8js 0.21.1 as the npm registry publishes it (MIT, no dependencies of its own).
AVR8JS_INTEGRITY = (
    "sha512-lS1vPaB0gB2GXoPrHFQOUG/5CRORjvnmjbs8SiPZdJpt4HkV0+v6HnNeXxo/X9lPqumqphls2Qyql8zsw9rBaw"
    "=="
)


def test_the_simulator_is_locked_to_avr8js_alone_with_its_integrity_hash() -> None:
    rig = TOOLENV / "avrsim"
    package = json.loads((rig / "package.json").read_text(encoding="utf-8"))
    assert package["dependencies"] == {"avr8js": "0.21.1"}
    assert package["type"] == "module"
    assert "devDependencies" not in package and "scripts" not in package
    lock = json.loads((rig / "package-lock.json").read_text(encoding="utf-8"))
    assert lock["lockfileVersion"] == 3
    entries = {name: entry for name, entry in lock["packages"].items() if name}
    assert entries == {
        "node_modules/avr8js": {
            "version": "0.21.1",
            "resolved": "https://registry.npmjs.org/avr8js/-/avr8js-0.21.1.tgz",
            "integrity": AVR8JS_INTEGRITY,
            "license": "MIT",
            "engines": {"node": ">= 20.19.0", "npm": ">= 10.0.0"},
        }
    }


def test_the_simulator_s_files_are_copied_in_with_its_launcher_executable_and_no_link(
    tmp_path: Path,
) -> None:
    provision = _provision()
    dest = tmp_path / "env"
    dest.mkdir()
    provision.copy_avrsim(dest)
    rig = TOOLENV / "avrsim"
    expected = {"package.json", "package-lock.json", "bin/avrsim"}
    expected |= {f"src/{path.name}" for path in (rig / "src").glob("*.js")}
    copied = {
        str(path.relative_to(dest / "avrsim"))
        for path in (dest / "avrsim").rglob("*")
        if path.is_file()
    }
    assert copied == expected
    for name in expected:
        path = dest / "avrsim" / name
        assert not path.is_symlink() and path.stat().st_nlink == 1, name
        assert path.read_bytes() == (rig / name).read_bytes(), name
    assert (dest / "avrsim" / "bin" / "avrsim").stat().st_mode & 0o111 == 0o111
    assert not (dest / "avrsim" / "src" / "cli.js").stat().st_mode & 0o111


def test_the_environment_records_every_file_its_simulator_was_built_from() -> None:
    provision = _provision()
    built = provision.built_from()
    rig = {"avrsim/package.json", "avrsim/package-lock.json", "avrsim/bin/avrsim"}
    rig |= {f"avrsim/src/{path.name}" for path in (TOOLENV / "avrsim" / "src").glob("*.js")}
    assert rig <= set(built)
    assert {"pyproject.toml", "uv.lock", "pins.json", "session.json",
            "platformio-server/package-lock.json"} <= set(built)  # fmt: skip
    for name in built:
        assert (TOOLENV / name).is_file(), name


def _summaries() -> tuple[dict[str, object], dict[str, object]]:
    balboa = {
        "timer1": {"icr1": 400},
        "pwm": {
            "PB5": {"period_cycles": {"count": 19_970, "mean": 800.0}, "frequency_hz": 20_000.0}
        },
    }
    timing = {
        "usart1": {"text": "W:69 G:58 L:14 R:-7\r\nW:69 G:58 L:30 R:-15\r\n"},
        "imu": {"registers_written": {"CTRL2_G": 0x58}, "whoami_reads": 100},
        "encoders": {"counts": {"left": 30, "right": -15}},
        "probes": {"update": {"entries": 100, "period_cycles": {"count": 99, "mean": 159_722.6}}},
    }
    return balboa, timing


def test_the_simulator_s_self_check_takes_the_fixtures_known_answers() -> None:
    provision = _provision()
    balboa, timing = _summaries()
    answers = provision.avrsim_answers(balboa, timing)
    assert answers == {
        "oc1a_frequency_hz": 20_000.0,
        "icr1": 400,
        "who_am_i": "69",
        "ctrl2_g": "58",
        "encoder_counts": {"left": 30, "right": -15},
        "update_period_cycles": 159_722.6,
    }


WRONG_ANSWERS = [
    ("PWM off by a percent", ("balboa", "pwm", "PB5", "period_cycles", "mean"), 809.0, "OC1A"),
    ("no PWM at all", ("balboa", "pwm"), {}, "OC1A"),
    ("another top", ("balboa", "timer1", "icr1"), 255, "ICR1"),
    ("another WHO_AM_I", ("timing", "usart1", "text"), "W:6A G:58 L:30 R:-15\r\n", "printed"),
    ("nothing printed", ("timing", "usart1", "text"), "", "fixture printed"),
    ("CTRL2_G not written", ("timing", "imu", "registers_written"), {}, "CTRL2_G"),
    ("a count lost", ("timing", "encoders", "counts", "left"), 29, "encoder"),
    ("a slow update", ("timing", "probes", "update", "period_cycles", "mean"), 158_000.0, "update"),
    ("too few updates", ("timing", "probes", "update", "entries"), 50, "update"),
]  # fmt: skip


@pytest.mark.parametrize(
    ("why", "path", "value", "says"), WRONG_ANSWERS, ids=[w[0] for w in WRONG_ANSWERS]
)
def test_a_self_check_answer_that_is_not_the_known_one_stops_provisioning(
    why: str, path: tuple[str, ...], value: object, says: str
) -> None:
    provision = _provision()
    balboa, timing = _summaries()
    target: dict[str, object] = {"balboa": balboa, "timing": timing}
    for key in path[:-1]:
        target = target[key]  # type: ignore[assignment]
    target[path[-1]] = value
    with pytest.raises(provision.ProvisionError, match=says):
        provision.avrsim_answers(balboa, timing)


# ---- the session file ------------------------------------------------------------------------


def test_the_session_file_is_one_the_harness_holds_and_names_what_provisioning_makes() -> None:
    from physgate.toolenv.session import SessionWiring

    wiring = SessionWiring.model_validate_json((TOOLENV / "session.json").read_text("utf-8"))
    # The programs are the environment's own scripts, and the links lead into the store
    # provisioning fills, each by its directory there.
    assert wiring.programs == {
        "pio": "venv/bin/pio",
        "platformio": "venv/bin/platformio",
        "avrsim": "avrsim/bin/avrsim",
    }
    assert set(wiring.links.values()) == {
        f"platformio/{n}" for n in ("platforms", "packages", "lib")
    }
    for link in wiring.links:
        assert link.split("/")[0] in wiring.directories, link
    # Nothing a build or a plot writes goes anywhere but the session's temporary directory,
    # and nothing phones home or opens a window.
    variables = wiring.variables
    for name in ("CORE_DIR", "BUILD_DIR", "WORKSPACE_DIR", "CACHE_DIR"):
        assert variables[f"PLATFORMIO_{name}"].startswith("{temp}/"), name
    assert variables["MPLCONFIGDIR"].startswith("{temp}/")
    assert variables["MPLBACKEND"] == "Agg"
    assert variables["PLATFORMIO_SETTING_ENABLE_TELEMETRY"] == "no"
    assert int(variables["PLATFORMIO_SETTING_CHECK_PLATFORMIO_INTERVAL"]) >= 36500


def test_provisioning_puts_the_session_file_at_the_environment_s_root(tmp_path: Path) -> None:
    provision = _provision()
    dest = tmp_path / "env"
    dest.mkdir()
    provision.session_file(dest)
    assert (dest / "session.json").read_bytes() == (TOOLENV / "session.json").read_bytes()
    assert not (dest / "session.json").is_symlink()
    assert (dest / "session.json").stat().st_nlink == 1
