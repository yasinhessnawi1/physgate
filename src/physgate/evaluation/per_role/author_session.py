"""The own tasks' authoring session, and the blind check of the held-out tier, end to end.

Both work on a tier-set store (:mod:`.tiers.store`): the role's root in it, ``<store>/<role>``,
holds every version of the role's tiers and, under its withheld root (``withheld/``), the
round's pool and the sessions' streams; every session started on it withholds the role's root,
and every run that names a tier of it withholds the withheld root.

**Authoring.** A session, on a model that is not the implementers', is given the author
brief and nothing else, and works in a fresh directory outside every held-out root (the
``baseline`` profile it runs under refuses those roots). Before it starts, the store is
looked at for what only a split in progress holds: another role's pool, a spent pool, or a
version still being written holds tasks that become held-out ones with no canary yet, and
nothing starts while one is there. The role's root is surveyed as the session's tripwire will
survey it: a link or an unreadable file anywhere under it would have the session refused
every tool call, so the runner refuses first, at no cost. It refuses too unless the session
looks for every canary that the lists the harness wrote under the root name, at any depth
(:func:`root_canaries`), and a list that cannot be taken whole, a directory that cannot be
listed, or a tier that holds tasks but no list, is never read as naming none.
While it runs, a checkpoint on the budget watch holds each task to its references as soon as
it is written (on a copy, never in the worktree), and stops the session when no task holds
after a quarter of the cap, or when more than a task's worth of tokens has gone by since the
last task came to hold. When it ends, the runner closes the checkpoint, so a call of it that
outlived the session changes nothing; a session its watch could not hold to its cap
(``WATCH_FAILURES``), or whose stream showed a held-out canary however it ended (or cannot
say, where the root names canaries), is refused, and only step 5 runs. So is a session under
whose root the canaries grew while it ran, or a list can no longer be taken whole or has gone:
it was not looking for what came, so its record cannot say it saw none of it. Otherwise the
runner:

1. copies each task it left into a staging directory beside its work, refusing a task
   that holds a link, a special file, a canary list's name, more than a task's worth of
   entries or depth, or whose copy fails;
2. holds every staged task to the split's own entry check, its references and its brief
   (:func:`.validate.sound`), and never prints one: what leaves is counts and digests;
3. moves every task that holds into the role's pool (a task whose id, however spelt, is
   already there is refused), so nothing a session wrote well is lost to a short session;
   there is no self-check inside the session in round 1;
4. once the pool holds the three tiers' worth, draws that many by the seed and writes them as
   a new version, split by the same seed (:func:`.tiers.store.write_version`): written whole
   under a temporary name and renamed last, with its manifest and the round's provenance
   record; the pool is then removed, with the tasks the draw did not take. Otherwise it says
   how many are pooled, and a further session adds to them;
5. copies the session's stream and record under the withheld root, since they hold every
   task the session wrote, as regular files only (the session's own links, such as its
   interpreter's, would trip the next session's tripwire), notes the session in the pool for
   the provenance record, and removes the work.

**The blind check.** A second session, on a model that is not the implementers' either,
reads a version's held-out tasks from a file placed in its own work directory (never its
prompt, which any process of the same user can list), keyed by the digest of each id, without
their references or canaries. It answers three questions per task with true or false and
nothing else. Its answer is read strictly: anything but those booleans for exactly those
keys is no answer. It is held to the store and the canaries as the author is: it runs only
looking for every canary under the role's root, and a check whose stream showed one (or
cannot say it did not), or under whose root they grew while it ran, gives no answer. Its
stream is kept under the withheld root as well. What leaves is counts and the digests of the
tasks with a ``false``.

Both are tested against the scripted endpoint; a real session is started by a person.
"""

from __future__ import annotations

import hashlib
import json
import os
import random
import shutil
import stat
import threading
import uuid
from collections.abc import Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from pydantic import BaseModel, ConfigDict, RootModel, TypeAdapter, ValidationError

from physgate.evaluation.per_role.arms.raw import WATCH_FAILURES, RawSetup, run_session
from physgate.evaluation.per_role.firmware.sandbox import open_directory
from physgate.evaluation.per_role.validate import id_digest, refusal_reasons, sound, validate
from physgate.evaluation.tiers.authoring import (
    CANARIES_NAME,
    PER_TIER,
    TIERS,
    AuthoringError,
    author_brief,
    require_author_model,
)
from physgate.evaluation.tiers.manifest import read_version
from physgate.evaluation.tiers.store import (
    AUTHOR_EVIDENCE,
    CHECK_EVIDENCE,
    SESSION_FOLDERS,
    WORKING,
    author_evidence,
    check_evidence,
    is_visible_tier,
    leftover_refusal,
    pool_dir,
    protected_tier_refusal,
    role_root,
    spelling_refusal,
    version_dir,
    withheld_refusal,
    work_root,
    write_version,
)
from physgate.evaluation.tiers.task import Canary, Role, canonical_json, fold_id, load_task
from physgate.hooks.withheld import survey

_READ = os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK
_NEW = os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW

#: The most entries (files and directories) and bytes one staged task may hold: a task, a
#: good reference and a few bad ones, each a small JSON file.
MOST_FILES_PER_TASK = 64
MOST_BYTES_PER_TASK = 2 * 1024 * 1024
#: The deepest a directory in a task lies below it: ``references/<reference>/`` and an
#: answer's own few levels. Nothing deeper is opened.
MOST_DEPTH_PER_TASK = 8

