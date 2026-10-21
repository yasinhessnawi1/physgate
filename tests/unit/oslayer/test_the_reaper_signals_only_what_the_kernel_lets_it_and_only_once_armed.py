"""The survivor reaper's selection and its one signal function, against a stand-in kernel.

No real signal is sent here: the kernel is a table. A process "in the sandbox" is one the
stand-in lets the reaper signal; every other one answers EPERM, as Seatbelt does for a
process outside the command's own sandbox (measured 21.10.2026). What is held: nothing but
signal 0 goes out before the sandbox and canary guards held, or in a dry run; no pid of 1 or
less is ever signalled; a target must have started at or after the reaper; its own shells
and itself are left out; and a process that keeps forking is followed round by round.
"""

from __future__ import annotations

import ast
import signal
from dataclasses import dataclass, field
from pathlib import Path

import pytest

from physgate.oslayer import reaper as reaper_module
from physgate.oslayer.reaper import CANARY_ENV, SHELL, Info, Reaper, RefusedError, run

ME = 500
#: When the reaper started, in microseconds.
T0 = 1_000_000_000
CANARY = 400


@dataclass
class Proc:
    ppid: int
    started_us: int
    inside: bool
    zombie: bool = False
    #: Pids it forks when it is stopped (a survivor that forks while being reaped).
    forks: list[int] = field(default_factory=list)


@dataclass
class FakeKernel:
    """A process table and the sandbox's answer for each process."""

    procs: dict[int, Proc]
    sandboxed_me: bool = True
    sent: list[tuple[int, int]] = field(default_factory=list)
    spare: dict[int, Proc] = field(default_factory=dict)

    def sandboxed(self, pid: int) -> bool:
        assert pid == ME, "the reaper asks this of itself only"
        return self.sandboxed_me

    def pids(self) -> list[int]:
        return sorted(self.procs)

    def info(self, pid: int) -> Info | None:
        proc = self.procs.get(pid)
        if proc is None:
            return None
        return Info(ppid=proc.ppid, zombie=proc.zombie, started_us=proc.started_us)

    def kill(self, pid: int, sig: int) -> None:
        self.sent.append((pid, sig))
        proc = self.procs.get(pid)
        if proc is None:
            raise ProcessLookupError(pid)
        if not proc.inside:
            raise PermissionError(pid)
        if sig == signal.SIGSTOP:
            for child in proc.forks:
                self.procs[child] = self.spare.pop(child)
            proc.forks = []
        if sig == signal.SIGKILL:
            del self.procs[pid]

    def nonzero(self) -> list[tuple[int, int]]:
        return [(pid, sig) for pid, sig in self.sent if sig != 0]


def _table() -> dict[int, Proc]:
    return {
        1: Proc(0, 0, inside=False),
        CANARY: Proc(1, T0 - 10_000_000, inside=False),
        ME: Proc(CANARY, T0, inside=True),
        # The command's own setsid orphan, handed to launchd.
        600: Proc(1, T0 + 5, inside=True),
        # An unrelated process of the user, started after the command: outside the sandbox.
        601: Proc(1, T0 + 6, inside=False),
        # A process inside that is older than the command (cannot happen; guard 3 holds it).
        602: Proc(1, T0 - 1, inside=True),
        # A zombie of the command.
        603: Proc(1, T0 + 7, inside=True, zombie=True),
    }


def test_only_signal_0_goes_out_before_the_guards_held() -> None:
    kernel = FakeKernel(_table())
    reaper = Reaper(kernel, ME, T0)
    for sig in (signal.SIGSTOP, signal.SIGKILL, signal.SIGTERM):
        with pytest.raises(RefusedError, match="before the sandbox and canary guards held"):
            reaper._send(600, sig)  # noqa: SLF001 - the one signal function itself
    assert kernel.sent == []
    assert reaper.reachable(600) is True
    assert reaper.reachable(601) is False
    assert kernel.sent == [(600, 0), (601, 0)]


@pytest.mark.parametrize("pid", [1, 0, -1, -600])
def test_no_pid_of_1_or_less_is_ever_signalled(pid: int) -> None:
    kernel = FakeKernel(_table())
    reaper = Reaper(kernel, ME, T0, armed=True)
    for sig in (0, signal.SIGKILL):
        with pytest.raises(RefusedError, match="launchd, a process group or every process"):
            reaper._send(pid, sig)  # noqa: SLF001
    assert kernel.sent == []


def test_the_members_are_what_the_kernel_lets_it_signal_and_started_after_it() -> None:
    kernel = FakeKernel(_table())
    reaper = Reaper(kernel, ME, T0)
    assert reaper.members(keep=()) == [600]
    # Only the candidates the start time lets through are asked, never itself or launchd;
    # the older canary, the older process inside and the zombie are not.
    probed = {pid for pid, _ in kernel.sent}
    assert probed == {600, 601}
    assert kernel.nonzero() == []


