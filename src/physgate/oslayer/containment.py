"""A tool server's containment: the session's own OS-layer policy, narrowed for a server.

The binary starts a session's tool servers itself, as processes of its own outside the sandbox
it puts around the session's shell commands. So each admitted server runs inside a wrapper the
harness generates from the same policy the session's commands run under (``oslayer.policy``):

- **reads:** denied wherever the session's commands are denied, and the series outbox whole: the
  Linux sandbox names the outbox's entries as they stand when each command starts, and a server
  lives as long as its session, so a rule by entries would not cover a record written after it
  started. A server never reads the records;
- **writes:** only a directory of its own beneath the session's temporary directory, made empty
  for it, so nothing it leaves is a channel another session reads;
- **network:** none, ever (all of a server's network happened at provisioning);
- **serial devices:** neither read nor written;
- **lifetime:** it stays in the session's process group, so the check that nothing of a session
  outlives it covers its servers too.

The wrapper is ``sandbox-exec`` with a generated profile on macOS and bubblewrap on Linux, the
programs the OS layer already depends on. A server's entry names its wrapper as its command and
nothing else, and the spawn refuses any other (:func:`physgate.orchestrator.invocation.role_argv`).
"""

from __future__ import annotations

import json
import os
import re
from collections.abc import Sequence
from pathlib import Path
from typing import Annotated

from pydantic import BaseModel, ConfigDict, StringConstraints

from physgate.hooks.config import SessionConfig
from physgate.oslayer.policy import _read_denied, outbox_read_denial, serial_devices

#: Seatbelt's front end, where macOS ships it.
SANDBOX_EXEC = "/usr/bin/sandbox-exec"
#: Where each server's own directory is made, beneath the session's temporary directory.
SERVERS_DIR = "servers"
#: What a path in a profile may hold: a quote, a backslash or a control character would end or
#: bend the string it is written into.
_UNQUOTABLE = re.compile(r'["\\\x00-\x1f\x7f]')
#: A serial device's name pattern, as the device table holds them (``/dev/cu.*``).
_DEVICE_PATTERN = re.compile(r"/dev/[A-Za-z0-9._-]*\*?[A-Za-z0-9._-]*")


class ContainmentError(RuntimeError):
    """A server cannot be contained as the session's policy says, so none is offered."""


class ServerLaunch(BaseModel):
    """One admitted tool server: its name, and its program by absolute path with arguments."""

    model_config = ConfigDict(frozen=True, extra="forbid", strict=True)

    name: Annotated[str, StringConstraints(pattern=r"^[a-z][a-z0-9_-]{0,31}$")]
    command: Annotated[str, StringConstraints(pattern=r"^/")]
    args: tuple[str, ...] = ()
    #: Where the programs it runs in turn lie (a build server runs its build tool), each by
    #: absolute path; it runs nothing else but its own command.
    exec_roots: tuple[Annotated[str, StringConstraints(pattern=r"^/")], ...] = ()


def server_read_denied(config: SessionConfig, platform: str) -> tuple[str, ...]:
    """Every path a contained server may not read: the session's own denials, the outbox whole.

    Raises:
        ContainmentError: a denial is left that only names entries by a pattern, which a
            server, living as long as its session, would outlast.
    """
    session = _read_denied(config, platform)
    outboxes = {
        root.path
        for root in config.protected_roots
        if root.reads != "open" and root.shell_writes == "allowed"
    }
    by_entries = {outbox_read_denial(outbox, platform) for outbox in outboxes}
    denied = (session - by_entries) | outboxes
    patterned = sorted(path for path in denied if "*" in path)
    if patterned:
        msg = f"a server's read denial would name entries by a pattern: {patterned}"
        raise ContainmentError(msg)
    return tuple(sorted(denied))


def _quoted(path: str) -> str:
    if _UNQUOTABLE.search(path):
        msg = f"the path {path!r} cannot be written into a sandbox profile"
        raise ContainmentError(msg)
    return f'"{path}"'


def _spellings(path: str) -> list[str]:
    """The path as given and where it really is: Seatbelt judges an access where it lands."""
    return sorted({path, os.path.realpath(path)})


