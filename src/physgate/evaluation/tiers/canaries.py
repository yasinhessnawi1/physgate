"""The canaries a session is checked for: every list the harness wrote under a protected root.

A split leaves each protected tier's canaries in a list beside its tasks. A session withholds
protected roots; what it is checked for must cover what it withholds, so the canaries are read
from the same roots: one role's (:func:`root_canaries`), or every role's in a store
(:func:`store_canaries`), which is what an author, a blind check and a baseline round withhold.
Here rather than beside the authoring session, so the baseline runner, which must not import
the scorers, reads them by the same walk.
"""

from __future__ import annotations

import json
import os
import stat
from pathlib import Path
from typing import get_args

from pydantic import TypeAdapter, ValidationError

from physgate.evaluation.tiers.authoring import CANARIES_NAME, AuthoringError
from physgate.evaluation.tiers.store import SESSION_FOLDERS, is_visible_tier, role_root
from physgate.evaluation.tiers.task import Canary, Role

#: How a list is opened: never through a link, never waiting on a pipe's writer.
_READ = os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK
#: The largest canary list read: a few dozen canaries per tier, a few tiers per root.
MOST_CANARY_LIST_BYTES = 1024 * 1024
#: What a canary list holds. A short entry would match nearly any stream, so nothing else
#: passes for one.
_CANARIES: TypeAdapter[list[str]] = TypeAdapter(list[Canary])


def names_a_list(name: str) -> bool:
    """Whether ``name`` is what a canary list is called, in any case.

    The harness writes lower case, but a disk that ignores case opens ``Canaries.json`` by
    that name all the same.
    """
    folded = name.casefold()
    return folded == CANARIES_NAME or folded.endswith(f".{CANARIES_NAME}")


def _refuse_list(reason: str, path: str, detail: str) -> AuthoringError:
    msg = (
        f"the canary list {path} is {detail}; it is never read as naming no canary, so the "
        "session does not run until it is put right"
    )
    return AuthoringError(msg, refused_because=reason, path=path)


def _canary_list(path: str) -> set[str]:
    """The canaries one list names, read whole through a descriptor that follows no link.

    Raises:
        AuthoringError: the list is a link, not a regular file with one name, too large or
            unreadable (``canary_list_unreadable``), not a list of canaries, each exactly
            :data:`.task.Canary` (``canary_list_unparsed``), or names none
            (``canary_list_empty``).
    """
    try:
        fd = os.open(path, _READ)
    except OSError as exc:
        raise _refuse_list("canary_list_unreadable", path, f"not readable ({exc})") from exc
    try:
        info = os.fstat(fd)
        if not stat.S_ISREG(info.st_mode) or info.st_nlink != 1:
            raise _refuse_list("canary_list_unreadable", path, "not a file with one name")
        if info.st_size > MOST_CANARY_LIST_BYTES:
            raise _refuse_list("canary_list_unreadable", path, "too large")
        with os.fdopen(os.dup(fd), "rb") as handle:
            data = handle.read(MOST_CANARY_LIST_BYTES + 1)
    except OSError as exc:
        raise _refuse_list("canary_list_unreadable", path, f"not readable ({exc})") from exc
    finally:
        os.close(fd)
    try:
        listed = json.loads(data)
    except (ValueError, RecursionError) as exc:
        raise _refuse_list("canary_list_unparsed", path, "not JSON") from exc
    try:
        _CANARIES.validate_python(listed)
    except ValidationError as exc:
        raise _refuse_list("canary_list_unparsed", path, "not a list of canaries") from exc
    if not listed:
        raise _refuse_list("canary_list_empty", path, "empty")
    return set(listed)


def root_canaries(root: Path) -> tuple[str, ...]:
    """Every canary the lists the harness wrote under ``root`` name; none while it holds none.

    A split leaves each protected tier's list inside the tier, as ``canaries.json``; a list
    named ``<tier>.canaries.json`` beside one is read as well, at any depth, in any case.
    The session folders at the root's top (:data:`.tiers.store.SESSION_FOLDERS`) are not
    entered: what a session wrote is no list of ours, and the pool's tasks carry no canary,
    which is given at the split. Of everything else only names are looked at, by the runner,
    never a task. A link is judged as the list it is named as, and never followed.

    A directory that holds a task (a directory with a ``task.json`` in it) is a tier, and a
    tier holds its list: one that holds a task but no list (the split stopped before its list
    was written, or the list was removed) leaves its canaries unknown, so it refuses rather
    than reading as naming none. A directory that holds no task is no tier. The one tier
    with no canaries is a version's visible tier, known by its place alone
    (``<root>/<version>/visible``, :func:`.tiers.store.is_visible_tier`); a list-less tier
    anywhere else, a version being written included, refuses.

    Raises:
        AuthoringError: a list cannot be taken whole (:func:`_canary_list`), a directory that
            could hold one cannot be listed (``canary_list_unreadable``), or a tier holds no
            list (``canary_list_missing``).
    """

    def unlisted(exc: OSError) -> None:
        msg = f"{exc.filename} cannot be listed, so a canary list in it cannot be ruled out"
        raise AuthoringError(
            msg, refused_because="canary_list_unreadable", path=str(exc.filename)
        ) from exc

    if not root.is_dir():
        return ()
    found: set[str] = set()
    tiers: set[str] = set()
    listed: set[str] = set()
    for where, directories, files in os.walk(root, onerror=unlisted):
        if where == str(root):
            directories[:] = [d for d in directories if d not in SESSION_FOLDERS]
        elif any(name.casefold() == "task.json" for name in files):
            tier = os.path.dirname(where)
            if not (is_visible_tier(Path(tier)) and Path(tier).parent.parent == root):
                tiers.add(tier)
        for name in sorted((*directories, *files)):
            if names_a_list(name):
                found |= _canary_list(str(Path(where) / name))
                listed.add(where)
    unlisted_tiers = sorted(tiers - listed)
    if unlisted_tiers:
        msg = (
            f"{unlisted_tiers[0]} holds tasks but no canary list, so its canaries cannot be "
            "looked for; it is never read as naming none"
        )
        raise AuthoringError(msg, refused_because="canary_list_missing", path=unlisted_tiers[0])
    return tuple(sorted(found))


def store_canaries(store: Path) -> tuple[str, ...]:
    """Every canary every role's root in ``store`` names.

    What a session that withholds the whole store must look for.

    Raises:
        AuthoringError: any role's walk refuses (:func:`root_canaries`).
    """
    found: set[str] = set()
    for role in get_args(Role):
        found |= set(root_canaries(role_root(store, role)))
    return tuple(sorted(found))
