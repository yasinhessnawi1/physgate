"""Placeholders the Linux sandbox leaves in a worktree when a session is killed.

On Linux the sandbox holds a write-denied path that does not exist yet with an
empty, read-only placeholder file while a command runs, and removes it after.
A session killed mid-command leaves it behind (Claude Code's documentation,
"0-byte read-only files appear at .claude settings paths"). In a worktree that
would be committed with the attempt, so after every session the dispatcher
removes each one, and records what it removed and what it refused.

The worktree is the session's to shape, so nothing in it is trusted. Only a path
named here, or named by the session's own deny list and absent when it started, is
ever considered; it is reached through directory descriptors opened
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
    #: Further paths under the worktree the session's own deny list names that did not
    #: exist when it started, relative to the worktree.
    absent: tuple[str, ...] = ()
    #: The worktree itself, as it was.
    worktree: Identity | None = None


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


def snapshot(worktree: str, absent: tuple[str, ...] = ()) -> Snapshot:
    """Record the named places as they are before the session starts.

    ``absent`` names further paths under the worktree, relative to it, that the session's
    deny list names and that do not exist yet.
    """
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
    still_absent = tuple(sorted(p for p in absent if not _exists(worktree, p)))
    return Snapshot(
        directories=directories,
        present=frozenset(present),
        absent=still_absent,
        worktree=directories.get(""),
    )


def _exists(worktree: str, relative: str) -> bool:
    try:
        os.lstat(os.path.join(worktree, relative))
    except FileNotFoundError:
        return False
    except OSError:
        return True  # cannot be told: treated as present, so never swept
    return True


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
    for relative in before.absent:
        _sweep_nested(worktree, relative, before.worktree, swept)
    return swept


def _sweep_nested(worktree: str, relative: str, identity: Identity | None, swept: Swept) -> None:
    """Remove a placeholder at ``relative``, reached one component at a time, no link followed.

    The worktree must still be the one recorded; a directory on the way may be new (the
    sandbox makes the missing ones as it holds the path), and each is opened relative to
    the one before it without following a link, so the walk never leaves the worktree.
    """
    parts = [part for part in relative.split("/") if part]
    if identity is None or not parts or any(p in (".", "..") for p in parts):
        return
    try:
        fd = os.open(worktree, _DIRECTORY)
    except OSError as exc:
        swept.refused.append((relative, f"the worktree cannot be opened: {exc}"))
        return
    try:
        if _identity(fd) != identity:
            swept.refused.append((relative, "the worktree was replaced"))
            return
        for part in parts[:-1]:
            try:
                child = os.open(part, _DIRECTORY, dir_fd=fd)
            except FileNotFoundError:
                return  # nothing was made on the way: nothing to sweep
            except OSError as exc:
                swept.refused.append((relative, f"a directory on the way: {exc}"))
                return
            os.close(fd)
            fd = child
        why = _remove_if_placeholder(fd, parts[-1], identity[0])
        if why is None:
            swept.removed.append(relative)
        elif why != "absent":
            swept.refused.append((relative, why))
    finally:
        os.close(fd)


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
