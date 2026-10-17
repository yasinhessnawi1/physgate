"""A role session leaves nothing running, and nothing written, by the orchestrator's first git call.

The sentinel's last check runs at the session's SessionEnd hook. Before, the dispatcher went on
from the session's exit to its commit with whatever the session had started still running: a
process left behind could write a put-back root after that last check and before, or after, the
orchestrator's git calls, and nothing would put it back.

Here a stand-in binary plays the session exactly as the runtime's hooks see one: it runs the
generated SessionStart command (the sentinel takes its record), starts inert children, runs the
generated SessionEnd command, and exits with a completed result. Each child tries to write an inert
marker into a temporary put-back root after SessionEnd:

- a sleep loop that writes a second after the session has gone;
- the same, ignoring SIGTERM;
- a double fork whose grandchild calls ``setsid`` and outlives the parent between it and the
  session;
- a child that writes between SessionEnd and the session's exit, and then sleeps.

The orchestrator's commit is wrapped so that each test sees the world at its first git call: no
child running, the root holding nothing new. The children must also have been found and stopped
(named in the session's end record), so a run where the collection missed one fails rather than
passing because the child had not yet written.
"""

from __future__ import annotations

import json
import os
import signal
import stat
import subprocess
import sys
import time
from collections.abc import Callable, Iterator
from pathlib import Path
from typing import Any

import pytest
from left_session import spawn_logged
from orch_helpers import make_config

from physgate.hooks.registry import REGISTRY
from physgate.hooks.settings import InstallRequest, install
from physgate.orchestrator import dispatch, processes
from physgate.orchestrator.credentials import Credential
from physgate.orchestrator.dispatch import ClaudeDispatcher, Installed
from physgate.orchestrator.exceptions import InvocationError
from physgate.orchestrator.git import head_of
from physgate.orchestrator.install import InstallFacts
from physgate.orchestrator.merge import RunGit, commit_attempt
from physgate.orchestrator.ports import SessionRequest
from physgate.orchestrator.processes import started_at
from physgate.orchestrator.run_config import RunBounds
from physgate.reviewers import ending
from physgate.state.store import Store

MODEL = "claude-sonnet-5"
MARKER = "inert-marker.txt"
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

