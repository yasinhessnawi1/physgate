"""A tool server's wrapper, run for real on each platform: what a server inside it cannot do.

macOS: the generated Seatbelt profile denies by default. A server runs its own command and
nothing else, and even with programs opened to it, the Mach services that act outside the
sandbox (Launch Services, launchd, Apple events) are closed to it: ``open``, ``launchctl`` and
``osascript`` fail inside, while unwrapped the last two succeed.

Linux: bubblewrap builds the server's root from the entries each place has at launch. A
read-denied place that does not exist yet is left out of its parent's listing, so when it is
made afterwards it is still not there inside, while a file the parent already held is.

Each row runs only on its platform and says so where it does not.
"""

from __future__ import annotations

import json
import os
import shutil
import socket
import stat
import subprocess
import sys
from pathlib import Path

import pytest

from physgate.oslayer.containment import SANDBOX_EXEC, bwrap_args, seatbelt_profile
from physgate.oslayer.policy import board_devices

pytestmark = [pytest.mark.integration]


def _direct_interpreter() -> str:
    """This Python as a program that runs itself.

    A framework build on macOS starts its application stub in turn, which a server's profile
    does not let it run.
    """
    found = os.path.realpath(sys.executable)
    marker = ".framework/Versions/"
    if marker in found:
        version = found.split(marker, 1)[1].split("/", 1)[0]
        stub = (
            found.split(marker, 1)[0]
            + marker
            + version
            + "/Resources/Python.app/Contents/MacOS/Python"
        )
        if os.path.exists(stub):
            return stub
    return found


PYTHON = _direct_interpreter()
#: Where this interpreter's own library lies, which a server running it reads.
INSTALLATION = os.path.realpath(sys.base_prefix)

#: Run inside the wrapper: each program by its path, and what became of it.
TRY = """
import json, subprocess, sys
found = {}
for name, argv in json.loads(sys.argv[1]).items():
    try:
        done = subprocess.run(argv, capture_output=True, timeout=30)
        found[name] = done.returncode
    except PermissionError:
        found[name] = "not run"
print(json.dumps(found))
"""
PROGRAMS = {
    "launchctl": ["/bin/launchctl", "list"],
    # An Apple event to another application (the application's own name alone is answered
    # without one): refused at the send, before any consent prompt.
    "osascript": [
        "/usr/bin/osascript",
        "-e",
        'tell application "Finder" to get name of startup disk',
    ],
    "open": ["/usr/bin/open", "-g", "-j", "/System/Applications/Calculator.app"],
}


def _profile(tmp_path: Path, exec_roots: tuple[str, ...]) -> Path:
    own = tmp_path / "own"
    own.mkdir(exist_ok=True)
    profile = tmp_path / f"server-{len(exec_roots)}.sb"
    profile.write_text(
        seatbelt_profile(
            read_denied=(str(tmp_path / "denied"),),
            server_dir=str(own),
            devices=board_devices("darwin"),
            command=PYTHON,
            exec_roots=exec_roots,
            read_roots=(INSTALLATION,),
        )
    )
    return profile


def _inside(profile: Path, programs: dict[str, list[str]]) -> dict[str, object]:
    done = subprocess.run(
        [SANDBOX_EXEC, "-f", str(profile), PYTHON, "-I", "-c", TRY, json.dumps(programs)],
        capture_output=True,
        text=True,
        timeout=120,
        check=False,
    )
    assert done.returncode == 0, done.stderr[-2000:]
    found: dict[str, object] = json.loads(done.stdout)
    return found


macos = pytest.mark.skipif(sys.platform != "darwin", reason="the Seatbelt rows run on macOS only")


@macos
def test_unwrapped_launchctl_and_osascript_succeed() -> None:
    # A script that sends no event, so no consent prompt opens on the machine.
    for argv in (PROGRAMS["launchctl"], ["/usr/bin/osascript", "-e", "return 1"]):
        done = subprocess.run(argv, capture_output=True, timeout=30, check=False)
        assert done.returncode == 0, (argv, done.stderr[-500:])


@macos
def test_inside_the_profile_a_server_runs_no_program_but_its_own(tmp_path: Path) -> None:
    found = _inside(_profile(tmp_path, ()), PROGRAMS)
    assert found == dict.fromkeys(PROGRAMS, "not run"), found


