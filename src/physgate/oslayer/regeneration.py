"""The process that makes a role's committed exports again, inside the tool containment.

The change check decides what is made again and what a difference means
(:mod:`physgate.orchestrator.derived`); this module only starts the recorded command inside the
wrapper this machine contains it with, and says how it ended: its exit code (``None`` when it ran
out of time) and the end of what it wrote to its error stream, at most :data:`MAX_SAID_BYTES`.
It names no tool: the argument list is the record's.

The command reads only the recorded roots (and the system's own places), writes only the folder
made for the call, and has no network: on Linux bubblewrap, on macOS ``sandbox-exec`` with a
profile generated for the call and written outside that folder.

The wrapper is named here, in code (:data:`WRAPPER`), and found on the orchestrator's own search
path, on its absolute folders only: a relative folder resolves against the current directory,
which may be a role's tree, so nothing of a role's tree can name the wrapper.

**Bounds.** The error stream is read through a pipe as the program writes it, its end kept and
its length counted; past :data:`MAX_ERROR_BYTES` the program is ended and
:class:`RegenerationBoundError` raised. What lies in the call's folder is counted every
:data:`POLL_S` seconds and once more at the end; past :data:`MAX_WRITTEN_BYTES` the same. So
neither the error stream nor the folder can fill a disk or this process's memory.

**Its own session.** The program starts in a session of its own, with no controlling
terminal, and when it ends, times out or passes a bound its whole process group is killed:
nothing it started goes on writing into a folder that is being removed.
"""

from __future__ import annotations

import contextlib
import os
import selectors
import shutil
import signal
import subprocess
import sys
import tempfile
import time
from collections.abc import Callable, Mapping, Sequence
from pathlib import Path

from physgate.oslayer.containment import (
    SANDBOX_EXEC,
    ContainmentError,
    bwrap_args,
    seatbelt_profile,
)
from physgate.oslayer.policy import board_devices

#: The Linux wrapper, by name; found on the search path's absolute folders only.
WRAPPER = "bwrap"
#: The most of a regeneration's error stream that is kept: its end.
MAX_SAID_BYTES = 4096
#: The most a regeneration may write to its error stream; past it, it is ended and refused.
MAX_ERROR_BYTES = 1_000_000
#: The most bytes the call's folder may hold, its configuration and temporary files included;
#: past it, the program is ended and refused. A KiCad set writes well under a megabyte.
MAX_WRITTEN_BYTES = 256_000_000
#: How often, in seconds, the call's folder is counted while the program runs.
POLL_S = 0.2
#: The most read from the error stream at once.
_CHUNK = 65536


class RegenerationBoundError(RuntimeError):
    """A regeneration passed a bound this module holds; the program was ended."""

#: What runs one regeneration: the argument list, the folder made for it, its environment, the
#: seconds it is given and the recorded roots; its exit code (``None`` when it timed out) and the
#: end of its error stream.
Runner = Callable[
    [Sequence[str], Path, Mapping[str, str], float, Sequence[str]], tuple[int | None, str]
]


def wrapper_on(search_path: str) -> str | None:
    """The wrapper on ``search_path``'s absolute folders, or ``None`` when none holds it."""
    folders = [folder for folder in search_path.split(os.pathsep) if os.path.isabs(folder)]
    if not folders:
        return None
    return shutil.which(WRAPPER, path=os.pathsep.join(folders))


def default_runner(*, platform: str = sys.platform, search_path: str | None = None) -> Runner:
    """The change check's runner: :func:`contained_runner` with the wrapper this machine has.

    ``search_path`` is the orchestrator's own (its ``PATH`` when ``None``).
    """
    path = os.environ.get("PATH", "") if search_path is None else search_path
    found = wrapper_on(path) if platform.startswith("linux") else None
    return contained_runner(platform=platform, bwrap=found)


