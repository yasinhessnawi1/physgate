"""Which versions of a role's tiers have been seen, and whether a measured run may use one.

**The register.** Each role's withheld root (``<store>/<role>/withheld/``) holds the role's one
register, ``register.jsonl``, and the roots its runs are made under, ``run-roots.jsonl``. Every
run that names anything under the role's root withholds that root from its sessions, so no
session of such a run reads either file or writes it, by any tool. A top-level file of the
store would be withheld by no run: a session's file tool could truncate it.

Both are logs that are only ever appended to, and nothing removes a line: no command unmarks a
version. Each line carries its place (``n``) and the digest of the line before it (``prev``),
and a head file beside the log (``<name>.head``) records how many lines the log held after the
last append and the digest of the last of them. A reader holds the log to both: a line out of
its place, a broken chain, fewer or more lines than the head records (more: a write cut off
between the two), or a head with no log (or a log with no head) refuses, so a shortened register
never reads as one with nothing exposed. Both logs are made empty, with their heads, as a
version is written (:func:`start_logs`), so once a role holds a version, a log, a head or the
withheld root that is gone refuses too (``register_missing``): it was removed. Readers take the
writers' lock shared. **A stated limit:** whoever can write the withheld root can shorten a log
and write its head again to match; the place is the hold against that.

The register's lines name a version by its id and its protected tiers' digests, and a key that
is a digest (of the incident's run and offset, or of the record's place): never a task id, a
brief, a canary or an outcome. A hand mark carries the person who made it and why.

- **exposure:** a ``held_out_read`` incident in the event log of a run under one of the role's
  run roots; a raw-arm record, under the run roots or beneath the withheld root's baseline
  records, whose ``held_out_seen`` is not false (``null``, nobody looked, on a validation or
  held-out task found by its brief: an exposure of unknown extent, ``raw_record_unchecked``,
  shown apart); or a mark made by a person at a terminal. Nothing inside a run directory is
  entered or parsed (the harness holds no run inside a run); a directory there that looks like
  a run, and a link to a directory anywhere, leave the root reported as not read whole. An
  incident names no root, so the run's held-out digests name the versions it marks: every
  version of the role whose validation or held-out tier the run recorded. A run or record that
  names none marks every version of the role.
- **authoring:** a read of the tiers by their author or their blind check. Never an exposure.
- **measurement:** one scoring of a protected tier whose result anyone sees.

**Every check reads the register as freshly scanned** (:func:`exposed_versions`): the lines
recorded, and every incident and record the run roots hold now, recorded or not. A check
never writes. The three writers (:func:`record_scan`, :func:`mark_exposed`,
:func:`add_run_root`) append, each under a lock.

**A measured run's version** is the one whose tasks hold the run's brief, found by its digest
as a baseline round finds a harness run's task. A run withholds every version's protected
tiers, older ones too, so a version it withholds is not one it is on: an exposed version
refuses only a run on it (:func:`version_refusal`).
"""

from __future__ import annotations

import contextlib
import fcntl
import hashlib
import json
import os
import stat
import tempfile
import time
from collections.abc import Callable, Iterable, Iterator, Mapping, Sequence
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Annotated, Any, Literal, get_args

from pydantic import Field, StringConstraints, TypeAdapter, ValidationError, model_validator

from physgate.evaluation.per_role.exceptions import PerRoleError
from physgate.evaluation.tiers.base import _Frozen
from physgate.evaluation.tiers.canaries import root_canaries
from physgate.evaluation.tiers.heldout import scan, tier_digest
from physgate.evaluation.tiers.manifest import VERSION_NAME, TierSet, read_version
from physgate.evaluation.tiers.store import (
    PROTECTED,
    role_root,
    role_roots,
    withheld_root,
)
from physgate.evaluation.tiers.task import Role, Sha256, canonical_json, parse_task
from physgate.orchestrator.events import Incident, read_events
from physgate.orchestrator.run_config import RunConfig, load_run_config

REGISTER = "register"
RUN_ROOTS = "run-roots"
LOG_SUFFIX = ".jsonl"
HEAD_SUFFIX = ".head"
LOCK_SUFFIX = ".lock"
#: Where a baseline round keeps its protected trials' records, beneath the withheld root.
BASELINE_RECORDS = "baseline"
RAW_RECORD = "raw.json"
RUN_RECORD = "run.json"
EVENT_LOG = "events.jsonl"
_ZERO = "0" * 64
_MISSING = object()
MOST_LOG_BYTES = 64 * 1024 * 1024
MOST_RECORD_BYTES = 1024 * 1024
#: How deep, and how many entries, a walk of the run roots takes before it refuses.
MOST_DEPTH = 8
MOST_ENTRIES = 200_000
#: What a hand mark's reason must at least hold: more than one bare word.
FEWEST_REASON_WORDS = 2
#: The most characters a hand mark's name or reason holds, each.
MOST_TEXT = 500
#: The places inside a run directory where the harness holds runs of its own: a walk enters
#: these alone there. The harness makes no run inside another run, so there are none, and a
#: walk enters nothing inside a run directory: a session writes in its worktree and its
#: scratch, so nothing there is parsed.
NESTED_RUN_PLACES: frozenset[str] = frozenset()
_PREFIX = 8

Key = Sha256
Date = Annotated[str, StringConstraints(pattern=r"^[0-9]{4}-[0-9]{2}-[0-9]{2}$")]
Text = Annotated[str, StringConstraints(min_length=1, max_length=500)]


class ExposureError(PerRoleError):
    """The register, the run roots or a run they hold cannot be read whole, or a write refused."""


class _Line(_Frozen):
    n: int = Field(ge=0)
    prev: Sha256


class Exposure(_Line):
    """A version was seen: by a session of a run, by a raw session, or by a person."""

    kind: Literal["exposure"]
    version: Sha256
    held_out: Sha256
    validation: Sha256
    #: ``raw_record_unchecked``: a raw session on a validation or held-out task looked for no
    #: canary, so whether it showed one cannot be told: an exposure of unknown extent.
    source: Literal["incident", "raw_record", "raw_record_unchecked", "hand"]
    key: Key
    by: Text | None = None
    reason: Text | None = None
    date: Date | None = None

    @model_validator(mode="after")
    def _a_hand_mark_says_who_and_why(self) -> Exposure:
        hand = self.source == "hand"
        if hand != (self.by is not None and self.reason is not None and self.date is not None):
            msg = "a hand mark, and only a hand mark, names who made it, why and when"
            raise ValueError(msg)
        return self


class Authoring(_Line):
    """The tiers were read by their author or their blind check: never an exposure."""

    kind: Literal["authoring"]
    version: Sha256
    held_out: Sha256
    validation: Sha256
    key: Key


class Measurement(_Line):
    """One scoring of a protected tier whose result anyone sees."""

    kind: Literal["measurement"]
    version: Sha256
    held_out: Sha256
    validation: Sha256
    measured: Literal["gaps", "experiment", "probe"]
    key: Key
    date: Date


