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

import contextlib
import errno
import fcntl
import inspect
import json
import os
import signal
import subprocess
import sys
import threading
import time
import uuid
from collections.abc import Iterator
from pathlib import Path
from typing import Any

import pytest

from physgate.cli import main
from physgate.orchestrator import cli as orchestrator_cli
from physgate.orchestrator import credentials, dispatch, processes, stop_signals
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
from physgate.orchestrator.exceptions import InvocationError
from physgate.orchestrator.processes import ProcessTableError, started_at
from physgate.reviewers import claude as reviewers

HERE = Path(__file__).resolve().parent
CHILD = HERE / "credential_stop_child.py"
NAMES = frozenset({LOGIN_FILE, KEY_FILE, KEY_HELPER})
#: The secrets the stand-in run process is never handed.
CREDENTIAL_VARIABLES = ("ANTHROPIC_API_KEY", "ANTHROPIC_AUTH_TOKEN", "CLAUDE_CODE_OAUTH_TOKEN")
DUMMY = "dummy-not-a-credential"
#: What the fake starts in its own group as it stops (``writer``): it says its pid, then writes the
#: login file again and again until it is killed. The fake ends once the writer has said its pid,
#: so the writer is running when the stop meets it, however loaded the machine; it waits at most
#: a thousand short sleeps for that, after which the row fails on the missing pid.
WRITER = """#!/bin/sh
echo $$ > "$WRITER_PID"
while :; do
  printf '%s' '{"dummy": "not-a-credential"}' > "$CLAUDE_CONFIG_DIR/.credentials.json"
  sleep 0.05
done
"""
FAKE_BINARY = """#!/bin/sh
"$PY" -c 'import os, sys, time
os.setpgid(0, 0)
open(sys.argv[1] + ".part", "w").write(str(os.getpid()))
os.rename(sys.argv[1] + ".part", sys.argv[1])
time.sleep(600)' "$TOOL_PID" &
while [ ! -s "$TOOL_PID" ]; do sleep 0.05; done
login() { printf '%s' '{"dummy": "not-a-credential"}' > "$CLAUDE_CONFIG_DIR/.credentials.json"; }
wait_for_writer() {
  i=0
  while [ ! -s "$WRITER_PID" ] && [ "$i" -lt 1000 ]; do sleep 0.01; i=$((i + 1)); done
}
case "$ON_TERM" in
  ignore) trap '' TERM ;;
  rewrite) trap 'login; exit 143' TERM ;;
  writer) trap '"$WRITER" & wait_for_writer; exit 143' TERM ;;
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
        # Its own id: a row in another worker runs a session at the same time, and the listing
        # tells sessions apart by their ids alone.
        self.session_id = str(uuid.uuid4())
        self.sdir = self.run_dir / "sessions" / self.session_id
        self.sdir.mkdir(parents=True)
        fake = tmp_path / "fake-claude"
        fake.write_text(FAKE_BINARY)
        fake.chmod(0o755)
        (tmp_path / "writer.sh").write_text(WRITER)
        (tmp_path / "writer.sh").chmod(0o755)
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
        # Its whole group, whether its leader still runs or not: what it started is in it.
        with contextlib.suppress(OSError):
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


def test_a_process_the_session_starts_as_it_stops_is_ended_with_its_group(
    tmp_path: Path, started: list[Started]
) -> None:
    run = Started(tmp_path, on_term="writer")
    started.append(run)
    run.process.send_signal(signal.SIGTERM)
    assert ended(run.process) == -signal.SIGTERM, run.said()
    # The writer started, and is gone: nothing is left to write the file after the stop.
    writer = run.sdir / "writer.pid"
    assert writer.exists(), "the session started no writer as it stopped"
    assert started_at(int(writer.read_text())) is None, "a process left in the group still runs"
    assert credential_files(run.run_dir) == [], "a process left in the session's group wrote it"


def test_a_run_killed_during_its_stop_s_grace_has_already_removed_the_files(
    tmp_path: Path, started: list[Started]
) -> None:
    run = Started(tmp_path, on_term="ignore")
    started.append(run)
    run.process.send_signal(signal.SIGTERM)
    # The files go first, well inside the grace the session that ignores SIGTERM is given.
    deadline = time.monotonic() + stop_signals.GRACE_S / 2
    while credential_files(run.run_dir) and time.monotonic() < deadline:
        time.sleep(0.01)
    assert credential_files(run.run_dir) == [], "the files waited for the grace"
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
    assert stop_signals.remove_left_credentials(run.run_dir) == (run.session_id,)
    assert credential_files(run.run_dir) == []


def test_a_running_session_s_id_is_listed_and_a_gone_one_s_is_not(
    tmp_path: Path, started: list[Started]
) -> None:
    run = Started(tmp_path)
    started.append(run)
    assert run.session_id in processes.running_session_ids()
    run.close()
    assert run.session_id not in processes.running_session_ids()


@pytest.mark.parametrize(
    ("code", "listed"),
    [(1, "{own} python\n"), (0, "1 /sbin/init --session-id x\n")],
    ids=["failed", "without-this-process"],
)
def test_a_failed_listing_or_one_without_this_process_is_no_listing(
    monkeypatch: pytest.MonkeyPatch, code: int, listed: str
) -> None:
    # This process's pid at run time: a test's id is the same in every worker that collects it.
    listed = listed.format(own=os.getpid())

    def ps(argv: list[str], **_: object) -> subprocess.CompletedProcess[str]:
        return subprocess.CompletedProcess(argv, code, stdout=listed, stderr="")

    monkeypatch.setattr(subprocess, "run", ps)
    try:
        processes.running_session_ids()
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
    write_login(config, DUMMY, place="role_session")
    write_key_helper(state, DUMMY, place="role_session")
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
    write_login(config_a, DUMMY, place="role_session")
    write_login(config_b, DUMMY, place="role_session")
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


def test_every_session_spawn_holds_its_login_file() -> None:
    assert "login_dir=" in inspect.getsource(dispatch.ClaudeDispatcher._run_session)
    assert "login_dir=" in inspect.getsource(reviewers.ClaudeReviewer._spawn)


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


def test_a_left_session_reached_only_through_a_link_leaves_the_others_removed(
    tmp_path: Path,
) -> None:
    run_dir = tmp_path / "run"
    _state_a, config_a = _session_dirs(run_dir / "sessions" / "a")
    _state_b, config_b = _session_dirs(run_dir / "sessions" / "b")
    (tmp_path / "elsewhere").mkdir()
    (tmp_path / "elsewhere" / LOGIN_FILE).write_text("{}")
    config_a.rmdir()
    config_a.symlink_to(tmp_path / "elsewhere")
    (config_b / LOGIN_FILE).write_text("{}")
    try:
        cleared = stop_signals.remove_left_credentials(run_dir)
    except Exception as exc:
        raise AssertionError(f"the resume's removal raised {exc!r}") from exc
    # The link is not followed; the leftovers' stop refuses it, as it always did.
    assert cleared == ("b",)
    assert (tmp_path / "elsewhere" / LOGIN_FILE).exists()
    assert not (config_b / LOGIN_FILE).exists()


class DyingWriter:
    """A process still dying after its SIGKILL, as the stop's probe sees it.

    It writes the session's login file again and again until the probe has asked after it
    ``polls`` times; the next ask finds it gone, and it writes nothing after that. A real one
    dies within microseconds of its SIGKILL, too soon for a row to land a write in between:
    the probe stands in for the kernel's answer, so the order the stop keeps is what is tried.
    """

    def __init__(self, config: Path, polls: int) -> None:
        self.login = config / LOGIN_FILE
        self.left = polls
        self.done = threading.Event()
        self.thread = threading.Thread(target=self._write, daemon=True)
        self.thread.start()

    def _write(self) -> None:
        while not self.done.is_set():
            with contextlib.suppress(OSError):
                self.login.write_text("{}")
            self.done.wait(0.005)

    def still_there(self) -> bool:
        if self.left > 0:
            self.left -= 1
            return True
        self.stop()
        return False

    def stop(self) -> None:
        self.done.set()
        self.thread.join()


@pytest.fixture
def one_session(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> Iterator[tuple[subprocess.Popen[bytes], Path]]:
    """One session this process spawned and tracks, with its login file held; nothing else."""
    monkeypatch.setattr(stop_signals, "_live", [])
    monkeypatch.setattr(credentials, "_held", {})
    _state, config = _session_dirs(tmp_path / "sessions" / str(uuid.uuid4()))
    session = subprocess.Popen(["sleep", "60"], start_new_session=True)  # noqa: S607 - fixed
    stop_signals.track(session, config)
    yield session, config
    with contextlib.suppress(OSError):
        os.killpg(session.pid, signal.SIGKILL)
    with contextlib.suppress(ChildProcessError):
        os.waitpid(session.pid, 0)
    session.returncode = -signal.SIGKILL


@pytest.mark.parametrize("dying", ["the session", "its group"])
def test_nothing_removed_after_the_stop_is_written_again_by_a_session_still_dying(
    one_session: tuple[subprocess.Popen[bytes], Path],
    monkeypatch: pytest.MonkeyPatch,
    dying: str,
) -> None:
    _session, config = one_session
    writer = DyingWriter(config, polls=3)
    try:
        if dying == "the session":
            reaped = stop_signals._reaped
            monkeypatch.setattr(
                stop_signals, "_reaped", lambda pid: not writer.still_there() and reaped(pid)
            )
        else:
            monkeypatch.setattr(stop_signals, "_group_left", lambda _pgid: writer.still_there())
        # What a stop signal does: remove, end the sessions, remove again.
        remove_held_secrets()
        assert stop_signals.end_live_sessions(grace_s=0).tried == 1
        # The dying process is gone before the stop's last removal: it writes nothing after.
        assert writer.done.is_set(), f"the stop did not wait for {dying} to go"
        remove_held_secrets()
        assert not (config / LOGIN_FILE).exists(), f"{dying}, still dying, wrote it again"
    finally:
        writer.stop()


@pytest.mark.parametrize("probe", ["_reaped", "_group_left"])
def test_a_session_that_never_goes_holds_the_stop_no_longer_than_its_bound(
    one_session: tuple[subprocess.Popen[bytes], Path],
    monkeypatch: pytest.MonkeyPatch,
    probe: str,
) -> None:
    holding = threading.Event()
    holding.set()
    if probe == "_reaped":
        reaped = stop_signals._reaped
        monkeypatch.setattr(
            stop_signals, "_reaped", lambda pid: not holding.is_set() and reaped(pid)
        )
    else:
        monkeypatch.setattr(stop_signals, "_group_left", lambda _pgid: holding.is_set())
    stop = threading.Thread(
        target=stop_signals.end_live_sessions, kwargs={"grace_s": 0}, daemon=True
    )
    stop.start()
    try:
        stop.join(timeout=stop_signals.REAP_S + 20)
        assert not stop.is_alive(), f"the stop still waits on {probe} past its bound"
    finally:
        # Released, and the session reaped by the fixture, a stop that never gave up ends too.
        holding.clear()
        stop.join(timeout=stop_signals.REAP_S + 20)


#: The exit status of a stop that left a session alive after its bound: not the signal's own.
SESSIONS_ALIVE_EXIT = 76


def stop_line(run: Started) -> dict[str, object]:
    """The stand-in's one line saying how its stop went, or nothing if it wrote none."""
    for line in run.said().splitlines():
        if line.startswith("{") and '"stopped_by"' in line:
            found: dict[str, object] = json.loads(line)
            return found
    return {}


