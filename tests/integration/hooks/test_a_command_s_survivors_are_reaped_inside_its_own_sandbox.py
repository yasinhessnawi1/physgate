"""On macOS, the survivor reaper stops what its command left running, and nothing else.

A disposable fixture, without Claude Code: the reaper runs as a command's first process
inside a ``sandbox-exec`` of its own, with the process rules Claude Code 2.1.301 writes into
every command's profile. Beside it run two of the test's own sleepers that the reaper must
never reach: one unsandboxed, one in a sibling sandbox with the identical profile. Every
process here is the test's own. The sleepers outside are ended by the test through the
``Popen`` it holds, and nothing else is ever signalled from outside a sandbox.

Measured with this fixture first (21.10.2026, macOS 26.2): from inside the sandbox a signal
to either outside sleeper fails with EPERM, and one to the sandbox's own orphan is delivered.
"""

from __future__ import annotations

import os
import shlex
import signal
import subprocess
import sys
import time
from collections.abc import Iterator
from dataclasses import dataclass
from pathlib import Path

import pytest

from physgate.oslayer import reaper as reaper_module
from physgate.oslayer.reaper import CANARY_ENV, TAG

pytestmark = [
    pytest.mark.integration,
    pytest.mark.skipif(sys.platform != "darwin", reason="the reaper runs on macOS only"),
]

#: The process rules of Claude Code 2.1.301's per-command profile, with reads open and
#: writes to the fixture's own directory.
PROFILE = """\
(version 1)
(deny default)
(allow process-exec)
(allow process-fork)
(allow process-info* (target same-sandbox))
(allow signal (target same-sandbox))
(allow mach-priv-task-port (target same-sandbox))
(allow file-read*)
(allow file-write* (subpath "{root}"))
(allow file-write* (literal "/dev/null"))
(allow file-ioctl)
(allow sysctl-read)
(allow mach-lookup)
(allow ipc-posix-shm)
"""

PYTHON = str(Path(sys.base_prefix) / "bin" / "python3")
REAPER = reaper_module.__file__


def spawn_lingerer(name: str, seconds: float, *, forking: bool = False) -> str:
    """Shell text: a python that starts a sleeper in a session of its own and returns.

    ``forking`` makes the lingerer itself a loop that starts a new session-leading child
    every 50 ms, as a survivor that forks while it is being reaped would.
    """
    if forking:
        body = (
            "import os,time\\n"
            f"end=time.time()+{seconds}\\n"
            "while time.time()<end:\\n"
            "    if os.fork()==0:\\n"
            "        os.setsid(); time.sleep(0.5); os._exit(0)\\n"
            "    time.sleep(0.05)\\n"
        )
        argv = f"[sys.executable,'-c','{body}']"
    else:
        argv = f"['/bin/sleep','{seconds}']"
    return (
        f'{PYTHON} -I -c "import subprocess,sys;p=subprocess.Popen({argv},'
        "start_new_session=True,stdin=subprocess.DEVNULL,stdout=subprocess.DEVNULL,"
        f"stderr=subprocess.DEVNULL);open('{name}','w').write(str(p.pid))\""
    )


def alive(pid: int) -> bool:
    """Whether ``pid`` exists, asked with signal 0 (which delivers nothing)."""
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    except PermissionError:
        return True
    return True


def gone_within(pid: int, seconds: float) -> bool:
    end = time.monotonic() + seconds
    while time.monotonic() < end:
        if not alive(pid):
            return True
        time.sleep(0.05)
    return not alive(pid)


@dataclass
class Fixture:
    root: Path
    sandbox: list[str]
    unsandboxed: subprocess.Popen[bytes]
    sibling: subprocess.Popen[bytes]

    def reaper(
        self, command: str, *extra: str, canary: int | None = None, sandboxed: bool = True
    ) -> subprocess.Popen[str]:
        env = {"PATH": "/usr/bin:/bin"}
        env[CANARY_ENV] = str(os.getpid() if canary is None else canary)
        argv = [PYTHON, "-I", "-S", REAPER, *extra, command]
        return subprocess.Popen(  # noqa: S603 - the test's own fixture
            [*self.sandbox, *argv] if sandboxed else argv,
            cwd=self.root,
            env=env,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
        )

    def pid(self, name: str) -> int:
        return int((self.root / name).read_text())

    def outside_untouched(self) -> None:
        assert self.unsandboxed.poll() is None, "the unsandboxed sleeper was reached"
        assert self.sibling.poll() is None, "the sibling sandbox's sleeper was reached"


@pytest.fixture
def fixture(tmp_path: Path) -> Iterator[Fixture]:
    root = tmp_path.resolve()
    sandbox = ["/usr/bin/sandbox-exec", "-p", PROFILE.format(root=root)]
    unsandboxed = subprocess.Popen(["/bin/sleep", "60"])  # noqa: S607
    sibling = subprocess.Popen([*sandbox, "/bin/sleep", "60"])  # noqa: S603
    time.sleep(0.3)
    try:
        yield Fixture(root, sandbox, unsandboxed, sibling)
    finally:
        # The test's own two sleepers, by the handles it holds.
        for proc in (unsandboxed, sibling):
            proc.kill()
            proc.wait()


def test_a_dry_run_names_only_the_command_s_own_orphan(fixture: Fixture) -> None:
    run = fixture.reaper(spawn_lingerer("orphan.pid", 6) + "; exit 3", "--dry-run")
    out, err = run.communicate(timeout=30)
    orphan = fixture.pid("orphan.pid")
    assert run.returncode == 3
    assert f"{TAG} dry run: fence held; would signal [{orphan}]; own shells []" in err
    # Both outside sleepers were alive while it chose, so leaving them out was a choice.
    fixture.outside_untouched()
    assert alive(orphan), "a dry run signalled its orphan"
    assert gone_within(orphan, 10)