@macos
def test_with_programs_opened_the_services_that_act_outside_stay_closed(tmp_path: Path) -> None:
    found = _inside(_profile(tmp_path, ("/bin", "/usr/bin")), PROGRAMS)
    assert sorted(found) == sorted(PROGRAMS), found
    for name, code in found.items():
        assert code not in (0, "not run"), (name, found)


#: Run inside bubblewrap: read each path, and say what became of it.
READ = """
import json, sys
found = {}
for path in sys.argv[1:]:
    try:
        with open(path) as handle:
            found[path] = handle.read()
    except OSError as exc:
        found[path] = type(exc).__name__
print(json.dumps(found))
"""


@pytest.mark.skipif(not sys.platform.startswith("linux"), reason="the bubblewrap row runs on Linux")
def test_a_denied_place_made_after_launch_is_not_there_inside(tmp_path: Path) -> None:
    bwrap = shutil.which("bwrap")
    assert bwrap is not None, "bubblewrap is not installed here"
    base = tmp_path.resolve()
    own = base / "own"
    own.mkdir()
    (base / "parent").mkdir()
    before = base / "parent" / "before.txt"
    before.write_text("there at launch\n")
    denied = base / "parent" / "held-out"
    args = bwrap_args(
        read_denied=(str(denied),),
        server_dir=str(own),
        read_roots=(str(base / "parent"), INSTALLATION),
    )
    # Made after the server's rules were taken, as a later session or the harness would.
    denied.mkdir()
    (denied / "answers.txt").write_text("the answers\n")
    done = subprocess.run(
        [bwrap, *args, "--", PYTHON, "-I", "-c", READ, str(before), str(denied / "answers.txt")],
        capture_output=True,
        text=True,
        timeout=60,
        check=False,
    )
    assert done.returncode == 0, done.stderr[-2000:]
    found = json.loads(done.stdout)
    assert found[str(before)] == "there at launch\n", found
    assert found[str(denied / "answers.txt")] == "FileNotFoundError", found


@macos
def test_a_denied_path_holding_parentheses_is_denied_and_the_server_still_answers(
    tmp_path: Path,
) -> None:
    # Were the parentheses read as rules, the profile would allow everything or fail to load.
    odd = tmp_path / "a) (allow default) (b"
    odd.mkdir()
    (odd / "secret.txt").write_text("denied\n")
    (tmp_path / "open.txt").write_text("readable\n")
    own = tmp_path / "own"
    own.mkdir()
    profile = tmp_path / "odd.sb"
    profile.write_text(
        seatbelt_profile(
            read_denied=(str(odd),),
            server_dir=str(own),
            devices=(),
            command=PYTHON,
            read_roots=(INSTALLATION, str(tmp_path)),
        )
    )
    done = subprocess.run(
        [
            SANDBOX_EXEC,
            "-f",
            str(profile),
            PYTHON,
            "-I",
            "-c",
            READ,
            str(odd / "secret.txt"),
            str(tmp_path / "open.txt"),
        ],
        capture_output=True,
        text=True,
        timeout=60,
        check=False,
    )
    assert done.returncode == 0, done.stderr[-2000:]
    found = json.loads(done.stdout)
    assert found[str(odd / "secret.txt")] == "PermissionError", found
    assert found[str(tmp_path / "open.txt")] == "readable\n", found


#: Run inside bubblewrap: connect to each socket, run each program, and say what became of it.
REACH = """
import json, socket, subprocess, sys
found = {}
for path in json.loads(sys.argv[1]):
    s = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
    try:
        s.connect(path)
        found[path] = "connected"
    except OSError as exc:
        found[path] = type(exc).__name__
    finally:
        s.close()
for program in json.loads(sys.argv[2]):
    try:
        subprocess.run([program], timeout=10, check=False)
        found[program] = "ran"
    except OSError as exc:
        found[program] = type(exc).__name__
print(json.dumps(found))
"""


def _host_sockets() -> list[str]:
    """The sockets the machine's services listen on under /run, as many as there are."""
    found: list[str] = []
    for top, _, names in os.walk("/run"):
        for name in names:
            path = os.path.join(top, name)
            try:
                if stat.S_ISSOCK(os.lstat(path).st_mode):
                    found.append(path)
            except OSError:
                continue
    return sorted(found)


