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
- **a board's devices** (the session's device table): neither read nor written;
- **lifetime:** it stays in the session's process group, so the check that nothing of a session
  outlives it covers its servers too.

The wrapper is ``sandbox-exec`` with a generated profile on macOS and bubblewrap on Linux, the
programs the OS layer already depends on. A server's entry names its wrapper as its command and
nothing else, and the spawn refuses any other (:func:`physgate.orchestrator.invocation.role_argv`).

Both wrappers are allowlists. What each still lets through, accepted as stated, each bounded by
a test that runs the wrapper for real:

- **Linux:** bubblewrap cannot refuse running a program, so a server may run the system's own
  programs under ``/usr``. They run inside the same wrapper: no network, no home, none of the
  denied places, writes only into the server's own directory.
- **macOS:** any place's metadata (its name, size and times) and the root's own listing stay
  readable, which looking a path up needs. The content of a denied or unlisted file it can
  stat is not, nor the listing of any directory outside the list.
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
from physgate.oslayer.policy import _read_denied, board_devices, outbox_read_denial

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
    #: Where what it reads lies beyond the system's own libraries (its environment's roots);
    #: the session's worktree is added for every server.
    read_roots: tuple[Annotated[str, StringConstraints(pattern=r"^/")], ...] = ()
    #: The variables it reads, beside the ones the wrapper sets (its directory as ``TMPDIR``
    #: and ``MPLCONFIGDIR``). ``{server_dir}`` and ``{worktree}`` stand for its own directory
    #: and the session's worktree.
    environment: dict[str, str] = {}
    #: Directories made in its own directory, and links made beneath them, each to a path
    #: inside one of its read or exec roots: a tool that takes lock files beside its store is
    #: given a directory of its own that links into the read-only store.
    directories: tuple[str, ...] = ()
    links: dict[str, str] = {}


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


def _refuse_roots_inside_denials(read_denied: Sequence[str], roots: Sequence[str]) -> None:
    """Refuse a root of the server's that lies inside a place it may not read.

    The same on both platforms: a read, exec or command root inside a denied place would be
    opened again by its own allowance, so no server is offered (fail closed). The server's own
    directory is not one of them: it is the one place beneath a denied parent opened again.

    Raises:
        ContainmentError: a root lies inside a denied place, or is one.
    """
    denied = [os.path.realpath(p) for p in read_denied]
    for root in roots:
        real = os.path.realpath(root)
        for place in denied:
            if real == place or real.startswith(place.rstrip("/") + "/"):
                msg = f"the server's root {root} lies inside {place}, which it may not read"
                raise ContainmentError(msg)


#: What a server reads on macOS beyond its own roots: the system's libraries, frameworks and
#: programs (the loader's shared cache lies beneath ``/System``), and the clock's database.
MACOS_SYSTEM = (
    "/System",
    "/usr/lib",
    "/usr/share",
    "/usr/bin",
    "/bin",
    "/private/var/db/timezone",
)
#: Single places of the system a server reads: the root's own listing (the loader reads it as a
#: program starts; measured, without it the interpreter aborts), the devices it reads, the clock.
MACOS_SYSTEM_FILES = (
    "/",
    "/dev/null",
    "/dev/zero",
    "/dev/random",
    "/dev/urandom",
    "/private/etc/localtime",
)


def seatbelt_profile(
    *,
    read_denied: Sequence[str],
    server_dir: str,
    devices: Sequence[str],
    command: str,
    exec_roots: Sequence[str] = (),
    read_roots: Sequence[str] = (),
) -> str:
    """The Seatbelt profile a server runs under on macOS: denied by default.

    The sandbox runtime's own base profile, narrowed for a server: it runs its own command
    and programs beneath its named roots, nothing else; it signals and inspects only processes
    of its own sandbox; it looks up only the runtime's Mach services; no network, no POSIX IPC,
    no Apple events, no registering a service. It reads the contents only of the system's
    libraries and programs (:data:`MACOS_SYSTEM`), its read and exec roots and its own
    directory, less what the session's commands may not read; any place's metadata stays
    readable (stated in this module's docstring). It writes only its own
    directory and ``/dev/null``. The last rule
    that matches an access decides, so each denial comes before the one place it opens again.
    Every path is named as given and where it really is.

    Raises:
        ContainmentError: no command is named, a path holds a character the profile cannot
            quote, or a device is named by more than a plain pattern.
    """
    if not command:
        msg = "a contained server names the command it runs"
        raise ContainmentError(msg)
    _refuse_roots_inside_denials(read_denied, (*read_roots, *exec_roots, command))
    for pattern in devices:
        if not _DEVICE_PATTERN.fullmatch(pattern):
            msg = f"the device pattern {pattern!r} cannot be written into a sandbox profile"
            raise ContainmentError(msg)
    own = " ".join(f"(subpath {_quoted(p)})" for p in _spellings(server_dir))
    readable = [f"(subpath {_quoted(p)})" for p in MACOS_SYSTEM]
    readable += [f"(literal {_quoted(p)})" for p in MACOS_SYSTEM_FILES]
    readable += [
        f"(subpath {_quoted(p)})" for root in (*read_roots, *exec_roots) for p in _spellings(root)
    ]
    readable += [f"(literal {_quoted(p)})" for p in _spellings(command)]
    reads = " ".join([*readable, own])
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
        # Any place's name, size and times, which looking a path up needs; its contents only
        # in the list below.
        "(allow file-read-metadata)",
        f"(allow file-read* {reads})",
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


