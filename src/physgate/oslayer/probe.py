"""Whether this machine can run a session's shell commands inside the OS layer.

Two halves. ``gather_facts`` looks at the machine: which programs the session's
search path finds, and whether a trial command really runs inside the sandbox
the binary would use. ``judge`` turns those facts into a state, as a pure
function, so every reason can be tested without the machine that produces it.

A layer is **present** only where a trial ran inside it and the binary is a
version the layer is generated for. Everything else is **absent**, with a reason
in words an operator can act on; on native Windows the reason also says there is
no OS protection at all.
"""

from __future__ import annotations

import shutil
import subprocess
import sys
from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field, StringConstraints

#: The Claude Code versions the OS layer is generated for: the first that keeps a
#: denied path denied when it is reached through a symbolic link on macOS, and that
#: holds a sandbox started from the settings flag against a repository's settings.
#: A run on an older pinned version records the layer as absent.
SANDBOX_VERSIONS = frozenset({"2.1.301"})

#: How long a trial command may take before it counts as not having run.
TRIAL_SECONDS = 10.0

#: The longest reason a state carries, whatever a program printed.
REASON_LIMIT = 400

#: The trial Seatbelt runs: a profile that allows everything, around ``true``.
SEATBELT_TRIAL = ("/usr/bin/sandbox-exec", "-p", "(version 1)(allow default)", "/usr/bin/true")

#: The trial bubblewrap runs: the namespaces and mounts a sandboxed command gets.
BWRAP_TRIAL = (
    "--unshare-user",
    "--unshare-pid",
    "--unshare-net",
    "--ro-bind",
    "/",
    "/",
    "--dev",
    "/dev",
    "--proc",
    "/proc",
    "/bin/true",
)

#: Whether a mount is allowed in a new user namespace here, which bubblewrap needs.
MOUNT_NAMESPACE_TRIAL = ("--user", "--map-root-user", "--mount", "/bin/true")

System = Literal["darwin", "linux", "windows", "other"]