def test_every_survivor_is_stopped_and_nothing_outside_is_reached(fixture: Fixture) -> None:
    command = "; ".join(
        [
            spawn_lingerer("plain.pid", 30),
            # A double fork: the intermediate shell and python both end before the reaper.
            "( " + spawn_lingerer("double.pid", 30) + " & ) ; sleep 0.3",
            spawn_lingerer("forking.pid", 30, forking=True),
            "sleep 0.3; echo done",
        ]
    )
    run = fixture.reaper(command)
    out, err = run.communicate(timeout=30)
    assert (run.returncode, out) == (0, "done\n")
    pids = [fixture.pid(name) for name in ("plain.pid", "double.pid", "forking.pid")]
    assert not [pid for pid in pids if alive(pid)]
    stopped = [line for line in err.splitlines() if line.startswith(f"{TAG} stopped ")]
    assert len(stopped) == 1, err
    assert int(stopped[0].split()[2]) >= len(pids)
    assert "still running" not in err
    fixture.outside_untouched()


def test_unsandboxed_it_runs_the_command_and_signals_nothing(fixture: Fixture) -> None:
    # As a hook command, which the prefix wraps too, or a call by hand outside a sandbox.
    run = fixture.reaper(spawn_lingerer("hook.pid", 2) + "; exit 7", sandboxed=False)
    _, err = run.communicate(timeout=30)
    lingerer = fixture.pid("hook.pid")
    assert (run.returncode, err) == (7, "")
    assert alive(lingerer), "an unsandboxed reaper signalled something"
    assert gone_within(lingerer, 10)  # it ends on its own
    fixture.outside_untouched()


def test_without_a_canary_it_signals_nothing(fixture: Fixture) -> None:
    run = fixture.reaper(spawn_lingerer("absent.pid", 2) + "; exit 4", canary=0)
    _, err = run.communicate(timeout=30)
    lingerer = fixture.pid("absent.pid")
    assert run.returncode == 4
    assert f"{TAG} not reaping: {CANARY_ENV} is not a pid ('0')" in err
    assert alive(lingerer)
    assert gone_within(lingerer, 10)
    fixture.outside_untouched()


def test_a_canary_it_can_signal_proves_no_fence_and_it_signals_nothing(fixture: Fixture) -> None:
    # The canary is a sleeper started inside the reaper's own sandbox, just before it: one
    # the kernel lets it signal, so the fence is not what was measured.
    reaper = f"{PYTHON} -I -S {REAPER}"
    command = spawn_lingerer("open.pid", 2) + "; exit 4"
    shell = f"sleep 2 & {CANARY_ENV}=$! exec {reaper} {shlex.quote(command)}"
    run = subprocess.Popen(  # noqa: S603 - the test's own fixture
        [*fixture.sandbox, "/bin/sh", "-c", shell],
        cwd=fixture.root,
        env={"PATH": "/usr/bin:/bin"},
        stderr=subprocess.PIPE,
        text=True,
    )
    _, err = run.communicate(timeout=30)
    lingerer = fixture.pid("open.pid")
    assert run.returncode == 4
    assert "could be signalled from inside the sandbox" in err
    assert alive(lingerer)
    assert gone_within(lingerer, 10)
    fixture.outside_untouched()


def test_a_canary_outside_the_command_s_sandbox_refuses_it(fixture: Fixture) -> None:
    # The sibling sandbox's sleeper is outside this command's sandbox: the fence holds.
    run = fixture.reaper(spawn_lingerer("held.pid", 30) + "; exit 4", canary=fixture.sibling.pid)
    _, err = run.communicate(timeout=30)
    assert run.returncode == 4
    assert "not reaping" not in err
    assert not alive(fixture.pid("held.pid"))
    fixture.outside_untouched()


def test_claude_code_s_sigterm_is_answered_by_reaping_within_its_grace(fixture: Fixture) -> None:
    run = fixture.reaper(spawn_lingerer("term.pid", 30) + "; sleep 30")
    deadline = time.monotonic() + 10
    while not (fixture.root / "term.pid").exists() and time.monotonic() < deadline:
        time.sleep(0.05)
    started = time.monotonic()
    run.send_signal(signal.SIGTERM)  # the test's own reaper, as Claude Code would
    run.communicate(timeout=10)
    took = time.monotonic() - started
    assert run.returncode == 128 + signal.SIGTERM
    assert took < 1.5, f"took {took:.2f} s; Claude Code sends SIGKILL after 1.5 s"
    assert not alive(fixture.pid("term.pid"))
    fixture.outside_untouched()


def test_a_command_that_kills_its_reaper_keeps_its_survivor(fixture: Fixture) -> None:
    # The residual, held here so a change in it is seen: the reaper shares the command's
    # sandbox, so the command can kill it, and its survivor then lives on. Claude Code
    # reports that death as an ordinary ``Exit code 1`` (measured on 2.1.301).
    run = fixture.reaper(spawn_lingerer("tamper.pid", 2) + "; kill -9 $PPID")
    _, err = run.communicate(timeout=30)
    assert run.returncode == -signal.SIGKILL
    assert TAG not in err
    lingerer = fixture.pid("tamper.pid")
    assert alive(lingerer)
    assert gone_within(lingerer, 10)
    fixture.outside_untouched()
