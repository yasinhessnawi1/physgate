"""A run ended mid-session leaves no session's credential file in its run directory.

A session's credential is a file in the session's own directory, inside the run directory, for
as long as the session runs; the session's end removes it. A run process ended by SIGTERM (or an
interrupt, or a hang-up) while a session ran used to end at once: the session, leading a group of
its own, ran on, and its credential file stayed in the run directory, which is evidence that gets
copied. Now a stop signal ends the run's sessions and removes their files before the process
ends by that signal; a run killed outright leaves them, and the next resume removes the file of
every session nothing runs as any more, before anything else, and leaves a running one's alone.

The run process here is a stand-in that spawns one fake session the way the run spawns one; the
fake starts a tool in a group of its own, writes its own login file and runs until it is
stopped. Every credential is a dummy, and no file's content is read: only its name.
"""

from __future__ import annotations

import inspect
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
from physgate.orchestrator import cli as orchestrator_cli
from physgate.orchestrator import dispatch, stop_signals
from physgate.orchestrator.cli import Registrations
from physgate.orchestrator.credentials import (
    KEY_FILE,
    KEY_HELPER,
    LOGIN_FILE,
    remove_held_secrets,
    remove_secrets,
    write_key_helper,
    write_login,
)
from physgate.orchestrator.processes import ProcessTableError, started_at
from physgate.reviewers import claude as reviewers

HERE = Path(__file__).resolve().parent
CHILD = HERE / "credential_stop_child.py"
SESSION_ID = "0b6f3c1e-5d7a-4f63-9a51-credentialrow"
NAMES = frozenset({LOGIN_FILE, KEY_FILE, KEY_HELPER})
#: The secrets the stand-in run process is never handed.
CREDENTIAL_VARIABLES = ("ANTHROPIC_API_KEY", "ANTHROPIC_AUTH_TOKEN", "CLAUDE_CODE_OAUTH_TOKEN")
DUMMY = "dummy-not-a-credential"
FAKE_BINARY = """#!/bin/sh
"$PY" -c 'import os, sys, time
os.setpgid(0, 0)
open(sys.argv[1] + ".part", "w").write(str(os.getpid()))
os.rename(sys.argv[1] + ".part", sys.argv[1])
time.sleep(600)' "$TOOL_PID" &
while [ ! -s "$TOOL_PID" ]; do sleep 0.05; done
login() { printf '%s' '{"dummy": "not-a-credential"}' > "$CLAUDE_CONFIG_DIR/.credentials.json"; }
case "$ON_TERM" in
  ignore) trap '' TERM ;;
  rewrite) trap 'login; exit 143' TERM ;;
esac
login
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


def ended(process: subprocess.Popen[bytes], timeout: float = 60) -> int:
    """The stand-in's exit code; one still running after ``timeout`` fails the row."""
    try:
        return process.wait(timeout=timeout)
    except subprocess.TimeoutExpired:
        raise AssertionError("the run process did not end on its stop signal") from None


class Started:
    """One stand-in run process, its session's directory, and the session once it is ready."""

    def __init__(self, tmp_path: Path, *, seeded: bool = True, on_term: str = "default") -> None:
        self.tmp_path = tmp_path
        self.run_dir = tmp_path / "run"
        self.sdir = self.run_dir / "sessions" / SESSION_ID
        self.sdir.mkdir(parents=True)
        fake = tmp_path / "fake-claude"
        fake.write_text(FAKE_BINARY)
        fake.chmod(0o755)
        env = {k: v for k, v in os.environ.items() if k not in CREDENTIAL_VARIABLES}
        self.log = (tmp_path / "child.out").open("wb")
        self.process = subprocess.Popen(
            [sys.executable, str(CHILD), str(self.sdir), str(fake), str(int(seeded)), on_term],
            env=env,
            stdout=self.log,
            stderr=self.log,
        )
        deadline = time.monotonic() + 60
        record = self.sdir / "process.json"
        while not ((self.sdir / "ready").exists() and record.exists()):
            assert self.process.poll() is None, self.said()
            assert time.monotonic() < deadline, "the session never became ready"
            time.sleep(0.05)
        held = json.loads(record.read_text())
        self.pid, self.started = int(held["pid"]), str(held["started"])
        self.tool = int((self.sdir / "tool.pid").read_text())
        self.tool_started = started_at(self.tool)
        assert self.tool_started is not None, "the session's tool was not running"

    def said(self) -> str:
        return (self.tmp_path / "child.out").read_text(errors="replace")

    def running(self) -> bool:
        return started_at(self.pid) == self.started

    def tool_running(self) -> bool:
        return started_at(self.tool) == self.tool_started

    def end_session_from_outside(self) -> None:
        if self.running():
            os.killpg(self.pid, signal.SIGKILL)
        if self.tool_running():
            os.killpg(self.tool, signal.SIGKILL)
        deadline = time.monotonic() + 30
        while self.running() or self.tool_running():
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


def _command(tmp_path: Path, run_dir: Path, command: str = "resume") -> int:
    """``physgate resume`` (or ``run``) on ``run_dir``, as an operator types it."""
    argv = [command, "--run-dir", str(run_dir), "--target", str(tmp_path / "target")]
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
    began = time.monotonic()
    run.process.send_signal(signum)
    code = ended(run.process)
    # Ended by the signal, as before: nothing of the run's own records is written on the way.
    assert code == -signum, run.said()
    # A session that ends on SIGTERM is not waited on for the whole grace.
    assert time.monotonic() - began < stop_signals.GRACE_S, "the stop waited out its grace"
    assert credential_files(run.run_dir) == []
    assert not run.running(), "the session outlived its run's stop signal"
    assert not run.tool_running(), "the session's tool outlived its run's stop signal"


