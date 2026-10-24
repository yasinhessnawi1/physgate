"""``physgate ui`` through the real command: it serves on loopback, or refuses to start.

It starts over the roots named, or refuses with a reason and exit code 2 before listening.
"""

from __future__ import annotations

import contextlib
import http.client
import json
import os
import signal
import socketserver
import subprocess
import sys
from collections.abc import Callable, Iterator
from pathlib import Path

import pytest
from ui_command_rig import ORPHANED, gone, kill_left_over, launch_command, stop_command
from ui_rig import fake_ui, write_run

from physgate.cli import main
from physgate.ui import cli as ui_cli

#: Runs the real command in a process of its own, with the fixture build as the app.
#:
#: It first watches for the process that started it to go (``ORPHANED``), and then gives the
#: interrupt Python's own handler back. A process started from a shell's background job
#: inherits the interrupt as ignored, and Python keeps an ignored one ignored, so the command
#: run that way never saw the interrupt these tests stop it with: the wait expired and the
#: server was left running. The operator's Ctrl-C reaches a process whose interrupt is not
#: ignored, which is the case these tests prove.
LAUNCH = ORPHANED + (
    "import signal; signal.signal(signal.SIGINT, signal.default_int_handler); "
    "import sys; from pathlib import Path; import physgate.ui.cli as c; "
    "c._ui_root = lambda: Path(sys.argv[1]); "
    "from physgate.cli import main; raise SystemExit(main(sys.argv[2:]))"
)