#: The stand-in session. ``FLAGS``, ``ROOT``, ``MODE`` and ``PAUSE`` are prepended. Every child
#: writes its pid to ``FLAGS/pids`` and only ever writes ``ROOT/MARKER``, an inert line of text.
SESSION = r"""
import json, os, shlex, signal, subprocess, sys, time

argv = sys.argv[1:]
if argv == ["--version"]:
    print("2.1.272 (Claude Code)")
    sys.exit(0)
settings = json.load(open(argv[argv.index("--settings") + 1]))
session_id = argv[argv.index("--session-id") + 1]
me = os.getpid()


def hook(event):
    command = settings["hooks"][event][0]["hooks"][0]["command"]
    body = json.dumps({"session_id": session_id, "cwd": os.getcwd(), "hook_event_name": event})
    subprocess.run(shlex.split(command), input=body.encode(), capture_output=True, check=False)


def note(pid):
    with open(os.path.join(FLAGS, "pids"), "a") as out:
        out.write(f"{pid}\n")


def write_marker():
    with open(os.path.join(ROOT, MARKER), "w") as out:
        out.write("inert\n")


def after_the_session_then_write():
    # Wait for the session to have gone, then a second more, then write.
    while True:
        try:
            os.kill(me, 0)
        except ProcessLookupError:
            break
        if os.getppid() != me and MODE not in ("setsid", "orphan"):
            break
        time.sleep(0.05)
    time.sleep(1.0)
    write_marker()
    time.sleep(120)


hook("SessionStart")
os.makedirs("modules/power", exist_ok=True)
open("modules/power/a.py", "w").write("x = 2\n")
if MODE in ("sleeper", "deaf"):
    pid = os.fork()
    if pid == 0:
        if MODE == "deaf":
            signal.signal(signal.SIGTERM, signal.SIG_IGN)
        after_the_session_then_write()
        os._exit(0)
    note(pid)
elif MODE == "setsid":
    pid = os.fork()
    if pid == 0:
        os.setsid()
        grandchild = os.fork()
        if grandchild == 0:
            after_the_session_then_write()
            os._exit(0)
        note(grandchild)
        # Long enough for the orchestrator's collection to see the grandchild under it.
        time.sleep(0.8)
        os._exit(0)
    os.waitpid(pid, 0)
elif MODE == "between":
    pid = os.fork()
    if pid == 0:
        while not os.path.exists(os.path.join(FLAGS, "session-end-ran")):
            time.sleep(0.02)
        write_marker()
        open(os.path.join(FLAGS, "written"), "w").close()
        time.sleep(120)
        os._exit(0)
    note(pid)
elif MODE == "orphan":
    # A grandchild left in the session's group whose parent exits at once: in the group, not
    # in the tree.
    pid = os.fork()
    if pid == 0:
        grandchild = os.fork()
        if grandchild == 0:
            after_the_session_then_write()
            os._exit(0)
        note(grandchild)
        os._exit(0)
    os.waitpid(pid, 0)
elif MODE in ("halted", "forget", "erase", "corrupt", "link"):
    sdir = os.path.dirname(os.path.dirname(argv[argv.index("--settings") + 1]))
    record = os.path.join(sdir, "state", "sessions", session_id, "sentinel", "baseline.json")
    pid = os.fork()
    if pid == 0:
        while not os.path.exists(os.path.join(FLAGS, "session-end-ran")):
            time.sleep(0.02)
        if MODE == "halted":
            # The sentinel's own record says it halted: its check then compares nothing.
            base = json.load(open(record))
            base["halted"] = "inert"
            json.dump(base, open(record, "w"))
            write_marker()
        elif MODE == "erase":
            # The sentinel's own record is gone, and a protected file with it.
            os.unlink(record)
            os.unlink(os.path.join(ROOT, "kept.txt"))
        elif MODE == "corrupt":
            # The sentinel's own record no longer parses: its check cannot complete.
            with open(record, "w") as out:
                out.write("not a record")
        elif MODE == "forget":
            # The sentinel's own record is gone: its check takes a new one, the change included.
            # The change keeps the file's size and mode: only its bytes differ.
            os.unlink(record)
            with open(os.path.join(ROOT, "kept.txt"), "w") as out:
                out.write("KEPT\n")
        else:
            os.symlink(os.path.join(FLAGS, "victim.txt"), os.path.join(sdir, "ended.json"))
        open(os.path.join(FLAGS, "written"), "w").close()
        time.sleep(120)
        os._exit(0)
    note(pid)
elif MODE == "tamper":
    pid = os.fork()
    if pid == 0:
        while not os.path.exists(os.path.join(FLAGS, "session-end-ran")):
            time.sleep(0.02)
        config = argv[argv.index("--settings") + 1].replace("settings.json", "session-config.json")
        with open(config, "a") as out:
            out.write(" ")
        open(os.path.join(FLAGS, "written"), "w").close()
        time.sleep(120)
        os._exit(0)
    note(pid)
time.sleep(PAUSE)
hook("SessionEnd")
open(os.path.join(FLAGS, "session-end-ran"), "w").close()
if MODE in ("between", "tamper", "halted", "forget", "erase", "corrupt", "link"):
    while not os.path.exists(os.path.join(FLAGS, "written")):
        time.sleep(0.02)
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


def _git(cwd: Path, *args: str) -> None:
    subprocess.run(["git", *args], cwd=cwd, env=GITENV, capture_output=True, check=True)


def _layout(root: Path) -> tuple[RunGit, Path]:
    repo = root / "target"
    (repo / "modules" / "power").mkdir(parents=True)
    (repo / "modules" / "power" / "base.py").write_text("x = 1\n")
    _git(repo, "init", "-q", "-b", "master")
    _git(repo, "add", "-A")
    _git(repo, "commit", "-q", "-m", "initial")
    run = RunGit(repo=repo, run_dir=root / "run", run_id="run-1")
    run.open_run_branch(head_of(repo, "master"))
    store_root = run.run_dir / "store"
    Store(store_root).close()
    return run, store_root


@pytest.fixture
def leftovers() -> Iterator[list[int]]:
    """Pids a test's session started; any still running when it ends is killed."""
    pids: list[int] = []
    yield pids
    for pid in pids:
        if started_at(pid) is not None:
            os.kill(pid, signal.SIGKILL)


