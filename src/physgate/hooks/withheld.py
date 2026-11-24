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
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from physgate.hooks.views import ConfigView

_DIRECTORY = os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW | getattr(os, "O_CLOEXEC", 0)

#: A file's identity: its device and inode.
Identity = tuple[int, int]
#: A problem the tripwire found: the path, and what was found there.
Problem = tuple[str, str]


def roots_of(config: ConfigView) -> tuple[str, ...]:
    """Every path a session's configuration keeps from all its reads, which the tripwire holds.

    The held-out tier, the answer-key corpora, and each run record withheld from the session
    (its protected roots that carry the withheld reason, refused to every read).
    """
    from physgate.hooks.reasons import WITHHELD_REASON

    # A withheld directory is kept from every read, but not tripwired: the harness itself puts a
    # link in one (the decomposition's latest round), which the tripwire would take for a second
    # name. A link to one of its files needs its path named, which the hooks refuse.
    records = tuple(
        root.path
        for root in config.protected_roots
        if root.reason == WITHHELD_REASON
        and root.reads == "denied"
        and not os.path.isdir(root.path)
    )
    return (*config.held_out, *config.answer_keys, *records)


def survey(roots: Iterable[str]) -> tuple[dict[str, Identity], list[str]]:
    """Every file under ``roots`` with its identity, and every problem found.

    A problem is a file with more than one name, anything that is neither a
    directory nor a regular file, or anything that could not be read or checked.
    A root that does not exist holds nothing and is no problem.
    """
    files, found = survey_found(roots)
    return files, [f"{path}: {what}" for path, what in found]


def survey_found(roots: Iterable[str]) -> tuple[dict[str, Identity], list[Problem]]:
    """As :func:`survey`, each problem as its path and what was found there, kept apart.

    In :func:`survey`'s order, so that the path can be written as something else.
    """
    files: dict[str, Identity] = {}
    problems: list[Problem] = []
    for root in roots:
        try:
            info = os.lstat(root)
        except FileNotFoundError:
            continue
        except OSError as exc:
            problems.append((root, f"cannot be checked ({exc.strerror})"))
            continue
        if stat.S_ISDIR(info.st_mode):
            try:
                fd = os.open(root, _DIRECTORY)
            except OSError as exc:
                problems.append((root, f"cannot be opened ({exc.strerror})"))
                continue
            try:
                _walk(fd, root, files, problems)
            finally:
                os.close(fd)
        else:
            _judge(root, info, files, problems)
    return files, sorted(problems, key=_joined)


def _joined(problem: Problem) -> str:
    return f"{problem[0]}: {problem[1]}"


def _walk(fd: int, where: str, files: dict[str, Identity], problems: list[Problem]) -> None:
    try:
        entries = sorted(os.listdir(fd))
    except OSError as exc:
        problems.append((where, f"cannot be listed ({exc.strerror})"))
        return
    for name in entries:
        path = os.path.join(where, name)
        try:
            info = os.stat(name, dir_fd=fd, follow_symlinks=False)
        except OSError as exc:
            problems.append((path, f"cannot be checked ({exc.strerror})"))
            continue
        if stat.S_ISDIR(info.st_mode):
            try:
                child = os.open(name, _DIRECTORY, dir_fd=fd)
            except OSError as exc:
                problems.append((path, f"cannot be opened ({exc.strerror})"))
                continue
            try:
                _walk(child, path, files, problems)
            finally:
                os.close(child)
        else:
            _judge(path, info, files, problems)


def _judge(
    path: str, info: os.stat_result, files: dict[str, Identity], problems: list[Problem]
) -> None:
    if not stat.S_ISREG(info.st_mode):
        problems.append((path, "not a regular file"))
        return
    if info.st_nlink != 1:
        problems.append((path, f"has more than one name ({info.st_nlink})"))
    files[path] = (info.st_dev, info.st_ino)


def changed(before: dict[str, Identity], now: dict[str, Identity]) -> list[str]:
    """Every file that is not the one it was: replaced, removed or new."""
    return [f"{path}: {what}" for path, what in changed_found(before, now)]


def changed_found(before: dict[str, Identity], now: dict[str, Identity]) -> list[Problem]:
    """As :func:`changed`, each as its path and what it is now, in :func:`changed`'s order."""
    out = [(p, "not the file it was") for p in before if p in now and now[p] != before[p]]
    out += [(p, "gone") for p in before if p not in now]
    out += [(p, "new") for p in now if p not in before]
    return sorted(out, key=_joined)
