"""Placeholders the Linux sandbox leaves in a worktree when a session is killed.

On Linux the sandbox holds a write-denied path that does not exist yet with an
empty, read-only placeholder file while a command runs, and removes it after.
A session killed mid-command leaves it behind (Claude Code's documentation,
"0-byte read-only files appear at .claude settings paths"). In a worktree that
would be committed with the attempt, so after every session the dispatcher
removes each one, and records what it removed and what it refused.

The worktree is the session's to shape, so nothing in it is trusted. Only a path
named here is ever considered; it is reached through directory descriptors opened
without following a link at any component, each directory checked to be the one
recorded before the session started; and it is removed only if it is provably a
placeholder: a regular file, empty, with one link, no write permission, on the
worktree's device. Nothing else is touched, a directory never is, and anything a
named path holds that is not a placeholder is refused and recorded.
"""

from __future__ import annotations

import os
import stat
from dataclasses import dataclass, field

#: Where the sandbox holds Claude Code's own protected names in a working directory:
#: ``(directory, name)``, the directory relative to the worktree ("" for its top).
NAMES: tuple[tuple[str, str], ...] = (
    ("", ".mcp.json"),
    ("", ".bashrc"),
    ("", ".bash_profile"),
    ("", ".zshrc"),
    ("", ".zprofile"),
    ("", ".profile"),
    ("", ".gitconfig"),
    ("", "HEAD"),
    ("", "config"),
    (".claude", "settings.json"),
    (".claude", "settings.local.json"),
)

_DIRECTORY = os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW | getattr(os, "O_CLOEXEC", 0)
Identity = tuple[int, int]


@dataclass(frozen=True)
class Snapshot:
    """What the named places held before the session: their directories and entries."""

    directories: dict[str, Identity]
    present: frozenset[str]


@dataclass
class Swept:
    """What a sweep removed, and what it refused with why."""

    removed: list[str] = field(default_factory=list)
    refused: list[tuple[str, str]] = field(default_factory=list)


def _open(worktree: str, directory: str) -> int:
    """A descriptor for ``directory`` under ``worktree``, no link followed at any step."""
    fd = os.open(worktree, _DIRECTORY)
    if not directory:
        return fd
    try:
        return os.open(directory, _DIRECTORY, dir_fd=fd)
    finally:
        os.close(fd)


def _identity(fd: int) -> Identity:
    info = os.fstat(fd)
    return info.st_dev, info.st_ino


def snapshot(worktree: str) -> Snapshot:
    """Record the named places as they are before the session starts."""
    directories: dict[str, Identity] = {}
    present: set[str] = set()
    for directory in sorted({d for d, _ in NAMES}):
        try:
            fd = _open(worktree, directory)
        except OSError:
            continue  # absent, or not a plain directory: nothing in it is swept
        try:
            directories[directory] = _identity(fd)
            for d, name in NAMES:
                if d != directory:
                    continue
                try:
                    os.stat(name, dir_fd=fd, follow_symlinks=False)
                except OSError:
                    continue
                present.add(os.path.join(directory, name))
        finally:
            os.close(fd)
    return Snapshot(directories=directories, present=frozenset(present))


def sweep(worktree: str, before: Snapshot) -> Swept:
    """Remove every placeholder that appeared at a named path; refuse anything else."""
    swept = Swept()
    for directory, identity in sorted(before.directories.items()):
        try:
            fd = _open(worktree, directory)
        except OSError as exc:
            swept.refused.append((directory or ".", f"the directory cannot be opened: {exc}"))
            continue
        try:
            if _identity(fd) != identity:
                swept.refused.append((directory or ".", "the directory was replaced"))
                continue
            for d, name in NAMES:
                path = os.path.join(directory, name)
                if d != directory or path in before.present:
                    continue
                why = _remove_if_placeholder(fd, name, identity[0])
                if why is None:
                    swept.removed.append(path)
                elif why != "absent":
                    swept.refused.append((path, why))
        finally:
            os.close(fd)
    return swept


def _remove_if_placeholder(parent: int, name: str, device: int) -> str | None:
    """Unlink ``name`` in ``parent`` if it is a placeholder; else say why not."""
    try:
        info = os.stat(name, dir_fd=parent, follow_symlinks=False)
    except FileNotFoundError:
        return "absent"
    if not stat.S_ISREG(info.st_mode):
        return "not a regular file"
    if info.st_size != 0:
        return "not empty"
    if info.st_nlink != 1:
        return "it has another name"
    if info.st_mode & (stat.S_IWUSR | stat.S_IWGRP | stat.S_IWOTH):
        return "it is writable"
    if info.st_dev != device:
        return "it is on another device"
    os.unlink(name, dir_fd=parent)
    return None
