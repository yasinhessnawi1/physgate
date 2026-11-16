"""A run ended mid-session leaves no session's credential file in its run directory.

A session's credential is a file in the session's own directory, inside the run directory, for
as long as the session runs; the session's end removes it. A run process ended by SIGTERM (or an
interrupt, or a hang-up) while a session ran used to end at once: the session, leading a group of
its own, ran on, and its credential file stayed in the run directory, which is evidence that gets
copied. Now a stop signal ends the run's sessions and removes their files before the process
ends by that signal; a run killed outright leaves them, and the next resume removes the file of
every session nothing runs as any more, before anything else, and leaves a running one's alone.

The run process here is a stand-in that spawns one fake session the way the run spawns one; the
fake writes its own login file and runs until it is stopped. Every credential is a dummy, and no
file's content is read: only its name.
"""

from __future__ import annotations

import json
import os
import signal
import subprocess
import sys
import time
from collections.abc import Iterator
from pathlib import Path

import pytest

from physgate.cli import main
from physgate.orchestrator import stop_signals
from physgate.orchestrator.cli import Registrations
from physgate.orchestrator.credentials import KEY_FILE, KEY_HELPER, LOGIN_FILE
from physgate.orchestrator.processes import ProcessTableError, started_at

HERE = Path(__file__).resolve().parent
CHILD = HERE / "credential_stop_child.py"
SESSION_ID = "0b6f3c1e-5d7a-4f63-9a51-credentialrow"
NAMES = frozenset({LOGIN_FILE, KEY_FILE, KEY_HELPER})
#: The secrets the stand-in run process is never handed.
CREDENTIAL_VARIABLES = ("ANTHROPIC_API_KEY", "ANTHROPIC_AUTH_TOKEN", "CLAUDE_CODE_OAUTH_TOKEN")
FAKE_BINARY = """#!/bin/sh
[ "$IGNORE_TERM" = 1 ] && trap '' TERM
printf '%s' '{"dummy": "not-a-credential"}' > "$CLAUDE_CONFIG_DIR/.credentials.json"
: > "$READY"
while :; do sleep 0.1; done
"""


def credential_files(top: Path) -> list[str]:
    """Every file under ``top`` named as a credential is, by its path only; never read."""
    return sorted(
        os.path.join(where, name)
        for where, _dirs, files in os.walk(top)
        for name in files
        if name in NAMES
    )


class Started:
    """One stand-in run process, its session's directory, and the session once it is ready."""

    def __init__(self, tmp_path: Path, *, seeded: bool = True, ignore_term: bool = False) -> None:
        self.run_dir = tmp_path / "run"
        self.sdir = self.run_dir / "sessions" / SESSION_ID
        self.sdir.mkdir(parents=True)
        fake = tmp_path / "fake-claude"
        fake.write_text(FAKE_BINARY)
        fake.chmod(0o755)
        env = {k: v for k, v in os.environ.items() if k not in CREDENTIAL_VARIABLES}
        self.log = (tmp_path / "child.out").open("wb")
        self.process = subprocess.Popen(
            [sys.executable, str(CHILD), str(self.sdir), str(fake), str(int(seeded))]
            + [str(int(ignore_term))],
            env=env,
            stdout=self.log,
            stderr=self.log,
        )
        deadline = time.monotonic() + 60
        record = self.sdir / "process.json"
        while not ((self.sdir / "ready").exists() and record.exists()):
            assert self.process.poll() is None, (tmp_path / "child.out").read_text()
            assert time.monotonic() < deadline, "the session never became ready"
            time.sleep(0.05)
        held = json.loads(record.read_text())
        self.pid, self.started = int(held["pid"]), str(held["started"])

    def running(self) -> bool:
        return started_at(self.pid) == self.started

    def end_session_from_outside(self) -> None:
        if self.running():
            os.killpg(self.pid, signal.SIGKILL)
        deadline = time.monotonic() + 30
        while self.running():
            assert time.monotonic() < deadline, "the session outlived its SIGKILL"
            time.sleep(0.05)

    def close(self) -> None:
        if self.process.poll() is None:
            self.process.kill()
            self.process.wait()
        self.end_session_from_outside()
        self.log.close()


@pytest.fixture
def started(tmp_path: Path) -> Iterator[list[Started]]:
    made: list[Started] = []
    yield made
    for each in made:
        each.close()


def _resume(tmp_path: Path, run_dir: Path) -> int:
    """``physgate resume`` on ``run_dir``, as an operator types it."""
    argv = ["resume", "--run-dir", str(run_dir), "--target", str(tmp_path / "target")]
    return main(
        [*argv, "--install", str(tmp_path / "install"), "--review-root", str(tmp_path / "rs")],
        Registrations(),
    )