def _device_regex(pattern: str) -> str:
    """A device name pattern (``/dev/cu.*``) as the anchored regex Seatbelt reads."""
    return "^" + ".*".join(re.escape(part) for part in pattern.split("*")) + "$"


#: The Mach services a contained server may look up: the sandbox runtime's own base list
#: (0.0.79, the family the session's OS layer comes from), and no other. Launch Services' open,
#: Apple events and launchd's own services are not on it, so ``open``, ``osascript`` and
#: ``launchctl`` cannot act outside the sandbox from inside it.
MACH_SERVICES = (
    "com.apple.audio.systemsoundserver",
    "com.apple.distributed_notifications@Uv3",
    "com.apple.FontObjectsServer",
    "com.apple.fonts",
    "com.apple.logd",
    "com.apple.lsd.mapdb",
    "com.apple.PowerManagement.control",
    "com.apple.system.logger",
    "com.apple.system.notification_center",
    "com.apple.system.opendirectoryd.libinfo",
    "com.apple.system.opendirectoryd.membership",
    "com.apple.bsd.dirhelper",
    "com.apple.securityd.xpc",
    "com.apple.coreservices.launchservicesd",
    "com.apple.SecurityServer",
)
#: The system values a contained server may read, as the sandbox runtime's base lists them.
SYSCTLS = (
    "hw.activecpu",
    "hw.busfrequency_compat",
    "hw.byteorder",
    "hw.cacheconfig",
    "hw.cachelinesize_compat",
    "hw.cpufamily",
    "hw.cpufrequency",
    "hw.cpufrequency_compat",
    "hw.cputype",
    "hw.l1dcachesize_compat",
    "hw.l1icachesize_compat",
    "hw.l2cachesize_compat",
    "hw.l3cachesize_compat",
    "hw.logicalcpu",
    "hw.logicalcpu_max",
    "hw.machine",
    "hw.memsize",
    "hw.ncpu",
    "hw.nperflevels",
    "hw.packages",
    "hw.pagesize_compat",
    "hw.pagesize",
    "hw.physicalcpu",
    "hw.physicalcpu_max",
    "hw.tbfrequency_compat",
    "hw.vectorunit",
    "kern.argmax",
    "kern.bootargs",
    "kern.hostname",
    "kern.maxfiles",
    "kern.maxfilesperproc",
    "kern.maxproc",
    "kern.ngroups",
    "kern.osproductversion",
    "kern.osrelease",
    "kern.ostype",
    "kern.osvariant_status",
    "kern.osversion",
    "kern.secure_kernel",
    "kern.tcsm_available",
    "kern.tcsm_enable",
    "kern.usrstack64",
    "kern.version",
    "kern.willshutdown",
    "machdep.cpu.brand_string",
    "machdep.ptrauth_enabled",
    "security.mac.lockdown_mode_state",
    "sysctl.proc_cputype",
    "vm.loadavg",
)
SYSCTL_PREFIXES = (
    "hw.optional.arm",
    "hw.optional.arm.",
    "hw.optional.armv8_",
    "hw.perflevel",
    "kern.proc.pgrp.",
    "kern.proc.pid.",
    "machdep.cpu.",
)
#: The devices a contained server may control, as the runtime's base names them.
IOCTL_DEVICES = ("/dev/null", "/dev/zero", "/dev/random", "/dev/urandom", "/dev/tty")