#: The most tokens one authoring session may be capped at, every class counted. Tasks are
#: pooled as they are written, so a session is short and a further one adds to it; the
#: one session that ran unbounded spent 80 M tokens on a loop that wrote nothing.
MOST_CAP = 8_000_000
#: The share of the cap a session may spend before its first task must hold.
FIRST_TASK_SHARE = 4


@dataclass(frozen=True)
class AuthoringPlan:
    """Where one authoring session works, and the tier-set store its version goes into."""

    role: Role
    implementer_model: str
    #: A directory that does not exist yet, outside every held-out root.
    work: Path
    #: The tier-set store. The role's root in it (:attr:`root`) holds the pool, the sessions'
    #: streams and every version, and the session withholds it.
    store: Path
    seed: int
    #: The session's token cap, at most :data:`MOST_CAP`.
    cap: int
    #: How many tasks the session is asked for; the pool decides when the tiers are cut.
    count: int = len(TIERS) * PER_TIER
    #: The most tokens the session may spend between one task coming to hold and the next
    #: (and before the first, within the first quarter of the cap); an eighth of the cap
    #: when not given.
    per_task_cap: int | None = None
    #: What every id the session writes begins with, so two sessions' ids do not collide
    #: in the pool; the author is told it and nothing else about other sessions.
    id_prefix: str = ""

    @property
    def task_cap(self) -> int:
        """The per-task cap in force."""
        return self.cap // 8 if self.per_task_cap is None else self.per_task_cap

    @property
    def root(self) -> Path:
        """The role's protected root in the store."""
        return role_root(self.store, self.role)


def _inside(path: Path, root: Path) -> bool:
    one, other = path.resolve(), root.resolve()
    return one == other or one.is_relative_to(other) or other.is_relative_to(one)


def _withheld(path: Path, roots: Sequence[Path]) -> bool:
    """Whether ``path`` is one of ``roots`` or inside one."""
    return any(path.resolve().is_relative_to(r.resolve()) for r in roots)


def _require_apart(plan: AuthoringPlan, setup: RawSetup) -> None:
    roots = [Path(r) for r in (*setup.held_out, *setup.withheld_reads)]
    if not _withheld(plan.root, [Path(r) for r in setup.held_out]):
        msg = "the session does not withhold the protected root the tiers are cut in"
        raise AuthoringError(msg, root=str(plan.root))
    if any(_inside(plan.work, r) for r in roots):
        msg = "the work is inside a held-out root, or holds one"
        raise AuthoringError(msg, path=str(plan.work))
    for name, path in (("work", plan.work), ("tier-set store", plan.store)):
        if path.resolve() != path.absolute():
            msg = f"the {name} is reached through a link; give its resolved path"
            raise AuthoringError(msg, path=str(path))
    if plan.work.exists():
        msg = "the work directory is made new for each session"
        raise AuthoringError(msg, work=str(plan.work))
    if plan.count < 1:
        msg = "a session is asked for at least one task"
        raise AuthoringError(msg, count=str(plan.count))
    if not 0 < plan.cap <= MOST_CAP:
        msg = f"an authoring session's cap is at most {MOST_CAP} tokens; tasks are pooled"
        raise AuthoringError(msg, cap=str(plan.cap))
    if not 0 < plan.task_cap <= plan.cap:
        msg = "the per-task cap is positive and no more than the session's cap"
        raise AuthoringError(msg, per_task_cap=str(plan.task_cap))


def _require_no_work_left(root: Path) -> None:
    """Refuse while an earlier author's or check's work may still lie outside ``root``.

    Each records, inside the protected root, that its work is out before its session starts,
    and clears the record only once that work is kept inside the root and removed
    (:func:`_working`). A record still there means a runner stopped before that, so the work
    it names (tasks before they are pooled, or the check's copy of the held-out tasks, with no
    canary) may be where any session can read it. It is never guessed away: a person looks at
    the work it names, removes what is left, and removes the record.

    Raises:
        AuthoringError: ``work_left``, naming the record and the work.
    """
    if not root.is_dir():
        return
    for record in sorted(root.iterdir()):
        if not record.name.endswith(WORKING):
            continue
        try:
            work = str(json.loads(record.read_text())["work"])
        except (OSError, ValueError, KeyError, TypeError):
            work = "(the record cannot be read)"
        msg = (
            f"{record} says a session's work was left outside the protected root at {work}; "
            "look at it, remove what is left there and then the record, before anything runs"
        )
        raise AuthoringError(msg, refused_because="work_left", work=work, record=str(record))


def _require_nothing_left(store: Path, continuing: Path | None = None) -> None:
    """Refuse while the store holds what only a split in progress holds, or work left.

    A pool, a version still being written, or a record of a session's work out of a role's
    root holds or points at tasks that are or become held-out and validation ones, with no
    canary: the next session to start must not be one that could read them
    (:func:`.tiers.store.leftovers`). ``continuing`` is the one pool an author may add to, its
    own role's, which its session withholds; no other session is given one.

    Raises:
        AuthoringError: ``pool_left``, ``temporary_version_left``, ``work_left`` or
            ``store_unreadable``.
    """
    refusal = leftover_refusal(store, continuing=continuing)
    if refusal is not None:
        raise AuthoringError(refusal[1], refused_because=refusal[0], store=str(store))


def _require_withheld_as_a_run(store: Path, role: Role, setup: RawSetup) -> None:
    """Refuse a check whose session does not withhold what a run on the role's root must.

    The role's withheld root and the validation and held-out tiers of every version under the
    role's root, each spelt as on disk (:func:`.tiers.store.withheld_refusal`,
    :func:`.tiers.store.protected_tier_refusal`, :func:`.tiers.store.spelling_refusal`).

    Raises:
        AuthoringError: ``held_out_not_spelt_as_on_disk``, ``withheld_root_not_named``,
            ``protected_tier_not_named`` or ``store_unreadable``.
    """
    also = [(store, role)]
    for judge in (spelling_refusal, withheld_refusal, protected_tier_refusal):
        refusal = judge(setup.held_out, also=also)
        if refusal is not None:
            raise AuthoringError(refusal[1], refused_because=refusal[0], store=str(store))


