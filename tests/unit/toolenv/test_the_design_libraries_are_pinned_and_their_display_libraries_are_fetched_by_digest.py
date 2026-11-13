"""The design libraries are pins of the tool environment; what the kernel links comes by digest.

The CAD library and its kernel wheel are a group of exact pins in the environment's own
project, in its lock with a hash for every file, installed by default. On a headless Linux the
kernel's library links two display libraries the host need not have; with what those need in
turn that is nine distribution packages, each pinned in ``pins.json`` by file name, version and
sha256 before anything is fetched. Provisioning fetches each, refuses one whose bytes differ,
unpacks its file tree into the environment, and links the library it provides into the one
directory the kernel's own run path searches, so no session needs a variable set and no host
needs anything installed. The script's judgements are tested here on their own; building a
real environment is the integration test's.
"""

from __future__ import annotations

import importlib.util
import json
import os
import platform
import re
import subprocess
import sys
import tarfile
import tomllib
from collections.abc import Callable
from pathlib import Path
from types import ModuleType

import pytest

from physgate.toolenv.manifest import manifest

REPO = Path(__file__).resolve().parents[3]
TOOLENV = REPO / "toolenv"

#: The CAD library and the kernel wheel it is used with, each an exact pin.
DESIGN = {"build123d": "0.13.0", "cadquery-ocp-novtk": "8.0.1.1.0"}
#: The library each pinned distribution package provides to the kernel.
PROVIDED = {
    "libgl1": "libGL.so.1",
    "libglvnd0": "libGLdispatch.so.0",
    "libglx0": "libGLX.so.0",
    "libx11-6": "libX11.so.6",
    "libxcb1": "libxcb.so.1",
    "libxau6": "libXau.so.6",
    "libxdmcp6": "libXdmcp.so.6",
    "libbsd0": "libbsd.so.0",
    "libmd0": "libmd.so.0",
}
KERNEL_LIBRARIES = "cadquery_ocp_novtk.libs"


def _provision() -> ModuleType:
    spec = importlib.util.spec_from_file_location("toolenv_provision", TOOLENV / "provision.py")
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def _pins() -> dict[str, object]:
    loaded = json.loads((TOOLENV / "pins.json").read_text(encoding="utf-8"))
    assert isinstance(loaded, dict)
    return loaded


def _raised(call: Callable[[], object]) -> BaseException | None:
    """What ``call`` raised, of any kind, so that a wrong error fails an assertion too."""
    try:
        call()
    except Exception as exc:  # noqa: BLE001 - every kind is wanted here
        return exc
    return None


def _package(name: str = "libgl1", **changed: object) -> dict[str, object]:
    package: dict[str, object] = {
        "package": name,
        "version": "1.0-1",
        "file": f"{name}_1.0-1_amd64.deb",
        "sha256": "0" * 64,
        "provides": PROVIDED[name],
    }
    return package | changed


# ---- the pins ---------------------------------------------------------------------------------


def test_the_design_libraries_are_a_group_of_exact_pins_installed_by_default() -> None:
    project = tomllib.loads((TOOLENV / "pyproject.toml").read_text(encoding="utf-8"))
    group = project.get("dependency-groups", {}).get("design", [])
    assert sorted(group) == sorted(f"{name}=={version}" for name, version in DESIGN.items())
    assert project["tool"]["uv"].get("default-groups") == ["design"]


def test_the_lock_holds_the_design_libraries_with_a_hashed_wheel_for_each_platform() -> None:
    lock = tomllib.loads((TOOLENV / "uv.lock").read_text(encoding="utf-8"))
    found = {package["name"]: package for package in lock["package"]}
    for name, version in DESIGN.items():
        assert found.get(name, {}).get("version") == version, name
    kernel = [wheel["url"].rsplit("/", 1)[-1] for wheel in found["cadquery-ocp-novtk"]["wheels"]]
    for tag in ("cp312-cp312-macosx_11_0_arm64", "cp312-cp312-manylinux_2_28_x86_64"):
        assert any(tag in name for name in kernel), tag
    # No design library is built from source at provisioning: each one the two pins bring in
    # comes as a wheel, by hash.
    waiting, added = list(DESIGN), set()
    while waiting:
        name = waiting.pop()
        if name not in added:
            added.add(name)
            waiting += [dep["name"] for dep in found[name].get("dependencies", [])]
    assert len(added) > 40
    for name in sorted(added):
        wheels = found[name].get("wheels", [])
        assert wheels, f"{name} has no wheel"
        for wheel in wheels:
            assert re.fullmatch(r"sha256:[0-9a-f]{64}", wheel["hash"]), name