def test_a_clean_stop_says_every_session_is_gone_and_its_files_removed(
    tmp_path: Path, started: list[Started]
) -> None:
    run = Started(tmp_path)
    started.append(run)
    run.process.send_signal(signal.SIGTERM)
    assert ended(run.process) == -signal.SIGTERM, run.said()
    said = stop_line(run)
    assert said.get("stopped_by") == "SIGTERM", run.said()
    assert (said.get("sessions_gone"), said.get("sessions_alive")) == (1, 0), said
    assert said.get("credentials") == "removed", said


def test_a_session_alive_after_the_bound_is_named_and_the_stop_ends_otherwise(
    tmp_path: Path, started: list[Started]
) -> None:
    run = Started(tmp_path, on_term="survivor")
    started.append(run)
    run.process.send_signal(signal.SIGTERM)
    code = ended(run.process)
    assert code == SESSIONS_ALIVE_EXIT, (code, run.said())
    said = stop_line(run)
    assert (said.get("sessions_gone"), said.get("sessions_alive")) == (0, 1), said
    assert said.get("survivors") == [run.pid], said
    # Nothing says the files are gone while a session that may write them again lives.
    assert said.get("credentials") != "removed", said
    assert "next command on this run" in str(said.get("credentials")), said


class LockHolder:
    """Another process driving the run: it holds the run directory's lock, shared, as a run does."""

    def __init__(self, run_dir: Path) -> None:
        code = (
            "import fcntl, os, sys, time\n"
            "fd = os.open(sys.argv[1], os.O_RDONLY)\n"
            "fcntl.flock(fd, fcntl.LOCK_SH)\n"
            "print('held', flush=True)\n"
            "time.sleep(600)\n"
        )
        self.process = subprocess.Popen(
            [sys.executable, "-c", code, str(run_dir)], stdout=subprocess.PIPE, text=True
        )
        stdout = self.process.stdout
        assert stdout is not None
        # Read on a thread and joined with a timeout: a child that never says it holds the lock
        # fails the row on an assertion and does not hang the run.
        said: list[str] = []
        reader = threading.Thread(
            target=lambda: said.append(stdout.readline().strip()), daemon=True
        )
        reader.start()
        reader.join(timeout=30)
        if said != ["held"]:
            self.close()
            raise AssertionError(f"the lock holder never said it held the lock: {said!r}")

    def close(self) -> None:
        self.process.kill()
        self.process.wait()
        if self.process.stdout is not None:
            self.process.stdout.close()