def _working(root: Path, name: str, work: Path) -> Path:
    """Record inside ``root`` that ``work`` is out of it; the record, to clear once secured."""
    root.mkdir(mode=0o700, parents=True, exist_ok=True)
    record = root / f"{name}{WORKING}"
    fd = os.open(record, _NEW, 0o600)
    try:
        os.write(fd, (json.dumps({"work": str(work)}) + "\n").encode())
    finally:
        os.close(fd)
    return record


def _require_clear(root: Path) -> None:
    """Refuse before any session if the protected root would trip the session's tripwire.

    The session withholds the root, and its tripwire refuses every tool call while any
    file under the root has a second name, is not a regular file, or cannot be checked
    (:func:`physgate.hooks.withheld.survey`). A session refused every call writes nothing
    and spends its whole cap finding that out, so the same survey runs here first.

    Raises:
        AuthoringError: the survey found a problem; it is named, so it can be removed.
    """
    _, problems = survey([str(root)])
    if problems:
        msg = (
            "the protected root would have the session refused every tool call; "
            "remove these first: " + "; ".join(problems)
        )
        raise AuthoringError(msg, root=str(root), problems=" | ".join(problems))


#: The largest canary list read: a few dozen canaries per tier, a few tiers per root.
MOST_CANARY_LIST_BYTES = 1024 * 1024
#: What a canary list holds. A short entry would match nearly any stream, so nothing else
#: passes for one.
_CANARIES: TypeAdapter[list[str]] = TypeAdapter(list[Canary])


def _names_a_list(name: str) -> bool:
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
            if _names_a_list(name):
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


def _require_looking(canaries: Sequence[str], setup: RawSetup) -> None:
    """Refuse a session that would not look for every one of ``canaries``.

    Raises:
        AuthoringError: ``canaries_missing``, with how many.
    """
    missing = set(canaries) - set(setup.held_out_canaries)
    if missing:
        msg = (
            f"the session would not look for {len(missing)} of the canaries its protected "
            "root names, so its record could not say whether it saw a held-out task"
        )
        raise AuthoringError(msg, refused_because="canaries_missing", missing=str(len(missing)))


def _require_unseen(record: dict[str, Any], canaries: Sequence[str], taken: str) -> None:
    """Refuse what a session left, unless its record says it saw no canary of its root's.

    The record must say no held-out canary showed in the stream; it may say it cannot tell
    only where there was none to look for. ``taken`` says what is then not taken from it.

    Raises:
        AuthoringError: ``held_out_seen``.
    """
    seen = record.get("held_out_seen", "unrecorded")
    if seen is not False and not (seen is None and not canaries):
        msg = f"the session's stream showed a held-out canary (held_out_seen); {taken}"
        raise AuthoringError(msg, end=str(record.get("end")), refused_because="held_out_seen")


def _require_none_came(root: Path, canaries: Sequence[str], taken: str) -> None:
    """Refuse what a session left if its root's canaries changed while it ran.

    The root is walked again: a list that came while the session ran names canaries it was
    not looking for, so its record says nothing of them, and a list that can no longer be
    taken whole, or has gone, refuses as it does before the session.

    Raises:
        AuthoringError: ``canaries_missing``, or a list's own reason.
    """
    grown = set(root_canaries(root)) - set(canaries)
    if grown:
        msg = (
            f"the protected root came to name {len(grown)} canaries while the session ran "
            f"that it was not looking for; {taken}"
        )
        raise AuthoringError(msg, refused_because="canaries_missing", missing=str(len(grown)))


class _NotPlainError(Exception):
    """A staged task holds what no task may: not a plain, singly named entry, or a list's name."""


def _classify(name: str, dir_fd: int) -> os.stat_result:
    """What ``name`` is, under ``dir_fd``, without following it: the listing's view only.

    Only the type decides how the entry is opened; whatever it is opened as is checked
    again on the descriptor, since the entry can be replaced between here and the open.
    """
    return os.stat(name, dir_fd=dir_fd, follow_symlinks=False)


def _new_file(name: str, dir_fd: int) -> int:
    """A file made new as ``name`` under ``dir_fd``: never one already there, never a link."""
    return os.open(name, _NEW, 0o600, dir_fd=dir_fd)


def _copy_into(source_fd: int, target_fd: int, budget: list[int]) -> None:
    """Copy the task directory ``source_fd`` into the empty directory ``target_fd``, by content.

    ``budget`` is the entries (files and directories) and bytes the task may still hold, and
    no directory deeper than :data:`MOST_DEPTH_PER_TASK` below the task is opened. The session
    may be writing the task while it is copied: an entry it removed between the listing and
    the look at it is no longer part of the task, and is left out of the copy, as a task is
    from the listing.

    Raises:
        _NotPlainError: an entry is a link of either kind, a special file, past the budget or
            the depth, or named as a canary list, which must not reach the pool or a tier.
    """
    _copy_level(source_fd, target_fd, budget, 1)


