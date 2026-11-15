"""KiCad's command-line program is provisioned by digest, in a root of its own, copied apart.

KiCad is a separate program under the GPL: it is fetched and run apart from the harness, never
linked into it, and the provisioning script names its licence. Its release is pinned in
``pins.json`` for each machine by file name, ``https`` address, exact size and sha256, all
recorded before anything is fetched. The download is bounded by the pin's own size (the release
is larger than the bound every other download has), refused unless its bytes are the pinned
ones, and kept in the cache only once they matched.

The release's tree is not one the environment's measure accepts as it comes: on Linux the
unpacked image gives one program file several names, and the measure refuses a file with a
second name (a write through one name changes the other unseen). So the tree is copied, never
linked: every regular file is written anew under each of its names, a link is kept only where it
resolves inside the tree, and anything else (a link out of the tree, nowhere or round in a loop;
a pipe, a socket, a device) stops provisioning with its name. The parts the pin drops (the
demonstration projects) are not copied. The copy lies in a root of its own, never inside the
tool environment's other root nor around it, nor in the harness checkout.

Before the root is left read-only, the program is asked its version with every download refused
and its configuration in provisioning's own scratch, and it must answer the pinned version. The
script's judgements are tested here on stand-ins; the real release is the integration test's.
"""

from __future__ import annotations

import hashlib
import importlib.util
import inspect
import json
import os
import stat
import sys
import tarfile
from collections.abc import Callable
from pathlib import Path
from types import ModuleType

import pytest

from physgate.toolenv.exceptions import ToolEnvironmentError
from physgate.toolenv.manifest import manifest

REPO = Path(__file__).resolve().parents[3]
TOOLENV = REPO / "toolenv"
VERSION = "10.0.8"
LINUX_FILE = "kicad-10.0.8-x86_64-lite.AppImage.tar"
LINUX = {
    "file": LINUX_FILE,
    "url": f"https://kicad-downloads.s3.cern.ch/appimage/stable/{LINUX_FILE}",
    "bytes": 316_538_880,
    "sha256": "abb59cee9f9782736c1b9a92e3ab08b31320ee01d72a6f9442a07fdef71b87d0",
}
MAC_FILE = "kicad-unified-universal-10.0.8.dmg"
MAC = {
    "file": MAC_FILE,
    "url": f"https://github.com/KiCad/kicad-source-mirror/releases/download/10.0.8/{MAC_FILE}",
    "bytes": 1_405_602_755,
    "sha256": "501d3e2933a385f1833497469f55326662df7e5d40401239826c40d6fa583f16",
}
#: What of the macOS application is kept: measured to run the command-line program read-only.
MAC_KEPT = [
    "Contents/Frameworks",
    "Contents/MacOS",
    "Contents/PlugIns",
    "Contents/Resources",
    "Contents/SharedSupport/footprints",
    "Contents/SharedSupport/resources",
    "Contents/SharedSupport/schemas",
    "Contents/SharedSupport/symbols",
    "Contents/SharedSupport/template",
]


def _provision() -> ModuleType:
    spec = importlib.util.spec_from_file_location("toolenv_provision", TOOLENV / "provision.py")
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def _raised(call: Callable[[], object]) -> BaseException | None:
    """What ``call`` raised, of any kind, so that a wrong error fails an assertion too."""
    try:
        call()
    except Exception as exc:  # noqa: BLE001 - every kind is wanted here
        return exc
    return None


def _named(provision: ModuleType, name: str) -> Callable[..., object]:
    found = getattr(provision, name, None)
    assert callable(found), f"provisioning has no {name}"
    return found  # type: ignore[no-any-return]


def _refused(provision: ModuleType, call: Callable[[], object], *words: str) -> str:
    raised = _raised(call)
    assert isinstance(raised, provision.ProvisionError), repr(raised)
    for word in words:
        assert word in str(raised), (word, str(raised))
    return str(raised)


def _pins() -> dict[str, object]:
    loaded = json.loads((TOOLENV / "pins.json").read_text(encoding="utf-8"))
    assert isinstance(loaded, dict)
    return loaded


def _pin(**changed: object) -> dict[str, object]:
    pin: dict[str, object] = {
        "file": "tool.tar",
        "url": "https://example.org/releases/tool.tar",
        "bytes": 1000,
        "sha256": "a" * 64,
    }
    return {key: value for key, value in (pin | changed).items() if value is not None}


