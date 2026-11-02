"""A session's hooks never put back the run's own records beneath the orchestrator that holds them.

The run's event log and task ledger are held open by the orchestrator for the whole run, and it
appends to them. A role session's sentinel once guarded them by putting them back from the record
it took when the session started, by replacing the file. A replaced file is a new inode: the
orchestrator kept appending to the old one, which no path names any more, and every line it wrote
from then on was lost when it exited. That happened on a real run: a resume appended its first
lines, then stopped the session its killed predecessor had left, and that session's SessionEnd
hook put the event log back.

Here every session is a stand-in binary that runs the generated hook commands, so the sentinel is
the real one, installed by the dispatcher's own installer, with the run's records protected as a
real run protects them. The stand-in ends through its SessionEnd hook when it is sent SIGTERM, as
the runtime does. Each test holds the record's path to the file the orchestrator's handle writes,
and holds a change no orchestrator made to a refusal or an incident.
"""

from __future__ import annotations

import json
import os
import shutil
import signal
import stat
import sys
import time
from collections.abc import Callable, Iterator
from pathlib import Path
from typing import Any

import pytest
from left_session import spawn_logged
from loop_fakes import Rig
from orch_helpers import make_config

from physgate.knowledge import loader
from physgate.orchestrator import dispatch
from physgate.orchestrator.credentials import Credential
from physgate.orchestrator.dispatch import ClaudeDispatcher, sentinel_refusal
from physgate.orchestrator.events import EventLog, Incident, InstallChecked, TokensUsed, read_events
from physgate.orchestrator.git import head_of
from physgate.orchestrator.install import InstallFacts
from physgate.orchestrator.loop import Loop
from physgate.orchestrator.merge import RunGit
from physgate.orchestrator.ports import SessionRequest
from physgate.orchestrator.processes import started_at
from physgate.orchestrator.run_config import RunBounds
from physgate.state.store import Store
from physgate.state.task_ledger import TaskLedger, TaskLine

MODEL = "claude-sonnet-5"
GITENV = {
    "PATH": "/usr/bin:/bin:/usr/local/bin:/opt/homebrew/bin",
    "HOME": "/nonexistent",
    "GIT_CONFIG_NOSYSTEM": "1",
    "GIT_CONFIG_GLOBAL": "/dev/null",
    "GIT_AUTHOR_NAME": "t",
    "GIT_AUTHOR_EMAIL": "t@example.invalid",
    "GIT_COMMITTER_NAME": "t",
    "GIT_COMMITTER_EMAIL": "t@example.invalid",
}