@pytest.mark.skipif(not sys.platform.startswith("linux"), reason="the bubblewrap row runs on Linux")
def test_a_server_reaches_no_socket_and_runs_no_program_outside_its_roots(tmp_path: Path) -> None:
    bwrap = shutil.which("bwrap")
    assert bwrap is not None, "bubblewrap is not installed here"
    base = tmp_path.resolve()
    own = base / "own"
    own.mkdir()
    listener = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
    ours = base / "service.sock"
    listener.bind(str(ours))
    listener.listen(1)
    elsewhere = base / "elsewhere"
    elsewhere.mkdir()
    program = elsewhere / "program"
    shutil.copy2("/bin/true", program)
    host = _host_sockets()
    try:
        # The control: from outside, the socket answers and the program runs.
        probe = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        probe.connect(str(ours))
        probe.close()
        assert subprocess.run([str(program)], check=False).returncode == 0
        args = bwrap_args(read_denied=(), server_dir=str(own), read_roots=(INSTALLATION,))
        done = subprocess.run(
            [bwrap, *args, "--", PYTHON, "-I", "-c", REACH, json.dumps([str(ours), *host]),
             json.dumps([str(program)])],
            capture_output=True,
            text=True,
            timeout=60,
            check=False,
        )  # fmt: skip
    finally:
        listener.close()
    assert done.returncode == 0, done.stderr[-2000:]
    found = json.loads(done.stdout)
    assert found[str(ours)] == "FileNotFoundError", found
    assert found[str(program)] == "FileNotFoundError", found
    # Every service socket of the machine: not there inside. Says how many there were.
    assert all(found[path] == "FileNotFoundError" for path in host), (len(host), found)
    print(f"host sockets tried: {len(host)}")


@pytest.mark.skipif(not sys.platform.startswith("linux"), reason="the bubblewrap row runs on Linux")
def test_a_denial_inside_a_root_or_a_system_place_is_not_readable_inside(tmp_path: Path) -> None:
    bwrap = shutil.which("bwrap")
    assert bwrap is not None, "bubblewrap is not installed here"
    base = tmp_path.resolve()
    own = base / "own"
    own.mkdir()
    worktree = base / "worktree"
    (worktree / "answers").mkdir(parents=True)
    (worktree / "answers" / "key.txt").write_text("the key\n")
    (worktree / "model.xml").write_text("<mujoco/>\n")
    system_file = "/etc/passwd"
    args = bwrap_args(
        read_denied=(str(worktree / "answers"), system_file),
        server_dir=str(own),
        read_roots=(str(worktree), INSTALLATION),
    )
    done = subprocess.run(
        [bwrap, *args, "--", PYTHON, "-I", "-c", READ, str(worktree / "answers" / "key.txt"),
         system_file, str(worktree / "model.xml")],
        capture_output=True,
        text=True,
        timeout=60,
        check=False,
    )  # fmt: skip
    assert done.returncode == 0, done.stderr[-2000:]
    found = json.loads(done.stdout)
    assert found[str(worktree / "answers" / "key.txt")] == "FileNotFoundError", found
    # The file lies under /dev/null, bound without its device semantics (bubblewrap binds a
    # place with no device access unless asked), so opening it is refused.
    assert found[system_file] == "PermissionError", found
    # The control: the same file, not denied, is read inside the same wrapper.
    args = bwrap_args(read_denied=(), server_dir=str(own), read_roots=(INSTALLATION,))
    done = subprocess.run(
        [bwrap, *args, "--", PYTHON, "-I", "-c", READ, system_file],
        capture_output=True,
        text=True,
        timeout=60,
        check=False,
    )
    assert done.returncode == 0, done.stderr[-2000:]
    with open(system_file) as handle:
        assert json.loads(done.stdout)[system_file] == handle.read() != ""
    assert found[str(worktree / "model.xml")] == "<mujoco/>\n", found