class _Frozen(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid", strict=True)


class Trial(_Frozen):
    """One trial command: whether it ran, and the first line it printed if it did not."""

    ran: bool
    detail: str | None


class PlatformFacts(_Frozen):
    """What the machine offers, as found by ``gather_facts``."""

    system: System
    claude_version: str
    #: macOS: the Seatbelt trial, or ``None`` where ``sandbox-exec`` is missing.
    sandbox_exec: Trial | None
    #: Linux: where the session's search path finds each program, or ``None``.
    bwrap: str | None
    socat: str | None
    #: Linux: the bubblewrap trial, or ``None`` where there is no bubblewrap to try.
    bwrap_trial: Trial | None
    #: Linux: whether a new user namespace may mount, or ``None`` where not tried.
    mount_namespace: Trial | None


_Reason = Annotated[str, StringConstraints(min_length=1, max_length=REASON_LIMIT)]


class Present(_Frozen):
    """The layer runs here: the mechanism, and the binary version it is generated for."""

    state: Literal["present"] = "present"
    mechanism: Literal["seatbelt", "bubblewrap"]
    claude_version: str


class Absent(_Frozen):
    """The layer does not run here, and why."""

    state: Literal["absent"] = "absent"
    reason: _Reason
    #: True on native Windows, where no OS protection exists at all.
    no_os_protection: bool = False


OsLayerState = Annotated[Present | Absent, Field(discriminator="state")]


def judge(facts: PlatformFacts) -> Present | Absent:
    """The OS layer's state on a machine with these facts."""
    if facts.system == "windows":
        return Absent(
            reason="native Windows: Claude Code runs commands unsandboxed",
            no_os_protection=True,
        )
    if facts.system == "other":
        return Absent(reason="this system is not macOS or Linux, where the sandbox runs")
    if facts.claude_version not in SANDBOX_VERSIONS:
        wanted = ", ".join(sorted(SANDBOX_VERSIONS))
        return Absent(
            reason=_bounded(
                f"the binary {facts.claude_version} predates the OS-layer pin ({wanted})"
            )
        )
    if facts.system == "darwin":
        return _judge_macos(facts)
    return _judge_linux(facts)


def _judge_macos(facts: PlatformFacts) -> Present | Absent:
    trial = facts.sandbox_exec
    if trial is None:
        return Absent(reason="macOS: sandbox-exec is missing")
    if not trial.ran:
        return Absent(reason=_bounded(f"macOS: Seatbelt could not run a trial: {trial.detail}"))
    return Present(mechanism="seatbelt", claude_version=facts.claude_version)


def _judge_linux(facts: PlatformFacts) -> Present | Absent:
    if facts.bwrap is None:
        reason = "Linux: bubblewrap (bwrap) is not on the session's search path"
        mount = facts.mount_namespace
        if mount is not None and not mount.ran:
            reason += (
                "; mounts in a user namespace are refused here, so installing it would "
                f"not help ({mount.detail})"
            )
        return Absent(reason=_bounded(reason))
    if facts.socat is None:
        return Absent(reason="Linux: socat is not on the session's search path")
    trial = facts.bwrap_trial
    if trial is None or not trial.ran:
        said = trial.detail if trial is not None else "not tried"
        return Absent(reason=_bounded(f"Linux: bubblewrap could not start: {said}"))
    return Present(mechanism="bubblewrap", claude_version=facts.claude_version)


def _bounded(text: str) -> str:
    return text if len(text) <= REASON_LIMIT else text[: REASON_LIMIT - 1] + "…"


def gather_facts(*, claude_version: str, search_path: str) -> PlatformFacts:
    """Look at this machine, with the search path a session will have."""
    system = _system()
    sandbox_exec: Trial | None = None
    bwrap = socat = None
    bwrap_trial = mount_namespace = None
    if system == "darwin" and shutil.which(SEATBELT_TRIAL[0]):
        sandbox_exec = _trial(SEATBELT_TRIAL)
    if system == "linux":
        bwrap = shutil.which("bwrap", path=search_path)
        socat = shutil.which("socat", path=search_path)
        if bwrap is not None:
            bwrap_trial = _trial((bwrap, *BWRAP_TRIAL))
        unshare = shutil.which("unshare", path=search_path)
        if unshare is not None:
            mount_namespace = _trial((unshare, *MOUNT_NAMESPACE_TRIAL))
    return PlatformFacts(
        system=system,
        claude_version=claude_version,
        sandbox_exec=sandbox_exec,
        bwrap=bwrap,
        socat=socat,
        bwrap_trial=bwrap_trial,
        mount_namespace=mount_namespace,
    )


def _system() -> System:
    if sys.platform == "darwin":
        return "darwin"
    if sys.platform.startswith("linux"):
        return "linux"
    if sys.platform in ("win32", "cygwin"):
        return "windows"
    return "other"


def _trial(argv: tuple[str, ...]) -> Trial:
    """Run one trial command with nothing on its input; it ran if it exited 0."""
    try:
        done = subprocess.run(
            argv,
            stdin=subprocess.DEVNULL,
            capture_output=True,
            text=True,
            check=False,
            timeout=TRIAL_SECONDS,
        )
    except subprocess.TimeoutExpired:
        return Trial(ran=False, detail=f"no answer within {TRIAL_SECONDS:g} s")
    except OSError as exc:
        return Trial(ran=False, detail=_bounded(str(exc)))
    if done.returncode == 0:
        return Trial(ran=True, detail=None)
    said = next((line for line in done.stderr.splitlines() if line.strip()), "")
    return Trial(ran=False, detail=_bounded(said or f"exit {done.returncode}"))


def judge_here(*, claude_version: str, search_path: str) -> Present | Absent:
    """The OS layer's state on this machine, for a session with this search path.

    A probe that fails is never a present layer: it reads as absent, with what failed.
    """
    try:
        facts = gather_facts(claude_version=claude_version, search_path=search_path)
    except (OSError, ValueError, subprocess.SubprocessError) as exc:
        return Absent(reason=_bounded(f"the probe could not run: {exc}"))
    return judge(facts)
