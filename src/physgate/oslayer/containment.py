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


def seatbelt_profile(
    *,
    read_denied: Sequence[str],
    server_dir: str,
    devices: Sequence[str],
    command: str = "",
    exec_roots: Sequence[str] = (),
) -> str:
    """The Seatbelt profile a server runs under on macOS.

    The last rule that matches an access decides, so each denial comes before the one place it
    opens again. Every path is named as given and where it really is.

    Raises:
        ContainmentError: a path holds a character the profile cannot quote.
    """
    own = " ".join(f"(subpath {_quoted(p)})" for p in _spellings(server_dir))
    lines = [
        "(version 1)",
        "(allow default)",
        "(deny network*)",
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


def bwrap_args(*, read_denied: Sequence[str], server_dir: str) -> list[str]:
    """The bubblewrap options a server runs under on Linux, before its command.

    The whole filesystem read-only; a fresh ``/dev`` (no serial device in it) and a ``/proc`` of
    a process namespace of its own, so no other process's root is a way out of the mounts; each
    denied directory hidden under an empty filesystem and each denied file under ``/dev/null``,
    a place beneath one already hidden left to it; no network namespace but its own loopback;
    the server's directory bound writable; and each hidden place made read-only last, after the
    server's directory is bound beneath it. No new session: it stays in the session's process
    group, and it dies with the binary.
    """
    hidden: list[str] = []
    files: list[str] = []
    for path in sorted({os.path.realpath(p) for p in read_denied}):
        if any(path == h or path.startswith(h + "/") for h in hidden):
            continue
        if os.path.isdir(path):
            hidden.append(path)
        elif os.path.lexists(path):
            files.append(path)
    own = os.path.realpath(server_dir)
    args = [
        "--die-with-parent",
        "--unshare-net",
        "--unshare-pid",
        "--unshare-ipc",
        "--ro-bind",
        "/",
        "/",
        "--dev",
        "/dev",
        "--proc",
        "/proc",
    ]
    for path in hidden:
        args += ["--tmpfs", path]
    for path in files:
        args += ["--ro-bind", "/dev/null", path]
    args += ["--bind", own, own]
    for path in hidden:
        args += ["--remount-ro", path]
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
