"""A process a role session's command left running is told apart by its sandbox and killed.

The rule is tested on a stand-in process table and a stand-in sandbox: a process counts only
if it is the user's, started after the session's state directory was made, descends from
nothing the hook descends from, and runs under a sandbox that opens this session's home to
reads and its worktree to writes and denies reads of its state directory. On macOS the
binding to Seatbelt is tested on real sandboxed processes.
"""

from __future__ import annotations

import os
import signal
import subprocess
import sys
import time
from pathlib import Path

import pytest

from physgate.oslayer import survivors
from physgate.oslayer.survivors import (
    Process,
    Seatbelt,
    SessionMark,
    ancestors,
    session_survivors,
)

HOME = "/run/sessions/s1/home"
STATE = "/run/sessions/s1/state"
WORKTREE = "/run/worktrees/sub1"
#: The session's state directory was made at 12:00:00; every listed process started at 12:00:05.
MARK = SessionMark(HOME, STATE, WORKTREE, time.mktime((2026, 10, 21, 12, 0, 0, 0, 0, -1)))
AFTER = "Wed Oct 21 12:00:05 2026"
BEFORE = "Wed Oct 21 11:59:58 2026"


class FakeSeatbelt:
    """Answers from a table: pid -> (sandboxed, reads home, writes worktree, reads state)."""

    def __init__(self, answers: dict[int, tuple[bool, bool, bool, bool]]) -> None:
        self.answers = answers

    def sandboxed(self, pid: int) -> bool:
        return self.answers.get(pid, NONE)[0]

    def allows(self, pid: int, operation: bytes, path: str) -> bool | None:
        _, home, worktree, state = self.answers.get(pid, NONE)
        return {HOME: home, WORKTREE: worktree, STATE: state}[path]


NONE = (False, True, True, True)


def _procs(*rows: tuple[int, int]) -> dict[int, Process]:
    uid = os.getuid()
    return {pid: Process(pid, ppid, uid, AFTER) for pid, ppid in rows}


# launchd 1; the orchestrator 10; Claude Code 20; the hook 30 under its shell 25; a running
# command's shell 40 and its program 41; two survivors handed to launchd, 50 and its child 51.
TREE = _procs((1, 0), (10, 1), (20, 10), (25, 20), (30, 25), (40, 20), (41, 40), (50, 1), (51, 50))
OURS = (True, True, True, False)


def test_ancestors_stop_at_launchd() -> None:
    assert ancestors(30, TREE) == [25, 20, 10]
    assert ancestors(51, TREE) == [50]


def test_only_this_session_s_processes_outside_every_running_command_survive() -> None:
    seatbelt = FakeSeatbelt({41: OURS, 50: OURS, 51: OURS})
    found = session_survivors(mark=MARK, seatbelt=seatbelt, procs=TREE, me=30)  # type: ignore[arg-type]
    # The running command's program is held by Claude Code, which the hook descends from too.
    assert sorted(p.pid for p in found) == [50, 51]


@pytest.mark.parametrize(
    ("answer", "why"),
    [
        ((False, True, True, False), "not sandboxed"),
        ((True, False, True, False), "another session's sandbox: this home is denied to it"),
        ((True, True, False, False), "a sandbox that may not write this worktree"),
        ((True, True, True, True), "a sandbox that is no session's: this state is open to it"),
    ],
)
def test_a_process_under_any_other_sandbox_is_left_alone(
    answer: tuple[bool, bool, bool, bool], why: str
) -> None:
    seatbelt = FakeSeatbelt({50: answer, 51: answer})
    found = session_survivors(mark=MARK, seatbelt=seatbelt, procs=TREE, me=30)  # type: ignore[arg-type]
    assert found == [], why


def test_another_user_s_process_is_left_alone() -> None:
    procs = dict(TREE)
    procs[50] = Process(50, 1, os.getuid() + 1, AFTER)
    procs[51] = Process(51, 50, os.getuid() + 1, AFTER)
    seatbelt = FakeSeatbelt({50: OURS, 51: OURS})
    assert (
        session_survivors(mark=MARK, seatbelt=seatbelt, procs=procs, me=30)  # type: ignore[arg-type]
        == []
    )


def test_a_process_older_than_the_session_is_left_alone() -> None:
    procs = dict(TREE)
    procs[50] = Process(50, 1, os.getuid(), BEFORE)
    procs[51] = Process(51, 50, os.getuid(), "not a time")
    seatbelt = FakeSeatbelt({50: OURS, 51: OURS})
    assert session_survivors(mark=MARK, seatbelt=seatbelt, procs=procs, me=30) == []  # type: ignore[arg-type]


def test_nothing_is_reaped_off_macos(monkeypatch: pytest.MonkeyPatch) -> None:
    # Each Linux command runs in a process namespace of its own, ended with it.
    monkeypatch.setattr(sys, "platform", "linux")
    monkeypatch.setattr(survivors, "table", lambda: pytest.fail("the table was read"))
    assert survivors.reap(MARK) == []


def test_a_survivor_that_keeps_coming_back_is_an_error(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(sys, "platform", "darwin")
    monkeypatch.setattr(survivors, "table", lambda: TREE)
    monkeypatch.setattr(survivors, "_signal", lambda proc, sig: True)
    seatbelt = FakeSeatbelt({50: OURS})
    with pytest.raises(survivors.SurvivorError, match="rounds"):
        survivors.reap(MARK, seatbelt=seatbelt)  # type: ignore[arg-type]


macos = pytest.mark.skipif(sys.platform != "darwin", reason="Seatbelt is macOS's")


def _sandboxed(profile: str) -> subprocess.Popen[bytes]:
    proc = subprocess.Popen(["/usr/bin/sandbox-exec", "-p", profile, "/bin/sleep", "30"])
    time.sleep(0.5)
    return proc


@macos
def test_seatbelt_tells_this_session_s_sandbox_from_any_other(tmp_path: Path) -> None:
    root = Path(os.path.realpath(tmp_path))
    sessions, home, state = (
        root / "sessions",
        root / "sessions" / "s1" / "home",
        root / "sessions" / "s1" / "state",
    )
    home.mkdir(parents=True)
    state.mkdir(parents=True)
    other_home = sessions / "s2" / "home"
    other_home.mkdir(parents=True)
    worktree, other_worktree = root / "worktrees" / "sub1", root / "worktrees" / "sub2"
    worktree.mkdir(parents=True)
    other_worktree.mkdir(parents=True)

    def profile(own_home: Path, own_worktree: Path) -> str:
        return (
            f'(version 1)(allow default)(deny file-read* (subpath "{sessions}"))'
            f'(allow file-read* (subpath "{own_home}"))'
            f'(deny file-write* (subpath "{root}"))(allow file-write* (subpath "{own_worktree}"))'
        )

    ours, theirs = profile(home, worktree), profile(other_home, other_worktree)
    seatbelt = Seatbelt()
    started = [_sandboxed(ours), _sandboxed(theirs), subprocess.Popen(["/bin/sleep", "30"])]
    try:
        verdicts = [
            survivors._ours(  # noqa: SLF001 - the rule itself, on real sandboxes
                p.pid, SessionMark(str(home), str(state), str(worktree), 0.0), seatbelt
            )
            for p in started
        ]
    finally:
        for p in started:
            p.send_signal(signal.SIGKILL)
            p.wait()
    assert verdicts == [True, False, False]