def _copy_level(source_fd: int, target_fd: int, budget: list[int], depth: int) -> None:
    """:func:`_copy_into` for the entries ``depth`` levels below the task."""
    for name in sorted(os.listdir(source_fd)):
        if _names_a_list(name):
            raise _NotPlainError(name)
        try:
            kind = _classify(name, source_fd).st_mode
        except FileNotFoundError:
            continue
        if stat.S_ISDIR(kind):
            # Counted, and judged for its depth, before it is opened.
            budget[0] -= 1
            if budget[0] < 0 or depth > MOST_DEPTH_PER_TASK:
                raise _NotPlainError(name)
            try:
                child = open_directory(name, source_fd)
            except OSError as exc:
                raise _NotPlainError(name) from exc
            try:
                os.mkdir(name, 0o700, dir_fd=target_fd)
                made = open_directory(name, target_fd)
                try:
                    _copy_level(child, made, budget, depth + 1)
                finally:
                    os.close(made)
            finally:
                os.close(child)
            continue
        if not stat.S_ISREG(kind):
            raise _NotPlainError(name)
        try:
            fd = os.open(name, _READ, dir_fd=source_fd)
        except OSError as exc:  # replaced by a link or a FIFO since it was listed
            raise _NotPlainError(name) from exc
        try:
            info = os.fstat(fd)
            if not stat.S_ISREG(info.st_mode) or info.st_nlink != 1:
                raise _NotPlainError(name)
            budget[0] -= 1
            budget[1] -= info.st_size
            if budget[0] < 0 or budget[1] < 0:
                raise _NotPlainError(name)
            with os.fdopen(os.dup(fd), "rb") as handle:
                data = handle.read(MOST_BYTES_PER_TASK + 1)
        finally:
            os.close(fd)
        try:
            out = _new_file(name, target_fd)
        except OSError as exc:  # something stands where the copy goes
            raise _NotPlainError(name) from exc
        try:
            os.write(out, data)
        finally:
            os.close(out)


def _stage_one(name: str, source: int, target: int) -> bool:
    """Copy the task directory ``name`` under ``source`` into ``target``; whether it was taken.

    A task holding a symbolic or a hard link, a special file, a canary list's name or more
    than a task's worth or depth, or named as a list itself, is refused, and what was copied
    of it removed. So is a task whose copy fails on the way (the disk, a recursion): a
    failure while one task is copied refuses that task, and never ends staging (or, in the
    checkpoint, the watch). A task's id is its directory's name, or the task does not hold.

    Raises:
        OSError: what was copied of a refused task cannot be removed, so the staging
            directory cannot be trusted to hold whole tasks only.
    """
    if _names_a_list(name):
        return False
    try:
        task = open_directory(name, source)
    except OSError:
        return False
    try:
        os.mkdir(name, 0o700, dir_fd=target)
        made = open_directory(name, target)
        try:
            _copy_into(task, made, [MOST_FILES_PER_TASK, MOST_BYTES_PER_TASK])
        except (_NotPlainError, OSError, RecursionError):
            shutil.rmtree(name, dir_fd=target)
            return False
        finally:
            os.close(made)
    finally:
        os.close(task)
    return True


def _task_names(source: int) -> list[str]:
    """The top-level directories under ``source``, those whose names begin with a dot aside.

    The session writes the directory while it is listed, by the checkpoint as it runs: an
    entry removed between the listing and the look at it is no longer a task, and is left
    out rather than ending the listing (and with it the checkpoint and the watch).
    """
    names = []
    for name in sorted(os.listdir(source)):
        if name.startswith("."):
            continue
        try:
            kind = _classify(name, source).st_mode
        except FileNotFoundError:
            continue
        if stat.S_ISDIR(kind):
            names.append(name)
    return names


def stage(worktree: Path, staging: Path, only: Sequence[str] | None = None) -> int:
    """Copy each task directory the session left into ``staging``; how many were refused.

    Everything is reached through descriptors, never by a path checked and then opened:
    the worktree and each directory in it are opened without following a link and checked
    on the descriptor (:func:`.firmware.sandbox.open_directory`); each file is opened the
    same way and checked on its descriptor to be a regular file with one name; each copy
    is a file made new under the staging directory's descriptor. Only top-level
    directories are looked at, those whose names begin with a dot aside, and only those
    named in ``only`` when it is given. A task holding a symbolic or a hard link, a special
    file, a canary list's name or more than a task's worth is refused, and what was copied
    of it removed.

    Raises:
        OSError: the staging directory cannot be made new (something stands there).
    """
    staging.mkdir(mode=0o700)
    target = open_directory(str(staging))
    source = open_directory(str(worktree))
    refused = 0
    try:
        for name in _task_names(source):
            if only is not None and name not in only:
                continue
            if not _stage_one(name, source, target):
                refused += 1
    finally:
        os.close(source)
        os.close(target)
    return refused


# ------------------------------------------------------------------ the checkpoint

#: A task directory's files as last seen: each file's path, size and modification time.
_Signature = tuple[tuple[str, int, int], ...]


#: What a look past a task's bounds ends with: the task is more than a task, so staging
#: will refuse it, and it is not walked further.
_OVER: tuple[str, int, int] = ("…", -1, -1)


def _signature(directory: Path) -> _Signature:
    """Each file of the task under ``directory``, with its size and time, within its bounds.

    The walk takes the budget and the depth staging takes (:data:`MOST_FILES_PER_TASK`,
    :data:`MOST_DEPTH_PER_TASK`): past either, it ends with :data:`_OVER` instead of going on,
    so a task too large to stage is never walked whole by the watch.
    """
    seen: list[tuple[str, int, int]] = []
    left = MOST_FILES_PER_TASK
    for here, dirs, files in os.walk(directory, followlinks=False):
        relative_here = os.path.relpath(here, directory)
        depth = 0 if relative_here == "." else relative_here.count(os.sep) + 1
        dirs.sort()
        left -= len(dirs)
        if depth + 1 > MOST_DEPTH_PER_TASK and dirs:
            dirs[:] = []
            seen.append(_OVER)
            return tuple(seen)
        for name in sorted(files):
            left -= 1
            if left < 0:
                seen.append(_OVER)
                return tuple(seen)
            try:
                info = os.lstat(Path(here) / name)
            except OSError:
                continue
            relative = os.path.relpath(Path(here) / name, directory)
            seen.append((relative, info.st_size, info.st_mtime_ns))
        if left < 0:
            seen.append(_OVER)
            return tuple(seen)
    return tuple(seen)