#: The stand-in session. ``FLAGS``, ``MODE`` and ``MODEL_NAME`` are prepended.
#: ``leftover``: runs until it is stopped, and ends through its SessionEnd hook on SIGTERM.
#: ``gone``: exits once its record is taken, with no SessionEnd, as one killed with its run.
#: ``writes-log``: appends a line to the run's event log, makes a tool call, and ends.
#: ``copies-log``: puts a copy of the run's event log in its place, makes a tool call, and ends.
#: Any other: writes its module file and ends.
SESSION = r"""
import json, os, shlex, signal, subprocess, sys, time

argv = sys.argv[1:]
if argv == ["--version"]:
    print("2.1.272 (Claude Code)")
    sys.exit(0)
settings_path = argv[argv.index("--settings") + 1]
settings = json.load(open(settings_path))
session_id = argv[argv.index("--session-id") + 1]
sdir = os.path.dirname(os.path.dirname(settings_path))
run_dir = os.path.dirname(os.path.dirname(sdir))


def hook(event, **extra):
    command = settings["hooks"][event][0]["hooks"][0]["command"]
    body = {"session_id": session_id, "cwd": os.getcwd(), "hook_event_name": event, **extra}
    subprocess.run(
        shlex.split(command), input=json.dumps(body).encode(), capture_output=True, check=False
    )


def flag(name):
    open(os.path.join(FLAGS, name), "w").close()


def stopped(*_args):
    hook("SessionEnd", reason="other")
    flag("session-end-ran")
    os._exit(0)


hook("SessionStart", source="startup")
if MODE == "leftover":
    signal.signal(signal.SIGTERM, stopped)
    flag("started")
    while True:
        time.sleep(0.05)
if MODE == "gone":
    flag("started")
    os._exit(0)
if MODE == "writes-log":
    with open(os.path.join(run_dir, "events.jsonl"), "ab") as out:
        out.write(b'{"seq": 999}\n')
    hook("PreToolUse", tool_name="Bash", tool_input={"command": "true"})
if MODE == "copies-log":
    # The same bytes on a new inode, in the log's place.
    log = os.path.join(run_dir, "events.jsonl")
    with open(log, "rb") as source, open(log + ".copy", "wb") as out:
        out.write(source.read())
    os.replace(log + ".copy", log)
    hook("PreToolUse", tool_name="Bash", tool_input={"command": "true"})
os.makedirs("modules/power", exist_ok=True)
with open("modules/power/a.py", "w") as out:
    out.write("x = 2\n")
hook("SessionEnd", reason="other")
usage = {"input_tokens": 3, "output_tokens": 5}
lines = [
    {"type": "assistant", "message": {"id": "m1", "model": MODEL_NAME, "usage": usage}},
    {
        "type": "result",
        "is_error": False,
        "terminal_reason": "completed",
        "modelUsage": {MODEL_NAME: {"inputTokens": 3, "outputTokens": 5}},
    },
]
sys.stdout.write("".join(json.dumps(line) + "\n" for line in lines))
sys.stdout.flush()
sys.exit(0)
"""

FACTS = InstallFacts(
    path="/i",
    interpreter="/i/bin/python",
    owner_is_session_user=True,
    files_with_write_bits=0,
    files_with_second_links=0,
    stdlib="/lib",
    stdlib_writable=True,
    state_filesystem="apfs",
    state_on_local_disk=True,
)
INSTALL_BIN = Path(sys.executable).parent / "physgate"


class Died(BaseException):
    """The orchestrator's death while its session runs."""


def _git(cwd: Path, *args: str) -> None:
    import subprocess

    subprocess.run(["git", *args], cwd=cwd, env=GITENV, capture_output=True, check=True)


@pytest.fixture
def leftovers() -> Iterator[list[int]]:
    """Pids a test's sessions ran as; any still running when it ends is killed."""
    pids: list[int] = []
    yield pids
    for pid in pids:
        if started_at(pid) is not None:
            os.kill(pid, signal.SIGKILL)


def _settle(check: Callable[[], bool], seconds: float) -> bool:
    deadline = time.monotonic() + seconds
    while time.monotonic() < deadline:
        if check():
            return True
        time.sleep(0.05)
    return check()