class Session:
    """One dispatched stand-in session, and what the orchestrator saw at its first git call."""

    def __init__(self, tmp_path: Path, mode: str, *, pause: float, wall_clock_s: float) -> None:
        """Lay out the run, the stand-in binary and the temporary put-back root."""
        self.flags = tmp_path / "flags"
        self.flags.mkdir()
        self.run, self.store_root = _layout(tmp_path)
        #: The temporary put-back root: protected by the sentinel, written by no one.
        self.root = tmp_path / "guarded"
        self.root.mkdir()
        (self.root / "kept.txt").write_text("kept\n")
        binary = tmp_path / "bin" / "claude"
        binary.parent.mkdir()
        prelude = (
            f"FLAGS = {str(self.flags)!r}\nROOT = {str(self.root)!r}\nMODE = {mode!r}\n"
            f"PAUSE = {pause!r}\nMARKER = {MARKER!r}\nMODEL_NAME = {MODEL!r}\n"
        )
        binary.write_text(f"#!{sys.executable}\n{prelude}{SESSION}")
        binary.chmod(binary.stat().st_mode | stat.S_IXUSR)
        self.binary = binary
        self.wall_clock_s = wall_clock_s
        #: What the first git call found: (pids still running, root's names). None until then.
        self.at_first_git: tuple[list[int], list[str]] | None = None

    def spawned(self, session_id: str, pid: int, started: str) -> None:
        """The loop's own record of the spawn, in the run's event log."""
        spawn_logged(self.run.run_dir, [(session_id, pid, started)])

    def pids(self) -> list[int]:
        path = self.flags / "pids"
        return [int(x) for x in path.read_text().split()] if path.exists() else []

    def bounds(self) -> RunBounds:
        return RunBounds(
            binary_max_retries=0,
            session_wall_clock_s=self.wall_clock_s,
            session_max_turns=20,
            infra_retry_delays_s=(),
        )

    def dispatcher(self, monkeypatch: pytest.MonkeyPatch) -> ClaudeDispatcher:
        config = make_config(bounds=self.bounds())
        root, store_root = self.root, self.store_root

        def _install(  # noqa: ANN401
            _self: Any,
            request: SessionRequest,
            worktree: Path,
            sdir: Path,
            _temp: Path | None,
        ) -> Installed:
            (sdir / "state").mkdir(parents=True)
            done = install(
                InstallRequest(
                    profile="role",
                    role=request.assigned_role,
                    worktree=str(worktree),
                    own_branch=_self._run.subtask_branch(request.subtask_id),
                    store_root=str(store_root),
                    state_dir=str(sdir / "state"),
                    target_dir=str(sdir / "session"),
                    claude_config_dir=str(sdir / "config"),
                    user_home=str(sdir / "home"),
                    token_ceiling=100_000,
                    extra_protected=(str(root),),
                ),
                REGISTRY,
            )
            return Installed(
                settings=str(done.settings_path),
                config=str(done.config_path),
                spawn_args=done.spawn_args,
                spawn_env=dict(done.spawn_env),
            )

        original = commit_attempt

        def first_git_call(*args: Any, **kwargs: Any) -> str:  # noqa: ANN401
            running = [pid for pid in self.pids() if started_at(pid) is not None]
            self.at_first_git = (running, sorted(p.name for p in self.root.iterdir()))
            return original(*args, **kwargs)

        monkeypatch.setattr(ClaudeDispatcher, "_install", _install)
        monkeypatch.setattr(ClaudeDispatcher, "environment", lambda _self: FACTS)
        monkeypatch.setattr(dispatch, "binary_version", lambda _binary: config.claude_version)
        monkeypatch.setattr(dispatch, "commit_attempt", first_git_call)
        return ClaudeDispatcher(
            config=config,
            run=self.run,
            store_root=self.store_root,
            # The installation is this interpreter's environment, as the hooks are installed.
            install_bin=Path(sys.executable).parent / "physgate",
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
            bounds=self.bounds(),
        )


def _settle(check: Callable[[], bool], seconds: float) -> bool:
    deadline = time.monotonic() + seconds
    while time.monotonic() < deadline:
        if check():
            return True
        time.sleep(0.05)
    return check()


@pytest.mark.parametrize("mode", ["sleeper", "deaf", "setsid"])
def test_a_child_that_would_write_after_the_session_is_stopped_before_the_first_git_call(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, leftovers: list[int], mode: str
) -> None:
    monkeypatch.setattr(ending, "GRACE_S", 0.5)
    session = Session(tmp_path, mode, pause=1.0, wall_clock_s=60.0)
    report = session.dispatcher(monkeypatch).run(session.request(), session.spawned)
    children = session.pids()
    leftovers += children
    assert report.end.outcome == "completed", report
    assert children, "the stand-in started no child"
    # At the orchestrator's first git call on the attempt: nothing running, nothing written.
    assert session.at_first_git == ([], ["kept.txt"])
    ended = json.loads((Path(str(report.trajectory)).parent / "ended.json").read_text())
    # Reached: each child was found running after the session and stopped, not merely early.
    assert set(children) <= set(ended["left_running"])
    # And it never writes: past the time it would have, the root holds only what it held.
    time.sleep(2.0)
    assert sorted(p.name for p in session.root.iterdir()) == ["kept.txt"]
    assert all(started_at(pid) is None for pid in children)