@pytest.fixture
def world(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> dict[str, Path]:
    root = tmp_path / "runs"
    root.mkdir()
    write_run(root / "run-1", "run-1")
    held = tmp_path / "held"
    held.mkdir()
    ui = fake_ui(tmp_path / "checkout")
    monkeypatch.setattr(ui_cli, "_ui_root", lambda: ui)

    # A refusal test that starts a server by mistake must fail at once, not serve forever:
    # a missing refusal would otherwise hang the suite instead of turning it red.
    def started(self: socketserver.BaseServer, poll_interval: float = 0.5) -> None:
        msg = "the command started serving where it should have refused"
        raise AssertionError(msg)

    monkeypatch.setattr(socketserver.BaseServer, "serve_forever", started)
    return {"root": root, "held": held, "ui": ui}


Launch = Callable[..., subprocess.Popen[str]]


@pytest.fixture
def commands() -> Iterator[Launch]:
    """Starts the command for a test, ``commands(*argv, code=LAUNCH)``, and stops it after.

    Whatever the test did, at its end every command it started is stopped with its process
    group, and waited for.
    """
    started: list[subprocess.Popen[str]] = []

    def launch(*argv: str, code: str = LAUNCH) -> subprocess.Popen[str]:
        process = launch_command(code, *argv)
        started.append(process)
        return process

    yield launch
    for process in started:
        with contextlib.suppress(subprocess.TimeoutExpired):
            stop_command(process)


def _started(process: subprocess.Popen[str]) -> dict[str, object]:
    """The start-up record the command prints once it listens, read line by line."""
    assert process.stdout is not None
    lines: list[str] = []
    while not lines or lines[-1] != "}":
        line = process.stdout.readline()
        assert line, process.stderr.read() if process.stderr else "no output"
        lines.append(line.rstrip("\n"))
    started: dict[str, object] = json.loads("\n".join(lines))
    return started


def _refused(capsys: pytest.CaptureFixture[str], argv: list[str]) -> dict[str, str]:
    assert main(argv) == 2
    error: dict[str, str] = json.loads(capsys.readouterr().err)
    return error


def test_a_non_loopback_bind_is_refused_before_anything_listens(
    world: dict[str, Path], capsys: pytest.CaptureFixture[str]
) -> None:
    error = _refused(capsys, ["ui", "--root", str(world["root"]), "--bind", "0.0.0.0"])
    assert "loopback only" in error["error"]
    assert error["bind"] == "0.0.0.0"


def test_a_root_overlapping_the_held_out_tier_is_refused(
    world: dict[str, Path], capsys: pytest.CaptureFixture[str]
) -> None:
    inside = world["held"] / "runs"
    inside.mkdir()
    error = _refused(
        capsys, ["ui", "--root", str(inside), "--held-out", str(world["held"]), "--port", "0"]
    )
    assert "overlaps" in error["error"]


def test_a_root_holding_this_checkout_s_corpora_is_refused(
    world: dict[str, Path], capsys: pytest.CaptureFixture[str]
) -> None:
    checkout = Path(__file__).resolve().parents[3]
    assert (checkout / "corpora").is_dir(), "the checkout's corpora are the case this proves"
    error = _refused(capsys, ["ui", "--root", str(checkout), "--port", "0"])
    assert "overlaps" in error["error"]


def test_a_stale_build_is_refused(
    world: dict[str, Path], capsys: pytest.CaptureFixture[str]
) -> None:
    (world["ui"] / "src" / "main.ts").write_text("export const x = 9;\n")
    error = _refused(capsys, ["ui", "--root", str(world["root"]), "--port", "0"])
    assert "stale" in error["error"]


def test_no_source_checkout_is_refused(
    world: dict[str, Path], capsys: pytest.CaptureFixture[str], monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(ui_cli, "_ui_root", lambda: None)
    error = _refused(capsys, ["ui", "--root", str(world["root"]), "--port", "0"])
    assert "source checkout" in error["error"]


def test_the_command_serves_the_app_and_the_runs_on_loopback_and_stops_cleanly(
    world: dict[str, Path], commands: Launch
) -> None:
    process = commands(str(world["ui"]), "ui", "--root", str(world["root"]), "--port", "0")
    try:
        started = _started(process)
        assert str(started["url"]).startswith("http://127.0.0.1:")
        port = int(str(started["url"]).rsplit(":", 1)[1].strip("/"))
        assert started["roots"] == [str(world["root"].resolve())]
        connection = http.client.HTTPConnection("127.0.0.1", port, timeout=10)
        connection.request("GET", "/api/runs")
        response = connection.getresponse()
        listed = json.loads(response.read())
        connection.close()
        assert response.status == 200
        assert [run["run_id"] for run in listed["runs"]] == ["run-1"]
    finally:
        stop_command(process)
    assert process.returncode == 0


def test_an_empty_run_folder_is_served_and_lists_no_runs(
    world: dict[str, Path], tmp_path: Path, commands: Launch
) -> None:
    """A machine with no run yet: the app is served, and the run list is empty, not refused."""
    empty = tmp_path / "physgate-runs"
    empty.mkdir(mode=0o700)
    process = commands(str(world["ui"]), "ui", "--root", str(empty), "--port", "0")
    try:
        started = _started(process)
        assert started["roots"] == [str(empty.resolve())]
        port = int(str(started["url"]).rsplit(":", 1)[1].strip("/"))
        answers: dict[str, tuple[int, bytes]] = {}
        for path in ("/", "/api/runs"):
            connection = http.client.HTTPConnection("127.0.0.1", port, timeout=10)
            connection.request("GET", path)
            response = connection.getresponse()
            answers[path] = (response.status, response.read())
            connection.close()
        assert answers["/"][0] == 200
        assert answers["/"][1].lstrip().lower().startswith(b"<!doctype html>")
        assert answers["/api/runs"][0] == 200
        assert json.loads(answers["/api/runs"][1])["runs"] == []
    finally:
        stop_command(process)
    assert process.returncode == 0


def test_an_operator_name_that_does_not_print_is_refused_before_anything_listens(
    world: dict[str, Path], capsys: pytest.CaptureFixture[str]
) -> None:
    error = _refused(
        capsys, ["ui", "--root", str(world["root"]), "--port", "0", "--operator", "a\nb"]
    )
    assert "printable name" in error["error"]


def test_the_command_prints_the_operator_s_address_and_no_route_serves_its_token(
    world: dict[str, Path], commands: Launch
) -> None:
    """The token is in the printed address's fragment, and in no response the server makes."""
    process = commands(str(world["ui"]), "ui", "--root", str(world["root"]),
                       "--port", "0", "--operator", "Yasin H.")  # fmt: skip
    try:
        started = _started(process)
        assert started["operator"] == "Yasin H."
        url, _, fragment = str(started["operator_url"]).partition("#")
        assert url == started["url"]
        assert fragment.startswith("act=")
        token = fragment.removeprefix("act=")
        assert len(token) >= 40
        port = int(str(started["url"]).rsplit(":", 1)[1].strip("/"))
        served = []
        for target in ("/", "/api/runs", "/api/runs/0/run-1/config"):
            connection = http.client.HTTPConnection("127.0.0.1", port, timeout=10)
            connection.request("GET", target)
            response = connection.getresponse()
            served.append(response.read().decode() + str(response.getheaders()))
            connection.close()
    finally:
        _, err = stop_command(process)
    assert not [s for s in served if token in s]
    assert token not in err, "the token reached the server's log"


def test_without_an_operator_no_address_with_a_token_is_printed(
    world: dict[str, Path], commands: Launch
) -> None:
    process = commands(str(world["ui"]), "ui", "--root", str(world["root"]), "--port", "0")
    try:
        started = _started(process)
    finally:
        stop_command(process)
    assert started["operator"] is None
    assert "operator_url" not in started


def test_the_command_stops_on_the_interrupt_even_when_started_with_it_ignored(
    world: dict[str, Path], commands: Launch
) -> None:
    """A suite started from a shell's background job still stops every command it starts.

    That shell starts its job with the interrupt ignored, and every process below inherits it.
    The command started here inherits it the same way, so the tests above stop it only because
    ``LAUNCH`` gives the interrupt back first. Without that, this wait expires.
    """
    ignored = (
        "import os, signal, sys; signal.signal(signal.SIGINT, signal.SIG_IGN); "
        "os.execv(sys.executable, [sys.executable, *sys.argv[1:]])"
    )
    process = commands("-c", LAUNCH, str(world["ui"]), "ui",
                       "--root", str(world["root"]), "--port", "0", code=ignored)  # fmt: skip
    try:
        assert process.stdout is not None
        first = process.stdout.readline()
        assert first, process.stderr.read() if process.stderr else "no output"
    finally:
        stop_command(process)
    assert process.returncode == 0


def test_an_interrupt_that_lands_as_the_address_is_printed_still_stops_the_command_cleanly(
    world: dict[str, Path], commands: Launch
) -> None:
    """The printed address is what a caller waits for, so its interrupt may land at once.

    Here it lands as the print returns, every time, with no wait on either side: the command
    must stop as it does on any later interrupt, not die of the signal (exit -2).
    """
    interrupted_as_printed = (
        "import builtins\n"
        "printed = builtins.print\n"
        "def interrupting(*a, **k):\n"
        "    printed(*a, **k)\n"
        "    if a and '\"url\"' in str(a[0]):\n"
        "        raise KeyboardInterrupt\n"
        "builtins.print = interrupting\n" + LAUNCH
    )
    process = commands(str(world["ui"]), "ui", "--root", str(world["root"]), "--port", "0",
                       code=interrupted_as_printed)  # fmt: skip
    out, err = process.communicate(timeout=10)
    assert process.returncode == 0, err
    assert json.loads(out)["url"].startswith("http://127.0.0.1:")


# --- Nothing a test starts outlives it -----------------------------------------------------------
#
# The command runs in a process of its own, so a test that stops it late, or never, would leave
# a server listening on the machine after the suite. Servers left this way by early runs of
# this file were still running a week later.

#: The tests directory, from which a stand-in test process imports the launcher.
TESTS = Path(__file__).resolve().parents[2]


def _child(on_interrupt: str) -> str:
    """A child of the command's own: it sets its interrupt, says it is ready, and sleeps.

    ``stop`` marks, beside the fixture build, that it stopped on the interrupt.
    """
    return (
        "import signal, sys, time\n"
        "from pathlib import Path\n"
        "here = Path(sys.argv[1]).parent\n"
        "def stop(*_):\n"
        "    (here / 'child-stopped').write_text('stopped')\n"
        "    raise SystemExit(0)\n"
        f"signal.signal(signal.SIGINT, {on_interrupt})\n"
        "(here / 'child-ready').write_text('ready')\n"
        "time.sleep(60)\n"
    )


#: A child that stops on the interrupt, and one that ignores it and stops only by force.
STOPS, IGNORES = _child("stop"), _child("signal.SIG_IGN")
#: A command that ignores the interrupt as well: ``LAUNCH`` gives back what it is told is the
#: default handler.
IGNORING = "import signal\nsignal.default_int_handler = signal.SIG_IGN\n"


def with_a_child(child: str, command: str = LAUNCH) -> str:
    """The command, once it has started ``child`` and printed the child's pid on a line.

    The child holds none of the command's pipes, so reading the command's output to its end
    does not wait for the child. Its command line names the fixture build, as the command's
    does, so a test knows its own processes from any other.
    """
    return (
        "import subprocess, sys, time\n"
        "from pathlib import Path\n"
        f"child = subprocess.Popen([sys.executable, '-c', {child!r}, sys.argv[1]],"
        " stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)\n"
        "ready = Path(sys.argv[1]).parent / 'child-ready'\n"
        "for _ in range(1000):\n"
        "    if ready.exists():\n"
        "        break\n"
        "    time.sleep(0.01)\n"
        "print(child.pid, flush=True)\n" + command
    )


#: A quick stop for the tests below, whose children may be meant to need force.
GRACE_S = 1.0


@pytest.mark.parametrize(
    ("command", "child"),
    [(LAUNCH, STOPS), (LAUNCH, IGNORES), (IGNORING + LAUNCH, IGNORES)],
    ids=[
        "a-child-that-stops-on-the-interrupt",
        "a-child-that-ignores-it",
        "a-command-and-its-child-that-ignore-it",
    ],
)
def test_stopping_the_command_stops_everything_it_started(
    world: dict[str, Path], commands: Launch, command: str, child: str
) -> None:
    """The interrupt reaches the command's whole process group, and force what ignores it."""
    process = commands(str(world["ui"]), "ui", "--root", str(world["root"]), "--port", "0",
                       code=with_a_child(child, command))  # fmt: skip
    assert process.stdout is not None
    left = [process.pid, int(process.stdout.readline())]
    try:
        _started(process)
        if command == LAUNCH:
            stop_command(process, grace=GRACE_S)
            assert process.returncode == 0
        else:
            with pytest.raises(subprocess.TimeoutExpired):
                stop_command(process, grace=GRACE_S)
        assert gone(left[1]), "the command's own child outlived the command's stop"
        if child == STOPS:
            assert (world["ui"].parent / "child-stopped").read_text() == "stopped"
    finally:
        kill_left_over(left, str(world["ui"]))


#: A test process, stood in for: it starts the command as the tests do, says the pids, and
#: waits to be killed.
STAND_IN = (
    "import sys, time\n"
    "sys.path.insert(0, sys.argv[1])\n"
    "from ui_command_rig import launch_command\n"
    "process = launch_command(sys.argv[2], *sys.argv[3:])\n"
    "print(process.pid, flush=True)\n"
    "for line in process.stdout:\n"
    "    print(line, end='', flush=True)\n"
    "    if line.rstrip() == '}':\n"
    "        break\n"
    "time.sleep(60)\n"
)


def test_a_command_whose_test_process_dies_before_its_teardown_stops_with_its_group(
    world: dict[str, Path],
) -> None:
    """A command stops with its group once the process that started it is gone.

    A test run killed mid-test (a timeout, a cancelled job, a dropped connection) runs no
    teardown, so only the command itself can see that its test is gone.
    """
    test = subprocess.Popen(
        [sys.executable, "-c", STAND_IN, str(TESTS), with_a_child(IGNORES), str(world["ui"]),
         "ui", "--root", str(world["root"]), "--port", "0"],
        stdin=subprocess.DEVNULL,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        process_group=0,
    )  # fmt: skip
    left: list[int] = []
    try:
        assert test.stdout is not None
        left += [int(test.stdout.readline()), int(test.stdout.readline())]
        _started(test)
        test.kill()
        outlived = [pid for pid in left if not gone(pid)]
        assert not outlived, f"the command and its child outlived their test process: {outlived}"
    finally:
        # The stand-in is not reaped yet, so its process group is still the one it made. With
        # nothing but its zombie left in it, the group refuses the signal (macOS: EPERM).
        with contextlib.suppress(ProcessLookupError, PermissionError):
            os.killpg(test.pid, signal.SIGKILL)
        test.communicate()
        kill_left_over(left, str(world["ui"]))


@pytest.fixture
def left_running() -> Iterator[list[subprocess.Popen[str]]]:
    """Commands a test leaves running; once every fixture is torn down, none may still run."""
    left: list[subprocess.Popen[str]] = []
    yield left
    outlived = [process.pid for process in left if process.poll() is None]
    for process in left:
        if process.poll() is None:  # the test's own child, not yet reaped: its pid is its own
            process.kill()
            process.communicate()
    assert not outlived, f"a command outlived its test: {outlived}"


def test_a_command_its_test_never_stops_is_stopped_when_the_test_ends(
    world: dict[str, Path], left_running: list[subprocess.Popen[str]], commands: Launch
) -> None:
    """A test that fails before it stops what it started leaves nothing running."""
    process = commands(str(world["ui"]), "ui", "--root", str(world["root"]), "--port", "0")
    left_running.append(process)
    assert str(_started(process)["url"]).startswith("http://127.0.0.1:")