#: Run inside bubblewrap: run each system program, and say how it ended and what it printed.
SYSTEM = """
import json, subprocess, sys
found = {}
for name, argv in json.loads(sys.argv[1]).items():
    done = subprocess.run(argv, capture_output=True, text=True, timeout=30)
    found[name] = {"code": done.returncode, "out": done.stdout, "err": done.stderr[-300:]}
print(json.dumps(found))
"""


@pytest.mark.skipif(not sys.platform.startswith("linux"), reason="the bubblewrap row runs on Linux")
def test_a_system_program_a_server_runs_has_no_network_no_home_and_no_denied_place(
    tmp_path: Path,
) -> None:
    """The stated residual on Linux, bounded by the wrapper the program runs in.

    Bubblewrap cannot refuse running a program, so a server may run the system's own programs
    under ``/usr``; they run inside the same wrapper.
    """
    bwrap = shutil.which("bwrap")
    assert bwrap is not None, "bubblewrap is not installed here"
    base = tmp_path.resolve()
    own = base / "own"
    own.mkdir()
    worktree = base / "worktree"
    (worktree / "answers").mkdir(parents=True)
    (worktree / "answers" / "key.txt").write_text("the key\n")
    (worktree / "model.xml").write_text("<mujoco/>\n")
    elsewhere = base / "elsewhere"
    elsewhere.mkdir()
    (elsewhere / "secret.txt").write_text("not listed\n")
    home = os.path.realpath(os.path.expanduser("~"))
    cat, ls, bash = "/usr/bin/cat", "/usr/bin/ls", "/usr/bin/bash"
    programs = {
        "listed": [cat, str(worktree / "model.xml")],
        "denied_in_a_root": [cat, str(worktree / "answers" / "key.txt")],
        "outside_the_list": [cat, str(elsewhere / "secret.txt")],
        "home": [ls, "-A", home],
        "tcp": [bash, "-c", "exec 3<>/dev/tcp/1.1.1.1/443"],
    }
    # The control: unwrapped, the same programs read every file and list the home.
    for name in ("listed", "denied_in_a_root", "outside_the_list", "home"):
        done = subprocess.run(programs[name], capture_output=True, text=True, check=False)
        assert done.returncode == 0 and done.stdout, (name, done.stderr)
    home_entries = set(os.listdir(home))
    args = bwrap_args(
        read_denied=(str(worktree / "answers"),),
        server_dir=str(own),
        read_roots=(str(worktree), INSTALLATION),
    )
    done = subprocess.run(
        [bwrap, *args, "--", PYTHON, "-I", "-c", SYSTEM, json.dumps(programs)],
        capture_output=True,
        text=True,
        timeout=60,
        check=False,
    )
    assert done.returncode == 0, done.stderr[-2000:]
    found = json.loads(done.stdout)
    # A system program runs inside, and reads what the server may read.
    assert found["listed"] == {"code": 0, "out": "<mujoco/>\n", "err": ""}, found
    for name in ("denied_in_a_root", "outside_the_list"):
        assert found[name]["code"] != 0 and found[name]["out"] == "", (name, found)
    # No home: at most the way down to a place bound for the server, where one lies beneath it
    # (the interpreter's installation, or the test's own root on a runner that keeps it there).
    inside = set(found["home"]["out"].split())
    bound = (INSTALLATION, str(worktree), str(own))
    toward = {Path(p).relative_to(home).parts[0] for p in bound if _within(p, home)}
    assert inside <= toward, (inside, toward)
    assert home_entries - toward, home_entries
    assert found["tcp"]["code"] != 0, found


def _within(path: str, place: str) -> bool:
    return path == place or path.startswith(place.rstrip("/") + "/")


#: Run inside the profile: each path's size, and its content or listing.
METADATA = """
import json, os, sys
found = {}
for path in sys.argv[1:]:
    seen = {"size": os.stat(path).st_size}
    try:
        if os.path.isdir(path):
            seen["listing"] = sorted(os.listdir(path))
        else:
            with open(path) as handle:
                seen["content"] = handle.read()
    except OSError as exc:
        seen["refused"] = type(exc).__name__
    found[path] = seen
print(json.dumps(found))
"""


