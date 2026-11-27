"""The process that makes a role's committed exports again, inside the tool containment.

The change check decides what is made again and what a difference means
(:mod:`physgate.orchestrator.derived`); this module only starts the recorded command inside the
wrapper this machine contains it with, and says how it ended: its exit code (``None`` when it ran
out of time) and the end of what it wrote to its error stream, at most :data:`MAX_SAID_BYTES`.
The change check reads only the first: what the command wrote is under the control of whatever
it ran, so nothing of it is quoted where a session, a reviewer or a person reads. It names no
tool: the argument list is the record's.

The command reads only the recorded roots (and the system's own places; on macOS the system TLS
library's settings file too, :data:`MACOS_TLS_CONFIGURATION`), writes only the folder
made for the call, and has no network: on Linux bubblewrap, on macOS ``sandbox-exec`` with a
profile generated for the call and written outside that folder. It is withheld, each whole, every
place it is given as withheld (the dispatcher's, at least what every role session of the run is
withheld), wherever such a place lies inside what it reads; a runner given none refuses. When
the wrapper's rules cannot be built, a place it reads lying inside a withheld one among the
causes, the refusal says so by kind and names no place: a withheld place is the protected
material's.

The wrapper is named here, in code (:data:`WRAPPER`), and found on the orchestrator's own search
path, on its absolute folders only: a relative folder resolves against the current directory,
which may be a role's tree, so nothing of a role's tree can name the wrapper.

**Bounds.** The error stream is read through a pipe as the program writes it, its end kept and
its length counted; past :data:`MAX_ERROR_BYTES` the program is ended and
:class:`RegenerationBoundError` raised. No file the program or anything it starts writes may
grow past :data:`MAX_WRITTEN_BYTES` and one byte: the operating system holds that
(``RLIMIT_FSIZE``, set by a launcher before the wrapper starts, and inherited by everything
under it), for a file deleted while open as for any other, and a program the limit stops is
refused. What lies in the call's folder is counted as well, every :data:`POLL_S` seconds and
once more at the end, a second check: past :data:`MAX_WRITTEN_BYTES` in all, or a folder that
cannot be listed or a file that cannot be looked at, refuses. What the count cannot see is the
sum of several files deleted while open, each under the limit; a size-capped folder in memory
inside the wrapper would hold that, and is not made here.

**Its own session.** The program starts in a session of its own, with no controlling
terminal, and when it ends, times out or passes a bound its whole process group is killed:
nothing it started goes on writing into a folder that is being removed. After that the error
stream must close within :data:`DRAIN_GRACE_S` seconds, and never later than the call's
deadline and that grace: something still holding it open left the group, and the call is
refused, never waited for. On Linux nothing can leave: bubblewrap's ``--unshare-pid`` makes the
program the first process of a namespace of its own, and ``--die-with-parent`` kills it when
the wrapper dies, which takes down every process in that namespace, a new session's included.
On macOS a process that starts a session of its own and closes its error stream is not seen
and can outlive the call.
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
#: The one file of the system's configuration the command reads on macOS, beside the system's
#: libraries: the system TLS library's own settings (LibreSSL), read when a program starts that
#: library. KiCad's command line starts it at every start, through curl, before it reads its
#: arguments. Denied, the library ends the program from inside that start, and KiCad's handler
#: at the end then spins for ever on the lock that start still holds: the command never ends and
#: every schematic's exports would be refused as timed out. A session's own commands read it
#: (their layer denies reads by name, and names none of the system's settings); the command reads
#: it and nothing else beneath ``/private/etc`` but the clock. A read root, so a withheld place
#: that holds it refuses the call as a root inside one would. Linux's library reads no settings
#: file it does not find, and the Linux wrapper is left as it is.
MACOS_TLS_CONFIGURATION = "/private/etc/ssl/openssl.cnf"
#: The most of a regeneration's error stream that is kept: its end.
MAX_SAID_BYTES = 4096
#: The most a regeneration may write to its error stream; past it, it is ended and refused.
MAX_ERROR_BYTES = 1_000_000
#: The most bytes the call's folder may hold, its configuration and temporary files included;
#: past it, the program is ended and refused. A KiCad set writes well under a megabyte.
MAX_WRITTEN_BYTES = 256_000_000
#: How often, in seconds, the call's folder is counted while the program runs.
POLL_S = 0.2
#: The seconds the error stream has to close once the program's group is ended.
DRAIN_GRACE_S = 2.0
#: The most read from the error stream at once.
_CHUNK = 65536
#: The launcher: the file size limit set, the signal that enforces it at its default (Python
#: ignores it at start), then the wrapper in its place, by absolute path, with nothing searched.
_LIMITED = (
    "import os, resource, signal, sys\n"
    "size = int(sys.argv[1])\n"
    "resource.setrlimit(resource.RLIMIT_FSIZE, (size, size))\n"
    "signal.signal(signal.SIGXFSZ, signal.SIG_DFL)\n"
    "os.execv(sys.argv[2], sys.argv[2:])\n"
)


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


#: What gives the places a regeneration may not read, each whole, at the time it runs.
Withheld = Callable[[], Sequence[str]]
#: What a refusal says when the wrapper's rules cannot be built: never the containment's own
#: words, which name the place a root of the command lies inside, a withheld one among them.
UNCONTAINED = (
    "the command cannot be contained as the session's policy says: a place it reads or runs "
    "lies inside one withheld from the run's sessions, or cannot be written into the wrapper's "
    "rules"
)


def default_runner(
    *,
    platform: str = sys.platform,
    search_path: str | None = None,
    withheld: Withheld | None = None,
) -> Runner:
    """The change check's runner: :func:`contained_runner` with the wrapper this machine has.

    ``search_path`` is the orchestrator's own (its ``PATH`` when ``None``); ``withheld`` gives
    the places the command may not read (``None``: none are known, and every regeneration is
    refused).
    """
    path = os.environ.get("PATH", "") if search_path is None else search_path
    found = wrapper_on(path) if platform.startswith("linux") else None
    return contained_runner(platform=platform, bwrap=found, withheld=withheld)


def contained_runner(
    *,
    platform: str = sys.platform,
    bwrap: str | None = None,
    withheld: Withheld | None = None,
) -> Runner:
    """A runner that starts the command inside the tool containment.

    On Linux the wrapper at ``bwrap`` (``None``: there is none, and every regeneration is
    refused); on macOS a generated Seatbelt profile. ``withheld`` gives the places the command
    may not read, each whole, asked at every call (``None``: none are known, and every
    regeneration is refused; an empty answer is a run that withholds nothing).

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
            if withheld is None:
                msg = "no places withheld from the run's sessions are given to the regeneration"
                raise ContainmentError(msg)
            denied = tuple(withheld())
            if platform.startswith("linux"):
                if bwrap is None:
                    msg = "no bubblewrap on this machine contains the regeneration"
                    raise ContainmentError(msg)
                try:
                    options = bwrap_args(read_denied=denied, server_dir=str(work), read_roots=roots)
                except ContainmentError:
                    raise ContainmentError(UNCONTAINED) from None
                command = [bwrap, *options, "--", *argv]
            elif platform == "darwin":
                try:
                    rules = seatbelt_profile(
                        read_denied=denied,
                        server_dir=str(work),
                        devices=board_devices(platform),
                        command=argv[0],
                        exec_roots=roots,
                        read_roots=(*roots, MACOS_TLS_CONFIGURATION),
                    )
                except ContainmentError:
                    raise ContainmentError(UNCONTAINED) from None
                profiles = tempfile.mkdtemp(prefix="physgate-derived-profile-")
                profile = Path(profiles) / "regenerate.sb"
                profile.write_text(rules, encoding="utf-8")
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
            limit = str(MAX_WRITTEN_BYTES + 1)
            child = subprocess.Popen(  # noqa: S603 - the recorded command, inside its wrapper
                [sys.executable, "-I", "-c", _LIMITED, limit, *command],
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
        # Nothing of the group is left to write, so the stream closes: what remains is read,
        # for a short grace and never past the deadline and that grace.
        drained = min(deadline, time.monotonic()) + DRAIN_GRACE_S
        while stream.open:
            left = drained - time.monotonic()
            if left <= 0:
                msg = (
                    "something the regeneration started left its process group and held its "
                    "error stream open after it ended"
                )
                raise RegenerationBoundError(msg)
            if watch.select(min(left, POLL_S)):
                stream.take()
            _hold_bounds(stream, work)
    _hold_bounds(stream, work)
    if child.returncode == -signal.SIGXFSZ:
        msg = f"the regeneration was stopped writing a file past {MAX_WRITTEN_BYTES} bytes"
        raise RegenerationBoundError(msg)
    return child.returncode, stream.tail.decode("utf-8", errors="replace")


def _hold_bounds(stream: _Stream, work: Path) -> None:
    if stream.count > MAX_ERROR_BYTES:
        msg = f"the regeneration wrote more than {MAX_ERROR_BYTES} bytes to its error stream"
        raise RegenerationBoundError(msg)
    if _bytes_in(work) > MAX_WRITTEN_BYTES:
        msg = f"the regeneration wrote more than {MAX_WRITTEN_BYTES} bytes into its folder"
        raise RegenerationBoundError(msg)


def _uncounted(error: OSError) -> None:
    """A folder of the call that cannot be listed: what it holds cannot be counted, so refused."""
    if isinstance(error, FileNotFoundError):
        return  # removed since its parent was listed: it holds nothing
    msg = f"a folder the regeneration wrote cannot be counted ({type(error).__name__})"
    raise RegenerationBoundError(msg)


def _bytes_in(folder: Path) -> int:
    """The bytes the files beneath ``folder`` hold, no link followed.

    A file or folder removed since it was listed holds nothing and counts none; one that
    cannot be listed or looked at for any other reason refuses, never counted as empty.
    """
    total = 0
    for top, _folders, files in os.walk(folder, onerror=_uncounted):
        for name in files:
            try:
                total += os.lstat(os.path.join(top, name)).st_size
            except FileNotFoundError:
                continue
            except OSError as exc:
                _uncounted(exc)
    return total


def _end(child: subprocess.Popen[bytes]) -> None:
    """Kill ``child``'s whole process group, and reap ``child``."""
    with contextlib.suppress(ProcessLookupError, PermissionError):
        os.killpg(child.pid, signal.SIGKILL)
    with contextlib.suppress(ProcessLookupError):
        child.kill()
    child.wait()
