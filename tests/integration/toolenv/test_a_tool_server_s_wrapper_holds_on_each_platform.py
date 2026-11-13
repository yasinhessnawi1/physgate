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
import subprocess
import sys
from pathlib import Path

import pytest

from physgate.oslayer.containment import SANDBOX_EXEC, bwrap_args, seatbelt_profile
from physgate.oslayer.policy import serial_devices

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
            devices=serial_devices("darwin"),
            command=PYTHON,
            exec_roots=exec_roots,
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
    args = bwrap_args(read_denied=(str(denied),), server_dir=str(own))
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
        seatbelt_profile(read_denied=(str(odd),), server_dir=str(own), devices=(), command=PYTHON)
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
