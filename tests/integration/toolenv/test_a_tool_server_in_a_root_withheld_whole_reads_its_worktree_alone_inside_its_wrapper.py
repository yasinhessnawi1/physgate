"""A tool server of a session in a root withheld whole, run in its wrapper on each platform.

A protected trial's session, and a blind check's, works in a place of its own inside a root
withheld whole, the worktree alone opened again there. Its tool server is contained by the same
rule: inside the wrapper the harness generates for it (Seatbelt on macOS, bubblewrap on Linux)
it reads the worktree, and nothing else of the root: not the rest of the session's own place
(its login, its records), not a sibling whose name starts as the worktree's, not what lay beside
the place at the install, not an entry made in the root after the wrapper was built, not a
denial inside the worktree, nor any of these through a link the session makes in its worktree.
It writes nothing in the worktree, only its own directory, and reaches no network: a listener on
the machine's loopback, answered outside, is not reached.

Each row runs on its own platform, and says so where it does not.
"""

from __future__ import annotations

import ctypes
import ctypes.util
import json
import os
import shutil
import socket
import subprocess
import sys
from pathlib import Path

import pytest
from test_a_tool_server_s_wrapper_holds_on_each_platform import INSTALLATION, PYTHON

from physgate.hooks import paths, shell_paths
from physgate.hooks.config import SessionConfig
from physgate.hooks.settings import InstallRequest, build_config
from physgate.hooks.settings import current_installation as installation
from physgate.hooks.shell import parse
from physgate.oslayer.containment import ServerLaunch, contained_servers

pytestmark = [
    pytest.mark.integration,
    pytest.mark.skipif(
        sys.platform != "darwin" and not sys.platform.startswith("linux"),
        reason="the wrappers are Seatbelt on macOS and bubblewrap on Linux",
    ),
]

MARKED = "marked.txt"
WRITTEN = "written"

#: Run inside the wrapper: read each path, list the session's place, write into the worktree and
#: into its own directory, connect to the listener; say what became of each.
PROBE = """
import ctypes, ctypes.util, errno, json, os, socket, sys
port, place, worktree, own = int(sys.argv[1]), sys.argv[2], sys.argv[3], sys.argv[4]
given = sys.argv[5:]
reads, looked = given[: given.index("--meta")], given[given.index("--meta") + 1 :]
libc = ctypes.CDLL(ctypes.util.find_library("c"), use_errno=True)

def xattr(path):
    buffer = ctypes.create_string_buffer(64)
    if sys.platform == "darwin":
        got = libc.getxattr(path.encode(), b"user.pg", buffer, 64, 0, 0)
    else:
        got = libc.getxattr(path.encode(), b"user.pg", buffer, 64)
    return buffer.raw[:got].decode() if got >= 0 else errno.errorcode[ctypes.get_errno()]

found = {}
for path in looked:
    seen = {}
    for name, call in (("stat", os.stat), ("lstat", os.lstat)):
        try:
            found_stat = call(path)
            seen[name] = found_stat.st_ino
            seen[name + " size"] = found_stat.st_size
        except OSError as exc:
            seen[name] = type(exc).__name__
    seen["access"] = os.access(path, os.F_OK)
    seen["exists"] = os.path.exists(path)
    seen["xattr"] = xattr(path)
    found["meta " + path] = seen
for path in reads:
    try:
        with open(path) as handle:
            found[path] = handle.read()
    except OSError as exc:
        found[path] = type(exc).__name__
try:
    found["listing"] = sorted(os.listdir(place))
except OSError as exc:
    found["listing"] = type(exc).__name__
for name, where in (("worktree", worktree), ("own", own)):
    try:
        with open(os.path.join(where, "new.txt"), "w") as handle:
            handle.write("from the server\\n")
        found["write " + name] = "written"
    except OSError as exc:
        found["write " + name] = type(exc).__name__
s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
s.settimeout(5)
try:
    s.connect(("127.0.0.1", port))
    found["network"] = "connected"
except OSError as exc:
    found["network"] = type(exc).__name__
finally:
    s.close()
print(json.dumps(found))
"""