def _with(pin: dict[str, object]) -> dict[str, object]:
    return {"kicad": {"version": VERSION, "linux-x86_64": pin, "darwin-arm64": pin}}


# ---- the pin ----------------------------------------------------------------------------------


def test_kicad_is_pinned_for_both_machines_by_file_address_size_and_digest() -> None:
    kicad = _pins().get("kicad")
    assert isinstance(kicad, dict), sorted(_pins())
    assert kicad.get("version") == VERSION
    linux, mac = kicad.get("linux-x86_64"), kicad.get("darwin-arm64")
    assert isinstance(linux, dict) and isinstance(mac, dict), sorted(kicad)
    assert {key: linux.get(key) for key in LINUX} == LINUX
    assert {key: mac.get(key) for key in MAC} == MAC
    assert linux.get("dropped") == ["usr/share/kicad/demos"]
    assert mac.get("kept") == MAC_KEPT


def test_the_pin_read_for_a_machine_is_that_machine_s() -> None:
    provision = _provision()
    read = _named(provision, "kicad_pin")
    linux = read(_pins(), "Linux", "x86_64")
    mac = read(_pins(), "Darwin", "arm64")
    assert isinstance(linux, dict) and isinstance(mac, dict)
    assert {key: linux.get(key) for key in LINUX} == LINUX
    assert {key: mac.get(key) for key in MAC} == MAC


@pytest.mark.parametrize(("system", "machine"), [("Linux", "aarch64"), ("Windows", "AMD64")])
def test_a_machine_with_no_kicad_pin_is_refused(system: str, machine: str) -> None:
    provision = _provision()
    read = _named(provision, "kicad_pin")
    _refused(provision, lambda: read(_pins(), system, machine), "KiCad", system, machine)


@pytest.mark.parametrize(
    "changed",
    [
        {"bytes": None},
        {"bytes": "1000"},
        {"bytes": 0},
        {"sha256": "A" * 64},
        {"sha256": None},
        {"url": "http://example.org/releases/tool.tar"},
        {"url": "https://example.org/releases/other.tar"},
        {"file": "releases/tool.tar", "url": "https://example.org/releases/tool.tar"},
        {"extra": "a field no pin has"},
    ],
    ids=[
        "no-size",
        "size-as-text",
        "size-zero",
        "digest-not-lower-hex",
        "no-digest",
        "not-https",
        "address-names-another-file",
        "file-is-a-path",
        "unknown-field",
    ],
)
def test_a_kicad_pin_that_is_not_exactly_file_address_size_and_digest_is_refused(
    changed: dict[str, object],
) -> None:
    provision = _provision()
    read = _named(provision, "kicad_pin")
    _refused(provision, lambda: read(_with(_pin(**changed)), "Linux", "x86_64"), "KiCad")


def test_a_well_formed_stand_in_pin_is_read() -> None:
    provision = _provision()
    read = _named(provision, "kicad_pin")
    found = read(_with(_pin()), "Linux", "x86_64")
    assert isinstance(found, dict)
    assert {key: found.get(key) for key in _pin()} == _pin()


def test_the_licence_of_kicad_and_its_libraries_is_named() -> None:
    licences = _provision().DESIGN_LICENCES
    kicad = str(licences.get("kicad", ""))
    assert "GPL-3.0-or-later" in kicad, licences
    assert "CC-BY-SA-4.0" in kicad, licences


# ---- the download -----------------------------------------------------------------------------


def _argv_of_fetch(
    provision: ModuleType, monkeypatch: pytest.MonkeyPatch, tmp_path: Path, **bound: int
) -> list[str]:
    seen: list[list[str]] = []

    def ran(argv: list[str], env: dict[str, str], **_: object) -> str:
        seen.append(list(argv))
        return ""

    monkeypatch.setattr(provision, "run", ran)
    if bound:
        takes = inspect.signature(provision.fetch).parameters
        assert set(bound) <= set(takes), f"a download takes no bound of its own: {list(takes)}"
    provision.fetch("https://example.org/releases/tool.tar", tmp_path / "into", tmp_path, **bound)
    assert len(seen) == 1
    return seen[0]


