"""``physgate ui`` through the real command: it serves on loopback, or refuses to start.

It starts over the roots named, or refuses with a reason and exit code 2 before listening.
"""

from __future__ import annotations

import http.client
import json
import signal
import socketserver
import subprocess
import sys
from pathlib import Path

import pytest
from ui_rig import fake_ui, write_run

from physgate.cli import main
from physgate.ui import cli as ui_cli

#: Runs the real command in a process of its own, with the fixture build as the app.
#:
#: Its first statement gives the interrupt Python's own handler back. A process started from a
#: shell's background job inherits the interrupt as ignored, and Python keeps an ignored one
#: ignored, so the command run that way never saw the interrupt these tests stop it with: the
#: wait expired and the server was left running. The operator's Ctrl-C reaches a process whose
#: interrupt is not ignored, which is the case these tests prove.
LAUNCH = (
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


def _interrupt(process: subprocess.Popen[str]) -> tuple[str, str]:
    """Stop the command as Ctrl-C would, and never leave it running.

    A command still running when the wait expires is killed before the failure is raised, so a
    red test does not leave a server behind on the machine.
    """
    process.send_signal(signal.SIGINT)
    try:
        return process.communicate(timeout=10)
    except subprocess.TimeoutExpired:
        process.kill()
        process.communicate()
        raise


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
    world: dict[str, Path],
) -> None:
    process = subprocess.Popen(
        [
            sys.executable,
            "-c",
            LAUNCH,
            str(world["ui"]),
            "ui",
            "--root",
            str(world["root"]),
            "--port",
            "0",
        ],
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
    )
    try:
        assert process.stdout is not None
        lines: list[str] = []
        while not lines or lines[-1] != "}":
            line = process.stdout.readline()
            assert line, process.stderr.read() if process.stderr else "no output"
            lines.append(line.rstrip("\n"))
        started = json.loads("\n".join(lines))
        assert started["url"].startswith("http://127.0.0.1:")
        port = int(started["url"].rsplit(":", 1)[1].strip("/"))
        assert started["roots"] == [str(world["root"].resolve())]
        connection = http.client.HTTPConnection("127.0.0.1", port, timeout=10)
        connection.request("GET", "/api/runs")
        response = connection.getresponse()
        listed = json.loads(response.read())
        connection.close()
        assert response.status == 200
        assert [run["run_id"] for run in listed["runs"]] == ["run-1"]
    finally:
        _interrupt(process)
    assert process.returncode == 0


def test_an_empty_run_folder_is_served_and_lists_no_runs(
    world: dict[str, Path], tmp_path: Path
) -> None:
    """A machine with no run yet: the app is served, and the run list is empty, not refused."""
    empty = tmp_path / "physgate-runs"
    empty.mkdir(mode=0o700)
    process = subprocess.Popen(
        [sys.executable, "-c", LAUNCH, str(world["ui"]), "ui", "--root", str(empty)]
        + ["--port", "0"],
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
    )
    try:
        assert process.stdout is not None
        lines: list[str] = []
        while not lines or lines[-1] != "}":
            line = process.stdout.readline()
            assert line, process.stderr.read() if process.stderr else "no output"
            lines.append(line.rstrip("\n"))
        started = json.loads("\n".join(lines))
        assert started["roots"] == [str(empty.resolve())]
        port = int(started["url"].rsplit(":", 1)[1].strip("/"))
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
        _interrupt(process)
    assert process.returncode == 0


def test_an_operator_name_that_does_not_print_is_refused_before_anything_listens(
    world: dict[str, Path], capsys: pytest.CaptureFixture[str]
) -> None:
    error = _refused(
        capsys, ["ui", "--root", str(world["root"]), "--port", "0", "--operator", "a\nb"]
    )
    assert "printable name" in error["error"]


def test_the_command_prints_the_operator_s_address_and_no_route_serves_its_token(
    world: dict[str, Path],
) -> None:
    """The token is in the printed address's fragment, and in no response the server makes."""
    process = subprocess.Popen(
        [sys.executable, "-c", LAUNCH, str(world["ui"]), "ui", "--root", str(world["root"]),
         "--port", "0", "--operator", "Yasin H."],
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
    )  # fmt: skip
    try:
        assert process.stdout is not None
        lines: list[str] = []
        while not lines or lines[-1] != "}":
            line = process.stdout.readline()
            assert line, process.stderr.read() if process.stderr else "no output"
            lines.append(line.rstrip("\n"))
        started = json.loads("\n".join(lines))
        assert started["operator"] == "Yasin H."
        url, _, fragment = started["operator_url"].partition("#")
        assert url == started["url"]
        assert fragment.startswith("act=")
        token = fragment.removeprefix("act=")
        assert len(token) >= 40
        port = int(started["url"].rsplit(":", 1)[1].strip("/"))
        served = []
        for target in ("/", "/api/runs", "/api/runs/0/run-1/config"):
            connection = http.client.HTTPConnection("127.0.0.1", port, timeout=10)
            connection.request("GET", target)
            response = connection.getresponse()
            served.append(response.read().decode() + str(response.getheaders()))
            connection.close()
    finally:
        _, err = _interrupt(process)
    assert not [s for s in served if token in s]
    assert token not in err, "the token reached the server's log"


def test_without_an_operator_no_address_with_a_token_is_printed(world: dict[str, Path]) -> None:
    process = subprocess.Popen(
        [sys.executable, "-c", LAUNCH, str(world["ui"]), "ui", "--root", str(world["root"]),
         "--port", "0"],
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
    )  # fmt: skip
    try:
        assert process.stdout is not None
        lines: list[str] = []
        while not lines or lines[-1] != "}":
            line = process.stdout.readline()
            assert line, process.stderr.read() if process.stderr else "no output"
            lines.append(line.rstrip("\n"))
        started = json.loads("\n".join(lines))
    finally:
        _interrupt(process)
    assert started["operator"] is None
    assert "operator_url" not in started


def test_the_command_stops_on_the_interrupt_even_when_started_with_it_ignored(
    world: dict[str, Path],
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
    process = subprocess.Popen(
        [sys.executable, "-c", ignored, "-c", LAUNCH, str(world["ui"]), "ui",
         "--root", str(world["root"]), "--port", "0"],
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
    )  # fmt: skip
    try:
        assert process.stdout is not None
        first = process.stdout.readline()
        assert first, process.stderr.read() if process.stderr else "no output"
    finally:
        _interrupt(process)
    assert process.returncode == 0


def test_an_interrupt_that_lands_as_the_address_is_printed_still_stops_the_command_cleanly(
    world: dict[str, Path],
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
    process = subprocess.Popen(
        [sys.executable, "-c", interrupted_as_printed, str(world["ui"]), "ui",
         "--root", str(world["root"]), "--port", "0"],
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
    )  # fmt: skip
    try:
        out, err = process.communicate(timeout=10)
    except subprocess.TimeoutExpired:
        process.kill()
        process.communicate()
        raise
    assert process.returncode == 0, err
    assert json.loads(out)["url"].startswith("http://127.0.0.1:")