@pytest.fixture
def rig(tmp_path: Path) -> Path:
    root = tmp_path.resolve()
    place = root / "work" / "trial" / "place"
    for d in ("worktree", "session/state", "session/session", "session/config", "session/home"):
        (place / d).mkdir(parents=True)
    wt = place / "worktree"
    (wt / "README.md").write_text("the session's own\n")
    (wt / "probe.py").write_text(PROBE)
    (wt / "corpora").mkdir()
    (wt / "corpora" / "key.txt").write_text("an answer key, inside the worktree\n")
    (place / "session" / "state" / "login.txt").write_text("the session's login\n")
    # A link the session made in its worktree, to its own login beside it.
    (wt / "out").symlink_to(place / "session" / "state" / "login.txt")
    (place / "worktree2").mkdir()
    (place / "worktree2" / MARKED).write_text("beside, with a name like the worktree's\n")
    (root / "work" / "trial" / "harness").mkdir()
    (root / "work" / "trial" / "harness" / MARKED).write_text("beside, at the install\n")
    (root / "temps" / "own").mkdir(parents=True)
    # A second name in the worktree for the file beside it, made from outside the sandbox: no
    # session can make one (below), so this is what a server would read were one there.
    os.link(place / "worktree2" / MARKED, wt / "second-name")
    for path in (wt / "README.md", place / "worktree2" / MARKED, wt / "corpora" / "key.txt"):
        _set_xattr(path)
    return root


def _set_xattr(path: Path) -> None:
    libc = ctypes.CDLL(ctypes.util.find_library("c"), use_errno=True)
    if sys.platform == "darwin":
        done = libc.setxattr(str(path).encode(), b"user.pg", b"v", 1, 0, 0)
    else:
        done = libc.setxattr(str(path).encode(), b"user.pg", b"v", 1, 0)
    assert done == 0, (path, ctypes.get_errno())


def _config(root: Path) -> SessionConfig:
    work, place = root / "work", root / "work" / "trial" / "place"
    sdir = place / "session"
    request = InstallRequest(
        profile="baseline",
        role=None,
        worktree=str(place / "worktree"),
        own_branch=None,
        store_root=None,
        state_dir=str(sdir / "state"),
        target_dir=str(sdir / "session"),
        claude_config_dir=str(sdir / "config"),
        user_home=str(sdir / "home"),
        token_ceiling=1000,
        sessions_root=str(sdir),
        held_out=(str(work / "trial" / "harness"),),
        temp_dir=str(root / "temps" / "own"),
        session_temps=str(root / "temps"),
        shared_claude_temp=(str(root / "claude-temp"),),
        withheld_whole=(str(work),),
        own_place=str(place),
    )
    return build_config(request, installation())


def _bwrap() -> str | None:
    if not sys.platform.startswith("linux"):
        return None
    found = shutil.which("bwrap")
    assert found is not None, "bubblewrap is not installed here"
    return found


def _looked(rig: Path) -> dict[str, Path]:
    """Every place whose metadata is probed inside the wrapper, by what it is."""
    work = rig / "work"
    place = work / "trial" / "place"
    wt = place / "worktree"
    return {
        "own file": wt / "README.md",
        "worktree": wt,
        "sibling file": place / "worktree2" / MARKED,
        "sibling directory": place / "worktree2",
        "login": place / "session" / "state" / "login.txt",
        "denial inside the worktree": wt / "corpora" / "key.txt",
        "denial's directory": wt / "corpora",
        "denial made after launch": wt / "knowledge" / "reviewers" / MARKED,
        "root": work,
        "trial": work / "trial",
        "place": place,
    }