def test_nine_display_library_packages_are_pinned_each_by_file_version_and_digest() -> None:
    libraries = _pins().get("system_libraries")
    assert isinstance(libraries, dict), "the pins name no system libraries"
    assert libraries.get("placed_beside") == KERNEL_LIBRARIES
    packages = libraries.get("linux-x86_64")
    assert isinstance(packages, list)
    assert {p["package"]: p["provides"] for p in packages} == PROVIDED
    for package in packages:
        assert set(package) == {"package", "version", "file", "sha256", "provides"}
        version = package["version"]
        assert re.fullmatch(r"[0-9][0-9a-z.+~-]*", version), package
        assert package["file"] == f"{package['package']}_{version}_amd64.deb"
        assert re.fullmatch(r"[0-9a-f]{64}", package["sha256"]), package
        assert package["sha256"] != "0" * 64
    assert len({p["sha256"] for p in packages}) == len(PROVIDED)


def test_the_script_names_the_licence_of_what_the_design_libraries_add() -> None:
    licences = getattr(_provision(), "DESIGN_LICENCES", {})
    assert set(DESIGN) | {"system libraries"} <= set(licences)
    assert "LGPL" in licences["cadquery-ocp-novtk"]


# ---- which machine gets which packages --------------------------------------------------------


def test_linux_x86_64_gets_the_nine_packages_and_macos_none() -> None:
    provision = _provision()
    assert provision.system_packages(_pins(), "Darwin", "arm64") == []
    found = provision.system_packages(_pins(), "Linux", "x86_64")
    assert {p["package"]: p["provides"] for p in found} == PROVIDED
    pinned = _pins()["system_libraries"]["linux-x86_64"]  # type: ignore[index]
    assert [p["sha256"] for p in found] == [p["sha256"] for p in pinned]
    assert [p["file"] for p in found] == [p["file"] for p in pinned]


@pytest.mark.parametrize(("system", "machine"), [("Linux", "aarch64"), ("Linux", "riscv64")])
def test_a_linux_no_packages_are_pinned_for_is_refused(system: str, machine: str) -> None:
    provision = _provision()
    with pytest.raises(provision.ProvisionError, match="no pinned system libraries"):
        provision.system_packages(_pins(), system, machine)


def test_pins_that_name_no_packages_for_a_machine_that_needs_them_are_refused() -> None:
    provision = _provision()
    empty: list[dict[str, object]] = [
        {},
        {"system_libraries": {}},
        {"system_libraries": {"linux-x86_64": []}},
    ]
    for pins in empty:
        with pytest.raises(provision.ProvisionError, match="names no system libraries"):
            provision.system_packages(pins, "Linux", "x86_64")


@pytest.mark.parametrize("missing", ["package", "version", "file", "sha256", "provides"])
def test_a_pin_without_one_of_its_fields_is_refused(missing: str) -> None:
    provision = _provision()
    package = _package()
    del package[missing]
    pins = {"system_libraries": {"linux-x86_64": [package]}}
    found = _raised(lambda: provision.system_packages(pins, "Linux", "x86_64"))
    assert isinstance(found, provision.ProvisionError), repr(found)
    assert "pin names" in str(found)


@pytest.mark.parametrize(
    "changed",
    [{"file": "../libgl1_1.0-1_amd64.deb"}, {"file": "pool/x.deb"}, {"provides": "../libGL.so.1"}],
)
def test_a_pin_that_names_a_path_is_refused(changed: dict[str, object]) -> None:
    provision = _provision()
    pins = {"system_libraries": {"linux-x86_64": [_package() | changed]}}
    with pytest.raises(provision.ProvisionError, match="never paths"):
        provision.system_packages(pins, "Linux", "x86_64")


# ---- a package is held to its digest before it is unpacked ------------------------------------


