"""The OS layer's settings for one session, generated from its session configuration.

The hooks and the OS layer read one registry: the session configuration the hook
installer writes. This module turns it into Claude Code's ``sandbox`` settings and
``Read`` deny rules, so the two layers cannot disagree about what is protected,
and a new kind of path in the configuration cannot be added without a rule here
(``FIELD_RULES``, which a test holds equal to the configuration's path fields).

**Writes.** A sandboxed command writes only in the session's worktree, its own
temporary directory and its own home. Everything else is denied by the OS before
any list is read, so a protected path outside those three places needs no entry
to be safe; it is named anyway, so the settings say what they protect. Inside a
writable place three rules apply:

- every write-protected path that exists is named; one that does not exist yet is
  named where its parent exists, and left to the hooks and the sentinel where its
  parent is missing too, because a denied path with a missing parent keeps a
  command from making that parent at all. On Linux a denied path that does not
  exist yet is held by an empty read-only placeholder file while a command runs,
  and a session killed mid-command leaves it behind; inside the worktree those
  paths are listed (``absent_named``), and the dispatcher's sweep removes such a
  placeholder before anything is committed;
- a root with a writable path beneath it (the knowledge tree around its staging
  directory) is named child by child around that path, as its children stand when
  the session starts, because a denied path wins over an allowed one beneath it; a
  child made later is the hooks' and the sentinel's alone;
- a root the registry leaves to scripts (``shell_writes: allowed``: the series
  outbox, whose records the collector judges) is not named for writes, and is read-denied
  (below);
- a root above a writable place (the run's ``sessions/`` above the session's
  home) is not named at all: the OS already denies everything in it but the home.

**The node proposals are the file tools' alone.** A node reaches the graph as a proposal
file the Write and Edit tools write in ``.physgate/proposals``, where the hooks check it
before it exists. The hooks refuse a command that names the directory, but a command that
reaches it by a path it builds as it runs, or by copying or moving a directory into place,
names nothing they can see. So the proposals directory is write-denied to every shell
command; the file tools, which the sandbox does not wrap, still write there. The completion
declaration's directory, ``.physgate/completion``, and the disputes', ``.physgate/disputes``, are
held the same way and for the same reason.

**Reads.** Denied for what no session reads (the held-out tier, answer keys,
review material, the harness checkout, the series outbox)
and for what the session's runtime keeps from its shell commands (its credentials, the
hooks' records, other sessions' files). A read-denied root above the session's home has
the home opened again.

**The series outbox is written blind.** A record reaches it by a script's own write, so a
shell command may write there and may not read there: a command that joins the outbox's path
at run time, which the hooks' text rule cannot see, must find nothing to read. The series
writer makes each record's file new in the outbox and writes it there; it never writes
through a name already there, and nothing waits beside the outbox to be caught. The two
mechanisms deny the reads differently, each measured on Claude Code 2.1.301:

- on macOS Seatbelt denies the outbox whole, to every process of the session: a command
  cannot list it, read, link, copy, rename or remove anything in it, nor rename it or a
  directory above it away; even the metadata of an entry is denied, through the descriptor
  that made it. A command can still hold the outbox by a search-only descriptor, create a
  new file in it through that descriptor and write it, which is how the series writer
  writes. So no command, nor a process that outlived one, reads a record;
- on Linux bubblewrap lays an empty layer over a read-denied directory, and a record written
  into that layer would be gone when the command ends. The outbox's entries are denied
  instead (``<outbox>/*``), expanded as each command starts: every record an earlier command
  wrote is unreadable and cannot be written over, renamed or moved away with the outbox.
  **What Linux does not deny:** an entry made during a command is not in that command's list,
  so the command that wrote a record, and any process of that same command, can read it
  back, link it elsewhere and keep it, and every command lists the names. The guarantee there
  is that no command reads a record an earlier command wrote, unless the command that wrote it
  kept a copy.

A platform with neither mechanism gets no policy at all: building one refuses, rather than
leaving the outbox readable.

**The file tools are left to the hooks.** No ``Read`` permission rule is written:
Claude Code applies such a rule before any hook runs, so a refused tool call would
be refused without the hooks' reason and without a line in their log, the record
the bypass measurements count. The hooks refuse the file tools on what no session
reads, and log it; the OS layer bounds the shell, where the hooks cannot see.
"""