@pytest.mark.parametrize("signum", [signal.SIGTERM, signal.SIGINT, signal.SIGHUP])
@pytest.mark.parametrize("seeded", [True, False], ids=["harness-written", "binary-written"])
def test_a_stop_signal_ends_the_session_and_leaves_no_credential_file(
    tmp_path: Path, started: list[Started], signum: int, seeded: bool
) -> None:
    run = Started(tmp_path, seeded=seeded)
    started.append(run)
    assert credential_files(run.run_dir), "the session had no credential file to leave"
    run.process.send_signal(signum)
    code = run.process.wait(timeout=60)
    # Ended by the signal, as before: nothing of the run's own records is written on the way.
    assert code == -signum, (tmp_path / "child.out").read_text()
    assert credential_files(run.run_dir) == []
    assert not run.running(), "the session outlived its run's stop signal"


def test_a_session_that_ignores_sigterm_is_killed_within_the_bound(
    tmp_path: Path, started: list[Started]
) -> None:
    run = Started(tmp_path, ignore_term=True)
    started.append(run)
    began = time.monotonic()
    run.process.send_signal(signal.SIGTERM)
    code = run.process.wait(timeout=60)
    assert code == -signal.SIGTERM
    assert time.monotonic() - began < stop_signals_grace() + 20
    assert credential_files(run.run_dir) == []
    assert not run.running(), "a session that ignored SIGTERM outlived the bound"


def stop_signals_grace() -> float:
    return float(getattr(stop_signals, "GRACE_S", 5.0))


def test_a_resume_after_a_kill_removes_the_credential_of_a_session_no_longer_running(
    tmp_path: Path, started: list[Started]
) -> None:
    run = Started(tmp_path)
    started.append(run)
    run.process.kill()
    run.process.wait()
    # A SIGKILL ends the run process alone: the session and its file are both still there.
    assert run.running()
    assert credential_files(run.run_dir)
    run.end_session_from_outside()
    # The run directory holds no run record, so this resume is refused, as it always was; the
    # file is removed all the same, before anything else is looked at.
    assert _resume(tmp_path, run.run_dir) != 0
    assert credential_files(run.run_dir) == []


def test_a_resume_leaves_the_credential_of_a_session_still_running(
    tmp_path: Path, started: list[Started]
) -> None:
    run = Started(tmp_path)
    started.append(run)
    run.process.kill()
    run.process.wait()
    before = {p: os.stat(p).st_ino for p in credential_files(run.run_dir)}
    assert before
    assert _resume(tmp_path, run.run_dir) != 0
    assert run.running()
    assert {p: os.stat(p).st_ino for p in credential_files(run.run_dir)} == before
    # Once nothing runs as the session, the next resume removes it.
    run.end_session_from_outside()
    assert _resume(tmp_path, run.run_dir) != 0
    assert credential_files(run.run_dir) == []


def test_with_no_process_listing_a_resume_removes_nothing(
    tmp_path: Path, started: list[Started], monkeypatch: pytest.MonkeyPatch
) -> None:
    run = Started(tmp_path)
    started.append(run)
    run.process.kill()
    run.process.wait()
    run.end_session_from_outside()
    before = credential_files(run.run_dir)

    def unlisted() -> frozenset[str]:
        msg = "ps could not be run"
        raise ProcessTableError(msg)

    # Without a listing nothing is concluded to be gone: the leftovers' stop removes it after.
    monkeypatch.setattr(stop_signals, "running_session_ids", unlisted)
    assert stop_signals.remove_left_credentials(run.run_dir) == ()
    assert credential_files(run.run_dir) == before
    monkeypatch.undo()
    assert stop_signals.remove_left_credentials(run.run_dir) == (SESSION_ID,)
    assert credential_files(run.run_dir) == []


def test_a_running_session_s_id_is_listed_and_a_gone_one_s_is_not(
    tmp_path: Path, started: list[Started]
) -> None:
    run = Started(tmp_path)
    started.append(run)
    assert SESSION_ID in stop_signals.running_session_ids()
    run.close()
    assert SESSION_ID not in stop_signals.running_session_ids()


def test_the_guard_handles_each_stop_signal_and_puts_back_what_it_found() -> None:
    found = {s: signal.getsignal(s) for s in (signal.SIGTERM, signal.SIGINT, signal.SIGHUP)}
    with stop_signals.on_stop_signals():
        for signum, handler in found.items():
            if handler != signal.SIG_IGN:
                assert signal.getsignal(signum) not in (handler, signal.SIG_DFL), signum
    assert {s: signal.getsignal(s) for s in found} == found


def test_a_stop_signal_the_launcher_ignored_stays_ignored() -> None:
    before = signal.signal(signal.SIGHUP, signal.SIG_IGN)
    try:
        with stop_signals.on_stop_signals():
            assert signal.getsignal(signal.SIGHUP) == signal.SIG_IGN
            assert signal.getsignal(signal.SIGTERM) not in (signal.SIG_DFL, signal.SIG_IGN)
    finally:
        signal.signal(signal.SIGHUP, before)