#: What a server's root holds on Linux beyond its own roots: the system's libraries and
#: programs, and the files the dynamic loader, the user database and the clock read. Nothing
#: else of the machine is there: not ``/run`` or ``/var/run`` with its services' sockets, not
#: ``/tmp``, not a home. A place that is a link (``/bin`` on a merged system) stays one.
LINUX_SYSTEM = (
    "/usr",
    "/bin",
    "/sbin",
    "/lib",
    "/lib32",
    "/lib64",
    "/libx32",
    "/etc/ld.so.cache",
    "/etc/ld.so.conf",
    "/etc/ld.so.conf.d",
    "/etc/localtime",
    "/etc/passwd",
    "/etc/group",
    "/etc/nsswitch.conf",
)


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
        if child in left_out:
            continue
        if os.path.islink(child):
            args += ["--symlink", os.readlink(child), child]
        else:
            args += ["--ro-bind", child, child]
    return args


def _depth(path: str) -> tuple[int, str]:
    return (path.rstrip("/").count("/"), path)


def bwrap_args(
    *, read_denied: Sequence[str], server_dir: str, read_roots: Sequence[str] = ()
) -> list[str]:
    """The bubblewrap options a server runs under on Linux, before its command.

    An allowlist: the server's root holds the system's libraries and programs
    (:data:`LINUX_SYSTEM`), its read roots, and its own directory, and nothing else of the
    machine, so no service's socket and no program outside them is there. A root inside a
    denied place is refused. Within anything the root holds, the system's places too, a
    denied directory is hidden under an empty filesystem and a denied file under ``/dev/null``
    (bound without device access, so opening it is refused);
    a denied place that does not exist yet has its nearest existing parent rebuilt from the
    entries it has at launch, so one made later is not there inside (fail closed). A fresh
    ``/dev`` (no serial device in it) and a ``/proc`` of a process namespace of its own; no
    network but its own loopback; its own directory bound writable; every filesystem made
    here, the root's among them, made read-only last. No new session: it stays in the
    session's process group, and it dies with the binary. What it still lets through is stated
    once, in this module's docstring.
    """
    _refuse_roots_inside_denials(read_denied, read_roots)
    roots = sorted({os.path.realpath(r) for r in read_roots if os.path.lexists(r)}, key=_depth)
    roots = [r for r in roots if not any(_within(r, o) and r != o for o in roots)]
    # Every place the root holds, the system's among them: a denial inside any is masked.
    mounted = [*roots, *(os.path.realpath(p) for p in LINUX_SYSTEM if os.path.exists(p))]
    denied = {os.path.realpath(p) for p in read_denied}
    inside = [p for p in denied if any(_within(p, m) for m in mounted)]
    directories = sorted((p for p in inside if os.path.isdir(p)), key=_depth)
    directories = [d for d in directories if not any(_within(d, o) and d != o for o in directories)]
    files = sorted(p for p in inside if os.path.lexists(p) and not os.path.isdir(p))

    def hidden(path: str) -> bool:
        return any(_within(path, d) for d in directories)

    rebuilt = sorted(
        {_nearest_existing(p) for p in inside if not os.path.lexists(p)} - {"/"},
        key=_depth,
    )
    rebuilt = [p for p in rebuilt if not hidden(p) and any(_within(p, m) for m in mounted)]
    args = ["--die-with-parent", "--unshare-net", "--unshare-pid", "--unshare-ipc"]
    for place in LINUX_SYSTEM:
        if os.path.islink(place):
            args += ["--symlink", os.readlink(place), place]
        elif os.path.exists(place):
            args += ["--ro-bind", place, place]
    for root in roots:
        args += ["--ro-bind", root, root]
    made: list[str] = []
    for place in rebuilt:
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
        # What every server reads: its own roots, and the session's worktree, less what the
        # session's commands may not read there.
        reads_from = (config.worktree, *server.read_roots)
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
                    devices=board_devices(platform),
                    command=server.command,
                    exec_roots=server.exec_roots,
                    read_roots=reads_from,
                )
            )
            command, args = SANDBOX_EXEC, ["-f", str(profile)]
        else:
            command, args = (
                contained_by[0],
                [
                    *bwrap_args(
                        read_denied=denied,
                        server_dir=str(server_dir),
                        read_roots=(*reads_from, *server.exec_roots, server.command),
                    ),
                    "--",
                ],
            )
        entries[server.name] = {
            "type": "stdio",
            "command": command,
            "args": [*args, server.command, *server.args],
            "env": {"TMPDIR": str(server_dir)},
        }
    return json.dumps({"mcpServers": entries}, sort_keys=True)
