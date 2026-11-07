"""The own tasks' authoring session, and the blind check of the held-out tier, end to end.

**Authoring.** A session, on a model that is not the implementers', is given the author
brief and nothing else, and works in a fresh directory outside every held-out root (the
``baseline`` profile it runs under refuses those roots). Before it starts, the protected
root is surveyed as the session's tripwire will survey it: a link or an unreadable file
anywhere under it would have the session refused every tool call, so the runner refuses
first, at no cost. It refuses too unless the session looks for every canary that the lists
the harness wrote under the root name, at any depth (:func:`root_canaries`), and a list that
cannot be taken whole, or a directory that cannot be listed, is never read as naming none.
While it runs, a checkpoint on the budget watch holds each task to its references as soon as
it is written (on a copy, never in the worktree), and stops the session when no task holds
after a quarter of the cap, or when more than a task's worth of tokens has gone by since the
last task came to hold. When it ends, the runner closes the checkpoint, so a call of it that
outlived the session changes nothing; a session its watch could not hold to its cap
(``WATCH_FAILURES``), or whose stream showed a held-out canary however it ended (or cannot
say, where the root names canaries), is refused, and only step 5 runs. Otherwise the runner:

1. copies each task it left into a staging directory beside its work, refusing a task
   that holds a link, a special file, a canary list's name or more than a task's worth of
   files;
2. holds every staged task to its references and its brief (:func:`.validate.sound`), and
   never prints one: what leaves is counts and digests;
3. moves every task that holds into the pool inside the protected root (a task whose id
   is already there is refused), so nothing a session wrote well is lost to a short
   session; there is no self-check inside the session in round 1;
4. once the pool holds the two tiers' worth, draws that many by the seed and splits them
   by the same seed: the visible tier where asked, the held-out tier inside its protected
   root. Otherwise it says how many are pooled, and a further session adds to them;
5. copies the session's stream and record inside the protected root, since they hold
   every task the session wrote, as regular files only (the session's own links, such as
   its interpreter's, would trip the next session's tripwire), and removes the work.

**The blind check.** A second session, on a model that is not the implementers' either,
reads the held-out tasks from a file placed in its own work directory (never its prompt,
which any process of the same user can list), keyed by the digest of each id, without
their references or canaries. It answers three questions per task with true or false and
nothing else. Its answer is read strictly: anything but those booleans for exactly those
keys is no answer. Its stream is moved inside the protected root as well. What leaves is
counts and the digests of the tasks with a ``false``.

Both are tested against the scripted endpoint; a real session is started by a person.
"""

from __future__ import annotations

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
from typing import Any, get_args

from pydantic import BaseModel, ConfigDict, RootModel, TypeAdapter, ValidationError

from physgate.evaluation.per_role.arms.raw import WATCH_FAILURES, RawSetup, run_session
from physgate.evaluation.per_role.authoring import (
    CANARIES_NAME,
    PER_TIER,
    AuthoringError,
    author_brief,
    require_author_model,
    split,
)
from physgate.evaluation.per_role.firmware.sandbox import open_directory
from physgate.evaluation.per_role.task import Canary, Role, load_task
from physgate.evaluation.per_role.validate import id_digest, refusal_reasons, sound, validate
from physgate.hooks.withheld import survey

_READ = os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK
_NEW = os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW

#: The most files and bytes one staged task may hold: a task, a good reference and a few
#: bad ones, each a small JSON file.
MOST_FILES_PER_TASK = 64
MOST_BYTES_PER_TASK = 2 * 1024 * 1024

#: The most tokens one authoring session may be capped at, every class counted. Tasks are
#: pooled as they are written, so a session is short and a further one adds to it; the
#: one session that ran unbounded spent 80 M tokens on a loop that wrote nothing.
MOST_CAP = 8_000_000
#: The share of the cap a session may spend before its first task must hold.
FIRST_TASK_SHARE = 4


@dataclass(frozen=True)
class AuthoringPlan:
    """Where one authoring session works and where its two tiers go."""

    role: Role
    implementer_model: str
    #: A directory that does not exist yet, outside every held-out root.
    work: Path
    #: The visible tier's directory, which must not exist yet.
    visible: Path
    #: The protected root the held-out tier goes inside, as ``<root>/<role>``.
    held_out_root: Path
    seed: int
    #: The session's token cap, at most :data:`MOST_CAP`.
    cap: int
    #: How many tasks the session is asked for; the pool decides when the tiers are cut.
    count: int = 2 * PER_TIER
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


