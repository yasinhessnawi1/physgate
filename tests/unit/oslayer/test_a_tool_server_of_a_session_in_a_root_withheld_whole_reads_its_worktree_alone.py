"""A tool server of a session in a root withheld whole reads the worktree there, and no more.

A protected trial's raw session, and a blind check's, works in a place of its own inside a root
withheld whole: the root is denied, and the session's worktree alone is opened again in it. A
tool server the session is offered is contained by the same policy, narrowed, so its wrapper
opens the same one place, for reading only: nothing else of the root (the rest of the session's
own place, its login and records among it, or anything made in the root later), no write to the
worktree, no network. A denial inside the worktree stays a denial. Where the worktree is not that
root's exception, or a root of the server's other than the worktree lies in the root, no server
is offered (fail closed), as before.

Each platform's wrapper is built here on either platform; the rows that run it for real are in
``tests/integration/toolenv``.
"""

from __future__ import annotations

import json
import os
import shlex
import tempfile
from pathlib import Path

import pytest

from physgate.hooks.config import SessionConfig
from physgate.hooks.settings import InstallRequest, build_config
from physgate.hooks.settings import current_installation as installation
from physgate.oslayer import containment
from physgate.oslayer.containment import (
    SANDBOX_EXEC,
    ContainmentError,
    ServerLaunch,
    bwrap_args,
    contained_servers,
    seatbelt_profile,
    server_read_denied,
)
from physgate.oslayer.policy import withheld_around_worktree

BWRAP = "/usr/bin/bwrap"
PLATFORMS = ("darwin", "linux")
PYTHON = "/usr/bin/python3"


@pytest.fixture
def rig(tmp_path: Path) -> Path:
    root = tmp_path.resolve()
    place = root / "work" / "trial" / "place"
    for d in ("worktree", "session/state", "session/session", "session/config", "session/home"):
        (place / d).mkdir(parents=True)
    (place / "worktree" / "README.md").write_text("the session's own\n")
    (root / "work" / "trial" / "harness").mkdir()
    (root / "temps" / "own").mkdir(parents=True)
    (root / "env" / "bin").mkdir(parents=True)
    return root


def _fields(root: Path, **changes: object) -> dict[str, object]:
    work, place = root / "work", root / "work" / "trial" / "place"
    sdir = place / "session"
    return {
        "profile": "baseline",
        "role": None,
        "worktree": str(place / "worktree"),
        "own_branch": None,
        "store_root": None,
        "state_dir": str(sdir / "state"),
        "target_dir": str(sdir / "session"),
        "claude_config_dir": str(sdir / "config"),
        "user_home": str(sdir / "home"),
        "token_ceiling": 1000,
        "sessions_root": str(sdir),
        "held_out": (str(work / "trial" / "harness"),),
        "temp_dir": str(root / "temps" / "own"),
        "session_temps": str(root / "temps"),
        "shared_claude_temp": (str(root / "claude-temp"),),
        "withheld_whole": (str(work),),
        "own_place": str(place),
    } | changes


def _config(root: Path, **changes: object) -> SessionConfig:
    return build_config(InstallRequest(**_fields(root, **changes)), installation())  # type: ignore[arg-type]


def _worktree(root: Path) -> str:
    return str(root / "work" / "trial" / "place" / "worktree")


def _server(root: Path, **changes: object) -> ServerLaunch:
    fields: dict[str, object] = {
        "name": "probe",
        "command": PYTHON,
        "args": ("-I", "{worktree}/probe.py"),
        "exec_roots": (str(root / "env" / "bin"),),
        "read_roots": (str(root / "env"),),
    }
    fields.update(changes)
    return ServerLaunch.model_validate(fields)


def _contain(root: Path, platform: str, config: SessionConfig) -> dict[str, object]:
    found = contained_servers(
        config,
        [_server(root)],
        platform=platform,
        temp_dir=root / "temps" / "own",
        profiles_dir=root / "profiles",
        bwrap=BWRAP,
    )
    entry: dict[str, object] = json.loads(found)["mcpServers"]["probe"]
    return entry