def test_a_write_between_session_end_and_the_stop_is_put_back_before_the_first_git_call(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, leftovers: list[int]
) -> None:
    session = Session(tmp_path, "between", pause=0.0, wall_clock_s=60.0)
    report = session.dispatcher(monkeypatch).run(session.request(), session.spawned)
    children = session.pids()
    leftovers += children
    assert report.end.outcome == "completed", report
    assert session.at_first_git == ([], ["kept.txt"])
    sdir = Path(str(report.trajectory)).parent
    ended = json.loads((sdir / "ended.json").read_text())
    assert set(children) <= set(ended["left_running"])
    marker = str(session.root / MARKER)
    # The sentinel's check, run again after the stop, put it back: moved aside, not deleted.
    assert ended["sentinel_after_stop"]["put_back"] == [marker]
    log = [
        json.loads(line)
        for line in (sdir / "state" / "hooks.log.jsonl").read_text().split("\n")
        if line
    ]
    put_back = [r for r in log if r.get("decision") == "put back"]
    assert [r["paths"] for r in put_back] == [[marker]]
    assert put_back[0]["event"] == "SessionEnd"


def test_a_check_that_cannot_run_after_the_stop_refuses_before_any_git_call(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, leftovers: list[int]
) -> None:
    """A child that changes the sentinel's configuration after SessionEnd: no check, no commit."""
    session = Session(tmp_path, "tamper", pause=0.0, wall_clock_s=60.0)
    dispatcher = session.dispatcher(monkeypatch)
    with pytest.raises(InvocationError, match="sentinel"):
        dispatcher.run(session.request(), session.spawned)
    leftovers += session.pids()
    assert session.at_first_git is None
    assert session.pids() and all(started_at(pid) is None for pid in session.pids())


def test_a_session_stopped_at_its_clock_leaves_no_setsid_grandchild(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, leftovers: list[int]
) -> None:
    """At the wall clock the tree walk alone misses a grandchild that left it; the stop does not."""
    session = Session(tmp_path, "setsid", pause=60.0, wall_clock_s=3.0)
    report = session.dispatcher(monkeypatch).run(session.request(), session.spawned)
    children = session.pids()
    leftovers += children
    assert report.end.outcome == "infrastructure" and report.end.cause == "wall_clock"
    assert children
    assert _settle(lambda: all(started_at(pid) is None for pid in children), 1.0)
    time.sleep(2.0)
    assert sorted(p.name for p in session.root.iterdir()) == ["kept.txt"]
    ended = json.loads(
        (session.run.run_dir / "sessions" / report.session_id / "ended.json").read_text()
    )
    assert ended["timed_out"] and set(children) <= set(ended["left_running"])


def _refused_before_git(session: Session, dispatcher: ClaudeDispatcher) -> dict[str, Any]:
    """Run the attempt, which must be refused before any git call; return what it recorded."""
    with pytest.raises(InvocationError, match="no git call follows"):
        dispatcher.run(session.request(), session.spawned)
    assert session.at_first_git is None
    (record,) = session.run.run_dir.glob("sessions/*/after_stop.json")
    assert not (record.parent / "ended.json").exists()
    settled: dict[str, Any] = json.loads(record.read_text())
    # The sentinel's check ran all the same, after the stop.
    assert settled["sentinel_after_stop"]["refused"] is None
    assert settled["sentinel_after_stop"]["exit"] == 0
    return settled


def test_a_stop_that_leaves_a_survivor_refuses_the_attempt_before_any_git_call(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, leftovers: list[int]
) -> None:
    """The stop exhausted (here it stops nothing): the table, read again, still shows the child."""
    session = Session(tmp_path, "sleeper", pause=1.0, wall_clock_s=60.0)
    dispatcher = session.dispatcher(monkeypatch)
    monkeypatch.setattr(ending, "stop_all", lambda procs: ())
    try:
        settled = _refused_before_git(session, dispatcher)
    finally:
        leftovers += session.pids()
    assert settled["stop_unconfirmed"].startswith("still running after the stop")
    assert str(session.pids()[0]) in settled["stop_unconfirmed"]


def test_a_process_table_that_cannot_be_read_refuses_the_attempt_before_any_git_call(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, leftovers: list[int]
) -> None:
    session = Session(tmp_path, "sleeper", pause=1.0, wall_clock_s=60.0)
    dispatcher = session.dispatcher(monkeypatch)
    monkeypatch.setattr(dispatch, "process_rows", lambda: None, raising=False)
    try:
        settled = _refused_before_git(session, dispatcher)
    finally:
        leftovers += session.pids()
    assert settled["stop_unconfirmed"] == "the process table could not be read"


def test_a_stop_denied_its_signal_refuses_the_attempt_before_any_git_call(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, leftovers: list[int]
) -> None:
    session = Session(tmp_path, "sleeper", pause=1.0, wall_clock_s=60.0)
    dispatcher = session.dispatcher(monkeypatch)

    def denied(pid: int, sig: int) -> None:
        raise PermissionError(1, "Operation not permitted")

    monkeypatch.setattr(ending, "_send", denied)
    try:
        settled = _refused_before_git(session, dispatcher)
    finally:
        leftovers += session.pids()
    assert "PermissionError" in settled["stop_unconfirmed"]