def _run(rig: Path) -> tuple[dict[str, object], Path, Path]:
    """The server's entry as the session is spawned with it, run as the binary would run it."""
    config = _config(rig)
    place = rig / "work" / "trial" / "place"
    wt = place / "worktree"
    own = rig / "temps" / "own" / "servers" / "probe"
    listener = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    listener.bind(("127.0.0.1", 0))
    listener.listen(4)
    port = listener.getsockname()[1]
    late = rig / "work" / "late-5e2a91"
    paths = [
        wt / "README.md",
        place / "session" / "state" / "login.txt",
        place / "worktree2" / MARKED,
        rig / "work" / "trial" / "harness" / MARKED,
        wt / "corpora" / "key.txt",
        late / MARKED,
        wt / "out",
        wt / "second-name",
        wt / "knowledge" / "reviewers" / MARKED,
    ]
    server = ServerLaunch(
        name="probe",
        command=PYTHON,
        args=("-I", "{worktree}/probe.py", str(port), str(place), str(wt), str(own),
              *map(str, paths), "--meta", *map(str, _looked(rig).values())),
        read_roots=(INSTALLATION,),
    )  # fmt: skip
    try:
        found = contained_servers(
            config,
            [server],
            platform=sys.platform,
            temp_dir=rig / "temps" / "own",
            profiles_dir=rig / "profiles",
            bwrap=_bwrap(),
        )
        entry = json.loads(found)["mcpServers"]["probe"]
        # Made in the root after the server's rules were taken, by something other than it.
        late.mkdir()
        (late / MARKED).write_text("made after the wrapper was built\n")
        # And a denial inside the worktree that was not there when they were taken.
        (wt / "knowledge" / "reviewers").mkdir(parents=True)
        (wt / "knowledge" / "reviewers" / MARKED).write_text("made after the wrapper was built\n")
        # The controls: outside the wrapper every file is read and the listener answers.
        for path in paths:
            assert path.read_text(), path
        probe = socket.create_connection(("127.0.0.1", port), timeout=5)
        probe.close()
        done = subprocess.run(
            [entry["command"], *entry["args"]],
            capture_output=True,
            text=True,
            timeout=120,
            check=False,
            cwd=wt,
            env={**os.environ, **entry["env"]},
        )
    finally:
        listener.close()
    assert done.returncode == 0, done.stderr[-2000:]
    return json.loads(done.stdout), place, own


def test_the_server_reads_the_worktree_and_its_own_directory_and_nothing_else_of_the_root(
    rig: Path,
) -> None:
    found, place, own = _run(rig)
    wt = place / "worktree"
    assert found[str(wt / "README.md")] == "the session's own\n", found
    assert found["write own"] == WRITTEN, found
    assert (own / "new.txt").read_text() == "from the server\n"
    refused = [
        place / "session" / "state" / "login.txt",
        place / "worktree2" / MARKED,
        rig / "work" / "trial" / "harness" / MARKED,
        rig / "work" / "late-5e2a91" / MARKED,
        # Through a link in the worktree: judged where it lands, which the server may not read.
        place / "worktree" / "out",
        # A denial inside the worktree that was not there at launch.
        place / "worktree" / "knowledge" / "reviewers" / MARKED,
    ]
    for path in refused:
        assert found[str(path)] in ("PermissionError", "FileNotFoundError"), (path, found)


def test_the_server_lists_nothing_of_the_place_beside_the_worktree(rig: Path) -> None:
    found, _place, _own = _run(rig)
    # macOS refuses the listing; Linux holds only the way down to the worktree there.
    assert found["listing"] in ("PermissionError", ["worktree"]), found


def test_a_denial_inside_the_worktree_stays_denied_to_the_server(rig: Path) -> None:
    found, place, _own = _run(rig)
    key = place / "worktree" / "corpora" / "key.txt"
    assert found[str(key)] in ("PermissionError", "FileNotFoundError"), found


def test_the_server_writes_nothing_in_the_worktree(rig: Path) -> None:
    found, place, _own = _run(rig)
    assert found["write worktree"] != WRITTEN, found
    assert not (place / "worktree" / "new.txt").exists()