def held_out_tier(root: Path, role: Role) -> Path:
    """Where a role's held-out tier lives inside its protected root."""
    return root / role


def pool_dir(root: Path, role: Role) -> Path:
    """Where a role's tasks that hold wait, inside the protected root, until the tiers are cut."""
    return root / f"{role}.pool"


def _inside(path: Path, root: Path) -> bool:
    one, other = path.resolve(), root.resolve()
    return one == other or one.is_relative_to(other) or other.is_relative_to(one)


def _withheld(path: Path, roots: Sequence[Path]) -> bool:
    """Whether ``path`` is one of ``roots`` or inside one."""
    return any(path.resolve().is_relative_to(r.resolve()) for r in roots)


def _require_apart(plan: AuthoringPlan, setup: RawSetup) -> None:
    roots = [Path(r) for r in (*setup.held_out, *setup.withheld_reads)]
    if not _withheld(plan.held_out_root, [Path(r) for r in setup.held_out]):
        msg = "the session does not withhold the protected root the held-out tier goes in"
        raise AuthoringError(msg, root=str(plan.held_out_root))
    for name, path in (("work", plan.work), ("visible tier", plan.visible)):
        if any(_inside(path, r) for r in roots):
            msg = f"the {name} is inside a held-out root, or holds one"
            raise AuthoringError(msg, path=str(path))
    for name, path in (
        ("work", plan.work),
        ("visible tier", plan.visible),
        ("protected root", plan.held_out_root),
    ):
        if path.resolve() != path.absolute():
            msg = f"the {name} is reached through a link; give its resolved path"
            raise AuthoringError(msg, path=str(path))
    tier = held_out_tier(plan.held_out_root, plan.role)
    if plan.work.exists() or plan.visible.exists() or tier.exists():
        msg = "the work directory and both tiers are made new for each session"
        raise AuthoringError(msg, work=str(plan.work), visible=str(plan.visible))
    if plan.count < 1:
        msg = "a session is asked for at least one task"
        raise AuthoringError(msg, count=str(plan.count))
    if not 0 < plan.cap <= MOST_CAP:
        msg = f"an authoring session's cap is at most {MOST_CAP} tokens; tasks are pooled"
        raise AuthoringError(msg, cap=str(plan.cap))
    if not 0 < plan.task_cap <= plan.cap:
        msg = "the per-task cap is positive and no more than the session's cap"
        raise AuthoringError(msg, per_task_cap=str(plan.task_cap))


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
#: The folders directly under a protected root that hold what sessions wrote: the pool, its
#: draw, and the streams of the author and the blind check. No list the harness writes lies
#: in one, and a list a session planted there would refuse every later session.
_SESSION_FOLDERS = frozenset(
    f"{role}.{kind}" for role in get_args(Role) for kind in ("pool", "draw", "author", "check")
)