class Died(BaseException):
    """The orchestrator killed while its session ran."""


def _orchestrator_dies(
    session: Session, dispatcher: ClaudeDispatcher, mp: pytest.MonkeyPatch
) -> None:
    def die(*_args: Any, **_kwargs: Any) -> None:  # noqa: ANN401
        raise Died

    with mp.context() as killed:
        killed.setattr(dispatch, "await_session", die)
        with pytest.raises(Died):
            dispatcher.run(session.request(), session.spawned)


def _resumed(session: Session, dispatcher: ClaudeDispatcher) -> ClaudeDispatcher:
    return ClaudeDispatcher(
        config=dispatcher._config,
        run=session.run,
        store_root=session.store_root,
        install_bin=Path(sys.executable).parent / "physgate",
        binary=str(session.binary),
        base_url=None,
        credential=Credential(mode="api_key", secret="not-a-key"),
        review_root=Path("/nonexistent/review-scratch"),
    )


def test_a_resume_stops_what_a_running_role_session_left_in_its_own_group(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, leftovers: list[int]
) -> None:
    """The orchestrator died; at the resume the session runs still, a grandchild in its group."""
    session = Session(tmp_path, "orphan", pause=60.0, wall_clock_s=120.0)
    dispatcher = session.dispatcher(monkeypatch)
    _orchestrator_dies(session, dispatcher, monkeypatch)
    try:
        assert _settle(lambda: bool(session.pids()), 20.0)
        (grandchild,) = session.pids()
        (left,) = _resumed(session, dispatcher).stop_leftovers()
    finally:
        leftovers += session.pids()
    assert left.stopped
    ended = json.loads(
        (session.run.run_dir / "sessions" / left.session_id / "ended.json").read_text()
    )
    # Not in the session's tree when it was stopped: found in the group the harness made.
    assert grandchild in ended["left_running"]
    assert started_at(grandchild) is None
    time.sleep(2.0)
    assert sorted(p.name for p in session.root.iterdir()) == ["kept.txt"]


def _left_exited(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, leftovers: list[int]
) -> tuple[Session, ClaudeDispatcher, int]:
    """The orchestrator died; then its session exited, and the session's child wrote."""
    session = Session(tmp_path, "sleeper", pause=1.0, wall_clock_s=60.0)
    dispatcher = session.dispatcher(monkeypatch)
    _orchestrator_dies(session, dispatcher, monkeypatch)
    try:
        assert _settle((session.root / MARKER).exists, 20.0), "the child never wrote"
    finally:
        leftovers += session.pids()
    (child,) = session.pids()
    return session, dispatcher, child


def _process_record(session: Session) -> Path:
    (record,) = session.run.run_dir.glob("sessions/*/process.json")
    return record


def test_a_resume_stops_what_an_exited_session_left_in_its_group_and_puts_its_write_back(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, leftovers: list[int]
) -> None:
    """Its record agrees with the spawn the event log holds: its group is the session's."""
    session, dispatcher, child = _left_exited(tmp_path, monkeypatch, leftovers)
    (left,) = _resumed(session, dispatcher).stop_leftovers()
    assert not left.stopped  # the session itself had exited
    assert started_at(child) is None
    ended = json.loads(_process_record(session).with_name("ended.json").read_text())
    assert child in ended["left_running"]
    assert ended["sentinel_after_stop"]["put_back"] == [str(session.root / MARKER)]
    assert sorted(p.name for p in session.root.iterdir()) == ["kept.txt"]


def test_a_process_record_rewritten_to_name_a_live_process_refuses_the_resume(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, leftovers: list[int]
) -> None:
    """The leftover's write: the record now names this live process, which is no session."""
    session, dispatcher, child = _left_exited(tmp_path, monkeypatch, leftovers)
    record = _process_record(session)
    forged = json.loads(record.read_text()) | {
        "pid": os.getpid(),
        "started": started_at(os.getpid()),
    }
    record.write_text(json.dumps(forged))
    with pytest.raises(InvocationError, match="nothing is signalled"):
        _resumed(session, dispatcher).stop_leftovers()
    # Refused, not passed: the child is not taken for gone, nor signalled on the record's say.
    assert started_at(child) is not None
    refused = json.loads(record.with_name("after_stop.json").read_text())
    assert refused["record_refused"].startswith("the process record's pid or start time")


