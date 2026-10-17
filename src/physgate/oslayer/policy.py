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

- on Linux a denied path that does not exist yet is held by an empty read-only
  placeholder file while a command runs, and a session killed mid-command leaves
  it behind, where an attempt's commit could pick it up; so inside the worktree
  only what exists when the session starts is named, and what does not exist
  stays with the hooks and the sentinel, as before (in the session's own home and
  temporary directory a placeholder is harmless, and every path is named);
- a root with a writable path beneath it (the knowledge tree around its staging
  directory) is named child by child around that path, because a denied path
  wins over an allowed one beneath it;
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
    "protected_roots": "write-denied; read-denied as each root's `reads` says",
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
    #: Protected paths inside a writable place that do not exist yet, so are not named.
    not_named: tuple[str, ...]


def sandbox_policy(
    config: SessionConfig,
    *,
    home: str,
    temp_dir: str,
    readable: tuple[str, ...] = (),
    exists: Callable[[str], bool] = os.path.lexists,
    children: Callable[[str], Iterable[str]] = os.listdir,
) -> OsPolicy:
    """The OS layer's settings for the session ``config`` describes.

    ``readable`` names further places of the session's own its shell commands read,
    opened again where a read-denied root holds them, as the home is.

    Raises:
        ValueError: the worktree, the home or the temporary directory sits inside a
            read-denied path, where the session could not work.
    """
    writable = (config.worktree, temp_dir, home)
    read_denied = _read_denied(config)
    for place in (config.worktree, temp_dir):
        if any(_under(place, denied) for denied in read_denied):
            what = "worktree" if place == config.worktree else "temporary directory"
            msg = f"the session's {what} ({place}) is inside a read-denied path"
            raise ValueError(msg)
    deny_write, not_named = _write_denied(config, writable, exists, children)
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
                # The process's own file descriptors: a process substitution reads and
                # writes through them, and Seatbelt otherwise refuses it.
                "allowWrite": [home, "/dev/fd"],
                "denyWrite": deny_write,
                "denyRead": sorted(read_denied),
                "allowRead": allow_read,
            },
        },
    }
    return OsPolicy(settings=settings, not_named=tuple(sorted(not_named)))


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
        (r.path, r.exceptions) for r in config.protected_roots
    ]
    plain = (*config.held_out, *config.answer_keys, *config.review_material, config.state_dir)
    roots += [(path, ()) for path in plain]
    if config.store_root is not None:
        roots.append((config.store_root, ()))
    for rule in config.experiments:
        roots += [(path, ()) for path in _frozen(rule, exists, children)]
    named: set[str] = set()
    not_named: set[str] = set()
    for path, exceptions in roots:
        if any(_under(place, path) for place in writable):
            continue  # a root above a writable place: the OS denies the rest of it already
        inside = any(_under(path, place) for place in writable)
        if not inside:
            named.add(path)
        elif _under(path, config.worktree) and not exists(path):
            not_named.add(path)  # a Linux placeholder here could be committed
        elif exceptions:
            named.update(_around(path, exceptions, exists, children))
        else:
            named.add(path)
    return sorted(named), sorted(not_named - named)


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