class AuthorProgress:
    """The budget watch's checkpoint for an author: tasks held as they are written.

    At each reading, every top-level directory of the worktree whose files are not as last
    seen is staged by content into a scratch directory of its own and held to its
    references and its brief (:func:`.validate.sound`), as the runner will hold it at the
    end; the scorer never runs in the worktree, and the copy is removed. The session is
    stopped for one of two reasons:

    - ``no_task_held``: no task holds and more than a quarter of the cap is spent;
    - ``task_cap``: more than the per-task cap is spent since the last task came to hold.

    What it counts is what the runner keeps: a task written and then broken is no longer
    held. Nothing of a task leaves this object but its directory name's presence in
    ``held``, for the record's count.

    A call runs on the watch's thread, and one that hangs outlives the stop of the session.
    Once the session is over the runner closes it (:meth:`close`), and from then on no call
    writes a copy, removes one or changes ``held``: what the runner reads and removes is
    the session's alone.
    """

    def __init__(self, worktree: Path, scratch: Path, *, cap: int, per_task: int):
        """Watch the tasks under ``worktree``, checking each in ``scratch``."""
        self.worktree, self.scratch = worktree, scratch
        self.cap, self.per_task = cap, per_task
        self.held: set[str] = set()
        self.checked = 0
        self._seen: dict[str, _Signature] = {}
        #: The count when the last task came to hold; none yet while the quarter governs.
        self._held_at: int | None = None
        self._n = 0
        #: Held while a copy is written or removed and while ``held`` changes, never while
        #: the scorer runs: a close waits for a copy, never for a scorer that hangs.
        self._lock = threading.Lock()
        self._closed = False

    @property
    def closed(self) -> bool:
        """Whether the session is over, so that no call changes anything any more."""
        return self._closed

    def close(self) -> int:
        """Take no further reading, once the session is over; how many tasks held then.

        A call still in progress changes nothing after this: it copies no further task,
        leaves the copy it made for the runner's removal of the work, and records nothing.
        """
        with self._lock:
            self._closed = True
            return len(self.held)

    def examine(self) -> None:
        """Hold every task directory that changed since it was last seen."""
        try:
            source = open_directory(str(self.worktree))
        except OSError:
            return
        try:
            names = _task_names(source)
            for name in names:
                signature = _signature(self.worktree / name)
                if self._seen.get(name) == signature:
                    continue
                with self._lock:
                    if self._closed:
                        return
                    self._seen[name] = signature
                    self.checked += 1
                    self._n += 1
                    copy = self.scratch / f"check-{self._n}"
                    self.scratch.mkdir(mode=0o700, exist_ok=True)
                    try:
                        staged = stage(self.worktree, copy, only=[name]) == 0
                    except BaseException:
                        shutil.rmtree(copy, ignore_errors=True)
                        raise
                try:
                    holds = staged and (copy / name).is_dir() and name in sound(copy)
                except BaseException:
                    with self._lock:
                        if not self._closed:
                            shutil.rmtree(copy, ignore_errors=True)
                    raise
                with self._lock:
                    if self._closed:
                        # The session is over: the copy is the runner's to remove with the
                        # work, and what this call found is not counted.
                        return
                    shutil.rmtree(copy, ignore_errors=True)
                    if holds:
                        self.held.add(name)
                    else:
                        self.held.discard(name)
        finally:
            os.close(source)
        with self._lock:
            if not self._closed:
                self.held &= set(names)

    def check(self, total: int) -> str | None:
        """The watch's checkpoint: a reason to stop the session at ``total`` tokens, or none."""
        before = len(self.held)
        self.examine()
        if len(self.held) > before:
            self._held_at = total
        if self._held_at is None:
            return "no_task_held" if total > self.cap // FIRST_TASK_SHARE else None
        return "task_cap" if total - self._held_at > self.per_task else None


def _remove(path: Path) -> str | None:
    """Remove ``path`` if it is there; the reason if it could not be, never silently."""
    if not path.exists() and not path.is_symlink():
        return None
    try:
        shutil.rmtree(path)
    except OSError as exc:
        return f"{path}: {exc}"
    return None if not path.exists() else f"{path}: still there"


def _copy_regular(source: Path, target: Path, dropped: list[str]) -> None:
    """Copy the directories and single-named regular files under ``source`` into ``target``.

    Everything else (a link of either kind, a special file, anything unreadable) is left
    behind and named in ``dropped``: the target goes inside a protected root, where any
    such entry would have every later session refused every tool call.
    """
    target.mkdir(mode=0o700)
    for entry in sorted(os.scandir(source), key=lambda e: e.name):
        if entry.is_dir(follow_symlinks=False):
            _copy_regular(Path(entry.path), target / entry.name, dropped)
            continue
        try:
            fd = os.open(entry.path, _READ)
        except OSError:
            dropped.append(entry.path)
            continue
        try:
            info = os.fstat(fd)
            if not stat.S_ISREG(info.st_mode) or info.st_nlink != 1:
                dropped.append(entry.path)
                continue
            with os.fdopen(os.dup(fd), "rb") as handle:
                data = handle.read()
        finally:
            os.close(fd)
        out = os.open(target / entry.name, _NEW, 0o600)
        try:
            os.write(out, data)
        finally:
            os.close(out)