from __future__ import annotations

import os
import sys
from collections.abc import Callable, Iterable, Mapping
from dataclasses import dataclass
from pathlib import Path
from types import MappingProxyType
from typing import Any, Literal

from physgate.hooks.config import ExperimentRule, SessionConfig
from physgate.hooks.graph import COMPLETION_DIR, DISPUTES_DIR, PROPOSALS_DIR

#: What the OS layer does with each path field of the session configuration.
FIELD_RULES: dict[str, str] = {
    "worktree": (
        "writable: the session's working directory, but for its node proposals, the "
        "completion declaration and its disputes, which only the file tools write"
    ),
    "store_root": "write-denied (named whole)",
    "state_dir": "write- and read-denied to shell commands: the hooks' records",
    "protected_roots": (
        "write-denied unless `shell_writes` leaves it to scripts; read-denied as `reads` says "
        "(a root scripts write: whole on macOS, by its entries on Linux)"
    ),
    "experiments": "frozen files write-denied, named as the hooks freeze them",
    "held_out": "write- and read-denied (the file tools are the hooks')",
    "answer_keys": "write- and read-denied (the file tools are the hooks')",
    "read_roots": "not used: only a reviewer has them, and a reviewer runs no shell",
    "review_material": "write- and read-denied (the file tools are the hooks')",
    "required_reading": "readable: the session must read it",
    "always_loaded": "readable: loaded into every session",
    "installation": "write-denied through the protected roots that name it",
}


@dataclass(frozen=True)
class OsPolicy:
    """The settings to merge into a session's settings file, and what they leave out."""

    settings: dict[str, Any]
    #: Write-denied paths inside the worktree that did not exist when the session started:
    #: named all the same, and swept after the session for the placeholder the Linux
    #: sandbox may leave at one.
    absent_named: tuple[str, ...]


#: The network block that takes a session's shell commands offline. An empty allow-list
#: alone is not enough: in ``bypassPermissions`` mode, which every session runs in, hosts
#: outside the list are let through unless ``strictAllowlist`` is on (Claude Code's
#: sandboxing documentation, read 17.10.2026). Local binding is off: with it on, a shell
#: command reached every service listening on the machine's loopback (a proxy, the
#: operator's UI, an editor's bridge), measured on macOS 17.10.2026, which ``open``
#: refuses; a local proxy would then carry a command past the allow-list. With it off,
#: a command can neither serve a port nor reach one on the host; an emulator talks to
#: its program over its standard streams instead. Never handed out by reference: each
#: session's settings get a copy.
OFFLINE: Mapping[str, Any] = MappingProxyType(
    {"strictAllowlist": True, "allowedDomains": (), "allowLocalBinding": False}
)


def offline_block() -> dict[str, Any]:
    """A fresh copy of :data:`OFFLINE`, as a session's settings carry it."""
    return {
        "strictAllowlist": OFFLINE["strictAllowlist"],
        "allowedDomains": list(OFFLINE["allowedDomains"]),
        "allowLocalBinding": OFFLINE["allowLocalBinding"],
    }


#: Recorded wherever ``none`` is asked for and no OS layer runs to enforce it: a shell
#: is kept from remote hosts by the OS layer alone, so without it its commands stay online.
NETWORK_UNENFORCED = "network: none requested, not enforceable here"


