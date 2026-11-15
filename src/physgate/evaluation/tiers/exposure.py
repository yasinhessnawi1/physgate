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
its place, a broken chain, fewer lines than the head records, or a head with no log (or a log
with no head) refuses, so a shortened register never reads as one with nothing exposed. A log
with neither file is empty: a role whose register was never written.

The register's lines name a version by its id and its protected tiers' digests, and a key that
is a digest (of the incident's run and offset, or of the record's place): never a task id, a
brief, a canary or an outcome. A hand mark carries the person who made it and why.

- **exposure:** a ``held_out_read`` incident in the event log of a run under one of the role's
  run roots; a raw-arm record, under the run roots or beneath the withheld root's baseline
  records, whose ``held_out_seen`` is not false; or a mark made by a person at a terminal. An
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

import fcntl
import hashlib
import json
import os
import secrets
import stat
import tempfile
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Annotated, Any, Literal

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
    source: Literal["incident", "raw_record", "hand"]
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


def _lines_of(dir_fd: int, name: str) -> list[bytes]:
    """The lines of the log ``name`` under ``dir_fd``, each with its newline, held to its head.

    Raises:
        ExposureError: the log or its head is missing beside the other, unreadable, cut, out of
            its chain, or holds fewer lines than its head records.
    """
    data = _read_at(dir_fd, name + LOG_SUFFIX, MOST_LOG_BYTES)
    head_bytes = _read_at(dir_fd, name + HEAD_SUFFIX, MOST_RECORD_BYTES)
    if data is None and head_bytes is None:
        return []
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
    last = _digest(lines[head.lines - 1]) if head.lines else _ZERO
    if last != head.last:
        msg = f"the {name} log's line {head.lines - 1} is not the one its head records"
        raise _refuse("register_unreadable", msg)
    return lines


def _read_log(withheld: Path, name: str) -> list[bytes]:
    """The lines of the log ``name`` in ``withheld``, held to its head; none if neither is there.

    Raises:
        ExposureError: as :func:`_lines_of`, or ``withheld`` is a link.
    """
    fd = _dir_fd(withheld)
    if fd is None:
        return []
    try:
        return _lines_of(fd, name)
    finally:
        os.close(fd)


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


def _append(withheld: Path, name: str, payloads: Sequence[Mapping[str, Any]]) -> int:
    """Append ``payloads`` to the log ``name`` in ``withheld``, chained, and move its head.

    The log is read and held to its head under the lock first, so nothing is appended to a log
    that has been cut. Returns the number of lines the log then holds.

    Raises:
        ExposureError: the write is asked for inside a harness session; the withheld root is
            missing or a link; or the log refuses as read.
    """
    _refuse_inside_a_session()
    fd = _dir_fd(withheld)
    if fd is None:
        msg = f"{withheld} is not there; the role's root is made with it"
        raise _refuse("register_unreadable", msg)
    try:
        lock = os.open(
            name + LOCK_SUFFIX, os.O_RDWR | os.O_CREAT | os.O_NOFOLLOW, 0o600, dir_fd=fd
        )
        try:
            fcntl.flock(lock, fcntl.LOCK_EX)
            lines = _lines_of(fd, name)
            prev = _digest(lines[-1]) if lines else _ZERO
            written: list[bytes] = []
            for at, payload in enumerate(payloads, start=len(lines)):
                # One line each: the canonical bytes end in their newline.
                line = canonical_json({**payload, "n": at, "prev": prev})
                written.append(line)
                prev = _digest(line)
            if written:
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
            if written or not lines:
                head = canonical_json({"format": 1, "lines": total, "last": prev})
                partial = f".{name}{HEAD_SUFFIX}.{secrets.token_hex(8)}"
                out = os.open(
                    partial, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o600, dir_fd=fd
                )
                try:
                    os.write(out, head)
                    os.fsync(out)
                finally:
                    os.close(out)
                os.replace(partial, name + HEAD_SUFFIX, src_dir_fd=fd, dst_dir_fd=fd)
                os.fsync(fd)
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
    source: Literal["incident", "raw_record"]
    versions: frozenset[str]


def _walk(root: Path, out_runs: list[Path], out_records: list[Path], seen: list[int]) -> None:
    """Every run directory and raw record beneath ``root``, no link followed, bounded.

    A directory holding a run's configuration is a run, and is not entered further: what its
    sessions left in their worktrees is no run of the harness's.

    Raises:
        ExposureError: the walk goes past its bounds, or a directory cannot be listed.
    """
    stack = [(root, 0)]
    while stack:
        here, depth = stack.pop()
        try:
            with os.scandir(here) as entries:
                listed = list(entries)
        except FileNotFoundError:
            continue
        except OSError as exc:
            msg = f"{here} cannot be listed, so a run in it cannot be ruled out"
            raise _refuse("register_unreadable", msg) from exc
        seen[0] += len(listed)
        if seen[0] > MOST_ENTRIES:
            msg = f"the run roots hold more than {MOST_ENTRIES} entries"
            raise _refuse("register_unreadable", msg)
        names = {e.name: e for e in listed}
        run = names.get(RUN_RECORD)
        if run is not None and run.is_file(follow_symlinks=False):
            out_runs.append(here)
            continue
        record = names.get(RAW_RECORD)
        if record is not None and not record.is_dir(follow_symlinks=False):
            out_records.append(here / RAW_RECORD)
        for entry in listed:
            if entry.is_dir(follow_symlinks=False):
                if depth + 1 > MOST_DEPTH:
                    msg = f"the run roots hold directories deeper than {MOST_DEPTH}"
                    raise _refuse("register_unreadable", msg)
                stack.append((Path(entry.path), depth + 1))


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