def contained_runner(*, platform: str = sys.platform, bwrap: str | None = None) -> Runner:
    """A runner that starts the command inside the tool containment.

    On Linux the wrapper at ``bwrap`` (``None``: there is none, and every regeneration is
    refused); on macOS a generated Seatbelt profile.

    The runner raises :class:`~physgate.oslayer.containment.ContainmentError` when the command
    cannot be contained here, then nothing was started; :class:`RegenerationBoundError` when
    the program passed a bound, then it was ended; and :class:`OSError` when it could not be
    started (a wrapper program gone among them).
    """

    def run(
        argv: Sequence[str],
        work: Path,
        env: Mapping[str, str],
        timeout_s: float,
        roots: Sequence[str],
    ) -> tuple[int | None, str]:
        profiles: str | None = None
        try:
            if platform.startswith("linux"):
                if bwrap is None:
                    msg = "no bubblewrap on this machine contains the regeneration"
                    raise ContainmentError(msg)
                options = bwrap_args(read_denied=(), server_dir=str(work), read_roots=roots)
                command = [bwrap, *options, "--", *argv]
            elif platform == "darwin":
                profiles = tempfile.mkdtemp(prefix="physgate-derived-profile-")
                profile = Path(profiles) / "regenerate.sb"
                profile.write_text(
                    seatbelt_profile(
                        read_denied=(),
                        server_dir=str(work),
                        devices=board_devices(platform),
                        command=argv[0],
                        exec_roots=roots,
                        read_roots=roots,
                    ),
                    encoding="utf-8",
                )
                command = [SANDBOX_EXEC, "-f", str(profile), *argv]
            else:
                msg = f"no wrapper contains the regeneration on {platform}"
                raise ContainmentError(msg)
            return _run(command, work, env, timeout_s)
        finally:
            if profiles is not None:
                shutil.rmtree(profiles, ignore_errors=True)

    return run


class _Stream:
    """An error stream as it is read: its end, how many bytes it held, and whether it is open."""

    def __init__(self, reader: int) -> None:
        self.reader = reader
        self.tail = b""
        self.count = 0
        self.open = True

    def take(self) -> None:
        """Read what the stream holds now; an empty read is its end."""
        chunk = os.read(self.reader, _CHUNK)
        self.open = bool(chunk)
        self.count += len(chunk)
        self.tail = (self.tail + chunk)[-MAX_SAID_BYTES:]


def _run(
    command: Sequence[str], work: Path, env: Mapping[str, str], timeout_s: float
) -> tuple[int | None, str]:
    deadline = time.monotonic() + timeout_s
    # The error stream comes through a pipe and is read as it is written: its end is kept and
    # its length counted, so a program writing much holds no memory and no disk here.
    reader, writer = os.pipe()
    try:
        try:
            child = subprocess.Popen(  # noqa: S603 - the recorded command, inside its wrapper
                list(command),
                cwd=work,
                env=dict(env),
                stdin=subprocess.DEVNULL,
                stdout=subprocess.DEVNULL,
                stderr=writer,
                start_new_session=True,
            )
        finally:
            os.close(writer)
        try:
            return _watched(child, _Stream(reader), work, deadline)
        finally:
            # However the call ends, its whole group ends with it.
            _end(child)
    finally:
        os.close(reader)


def _watched(
    child: subprocess.Popen[bytes], stream: _Stream, work: Path, deadline: float
) -> tuple[int | None, str]:
    """Read ``stream`` until ``child`` ends or runs out of time, holding the bounds."""
    with selectors.DefaultSelector() as watch:
        watch.register(stream.reader, selectors.EVENT_READ)
        while child.poll() is None:
            left = deadline - time.monotonic()
            if left <= 0:
                return None, ""
            if not stream.open:
                with contextlib.suppress(subprocess.TimeoutExpired):
                    child.wait(min(left, POLL_S))
            elif watch.select(min(left, POLL_S)):
                stream.take()
            _hold_bounds(stream, work)
        _end(child)
        # Nothing of the group is left to write, so the stream closes: what remains is read.
        while stream.open and watch.select(POLL_S):
            stream.take()
            _hold_bounds(stream, work)
    _hold_bounds(stream, work)
    return child.returncode, stream.tail.decode("utf-8", errors="replace")


def _hold_bounds(stream: _Stream, work: Path) -> None:
    if stream.count > MAX_ERROR_BYTES:
        msg = f"the regeneration wrote more than {MAX_ERROR_BYTES} bytes to its error stream"
        raise RegenerationBoundError(msg)
    if _bytes_in(work) > MAX_WRITTEN_BYTES:
        msg = f"the regeneration wrote more than {MAX_WRITTEN_BYTES} bytes into its folder"
        raise RegenerationBoundError(msg)


def _bytes_in(folder: Path) -> int:
    """The bytes the files beneath ``folder`` hold, no link followed; what is gone counts none."""
    total = 0
    for top, _folders, files in os.walk(folder):
        for name in files:
            with contextlib.suppress(OSError):
                total += os.lstat(os.path.join(top, name)).st_size
    return total


def _end(child: subprocess.Popen[bytes]) -> None:
    """Kill ``child``'s whole process group, and reap ``child``."""
    with contextlib.suppress(ProcessLookupError, PermissionError):
        os.killpg(child.pid, signal.SIGKILL)
    with contextlib.suppress(ProcessLookupError):
        child.kill()
    child.wait()