def seatbelt_profile(
    *,
    read_denied: Sequence[str],
    server_dir: str,
    devices: Sequence[str],
    command: str,
    exec_roots: Sequence[str] = (),
) -> str:
    """The Seatbelt profile a server runs under on macOS: denied by default.

    The sandbox runtime's own base profile, narrowed for a server: it runs its own command
    and programs beneath its named roots, nothing else; it signals and inspects only processes
    of its own sandbox; it looks up only the runtime's Mach services; no network, no POSIX IPC,
    no Apple events, no registering a service. It reads everything but what the session's
    commands may not read, and writes only its own directory and ``/dev/null``. The last rule
    that matches an access decides, so each denial comes before the one place it opens again.
    Every path is named as given and where it really is.

    Raises:
        ContainmentError: no command is named, a path holds a character the profile cannot
            quote, or a device is named by more than a plain pattern.
    """
    if not command:
        msg = "a contained server names the command it runs"
        raise ContainmentError(msg)
    for pattern in devices:
        if not _DEVICE_PATTERN.fullmatch(pattern):
            msg = f"the device pattern {pattern!r} cannot be written into a sandbox profile"
            raise ContainmentError(msg)
    own = " ".join(f"(subpath {_quoted(p)})" for p in _spellings(server_dir))
    runs = [f"(literal {_quoted(p)})" for p in _spellings(command)]
    runs += [f"(subpath {_quoted(p)})" for root in exec_roots for p in _spellings(root)]
    lines = [
        "(version 1)",
        "(deny default)",
        "(deny network*)",
        f"(allow process-exec {' '.join(runs)})",
    ]
    lines += [
        "(allow process-fork)",
        "(allow process-info* (target same-sandbox))",
        "(allow signal (target same-sandbox))",
        "(allow user-preference-read)",
        "(allow mach-lookup " + " ".join(f'(global-name "{n}")' for n in MACH_SERVICES) + ")",
        "(allow sysctl-read "
        + " ".join(f'(sysctl-name "{n}")' for n in SYSCTLS)
        + " "
        + " ".join(f'(sysctl-name-prefix "{n}")' for n in SYSCTL_PREFIXES)
        + ")",
        "(allow file-ioctl " + " ".join(f'(literal "{d}")' for d in IOCTL_DEVICES) + ")",
        "(allow file-read*)",
        "(deny file-write*)",
        f'(allow file-write* {own} (literal "/dev/null"))',
    ]
    for path in sorted(read_denied):
        spelt = " ".join(f"(subpath {_quoted(p)})" for p in _spellings(path))
        lines.append(f"(deny file-read* {spelt})")
    if devices:
        # No device lies in the server's own directory, so the opening after it reopens none.
        named = " ".join(f'(regex #"{_device_regex(d)}")' for d in devices)
        lines.append(f"(deny file-read* file-write* {named})")
    lines.append(f"(allow file-read* {own})")
    return "\n".join(lines) + "\n"


#: The places bubblewrap makes afresh for a server, never bound from the machine.
_FRESH = frozenset({"/dev", "/proc"})


def _within(path: str, place: str) -> bool:
    return path == place or path.startswith(place.rstrip("/") + "/")


def _nearest_existing(path: str) -> str:
    current = path
    while not os.path.lexists(current):
        parent = os.path.dirname(current)
        if parent == current:
            break
        current = parent
    return current


def _entries(place: str, left_out: set[str]) -> list[str]:
    """Bind each entry ``place`` has now, read-only, but those left out; a link as a link."""
    args: list[str] = []
    for name in sorted(os.listdir(place)):
        child = os.path.join(place, name)
        if child in left_out or child in _FRESH:
            continue
        if os.path.islink(child):
            args += ["--symlink", os.readlink(child), child]
        else:
            args += ["--ro-bind", child, child]
    return args


