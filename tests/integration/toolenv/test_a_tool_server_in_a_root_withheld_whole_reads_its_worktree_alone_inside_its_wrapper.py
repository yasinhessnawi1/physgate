"""A tool server of a session in a root withheld whole, run in its wrapper on each platform.

A protected trial's session, and a blind check's, works in a place of its own inside a root
withheld whole, the worktree alone opened again there. Its tool server is contained by the same
rule: inside the wrapper the harness generates for it (Seatbelt on macOS, bubblewrap on Linux)
it reads the worktree, and nothing else of the root: not the rest of the session's own place
(its login, its records), not a sibling whose name starts as the worktree's, not what lay beside
the place at the install, not an entry made in the root after the wrapper was built, not a
denial inside the worktree. It writes nothing in the worktree, only its own directory, and
reaches no network: a listener on the machine's loopback, answered outside, is not reached.

Each row runs on its own platform, and says so where it does not.
"""

from __future__ import annotations

import json
import os
import shutil
import socket
import subprocess
import sys
from pathlib import Path

import pytest
from test_a_tool_server_s_wrapper_holds_on_each_platform import INSTALLATION, PYTHON

from physgate.hooks.config import SessionConfig
from physgate.hooks.settings import InstallRequest, build_config
from physgate.hooks.settings import current_installation as installation
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
import json, os, socket, sys
port, place, worktree, own = int(sys.argv[1]), sys.argv[2], sys.argv[3], sys.argv[4]
found = {}
for path in sys.argv[5:]:
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
    (place / "worktree2").mkdir()
    (place / "worktree2" / MARKED).write_text("beside, with a name like the worktree's\n")
    (root / "work" / "trial" / "harness").mkdir()
    (root / "work" / "trial" / "harness" / MARKED).write_text("beside, at the install\n")
    (root / "temps" / "own").mkdir(parents=True)
    return root


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
    ]
    server = ServerLaunch(
        name="probe",
        command=PYTHON,
        args=("-I", "{worktree}/probe.py", str(port), str(place), str(wt), str(own),
              *map(str, paths)),
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