def test_a_forged_review_record_naming_another_run_s_session_signals_nothing(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, leftovers: list[int]
) -> None:
    """A review directory made for this run, named for another run's live session."""
    session = Session(tmp_path, "sleeper", pause=0.0, wall_clock_s=60.0)
    dispatcher = session.dispatcher(monkeypatch)
    victim_id = "33333333-3333-4333-8333-333333333333"
    marker = tmp_path / "victim"
    victim = subprocess.Popen(
        [sys.executable, "-c", VICTIM, str(marker), "--session-id", victim_id],
        start_new_session=True,
    )
    try:
        assert _settle(lambda: marker.exists() and len(marker.read_text().split()) == 2, 10.0)
        leader, member = (int(x) for x in marker.read_text().split())
        leftovers += [leader, member]
        review_root = tmp_path / "review-scratch"
        sdir = review_root / victim_id / "session"
        sdir.mkdir(parents=True)
        (sdir / "owner.json").write_text(json.dumps({"run_id": "run-1"}))
        record = {
            "pid": leader,
            "started": started_at(leader),
            "session_id": victim_id,
            "kind": "reviewer",
        }
        (sdir / "process.json").write_text(json.dumps(record))
        resumed = _resumed(session, dispatcher)
        resumed._review_root = review_root
        with pytest.raises(InvocationError, match="nothing is signalled"):
            resumed.stop_leftovers()
        time.sleep(0.5)
        assert started_at(leader) is not None and started_at(member) is not None
        refused = json.loads((sdir / "after_stop.json").read_text())
        assert refused["record_refused"] == "the event log records no spawn of this session"
    finally:
        victim.kill()
        victim.wait()


def test_a_sentinel_record_deleted_after_the_session_refuses_the_resume(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, leftovers: list[int]
) -> None:
    """The leftover's write: the record the check compares with is gone. No pass."""
    session, dispatcher, _child = _left_exited(tmp_path, monkeypatch, leftovers)
    sdir = _process_record(session).parent
    (sdir / "state" / "sessions" / sdir.name / "sentinel" / "baseline.json").unlink()
    with pytest.raises(InvocationError, match="the resume goes no further"):
        _resumed(session, dispatcher).stop_leftovers()
    settled = json.loads((sdir / "after_stop.json").read_text())
    assert settled["sentinel_after_stop"]["refused"] == (
        "the sentinel's record of the session is missing"
    )
    assert not (sdir / "ended.json").exists()


VICTIM = r"""
import os, subprocess, sys, time
member = subprocess.Popen([sys.executable, "-c", "import time; time.sleep(120)"])
# Out of its tree, in its group: the parent of the member exits at once.
open(sys.argv[1], "w").write(f"{os.getpid()} {member.pid}")
time.sleep(120)
"""


def test_a_record_naming_another_run_s_session_signals_nothing(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, leftovers: list[int]
) -> None:
    """A forged record names a live session of another run, leading its own group."""
    session = Session(tmp_path, "sleeper", pause=0.0, wall_clock_s=60.0)
    dispatcher = session.dispatcher(monkeypatch)
    marker = tmp_path / "victim"
    victim = subprocess.Popen(
        [sys.executable, "-c", VICTIM, str(marker), "--session-id", "other-runs-session"],
        start_new_session=True,
    )
    try:
        assert _settle(
            lambda: len(marker.read_text().split()) == 2 if marker.exists() else False, 10.0
        )
        leader, member = (int(x) for x in marker.read_text().split())
        leftovers += [leader, member]
        forged = session.run.run_dir / "sessions" / "forged"
        forged.mkdir(parents=True)
        record = {"pid": leader, "started": started_at(leader), "session_id": "other-runs-session"}
        (forged / "process.json").write_text(json.dumps(record))
        with pytest.raises(InvocationError, match="nothing is signalled"):
            _resumed(session, dispatcher).stop_leftovers()
        time.sleep(0.5)
        assert started_at(leader) is not None and started_at(member) is not None
        refused = json.loads((forged / "after_stop.json").read_text())
        assert refused["record_refused"] == (
            "the process record names another session than its directory's"
        )
    finally:
        victim.kill()
        victim.wait()


BYSTANDER = r"""
import os, subprocess, sys, time
sleeper = subprocess.Popen([sys.executable, "-c", "import time; time.sleep(120)"])
open(sys.argv[1], "w").write(str(sleeper.pid))
os._exit(0)
"""


def test_a_rewritten_process_record_never_points_a_resume_s_sweep_at_another_group(
    tmp_path: Path, leftovers: list[int], monkeypatch: pytest.MonkeyPatch
) -> None:
    """A record naming the leader of another, leaderless group: its member is never signalled."""
    session = Session(tmp_path, "sleeper", pause=0.0, wall_clock_s=60.0)
    dispatcher = session.dispatcher(monkeypatch)
    marker = tmp_path / "bystander"
    leader = subprocess.Popen(
        [sys.executable, "-c", BYSTANDER, str(marker)], start_new_session=True
    )
    leader.wait()
    member = int(marker.read_text()) if _settle(marker.exists, 10.0) else 0
    leftovers.append(member)
    forged = session.run.run_dir / "sessions" / "forged"
    forged.mkdir(parents=True)
    record = {"pid": leader.pid, "started": "Mon Jan  1 00:00:00 2001", "session_id": "forged"}
    (forged / "process.json").write_text(json.dumps(record))
    with pytest.raises(InvocationError, match="the resume goes no further"):
        _resumed(session, dispatcher).stop_leftovers()
    time.sleep(0.5)
    assert started_at(member) is not None