def sandbox_policy(
    config: SessionConfig,
    *,
    home: str,
    temp_dir: str,
    readable: tuple[str, ...] = (),
    shared_temp: tuple[str, ...] = (),
    claude_temp: tuple[str, ...] = (),
    network: Literal["open", "none"] = "open",
    exists: Callable[[str], bool] = os.path.lexists,
    children: Callable[[str], Iterable[str]] = os.listdir,
    platform: str = sys.platform,
) -> OsPolicy:
    """The OS layer's settings for the session ``config`` describes.

    ``network`` set to ``none`` refuses the session's shell commands every remote host and
    every service on the machine's loopback (:data:`OFFLINE`).
    ``readable`` names further places of the session's own its shell commands read,
    opened again where a read-denied root holds them, as the home is. ``shared_temp`` names
    the machine's shared temporary directories, writable too, because ordinary commands
    write there by name (``/tmp``, and on macOS the per-user directory plain ``mktemp``
    uses); ``claude_temp`` names Claude Code's own temporary directories inside them, which
    hold every session of the user's records and are denied both ways. ``platform`` says
    which mechanism enforces the settings, which decides how the series outbox is read-denied.

    Raises:
        ValueError: the worktree, the home or the temporary directory sits inside a
            read-denied path, where the session could not work; or ``platform`` has no
            mechanism that keeps the series outbox unreadable.
    """
    writable = (config.worktree, temp_dir, home, *shared_temp)
    read_denied = _read_denied(config, platform)
    for place in (config.worktree, temp_dir):
        if any(_under(place, denied) for denied in read_denied):
            what = "worktree" if place == config.worktree else "temporary directory"
            msg = f"the session's {what} ({place}) is inside a read-denied path"
            raise ValueError(msg)
    deny_write, absent_named = _write_denied(config, writable, exists, children)
    # The home, and any further place of the session's own its commands read, may sit
    # inside a read-denied root (the run's sessions/): opened again.
    allow_read = sorted(
        place for place in {home, *readable} if any(_under(place, denied) for denied in read_denied)
    )
    settings: dict[str, Any] = {
        "sandbox": {
            "enabled": True,
            "failIfUnavailable": True,
            "allowUnsandboxedCommands": False,
            "autoAllowBashIfSandboxed": True,
            "excludedCommands": [],
            "filesystem": {
                "allowWrite": _spelled(home, *shared_temp),
                "denyWrite": _spelled(*deny_write, *claude_temp),
                "denyRead": _spelled(*read_denied, *claude_temp),
                "allowRead": _spelled(*allow_read),
            },
        },
    }
    if network == "none":
        settings["sandbox"]["network"] = offline_block()
    return OsPolicy(settings=settings, absent_named=tuple(sorted(absent_named)))


def _spelled(*paths: str) -> list[str]:
    """Each path as given and where it really is, when the two differ.

    The sandbox judges an access where it lands. A path given through a symbolic link
    (``/var`` is ``/private/var`` on macOS) and named only as given was measured to deny
    nothing on Seatbelt, so both spellings are named.
    """
    return sorted({spelling for path in paths for spelling in (path, os.path.realpath(path))})


#: What names every entry of a directory to the Linux sandbox, which expands it against the
#: directory as it stands when each command starts.
EVERY_ENTRY = "*"
#: The characters a glob reads as more than themselves: in the outbox's own path they would
#: name other places than the outbox's entries, or none.
GLOB_CHARACTERS = "*?[]{}\\"


def outbox_read_denial(path: str, platform: str) -> str:
    """How the sandbox on ``platform`` is told no command reads the outbox at ``path``.

    Raises:
        ValueError: ``platform`` has no mechanism that denies the reads and keeps the writes,
            or the outbox's own path would read as a pattern.
    """
    if platform == "darwin":
        return path
    if platform.startswith("linux"):
        if set(path) & set(GLOB_CHARACTERS):
            msg = f"the series outbox's path {path} reads as a pattern; its entries cannot be named"
            raise ValueError(msg)
        return os.path.join(path, EVERY_ENTRY)
    msg = f"no OS-layer rule keeps the series outbox unreadable on {platform}"
    raise ValueError(msg)


def _read_denied(config: SessionConfig, platform: str) -> set[str]:
    """Every path a shell command of this session may not read.

    A read-denied root that scripts write (the series outbox) is named as the platform's
    mechanism can deny its reads and keep its writes (:func:`outbox_read_denial`).
    """
    denied = {*config.held_out, *config.answer_keys, *config.review_material, config.state_dir}
    for root in config.protected_roots:
        if root.reads == "open":
            continue
        if root.shell_writes == "allowed":
            denied.add(outbox_read_denial(root.path, platform))
        else:
            denied.add(root.path)
    return denied