def _as_linux(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(platform, "system", lambda: "Linux")
    monkeypatch.setattr(platform, "machine", lambda: "x86_64")


def _one_pin(body: bytes) -> tuple[dict[str, object], dict[str, object]]:
    import hashlib

    package = _package(sha256=hashlib.sha256(body).hexdigest())
    pins: dict[str, object] = {
        "system_libraries": {"placed_beside": KERNEL_LIBRARIES, "linux-x86_64": [package]}
    }
    return pins, package


def test_a_kept_package_whose_bytes_changed_is_refused_and_nothing_is_unpacked(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    provision = _provision()
    _as_linux(monkeypatch)
    pins, package = _one_pin(b"the package as pinned")
    kept = tmp_path / "cache" / "system-libraries" / str(package["file"])
    kept.parent.mkdir(parents=True)
    kept.write_bytes(b"other bytes under the pinned name")
    read: list[Path] = []
    monkeypatch.setattr(provision, "_package_tree", lambda path, work: read.append(path))
    dest = tmp_path / "env"
    dest.mkdir()
    found = _raised(lambda: provision._system_libraries(dest, pins, tmp_path / "cache", tmp_path))
    assert read == []
    assert isinstance(found, provision.ProvisionError) and "digest" in str(found), repr(found)
    assert list((dest / "system-libraries").iterdir()) == []


def test_a_fetched_package_whose_bytes_differ_is_refused_and_never_kept(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    provision = _provision()
    _as_linux(monkeypatch)
    pins, package = _one_pin(b"the package as pinned")
    asked: list[str] = []

    def fetch(url: str, into: Path, work: Path) -> Path:
        asked.append(url)
        into.mkdir(parents=True)
        (into / "fetched").write_bytes(b"what a changed mirror serves")
        return into / "fetched"

    monkeypatch.setattr(provision, "fetch", fetch)
    read: list[Path] = []
    monkeypatch.setattr(provision, "_package_tree", lambda path, work: read.append(path))
    dest = tmp_path / "env"
    dest.mkdir()
    with pytest.raises(provision.ProvisionError, match="digest"):
        provision._system_libraries(dest, pins, tmp_path / "cache", tmp_path)
    # Asked for by its file name alone, over the one source, and not kept for a later run.
    assert asked == [f"{provision.PACKAGE_FILES}/{package['file']}"]
    assert asked[0].startswith("https://")
    assert read == []
    assert not (tmp_path / "cache" / "system-libraries" / str(package["file"])).exists()


@pytest.mark.parametrize("failure", ["not served", "timed out"])
def test_a_package_the_archive_does_not_serve_is_named_with_its_digest_and_nothing_is_kept(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, failure: str
) -> None:
    provision = _provision()
    _as_linux(monkeypatch)
    pins, package = _one_pin(b"the package as pinned")
    asked: list[list[str]] = []

    def run(argv: list[str], env: dict[str, str], **more: object) -> str:
        # The download program fails as it does when the archive has dropped a file, or when
        # the step's time runs out: provisioning's own step runner says so in its own words.
        asked.append(list(argv))
        if failure == "timed out":
            raise subprocess.TimeoutExpired(argv, provision.STEP_TIMEOUT_S)
        raise provision.ProvisionError("curl -fsSL --proto failed:\ncurl: (22) error: 404")

    monkeypatch.setattr(provision, "run", run)
    read: list[Path] = []
    monkeypatch.setattr(provision, "_package_tree", lambda path, work: read.append(path))
    dest = tmp_path / "env"
    dest.mkdir()
    found = _raised(lambda: provision._system_libraries(dest, pins, tmp_path / "cache", tmp_path))
    assert len(asked) == 1 and asked[0][-1].endswith(f"/{package['file']}"), asked
    assert isinstance(found, provision.ProvisionError), repr(found)
    message = str(found)
    assert str(package["file"]) in message and str(package["sha256"]) in message, message
    assert read == []
    assert not (tmp_path / "cache" / "system-libraries" / str(package["file"])).exists()


def test_a_package_that_matches_its_pin_is_kept_unpacked_and_its_library_placed(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    provision = _provision()
    _as_linux(monkeypatch)
    body = b"the package as pinned"
    pins, package = _one_pin(body)

    def fetch(url: str, into: Path, work: Path) -> Path:
        into.mkdir(parents=True)
        (into / "fetched").write_bytes(body)
        return into / "fetched"

    def tree(path: Path, work: Path) -> Path:
        assert path.read_bytes() == body
        return _tree(tmp_path, {"./usr/lib/x86_64-linux-gnu/libGL.so.1.7.0": b"elf"}, links=True)

    monkeypatch.setattr(provision, "fetch", fetch)
    monkeypatch.setattr(provision, "_package_tree", tree)
    dest = tmp_path / "env"
    home = dest / "venv" / "lib" / "python3.12" / "site-packages" / KERNEL_LIBRARIES
    home.mkdir(parents=True)
    found = provision._system_libraries(dest, pins, tmp_path / "cache", tmp_path)
    assert [p["package"] for p in found] == ["libgl1"]
    assert (tmp_path / "cache" / "system-libraries" / str(package["file"])).read_bytes() == body
    assert (home / "libGL.so.1").resolve().read_bytes() == b"elf"


def test_macos_fetches_no_package_and_makes_no_directory(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    provision = _provision()
    monkeypatch.setattr(platform, "system", lambda: "Darwin")
    monkeypatch.setattr(platform, "machine", lambda: "arm64")
    asked: list[str] = []
    monkeypatch.setattr(provision, "fetch", lambda url, into, work: asked.append(url))
    dest = tmp_path / "env"
    dest.mkdir()
    assert provision._system_libraries(dest, _pins(), tmp_path / "cache", tmp_path) == []
    assert asked == []
    assert list(dest.iterdir()) == []


# ---- a package's file tree ---------------------------------------------------------------------


def _tree(tmp_path: Path, files: dict[str, bytes], *, links: bool = False) -> Path:
    archive = tmp_path / "tree.tar"
    with tarfile.open(archive, "w") as tar:
        for name, body in files.items():
            payload = tmp_path / "payload"
            payload.write_bytes(body)
            tar.add(payload, arcname=name)
            if links:
                member = tarfile.TarInfo(name.rsplit(".", 2)[0])
                member.type, member.linkname = tarfile.SYMTYPE, name.rsplit("/", 1)[-1]
                tar.addfile(member)
    return archive


def test_a_package_tree_is_unpacked_with_its_links(tmp_path: Path) -> None:
    provision = _provision()
    archive = _tree(tmp_path, {"./usr/lib/x86_64-linux-gnu/libGL.so.1.7.0": b"elf"}, links=True)
    into = tmp_path / "into"
    into.mkdir()
    provision.unpack_tree(archive, into)
    library = into / "usr" / "lib" / "x86_64-linux-gnu"
    assert (library / "libGL.so.1.7.0").read_bytes() == b"elf"
    assert os.readlink(library / "libGL.so.1") == "libGL.so.1.7.0"


@pytest.mark.parametrize("kind", ["file", "link", "device"])
def test_a_package_tree_member_that_leaves_its_directory_is_refused(
    tmp_path: Path, kind: str
) -> None:
    provision = _provision()
    archive = tmp_path / "bad.tar"
    payload = tmp_path / "payload"
    payload.write_text("x")
    with tarfile.open(archive, "w") as tar:
        if kind == "file":
            tar.add(payload, arcname="../escaped")
        elif kind == "link":
            member = tarfile.TarInfo("usr/lib/escaped")
            member.type, member.linkname = tarfile.SYMTYPE, str(payload)
            tar.addfile(member)
        else:
            member = tarfile.TarInfo("usr/lib/device")
            member.type = tarfile.CHRTYPE
            tar.addfile(member)
    into = tmp_path / "into"
    into.mkdir()
    with pytest.raises(provision.ProvisionError, match="package tree"):
        provision.unpack_tree(archive, into)
    assert not (tmp_path / "escaped").exists()
    assert not (into / "usr" / "lib" / "escaped").is_symlink()
    assert not (into / "usr" / "lib" / "device").exists()


# ---- where the kernel finds them --------------------------------------------------------------


def _unpacked(tmp_path: Path, names: dict[str, str]) -> tuple[Path, Path]:
    """An environment with the kernel's library directory and each library unpacked."""
    dest = tmp_path / "env"
    home = dest / "venv" / "lib" / "python3.12" / "site-packages" / KERNEL_LIBRARIES
    home.mkdir(parents=True)
    (home / "libTKernel.so.8").write_text("the kernel's own")
    library = dest / "system-libraries" / "usr" / "lib" / "x86_64-linux-gnu"
    library.mkdir(parents=True)
    for soname in names.values():
        (library / f"{soname}.7.0").write_text(f"the bytes of {soname}")
        os.symlink(f"{soname}.7.0", library / soname)
    return dest, home


def test_each_library_is_linked_into_the_kernel_s_own_directory_by_a_relative_link(
    tmp_path: Path,
) -> None:
    provision = _provision()
    dest, home = _unpacked(tmp_path, PROVIDED)
    packages = [_package(name) for name in PROVIDED]
    placed = provision.place_beside_kernel(dest, packages, KERNEL_LIBRARIES)
    assert sorted(placed) == sorted(PROVIDED.values())
    for soname in PROVIDED.values():
        link = home / soname
        assert link.is_symlink(), soname
        assert not os.readlink(link).startswith("/"), "an absolute link breaks on a restored path"
        assert link.read_text() == f"the bytes of {soname}"
    assert sorted(p.name for p in home.iterdir()) == sorted([*PROVIDED.values(), "libTKernel.so.8"])
    # The environment is still one the script and the harness accept: every link stays inside.
    provision.require_links_inside(dest)
    moved = tmp_path / "restored"
    dest.rename(moved)
    assert manifest([moved]).entries > 2 * len(PROVIDED)
    assert (
        moved / "venv" / "lib" / "python3.12" / "site-packages" / KERNEL_LIBRARIES / "libGL.so.1"
    ).read_text() == "the bytes of libGL.so.1"


def test_a_package_that_did_not_provide_its_library_stops_provisioning(tmp_path: Path) -> None:
    provision = _provision()
    dest, home = _unpacked(tmp_path, {"libgl1": "libGL.so.1"})
    with pytest.raises(provision.ProvisionError, match=r"did not provide libX11\.so\.6"):
        provision.place_beside_kernel(dest, [_package("libx11-6")], KERNEL_LIBRARIES)
    assert not (home / "libX11.so.6").is_symlink()


def test_a_library_whose_link_leads_nowhere_stops_provisioning(tmp_path: Path) -> None:
    provision = _provision()
    dest, _ = _unpacked(tmp_path, {"libgl1": "libGL.so.1"})
    (dest / "system-libraries" / "usr" / "lib" / "x86_64-linux-gnu" / "libGL.so.1.7.0").unlink()
    with pytest.raises(provision.ProvisionError, match="did not provide"):
        provision.place_beside_kernel(dest, [_package("libgl1")], KERNEL_LIBRARIES)


@pytest.mark.parametrize("copies", [0, 2])
def test_the_kernel_s_directory_must_be_there_exactly_once(tmp_path: Path, copies: int) -> None:
    provision = _provision()
    dest, home = _unpacked(tmp_path, {"libgl1": "libGL.so.1"})
    if copies == 0:
        home.rename(home.with_name("another.libs"))
    else:
        other = dest / "venv" / "lib" / "python3.13" / "site-packages" / KERNEL_LIBRARIES
        other.mkdir(parents=True)
    with pytest.raises(provision.ProvisionError, match="was not found once"):
        provision.place_beside_kernel(dest, [_package("libgl1")], KERNEL_LIBRARIES)


# ---- the self-check: the loader took them from the environment --------------------------------


def test_a_library_the_loader_took_from_the_host_or_never_loaded_is_named(tmp_path: Path) -> None:
    provision = _provision()
    dest = tmp_path / "env"
    inside = dest / "system-libraries" / "usr" / "lib" / "x86_64-linux-gnu"
    inside.mkdir(parents=True)
    packages = [_package("libgl1"), _package("libx11-6")]
    ours = [str(inside / "libGL.so.1.7.0"), str(inside / "libX11.so.6.4.0")]
    other = [str(dest / "venv" / "lib" / "libTKernel.so.8"), "/usr/lib/libc.so.6", "[heap]"]
    assert provision.mapped_outside([*ours, *other], packages, dest) == []
    host = "/usr/lib/x86_64-linux-gnu/libGL.so.1.7.0"
    assert provision.mapped_outside([host, ours[1], *other], packages, dest) == [host]
    assert provision.mapped_outside([ours[0], *other], packages, dest) == [
        "libX11.so.6: not loaded"
    ]
    # A directory whose name only starts as the environment's does is outside it.
    beside = str(tmp_path / "env-other" / "libGL.so.1.7.0")
    assert provision.mapped_outside([beside, ours[1]], packages, dest) == [beside]
    assert provision.mapped_outside(other, [], dest) == []


def test_the_design_check_is_given_no_network_and_no_inherited_setting(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    provision = _provision()
    seen: dict[str, object] = {}

    def run(argv: list[str], env: dict[str, str], **more: object) -> str:
        seen["argv"], seen["env"] = list(argv), dict(env)
        part = {"libraries": dict(DESIGN), "geometry_hash": "sha256:" + "a" * 64}
        return json.dumps({"part": part, "load_case": {"kind": "load_case"}, "mapped": []})

    monkeypatch.setattr(provision, "run", run)
    dest = tmp_path / "env"
    (dest / "project").mkdir(parents=True)
    (dest / "project" / "pyproject.toml").write_bytes((TOOLENV / "pyproject.toml").read_bytes())
    monkeypatch.setenv("LD_LIBRARY_PATH", "/somewhere")
    found = provision._check_design(dest, [], tmp_path)
    assert found["part"]["geometry_hash"] == "sha256:" + "a" * 64
    argv, env = seen["argv"], seen["env"]
    assert isinstance(argv, list) and isinstance(env, dict)
    assert argv[:3] == [str(dest / "venv" / "bin" / "python"), "-I", "-c"]
    assert argv[4] == str(dest / "helpers")
    for name in ("HTTP_PROXY", "HTTPS_PROXY", "ALL_PROXY"):
        assert env.get(name) == "http://127.0.0.1:9"
    assert env.get("HOME") == str(tmp_path / "home")
    assert "LD_LIBRARY_PATH" not in env and "DISPLAY" not in env


def test_a_design_library_at_another_version_stops_provisioning(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    provision = _provision()
    part = {"libraries": DESIGN | {"cadquery-ocp-novtk": "8.0.1.1.1"}}
    answer = json.dumps({"part": part, "load_case": {}, "mapped": []})
    monkeypatch.setattr(provision, "run", lambda argv, env, **more: answer)
    dest = tmp_path / "env"
    (dest / "project").mkdir(parents=True)
    (dest / "project" / "pyproject.toml").write_bytes((TOOLENV / "pyproject.toml").read_bytes())
    with pytest.raises(provision.ProvisionError, match="not the pinned version"):
        provision._check_design(dest, [], tmp_path)


def test_a_display_library_served_by_the_host_stops_provisioning(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    provision = _provision()
    mapped = ["/usr/lib/x86_64-linux-gnu/libGL.so.1.7.0"]
    answer = json.dumps({"part": {"libraries": DESIGN}, "load_case": {}, "mapped": mapped})
    monkeypatch.setattr(provision, "run", lambda argv, env, **more: answer)
    dest = tmp_path / "env"
    (dest / "project").mkdir(parents=True)
    (dest / "project" / "pyproject.toml").write_bytes((TOOLENV / "pyproject.toml").read_bytes())
    with pytest.raises(provision.ProvisionError, match="not the environment's"):
        provision._check_design(dest, [_package("libgl1")], tmp_path)


# ---- the helpers are copied in, as the servers are --------------------------------------------


def test_the_helpers_are_copied_into_the_environment_byte_for_byte(tmp_path: Path) -> None:
    provision = _provision()
    dest = tmp_path / "env"
    dest.mkdir()
    copied = provision._helpers(dest)
    own = sorted(p.name for p in (TOOLENV / "helpers").glob("*.py"))
    assert copied == own
    assert {"geometry.py", "result_file.py", "structure.py"} <= set(own)
    assert sorted(p.name for p in (dest / "helpers").iterdir()) == own
    for name in own:
        assert (dest / "helpers" / name).read_bytes() == (TOOLENV / "helpers" / name).read_bytes()