def test_a_second_command_on_a_driven_run_leaves_a_login_written_before_its_spawn(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(credentials, "_held", {})
    run_dir = tmp_path / "run"
    session_id = str(uuid.uuid4())
    _state, config = _session_dirs(run_dir / "sessions" / session_id)
    # The window: the driving run has written the session's login file, and no process names
    # the session's id yet, since it is not spawned.
    write_login(config, DUMMY, place="role_session")
    holder = LockHolder(run_dir)
    try:
        assert _command(tmp_path, run_dir) != 0
        assert stop_signals.remove_left_credentials(run_dir) == ()
        assert credential_files(run_dir) == [str(config / LOGIN_FILE)]
    finally:
        holder.close()
    # Nothing drives the run now: the next command removes it.
    assert _command(tmp_path, run_dir) != 0
    assert credential_files(run_dir) == []


def test_a_run_holds_its_run_directory_s_lock_while_it_drives(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    run_dir = tmp_path / "run"
    run_dir.mkdir()
    blocked: list[bool] = []

    def drive(*_args: object, **_kwargs: object) -> int:
        fd = os.open(run_dir, os.O_RDONLY)
        try:
            fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            blocked.append(True)
        else:
            blocked.append(False)
        finally:
            os.close(fd)
        return 0

    monkeypatch.setattr(orchestrator_cli, "_drive_run", drive)
    assert _command(tmp_path, run_dir) == 0
    assert blocked == [True], "nothing told a second command this run is driven"


#: A sha256 in hex, as the binary names a messaging key by its socket's path.
DIGEST = "ab" * 32


@pytest.mark.parametrize("route", ["the session's end", "a stop signal", "the next command"])
def test_the_binary_s_messaging_keys_go_with_the_login_file(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, route: str
) -> None:
    monkeypatch.setattr(credentials, "_held", {})
    run_dir = tmp_path / "run"
    session_id = str(uuid.uuid4())
    state, config = _session_dirs(run_dir / "sessions" / session_id)
    write_login(config, DUMMY, place="role_session")
    keys = config / "sessions"
    keys.mkdir()
    for name in (f"4242.{DIGEST}.key", f"4242.{DIGEST}.key.tmp.9f3c", f"77.{DIGEST}.key"):
        (keys / name).write_text("{}")
    # Kept: the binary's session record holds no secret, and nothing else is the binary's key.
    (keys / "4242.json").write_text("{}")
    (keys / "notes.key").write_text("")
    (keys / f"5.{DIGEST}.key.d").mkdir()
    (keys / f"9.{DIGEST}.key").mkdir()
    outside = tmp_path / "outside.key"
    outside.write_text("{}")
    (keys / f"8.{DIGEST}.key").symlink_to(outside)
    if route == "the session's end":
        remove_secrets(state, config)
    elif route == "a stop signal":
        remove_held_secrets()
    else:
        assert stop_signals.remove_left_credentials(run_dir) == (session_id,)
    assert sorted(p.name for p in keys.iterdir()) == sorted(
        ["4242.json", "notes.key", f"5.{DIGEST}.key.d", f"9.{DIGEST}.key"]
    ), route
    assert outside.exists(), "a link at a key's name was followed"
    assert not (config / LOGIN_FILE).exists()


def test_a_link_at_the_keys_directory_is_not_followed(tmp_path: Path) -> None:
    state, config = _session_dirs(tmp_path / "sessions" / "a")
    elsewhere = tmp_path / "elsewhere"
    elsewhere.mkdir()
    (elsewhere / f"1.{DIGEST}.key").write_text("{}")
    (config / "sessions").symlink_to(elsewhere)
    with contextlib.suppress(InvocationError):
        remove_secrets(state, config)
    assert (elsewhere / f"1.{DIGEST}.key").exists()


def test_a_resume_removes_this_run_s_reviewer_credentials_and_no_other_s(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(credentials, "_held", {})
    run_dir = tmp_path / "run"
    run_dir.mkdir()
    (run_dir / "run.json").write_text(json.dumps({"run_id": "run-a"}))
    reviews = tmp_path / "rs"

    def review(run_id: str) -> tuple[str, Path]:
        review_id = str(uuid.uuid4())
        sdir = reviews / review_id / "session"
        _session_dirs(sdir)
        (sdir / dispatch.OWNER_NAME).write_text(json.dumps({"run_id": run_id}))
        write_login(sdir / "config", DUMMY, place="review_session")
        return review_id, sdir / "config" / LOGIN_FILE

    _gone, gone_login = review("run-a")
    _other, other_login = review("run-b")
    living, living_login = review("run-a")
    # A reviewer in its repair resume names its id after --resume.
    alive = subprocess.Popen(
        [sys.executable, "-c", "import time; time.sleep(600)", "--resume", living]
    )
    try:
        assert _command(tmp_path, run_dir) != 0
        assert not gone_login.exists(), "this run's reviewer's login was left"
        assert other_login.exists(), "another run's reviewer's login was removed"
        assert living_login.exists(), "a reviewer still running lost its login"
    finally:
        alive.kill()
        alive.wait()


def _refuse_locks(monkeypatch: pytest.MonkeyPatch) -> None:
    def refuse(*_args: object, **_kwargs: object) -> None:
        raise OSError(errno.ENOLCK, "no locks available")

    monkeypatch.setattr(fcntl, "flock", refuse)


def test_a_filesystem_that_refuses_the_lock_does_not_stop_a_run_and_is_said_once(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capfd: pytest.CaptureFixture[str]
) -> None:
    run_dir = tmp_path / "run"
    run_dir.mkdir()
    monkeypatch.setattr(stop_signals, "_said_unlocked", False, raising=False)
    _refuse_locks(monkeypatch)
    refused: list[OSError] = []
    ran = 0
    for _ in range(2):
        try:
            with stop_signals.driving(run_dir):
                ran += 1
        except OSError as exc:
            refused.append(exc)
    assert refused == [], "a lock the filesystem refuses stopped the run"
    assert ran == 2
    said = [line for line in capfd.readouterr().err.splitlines() if "lock" in line]
    assert len(said) == 1, said


def test_the_sweep_removes_nothing_when_the_lock_is_refused(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(credentials, "_held", {})
    run_dir = tmp_path / "run"
    _state, config = _session_dirs(run_dir / "sessions" / str(uuid.uuid4()))
    write_login(config, DUMMY, place="role_session")
    _refuse_locks(monkeypatch)
    assert stop_signals.remove_left_credentials(run_dir) == ()
    assert credential_files(run_dir) == [str(config / LOGIN_FILE)]


def test_a_key_file_named_with_other_digits_is_left_alone(tmp_path: Path) -> None:
    state, config = _session_dirs(tmp_path / "sessions" / "a")
    keys = config / "sessions"
    keys.mkdir()
    # Arabic-indic digits: a digit to the str pattern's \d, and not one the binary writes.
    odd = f"\u0661\u0662.{DIGEST}.key"
    (keys / odd).write_text("{}")
    (keys / f"12.{DIGEST}.key").write_text("{}")
    remove_secrets(state, config)
    assert sorted(p.name for p in keys.iterdir()) == [odd]


def test_one_key_file_that_will_not_go_does_not_stop_the_others(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _state, config = _session_dirs(tmp_path / "sessions" / "a")
    keys = config / "sessions"
    keys.mkdir()
    for pid in (1, 2, 3):
        (keys / f"{pid}.{DIGEST}.key").write_text("{}")
    real = os.unlink
    refused: list[str] = []

    def unlink(name: str, **kwargs: Any) -> None:
        if not refused:
            refused.append(name)
            raise PermissionError(errno.EPERM, "not permitted")
        real(name, **kwargs)

    monkeypatch.setattr(os, "unlink", unlink)
    with contextlib.suppress(Exception):
        credentials.remove_messaging_keys(config)
    assert [p.name for p in keys.iterdir()] == refused


@pytest.mark.skipif(os.geteuid() == 0, reason="root removes from a directory it may not write")
def test_a_stop_says_which_files_it_could_not_remove_and_prints_none_of_them(
    tmp_path: Path, started: list[Started]
) -> None:
    run = Started(tmp_path)
    started.append(run)
    keys = run.sdir / "config" / "sessions"
    keys.mkdir()
    (keys / f"7.{DIGEST}.key").write_text("TOKEN-CONTENT-MARK")
    keys.chmod(0o500)
    try:
        run.process.send_signal(signal.SIGTERM)
        assert ended(run.process) == -signal.SIGTERM, run.said()
        said = stop_line(run)
    finally:
        keys.chmod(0o700)
    assert said.get("credentials") != "removed", said
    assert said.get("removal_failures") == 1, said
    assert "TOKEN-CONTENT-MARK" not in run.said()
    assert not (run.sdir / "config" / LOGIN_FILE).exists(), "the login stayed for one key"
