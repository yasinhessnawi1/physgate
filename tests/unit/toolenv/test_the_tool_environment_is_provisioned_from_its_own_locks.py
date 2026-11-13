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
    assert policy.strip() == "profile: build_only"


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


# ---- the session file ------------------------------------------------------------------------


def test_the_session_file_is_one_the_harness_holds_and_names_what_provisioning_makes() -> None:
    from physgate.toolenv.session import SessionWiring

    wiring = SessionWiring.model_validate_json((TOOLENV / "session.json").read_text("utf-8"))
    # The programs are the environment's own scripts, and the links lead into the store
    # provisioning fills, each by its directory there.
    assert set(wiring.programs.values()) == {"venv/bin/pio", "venv/bin/platformio"}
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
