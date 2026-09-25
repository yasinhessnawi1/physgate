"""The shell wrapper turns every hook outcome except a clean pass into a refusal.

Measured against the pinned Claude Code: a hook that exits 1, crashes, is
killed, cannot start, or hangs past Claude Code's timeout lets the tool run.
These tests run the wrapper directly around each of those outcomes.
"""

from __future__ import annotations

import subprocess
import sys
import time
from pathlib import Path

import pytest

import physgate.hooks

TRAMPOLINE = Path(physgate.hooks.__file__).parent / "trampoline.sh"


def _through(watchdog: str, *command: str, stdin: str = "{}") -> tuple[int, str, float]:
    start = time.monotonic()
    proc = subprocess.run(
        ["/bin/sh", str(TRAMPOLINE), watchdog, *command],
        input=stdin,
        capture_output=True,
        text=True,
        check=False,
        timeout=30,
    )
    return proc.returncode, proc.stdout, time.monotonic() - start


def _py(code: str) -> tuple[str, ...]:
    return (sys.executable, "-c", code)


def test_a_clean_pass_passes_with_its_output() -> None:
    rc, out, _ = _through("5", *_py("import sys; print(sys.stdin.read())"), stdin="payload")
    assert (rc, out.strip()) == (0, "payload")


def test_a_refusal_passes_with_its_output() -> None:
    rc, out, _ = _through("5", *_py("print('refused'); raise SystemExit(2)"))
    assert (rc, out.strip()) == (2, "refused")


@pytest.mark.parametrize(
    "command",
    [
        _py("raise SystemExit(1)"),
        _py("raise SystemExit(3)"),
        _py("raise RuntimeError('crash')"),
        _py("import os, signal; os.kill(os.getpid(), signal.SIGKILL)"),
        ("/nonexistent/interpreter", "-c", "pass"),
    ],
    ids=["exit-1", "exit-3", "exception", "killed", "missing-interpreter"],
)
def test_every_other_outcome_becomes_a_refusal(command: tuple[str, ...]) -> None:
    rc, _, _ = _through("5", *command)
    assert rc == 2


def test_a_hung_hook_is_killed_by_the_watchdog_and_refused() -> None:
    rc, _, elapsed = _through("1", *_py("import time; time.sleep(20)"))
    assert rc == 2
    assert elapsed < 5, f"the watchdog took {elapsed:.1f} s"


def test_a_fast_pass_does_not_wait_for_the_watchdog_and_leaves_no_sleeper() -> None:
    rc, _, elapsed = _through("7.391", *_py("pass"))
    assert rc == 0
    assert elapsed < 3, f"a clean pass took {elapsed:.1f} s; the watchdog is holding the pipe"
    time.sleep(0.2)
    ps = subprocess.run(["ps", "-A", "-o", "command="], capture_output=True, text=True, check=True)
    assert "sleep 7.391" not in ps.stdout