def test_a_download_is_bounded_by_the_pin_s_own_size_where_it_states_one(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    provision = _provision()
    argv = _argv_of_fetch(provision, monkeypatch, tmp_path, max_bytes=316_538_880)
    assert argv[argv.index("--max-filesize") + 1] == "316538880"


def test_every_other_download_keeps_the_common_bound(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    provision = _provision()
    argv = _argv_of_fetch(provision, monkeypatch, tmp_path)
    assert argv[argv.index("--max-filesize") + 1] == str(200 << 20)
    assert provision.MAX_DOWNLOAD_BYTES == 200 << 20


def test_a_kept_release_whose_bytes_differ_from_the_pin_is_refused_naming_both_digests(
    tmp_path: Path,
) -> None:
    provision = _provision()
    kept = _named(provision, "kicad_archive")
    body = b"a release as published"
    pin = _pin(bytes=len(body), sha256=hashlib.sha256(b"other bytes").hexdigest())
    (tmp_path / "cache" / "kicad").mkdir(parents=True)
    (tmp_path / "cache" / "kicad" / "tool.tar").write_bytes(body)
    (tmp_path / "work").mkdir()
    _refused(
        provision,
        lambda: kept(pin, tmp_path / "cache", tmp_path / "work"),
        "tool.tar",
        str(pin["sha256"]),
        hashlib.sha256(body).hexdigest(),
    )


def test_a_kept_release_that_matches_is_used_without_a_fetch(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    provision = _provision()
    kept = _named(provision, "kicad_archive")
    body = b"a release as published"
    pin = _pin(bytes=len(body), sha256=hashlib.sha256(body).hexdigest())
    (tmp_path / "cache" / "kicad").mkdir(parents=True)
    (tmp_path / "cache" / "kicad" / "tool.tar").write_bytes(body)
    (tmp_path / "work").mkdir()
    monkeypatch.setattr(provision, "fetch", lambda *a, **k: pytest.fail("fetched again"))
    found = kept(pin, tmp_path / "cache", tmp_path / "work")
    assert Path(str(found)).read_bytes() == body


def test_a_fetched_release_is_bounded_by_its_pin_and_kept_only_once_it_matched(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    provision = _provision()
    kept = _named(provision, "kicad_archive")
    body = b"a release as published"
    bounds: list[object] = []

    def fetched(url: str, into: Path, work: Path, **bound: object) -> Path:
        bounds.append(bound.get("max_bytes"))
        into.mkdir(parents=True)
        (into / "tool.tar").write_bytes(b"bytes changed on the way")
        return into / "tool.tar"

    monkeypatch.setattr(provision, "fetch", fetched)
    (tmp_path / "work").mkdir()
    pin = _pin(bytes=len(body), sha256=hashlib.sha256(body).hexdigest())
    _refused(provision, lambda: kept(pin, tmp_path / "cache", tmp_path / "work"), "tool.tar")
    assert bounds == [len(body)]
    assert not (tmp_path / "cache" / "kicad" / "tool.tar").exists()


# ---- the copy the measure accepts -------------------------------------------------------------


def _copied(source: Path, into: Path, dropped: tuple[str, ...] = ()) -> object:
    provision = _provision()
    return _named(provision, "copy_apart")(source, into, dropped)


def _release(tmp_path: Path) -> Path:
    """A stand-in release tree with a file under three names, inner links and a dropped part."""
    tree = tmp_path / "release"
    (tree / "bin").mkdir(parents=True)
    (tree / "shared" / "bin").mkdir(parents=True)
    (tree / "share" / "demos" / "one").mkdir(parents=True)
    launcher = tree / "launcher"
    launcher.write_bytes(b"#!/bin/sh\necho a launcher\n")
    launcher.chmod(0o755)
    os.link(launcher, tree / "bin" / "tool-cli")
    os.link(launcher, tree / "bin" / "tool")
    (tree / "shared" / "bin" / "tool-cli").write_bytes(b"the program\n")
    (tree / "share" / "demos" / "one" / "demo.sch").write_bytes(b"a demonstration\n")
    (tree / "share" / "library.txt").write_bytes(b"a library\n")
    (tree / "AppRun").symlink_to("launcher")
    (tree / "usr").symlink_to(".")
    (tree / "lib").symlink_to("shared/bin")
    return tree


def test_a_file_with_several_names_becomes_a_file_under_each_name_with_one_name(
    tmp_path: Path,
) -> None:
    tree = _release(tmp_path)
    assert (tree / "launcher").stat().st_nlink == 3
    into = tmp_path / "copy"
    _copied(tree, into)
    for name in ("launcher", "bin/tool-cli", "bin/tool"):
        found = (into / name).lstat()
        assert stat.S_ISREG(found.st_mode), name
        assert found.st_nlink == 1, name
        assert (into / name).read_bytes() == b"#!/bin/sh\necho a launcher\n", name
        assert stat.S_IMODE(found.st_mode) & 0o111 == 0o111, name
    inodes = {(into / name).lstat().st_ino for name in ("launcher", "bin/tool-cli", "bin/tool")}
    assert len(inodes) == 3


def test_a_link_that_resolves_inside_the_tree_is_kept_with_its_text(tmp_path: Path) -> None:
    tree = _release(tmp_path)
    into = tmp_path / "copy"
    _copied(tree, into)
    for name, text in (("AppRun", "launcher"), ("usr", "."), ("lib", "shared/bin")):
        assert (into / name).is_symlink(), name
        assert os.readlink(into / name) == text, name
    assert (into / "lib" / "tool-cli").read_bytes() == b"the program\n"


def test_a_dropped_part_is_not_copied(tmp_path: Path) -> None:
    tree = _release(tmp_path)
    into = tmp_path / "copy"
    _copied(tree, into, ("share/demos",))
    assert not (into / "share" / "demos").exists()
    assert (into / "share" / "library.txt").read_bytes() == b"a library\n"


def test_a_dropped_part_may_be_a_link_out_of_the_tree_which_is_then_not_copied(
    tmp_path: Path,
) -> None:
    tree = _release(tmp_path)
    (tree / "shared" / "settings.py").symlink_to("/etc/a-host-file.py")
    into = tmp_path / "copy"
    counts = _copied(tree, into, ("usr/shared/settings.py",))
    assert not os.path.lexists(into / "shared" / "settings.py")
    assert isinstance(counts, dict) and counts.get("dropped") == ["usr/shared/settings.py"]
    assert manifest([into]).entries > 8


def test_every_link_the_measure_would_refuse_is_named_at_once(tmp_path: Path) -> None:
    tree = _release(tmp_path)
    (tree / "first").symlink_to("/etc/one")
    (tree / "share" / "second").symlink_to("../../two")
    provision = _provision()
    _refused(
        provision,
        lambda: _copied(tree, tmp_path / "copy"),
        "2 links",
        "first (/etc/one)",
        "share/second (../../two)",
    )


def test_the_copy_says_what_it_made_acceptable(tmp_path: Path) -> None:
    tree = _release(tmp_path)
    counts = _copied(tree, tmp_path / "copy", ("share/demos",))
    assert isinstance(counts, dict), counts
    assert counts.get("names_copied_apart") == 3
    assert counts.get("links_kept") == 3
    assert counts.get("dropped") == ["share/demos"]
    assert counts.get("files") == 5


def test_the_measure_refuses_the_release_and_accepts_the_copy(tmp_path: Path) -> None:
    tree = _release(tmp_path)
    with pytest.raises(ToolEnvironmentError, match="another name"):
        manifest([tree])
    into = tmp_path / "copy"
    _copied(tree, into, ("share/demos",))
    found = manifest([into])
    assert found.entries > 8


@pytest.mark.parametrize(
    ("name", "text"),
    [
        ("outside", "../../elsewhere"),
        ("absolute", "/usr/lib"),
        ("nowhere", "no-such-file"),
        ("loop-a", "loop-b"),
        ("into-dropped", "share/demos/one"),
    ],
    ids=["leads-outside", "absolute", "leads-nowhere", "loops", "into-a-dropped-part"],
)
def test_a_link_the_measure_would_refuse_stops_the_copy_with_its_name(
    tmp_path: Path, name: str, text: str
) -> None:
    tree = _release(tmp_path)
    (tmp_path / "elsewhere").write_bytes(b"outside the tree\n")
    (tree / name).symlink_to(text)
    if name == "loop-a":
        (tree / "loop-b").symlink_to("loop-a")
    provision = _provision()
    message = _refused(
        provision, lambda: _copied(tree, tmp_path / "copy", ("share/demos",)), name, "link"
    )
    assert text in message


def test_something_that_is_not_a_file_a_directory_or_a_link_stops_the_copy(
    tmp_path: Path,
) -> None:
    tree = _release(tmp_path)
    os.mkfifo(tree / "share" / "a-pipe")
    provision = _provision()
    _refused(provision, lambda: _copied(tree, tmp_path / "copy"), "a-pipe")


def test_a_dropped_part_names_a_path_inside_the_tree(tmp_path: Path) -> None:
    tree = _release(tmp_path)
    provision = _provision()
    for dropped in ("../release", "/share/demos", "share/../share/demos", "share/no-such"):

        def copy(part: str = dropped) -> object:
            return _copied(tree, tmp_path / "copy", (part,))

        _refused(provision, copy, dropped)


# ---- where the root lies ----------------------------------------------------------------------


def _root_refused(provision: ModuleType, root: Path, beside: Path | None, *words: str) -> None:
    build = _named(provision, "provision_kicad")
    _refused(
        provision, lambda: build(root, root.parent / "cache", _with(_pin()), beside=beside), *words
    )


def test_the_root_is_absolute_new_and_outside_the_checkout(tmp_path: Path) -> None:
    provision = _provision()
    _root_refused(provision, Path("relative/kicad"), None, "absolute")
    full = tmp_path / "full"
    full.mkdir()
    (full / "something").write_text("here already")
    _root_refused(provision, full, None, "empty")
    _root_refused(provision, REPO / "kicad-inside", None, "checkout")
    assert not (REPO / "kicad-inside").exists()


def test_the_root_is_never_inside_the_environment_s_other_root_nor_around_it(
    tmp_path: Path,
) -> None:
    provision = _provision()
    env = tmp_path / "pg" / "env"
    env.mkdir(parents=True)
    _root_refused(provision, env / "kicad", env, "inside")
    _root_refused(provision, tmp_path / "pg", env, "inside")
    _root_refused(provision, env, env, "inside")
    assert not (env / "kicad").exists()


# ---- the self-check ---------------------------------------------------------------------------


def _stand_in_cli(tmp_path: Path, answer: str) -> Path:
    cli = tmp_path / "stand-in" / "kicad-cli"
    cli.parent.mkdir(parents=True)
    cli.write_text(
        "#!/bin/sh\n"
        f"/usr/bin/env > {tmp_path / 'seen-env'}\n"
        f'echo "$@" >> {tmp_path / "seen-args"}\n'
        f"echo {answer}\n"
    )
    cli.chmod(0o755)
    return cli


def test_the_self_check_takes_the_pinned_version_from_the_program_itself(tmp_path: Path) -> None:
    provision = _provision()
    check = _named(provision, "check_kicad")
    cli = _stand_in_cli(tmp_path, VERSION)
    (tmp_path / "work").mkdir()
    found = check(cli, VERSION, tmp_path / "work")
    assert isinstance(found, dict), found
    assert found.get("version") == VERSION
    asked = (tmp_path / "seen-args").read_text().splitlines()
    assert asked == ["--version", "version"]


def test_a_program_that_answers_another_version_is_refused_naming_both(tmp_path: Path) -> None:
    provision = _provision()
    check = _named(provision, "check_kicad")
    cli = _stand_in_cli(tmp_path, "9.0.1")
    (tmp_path / "work").mkdir()
    _refused(provision, lambda: check(cli, VERSION, tmp_path / "work"), "9.0.1", VERSION)


def test_the_self_check_runs_with_downloads_refused_and_its_writes_in_provisioning_s_scratch(
    tmp_path: Path,
) -> None:
    provision = _provision()
    check = _named(provision, "check_kicad")
    cli = _stand_in_cli(tmp_path, VERSION)
    work = tmp_path / "work"
    work.mkdir()
    check(cli, VERSION, work)
    seen = dict(
        line.split("=", 1)
        for line in (tmp_path / "seen-env").read_text().splitlines()
        if "=" in line
    )
    for name in ("HTTP_PROXY", "HTTPS_PROXY", "ALL_PROXY"):
        assert seen.get(name) == provision.DEAD_PROXY, name
    for name in ("HOME", "TMPDIR", "KICAD_CONFIG_HOME"):
        assert Path(seen.get(name, "/")).is_relative_to(work), name
    assert seen.get("PATH") == "/usr/bin:/bin"
    assert "DISPLAY" not in seen
    assert "WAYLAND_DISPLAY" not in seen


# ---- the Linux release unpacked ---------------------------------------------------------------

#: A stand-in image: asked to unpack itself, it leaves a tree as the real runtime does.
IMAGE = b"#!/bin/sh\nmkdir -p squashfs-root/bin\necho a program > squashfs-root/bin/tool-cli\n"


def _archive(tmp_path: Path, *members: tuple[str, bytes]) -> Path:
    archive = tmp_path / "release.tar"
    with tarfile.open(archive, "w") as tar:
        for name, body in members:
            (tmp_path / "member").write_bytes(body)
            tar.add(tmp_path / "member", arcname=name)
    return archive


def _unpacked(provision: ModuleType, archive: Path, inner: dict[str, str], work: Path) -> object:
    work.mkdir()
    for name in ("home", "tmp"):
        (work / name).mkdir()
    return _named(provision, "_linux_release")(archive, _pin(inner=inner), work)


def test_the_archive_s_one_image_is_held_to_its_digest_and_unpacks_its_own_tree(
    tmp_path: Path,
) -> None:
    provision = _provision()
    archive = _archive(tmp_path, ("tool.AppImage", IMAGE))
    inner = {"file": "tool.AppImage", "sha256": hashlib.sha256(IMAGE).hexdigest()}
    tree = Path(str(_unpacked(provision, archive, inner, tmp_path / "work")))
    assert tree.name == "squashfs-root"
    assert (tree / "bin" / "tool-cli").read_text() == "a program\n"
    assert not (tmp_path / "work" / "kicad-archive" / "tool.AppImage").exists()


def test_an_image_whose_bytes_differ_from_its_pin_is_refused_naming_both_digests(
    tmp_path: Path,
) -> None:
    provision = _provision()
    archive = _archive(tmp_path, ("tool.AppImage", IMAGE))
    pinned = hashlib.sha256(b"another image").hexdigest()
    inner = {"file": "tool.AppImage", "sha256": pinned}
    _refused(
        provision,
        lambda: _unpacked(provision, archive, inner, tmp_path / "work"),
        "tool.AppImage",
        pinned,
        hashlib.sha256(IMAGE).hexdigest(),
    )
    assert not (tmp_path / "work" / "kicad-tree" / "squashfs-root").exists()


@pytest.mark.parametrize(
    "members",
    [
        (("tool.AppImage", IMAGE), ("extra", b"one more file")),
        (("other.AppImage", IMAGE),),
    ],
    ids=["a-second-member", "another-name"],
)
def test_an_archive_that_is_not_exactly_the_one_image_is_refused(
    tmp_path: Path, members: tuple[tuple[str, bytes], ...]
) -> None:
    provision = _provision()
    archive = _archive(tmp_path, *members)
    inner = {"file": "tool.AppImage", "sha256": hashlib.sha256(IMAGE).hexdigest()}
    _refused(
        provision,
        lambda: _unpacked(provision, archive, inner, tmp_path / "work"),
        "release.tar",
        "one image",
    )


def test_the_command_line_refuses_a_kicad_root_in_the_environment_before_building_anything(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    provision = _provision()
    built: list[object] = []

    def build(*args: object, **_: object) -> dict[str, object]:
        built.append(args)
        return {"self_check": {}}

    monkeypatch.setattr(provision, "provision", build)
    monkeypatch.setattr(provision, "provision_kicad", build)
    env = tmp_path / "env"
    status = provision.main(["--dest", str(env), "--kicad-dest", str(env / "kicad")])
    assert status == 1
    assert built == []
    assert "inside" in capsys.readouterr().err


# ---- the program's place, and macOS -----------------------------------------------------------


def test_the_program_is_named_inside_the_root_for_each_machine(tmp_path: Path) -> None:
    provision = _provision()
    place = _named(provision, "kicad_cli")
    linux = Path(str(place(tmp_path, "Linux")))
    mac = Path(str(place(tmp_path, "Darwin")))
    assert linux == tmp_path / "app" / "bin" / "kicad-cli"
    assert mac == tmp_path / "app" / "KiCad.app" / "Contents" / "MacOS" / "kicad-cli"


def test_the_macos_image_is_attached_read_only_out_of_sight_and_never_opened(
    tmp_path: Path,
) -> None:
    provision = _provision()
    argv = _named(provision, "attach_argv")(tmp_path / "kicad.dmg", tmp_path / "mount")
    assert isinstance(argv, list)
    assert argv[:2] == ["/usr/bin/hdiutil", "attach"]
    for flag in ("-readonly", "-nobrowse", "-noautoopen"):
        assert flag in argv, flag
    assert argv[argv.index("-mountpoint") + 1] == str(tmp_path / "mount")
    assert argv[-1] == str(tmp_path / "kicad.dmg")