def _keep_evidence(work: Path, record: dict[str, Any] | None, into: Path) -> list[str | None]:
    """Copy the session's stream and record inside the protected root, then drop ``work``.

    Run however the session or what follows it ended: what the session wrote holds tasks
    that may become held-out ones, so it never stays outside the protected root. Only
    regular files with one name are copied: the session directory also holds links (its
    interpreter's, under ``bin``), and a link inside the protected root trips the next
    session's tripwire on every call. What was left behind is named in the record. A
    session that left no record is kept under a name of its own. Every step is tried; what
    could not be done is returned, for the caller to refuse on.
    """
    problems: list[str | None] = []
    name = str(record["session_id"]) if record else f"unrecorded-{uuid.uuid4().hex[:12]}"
    target = into / name
    dropped: list[str] = []
    try:
        into.mkdir(mode=0o700, parents=True, exist_ok=True)
        if (work / "session").is_dir():
            _copy_regular(work / "session", target, dropped)
        else:
            target.mkdir(mode=0o700)
        kept = {**(record or {}), "evidence_dropped": sorted(dropped)}
        (target / "record.json").write_text(json.dumps(kept, sort_keys=True, indent=1))
    except OSError as exc:
        problems.append(f"the session's stream into {target}: {exc}")
    problems.append(_remove(work))
    return problems


def _closed(problems: Sequence[str | None]) -> None:
    """Refuse, loudly, if anything that could hold a task was left where it could be read.

    Raises:
        AuthoringError: a removal failed: say where, and report no result.
    """
    left = [p for p in problems if p is not None]
    if left:
        msg = (
            "what the session wrote could not be removed, so a held-out task may be readable "
            "outside the protected root; remove these by hand before anything else runs: "
            + "; ".join(left)
        )
        raise AuthoringError(msg, left=" | ".join(left))


def _spent(record: dict[str, Any]) -> dict[str, Any]:
    return {key: record.get(key) for key in ("end", "tokens", "cap", "wall_clock_s")}


def _pool(staging: Path, held: Sequence[str], pool: Path) -> tuple[int, int]:
    """Move each held task from ``staging`` into ``pool``; how many went in, how many were there.

    A task is there already when its id, folded (:func:`.task.fold_id`), is one the pool
    holds: the split refuses two such ids, so the pool never takes a second.
    """
    pool.mkdir(mode=0o700, parents=True, exist_ok=True)
    taken = {fold_id(p.name) for p in pool.iterdir() if p.is_dir()}
    added = already = 0
    for name in sorted(held):
        if fold_id(name) in taken or os.path.lexists(pool / name):
            already += 1
            continue
        shutil.move(str(staging / name), str(pool / name))
        taken.add(fold_id(name))
        added += 1
    return added, already


#: Where the pool records each session of its round, for the version's provenance record.
SESSIONS = ".sessions.jsonl"
#: What the provenance says of what the session record does not carry.
NOT_RECORDED = "not recorded by the session record"


def _note_session(pool: Path, kept: Path, record: dict[str, Any]) -> None:
    """Record, in the pool, one session of the round and the digest of every file it left.

    The pool lasts as long as the round, so what it holds when the tiers are cut is every
    session of that round: the version's provenance record (session ids, ends, spend, and
    the digest of each file of its stream, as kept inside the protected root).
    """
    files = {
        p.relative_to(kept).as_posix(): hashlib.sha256(p.read_bytes()).hexdigest()
        for p in sorted(kept.rglob("*"))
        if p.is_file() and not p.is_symlink()
    }
    line = {
        **{key: record.get(key) for key in ("session_id", "end", "tokens", "cap", "wall_clock_s")},
        "held_out_seen": record.get("held_out_seen"),
        "files": files,
        # The session record carries neither, so the provenance says so rather than leave
        # a reader to take their absence for a count of none or a clean scan.
        "turns": NOT_RECORDED,
        "secret_scan": NOT_RECORDED,
    }
    pool.mkdir(mode=0o700, parents=True, exist_ok=True)
    fd = os.open(pool / SESSIONS, os.O_WRONLY | os.O_CREAT | os.O_APPEND | os.O_NOFOLLOW, 0o600)
    try:
        os.write(fd, canonical_json(line))
    finally:
        os.close(fd)


def _provenance(pool: Path) -> bytes:
    """The round's provenance record: every session the pool noted, in order."""
    path = pool / SESSIONS
    lines = path.read_text().splitlines() if path.is_file() else []
    return canonical_json({"sessions": [json.loads(line) for line in lines]})


def _draw(pool: Path, seed: int) -> list[str]:
    """The three tiers' worth of the pool's tasks, by ``seed``, or nothing while it holds fewer."""
    names = sorted(p.name for p in pool.iterdir() if p.is_dir()) if pool.is_dir() else []
    if len(names) < len(TIERS) * PER_TIER:
        return []
    random.Random(seed).shuffle(names)
    return names[: len(TIERS) * PER_TIER]


#: What is not taken from a session its record or its root refuses.
NOT_POOLED = "none of the tasks it wrote is pooled"


