"""A tripwire on the files no session reads: none may have a second name, or change.

The OS layer judges a read by the name it is given, so a held-out or answer-key
file that also had a name inside the worktree could be read there. The OS
layer's read denial and the hooks are the layers that keep these files unread;
this is a tripwire behind them, and claims only what it checks:

- at three points: the session's start, its end, and before the orchestrator
  commits its attempt;
- that every file under the held-out tier and the answer-key corpora has one
  name, and (between the start and the end) is still the file it was, by device
  and inode;
- reached by directory descriptors, without following a link at any step.

A second name made and removed between two of those points is not seen; that is
the residual, and the layers in front are what close it. Anything the tripwire
cannot read or check is reported as a problem, never passed.
"""

from __future__ import annotations

import os
import stat
from collections.abc import Iterable

_DIRECTORY = os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW | getattr(os, "O_CLOEXEC", 0)

#: A file's identity: its device and inode.
Identity = tuple[int, int]


def survey(roots: Iterable[str]) -> tuple[dict[str, Identity], list[str]]:
    """Every file under ``roots`` with its identity, and every problem found.

    A problem is a file with more than one name, anything that is neither a
    directory nor a regular file, or anything that could not be read or checked.
    A root that does not exist holds nothing and is no problem.
    """
    files: dict[str, Identity] = {}
    problems: list[str] = []
    for root in roots:
        try:
            info = os.lstat(root)
        except FileNotFoundError:
            continue
        except OSError as exc:
            problems.append(f"{root}: cannot be checked ({exc.strerror})")
            continue
        if stat.S_ISDIR(info.st_mode):
            try:
                fd = os.open(root, _DIRECTORY)
            except OSError as exc:
                problems.append(f"{root}: cannot be opened ({exc.strerror})")
                continue
            try:
                _walk(fd, root, files, problems)
            finally:
                os.close(fd)
        else:
            _judge(root, info, files, problems)
    return files, sorted(problems)


def _walk(fd: int, where: str, files: dict[str, Identity], problems: list[str]) -> None:
    try:
        entries = sorted(os.listdir(fd))
    except OSError as exc:
        problems.append(f"{where}: cannot be listed ({exc.strerror})")
        return
    for name in entries:
        path = os.path.join(where, name)
        try:
            info = os.stat(name, dir_fd=fd, follow_symlinks=False)
        except OSError as exc:
            problems.append(f"{path}: cannot be checked ({exc.strerror})")
            continue
        if stat.S_ISDIR(info.st_mode):
            try:
                child = os.open(name, _DIRECTORY, dir_fd=fd)
            except OSError as exc:
                problems.append(f"{path}: cannot be opened ({exc.strerror})")
                continue
            try:
                _walk(child, path, files, problems)
            finally:
                os.close(child)
        else:
            _judge(path, info, files, problems)


def _judge(
    path: str, info: os.stat_result, files: dict[str, Identity], problems: list[str]
) -> None:
    if not stat.S_ISREG(info.st_mode):
        problems.append(f"{path}: not a regular file")
        return
    if info.st_nlink != 1:
        problems.append(f"{path}: has more than one name ({info.st_nlink})")
    files[path] = (info.st_dev, info.st_ino)


def changed(before: dict[str, Identity], now: dict[str, Identity]) -> list[str]:
    """Every file that is not the one it was: replaced, removed or new."""
    out = [f"{p}: not the file it was" for p in before if p in now and now[p] != before[p]]
    out += [f"{p}: gone" for p in before if p not in now]
    out += [f"{p}: new" for p in now if p not in before]
    return sorted(out)
