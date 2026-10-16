"""A review session is stopped, not left running unobserved, when the process table fails.

The process table now raises when ``ps`` fails rather than reading as empty. A review session
spawned just before that would otherwise run on to its own end with nothing watching it: right
after the spawn with no process record at all, or in the middle of the wait. The reviewer stops
its own session, an unreaped child of its own whose pid is still its own, before it raises.
"""

from __future__ import annotations

import json
import stat
import subprocess
import sys
from collections.abc import Callable
from pathlib import Path
from types import SimpleNamespace
from typing import Any, cast

import pytest
from test_a_review_session_leaves_nothing_running_however_it_ends import _reviewer

from physgate.orchestrator import dispatch, processes
from physgate.orchestrator.dispatch import Installed
from physgate.reviewers.packet import WORKTREE_NAME, Packet

#: The stand-in review session: a flag once it runs, then a wait it is not let finish.
SESSION = r"""
import sys, time
open(sys.argv[1], "w").close()
time.sleep(60)
"""


class FailingPs:
    """``subprocess`` for one module: ``ps`` fails once ``when`` holds; all else runs."""

    SubprocessError = subprocess.SubprocessError
    TimeoutExpired = subprocess.TimeoutExpired
    CompletedProcess = subprocess.CompletedProcess

    def __init__(self, when: Callable[[], bool]) -> None:
        self.when = when

    def run(self, argv: list[str], **kwargs: Any) -> subprocess.CompletedProcess[str]:  # noqa: ANN401
        if argv[0] != "ps" or not self.when():
            return subprocess.run(argv, **kwargs)  # noqa: S603, PLW1510
        return subprocess.CompletedProcess(argv, 1, stdout="", stderr="")


class Spawned:
    """``subprocess`` for the reviewer: every process it spawns, kept to look at afterwards."""

    def __init__(self) -> None:
        self.processes: list[subprocess.Popen[bytes]] = []

    def __getattr__(self, name: str) -> Any:  # noqa: ANN401
        return getattr(subprocess, name)

    def Popen(self, *args: Any, **kwargs: Any) -> subprocess.Popen[bytes]:  # noqa: ANN401, N802
        process: subprocess.Popen[bytes] = subprocess.Popen(*args, **kwargs)  # noqa: S603
        self.processes.append(process)
        return process


@pytest.mark.parametrize("when", ["at_the_spawn", "during_the_wait"])
def test_a_review_session_is_stopped_when_the_process_table_cannot_be_read(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, when: str
) -> None:
    flag = tmp_path / "running"
    binary = tmp_path / "bin" / "claude"
    binary.parent.mkdir()
    binary.write_text(
        f"#!{sys.executable}\nimport sys\nsys.argv = [sys.argv[0], {str(flag)!r}]\n" + SESSION
    )
    binary.chmod(binary.stat().st_mode | stat.S_IXUSR)
    read = tmp_path / "rs" / "review" / "read"
    (read / WORKTREE_NAME).mkdir(parents=True)
    sdir = tmp_path / "rs" / "review" / "session"
    sdir.mkdir()
    reviewer = _reviewer(tmp_path, binary, wall_clock_s=30.0)
    spawned = Spawned()
    monkeypatch.setattr(dispatch, "subprocess", spawned)
    fails = (lambda: True) if when == "at_the_spawn" else flag.exists
    monkeypatch.setattr(processes, "subprocess", FailingPs(fails))
    installed = Installed(settings="s", config="c", spawn_args=(), spawn_env={})
    packet = cast(Packet, SimpleNamespace(read_root=str(read)))
    try:
        with pytest.raises(processes.ProcessTableError):
            reviewer._spawn(packet, sdir, installed, "sid", prompt="p", schema={})
        (process,) = spawned.processes
        # Stopped and reaped by the reviewer itself, before it raised.
        assert process.returncode is not None
        if when == "during_the_wait":
            # Its process record was on disk before the first poll, for a resume to find.
            assert json.loads((sdir / "process.json").read_text())["pid"] == process.pid
    finally:
        for process in spawned.processes:
            if process.poll() is None:
                process.kill()
                process.wait()


#: A stand-in review session that, before it exits, plants a link where its end record goes.
PLANTER = r"""
import os, sys
os.symlink(sys.argv[2], os.path.join(sys.argv[1], "ended.json"))
"""


def test_a_review_s_end_record_is_never_written_through_a_link_its_session_planted(
    tmp_path: Path,
) -> None:
    sdir = tmp_path / "rs" / "review" / "session"
    sdir.mkdir(parents=True)
    victim = tmp_path / "elsewhere.txt"
    victim.write_text("not the review's\n")
    binary = tmp_path / "bin" / "claude"
    binary.parent.mkdir()
    binary.write_text(
        f"#!{sys.executable}\nimport sys\nsys.argv = [sys.argv[0], {str(sdir)!r}, "
        f"{str(victim)!r}]\n" + PLANTER
    )
    binary.chmod(binary.stat().st_mode | stat.S_IXUSR)
    read = tmp_path / "rs" / "review" / "read"
    (read / WORKTREE_NAME).mkdir(parents=True)
    reviewer = _reviewer(tmp_path, binary, wall_clock_s=30.0)
    installed = Installed(settings="s", config="c", spawn_args=(), spawn_env={})
    packet = cast(Packet, SimpleNamespace(read_root=str(read)))
    reviewer._spawn(packet, sdir, installed, "sid", prompt="p", schema={})
    assert victim.read_text() == "not the review's\n"
    assert not (sdir / "ended.json").is_symlink()
    assert json.loads((sdir / "ended.json").read_text())["exit"] == 0