def author(plan: AuthoringPlan, setup: RawSetup) -> dict[str, Any]:
    """Run one authoring session, pool the tasks that hold, and cut a version once it can.

    Returns what may be shown: counts, what the session spent, how many tasks are pooled,
    and once a version is cut its id, the visible tier's ids and the protected tiers' counts
    and digests.

    Raises:
        AuthoringError: the author's model is the implementers', the work is inside a held-out
            root or already exists, the cap is over :data:`MOST_CAP`, the session does not
            withhold the role's root, the store holds a pool other than this role's or a
            version still being written (``pool_left``, ``temporary_version_left``), work an
            earlier session left is recorded (``work_left``), the root would trip the
            session's tripwire, a canary list under the root cannot be taken whole, a tier
            there holds none, or a list names a canary the session would not look for, or the
            session's watch could not hold it to its cap, its stream showed a held-out
            canary, or the root's canaries grew while it ran or a list can no longer be taken
            whole or has gone (none of its tasks is pooled; ``refused_because`` says which).
    """
    require_author_model(setup.model, plan.implementer_model)
    _require_apart(plan, setup)
    root = plan.root
    _require_no_work_left(root)
    _require_nothing_left(plan.store, continuing=pool_dir(plan.store, plan.role))
    canaries = root_canaries(root)
    _require_looking(canaries, setup)
    _require_clear(root)
    evidence = author_evidence(plan.store, plan.role)
    pool = pool_dir(plan.store, plan.role)
    record: dict[str, Any] | None = None
    progress = AuthorProgress(
        plan.work / "worktree", plan.work / "checks", cap=plan.cap, per_task=plan.task_cap
    )
    working = _working(root, AUTHOR_EVIDENCE, plan.work)
    try:
        try:
            record = run_session(
                author_brief(plan.role, count=plan.count, id_prefix=plan.id_prefix),
                setup,
                plan.work,
                cap=plan.cap,
                check=progress.check,
            )
        finally:
            # However the session ended: a checkpoint call that outlived it changes nothing
            # from here on.
            held_while_running = progress.close()
        # A held-out canary showed in the session's stream, or the record cannot say it did
        # not while the root names canaries (it is unknown only where there is none to look
        # for): what the session wrote may hold what it saw, however it ended, so none of its
        # tasks is taken. Its stream is still secured below.
        _require_unseen(record, canaries, NOT_POOLED)
        if record["end"] in WATCH_FAILURES:
            # The watch could not hold the session to its cap: what it did was not counted as
            # meant, so none of its tasks is taken. Its stream is still secured below.
            msg = (
                f"the session's watch could not hold it ({record['end']}); none of the tasks "
                "it wrote is pooled"
            )
            raise AuthoringError(msg, end=str(record["end"]), refused_because=str(record["end"]))
        # Another author's split may have left a list under the root while this session ran.
        # Its canaries were not looked for, so the record above says nothing of them, and a
        # session whose withhold failed could have read that tier. The same walk, so a list
        # that can no longer be taken whole, or has gone, refuses here as before the session.
        _require_none_came(root, canaries, NOT_POOLED)
        staging = plan.work / "staging"
        refused = stage(plan.work / "worktree", staging)
        staged = sum(1 for p in staging.iterdir() if p.is_dir())
        held = sound(staging)
        reasons = refusal_reasons(staging)
        added, already = _pool(staging, held, pool)
        if already:
            reasons["id_already_pooled"] = already
        summary: dict[str, Any] = {
            "asked": plan.count,
            "written": staged + refused,
            "refused_as_files": refused,
            "held": len(held),
            "held_while_running": held_while_running,
            "refused_because": reasons,
            "pooled": added,
            "pool": sum(1 for p in pool.iterdir() if p.is_dir()),
            "session": {**_spent(record), "per_task_cap": plan.task_cap},
        }
    finally:
        _closed(_keep_evidence(plan.work, record, evidence))
        working.unlink()
        if record is not None:
            # Every session of the round, however it ended, is in the version's provenance.
            _note_session(pool, evidence / str(record["session_id"]), record)
    chosen = _draw(pool, plan.seed)
    if not chosen:
        return {**summary, "status": "pooled"}
    manifest, placed = write_version(
        root,
        [pool / name for name in chosen],
        role=plan.role,
        seed=plan.seed,
        model=setup.model,
        runtime=setup.claude_version,
        provenance=_provenance(pool),
        retire=pool,
    )
    version = version_dir(plan.store, plan.role, manifest.version)
    return {
        **summary,
        "status": "split",
        "version": manifest.version,
        "pool": 0,
        "left_with_the_pool": summary["pool"] - len(chosen),
        "visible": placed["visible"],
        **{
            f"{name}_{what}": placed[f"{name}_{what}"]
            for name in TIERS[1:]
            for what in ("count", "sha256", "canaries_sha256")
        },
        "visible_check": validate(version / "visible", show_ids=True),
        "validation_check": validate(version / "validation"),
        "held_out_check": validate(version / "held_out"),
    }


# ----------------------------------------------------------------------- the blind check

QUESTIONS = ("states_every_requirement", "unambiguous", "answerable_as_asked")

CHECK_BRIEF = """\
You are checking engineering design tasks before they are used. The file tasks.json in
the directory you work in holds them, each under a key. For each task read its brief, its
inputs, its answer contract and its specifications, and answer three questions:
  - states_every_requirement: does the brief state every specification, with its bound
    and unit, so that a designer reading only the brief knows what is asked?
  - unambiguous: can the brief be read in only one way where it matters for the answer?
  - answerable_as_asked: could a competent designer meet every specification with an
    answer of the stated form?

Write the file answers.json in the directory you work in, and nothing else:
  {{"<key>": {{"states_every_requirement": true or false, "unambiguous": true or false,
             "answerable_as_asked": true or false}}, ...}}
with every key of tasks.json once. Write no explanation in it or anywhere else. There are
{count} tasks.
"""