@pytest.mark.parametrize("mode", ["halted", "forget", "erase"])
def test_a_sentinel_record_rewritten_after_session_end_cannot_pass_a_changed_root(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, leftovers: list[int], mode: str
) -> None:
    """The check after the stop is held to the orchestrator's own record, not the sentinel's."""
    session = Session(tmp_path, mode, pause=0.0, wall_clock_s=60.0)
    dispatcher = session.dispatcher(monkeypatch)
    try:
        with pytest.raises(InvocationError, match="no git call follows"):
            dispatcher.run(session.request(), session.spawned)
    finally:
        leftovers += session.pids()
    assert session.at_first_git is None
    (record,) = session.run.run_dir.glob("sessions/*/after_stop.json")
    settled = json.loads(record.read_text())
    changed = {"halted": MARKER, "forget": "kept.txt", "erase": "kept.txt"}[mode]
    assert settled["protected_changed"] == [str(session.root / changed)]


def test_a_sentinel_check_that_cannot_complete_refuses_though_no_root_changed(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, leftovers: list[int]
) -> None:
    """The check after the stop must complete: a record it cannot read is no pass."""
    session = Session(tmp_path, "corrupt", pause=0.0, wall_clock_s=60.0)
    dispatcher = session.dispatcher(monkeypatch)
    try:
        with pytest.raises(InvocationError, match="no git call follows"):
            dispatcher.run(session.request(), session.spawned)
    finally:
        leftovers += session.pids()
    assert session.at_first_git is None
    (record,) = session.run.run_dir.glob("sessions/*/after_stop.json")
    settled = json.loads(record.read_text())
    assert settled["protected_changed"] == [] and settled["stop_unconfirmed"] is None
    assert settled["sentinel_after_stop"]["refused"] == "the check recorded 'error'"


def test_an_end_record_is_never_written_through_a_link_the_session_planted(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, leftovers: list[int]
) -> None:
    session = Session(tmp_path, "link", pause=0.0, wall_clock_s=60.0)
    victim = session.flags / "victim.txt"
    victim.write_text("inert victim\n")
    try:
        report = session.dispatcher(monkeypatch).run(session.request(), session.spawned)
    finally:
        leftovers += session.pids()
    assert victim.read_text() == "inert victim\n"
    ended = session.run.run_dir / "sessions" / report.session_id / "ended.json"
    assert not ended.is_symlink()
    assert json.loads(ended.read_text())["exit"] == 0


class FailingPs:
    """Stands in for a module's ``subprocess``: ``ps`` fails once ``when`` holds, all else runs."""

    SubprocessError = subprocess.SubprocessError
    TimeoutExpired = subprocess.TimeoutExpired
    CompletedProcess = subprocess.CompletedProcess

    def __init__(self, how: str, when: Callable[[], bool] = lambda: True) -> None:
        self.how, self.when = how, when

    def run(self, argv: list[str], **kwargs: Any) -> subprocess.CompletedProcess[str]:  # noqa: ANN401
        if argv[0] != "ps" or not self.when():
            return subprocess.run(argv, **kwargs)  # noqa: S603, PLW1510
        if self.how == "raises":
            raise OSError(1, "ps could not be started")
        code = 1 if self.how == "fails" else 0
        return subprocess.CompletedProcess(argv, code, stdout="", stderr="")


@pytest.mark.parametrize("how", ["raises", "fails", "empty"])
def test_a_process_table_that_cannot_be_read_never_reads_as_nothing_running(
    monkeypatch: pytest.MonkeyPatch, how: str
) -> None:
    """An enumerator that failed is not an empty table: it raises, or names itself unread."""
    with monkeypatch.context() as m:
        m.setattr(processes, "subprocess", FailingPs(how))
        with pytest.raises(processes.ProcessTableError):
            processes.table()
    with monkeypatch.context() as m:
        m.setattr(dispatch, "subprocess", FailingPs(how))
        assert dispatch.process_rows() is None


def test_a_tree_that_cannot_be_enumerated_while_the_session_runs_refuses_the_attempt(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, leftovers: list[int]
) -> None:
    """The stop's polls cannot list the tree once the session has started its child.

    The grandchild that leaves the group is then never seen, so nothing is confirmed.
    """
    session = Session(tmp_path, "setsid", pause=1.0, wall_clock_s=60.0)
    dispatcher = session.dispatcher(monkeypatch)
    started = session.flags / "pids"
    monkeypatch.setattr(processes, "subprocess", FailingPs("fails", started.exists))
    try:
        settled = _refused_before_git(session, dispatcher)
    finally:
        monkeypatch.undo()
        leftovers += session.pids()
    assert "ProcessTableError" in settled["stop_unconfirmed"]