def test_the_server_reaches_no_network(rig: Path) -> None:
    found, _place, _own = _run(rig)
    assert found["network"] != "connected", found
    assert found["network"] in ("PermissionError", "ConnectionRefusedError", "OSError"), found


def _meta(found: dict[str, object], path: Path) -> dict[str, object]:
    seen = found["meta " + str(path)]
    assert isinstance(seen, dict), found
    return seen


#: What each probe gives where a place is not to be seen at all.
UNSEEN = {"access": False, "exists": False}


def test_nothing_of_the_root_but_the_worktree_is_even_seen_to_be_there(rig: Path) -> None:
    """No size, mode, time, existence or extended attribute of anything else in the root."""
    found, _place, _own = _run(rig)
    looked = _looked(rig)
    for what in ("own file", "worktree"):
        seen = _meta(found, looked[what])
        assert isinstance(seen["stat"], int) and isinstance(seen["lstat"], int), (what, seen)
        assert seen["access"] is True and seen["exists"] is True, (what, seen)
        if sys.platform == "darwin":
            # Seatbelt judges the real place: the very file and directory, as outside.
            assert seen["stat"] == os.stat(looked[what]).st_ino, (what, seen)
    # The worktree's own file as it is outside, on both platforms. Bubblewrap binds it, so its
    # inode inside may differ; its size does not. (The worktree directory itself may be rebuilt
    # inside from its entries at launch, so only its being there is held for it.)
    own = looked["own file"]
    assert _meta(found, own)["stat size"] == os.stat(own).st_size, found
    # Its own file's extended attribute is read as it is outside.
    assert _meta(found, looked["own file"])["xattr"] == "v", found
    hidden = [
        "sibling file",
        "sibling directory",
        "login",
        "denial inside the worktree",
        "denial's directory",
        "denial made after launch",
    ]
    # macOS denies every ancestor's metadata too (reaching the worktree needs none); bubblewrap
    # makes the way down to the worktree in the server's own root, below.
    if sys.platform == "darwin":
        hidden += ["root", "trial", "place"]
    for what in hidden:
        seen = _meta(found, looked[what])
        assert seen["stat"] in ("PermissionError", "FileNotFoundError"), (what, seen)
        assert seen["lstat"] in ("PermissionError", "FileNotFoundError"), (what, seen)
        assert {k: seen[k] for k in UNSEEN} == UNSEEN, (what, seen)
        assert seen["xattr"] in ("EPERM", "ENOENT"), (what, seen)


@pytest.mark.skipif(not sys.platform.startswith("linux"), reason="bubblewrap's own way down")
def test_the_way_down_to_the_worktree_is_bubblewrap_s_own_not_the_root_s(rig: Path) -> None:
    """The directories above the worktree are there, as lookup needs, but are made empty."""
    found, _place, _own = _run(rig)
    looked = _looked(rig)
    for what in ("root", "trial", "place"):
        seen = _meta(found, looked[what])
        assert seen["stat"] != os.stat(looked[what]).st_ino, (what, seen)
        assert seen["xattr"] != "v", (what, seen)


def test_a_second_name_in_the_worktree_is_read_and_no_session_can_make_one(rig: Path) -> None:
    """What the wrapper would let through, and the harness's refusals that keep it from arising.

    The wrappers judge a path, not the file: a second name in the worktree for a file beside it
    is read. No session makes one: the hooks refuse a command naming the file beside it, and a
    read of a file with a second name, by any tool and by a server's own path argument.
    """
    found, place, _own = _run(rig)
    wt = place / "worktree"
    sibling = place / "worktree2" / MARKED
    assert found[str(wt / "second-name")] == sibling.read_text(), found
    config = _config(rig)
    for command in (f"ln {sibling} {wt}/again", f"ln {sibling} again", f"cp -l {sibling} again"):
        assert shell_paths.check(parse(command)[0], str(wt), config) is not None, command
    refused = paths.protection(str(wt / "second-name"), str(wt), config, writing=False)
    assert refused is not None, "a file with a second name in the worktree was not refused"