class Run:
    """A run directory with a target repository, a store, a started log, and a stand-in binary."""

    def __init__(self, tmp_path: Path, mode: str) -> None:
        self.flags = tmp_path / "flags"
        self.flags.mkdir()
        repo = tmp_path / "target"
        (repo / "modules" / "power").mkdir(parents=True)
        (repo / "modules" / "power" / "base.py").write_text("x = 1\n")
        _git(repo, "init", "-q", "-b", "master")
        _git(repo, "add", "-A")
        _git(repo, "commit", "-q", "-m", "initial")
        self.run = RunGit(repo=repo, run_dir=tmp_path / "run", run_id="run-1")
        self.run.open_run_branch(head_of(repo, "master"))
        self.store_root = self.run.run_dir / "store"
        Store(self.store_root).close()
        # The log is started as the loop's own writer starts it, with its configuration.
        spawn_logged(self.run.run_dir, [])
        binary = tmp_path / "bin" / "claude"
        binary.parent.mkdir()
        prelude = f"FLAGS = {str(self.flags)!r}\nMODE = {mode!r}\nMODEL_NAME = {MODEL!r}\n"
        binary.write_text(f"#!{sys.executable}\n{prelude}{SESSION}")
        binary.chmod(binary.stat().st_mode | stat.S_IXUSR)
        self.binary = binary

    @property
    def log_path(self) -> Path:
        return self.run.run_dir / "events.jsonl"

    def dispatcher(self, monkeypatch: pytest.MonkeyPatch) -> ClaudeDispatcher:
        """The dispatcher, installing each session through its own installer.

        Only what a stand-in run cannot have is left out: the role's reading list and the
        interface contracts (no specification commit), and the harness checkout's protection
        (the tests run from it).
        """
        bounds = RunBounds(
            binary_max_retries=0,
            session_wall_clock_s=60.0,
            session_max_turns=20,
            infra_retry_delays_s=(),
        )
        config = make_config(bounds=bounds, os_layer_absent="allow")
        monkeypatch.setattr(ClaudeDispatcher, "environment", lambda _self: FACTS)
        monkeypatch.setattr(ClaudeDispatcher, "_contracts", lambda _self, _request: ())
        monkeypatch.setattr(dispatch, "binary_version", lambda _binary: config.claude_version)
        monkeypatch.setattr(dispatch, "harness_protection", lambda: [])
        monkeypatch.setattr(loader, "required_reading", lambda *_a, **_k: ())
        monkeypatch.setattr(loader, "always_loaded", lambda *_a, **_k: ())
        return ClaudeDispatcher(
            config=config,
            run=self.run,
            store_root=self.store_root,
            install_bin=INSTALL_BIN,
            binary=str(self.binary),
            base_url=None,
            credential=Credential(mode="api_key", secret="not-a-key"),
            review_root=Path("/nonexistent/review-scratch"),
        )

    def request(self) -> SessionRequest:
        return SessionRequest(
            subtask_id="s1",
            attempt=1,
            assigned_role="electrical",
            spec_path=".physgate/specs/s1.md",
            module_dir="modules/power",
            model=MODEL,
            repair_instruction=None,
            bounds=self.dispatcher_bounds(),
        )

    @staticmethod
    def dispatcher_bounds() -> RunBounds:
        return RunBounds(
            binary_max_retries=0,
            session_wall_clock_s=60.0,
            session_max_turns=20,
            infra_retry_delays_s=(),
        )

    def spawned(self, session_id: str, pid: int, started: str) -> None:
        spawn_logged(self.run.run_dir, [(session_id, pid, started)])

    def session_dir(self) -> Path:
        (sdir,) = (self.run.run_dir / "sessions").iterdir()
        return sdir

    def hook_decisions(self) -> list[tuple[str, list[str]]]:
        log = self.session_dir() / "state" / "hooks.log.jsonl"
        lines = [json.loads(x) for x in log.read_text().splitlines()] if log.exists() else []
        return [(str(r.get("decision")), list(r.get("paths") or [])) for r in lines]


def _orchestrator_dies(run: Run, dispatcher: ClaudeDispatcher, mp: pytest.MonkeyPatch) -> None:
    """The orchestrator dies while its session runs: after the spawn, before any end."""

    def die(*_args: Any, **_kwargs: Any) -> None:  # noqa: ANN401
        raise Died

    with mp.context() as killed:
        killed.setattr(dispatch, "await_session", die)
        with pytest.raises(Died):
            dispatcher.run(run.request(), run.spawned)
    assert _settle((run.flags / "started").exists, 20.0), "the stand-in never took its record"


def _resume(run: Run, monkeypatch: pytest.MonkeyPatch) -> Loop:
    """A fresh process's loop over the run, with its first line written, as the command's is."""
    loop = Rig(run.run.run_dir, dispatcher=run.dispatcher(monkeypatch)).open()  # type: ignore[arg-type]
    loop.record.emit(
        InstallChecked(
            **loop.record.envelope(),
            path=str(INSTALL_BIN),
            action="checked",
            seconds=0.1,
            entries=1,
        )
    )
    return loop


def _handle_inode(handle: Any) -> int:  # noqa: ANN401
    return os.fstat(handle.fileno()).st_ino