def test_a_session_whose_start_cannot_be_read_never_runs(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, leftovers: list[int]
) -> None:
    """The process table fails at the spawn: the held process is never let run the session."""
    session = Session(tmp_path, "sleeper", pause=0.0, wall_clock_s=60.0)
    dispatcher = session.dispatcher(monkeypatch)
    monkeypatch.setattr(processes, "subprocess", FailingPs("fails"))
    try:
        with pytest.raises(processes.ProcessTableError):
            dispatcher.run(session.request(), session.spawned)
    finally:
        monkeypatch.undo()
        leftovers += session.pids()
    time.sleep(2.0)
    # No hook of the session ever ran, and nothing it would have started exists.
    assert session.pids() == []
    assert not list(session.run.run_dir.glob("sessions/*/state/sessions/*/sentinel"))
    assert session.at_first_git is None


def test_a_put_back_root_that_cannot_be_read_starts_no_session(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, leftovers: list[int]
) -> None:
    """A directory in a root that cannot be listed starts no session.

    What it holds cannot be confirmed, before the session or after it.
    """
    session = Session(tmp_path, "sleeper", pause=0.0, wall_clock_s=60.0)
    locked = session.root / "locked"
    locked.mkdir()
    locked.chmod(0o300)  # writable and enterable, not listable
    dispatcher = session.dispatcher(monkeypatch)
    try:
        with pytest.raises(InvocationError, match="could not be read"):
            dispatcher.run(session.request(), session.spawned)
    finally:
        locked.chmod(0o700)
        leftovers += session.pids()
    assert session.at_first_git is None
    assert session.pids() == []


def test_a_root_that_cannot_be_read_after_the_stop_refuses_the_attempt(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, leftovers: list[int]
) -> None:
    session = Session(tmp_path, "sleeper", pause=1.0, wall_clock_s=60.0)
    dispatcher = session.dispatcher(monkeypatch)

    def unreadable(_record: Any) -> list[str]:  # noqa: ANN401
        raise PermissionError(13, "Permission denied", str(session.root))

    monkeypatch.setattr(dispatch, "changed_since", unreadable)
    try:
        settled = _refused_before_git(session, dispatcher)
    finally:
        leftovers += session.pids()
    assert "PermissionError" in settled["protected_unread"]


@pytest.mark.parametrize(
    ("exit_code", "decisions", "refused"),
    [
        (0, [], False),
        (2, ["put back", "refuse"], False),
        (2, ["node mismatch", "refuse"], False),
        (2, ["journal append"], False),
        (2, ["refuse"], False),
        (2, ["halt", "refuse"], True),
        (2, ["unrestorable", "refuse"], True),
        (2, ["error"], True),
        (2, [], True),
        (1, [], True),
    ],
)
def test_what_the_check_after_the_stop_refuses(
    exit_code: int, decisions: list[str], refused: bool
) -> None:
    """Put back, or left to the readers that already handle it; else the attempt goes no further."""
    records = [{"decision": d} for d in decisions]
    assert (dispatch.sentinel_refusal(exit_code, records) is not None) is refused


def test_the_loop_records_each_spawn_in_its_event_log_as_the_dispatcher_reports_it(
    tmp_path: Path,
) -> None:
    """What a resume holds a process record to is written by the loop, at the spawn."""
    from loop_fakes import FakeDispatcher, FakeReviewer, Rig, plan

    from physgate.orchestrator.events import SessionSpawned, read_events
    from physgate.orchestrator.ports import SessionReport, SpawnHook

    class Spawning(FakeDispatcher):
        def run(self, request: SessionRequest, on_spawn: SpawnHook | None = None) -> SessionReport:
            assert on_spawn is not None, "the loop gave the dispatcher no way to record a spawn"
            on_spawn(f"sess-{request.attempt}", 4242, "Mon Jan  1 00:00:00 2001")
            return super().run(request, on_spawn)

    class Reviewing(FakeReviewer):
        hook: SpawnHook | None = None

        def record_spawns(self, hook: SpawnHook) -> None:
            self.hook = hook

    reviewer = Reviewing()
    rig = Rig(tmp_path, dispatcher=Spawning(), reviewer=reviewer)
    loop = rig.open()
    # The loop gives its reviewers the same record of a spawn.
    assert reviewer.hook is not None
    loop.start(plan("s1"))
    loop.run()
    loop.close()
    spawns = [e for e in read_events(tmp_path / "events.jsonl") if isinstance(e, SessionSpawned)]
    assert [(e.session_id, e.pid) for e in spawns][:1] == [("sess-1", 4242)]