class _Answer(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid", strict=True)

    states_every_requirement: bool
    unambiguous: bool
    answerable_as_asked: bool


class _Answers(RootModel[dict[str, _Answer]]):
    model_config = ConfigDict(strict=True)


#: The largest answer file read: three booleans for each of a few dozen tasks.
MAX_ANSWERS_BYTES = 64 * 1024


def bundle(tier: Path) -> dict[str, dict[str, Any]]:
    """The tier's tasks as the check reads them: by id digest, without references or canary.

    Raises:
        PerRoleError: a task in the tier does not load.
    """
    found: dict[str, dict[str, Any]] = {}
    for entry in sorted(p for p in tier.iterdir() if p.is_dir()):
        task = load_task(entry).task
        found[id_digest(task.id)] = {
            "brief": task.brief,
            "inputs": [m.model_dump(mode="json") for m in task.inputs],
            "answer": task.answer.model_dump(mode="json"),
            "specs": [s.model_dump(mode="json") for s in task.specs],
        }
    return found


def read_answers(path: Path, keys: Sequence[str]) -> dict[str, _Answer] | None:
    """The check's answers, or ``None`` unless they are booleans for exactly ``keys``."""
    if path.is_symlink() or not path.is_file() or path.stat().st_size > MAX_ANSWERS_BYTES:
        return None
    try:
        answers = _Answers.model_validate_json(path.read_bytes()).root
    except ValidationError:
        return None
    return answers if sorted(answers) == sorted(keys) else None


def blind_check(
    store: Path,
    role: Role,
    version: str,
    setup: RawSetup,
    work: Path,
    *,
    implementer_model: str,
    cap: int,
) -> dict[str, Any]:
    """Run the blind check on a version's held-out tier; counts and the flagged tasks' digests.

    The version is read as every reader reads it, its manifest held to the bytes on disk
    (:func:`.tiers.manifest.read_version`). The check is held to the canaries under the
    role's root, as an author is (:func:`root_canaries`): it runs only looking for every one
    of them, and its answer is taken only when its record says none showed in its stream and
    none came under the root while it ran. Its stream is kept inside the role's root.

    Its session withholds what a run on the role's root withholds but the work root: the
    role's withheld root and every version's validation and held-out tiers, spelt as on disk.
    ``work`` is a directory of its own directly under the role's work root
    (:func:`.tiers.store.work_root`), which every run naming the role's root withholds, so its
    copy of the held-out tasks is never where a run's session could read it. No pool may be
    in the store, its own role's included: the exception for that pool is an author's alone.

    Raises:
        AuthoringError: the checking model is the implementers', ``work`` is inside a
            held-out root, the session does not withhold the tier, the role's withheld root or
            a protected tier under the role's root, or names one spelt otherwise than on disk,
            the store holds a pool or a version still being written, work an earlier session
            left is recorded, a canary list under the root cannot be taken whole or a tier
            there holds none, the session would not look for every canary the root names, or
            (its answer not taken, ``refused_because`` says why) its stream showed one or the
            root's canaries changed while it ran.
        TierSetError: the version is not what its manifest says.
        PerRoleError: a task in the tier does not load.
    """
    require_author_model(setup.model, implementer_model)
    root = role_root(store, role)
    tier = version_dir(store, role, version) / "held_out"
    roots = [Path(r) for r in (*setup.held_out, *setup.withheld_reads)]
    held = [Path(r) for r in setup.held_out]
    if not _withheld(tier, held) or any(_inside(work, r) for r in roots):
        msg = "the check withholds the tier and works outside every held-out root"
        raise AuthoringError(msg, tier=str(tier), work=str(work))
    # Its work holds a copy of the held-out tasks: it lies in the role's work root, which
    # every run naming the role's root withholds, never where a run could read it.
    if work.resolve().parent != work_root(store, role).resolve():
        msg = f"the check works in a directory of its own directly under {work_root(store, role)}"
        raise AuthoringError(msg, refused_because="work_outside_the_work_root", work=str(work))
    _require_withheld_as_a_run(store, role, setup)
    _require_no_work_left(root)
    _require_nothing_left(store)
    read_version(version_dir(store, role, version))
    canaries = root_canaries(root)
    _require_looking(canaries, setup)
    tasks = bundle(tier)
    files = {"tasks.json": json.dumps(tasks, sort_keys=True, indent=1).encode()}
    record: dict[str, Any] | None = None
    working = _working(root, CHECK_EVIDENCE, work)
    work_root(store, role).mkdir(mode=0o700, exist_ok=True)
    try:
        record = run_session(
            CHECK_BRIEF.format(count=len(tasks)), setup, work, cap=cap, files=files
        )
        _require_unseen(record, canaries, "its answer is not taken")
        _require_none_came(root, canaries, "its answer is not taken")
        answers = read_answers(work / "worktree" / "answers.json", list(tasks))
    finally:
        # The work holds the held-out tasks it was given: it never stays outside the root.
        _closed(_keep_evidence(work, record, check_evidence(store, role)))
        working.unlink()
    if answers is None:
        return {"tasks": len(tasks), "answered": False, "session": _spent(record)}
    flagged = sorted(key for key, a in answers.items() if not all(getattr(a, q) for q in QUESTIONS))
    return {
        "tasks": len(tasks),
        "answered": True,
        "all_yes": len(tasks) - len(flagged),
        "flagged": flagged,
        "session": _spent(record),
    }


__all__ = [
    "MOST_CAP",
    "AuthoringPlan",
    "AuthorProgress",
    "author",
    "blind_check",
    "bundle",
    "read_answers",
    "stage",
]