def _names_a_list(name: str) -> bool:
    """Whether ``name`` is what a canary list is called."""
    return name == CANARIES_NAME or name.endswith(f".{CANARIES_NAME}")


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

    A split leaves each held-out tier's list beside it, as ``<tier>.canaries.json``, and a
    tier may hold one as ``canaries.json``, at any depth. :data:`_SESSION_FOLDERS` are not
    entered: what a session wrote is no list of ours. Of everything else only names are
    looked at, by the runner, never a task; the pool's tasks carry no canary yet. A link is
    judged as the list it is named as, and never followed.

    Raises:
        AuthoringError: a list cannot be taken whole (:func:`_canary_list`), or a directory
            that could hold one cannot be listed (``canary_list_unreadable``).
    """

    def unlisted(exc: OSError) -> None:
        msg = f"{exc.filename} cannot be listed, so a canary list in it cannot be ruled out"
        raise AuthoringError(
            msg, refused_because="canary_list_unreadable", path=str(exc.filename)
        ) from exc

    if not root.is_dir():
        return ()
    found: set[str] = set()
    for where, directories, files in os.walk(root, onerror=unlisted):
        if where == str(root):
            directories[:] = [d for d in directories if d not in _SESSION_FOLDERS]
        for name in sorted((*directories, *files)):
            if _names_a_list(name):
                found |= _canary_list(str(Path(where) / name))
    return tuple(sorted(found))


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
    """Copy the directory ``source_fd`` into the empty directory ``target_fd``, by content.

    ``budget`` is the files and bytes the task may still hold. The session may be writing the
    task while it is copied: an entry it removed between the listing and the look at it is
    no longer part of the task, and is left out of the copy, as a task is from the listing.

    Raises:
        _NotPlainError: an entry is a link of either kind, a special file, past the budget,
            or named as a canary list, which must not reach the pool or a tier.
    """
    for name in sorted(os.listdir(source_fd)):
        if _names_a_list(name):
            raise _NotPlainError(name)
        try:
            kind = _classify(name, source_fd).st_mode
        except FileNotFoundError:
            continue
        if stat.S_ISDIR(kind):
            try:
                child = open_directory(name, source_fd)
            except OSError as exc:
                raise _NotPlainError(name) from exc
            try:
                os.mkdir(name, 0o700, dir_fd=target_fd)
                made = open_directory(name, target_fd)
                try:
                    _copy_into(child, made, budget)
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
    than a task's worth, or named as a list itself, is refused, and what was copied of it
    removed. A task's id is its directory's name, or the task does not hold.
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
        except _NotPlainError:
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


def _signature(directory: Path) -> _Signature:
    seen: list[tuple[str, int, int]] = []
    for here, dirs, files in os.walk(directory, followlinks=False):
        dirs.sort()
        for name in sorted(files):
            try:
                info = os.lstat(Path(here) / name)
            except OSError:
                continue
            relative = os.path.relpath(Path(here) / name, directory)
            seen.append((relative, info.st_size, info.st_mtime_ns))
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
    """Move each held task from ``staging`` into ``pool``; how many went in, how many were there."""
    pool.mkdir(mode=0o700, parents=True, exist_ok=True)
    added = already = 0
    for name in sorted(held):
        if os.path.lexists(pool / name):
            already += 1
            continue
        shutil.move(str(staging / name), str(pool / name))
        added += 1
    return added, already


def _draw(pool: Path, seed: int) -> list[str]:
    """The two tiers' worth of the pool's tasks, by ``seed``, or nothing while it holds fewer."""
    names = sorted(p.name for p in pool.iterdir() if p.is_dir()) if pool.is_dir() else []
    if len(names) < 2 * PER_TIER:
        return []
    random.Random(seed).shuffle(names)
    return names[: 2 * PER_TIER]


def _cut_tiers(plan: AuthoringPlan, pool: Path, chosen: Sequence[str]) -> dict[str, Any]:
    """Copy ``chosen`` out of the pool into a draw beside it, split them, then drop them from it.

    The draw lives inside the protected root, like the pool: a task that may become a
    held-out one is never outside it. The chosen tasks leave the pool only once both
    tiers are written and checked; a split that fails leaves the pool whole.
    """
    tier = held_out_tier(plan.held_out_root, plan.role)
    draw = plan.held_out_root / f"{plan.role}.draw"
    if os.path.lexists(draw):
        msg = f"{draw} is left from an earlier split that did not finish; look before removing it"
        raise AuthoringError(msg, draw=str(draw))
    draw.mkdir(mode=0o700)
    started = False
    try:
        for name in chosen:
            shutil.copytree(pool / name, draw / name, symlinks=True)
        started = True
        placed = split(draw, plan.visible, tier, seed=plan.seed)
        started = False
    finally:
        problems: list[str | None] = [_remove(draw)]
        if started:
            # Neither tier existed before this call; half a split is no tier at all.
            problems += [_remove(plan.visible), _remove(tier)]
        _closed(problems)
    for name in chosen:
        shutil.rmtree(pool / name)
    return placed


def author(plan: AuthoringPlan, setup: RawSetup) -> dict[str, Any]:
    """Run one authoring session, pool the tasks that hold, and cut the tiers once it can.

    Returns what may be shown: counts, what the session spent, how many tasks are pooled,
    and once the tiers are cut the visible tier's ids and the held-out tier's digest.

    Raises:
        AuthoringError: the author's model is the implementers', a place is inside a held-out
            root or already exists, the cap is over :data:`MOST_CAP`, the session does not
            withhold the protected root, the root would trip the session's tripwire, a
            canary list under the root cannot be taken whole or names a canary the session
            would not look for, or the
            session's watch could not hold it to its cap or its stream showed a held-out
            canary (none of its tasks is pooled; ``refused_because`` says which).
    """
    require_author_model(setup.model, plan.implementer_model)
    _require_apart(plan, setup)
    canaries = root_canaries(plan.held_out_root)
    missing = set(canaries) - set(setup.held_out_canaries)
    if missing:
        msg = (
            f"the session would not look for {len(missing)} of the canaries its protected "
            "root names, so its record could not say whether it saw a held-out task"
        )
        raise AuthoringError(msg, refused_because="canaries_missing", missing=str(len(missing)))
    _require_clear(plan.held_out_root)
    evidence = plan.held_out_root / f"{plan.role}.author"
    tier = held_out_tier(plan.held_out_root, plan.role)
    pool = pool_dir(plan.held_out_root, plan.role)
    record: dict[str, Any] | None = None
    progress = AuthorProgress(
        plan.work / "worktree", plan.work / "checks", cap=plan.cap, per_task=plan.task_cap
    )
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
        seen = record.get("held_out_seen", "unrecorded")
        if seen is not False and not (seen is None and not canaries):
            # A held-out canary showed in the session's stream, or the record cannot say it
            # did not while the root names canaries (it is unknown only where there is none
            # to look for): what the session wrote may hold what it saw, however it ended,
            # so none of its tasks is taken. Its stream is still secured below.
            msg = (
                "the session's stream showed a held-out canary (held_out_seen); none of the "
                "tasks it wrote is pooled"
            )
            raise AuthoringError(msg, end=str(record["end"]), refused_because="held_out_seen")
        if record["end"] in WATCH_FAILURES:
            # The watch could not hold the session to its cap: what it did was not counted as
            # meant, so none of its tasks is taken. Its stream is still secured below.
            msg = (
                f"the session's watch could not hold it ({record['end']}); none of the tasks "
                "it wrote is pooled"
            )
            raise AuthoringError(msg, end=str(record["end"]), refused_because=str(record["end"]))
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
    chosen = _draw(pool, plan.seed)
    if not chosen:
        return {**summary, "status": "pooled"}
    placed = _cut_tiers(plan, pool, chosen)
    return {
        **summary,
        "status": "split",
        "pool": sum(1 for p in pool.iterdir() if p.is_dir()),
        "visible": placed["visible"],
        "held_out_count": placed["held_out_count"],
        "held_out_sha256": placed["held_out_sha256"],
        "visible_check": validate(plan.visible, show_ids=True),
        "held_out_check": validate(tier),
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
    tier: Path, setup: RawSetup, work: Path, *, implementer_model: str, cap: int, evidence: Path
) -> dict[str, Any]:
    """Run the blind check on ``tier``; counts and the digests of tasks with a ``false``.

    Raises:
        AuthoringError: the checking model is the implementers', ``work`` is inside a
            held-out root, or the session does not withhold the tier.
        PerRoleError: a task in the tier does not load.
    """
    require_author_model(setup.model, implementer_model)
    roots = [Path(r) for r in (*setup.held_out, *setup.withheld_reads)]
    held = [Path(r) for r in setup.held_out]
    if not _withheld(tier, held) or any(_inside(work, r) for r in roots):
        msg = "the check withholds the tier and works outside every held-out root"
        raise AuthoringError(msg, tier=str(tier), work=str(work))
    tasks = bundle(tier)
    files = {"tasks.json": json.dumps(tasks, sort_keys=True, indent=1).encode()}
    record: dict[str, Any] | None = None
    try:
        record = run_session(
            CHECK_BRIEF.format(count=len(tasks)), setup, work, cap=cap, files=files
        )
        answers = read_answers(work / "worktree" / "answers.json", list(tasks))
    finally:
        # The work holds the held-out tasks it was given: it never stays outside the root.
        _closed(_keep_evidence(work, record, evidence))
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
    "held_out_tier",
    "pool_dir",
    "read_answers",
    "stage",
]