def proposals_dir(worktree: str) -> str:
    """Where the session's node proposals are written, by the file tools alone."""
    return os.path.join(worktree, PROPOSALS_DIR)


def _write_denied(
    config: SessionConfig,
    writable: tuple[str, ...],
    exists: Callable[[str], bool],
    children: Callable[[str], Iterable[str]],
) -> tuple[list[str], list[str]]:
    """The write-denied paths to name, and the protected paths left unnamed."""
    roots: list[tuple[str, tuple[str, ...]]] = [
        (r.path, r.exceptions) for r in config.protected_roots if r.shell_writes == "denied"
    ]
    plain = (*config.held_out, *config.answer_keys, *config.review_material, config.state_dir)
    roots += [(path, ()) for path in plain]
    if config.store_root is not None:
        roots.append((config.store_root, ()))
    roots.append((proposals_dir(config.worktree), ()))
    roots.append((os.path.join(config.worktree, COMPLETION_DIR), ()))
    roots.append((os.path.join(config.worktree, DISPUTES_DIR), ()))
    for rule in config.experiments:
        roots += [(path, ()) for path in _frozen(rule, exists, children)]
    named: set[str] = set()
    absent: set[str] = set()
    for path, exceptions in roots:
        below = tuple(place for place in writable if place != path and _under(place, path))
        inside = any(_under(path, place) for place in writable if place not in below)
        if below:
            # A root above a writable place (the run's sessions/ above the session's home).
            # Outside every other writable place the OS denies the rest of it already; inside
            # one (a run directory under the shared /tmp) it is named around that place.
            if inside and exists(path):
                named.update(_around(path, (*exceptions, *below), exists, children))
            continue
        if not inside or exists(path):
            if exceptions and inside:
                named.update(_around(path, exceptions, exists, children))
            else:
                named.add(path)
            continue
        # Absent, inside a writable place. Named only where its parent exists and nothing
        # beneath it is carved out: a denied path whose parent is missing was measured to
        # keep a command from making that parent at all (``mkdir -p src/other`` refused for
        # a denied, absent ``src/physgate/gate``), a false refusal of ordinary work.
        if not exceptions and exists(os.path.dirname(path)):
            named.add(path)
            if _under(path, config.worktree):
                absent.add(path)  # swept after the session for a placeholder
    # A path beneath another named one is denied with it. Naming it too would, on Linux,
    # have bubblewrap make a placeholder for it wherever the outer one sits in a writable
    # place (the run repository's common git directory, which the sandbox opens to a
    # linked worktree): measured as ``config.worktree`` files appearing in it.
    outer = {p for p in named if not any(p != q and _under(p, q) for q in named)}
    return sorted(outer), sorted(absent & outer)


def _around(
    root: str,
    exceptions: tuple[str, ...],
    exists: Callable[[str], bool],
    children: Callable[[str], Iterable[str]],
) -> set[str]:
    """Every existing path under ``root`` that is not an exception or on the way to one."""
    named: set[str] = set()
    for name in sorted(children(root)):
        child = str(Path(root) / name)
        if child in exceptions:
            continue
        if any(_under(exception, child) for exception in exceptions):
            named.update(_around(child, exceptions, exists, children))
        elif exists(child):
            named.add(child)
    return named


def _frozen(
    rule: ExperimentRule,
    exists: Callable[[str], bool],
    children: Callable[[str], Iterable[str]],
) -> list[str]:
    """The experiment files the hooks freeze, as they stand when the session starts.

    An experiment directory with a result anywhere beneath it is frozen whole; in
    any other, each criteria file is.
    """
    if not exists(rule.root):
        return []
    frozen: list[str] = []
    for name in sorted(children(rule.root)):
        experiment = Path(rule.root) / name
        files = [Path(d) / f for d, _, fs in os.walk(experiment) for f in fs]
        if any(f.name == rule.frozen_marker for f in files):
            frozen.append(str(experiment))
        else:
            frozen += [str(f) for f in files if f.name == rule.always_frozen_name]
    return frozen


def _under(path: str, root: str) -> bool:
    return Path(path).is_relative_to(Path(root))