def _covered(path: str, places: list[str]) -> bool:
    return any(path == p or path.startswith(p.rstrip("/") + "/") for p in places)


# ---- the session starts, its server contained ----------------------------------------------------


@pytest.mark.parametrize("platform", PLATFORMS)
def test_a_server_of_a_session_in_a_root_withheld_whole_is_contained(
    rig: Path, platform: str
) -> None:
    config = _config(rig)
    work = str(rig / "work")
    # Not vacuous: the root is withheld whole, the worktree lies in it, and the server is denied it.
    assert withheld_around_worktree(config) == frozenset({work})
    assert work in server_read_denied(config, platform)
    entry = _contain(rig, platform, config)
    wrapper = SANDBOX_EXEC if platform == "darwin" else BWRAP
    assert entry["command"] == wrapper, entry
    args = entry["args"]
    assert isinstance(args, list)
    assert args[-3:] == [PYTHON, "-I", f"{_worktree(rig)}/probe.py"], args


def test_a_session_whose_worktree_is_no_root_s_exception_names_none(rig: Path) -> None:
    """The ordinary session: nothing withheld whole around its worktree, nothing excepted."""
    config = _config(rig, withheld_whole=(), own_place=None)
    assert withheld_around_worktree(config) == frozenset()


# ---- macOS: the root denied, the worktree alone opened again, for reading ------------------------


def _profile(rig: Path) -> list[str]:
    config = _config(rig)
    _contain(rig, "darwin", config)
    text = (rig / "profiles" / "probe.sb").read_text()
    return [line.strip() for line in text.splitlines() if line.strip()]


def _subpaths(line: str) -> list[str]:
    return [part.split('"')[1] for part in line.split("(subpath ")[1:]]


def test_the_macos_profile_opens_the_worktree_after_the_root_is_denied(rig: Path) -> None:
    lines = _profile(rig)
    work, wt = str(rig / "work"), _worktree(rig)
    denies = [i for i, line in enumerate(lines) if line.startswith("(deny file-read*")]
    root_deny = next(i for i in denies if work in _subpaths(lines[i]))
    opened = [
        i
        for i, line in enumerate(lines)
        if line.startswith("(allow file-read*") and wt in _subpaths(line) and i > root_deny
    ]
    assert len(opened) == 1, lines
    # The worktree alone, as given and where it really is: never the place, the root or a parent.
    assert set(_subpaths(lines[opened[0]])) == {wt, os.path.realpath(wt)}, lines[opened[0]]


def test_the_macos_profile_opens_nothing_else_of_the_root(rig: Path) -> None:
    lines = _profile(rig)
    work, wt = str(rig / "work"), _worktree(rig)
    root_deny = next(
        i
        for i, line in enumerate(lines)
        if line.startswith("(deny file-read*") and work in _subpaths(line)
    )
    after = [line for line in lines[root_deny + 1 :] if line.startswith("(allow file-read*")]
    opened = [p for line in after for p in _subpaths(line) + _literals(line)]
    inside = [p for p in opened if _covered(p, [work]) and not _covered(p, [wt])]
    assert inside == [], inside


def _literals(line: str) -> list[str]:
    return [part.split('"')[1] for part in line.split("(literal ")[1:]]


def test_the_macos_profile_writes_nothing_of_the_worktree(rig: Path) -> None:
    lines = _profile(rig)
    wt = _worktree(rig)
    writes = [line for line in lines if line.startswith("(allow file-write*")]
    assert len(writes) == 1, writes
    assert not _covered(wt, _subpaths(writes[0])), writes
    assert not any(_covered(p, [wt]) for p in _subpaths(writes[0])), writes


def test_the_macos_profile_denies_a_denial_inside_the_worktree_after_opening_it(rig: Path) -> None:
    lines = _profile(rig)
    wt = _worktree(rig)
    corpora = os.path.join(wt, "corpora")  # an answer key, beneath every worktree
    opened = next(
        i
        for i, line in enumerate(lines)
        if line.startswith("(allow file-read*")
        and _subpaths(line)
        and set(_subpaths(line)) == {wt} | {os.path.realpath(wt)}
    )
    later = [
        line
        for line in lines[opened + 1 :]
        if line.startswith("(deny file-read*") and corpora in _subpaths(line)
    ]
    assert later, lines[opened:]


