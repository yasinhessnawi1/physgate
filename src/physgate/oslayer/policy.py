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
  outbox, whose records the collector judges) is not named;
- a root above a writable place (the run's ``sessions/`` above the session's
  home) is not named at all: the OS already denies everything in it but the home.

**Reads.** Denied for what no session reads (the held-out tier, answer keys,
review material, the harness checkout) and for what the session's runtime keeps
from its shell commands (its credentials, the hooks' records, other sessions'
files). A read-denied root above the session's home has the home opened again.

**The file tools are left to the hooks.** No ``Read`` permission rule is written:
Claude Code applies such a rule before any hook runs, so a refused tool call would
be refused without the hooks' reason and without a line in their log, the record
the bypass measurements count. The hooks refuse the file tools on what no session
reads, and log it; the OS layer bounds the shell, where the hooks cannot see.
"""

from __future__ import annotations

import os
from collections.abc import Callable, Iterable
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from physgate.hooks.config import ExperimentRule, SessionConfig

#: What the OS layer does with each path field of the session configuration.
FIELD_RULES: dict[str, str] = {
    "worktree": "writable: the session's working directory",
    "store_root": "write-denied (named whole)",
    "state_dir": "write- and read-denied to shell commands: the hooks' records",
    "protected_roots": (
        "write-denied unless `shell_writes` leaves it to scripts; read-denied as `reads` says"
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


def sandbox_policy(
    config: SessionConfig,
    *,
    home: str,
    temp_dir: str,
    readable: tuple[str, ...] = (),
    shared_temp: tuple[str, ...] = (),
    claude_temp: tuple[str, ...] = (),
    exists: Callable[[str], bool] = os.path.lexists,
    children: Callable[[str], Iterable[str]] = os.listdir,
) -> OsPolicy:
    """The OS layer's settings for the session ``config`` describes.

    ``readable`` names further places of the session's own its shell commands read,
    opened again where a read-denied root holds them, as the home is. ``shared_temp`` names
    the machine's shared temporary directories, writable too, because ordinary commands
    write there by name (``/tmp``, and on macOS the per-user directory plain ``mktemp``
    uses); ``claude_temp`` names Claude Code's own temporary directories inside them, which
    hold every session of the user's records and are denied both ways.

    Raises:
        ValueError: the worktree, the home or the temporary directory sits inside a
            read-denied path, where the session could not work.
    """
    writable = (config.worktree, temp_dir, home, *shared_temp)
    read_denied = _read_denied(config)
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
    return OsPolicy(settings=settings, absent_named=tuple(sorted(absent_named)))


def _spelled(*paths: str) -> list[str]:
    """Each path as given and where it really is, when the two differ.

    The sandbox judges an access where it lands. A path given through a symbolic link
    (``/var`` is ``/private/var`` on macOS) and named only as given was measured to deny
    nothing on Seatbelt, so both spellings are named.
    """
    return sorted({spelling for path in paths for spelling in (path, os.path.realpath(path))})


def _read_denied(config: SessionConfig) -> set[str]:
    """Every path a shell command of this session may not read."""
    denied = {*config.held_out, *config.answer_keys, *config.review_material, config.state_dir}
    denied.update(r.path for r in config.protected_roots if r.reads != "open")
    return denied


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