def _holds(path: Path, handle: Any) -> bool:  # noqa: ANN401
    """Whether ``path`` names the very file ``handle`` writes."""
    return path.stat().st_ino == _handle_inode(handle)


def _incidents(path: Path) -> list[str]:
    return [e.cause for e in read_events(path) if isinstance(e, Incident)]


def test_a_leftover_s_session_end_after_the_resume_s_first_lines_leaves_the_log_the_resume_s(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, leftovers: list[int]
) -> None:
    """The case a real run met: the resume appends, then stops the leftover, whose end hook ran."""
    run = Run(tmp_path, "leftover")
    _orchestrator_dies(run, run.dispatcher(monkeypatch), monkeypatch)
    record = json.loads((run.session_dir() / "process.json").read_text())
    leftovers.append(int(record["pid"]))
    loop = _resume(run, monkeypatch)
    try:
        loop._stop_leftovers()
        assert (run.flags / "session-end-ran").exists(), "the leftover never ran its end hook"
        assert _holds(run.log_path, loop.log._handle), "the log was replaced beneath the resume"
        written = len(loop.log.events)
        assert len(read_events(run.log_path)) == written, "the resume's lines are not at the path"
        assert _incidents(run.log_path) == [], "no session changed the log: no incident"
        assert loop.state.halted is None
        assert not any(
            d == "put back" and str(run.log_path) in paths for d, paths in run.hook_decisions()
        ), "a hook put the run's own event log back"
    finally:
        loop.close()


def test_the_resume_s_own_check_after_a_gone_session_leaves_the_log_the_resume_s(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, leftovers: list[int]
) -> None:
    """The session exited with its run and ran no end hook: only the resume's check runs."""
    run = Run(tmp_path, "gone")
    _orchestrator_dies(run, run.dispatcher(monkeypatch), monkeypatch)
    leftovers.append(int(json.loads((run.session_dir() / "process.json").read_text())["pid"]))
    assert _settle(lambda: started_at(leftovers[-1]) is None, 20.0)
    loop = _resume(run, monkeypatch)
    try:
        loop._stop_leftovers()
        assert _holds(run.log_path, loop.log._handle), "the resume's own check replaced the log"
        assert len(read_events(run.log_path)) == len(loop.log.events)
        assert _incidents(run.log_path) == []
        assert loop.state.halted is None
    finally:
        loop.close()


def test_a_leftover_s_session_end_leaves_the_ledger_the_resume_holds(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, leftovers: list[int]
) -> None:
    """The task ledger, held open as the event log is, is never replaced beneath its writer."""
    run = Run(tmp_path, "leftover")
    _orchestrator_dies(run, run.dispatcher(monkeypatch), monkeypatch)
    leftovers.append(int(json.loads((run.session_dir() / "process.json").read_text())["pid"]))
    path = run.run.run_dir / "ledger.jsonl"
    ledger = TaskLedger(path)
    try:
        line = TaskLine(
            id="s1", spec_path="specs/s1.md", assigned_role="electrical", attempt_count=1
        )
        ledger.append(line)
        resumed = run.dispatcher(monkeypatch)
        resumed.stop_leftovers()
        resumed.end_leftovers()
        assert (run.flags / "session-end-ran").exists(), "the leftover never ran its end hook"
        assert _holds(path, ledger._handle), "the ledger was replaced beneath its writer"
        assert path.read_bytes().endswith(line.model_dump_json().encode() + b"\n")
    finally:
        ledger.close()


def test_a_session_s_write_to_the_held_log_is_refused_and_the_log_is_never_replaced(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, leftovers: list[int]
) -> None:
    """A normal run: the session appends to the log its orchestrator holds, then calls a tool."""
    run = Run(tmp_path, "writes-log")
    loop = Rig(run.run.run_dir).open()
    try:
        raised: BaseException | None = None
        try:
            run.dispatcher(monkeypatch).run(run.request(), loop._spawned)
        except Exception as exc:  # noqa: BLE001 - whichever refusal it is, it names the log
            raised = exc
        assert _holds(run.log_path, loop.log._handle), "the log was replaced beneath the run"
        assert raised is not None, "the session's write to the run's log went unrefused"
        assert "events.jsonl" in json.dumps(getattr(raised, "context", {})), raised
    finally:
        loop.close()


