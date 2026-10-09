"""``physgate ui`` through the real command: it serves on loopback, or refuses to start.

It starts over the roots named, or refuses with a reason and exit code 2 before listening.
"""

from __future__ import annotations

import http.client
import json
import signal
import subprocess
import sys
from pathlib import Path

import pytest
from ui_rig import fake_ui, write_run

from physgate.cli import main
from physgate.ui import cli as ui_cli

#: Runs the real command in a process of its own, with the fixture build as the app.
LAUNCH = (
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
    return {"root": root, "held": held, "ui": ui}


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
        process.send_signal(signal.SIGINT)
        code = process.wait(timeout=10)
    assert code == 0