def _record_finding(path: Path, known: Mapping[str, TierSet]) -> Finding | None:
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
    # Only a record that says no canary showed, or that none was looked for, is no exposure:
    # one that says nothing, or anything else, is read as one.
    seen = record.get("held_out_seen", _MISSING)
    if seen is False or seen is None:
        return None
    digests = record.get("held_out_sha256")
    named = [d for d in digests if isinstance(d, str)] if isinstance(digests, list) else []
    return Finding(_digest(f"raw\0{path}".encode()), "raw_record", _named_by(named, known))


def _findings(store: Path, role: Role, roots: Sequence[Path]) -> list[Finding]:
    """Every exposure beneath ``roots`` and the role's withheld baseline records, now.

    Raises:
        ExposureError: a root, a version, a run or a record cannot be read whole.
    """
    known = versions(store, role)
    runs: list[Path] = []
    records: list[Path] = []
    seen = [0]
    for root in [*roots, withheld_root(store, role) / BASELINE_RECORDS]:
        _walk(root, runs, records, seen)
    found: list[Finding] = []
    for run in sorted(set(runs)):
        found += _run_findings(run, known)
    for record in sorted(set(records)):
        finding = _record_finding(record, known)
        if finding is not None:
            found.append(finding)
    return found


def found_exposures(store: Path, role: Role) -> list[Finding]:
    """Every exposure the role's run roots and its withheld baseline records hold now.

    Raises:
        ExposureError: the run roots, a version, a run or a record cannot be read whole.
    """
    return _findings(store, role, run_roots(store, role))


def exposed_versions(store: Path, role: Role) -> frozenset[str]:
    """Every version of the role the register marks exposed, as freshly scanned; it writes nothing.

    Raises:
        ExposureError: the register, the run roots or what they hold cannot be read whole.
    """
    recorded = {line.version for line in register_lines(store, role) if line.kind == "exposure"}
    for finding in found_exposures(store, role):
        recorded |= finding.versions
    return frozenset(recorded)


def _version_fields(manifest: TierSet) -> dict[str, str]:
    return {
        "version": manifest.version,
        "held_out": manifest.held_out.sha256,
        "validation": manifest.validation.sha256,
    }


def record_scan(store: Path, role: Role) -> tuple[int, int]:
    """Append one exposure line per finding and version not yet recorded; (added, already).

    Raises:
        ExposureError: the scan or the append refuses.
    """
    known = versions(store, role)
    lines = register_lines(store, role)
    recorded = {(line.key, line.version) for line in lines if line.kind == "exposure"}
    new: list[dict[str, Any]] = []
    already = 0
    for finding in found_exposures(store, role):
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
    return len(new), already


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
    Exposure.model_validate({**payload, "n": 0, "prev": _ZERO})
    _append(withheld_root(store, role), REGISTER, [payload])


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
        _findings(store, role, [*roots, real])
    except ExposureError as exc:
        why = exc.context.get("refused_because", "register_unreadable")
        msg = f"with {root} among the run roots every scan would refuse ({why}): {exc}"
        raise _refuse("run_root_would_refuse_the_scan", msg) from exc
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


def version_refusal(config: RunConfig, run_dir: Path | None) -> tuple[str, str] | None:
    """Why a measured run with held-out roots may not start or go on: a reason and its words.

    In order: a held-out entry in no tier-set store; a protected tier whose bytes are not the
    digest the run recorded (``tier_digest`` recomputed now); a tier whose version is not what
    its manifest says, or whose manifest names another digest; a brief in no version of the
    stores the run names, or in several; that version marked exposed by the register, freshly
    scanned; a run directory beneath none of the role's run roots; and the pre-run scan of the
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
    roots = run_roots(store, role)
    if run_dir is None or not any(run_dir.resolve().is_relative_to(r) for r in roots):
        return "run_outside_run_roots", (
            "the run's directory lies beneath none of the role's run roots, where the register "
            "finds every run"
        )
    named = {
        tier: entry
        for entry, (s, r, v, tier, _) in tiers.items()
        if (s, r, v) == (store, role, version)
    }
    return _scan_refusal(config, run_dir, role_root(store, role) / version, named)
