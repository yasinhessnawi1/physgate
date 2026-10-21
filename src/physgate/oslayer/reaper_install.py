"""The survivor reaper's place in a session: where it is written, how it is named, its canary.

:mod:`physgate.oslayer.reaper` must run inside each shell command's own sandbox, as the
command's first process. Claude Code 2.1.301 applies ``CLAUDE_CODE_SHELL_PREFIX`` to the
command string before it wraps that in ``sandbox-exec`` (measured 21.10.2026), so the
prefix names it. It also wraps every hook command, which runs unsandboxed. The prefix is
therefore a small shell front: when signal 0 to the canary is delivered **and** the session's
settings file can be read (the sandbox read-denies it to every command), this process is a
hook command outside the sandbox, and the front only runs it with the hook shell. Otherwise
it hands over to the reaper, which checks its three guards itself and says why it signals
nothing when they fail: a sandboxed command whose canary takes its signal is never let
through silently.

Both files are written into the session's settings directory, which no session writes, and
that directory is opened to the sandbox for reads (``os_layer_readable``): the harness
checkout, where the package lives, is read-denied to a session's shell. The reaper runs
under the base interpreter, which the session's shell can read.

The canary is the session's Claude Code: whoever spawns it sets ``PHYSGATE_REAPER_CANARY``
to its pid, with a shell that exports its own pid and then replaces itself with the binary
(:data:`CANARY_EXPORT`).
"""

from __future__ import annotations

import os
import sys
from pathlib import Path

from physgate.oslayer.reaper import CANARY_ENV, SHELL

#: The shell Claude Code runs a hook command with (``spawn`` with ``shell: true``), which
#: the front keeps for the hook commands it passes through.
HOOK_SHELL = "/bin/sh"

#: The directory, inside the session's settings directory, that holds the reaper.
DIRNAME = "reaper"
#: The front's file name: what ``CLAUDE_CODE_SHELL_PREFIX`` names.
FRONT = "reaper"
#: The reaper's file name beside it.
PROGRAM = "reaper.py"

#: Shell text that exports the shell's own pid as the canary. A spawner puts it before an
#: ``exec`` of the binary, so the pid is the session's Claude Code.
CANARY_EXPORT = f"{CANARY_ENV}=$$; export {CANARY_ENV}; "

_FRONT_TEXT = """\
#!/bin/sh
# Written by physgate (oslayer/reaper_install.py) for one session: CLAUDE_CODE_SHELL_PREFIX.
# The only signal this front sends is 0 to the canary, the session's Claude Code. Delivered,
# with the session's settings readable (which the sandbox denies every command), means a
# hook command outside the sandbox: it only runs it. Otherwise the reaper runs the command,
# checks its own guards, and says why when they fail.
if [ "$#" -eq 1 ] && kill -0 "${{{canary}:-none}}" 2>/dev/null && [ -r {settings} ]; then
  exec {hook_shell} -c "$1"
fi
exec {python} -I -S {program} "$@"
"""


def wanted(platform: str = sys.platform) -> bool:
    """Whether a session with the OS layer gets the reaper: on macOS only.

    On Linux each sandboxed command runs in a process namespace of its own, which the
    kernel empties when the command ends (bubblewrap's ``--unshare-pid``).
    """
    return platform == "darwin"


def base_interpreter(base_prefix: str) -> Path:
    """The interpreter of ``base_prefix`` (outside any virtual environment).

    Raises:
        ValueError: there is none.
    """
    found = Path(base_prefix) / "bin" / "python3"
    if not os.access(found, os.X_OK):
        msg = f"no base interpreter at {found} to run the survivor reaper with"
        raise ValueError(msg)
    return found


def _quoted(path: Path) -> str:
    text = str(path)
    if "'" in text:
        msg = f"the path {text!r} cannot be written into the reaper's front"
        raise ValueError(msg)
    return f"'{text}'"


def place(target_dir: Path, base_prefix: str, settings: Path) -> Path:
    """Write the front and the reaper into ``target_dir``; return their directory.

    ``settings`` is the session's settings file, which the sandbox read-denies: the front
    passes a command through only where it can read it.

    Raises:
        ValueError: no base interpreter, or a path the prefix cannot carry: Claude Code
            splits a prefix at its last ``" -"``.
    """
    directory = target_dir / DIRNAME
    front = directory / FRONT
    if " -" in str(front):
        msg = f"the prefix {front} holds ' -', which Claude Code would split"
        raise ValueError(msg)
    python = base_interpreter(base_prefix)
    directory.mkdir(mode=0o755, exist_ok=True)
    program = directory / PROGRAM
    source = Path(__file__).with_name("reaper.py").read_bytes()
    program.write_bytes(source)
    program.chmod(0o644)
    front.write_text(
        _FRONT_TEXT.format(
            canary=CANARY_ENV,
            hook_shell=HOOK_SHELL,
            settings=_quoted(settings),
            python=_quoted(python),
            program=_quoted(program),
        )
    )
    front.chmod(0o755)
    return directory


def spawn_env(directory: Path) -> dict[str, str]:
    """What Claude Code's environment carries for the reaper in ``directory``.

    The shell is pinned to the one the reaper runs the command string with, since Claude
    Code writes that string (and its shell snapshot) for the shell it runs. It is the one
    Claude Code picks for a role session without the pin, so nothing about how a command
    runs changes.
    """
    return {"CLAUDE_CODE_SHELL_PREFIX": str(directory / FRONT), "CLAUDE_CODE_SHELL": SHELL}


def with_canary(argv: list[str]) -> list[str]:
    """``argv`` run so that its pid is exported as the canary first (a spawner's helper)."""
    return ["/bin/sh", "-c", CANARY_EXPORT + 'exec "$@"', "physgate-canary", *argv]