def test_its_own_shells_are_left_out_and_the_walk_stops_outside() -> None:
    table = _table()
    # The reaper's parent is a shell inside the sandbox, its grandparent the canary outside.
    table[ME] = Proc(550, T0, inside=True)
    table[550] = Proc(CANARY, T0 - 2, inside=True)
    kernel = FakeKernel(table)
    reaper = Reaper(kernel, ME, T0)
    assert reaper.own_shells() == {550}
    assert 550 not in reaper.members(keep={550})


def test_an_armed_reap_kills_only_members_and_follows_forks() -> None:
    table = _table()
    table[600].forks = [700]
    kernel = FakeKernel(table, spare={700: Proc(1, T0 + 9, inside=True)})
    reaper = Reaper(kernel, ME, T0, armed=True)
    killed, clean = reaper.reap(keep=(), deadline=float("inf"))
    assert (killed, clean) == (2, True)
    assert {pid for pid, _ in kernel.nonzero()} == {600, 700}
    # The outside process, the older one, the zombie, the canary and itself are untouched.
    assert {1, CANARY, ME, 601, 602, 603} == set(kernel.procs)


def test_a_dry_run_reports_and_sends_signal_0_only() -> None:
    kernel = FakeKernel(_table())
    reaper = Reaper(kernel, ME, T0, dry_run=True, armed=True)
    assert reaper.members(keep=()) == [600]
    with pytest.raises(RefusedError):
        reaper.reap(keep=(), deadline=float("inf"))
    assert kernel.nonzero() == []


@pytest.mark.parametrize(
    ("value", "inside", "said"),
    [
        (None, False, "is not a pid"),
        ("1", False, "is not a pid"),
        ("x", False, "is not a pid"),
        ("999", False, "is gone"),
        (str(CANARY), True, "could be signalled"),
    ],
)
def test_the_fence_is_proven_only_by_a_canary_that_refuses(
    value: str | None, *, inside: bool, said: str
) -> None:
    table = _table()
    table[CANARY].inside = inside
    environ = {} if value is None else {CANARY_ENV: value}
    kernel = FakeKernel(table)
    assert said in str(Reaper(kernel, ME, T0).fence(environ))
    assert kernel.nonzero() == []
    assert Reaper(FakeKernel(_table()), ME, T0).fence({CANARY_ENV: str(CANARY)}) is None


def test_unsandboxed_it_only_runs_the_command_and_signals_nothing(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(reaper_module.sys, "platform", "darwin")
    monkeypatch.setattr(reaper_module.os, "getpid", lambda: ME)
    kernel = FakeKernel(_table(), sandboxed_me=False)
    ran: list[tuple[str, list[str]]] = []
    run(
        ["reaper", "echo 'a b'; exit 3"],
        kernel=kernel,
        environ={CANARY_ENV: str(CANARY)},
        execv=lambda path, argv: ran.append((path, argv)),
    )
    assert ran == [(SHELL, [SHELL, "-c", "echo 'a b'; exit 3"])]
    assert kernel.sent == []


def test_with_the_fence_unproven_it_signals_nothing_but_0(
    monkeypatch: pytest.MonkeyPatch, capfd: pytest.CaptureFixture[str]
) -> None:
    # The command runs for real (``exit 4``); the kernel is the stand-in, with the
    # canary inside the "sandbox", so the fence is not proven and nothing is armed.
    monkeypatch.setattr(reaper_module.sys, "platform", "darwin")
    monkeypatch.setattr(reaper_module.os, "getpid", lambda: ME)
    table = _table()
    table[CANARY].inside = True
    kernel = FakeKernel(table)
    status = run(["reaper", "exit 4"], kernel=kernel, environ={CANARY_ENV: str(CANARY)})
    assert status == 4
    assert kernel.nonzero() == []
    assert (
        "physgate-reaper: not reaping: the canary 400 could be signalled" in capfd.readouterr().err
    )


def test_every_signal_goes_through_the_one_function() -> None:
    # No other call of kill, killpg or a group or broadcast signal anywhere in the module.
    tree = ast.parse(Path(reaper_module.__file__).read_text())
    calls = [
        node
        for node in ast.walk(tree)
        if isinstance(node, ast.Call)
        and isinstance(node.func, ast.Attribute)
        and node.func.attr in {"kill", "killpg", "send_signal", "terminate"}
    ]
    owners = {_enclosing(tree, call) for call in calls}
    assert calls, "the walk must see the kill calls it vets"
    assert owners == {"Kernel.kill", "Reaper._send"}


def _enclosing(tree: ast.Module, target: ast.AST) -> str:
    for cls in [n for n in tree.body if isinstance(n, ast.ClassDef)]:
        for fn in [n for n in cls.body if isinstance(n, ast.FunctionDef)]:
            if any(n is target for n in ast.walk(fn)):
                return f"{cls.name}.{fn.name}"
    for fn in [n for n in tree.body if isinstance(n, ast.FunctionDef)]:
        if any(n is target for n in ast.walk(fn)):
            return fn.name
    return "?"