def test_a_line_a_leftover_rewrote_before_the_resume_opened_halts_the_run(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, leftovers: list[int]
) -> None:
    """History rewritten in place, the file kept: found against the session's own record."""
    run = Run(tmp_path, "leftover")
    _orchestrator_dies(run, run.dispatcher(monkeypatch), monkeypatch)
    leftovers.append(int(json.loads((run.session_dir() / "process.json").read_text())["pid"]))
    first = json.loads(run.log_path.read_bytes().splitlines()[0])
    old = first["ts"].encode()
    new = b"2000-01-01T00:00:00." + b"0" * (len(old) - len("2000-01-01T00:00:00.") - 1) + b"Z"
    data = run.log_path.read_bytes()
    with run.log_path.open("r+b") as out:
        out.write(data.replace(old, new, 1))
    loop = _resume(run, monkeypatch)
    try:
        loop._stop_leftovers()
        assert _holds(run.log_path, loop.log._handle)
        assert _incidents(run.log_path)[-1:] == ["run_records_changed"]
        assert loop.state.halted is not None
    finally:
        loop.close()


def test_a_line_a_leftover_added_before_the_resume_opened_halts_the_run(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, leftovers: list[int]
) -> None:
    """Its orchestrator died mid-session, so nothing it wrote can follow the session's record."""
    run = Run(tmp_path, "leftover")
    _orchestrator_dies(run, run.dispatcher(monkeypatch), monkeypatch)
    leftovers.append(int(json.loads((run.session_dir() / "process.json").read_text())["pid"]))
    # A line of the record's form, but no end, finding, incident or process start: tokens.
    forger = EventLog(run.log_path, run_id="run-1", gate_mode="on")
    sid = run.session_dir().name
    usage = {"input_tokens": 1, "output_tokens": 1, "cache_creation_input_tokens": 0}
    usage |= {"cache_read_input_tokens": 0}
    forger.emit(TokensUsed, attribution=f"session:{sid}", message_id="m-forged", usage=usage)
    forger.close()
    loop = _resume(run, monkeypatch)
    try:
        loop._stop_leftovers()
        assert _holds(run.log_path, loop.log._handle)
        assert _incidents(run.log_path)[-1:] == ["run_records_changed"]
        assert loop.state.halted is not None
    finally:
        loop.close()


def test_a_line_a_leftover_adds_after_the_resume_opened_stops_the_resume_writing(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, leftovers: list[int]
) -> None:
    """The log is no longer what the resume wrote: it writes nothing more to it and stops."""
    run = Run(tmp_path, "leftover")
    _orchestrator_dies(run, run.dispatcher(monkeypatch), monkeypatch)
    leftovers.append(int(json.loads((run.session_dir() / "process.json").read_text())["pid"]))
    loop = _resume(run, monkeypatch)
    try:
        # A valid line, by a writer other than the resume's own.
        forger = EventLog(run.log_path, run_id="run-1", gate_mode="on")
        forger.emit(InstallChecked, path="/forged", action="checked", seconds=0.0, entries=0)
        forger.close()
        held = run.log_path.read_bytes()
        raised: BaseException | None = None
        try:
            loop._stop_leftovers()
        except Exception as exc:  # noqa: BLE001 - its class is asserted below
            raised = exc
        assert raised is not None and type(raised).__name__ == "RecordMovedError", raised
        assert run.log_path.read_bytes() == held, "the resume wrote to a log it no longer holds"
    finally:
        loop.close()