def test_the_macos_profile_keeps_the_network_denied(rig: Path) -> None:
    lines = _profile(rig)
    assert "(deny network*)" in lines
    assert not [line for line in lines if line.startswith("(allow network")], lines


# ---- Linux: the worktree bound read-only, nothing else of the root there -------------------------


def _bwrap(rig: Path) -> list[str]:
    config = _config(rig)
    entry = _contain(rig, "linux", config)
    args = entry["args"]
    assert isinstance(args, list)
    return [str(a) for a in args[: args.index("--")]]


def _bound(args: list[str], option: str) -> list[str]:
    return [args[i + 2] for i, a in enumerate(args) if a == option]


def test_the_linux_wrapper_binds_the_worktree_read_only_and_no_other_place_of_the_root(
    rig: Path,
) -> None:
    args = _bwrap(rig)
    work, wt = os.path.realpath(rig / "work"), os.path.realpath(_worktree(rig))
    assert wt in _bound(args, "--ro-bind"), shlex.join(args)
    # Writable: the server's own directory alone, never the worktree.
    assert [p for p in _bound(args, "--bind") if _covered(p, [work])] == [], shlex.join(args)
    inside = [p for p in _bound(args, "--ro-bind") if _covered(p, [work]) and not _covered(p, [wt])]
    assert inside == [], shlex.join(args)


def test_the_linux_wrapper_hides_a_denial_inside_the_worktree_after_binding_it(rig: Path) -> None:
    wt = Path(_worktree(rig))
    (wt / "corpora").mkdir()
    (wt / "corpora" / "key.txt").write_text("the key\n")
    args = _bwrap(rig)
    real, corpora = os.path.realpath(wt), os.path.realpath(wt / "corpora")
    text = shlex.join(args)
    after = args[args.index(real) + 2 :]
    assert args[args.index(real) - 1] == "--ro-bind", text
    # Not bound after the worktree is, and hidden after it: masked, or left out of the worktree's
    # own listing rebuilt (a denial in it is not there yet, as the reviewers' place is not).
    bound = [
        after[i + 2]
        for i, a in enumerate(after)
        if a == "--ro-bind" and after[i + 1] != "/dev/null"
    ]
    assert not [p for p in bound if _covered(p, [corpora])], text
    masked = any(after[i : i + 2] == ["--tmpfs", corpora] for i in range(len(after)))
    rebuilt = any(after[i : i + 2] == ["--tmpfs", real] for i in range(len(after)))
    assert masked or rebuilt, text


def test_the_linux_wrapper_takes_the_network(rig: Path) -> None:
    assert "--unshare-net" in _bwrap(rig)


def test_the_root_inside_a_place_the_server_reads_is_masked_and_the_worktree_bound_after(
    rig: Path,
) -> None:
    """A root of the server's above the root withheld whole: the root hidden, the worktree on it."""
    work, wt = str(rig / "work"), _worktree(rig)
    args = bwrap_args(
        read_denied=(work,),
        server_dir=str(rig / "temps" / "own"),
        read_roots=(str(rig), wt),
        excepted=wt,
        withheld=(work,),
    )
    text = shlex.join(args)
    assert f"--tmpfs {work}" in text and f"--ro-bind {wt} {wt}" in text, text
    assert text.index(f"--tmpfs {work}") < text.index(f"--ro-bind {wt} {wt}"), text
    assert text.index(f"--ro-bind {wt} {wt}") < text.index("--remount-ro /"), text


# ---- what stays refused --------------------------------------------------------------------------


def _refused(rig: Path, config: SessionConfig, server: ServerLaunch, platform: str) -> None:
    """Contain ``server`` in a temporary directory of its own, fresh for each case."""
    temp = Path(tempfile.mkdtemp(dir=rig / "temps"))
    contained_servers(
        config,
        [server],
        platform=platform,
        temp_dir=temp,
        profiles_dir=temp / "profiles",
        bwrap=BWRAP,
    )


