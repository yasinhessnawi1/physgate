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
from orch_helpers import make_config

from physgate.hooks.registry import REGISTRY
from physgate.hooks.settings import InstallRequest, install
from physgate.orchestrator import dispatch
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
        if os.getppid() != me and MODE != "setsid":
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
if MODE in ("between", "tamper"):
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

        def _install(_self: Any, request: SessionRequest, worktree: Path, sdir: Path) -> Installed:  # noqa: ANN401
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
            install_bin=Path("/nonexistent/bin/physgate"),
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
    report = session.dispatcher(monkeypatch).run(session.request())
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
    report = session.dispatcher(monkeypatch).run(session.request())
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
        dispatcher.run(session.request())
    leftovers += session.pids()
    assert session.at_first_git is None
    assert session.pids() and all(started_at(pid) is None for pid in session.pids())


def test_a_session_stopped_at_its_clock_leaves_no_setsid_grandchild(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, leftovers: list[int]
) -> None:
    """At the wall clock the tree walk alone misses a grandchild that left it; the stop does not."""
    session = Session(tmp_path, "setsid", pause=60.0, wall_clock_s=3.0)
    report = session.dispatcher(monkeypatch).run(session.request())
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