def test_a_session_s_copy_of_the_held_log_in_its_place_is_refused_at_its_end(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, leftovers: list[int]
) -> None:
    """The same bytes on a new inode: the orchestrator's record of the roots holds the identity."""
    run = Run(tmp_path, "copies-log")
    loop = Rig(run.run.run_dir).open()
    try:
        raised: BaseException | None = None
        try:
            run.dispatcher(monkeypatch).run(run.request(), loop._spawned)
        except Exception as exc:  # noqa: BLE001 - its context is asserted below
            raised = exc
        assert raised is not None, "a copy of the run's log in its place went unrefused"
        assert "events.jsonl" in json.dumps(getattr(raised, "context", {})), raised
    finally:
        loop.close()


def test_a_log_a_leftover_replaced_by_a_copy_before_the_resume_opened_halts_the_run(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, leftovers: list[int]
) -> None:
    """The same bytes, another file: not the one the session started with."""
    run = Run(tmp_path, "leftover")
    _orchestrator_dies(run, run.dispatcher(monkeypatch), monkeypatch)
    leftovers.append(int(json.loads((run.session_dir() / "process.json").read_text())["pid"]))
    copy = run.log_path.with_name("events.copy")
    shutil.copy2(run.log_path, copy)
    os.replace(copy, run.log_path)
    loop = _resume(run, monkeypatch)
    try:
        loop._stop_leftovers()
        assert _holds(run.log_path, loop.log._handle)
        assert _incidents(run.log_path)[-1:] == ["run_records_changed"]
        assert loop.state.halted is not None
    finally:
        loop.close()


def test_a_line_of_the_resume_s_own_rewritten_in_place_halts_the_run(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, leftovers: list[int]
) -> None:
    """Same file, same size: only the resume's own digest of what it wrote tells."""
    run = Run(tmp_path, "leftover")
    _orchestrator_dies(run, run.dispatcher(monkeypatch), monkeypatch)
    leftovers.append(int(json.loads((run.session_dir() / "process.json").read_text())["pid"]))
    loop = _resume(run, monkeypatch)
    try:
        data = run.log_path.read_bytes()
        at = data.rindex(b'"seconds":0.1')
        with run.log_path.open("r+b") as out:
            out.seek(at)
            out.write(b'"seconds":0.2')
        loop._stop_leftovers()
        assert _incidents(run.log_path)[-1:] == ["run_records_changed"]
        assert loop.state.halted is not None
    finally:
        loop.close()


def test_lines_a_run_wrote_after_its_session_ended_are_its_own_at_the_resume(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, leftovers: list[int]
) -> None:
    """The session ended under its run, which wrote on and died before the end's own line."""
    run = Run(tmp_path, "clean")
    loop = Rig(run.run.run_dir).open()
    try:
        run.dispatcher(monkeypatch).run(run.request(), loop._spawned)
        loop.record.emit(
            InstallChecked(
                **loop.record.envelope(), path="/its-run", action="checked", seconds=0.0, entries=0
            )
        )
    finally:
        loop.close()
    resumed = _resume(run, monkeypatch)
    try:
        resumed._stop_leftovers()
        assert "run_records_changed" not in _incidents(run.log_path)
        assert _holds(run.log_path, resumed.log._handle)
    finally:
        resumed.close()


def test_after_the_stop_a_rewritten_journal_refuses_and_a_record_change_does_not() -> None:
    """A record's change is the loop's to judge at a resume; a journal is never put back."""
    assert sentinel_refusal(2, [{"decision": "journal changed"}]) is not None
    assert sentinel_refusal(2, [{"decision": "record changed"}]) is None


def test_an_earlier_resume_s_first_lines_are_no_change_at_the_next_resume(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, leftovers: list[int]
) -> None:
    """A resume that wrote its first lines and died before it ended the leftover is a later run."""
    run = Run(tmp_path, "leftover")
    _orchestrator_dies(run, run.dispatcher(monkeypatch), monkeypatch)
    leftovers.append(int(json.loads((run.session_dir() / "process.json").read_text())["pid"]))
    _resume(run, monkeypatch).close()
    loop = _resume(run, monkeypatch)
    try:
        loop._stop_leftovers()
        assert "run_records_changed" not in _incidents(run.log_path)
        assert loop.state.halted is None
    finally:
        loop.close()
