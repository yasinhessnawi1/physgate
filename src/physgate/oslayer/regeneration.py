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
"""

from __future__ import annotations

import os
import shutil
import subprocess
import sys
import tempfile
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
    cannot be contained here; then nothing was started.
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


def _run(
    command: Sequence[str], work: Path, env: Mapping[str, str], timeout_s: float
) -> tuple[int | None, str]:
    # The error stream goes to a file outside the call's folder, so a program writing much
    # holds no memory here; only its end is read back.
    with tempfile.TemporaryFile() as said:
        try:
            done = subprocess.run(  # noqa: S603 - the recorded command, inside its wrapper
                list(command),
                cwd=work,
                env=dict(env),
                stdin=subprocess.DEVNULL,
                stdout=subprocess.DEVNULL,
                stderr=said,
                timeout=timeout_s,
                check=False,
            )
        except subprocess.TimeoutExpired:
            return None, ""
        size = said.seek(0, os.SEEK_END)
        said.seek(max(0, size - MAX_SAID_BYTES))
        return done.returncode, said.read().decode("utf-8", errors="replace")