def bwrap_args(*, read_denied: Sequence[str], server_dir: str) -> list[str]:
    """The bubblewrap options a server runs under on Linux, before its command.

    Nothing is bound whole. The server's root is built from the entries ``/`` has at launch,
    each bound read-only, and so is the nearest existing parent of every denied place that
    does not exist yet: a name made there later is not there inside, so a denied place made
    after the server started is never readable from it (fail closed). An existing denied
    directory is left out of its parent's listing where that parent is rebuilt, and hidden
    under an empty filesystem otherwise; a denied file lies under ``/dev/null``. A fresh
    ``/dev`` (no serial device in it) and a ``/proc`` of a process namespace of its own, so no
    other process's root is a way out of the mounts; no network but its own loopback; the
    server's directory bound writable; every filesystem made here, the root's among them, made
    read-only last. No new session: it stays in the session's process group, and it dies with
    the binary.
    """
    denied = {os.path.realpath(p) for p in read_denied}
    directories = sorted(p for p in denied if os.path.isdir(p))
    directories = [d for d in directories if not any(_within(d, o) and d != o for o in directories)]
    files = sorted(p for p in denied if os.path.lexists(p) and not os.path.isdir(p))

    def hidden(path: str) -> bool:
        return any(_within(path, d) for d in directories)

    absent_parents = {_nearest_existing(p) for p in denied if not os.path.lexists(p)}
    rebuilt = sorted(
        {"/"} | {p for p in absent_parents if not hidden(p)},
        key=lambda p: (p.count("/") if p != "/" else 0, p),
    )
    args = ["--die-with-parent", "--unshare-net", "--unshare-pid", "--unshare-ipc"]
    made: list[str] = []
    for place in rebuilt:
        if place != "/":
            args += ["--tmpfs", place]
            made.append(place)
        args += _entries(place, denied)
    args += ["--dev", "/dev", "--proc", "/proc"]
    listed = set(rebuilt)
    for path in directories:
        if os.path.dirname(path) in listed:
            continue  # left out of a listing that was rebuilt: not there at all
        args += ["--tmpfs", path]
        made.append(path)
    for path in files:
        if hidden(path) or os.path.dirname(path) in listed:
            continue
        args += ["--ro-bind", "/dev/null", path]
    own = os.path.realpath(server_dir)
    args += ["--bind", own, own]
    for path in made:
        args += ["--remount-ro", path]
    args += ["--remount-ro", "/"]
    return args


def wrappers(platform: str, bwrap: str | None) -> tuple[str, ...]:
    """The programs a contained server's entry may name as its command."""
    if platform == "darwin":
        return (SANDBOX_EXEC,)
    if platform.startswith("linux") and bwrap is not None:
        return (bwrap,)
    return ()


def contained_servers(
    config: SessionConfig,
    servers: Sequence[ServerLaunch],
    *,
    platform: str,
    temp_dir: Path,
    profiles_dir: Path,
    bwrap: str | None,
) -> str:
    """The tool-server configuration a session is spawned with: each server in its wrapper.

    Each server gets a directory of its own beneath the session's temporary directory, made
    here and empty; on macOS its profile is written into ``profiles_dir``, a place of the
    harness's that no session writes.

    Raises:
        ContainmentError: two servers share a name, a server's directory is already there, the
            platform has no wrapper, or a path cannot be put into one.
    """
    names = [server.name for server in servers]
    if len(set(names)) != len(names):
        msg = f"two tool servers share a name: {sorted(names)}"
        raise ContainmentError(msg)
    contained_by = wrappers(platform, bwrap)
    if not contained_by:
        msg = (
            f"no wrapper contains a tool server on {platform} here (Linux needs bubblewrap on "
            "the session's search path)"
        )
        raise ContainmentError(msg)
    denied = server_read_denied(config, platform)
    entries: dict[str, dict[str, object]] = {}
    for server in servers:
        server_dir = temp_dir / SERVERS_DIR / server.name
        try:
            server_dir.parent.mkdir(mode=0o700, exist_ok=True)
            server_dir.mkdir(mode=0o700)
        except FileExistsError as exc:
            msg = f"the tool server's directory {server_dir} is already there"
            raise ContainmentError(msg) from exc
        if platform == "darwin":
            profile = profiles_dir / f"{server.name}.sb"
            profiles_dir.mkdir(parents=True, exist_ok=True)
            profile.write_text(
                seatbelt_profile(
                    read_denied=denied,
                    server_dir=str(server_dir),
                    devices=serial_devices(platform),
                    command=server.command,
                    exec_roots=server.exec_roots,
                )
            )
            command, args = SANDBOX_EXEC, ["-f", str(profile)]
        else:
            command, args = (
                contained_by[0],
                [*bwrap_args(read_denied=denied, server_dir=str(server_dir)), "--"],
            )
        entries[server.name] = {
            "type": "stdio",
            "command": command,
            "args": [*args, server.command, *server.args],
            "env": {"TMPDIR": str(server_dir)},
        }
    return json.dumps({"mcpServers": entries}, sort_keys=True)