def test_a_session_that_ignores_sigterm_is_killed_within_the_bound(
    tmp_path: Path, started: list[Started]
) -> None:
    run = Started(tmp_path, on_term="ignore")
    started.append(run)
    began = time.monotonic()
    run.process.send_signal(signal.SIGTERM)
    code = ended(run.process)
    assert code == -signal.SIGTERM, run.said()
    assert time.monotonic() - began < stop_signals.GRACE_S + 20
    assert credential_files(run.run_dir) == []
    assert not run.running(), "a session that ignored SIGTERM outlived the bound"
    assert not run.tool_running()


def test_a_session_that_writes_its_login_again_as_it_stops_leaves_none(
    tmp_path: Path, started: list[Started]
) -> None:
    run = Started(tmp_path, on_term="rewrite")
    started.append(run)
    run.process.send_signal(signal.SIGTERM)
    assert ended(run.process) == -signal.SIGTERM, run.said()
    assert credential_files(run.run_dir) == []
    assert not run.running()


def test_a_run_killed_during_its_stop_s_grace_has_already_removed_the_files(
    tmp_path: Path, started: list[Started]
) -> None:
    run = Started(tmp_path, on_term="ignore")
    started.append(run)
    run.process.send_signal(signal.SIGTERM)
    time.sleep(1.0)
    assert run.process.poll() is None, "the stop did not wait for the session"
    run.process.kill()
    run.process.wait()
    # The files go first: a supervisor's SIGKILL after its SIGTERM finds them gone already.
    assert credential_files(run.run_dir) == []


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
    assert _command(tmp_path, run.run_dir) != 0
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
    assert _command(tmp_path, run.run_dir) != 0
    assert run.running()
    assert {p: os.stat(p).st_ino for p in credential_files(run.run_dir)} == before
    # Once nothing runs as the session, the next command on the run removes it.
    run.end_session_from_outside()
    assert _command(tmp_path, run.run_dir, "run") != 0
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


@pytest.mark.parametrize(
    ("code", "listed"), [(1, f"{os.getpid()} python\n"), (0, "1 /sbin/init --session-id x\n")]
)
def test_a_failed_listing_or_one_without_this_process_is_no_listing(
    monkeypatch: pytest.MonkeyPatch, code: int, listed: str
) -> None:
    def ps(argv: list[str], **_: object) -> subprocess.CompletedProcess[str]:
        return subprocess.CompletedProcess(argv, code, stdout=listed, stderr="")

    monkeypatch.setattr(stop_signals.subprocess, "run", ps)
    try:
        stop_signals.running_session_ids()
    except ProcessTableError:
        refused = True
    else:
        refused = False
    assert refused, "a listing that is no listing was taken for one"


def _session_dirs(top: Path) -> tuple[Path, Path]:
    state, config = top / "state", top / "config"
    state.mkdir(parents=True)
    config.mkdir(parents=True)
    return state, config


def test_a_written_credential_is_removed_by_a_stop_until_its_session_s_end_removed_it(
    tmp_path: Path,
) -> None:
    state, config = _session_dirs(tmp_path / "sessions" / "a")
    write_login(config, DUMMY)
    write_key_helper(state, DUMMY)
    (config / "debug.txt").write_text("a debug log may hold it\n")
    remove_held_secrets()
    assert credential_files(tmp_path) == []
    assert not (config / "debug.txt").exists(), "a debug log outlived the stop"
    remove_secrets(state, config)
    # Ended: a file of that name there now is not the session's, and a stop leaves it.
    (config / LOGIN_FILE).write_text("{}")
    remove_held_secrets()
    assert credential_files(tmp_path) == [str(config / LOGIN_FILE)]


def test_one_session_s_unreachable_directory_leaves_the_other_s_files_removed(
    tmp_path: Path,
) -> None:
    state_a, config_a = _session_dirs(tmp_path / "sessions" / "a")
    state_b, config_b = _session_dirs(tmp_path / "sessions" / "b")
    write_login(config_a, DUMMY)
    write_login(config_b, DUMMY)
    # The first session's configuration directory is now a link: it is never followed.
    config_a.rename(tmp_path / "moved")
    config_a.symlink_to(tmp_path / "moved")
    try:
        remove_held_secrets()
    except Exception as exc:
        raise AssertionError(f"a stop's removal raised {exc!r}") from exc
    assert not (config_b / LOGIN_FILE).exists()
    assert (tmp_path / "moved" / LOGIN_FILE).exists(), "a link was followed out of its session"
    config_a.unlink()
    remove_secrets(state_a, config_a)
    remove_secrets(state_b, config_b)


@pytest.mark.parametrize("command", ["run", "resume", "decompose"])
def test_each_command_that_spawns_a_session_runs_under_the_guard(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, command: str
) -> None:
    seen: list[object] = []

    def under(*_args: object, **_kwargs: object) -> int:
        seen.append(signal.getsignal(signal.SIGTERM))
        return 0

    name = "_decompose_run" if command == "decompose" else "_drive_run"
    monkeypatch.setattr(orchestrator_cli, name, under)
    if command == "decompose":
        argv = ["decompose", str(tmp_path / "brief.md"), "--seed", "1", "--run-id", "r"]
        argv += ["--params", str(tmp_path / "p.json"), "--target", str(tmp_path / "t")]
        assert main([*argv, "--run-dir", str(tmp_path / "run")], Registrations()) == 0
    else:
        assert _command(tmp_path, tmp_path / "run", command) == 0
    assert seen == [stop_signals._on_stop]


def test_every_session_spawn_holds_its_credential_s_directories() -> None:
    assert "credential_dirs=" in inspect.getsource(dispatch.ClaudeDispatcher._run_session)
    assert "credential_dirs=" in inspect.getsource(reviewers.ClaudeReviewer._spawn)


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