class RunRoot(_Line):
    """A directory beneath which the role's runs are made, and the register scans."""

    kind: Literal["run_root"]
    path: Annotated[str, StringConstraints(min_length=2, max_length=4096, pattern=r"^/")]


RegisterLine = Annotated[Exposure | Authoring | Measurement, Field(discriminator="kind")]
_REGISTER_LINE: TypeAdapter[Exposure | Authoring | Measurement] = TypeAdapter(RegisterLine)


class _Head(_Frozen):
    format: Literal[1]
    lines: int = Field(ge=0)
    last: Sha256


def _digest(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _refuse(reason: str, detail: str) -> ExposureError:
    return ExposureError(detail, refused_because=reason)


def _dir_fd(directory: Path) -> int | None:
    """A descriptor for ``directory``, opened without following a link; ``None`` if absent.

    Raises:
        ExposureError: it is a link or not a directory.
    """
    try:
        fd = os.open(directory, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
    except FileNotFoundError:
        return None
    except OSError as exc:
        msg = f"{directory} is a link or not a directory; the harness makes it with mkdir"
        raise _refuse("register_unreadable", msg) from exc
    return fd


def _read_at(dir_fd: int, name: str, most: int) -> bytes | None:
    """The bytes of the regular file ``name`` under ``dir_fd``; ``None`` if it is not there.

    Raises:
        ExposureError: it is a link, not a regular file, too large, or cannot be read.
    """
    try:
        fd = os.open(name, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK, dir_fd=dir_fd)
    except FileNotFoundError:
        return None
    except OSError as exc:
        raise _refuse("register_unreadable", f"{name} cannot be opened: {exc}") from exc
    try:
        info = os.fstat(fd)
        if not stat.S_ISREG(info.st_mode) or info.st_nlink != 1 or info.st_size > most:
            msg = f"{name} is not a plain file of its own under the size bound"
            raise _refuse("register_unreadable", msg)
        with os.fdopen(os.dup(fd), "rb") as handle:
            return handle.read(most + 1)
    finally:
        os.close(fd)


def _has_version(role_root_dir: Path) -> bool:
    """Whether the role's root holds a version; one that cannot be listed is taken as one."""
    try:
        return any(VERSION_NAME.fullmatch(n) for n in os.listdir(role_root_dir))
    except FileNotFoundError:
        return False
    except OSError:
        return True


def _missing(name: str) -> ExposureError:
    msg = (
        f"the {name} log is gone while the role has a version, and a version is never written "
        "without it: it was removed, and what it recorded cannot be read"
    )
    return _refuse("register_missing", msg)


def _lines_of(dir_fd: int, name: str) -> list[bytes] | None:
    """The lines of the log ``name`` under ``dir_fd``, each with its newline, held to its head.

    ``None`` when neither the log nor its head is there.

    Raises:
        ExposureError: the log or its head is missing beside the other, unreadable, cut, out of
            its chain, or holds fewer or more lines than its head records.
    """
    data = _read_at(dir_fd, name + LOG_SUFFIX, MOST_LOG_BYTES)
    head_bytes = _read_at(dir_fd, name + HEAD_SUFFIX, MOST_RECORD_BYTES)
    if data is None and head_bytes is None:
        return None
    if data is None or head_bytes is None:
        msg = f"the {name} log and its head are not both there, so lines may have been removed"
        raise _refuse("register_unreadable", msg)
    try:
        head = _Head.model_validate_json(head_bytes)
    except ValidationError as exc:
        raise _refuse("register_unreadable", f"the {name} head is not a head") from exc
    if data and not data.endswith(b"\n"):
        raise _refuse("register_unreadable", f"the {name} log ends in a cut line")
    lines = data.splitlines(keepends=True)
    prev = _ZERO
    for at, line in enumerate(lines):
        try:
            fields = json.loads(line)
        except ValueError as exc:
            raise _refuse("register_unreadable", f"line {at} of the {name} log is no line") from exc
        if not isinstance(fields, dict) or fields.get("n") != at or fields.get("prev") != prev:
            msg = f"line {at} of the {name} log is out of its place in the chain"
            raise _refuse("register_unreadable", msg)
        prev = _digest(line)
    if len(lines) < head.lines:
        msg = (
            f"the {name} log holds {len(lines)} line(s) and its head records {head.lines}: "
            "lines have been removed"
        )
        raise _refuse("register_unreadable", msg)
    if len(lines) > head.lines:
        msg = (
            f"the {name} log holds {len(lines) - head.lines} line(s) past its head: a write was "
            "cut off between the log and its head, so whether those lines were meant cannot be "
            "told; a person compares them with what was being recorded and writes the head again"
        )
        raise _refuse("register_unreadable", msg)
    last = _digest(lines[head.lines - 1]) if head.lines else _ZERO
    if last != head.last:
        msg = f"the {name} log's line {head.lines - 1} is not the one its head records"
        raise _refuse("register_unreadable", msg)
    return lines


def _read_log(withheld: Path, name: str) -> list[bytes]:
    """The lines of the log ``name`` in ``withheld``, held to its head, under the shared lock.

    A role with no version yet has no log, which reads as empty. Once the role holds a version
    the log is there (:func:`start_logs`), so a log, a head or a withheld root that is gone
    refuses: it was removed, never empty.

    Raises:
        ExposureError: as :func:`_lines_of`; ``withheld`` is a link; or the log is gone while the
            role holds a version.
    """
    fd = _dir_fd(withheld)
    if fd is None:
        if _has_version(withheld.parent):
            raise _missing(name)
        return []
    try:
        try:
            lock = os.open(
                name + LOCK_SUFFIX, os.O_RDONLY | os.O_CREAT | os.O_NOFOLLOW, 0o600, dir_fd=fd
            )
        except OSError as exc:
            raise _refuse("register_unreadable", f"the {name} lock cannot be taken: {exc}") from exc
        try:
            # Shared with every other reader, never with a writer: no log is read half-appended.
            fcntl.flock(lock, fcntl.LOCK_SH)
            lines = _lines_of(fd, name)
        finally:
            os.close(lock)
    finally:
        os.close(fd)
    if lines is None:
        if _has_version(withheld.parent):
            raise _missing(name)
        return []
    return lines


#: What the harness puts in every role and baseline session's environment, as its hook
#: installer writes it (:func:`physgate.hooks.settings.install`): background commands
#: switched off, and the session's own temporary directory; and, where the OS layer runs, the
#: survivor reaper's shell prefix.
SESSION_MARKERS = (
    "CLAUDE_CODE_DISABLE_BACKGROUND_TASKS",
    "CLAUDE_CODE_TMPDIR",
    "CLAUDE_CODE_SHELL_PREFIX",
)


def _refuse_inside_a_session() -> None:
    """Refuse a write to the register or the run roots asked for inside a harness session.

    Defence in depth only: a session controls its own environment and can drop these. What
    stops a session is the place: both logs lie beneath the role's withheld root, which the
    hooks and the OS layer deny every session of a run on the role, to read and to write.

    Raises:
        ExposureError: the environment carries a harness session's marker.
    """
    found = sorted(name for name in SESSION_MARKERS if name in os.environ)
    if found:
        msg = f"the register is written by a person, never from a session ({', '.join(found)})"
        raise _refuse("inside_a_session", msg)


def _write_head(dir_fd: int, name: str, total: int, last: str) -> None:
    """Replace the head of the log ``name`` whole: ``total`` lines, the last's digest ``last``."""
    head = canonical_json({"format": 1, "lines": total, "last": last})
    # Named without drawing from ``secrets``, which a version's writing draws from in order:
    # the head is written under the log's lock, and the name is made new below.
    partial = f".{name}{HEAD_SUFFIX}.{os.getpid()}.{time.monotonic_ns()}"
    out = os.open(
        partial, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o600, dir_fd=dir_fd
    )
    try:
        os.write(out, head)
        os.fsync(out)
    finally:
        os.close(out)
    os.replace(partial, name + HEAD_SUFFIX, src_dir_fd=dir_fd, dst_dir_fd=dir_fd)
    os.fsync(dir_fd)


def start_logs(withheld: Path) -> None:
    """Make the role's two logs, empty with their heads, where neither file of a pair is there.

    Called as a version is written, before it is there, so a role never holds a version without
    its logs, and a log removed later refuses every reader and writer (:func:`_read_log`). A
    pair that is there is left as it is; one file of a pair alone refuses.

    Raises:
        ExposureError: ``withheld`` is missing or a link, or a pair refuses as read.
    """
    fd = _dir_fd(withheld)
    if fd is None:
        msg = f"{withheld} is not there; the role's root is made with it"
        raise _refuse("register_unreadable", msg)
    try:
        for name in (REGISTER, RUN_ROOTS):
            lock = os.open(
                name + LOCK_SUFFIX, os.O_RDWR | os.O_CREAT | os.O_NOFOLLOW, 0o600, dir_fd=fd
            )
            try:
                fcntl.flock(lock, fcntl.LOCK_EX)
                if _lines_of(fd, name) is not None:
                    continue
                log = os.open(
                    name + LOG_SUFFIX,
                    os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW,
                    0o600,
                    dir_fd=fd,
                )
                os.close(log)
                _write_head(fd, name, 0, _ZERO)
            finally:
                os.close(lock)
    except OSError as exc:
        raise _refuse("register_unreadable", f"the logs cannot be made: {exc}") from exc
    finally:
        os.close(fd)


def _append(
    withheld: Path,
    name: str,
    payloads: Sequence[Mapping[str, Any]],
    *,
    check: Callable[[list[bytes]], None] | None = None,
) -> int:
    """Append ``payloads`` to the log ``name`` in ``withheld``, chained, and move its head.

    The log is read and held to its head under the lock first, so nothing is appended to a log
    that has been cut; ``check``, when given, is shown the lines read there, under the lock, and
    refuses by raising. Returns the number of lines the log then holds.

    Raises:
        ExposureError: the write is asked for inside a harness session; the withheld root is
            missing or a link; the log refuses as read; or ``check`` refuses.
    """
    _refuse_inside_a_session()
    fd = _dir_fd(withheld)
    if fd is None:
        msg = f"{withheld} is not there; the role's root is made with it"
        raise _refuse("register_unreadable", msg)
    try:
        lock = os.open(name + LOCK_SUFFIX, os.O_RDWR | os.O_CREAT | os.O_NOFOLLOW, 0o600, dir_fd=fd)
        try:
            fcntl.flock(lock, fcntl.LOCK_EX)
            found = _lines_of(fd, name)
            if found is None and _has_version(withheld.parent):
                # Removed: a new log here would read as one with nothing recorded.
                raise _missing(name)
            lines = found or []
            if check is not None:
                check(lines)
            prev = _digest(lines[-1]) if lines else _ZERO
            written: list[bytes] = []
            for at, payload in enumerate(payloads, start=len(lines)):
                # One line each: the canonical bytes end in their newline.
                line = canonical_json({**payload, "n": at, "prev": prev})
                written.append(line)
                prev = _digest(line)
            # The log is made with its first head, even with nothing in it: a head never stands
            # without its log.
            log = os.open(
                name + LOG_SUFFIX,
                os.O_WRONLY | os.O_APPEND | os.O_CREAT | os.O_NOFOLLOW,
                0o600,
                dir_fd=fd,
            )
            try:
                os.write(log, b"".join(written))
                os.fsync(log)
            finally:
                os.close(log)
            total = len(lines) + len(written)
            if written or found is None:
                _write_head(fd, name, total, prev)
            return total
        finally:
            os.close(lock)
    except OSError as exc:
        raise _refuse("register_unreadable", f"the {name} log cannot be written: {exc}") from exc
    finally:
        os.close(fd)


def register_lines(store: Path, role: Role) -> list[Exposure | Authoring | Measurement]:
    """Every line of the role's register, held to its head.

    Raises:
        ExposureError: the register refuses as read (:func:`_lines_of`) or holds a line that
            is none of its kinds.
    """
    found = []
    for at, line in enumerate(_read_log(withheld_root(store, role), REGISTER)):
        try:
            found.append(_REGISTER_LINE.validate_json(line))
        except ValidationError as exc:
            msg = f"line {at} of the register is none of its kinds"
            raise _refuse("register_unreadable", msg) from exc
    return found


@contextlib.contextmanager
def holding_register(store: Path, role: Role) -> Iterator[None]:
    """The role's register held from its writers while the body runs, as every reader holds it.

    A shared hold of the register's lock: readers go on, and no measurement or exposure line is
    appended until the body ends. For a look at the register that must still hold as something
    is put in place beside it. A role with no withheld root yet has no register to hold.

    Raises:
        ExposureError: the withheld root is a link, or the register's lock cannot be taken.
    """
    fd = _dir_fd(withheld_root(store, role))
    if fd is None:
        yield
        return
    try:
        try:
            lock = os.open(
                REGISTER + LOCK_SUFFIX, os.O_RDONLY | os.O_CREAT | os.O_NOFOLLOW, 0o600, dir_fd=fd
            )
        except OSError as exc:
            msg = f"the {REGISTER} lock cannot be taken: {exc}"
            raise _refuse("register_unreadable", msg) from exc
        try:
            fcntl.flock(lock, fcntl.LOCK_SH)
            yield
        finally:
            os.close(lock)
    finally:
        os.close(fd)


def run_roots(store: Path, role: Role) -> list[Path]:
    """The directories beneath which the role's runs are made.

    Raises:
        ExposureError: the run-roots log refuses as read, or holds a line that is not a root.
    """
    found = []
    for at, line in enumerate(_read_log(withheld_root(store, role), RUN_ROOTS)):
        try:
            found.append(Path(RunRoot.model_validate_json(line).path))
        except ValidationError as exc:
            msg = f"line {at} of the run roots is not a run root"
            raise _refuse("register_unreadable", msg) from exc
    return found


def versions(store: Path, role: Role) -> dict[str, TierSet]:
    """Every version of the role, each read as every reader reads it.

    Raises:
        ExposureError: the role's root cannot be listed, or a version is not what its manifest
            says, so what a run's digests name cannot be told.
    """
    root = role_root(store, role)
    try:
        names = sorted(n for n in os.listdir(root) if VERSION_NAME.fullmatch(n))
    except FileNotFoundError:
        return {}
    except OSError as exc:
        raise _refuse("register_unreadable", f"the role's root cannot be listed: {exc}") from exc
    found: dict[str, TierSet] = {}
    for name in names:
        try:
            found[name] = read_version(root / name)
        except PerRoleError as exc:
            msg = f"the version {name[:_PREFIX]} is not what its manifest says"
            raise _refuse("version_unknown", msg) from exc
    return found


@dataclass(frozen=True)
class Finding:
    """An exposure found in a run root or the withheld root's records, recorded or not."""

    key: str
    source: Literal["incident", "raw_record", "raw_record_unchecked"]
    versions: frozenset[str]


@dataclass
class _Walk:
    """What a walk of the roots found, and what of them it could not read."""

    runs: list[Path]
    records: list[Path]
    seen: int = 0
    #: Roots not read whole: they hold a link to a directory, which is not followed, or a
    #: directory inside a run that looks like a run, which is not read.
    unread: list[Path] = field(default_factory=list)
    #: Where in those roots, by position beneath the root; never what is there.
    places: list[str] = field(default_factory=list)
    #: Roots that are not there.
    missing: list[Path] = field(default_factory=list)


def _walk(root: Path, walk: _Walk, *, required: bool) -> None:
    """Every run directory and raw record beneath ``root``, no link followed, bounded.

    Inside a run directory the walk enters only :data:`NESTED_RUN_PLACES` and parses nothing
    else. A directory there that holds a run's configuration is neither read nor ignored: its
    root is recorded as not read whole, with its position. A link to a directory is not
    followed, and its root is recorded so too. A ``required`` root that is not there is
    recorded as missing, never read as empty.

    Raises:
        ExposureError: the walk goes past its bounds, or a directory cannot be listed.
    """
    stack = [(root, 0)]
    places: list[str] = []
    while stack:
        here, depth = stack.pop()
        try:
            with os.scandir(here) as entries:
                listed = list(entries)
        except FileNotFoundError:
            if here == root and required:
                walk.missing.append(root)
            continue
        except OSError as exc:
            msg = (
                f"{here}, beneath the run root {root}, cannot be listed, so a run in it cannot be "
                "ruled out: a person makes it readable to this user again"
            )
            raise _refuse("register_unreadable", msg) from exc
        walk.seen += len(listed)
        if walk.seen > MOST_ENTRIES:
            msg = (
                f"the run roots hold more than {MOST_ENTRIES} entries, the bound passed in the "
                f"run root {root}: a walk past it is refused rather than read in part. A person "
                "looks at that root and moves out of it what is no run's (a run is never moved "
                "out of the run roots to let a look pass)"
            )
            raise _refuse("register_unreadable", msg)
        names = {e.name: e for e in listed}
        run = names.get(RUN_RECORD)
        is_run = run is not None and run.is_file(follow_symlinks=False)
        if is_run:
            walk.runs.append(here)
        record = names.get(RAW_RECORD)
        if not is_run and record is not None and not record.is_dir(follow_symlinks=False):
            walk.records.append(here / RAW_RECORD)
        for entry in listed:
            where = Path(entry.path)
            if entry.is_symlink():
                if entry.is_dir(follow_symlinks=True):
                    places.append(where.relative_to(root).as_posix())
                continue
            if not entry.is_dir(follow_symlinks=False):
                continue
            if is_run and entry.name not in NESTED_RUN_PLACES:
                # Not entered and nothing in it parsed; one that looks like a run is said.
                if os.path.lexists(where / RUN_RECORD):
                    places.append(where.relative_to(root).as_posix())
                continue
            if depth + 1 > MOST_DEPTH:
                msg = (
                    f"the run root {root} holds directories deeper than {MOST_DEPTH}: a person "
                    "looks at it and moves out of it what is no run's"
                )
                raise _refuse("register_unreadable", msg)
            stack.append((Path(entry.path), depth + 1))
    if places:
        walk.unread.append(root)
        walk.places += sorted(places)


def _named_by(digests: Iterable[str], known: Mapping[str, TierSet]) -> frozenset[str]:
    """The versions whose protected tiers ``digests`` name; every version where they name none."""
    named = set(digests)
    found = {
        version
        for version, manifest in known.items()
        if manifest.held_out.sha256 in named or manifest.validation.sha256 in named
    }
    return frozenset(found or known)


def _run_findings(run: Path, known: Mapping[str, TierSet]) -> list[Finding]:
    try:
        config = load_run_config(run / RUN_RECORD)
        log = run / EVENT_LOG
        events = read_events(log) if os.path.lexists(log) else []
    except Exception as exc:  # noqa: BLE001 - a run that cannot be read cannot be ruled out
        msg = f"a run under the run roots cannot be read: {type(exc).__name__}"
        raise _refuse("register_unreadable", msg) from exc
    marked = _named_by(config.held_out_sha256, known)
    return [
        Finding(_digest(f"incident\0{run}\0{event.seq}".encode()), "incident", marked)
        for event in events
        if isinstance(event, Incident) and event.cause == "held_out_read"
    ]


def _protected_briefs(store: Path, role: Role) -> dict[str, frozenset[str]]:
    """Each brief digest of a validation or held-out task of the role, and the versions holding it.

    Raises:
        ExposureError: a task of a version cannot be read; only its tier is said.
    """
    root = role_root(store, role)
    try:
        names = sorted(n for n in os.listdir(root) if VERSION_NAME.fullmatch(n))
    except OSError as exc:
        raise _refuse("version_unknown", f"the role's root cannot be listed: {exc}") from exc
    found: dict[str, set[str]] = {}
    for name in names:
        for tier in PROTECTED:
            here = root / name / tier
            try:
                entries = sorted(p for p in here.iterdir() if p.is_dir() and not p.is_symlink())
                for entry in entries:
                    brief = parse_task((entry / "task.json").read_bytes()).brief
                    found.setdefault(_digest(brief.encode()), set()).add(name)
            except (OSError, PerRoleError) as exc:
                # The error may name the task; only the tier is said.
                msg = f"a task of the {tier} tier of {name[:_PREFIX]} cannot be read"
                raise _refuse("version_unknown", msg) from exc
    return {brief: frozenset(versions) for brief, versions in found.items()}


def _unchecked(
    record: Mapping[str, Any],
    named: Sequence[str],
    known: Mapping[str, TierSet],
    briefs: Callable[[], Mapping[str, frozenset[str]]],
) -> frozenset[str]:
    """The versions a raw record that looked for no canary may have exposed; none if visible.

    Only a validation or held-out task has a canary, so only a session on one can show one. The
    task is found by the brief digest the record pins; a record pinning none could be on any.
    """
    pins = record.get("pins")
    brief = pins.get("brief_sha256") if isinstance(pins, dict) else None
    if not isinstance(brief, str):
        return _named_by(named, known)
    return briefs().get(brief, frozenset())


def _record_finding(
    path: Path,
    known: Mapping[str, TierSet],
    briefs: Callable[[], Mapping[str, frozenset[str]]],
) -> Finding | None:
    fd = _dir_fd(path.parent)
    if fd is None:
        return None
    try:
        data = _read_at(fd, path.name, MOST_RECORD_BYTES)
    finally:
        os.close(fd)
    if data is None:
        return None
    try:
        record = json.loads(data)
    except ValueError as exc:
        raise _refuse("register_unreadable", "a raw record cannot be read") from exc
    if not isinstance(record, dict):
        raise _refuse("register_unreadable", "a raw record is not a record")
    # Only a record that says no canary showed is no exposure. One that looked for none is an
    # exposure of unknown extent where its task is a validation or held-out one; one that says
    # nothing, or anything else, is read as an exposure.
    seen = record.get("held_out_seen", _MISSING)
    if seen is False:
        return None
    digests = record.get("held_out_sha256")
    named = [d for d in digests if isinstance(d, str)] if isinstance(digests, list) else []
    key = _digest(f"raw\0{path}".encode())
    if seen is None:
        marked = _unchecked(record, named, known, briefs)
        return Finding(key, "raw_record_unchecked", marked) if marked else None
    return Finding(key, "raw_record", _named_by(named, known))


@dataclass(frozen=True)
class Survey:
    """What the roots hold now: the exposures, and the roots not there or not read whole."""

    findings: tuple[Finding, ...]
    missing: tuple[Path, ...]
    unread: tuple[Path, ...]
    #: Where in the unread roots, by position; never what is there.
    places: tuple[str, ...] = ()


def survey(store: Path, role: Role, roots: Sequence[Path]) -> Survey:
    """Every exposure beneath ``roots`` and the role's withheld baseline records, now.

    Raises:
        ExposureError: a version, a run or a record cannot be read whole, or the walk goes past
            its bounds.
    """
    known = versions(store, role)
    walk = _Walk(runs=[], records=[])
    for root in roots:
        _walk(root, walk, required=True)
    _walk(withheld_root(store, role) / BASELINE_RECORDS, walk, required=False)
    cache: list[Mapping[str, frozenset[str]]] = []

    def briefs() -> Mapping[str, frozenset[str]]:
        if not cache:
            cache.append(_protected_briefs(store, role))
        return cache[0]

    found: list[Finding] = []
    for run in sorted(set(walk.runs)):
        found += _run_findings(run, known)
    for record in sorted(set(walk.records)):
        finding = _record_finding(record, known, briefs)
        if finding is not None:
            found.append(finding)
    return Survey(tuple(found), tuple(walk.missing), tuple(walk.unread), tuple(walk.places))


def _findings(store: Path, role: Role, roots: Sequence[Path]) -> list[Finding]:
    """Every exposure beneath ``roots`` and the role's withheld baseline records, now.

    Raises:
        ExposureError: as :func:`survey`.
    """
    return list(survey(store, role, roots).findings)


def found_exposures(store: Path, role: Role) -> list[Finding]:
    """Every exposure the role's run roots and its withheld baseline records hold now.

    Raises:
        ExposureError: the run roots, a version, a run or a record cannot be read whole.
    """
    return _findings(store, role, run_roots(store, role))


def exposure_sources(store: Path, role: Role) -> dict[str, frozenset[str]]:
    """Each version the register marks exposed, as freshly scanned, and by what; it writes nothing.

    A source of ``raw_record_unchecked`` alone is an exposure of unknown extent: nobody looked.

    Raises:
        ExposureError: the register, the run roots or what they hold cannot be read whole.
    """
    found: dict[str, set[str]] = {}
    for line in register_lines(store, role):
        if line.kind == "exposure":
            found.setdefault(line.version, set()).add(line.source)
    for finding in found_exposures(store, role):
        for version in finding.versions:
            found.setdefault(version, set()).add(finding.source)
    return {version: frozenset(sources) for version, sources in found.items()}


def exposed_versions(store: Path, role: Role) -> frozenset[str]:
    """Every version of the role the register marks exposed, as freshly scanned; it writes nothing.

    An exposure of unknown extent is one: a version nobody can say was not seen is not measured.

    Raises:
        ExposureError: the register, the run roots or what they hold cannot be read whole.
    """
    return frozenset(exposure_sources(store, role))


def _version_fields(manifest: TierSet) -> dict[str, str]:
    return {
        "version": manifest.version,
        "held_out": manifest.held_out.sha256,
        "validation": manifest.validation.sha256,
    }


@dataclass(frozen=True)
class ScanReport:
    """What a scan recorded, and the roots it could not read whole or found gone."""

    added: int
    already: int
    missing: tuple[Path, ...]
    unread: tuple[Path, ...]
    places: tuple[str, ...] = ()


def scan_exposures(store: Path, role: Role, roots: Sequence[Path] | None = None) -> ScanReport:
    """Append one exposure line per finding and version not yet recorded.

    ``roots``, when given, are scanned in place of the run-roots log, which is not read: so the
    exposures in a role's runs can be recorded before a broken log is replaced. A root that is
    gone, or that holds a link to a directory, is reported, never read as empty or whole.

    Raises:
        ExposureError: the scan or the append refuses.
    """
    known = versions(store, role)
    lines = register_lines(store, role)
    recorded = {(line.key, line.version) for line in lines if line.kind == "exposure"}
    new: list[dict[str, Any]] = []
    already = 0
    surveyed = survey(store, role, run_roots(store, role) if roots is None else roots)
    for finding in surveyed.findings:
        for version in sorted(finding.versions):
            if (finding.key, version) in recorded:
                already += 1
                continue
            recorded.add((finding.key, version))
            new.append(
                {
                    "kind": "exposure",
                    "source": finding.source,
                    "key": finding.key,
                    **_version_fields(known[version]),
                }
            )
    _append(withheld_root(store, role), REGISTER, new)
    return ScanReport(len(new), already, surveyed.missing, surveyed.unread, surveyed.places)


def record_scan(store: Path, role: Role) -> tuple[int, int]:
    """Scan the role's run roots and record what is new (:func:`scan_exposures`); (added, already).

    Raises:
        ExposureError: the scan or the append refuses.
    """
    report = scan_exposures(store, role)
    return report.added, report.already


def _today() -> str:
    return datetime.now(UTC).date().isoformat()


def mark_exposed(store: Path, role: Role, version: str, *, by: str, reason: str) -> None:
    """Mark ``version`` exposed by hand: a person opened it, which no hook sees.

    Raises:
        ExposureError: no person or no reason of more than one word is given, or the version
            is not one of the role's.
    """
    if not by.strip():
        raise _refuse("hand_mark_names_no_one", "a hand mark names the person who makes it")
    if len(by.strip()) > MOST_TEXT or len(reason.strip()) > MOST_TEXT:
        msg = f"a hand mark's name and its reason are each at most {MOST_TEXT} characters"
        raise _refuse("hand_mark_too_long", msg)
    if len(reason.split()) < FEWEST_REASON_WORDS:
        raise _refuse("hand_mark_without_a_reason", "a hand mark says why, in more than a word")
    known = versions(store, role)
    if version not in known:
        msg = f"the role has no version {version[:_PREFIX]}"
        raise _refuse("version_unknown", msg)
    date = _today()
    key = _digest(f"hand\0{version}\0{by}\0{reason}\0{date}".encode())
    payload = {
        "kind": "exposure",
        "source": "hand",
        "key": key,
        "by": by.strip(),
        "reason": reason.strip(),
        "date": date,
        **_version_fields(known[version]),
    }
    try:
        Exposure.model_validate({**payload, "n": 0, "prev": _ZERO})
    except ValidationError as exc:
        # What was given is not repeated: only that it is not a line the register holds.
        msg = "the hand mark is not a line the register holds"
        raise _refuse("hand_mark_not_a_line", msg) from exc
    _append(withheld_root(store, role), REGISTER, [payload])


def record_measurement(store: Path, role: Role, version: str, *, measured: str, key: str) -> int:
    """Count one scoring of ``version``'s protected tiers whose result anyone sees.

    ``key`` names what was measured (a vector's digest). Returns the version's measurement
    count with this one. A version marked exposed is refused, judged under the register's lock
    from the lines read there and the run roots' exposures read just before: an exposure
    recorded after a caller's own check and before this line is not missed.

    Raises:
        ExposureError: the version is not one of the role's or is marked exposed, the line is
            not one the register holds, or the register refuses the write.
    """
    known = versions(store, role)
    if version not in known:
        msg = f"the role has no version {version[:_PREFIX]}"
        raise _refuse("version_unknown", msg)
    payload = {
        "kind": "measurement",
        "measured": measured,
        "key": key,
        "date": _today(),
        **_version_fields(known[version]),
    }
    try:
        Measurement.model_validate({**payload, "n": 0, "prev": _ZERO})
    except ValidationError as exc:
        msg = "the measurement is not a line the register holds"
        raise _refuse("measurement_not_a_line", msg) from exc
    found = frozenset(v for finding in found_exposures(store, role) for v in finding.versions)

    def unexposed(lines: list[bytes]) -> None:
        exposed = set(found)
        for at, raw in enumerate(lines):
            try:
                line = _REGISTER_LINE.validate_json(raw)
            except ValidationError as exc:
                msg = f"line {at} of the register is none of its kinds"
                raise _refuse("register_unreadable", msg) from exc
            if line.kind == "exposure":
                exposed.add(line.version)
        if version in exposed:
            msg = (
                f"the version {version[:_PREFIX]} is marked exposed as the register reads now; "
                "the measurement is not counted"
            )
            raise _refuse("version_exposed", msg)

    _append(withheld_root(store, role), REGISTER, [payload], check=unexposed)
    return sum(1 for line in measurements(store, role) if line.version == version)


def measurements(store: Path, role: Role) -> list[Measurement]:
    """Every measurement line of the role's register, held to its head.

    Raises:
        ExposureError: the register refuses as read.
    """
    return [line for line in register_lines(store, role) if isinstance(line, Measurement)]


def add_run_root(store: Path, role: Role, root: Path) -> bool:
    """Add ``root`` to the role's run roots; whether it was not there already.

    Nothing is appended for a root that would make every later scan refuse: it is checked
    first, with the roots there already, as the scan will read it (walked within the scan's
    entry and depth bounds, every run and record in it read whole).

    Raises:
        ExposureError: the write is asked for inside a harness session; ``root`` is not an
            existing, readable directory of its own; it lies in the store, whose places no
            run's sessions work in, or holds it, so that the scan would walk the store and take
            what a session left there for a run; or the scan would refuse with it.
    """
    _refuse_inside_a_session()
    if root.is_symlink() or not root.is_dir():
        raise _refuse("run_root_not_a_directory", f"{root} is not a directory of its own")
    real, home = root.resolve(), store.resolve()
    if not os.access(real, os.R_OK | os.X_OK):
        raise _refuse("run_root_unreadable", f"{root} cannot be listed")
    if real.is_relative_to(home) or home.is_relative_to(real):
        raise _refuse(
            "run_root_and_store_overlap", "a run root lies outside the tier-set store, and apart"
        )
    roots = run_roots(store, role)
    if real in roots:
        return False
    try:
        surveyed = survey(store, role, [*roots, real])
    except ExposureError as exc:
        why = exc.context.get("refused_because", "register_unreadable")
        msg = f"with {root} among the run roots every scan would refuse ({why}): {exc}"
        raise _refuse("run_root_would_refuse_the_scan", msg) from exc
    if real in surveyed.unread:
        msg = (
            f"{root} holds a link to a directory, which a scan does not follow, or a directory "
            "inside a run that looks like a run, which a scan does not read, so a run there would "
            "never be read"
        )
        raise _refuse("run_root_not_fully_read", msg)
    _append(withheld_root(store, role), RUN_ROOTS, [{"kind": "run_root", "path": str(real)}])
    return True


def _resolved(entry: str) -> Path:
    return Path(entry).resolve(strict=False)


def _protected_tier_of(path: Path) -> tuple[Path, Role, str, str] | None:
    """The store, role, version and tier ``path`` (resolved) is a protected tier of; or ``None``."""
    if path.name not in PROTECTED or VERSION_NAME.fullmatch(path.parent.name) is None:
        return None
    for store, role in role_roots((str(path),)):
        if path.parent.parent == role_root(store, role):
            return store, role, path.parent.name, path.name
    return None


def _versions_with_brief(store: Path, role: Role, brief: str) -> list[str]:
    """Every version of the role one of whose tasks, in any tier, has the brief digest ``brief``.

    Raises:
        ExposureError: a task of a version cannot be read; only its tier is said.
    """
    root = role_root(store, role)
    try:
        names = sorted(n for n in os.listdir(root) if VERSION_NAME.fullmatch(n))
    except OSError as exc:
        raise _refuse("version_unknown", f"the role's root cannot be listed: {exc}") from exc
    found = []
    for name in names:
        for tier in ("visible", *PROTECTED):
            here = root / name / tier
            try:
                entries = sorted(p for p in here.iterdir() if p.is_dir() and not p.is_symlink())
                briefs = {
                    _digest(parse_task((e / "task.json").read_bytes()).brief.encode())
                    for e in entries
                }
            except (OSError, PerRoleError) as exc:
                # The error may name the task; only the tier is said.
                msg = f"a task of the {tier} tier of {name[:_PREFIX]} cannot be read"
                raise _refuse("version_unknown", msg) from exc
            if brief in briefs:
                found.append(name)
                break
    return found


def _scan_refusal(
    config: RunConfig, run_dir: Path | None, version: Path, entries: Mapping[str, str]
) -> tuple[str, str] | None:
    """The pre-run scan on each protected tier of the run's version, each held to its own list."""
    digests = dict(zip(config.held_out, config.held_out_sha256, strict=True))
    places = {"run directory": run_dir} if run_dir is not None and run_dir.exists() else {}
    for tier in PROTECTED:
        entry = entries.get(tier)
        if entry is None:
            msg = f"the run does not name its version's {tier} tier among its held-out roots"
            return "tier_not_named", msg
        listed = root_canaries(Path(entry))
        if not set(listed) <= set(config.held_out_canaries):
            return "canary_not_looked_for", (
                f"the run does not look for every canary of its version's {tier} tier"
            )
        with tempfile.TemporaryDirectory(prefix="pg-tier-scan-") as scratch:
            problems = scan(
                Path(entry),
                run_held_out=tuple(config.held_out),
                run_digests=digests,
                run_canaries=listed,
                places=places,
                scratch=Path(scratch),
                visible_tier=version / "visible",
                label=tier,  # type: ignore[arg-type]
            )
        if problems:
            # Counted only: a problem may name a task.
            return "tier_scan_refused", (
                f"the pre-run scan of the version's {tier} tier finds {len(problems)} problem(s)"
            )
    return None


def _names_version(value: object, digests: frozenset[str]) -> bool:
    return isinstance(value, list) and any(isinstance(d, str) and d in digests for d in value)


def results_refusal(store: Path, role: Role, version: str) -> tuple[str, str] | None:
    """Why the version's blind check may no longer be made or imported; ``None`` if it may.

    What a check flags is left out of every held-out figure of its version, so the check is
    made, or an earlier one imported, before any result of the version exists: never once the
    register holds a measurement of it (``version_measured``) or an exposure
    (``version_exposed``, as freshly scanned), or a run under the role's run roots or a raw
    record beneath them or the withheld root's baseline records names its held-out or validation
    tier (``version_has_runs``: a run withholds every version it was made beside, so one that
    names it was made after it was written). A run root that is not there or not read whole
    leaves a run on it unruled out (``run_roots_unread``). Only a digest's prefix is said.

    Raises:
        ExposureError: the register, the run roots or a run they hold cannot be read whole.
    """
    known = versions(store, role)
    manifest = known.get(version)
    if manifest is None:
        return "version_unknown", f"the role has no version {version[:_PREFIX]}"
    said = version[:_PREFIX]
    for line in register_lines(store, role):
        if line.version == version and line.kind == "measurement":
            return "version_measured", (
                f"the register holds a measurement of the version {said}: what its check leaves "
                "out would be chosen after a result of it exists"
            )
    if version in exposed_versions(store, role):
        return "version_exposed", (
            f"the version {said} is marked exposed as the register reads now: it is no "
            "measurement, and its check is not made after it was seen"
        )
    walk = _Walk(runs=[], records=[])
    for root in run_roots(store, role):
        _walk(root, walk, required=True)
    _walk(withheld_root(store, role) / BASELINE_RECORDS, walk, required=False)
    if walk.missing or walk.unread:
        return "run_roots_unread", _roots_unread_words(walk, said)
    digests = frozenset({manifest.held_out.sha256, manifest.validation.sha256})
    for run in sorted(set(walk.runs)):
        try:
            named = load_run_config(run / RUN_RECORD).held_out_sha256
        except Exception as exc:  # noqa: BLE001 - a run that cannot be read cannot be ruled out
            msg = f"a run under the run roots cannot be read: {type(exc).__name__}"
            raise _refuse("register_unreadable", msg) from exc
        if _names_version(list(named), digests):
            return "version_has_runs", (
                f"a run under the role's run roots names the version {said}: its check is made "
                "before any run on it, never after"
            )
    for path in sorted(set(walk.records)):
        fd = _dir_fd(path.parent)
        data = None
        if fd is not None:
            try:
                data = _read_at(fd, path.name, MOST_RECORD_BYTES)
            finally:
                os.close(fd)
        try:
            record = json.loads(data) if data is not None else {}
        except ValueError as exc:
            raise _refuse("register_unreadable", "a raw record cannot be read") from exc
        if isinstance(record, dict) and _names_version(record.get("held_out_sha256"), digests):
            return "version_has_runs", (
                f"a raw record names the version {said}: its check is made before any trial on "
                "it, never after"
            )
    return None


def _roots_unread_words(walk: _Walk, said: str) -> str:
    """Which run roots a look could not read, and what a person does about each kind."""
    parts = []
    if walk.missing:
        gone = ", ".join(str(root) for root in walk.missing)
        parts.append(
            f"the run root {gone} is not there: a person puts it back as it was, with the runs it "
            "held (a root that is gone may have held a run on the version, so making an empty "
            "one in its place is a person's deliberate act, after looking)"
        )
    if walk.unread:
        unread = ", ".join(str(root) for root in walk.unread)
        parts.append(
            f"{unread} holds a link to a directory, which a look does not follow, "
            "or a directory inside a run that looks like a run, which a look does not read: a "
            "person replaces the link with the directory it names, or moves the inner run to a "
            "place of its own beneath a run root"
        )
    return (
        "; ".join(parts) + f". Until then a run on the version {said} cannot be ruled out, so "
        "no check or import of it is made; the harness never drops a root from the run roots"
    )


def _check_refusal(store: Path, role: Role, version: str) -> tuple[str, str] | None:
    """Why a measured run on ``version`` may not be made for want of its blind check; or ``None``.

    A version is measured only once its held-out tier's check is recorded: what the check
    flagged is left out of every held-out figure, so a version with no record, or one whose
    record does not read as the version's, has no held-out figure, and no run on it is
    measured (``held_out_unchecked``, or the record's own reason).
    """
    from physgate.evaluation.tiers.checks import CheckError, read_check

    try:
        record = read_check(store, role, version, manifest=versions(store, role)[version])
    except CheckError as exc:
        reason = str(exc.context.get("refused_because", "check_record_unreadable"))
        return reason, str(exc)
    if record is None:
        return "held_out_unchecked", (
            f"the version {version[:_PREFIX]} the run is on has no record of its blind check: a "
            "held-out tier nobody checked is not scored, so no run on it is measured"
        )
    return None


def _inside_a_run(run_dir: Path, roots: Sequence[Path]) -> bool:
    """Whether a directory between ``run_dir`` and the run root it lies beneath holds a run."""
    for root in roots:
        if not run_dir.is_relative_to(root):
            continue
        for parent in run_dir.parents:
            if parent == root or not parent.is_relative_to(root):
                break
            if (parent / RUN_RECORD).is_file():
                return True
    return False


def version_refusal(config: RunConfig, run_dir: Path | None) -> tuple[str, str] | None:
    """Why a measured run with held-out roots may not start or go on: a reason and its words.

    In order: a held-out entry in no tier-set store; a protected tier whose bytes are not the
    digest the run recorded (``tier_digest`` recomputed now); a tier whose version is not what
    its manifest says, or whose manifest names another digest; a brief in no version of the
    stores the run names, or in several; that version marked exposed by the register, freshly
    scanned; that version with no record of its blind check, or one that does not read as its
    own; a run directory beneath none of the role's run roots; and the pre-run scan of the
    version's two protected tiers. Nothing but a digest's prefix is said: never a task id or
    content. ``None`` if the run may go on.
    """
    try:
        return _version_refusal(config, run_dir)
    except Exception as exc:  # noqa: BLE001 - anything unchecked is a refusal, never a pass
        reason = exc.context.get("refused_because") if isinstance(exc, PerRoleError) else None
        return reason or "register_unreadable", (
            f"the run's tier version cannot be checked: {type(exc).__name__}"
        )


def _version_refusal(config: RunConfig, run_dir: Path | None) -> tuple[str, str] | None:
    for entry in config.held_out:
        if not role_roots((entry,)):
            return "held_out_outside_a_store", (
                "a measured run's held-out roots lie in a tier-set store, and one of this "
                "run's lies in none"
            )
    if len(config.held_out_sha256) != len(config.held_out):
        return "tier_changed", "the run records no digest for its held-out roots"
    tiers: dict[str, tuple[Path, Role, str, str, str]] = {}
    for entry, recorded in zip(config.held_out, config.held_out_sha256, strict=True):
        found = _protected_tier_of(_resolved(entry))
        if found is None:
            continue
        if tier_digest(_resolved(entry)) != recorded:
            return "tier_changed", (
                f"a protected tier is no longer the bytes the run recorded ({recorded[:_PREFIX]})"
            )
        tiers[entry] = (*found, recorded)
    for store, owner, version, tier, recorded in tiers.values():
        try:
            manifest = read_version(role_root(store, owner) / version)
        except PerRoleError:
            return "version_unknown", (
                f"the tier the run recorded as {recorded[:_PREFIX]} is in no version of the store"
            )
        if manifest.tier(tier).sha256 != recorded:
            return "version_unknown", (
                f"no version's manifest names the tier the run recorded as {recorded[:_PREFIX]}"
            )
    on: list[tuple[Path, Role, str]] = []
    for store, role in role_roots(tuple(config.held_out)):
        on += [(store, role, v) for v in _versions_with_brief(store, role, config.brief_sha256)]
    if not on:
        return "brief_in_no_version", (
            "a measured run naming a tier-set store is given a task of one of its versions, and "
            "this run's brief is in none"
        )
    if len(on) > 1:
        return "brief_in_several_versions", (
            f"the run's brief is in {len(on)} versions, so which it is on cannot be told"
        )
    ((store, role, version),) = on
    if version in exposed_versions(store, role):
        return "version_exposed", (
            f"the version {version[:_PREFIX]} the run is on has been seen; it is no measurement "
            "until a new version is generated"
        )
    unchecked = _check_refusal(store, role, version)
    if unchecked is not None:
        return unchecked
    roots = run_roots(store, role)
    if run_dir is None or not any(run_dir.resolve().is_relative_to(r) for r in roots):
        return "run_outside_run_roots", (
            "the run's directory lies beneath none of the role's run roots, where the register "
            "finds every run"
        )
    if _inside_a_run(run_dir.resolve(), roots):
        return "run_inside_a_run", (
            "the run's directory lies inside another run's directory, where a scan may not reach "
            "it; a measured run is made beside the others"
        )
    named = {
        tier: entry
        for entry, (s, r, v, tier, _) in tiers.items()
        if (s, r, v) == (store, role, version)
    }
    return _scan_refusal(config, run_dir, role_root(store, role) / version, named)


def run_roots_refusal(config: RunConfig, run_dir: Path | None) -> tuple[str, str] | None:
    """Why a measured run does not withhold whole the run roots every run on its stores must.

    The earlier runs on a store lie under its roles' run roots, each with every canary of the
    store in its record, the plan and specifications written from its brief, and its answer. A
    measured run withholds whole, in ``withheld_whole``, exactly the run roots of every role's
    root in each store it names, its own role's or another's, spelt as the run-roots logs hold
    them: all of them
    (``run_root_not_withheld``), and nothing else (``withheld_whole_not_a_run_root``). Its
    sessions reach only their own worktree inside them, so its directory lies strictly inside a
    run root, never at one (``run_dir_is_a_run_root``). Only counts are said, never a path.
    ``None`` if the run may go on.
    """
    try:
        return _run_roots_refusal(config, run_dir)
    except Exception as exc:  # noqa: BLE001 - anything unchecked is a refusal, never a pass
        reason = exc.context.get("refused_because") if isinstance(exc, PerRoleError) else None
        return reason or "register_unreadable", (
            f"the run roots the run must withhold cannot be read: {type(exc).__name__}"
        )


def _run_roots_refusal(config: RunConfig, run_dir: Path | None) -> tuple[str, str] | None:
    registered: set[str] = set()
    for store in sorted({store for store, _ in role_roots(tuple(config.held_out))}):
        # Every role's root in the store, named or not: its runs lie on the same store.
        for role in get_args(Role):
            if os.path.lexists(role_root(store, role)):
                registered |= {str(root) for root in run_roots(store, role)}
    given = set(config.withheld_whole)
    missing = registered - given
    if missing:
        return "run_root_not_withheld", (
            f"the run does not withhold whole {len(missing)} of the run roots of the stores it "
            "names, where the earlier runs on them lie: a measured run withholds each of them "
            "whole, spelt as the run roots record it"
        )
    other = given - registered
    if other:
        return "withheld_whole_not_a_run_root", (
            f"{len(other)} of the roots the run withholds whole are no run root of a store it "
            "names: a measured run withholds whole the run roots of its stores, and nothing else"
        )
    if run_dir is not None and str(run_dir.resolve()) in registered:
        return "run_dir_is_a_run_root", (
            "the run's directory is itself a run root, so its sessions would have no place of "
            "their own inside the root they withhold whole; a measured run is made inside one"
        )
    return None