@pytest.mark.parametrize("platform", PLATFORMS)
def test_a_read_root_of_the_server_s_elsewhere_in_the_root_is_refused(
    rig: Path, platform: str
) -> None:
    config = _config(rig)
    place = rig / "work" / "trial" / "place"
    for elsewhere in (place / "session" / "home", place, rig / "work" / "trial"):
        server = _server(rig, read_roots=(str(elsewhere),))
        with pytest.raises(ContainmentError, match="lies inside"):
            _refused(rig, config, server, platform)


@pytest.mark.parametrize("platform", PLATFORMS)
def test_a_program_of_the_server_s_inside_the_worktree_is_refused(rig: Path, platform: str) -> None:
    """The worktree is read by the server, never run from: the session writes it."""
    config = _config(rig)
    wt = Path(_worktree(rig))
    for server in (
        _server(rig, command=str(wt / "python3")),
        _server(rig, exec_roots=(str(wt / "bin"),)),
    ):
        with pytest.raises(ContainmentError, match="lies inside"):
            _refused(rig, config, server, platform)


def _both(rig: Path, **given: object) -> None:
    """Each platform's wrapper, given the same: each refuses it."""
    own = str(rig / "temps" / "own")
    reads = given.pop("read_roots", (_worktree(rig),))
    with pytest.raises(ContainmentError):
        seatbelt_profile(server_dir=own, devices=(), command=PYTHON, read_roots=reads, **given)  # type: ignore[arg-type]
    with pytest.raises(ContainmentError):
        bwrap_args(server_dir=own, read_roots=reads, **given)  # type: ignore[arg-type]


def test_the_worktree_is_opened_only_inside_a_root_denied_and_withheld_around_it(rig: Path) -> None:
    work, wt = str(rig / "work"), _worktree(rig)
    held = str(rig / "work" / "trial")
    # Not withheld whole: an ordinary denial around the worktree refuses, as it did.
    _both(rig, read_denied=(work,))
    _both(rig, read_denied=(work,), excepted=wt, withheld=())
    # Withheld, but not denied to the server: nothing to except it from.
    _both(rig, read_denied=(), excepted=wt, withheld=(work,))
    # The root withheld does not hold the worktree, or is the worktree.
    _both(rig, read_denied=(str(rig / "env"),), excepted=wt, withheld=(str(rig / "env"),))
    _both(rig, read_denied=(wt,), excepted=wt, withheld=(wt,))
    # Another denial around the worktree, beside the root withheld: still refused.
    _both(rig, read_denied=(work, held), excepted=wt, withheld=(work,))


@pytest.mark.parametrize("platform", PLATFORMS)
def test_a_session_in_a_root_withheld_whole_without_its_exception_offers_no_server(
    rig: Path, platform: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Were the root not the worktree's exception, the server is refused as before."""
    config = _config(rig)
    monkeypatch.setattr(containment, "withheld_around_worktree", lambda _c: frozenset())
    with pytest.raises(ContainmentError, match="lies inside"):
        _contain(rig, platform, config)


def test_the_macos_profile_denies_the_root_s_metadata_by_name_and_reopens_the_worktree_s(
    rig: Path,
) -> None:
    """A rule naming every read does not outrank the metadata allowed everywhere: named here."""
    lines = _profile(rig)
    work, wt = str(rig / "work"), _worktree(rig)
    corpora = os.path.join(wt, "corpora")
    ops = ("file-read-metadata", "file-test-existence", "file-read-xattr")
    everywhere = lines.index("(allow file-read-metadata)")
    root = [
        i
        for i, line in enumerate(lines)
        if line.startswith("(deny ") and work in _subpaths(line) and all(op in line for op in ops)
    ]
    opened = [
        i
        for i, line in enumerate(lines)
        if line.startswith("(allow ") and wt in _subpaths(line) and all(op in line for op in ops)
    ]
    again = [
        i
        for i, line in enumerate(lines)
        if line.startswith("(deny ")
        and corpora in _subpaths(line)
        and all(op in line for op in ops)
    ]
    assert root and opened and again, lines
    assert everywhere < root[0] < opened[0] < again[0], lines