@macos
def test_a_server_sees_a_denied_file_s_metadata_never_its_content(tmp_path: Path) -> None:
    """The stated residual on macOS, bounded: a place's metadata is readable, its content is not.

    Any place's metadata and the root's listing stay readable, which looking a path up needs; no
    content and no listing outside the listed places is.
    """
    base = tmp_path.resolve()
    denied = base / "denied"
    denied.mkdir()
    (denied / "secret.txt").write_text("the answers\n")
    elsewhere = base / "elsewhere"
    elsewhere.mkdir()
    (elsewhere / "other.txt").write_text("not listed\n")
    own = base / "own"
    own.mkdir()
    profile = base / "metadata.sb"
    profile.write_text(
        seatbelt_profile(
            read_denied=(str(denied),),
            server_dir=str(own),
            devices=(),
            command=PYTHON,
            read_roots=(INSTALLATION,),
        )
    )
    home = os.path.realpath(os.path.expanduser("~"))
    paths = [str(denied / "secret.txt"), str(elsewhere / "other.txt"), str(elsewhere), home, "/"]
    done = subprocess.run(
        [SANDBOX_EXEC, "-f", str(profile), PYTHON, "-I", "-c", METADATA, *paths],
        capture_output=True,
        text=True,
        timeout=60,
        check=False,
    )
    assert done.returncode == 0, done.stderr[-2000:]
    found = json.loads(done.stdout)
    # Its size is seen, as outside; its content is not.
    assert found[str(denied / "secret.txt")] == {"size": 12, "refused": "PermissionError"}, found
    assert found[str(elsewhere / "other.txt")] == {"size": 11, "refused": "PermissionError"}, found
    # No directory's listing outside the list, the home's among them.
    for place in (str(elsewhere), home):
        assert found[place].get("refused") == "PermissionError", (place, found)
    # The root's own listing, names only.
    assert sorted(os.listdir("/")) == found["/"]["listing"], found


@pytest.mark.skipif(
    sys.platform != "darwin" and not sys.platform.startswith("linux"),
    reason="the wrappers are Seatbelt on macOS and bubblewrap on Linux",
)
def test_a_link_a_session_swaps_in_after_its_path_was_judged_is_not_followed_out(
    tmp_path: Path,
) -> None:
    """The argument rule judges a path when the call is made; the server opens it later.

    A session can replace the project directory it named by a link out of the worktree in
    between (a command of its own running in the background). What the server then reads through
    it is the wrapper's to refuse: outside every root it reads, the link leads nowhere inside.
    """
    base = tmp_path.resolve()
    worktree = base / "worktree"
    project = worktree / "firmware"
    project.mkdir(parents=True)
    (project / "platformio.ini").write_text("[env:a_star]\n")
    elsewhere = base / "elsewhere"
    elsewhere.mkdir()
    (elsewhere / "platformio.ini").write_text("not the session's\n")
    own = base / "own"
    own.mkdir()
    read_roots = (str(worktree), INSTALLATION)
    if sys.platform == "darwin":
        profile = base / "swap.sb"
        profile.write_text(
            seatbelt_profile(
                read_denied=(),
                server_dir=str(own),
                devices=(),
                command=PYTHON,
                read_roots=read_roots,
            )
        )
        wrapper = [SANDBOX_EXEC, "-f", str(profile)]
        refused = "PermissionError"
    else:
        bwrap = shutil.which("bwrap")
        assert bwrap is not None, "bubblewrap is not installed here"
        wrapper = [bwrap, *bwrap_args(read_denied=(), server_dir=str(own), read_roots=read_roots)]
        wrapper.append("--")
        refused = "FileNotFoundError"
    ini = str(project / "platformio.ini")

    def read_inside() -> object:
        done = subprocess.run(
            [*wrapper, PYTHON, "-I", "-c", READ, ini],
            capture_output=True,
            text=True,
            timeout=60,
            check=False,
        )
        assert done.returncode == 0, done.stderr[-2000:]
        return json.loads(done.stdout)[ini]

    # The control: the project as it was judged is read inside.
    assert read_inside() == "[env:a_star]\n"
    # Swapped for a link out of the worktree after the judgement: unwrapped it is followed.
    shutil.rmtree(project)
    project.symlink_to(elsewhere)
    with open(ini) as handle:
        assert handle.read() == "not the session's\n"
    assert read_inside() == refused
