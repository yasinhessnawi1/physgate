"""A version's blind check, kept as one record beside the version: written once, read whole.

The blind check (:func:`physgate.evaluation.per_role.author_session.blind_check`) asks a model
three yes-or-no questions of each task of a version's held-out tier: does the brief state every
specification, can it be read one way only, can it be met with an answer of the form it asks
for. A task with any "no" is *flagged*. What the check found is kept as one record per version,
in the role's root beside the version, never inside it, since a version is never written again::

    <store>/<role>/<version>.check.json

**What it holds.** The version's id; the held-out tier's digest and task count as the version's
manifest names them; where the answer came from (``source``: ``check``, written by the check
itself as it ended; ``imported``, derived afterwards from the check's kept session by
``physgate per-role record-check``); the checking model and its pins; the kept session it came
from (its id, its stream's digest, and how it is tied to the version); when it ran; the
session's spend; the counts; and the flagged tasks by the digest of their ids alone
(:func:`.task.id_digest`), never an id, a brief or an answer. And ``sha256``, the digest of the
record's canonical JSON with that field left out: a record whose bytes were changed by hand
without it no longer names itself, and is refused.

**Written once, whole.** The record is written to a temporary file beneath the role's withheld
root, synced, then renamed into place under its own name, under the writers' lock and only if
no record is there: one is never replaced (:func:`write_check`), and a crash leaves either no
record or a whole one, never an empty one. A check on a version that has one is refused before
its session starts, since running a check again until it passes is what the record is there to
stop.

**Before any result.** A check, or an import, of a version is refused once the version has a
measurement or an exposure in the register, or any run or raw record names it
(:func:`physgate.evaluation.tiers.exposure.results_refusal`): what is left out is chosen before
any result exists, and never after, even if a record was removed.

**Read whole, or refused** (:func:`read_check`): a link, anything but a plain file of its own,
a file larger than any record, one that is not a record, one whose digest is not its own, or
one that names another version, role, tier digest or task count than the version's manifest is
refused, with ``refused_because`` naming which and, for a record that cannot be read, what a
person does about it. A record that is not there is ``None``: the version has not been checked.

**The rule it carries** (:func:`left_out`). Every held-out count, pass rate, gap and interval of
the version leaves out the tasks the record flags. The flagged tasks' digests stay in the record
and in the withheld vectors; whatever a person reads or a commit carries (the report, ``gaps``'
output, a trend line, a run's tiers record) says only how many were left out, the record's
digest and its source (:func:`said`), since a task's id may be guessed and its digest then
tells which task was flagged. A version with no record is not scored at all: a held-out tier
nobody checked is no measurement. The visible and validation tiers are not touched: the check
reads the held-out tier alone.

**A stated limit:** whoever can write the role's root can remove the record. A removed record
reads as none, so the version is refused as unchecked rather than scored whole; a check or an
import could then be made again only while nothing has measured, seen or run on the version.
"""

from __future__ import annotations

import contextlib
import fcntl
import hashlib
import json
import os
import re
import secrets
import stat
from collections import Counter
from collections.abc import Mapping
from pathlib import Path
from typing import Annotated, Any, Literal

from pydantic import Field, StringConstraints, ValidationError, model_validator

from physgate.evaluation.per_role.exceptions import PerRoleError
from physgate.evaluation.tiers.base import _Frozen
from physgate.evaluation.tiers.manifest import TierSet, read_version
from physgate.evaluation.tiers.store import role_root, version_dir, withheld_root
from physgate.evaluation.tiers.task import (
    Role,
    Sha256,
    TaskDigest,
    canonical_json,
    id_digest,
    parse_task,
)

#: What a version's check record is called beside it: ``<version>.check.json``.
CHECK_SUFFIX = ".check.json"
CHECK_NAME = re.compile(r"^[0-9a-f]{64}\.check\.json$")
#: The writers' lock beneath the role's withheld root, held while a record is put in place.
CHECK_LOCK = "check-record.lock"
#: The largest check record read or written: counts, pins and a few dozen digests.
MOST_CHECK_BYTES = 64 * 1024
#: The largest printed answer an import reads: the check's one line of counts and digests.
MOST_PRINTED_BYTES = 64 * 1024
FORMAT = 1

Sha1 = Annotated[str, StringConstraints(pattern=r"^[0-9a-f]{40}$")]
Name = Annotated[str, StringConstraints(min_length=1, max_length=200)]
Short = Annotated[str, StringConstraints(min_length=1, max_length=64)]
SessionId = Annotated[str, StringConstraints(pattern=r"^[A-Za-z0-9-]{1,64}$")]
#: When a check ran: a UTC time to the second, or (a record written before times were kept) a
#: date.
Checked = Annotated[
    str, StringConstraints(pattern=r"^[0-9]{4}-[0-9]{2}-[0-9]{2}(T[0-9]{2}:[0-9]{2}:[0-9]{2}Z)?$")
]
Count = Annotated[int, Field(ge=0)]
Source = Literal["check", "imported"]


class CheckError(PerRoleError):
    """A check record cannot be written, read or imported as asked; it names no task."""


def _refuse(reason: str, msg: str) -> CheckError:
    return CheckError(msg, refused_because=reason)


def _sorted_unique(digests: tuple[str, ...], what: str) -> None:
    if list(digests) != sorted(set(digests)):
        msg = f"{what} are listed once each, in order"
        raise ValueError(msg)


class CheckPins(_Frozen):
    """What a check's session ran under, as the check itself was given it."""

    model: Name
    #: The implementers' model, which the checking model was held apart from.
    implementer_model: Name
    claude_version: Short
    effort: Short
    max_output_tokens: Annotated[int, Field(ge=1)]
    #: ``default``: the binary's own endpoint; ``given``: one the command named (a scripted one
    #: in tests). Never the address itself.
    endpoint: Literal["default", "given"]
    #: The harness checkout the check ran from, and whether it was clean; ``None`` if unknown.
    commit: Sha1 | None
    clean: bool | None


class ImportedPins(_Frozen):
    """What an imported check's session ran under, as its kept stream names it."""

    #: The model and the binary's version the session's stream names as it started.
    model: Name
    claude_version: Short
    #: The implementers' model, as the person importing states it: the session's model is held
    #: apart from it. The one thing in an imported record that its session does not record.
    implementer_model: Name


class KeptSession(_Frozen):
    """The check's session as the role's withheld root keeps it, and how it is the version's.

    ``bound_by``: ``ran``, the check itself ran it on the version; ``tasks_read``, its stream
    holds its whole read of the tasks it was given, and those are exactly what the version's
    held-out tier gives a check now; ``answer_keys``, only its answer ties it: the answer's keys
    are exactly the digests of the version's held-out task ids, so it is an answer on a tier with
    those ids (any version whose held-out tier has the same ids would match it as well).
    """

    session_id: SessionId
    #: The digest of the session's kept stream; ``None`` where the check kept none.
    stream_sha256: Sha256 | None
    bound_by: Literal["ran", "tasks_read", "answer_keys"]


class CheckSpend(_Frozen):
    """The check's session, as its record counted it."""

    end: Short | None = None
    tokens: Count | None = None
    cap: Count | None = None
    wall_clock_s: Annotated[float, Field(ge=0)] | Count | None = None
    tokens_not_in_binary_totals: Count | None = None


class _CheckBody(_Frozen):
    """A check record but its own digest: what the digest is taken of."""

    format: Literal[1]
    role: Role
    version: Sha256
    #: The tier the check reads. A check of another tier would be a record of its own.
    tier: Literal["held_out"]
    #: The held-out tier's digest, as the version's manifest names it.
    tier_sha256: Sha256
    source: Source
    checked: Checked
    pins: CheckPins | ImportedPins
    kept: KeptSession
    session: CheckSpend
    tasks: Annotated[int, Field(ge=1)]
    all_yes: Count
    flagged: tuple[TaskDigest, ...]
    #: The digest of the answer file the flagged tasks were computed from: as the check read
    #: it, or (imported) as its kept session's stream shows it written.
    answer_sha256: Sha256

    @model_validator(mode="after")
    def _holds_its_counts(self) -> _CheckBody:
        _sorted_unique(self.flagged, "the flagged tasks")
        if self.all_yes + len(self.flagged) != self.tasks:
            msg = "the tasks with all three answers yes and those flagged are not every task"
            raise ValueError(msg)
        ran = self.source == "check"
        if ran != isinstance(self.pins, CheckPins) or ran != (self.kept.bound_by == "ran"):
            msg = (
                "a check's own record carries the pins it was given and the session it ran; an "
                "imported one, what its kept session records and how that session is the version's"
            )
            raise ValueError(msg)
        return self


class CheckRecord(_CheckBody):
    """One version's blind check: what it was, and the tasks it flagged, by digest only."""

    #: The digest of the record's canonical JSON with this field left out.
    sha256: Sha256

    @model_validator(mode="after")
    def _names_itself(self) -> CheckRecord:
        if self.sha256 != record_digest(self.model_dump(mode="json")):
            msg = "the record's digest is not the digest of what it holds"
            raise ValueError(msg)
        return self


class LeftOut(_Frozen):
    """What a held-out vector of a version carries: the tasks left out of it, by digest.

    ``count`` tasks, named by ``digests``, which the version's check record (``check_sha256``,
    whose answer came from ``source``) flagged. ``count`` is 0 when the check flagged none; it is
    said all the same. Kept beneath the role's withheld root only: what a person reads carries
    :class:`LeftOutSaid` instead.
    """

    count: Count
    digests: tuple[TaskDigest, ...]
    check_sha256: Sha256
    source: Source

    @model_validator(mode="after")
    def _counts_its_digests(self) -> LeftOut:
        _sorted_unique(self.digests, "the tasks left out")
        if self.count != len(self.digests):
            msg = "the count left out is not the number of tasks named"
            raise ValueError(msg)
        return self


class LeftOutSaid(_Frozen):
    """What every held-out figure a person reads carries beside it: how many were left out.

    The count, the check record's digest and where its answer came from; never which tasks: a
    task's id may be guessed, and its digest would then say which held-out task was flagged.
    Two figures left out the same tasks exactly when they name the same record.
    """

    count: Count
    check_sha256: Sha256
    source: Source


def record_digest(fields: Mapping[str, Any]) -> str:
    """The digest a check record names itself by: of its canonical JSON, ``sha256`` left out."""
    return hashlib.sha256(
        canonical_json({key: value for key, value in fields.items() if key != "sha256"})
    ).hexdigest()


def make_check(**fields: Any) -> CheckRecord:  # noqa: ANN401
    """The check record holding ``fields``, its format and its own digest.

    Raises:
        CheckError: the fields do not make a record (``check_record_invalid``).
    """
    payload = {"format": FORMAT, **fields}
    if isinstance(payload.get("flagged"), list | tuple):
        payload["flagged"] = sorted(set(payload["flagged"]))
    try:
        body = _CheckBody.model_validate_json(json.dumps(payload)).model_dump(mode="json")
        return CheckRecord.model_validate_json(json.dumps({**body, "sha256": record_digest(body)}))
    except ValidationError as exc:
        msg = f"not a check record: {exc.errors()[0]['msg']}"
        raise _refuse("check_record_invalid", msg) from None


def left_out(record: CheckRecord) -> LeftOut:
    """What the version's held-out figures leave out, as ``record`` flags it."""
    return LeftOut(
        count=len(record.flagged),
        digests=record.flagged,
        check_sha256=record.sha256,
        source=record.source,
    )


def said(left: LeftOut) -> LeftOutSaid:
    """What of ``left`` a person may read: the count, the record's digest and its source."""
    return LeftOutSaid(count=left.count, check_sha256=left.check_sha256, source=left.source)


def check_path(store: Path, role: Role, version: str) -> Path:
    """Where the version's check record lies: in the role's root, beside the version."""
    return role_root(store, role) / f"{version}{CHECK_SUFFIX}"


def _unreadable(path: Path, why: str, reason: str = "check_record_unreadable") -> CheckError:
    """A refusal of the record at ``path`` that says what a person does about it."""
    msg = (
        f"the check record {path} {why}. The harness never replaces or removes a check record. "
        "A person who has looked at it may delete it by hand: a deliberate act, after which the "
        "version reads as unchecked, and a new check or import of it is refused once the "
        "register holds a measurement or an exposure of it or any run names it"
    )
    return _refuse(reason, msg)


def _record_at(path: Path) -> CheckRecord | None:
    """The record at ``path``, read without following a link; ``None`` if it is not there.

    Raises:
        CheckError: it is a link, not a plain file of its own, larger than any record, or not a
            record (``check_record_unreadable``), or its digest is not its own
            (``check_record_changed``); the words name the file and what a person does.
    """
    try:
        fd = os.open(path, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK)
    except FileNotFoundError:
        return None
    except OSError as exc:
        raise _unreadable(path, f"cannot be opened as a plain file ({exc.strerror})") from None
    try:
        info = os.fstat(fd)
        if not stat.S_ISREG(info.st_mode) or info.st_nlink != 1:
            raise _unreadable(path, "is not a file of its own")
        with os.fdopen(os.dup(fd), "rb") as handle:
            raw = handle.read(MOST_CHECK_BYTES + 1)
    finally:
        os.close(fd)
    if len(raw) > MOST_CHECK_BYTES:
        raise _unreadable(path, "is larger than any record is")
    try:
        shape = json.loads(raw)
    except ValueError:
        raise _unreadable(path, "is not a record") from None
    if isinstance(shape, dict) and shape.get("sha256") != record_digest(shape):
        raise _unreadable(
            path,
            "holds bytes other than the ones its digest names: it was changed",
            "check_record_changed",
        )
    try:
        return CheckRecord.model_validate_json(raw)
    except ValidationError:
        raise _unreadable(path, "is not a record") from None


def read_check(
    store: Path, role: Role, version: str, *, manifest: TierSet | None = None
) -> CheckRecord | None:
    """The version's check record, held to its name and its version; ``None`` if it has none.

    The record names the role and version it is filed under; given the version's ``manifest``
    (read by the caller as every reader reads it), its tier digest and task count are the
    manifest's held-out ones. Nothing of the tier is opened here.

    Raises:
        CheckError: the record refuses as read (:func:`_record_at`), or it is another
            version's, role's or tier's (``check_record_not_the_version``).
    """
    record = _record_at(check_path(store, role, version))
    if record is None:
        return None
    named = record.role == role and record.version == version
    if manifest is not None:
        named = (
            named
            and manifest.version == version
            and record.tier_sha256 == manifest.held_out.sha256
            and record.tasks == manifest.held_out.count
        )
    if not named:
        msg = (
            f"the check record of {version[:8]} names another version, role, held-out tier or "
            "task count than the version's own"
        )
        raise _refuse("check_record_not_the_version", msg)
    return record


def check_in_place(path: Path) -> bool:
    """Whether ``path``, directly in a role's root, is a sound check record of a version there.

    Its name is a version's id and the suffix, exactly; it reads as a record
    (:func:`_record_at`) of that version and of the role whose root it lies in; and the version
    is there. Anything else under such a name is out of place, as any other stray entry is.
    """
    if CHECK_NAME.fullmatch(path.name) is None:
        return False
    version = path.name.removesuffix(CHECK_SUFFIX)
    try:
        record = _record_at(path)
    except CheckError:
        return False
    return (
        record is not None
        and record.version == version
        and record.role == path.parent.name
        and os.path.isdir(path.parent / version)
        and not os.path.islink(path.parent / version)
    )


def _recorded(record: CheckRecord) -> CheckError:
    msg = (
        f"the version {record.version[:8]} has a check record already; a version is checked "
        "once, and its record is never replaced"
    )
    return _refuse("check_recorded", msg)


def write_check(store: Path, role: Role, record: CheckRecord) -> None:
    """Write ``record`` beside its version, whole and once; one already there is never replaced.

    The bytes go to a new temporary file beneath the role's withheld root (where nothing judges
    a stray entry, on the same volume as the role's root), which is synced and then renamed into
    place under the record's name, so a crash leaves no record or a whole one, never an empty or
    a cut one. The rename is made under the writers' lock beneath the withheld root, after a
    look, under that lock, that no record is there: no writer ever replaces one. No second name
    is made (a hard link inside the protected root would trip every later session's
    tripwire). The temporary name is removed whatever happens.

    Raises:
        CheckError: it is another role's (``check_record_not_the_version``), or the version has
            a record already (``check_recorded``), or it cannot be written
            (``check_record_unwritten``).
        ExposureError: asked for inside a harness session's environment.
    """
    from physgate.evaluation.tiers.exposure import _refuse_inside_a_session

    _refuse_inside_a_session()
    if record.role != role:
        raise _refuse("check_record_not_the_version", "the check record is another role's")
    path = check_path(store, role, record.version)
    if os.path.lexists(path):
        raise _recorded(record)
    data = canonical_json(record.model_dump(mode="json"))
    temporary = withheld_root(store, role) / f".{record.version}.check.{secrets.token_hex(8)}"
    try:
        fd = os.open(temporary, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o600)
    except OSError as exc:
        msg = f"the check record cannot be written: {exc.strerror}"
        raise _refuse("check_record_unwritten", msg) from None
    try:
        try:
            view = memoryview(data)
            while view:
                view = view[os.write(fd, view) :]
            os.fsync(fd)
        finally:
            os.close(fd)
        lock = os.open(
            withheld_root(store, role) / CHECK_LOCK, os.O_RDWR | os.O_CREAT | os.O_NOFOLLOW, 0o600
        )
        try:
            fcntl.flock(lock, fcntl.LOCK_EX)
            # Under the lock no other writer makes a record: one there now is never replaced.
            if os.path.lexists(path):
                raise _recorded(record)
            os.rename(temporary, path)
            _sync_directory(path.parent)
        finally:
            os.close(lock)
    except OSError as exc:
        msg = f"the check record cannot be written: {exc.strerror}"
        raise _refuse("check_record_unwritten", msg) from None
    finally:
        with contextlib.suppress(FileNotFoundError):
            os.unlink(temporary)


def _sync_directory(directory: Path) -> None:
    fd = os.open(directory, os.O_RDONLY | os.O_DIRECTORY)
    try:
        os.fsync(fd)
    finally:
        os.close(fd)


def stream_digest(path: Path) -> str | None:
    """The digest of a kept session's stream at ``path``, a plain file of its own; else ``None``."""
    try:
        fd = os.open(path, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK)
    except OSError:
        return None
    try:
        info = os.fstat(fd)
        if not stat.S_ISREG(info.st_mode) or info.st_nlink != 1:
            return None
        digest = hashlib.sha256()
        with os.fdopen(os.dup(fd), "rb") as handle:
            for block in iter(lambda: handle.read(1 << 20), b""):
                digest.update(block)
        return digest.hexdigest()
    finally:
        os.close(fd)


def counts(record: CheckRecord) -> dict[str, Any]:
    """A record's counts, as a person may be shown them: never a digest of a task."""
    return {
        "tasks": record.tasks,
        "all_yes": record.all_yes,
        "flagged": len(record.flagged),
        "source": record.source,
    }


def _held_out_digests(store: Path, role: Role, version: str) -> Counter[str]:
    """How many tasks of the version's held-out tier have each id digest; nothing is named.

    Raises:
        CheckError: a task of the tier cannot be read; only the tier is said.
    """
    directory = version_dir(store, role, version) / "held_out"
    found: Counter[str] = Counter()
    try:
        entries = sorted(p for p in directory.iterdir() if p.is_dir() and not p.is_symlink())
        for entry in entries:
            found[id_digest(parse_task((entry / "task.json").read_bytes()).id)] += 1
    except (OSError, PerRoleError):
        # The error may name a task; only the tier is said.
        raise _refuse("tier_unreadable", "a task of the held-out tier cannot be read") from None
    return found


def _given_to_the_check(store: Path, role: Role, version: str) -> object:
    """The tasks a blind check of the version is given now, as its tasks file holds them.

    Raises:
        CheckError: a task of the tier does not load; only the tier is said.
    """
    from physgate.evaluation.tiers.check_tasks import bundle

    try:
        return json.loads(json.dumps(bundle(version_dir(store, role, version) / "held_out")))
    except (OSError, PerRoleError):
        raise _refuse("tier_unreadable", "a task of the held-out tier cannot be read") from None


def _printed_agrees(printed: bytes, derived: Mapping[str, Any], version: str) -> bool:
    """Whether the line the check printed is exactly what its kept session derives."""
    if len(printed) > MOST_PRINTED_BYTES:
        return False
    try:
        shape = json.loads(printed)
    except ValueError:
        return False
    if not isinstance(shape, dict):
        return False
    if "version" in shape and shape.pop("version") != version:
        return False
    return bool(shape == dict(derived))


def import_check(
    store: Path,
    role: Role,
    version: str,
    *,
    implementer_model: str,
    printed: bytes | None = None,
) -> CheckRecord:
    """Derive the version's check record from the check's kept session, and write it, once.

    For a version whose check ran before checks kept their record. Nothing is taken from a
    person but the implementers' model: the answer is what the kept session's stream shows it
    wrote to its answer file (:mod:`.check_sessions`), the flagged tasks are computed again
    from it and the version's held-out tier, and the pins, the time and the spend are what the
    session recorded. The import is refused:

    - once anything has measured, seen or run on the version (``results_refusal``), or the
      version has a record (``check_recorded``);
    - when no kept session answered on the version (``check_session_missing``), or more than one
      did (``check_sessions_several``: a person must look); a session that ended without an
      answer, or answered on another tier, is passed over;
    - when a kept session cannot be read whole, or named its answer file by a tool other than
      its file-write tool without one write that landed (``check_session_unclear``);
    - when the session's whole read of its tasks file is not what the version's held-out tier
      gives a check now (``check_session_not_the_version``);
    - when its model is the implementers' (``checked_on_the_implementers_model``);
    - when the store holds work a session left (``work_left``): a check that left it may have
      been refused;
    - when ``printed`` (the line the check printed) is given and is not exactly what the
      session derives (``check_answer_disagrees``); or is not given where the session's record
      is of the earlier kind, which says neither whether the check took the answer nor what the
      file held (``check_answer_unconfirmed``), or where any call but a read followed the
      answer's last write, or the digest the record keeps of the file is not the written
      answer's (``check_answer_not_derivable``).

    A session is passed over unless it ended as a session ends (``end`` is ``ended``), its
    stream showed no canary, and, where its record says what the check made of its answer, every
    gate passed (``answer_taken`` is ``true``).

    Raises:
        CheckError: as above; the reason is counted, and no task is named.
        TierSetError: the version is not what its manifest says.
        ExposureError: the register or the run roots cannot be read whole.
    """
    from physgate.evaluation.tiers.check_sessions import kept_answers
    from physgate.evaluation.tiers.check_tasks import QUESTIONS
    from physgate.evaluation.tiers.exposure import results_refusal
    from physgate.evaluation.tiers.store import leftovers

    manifest = read_version(version_dir(store, role, version))
    refusal = results_refusal(store, role, version)
    if refusal is not None:
        raise _refuse(*refusal)
    try:
        left = {reason: n for reason, n in leftovers(store).items() if n}
    except OSError as exc:
        raise _refuse("work_left", f"the store cannot be read whole: {exc}") from None
    if left:
        msg = (
            f"the store holds work a session left ({left}): a check that left it may have been "
            "refused, so no kept session's answer is taken until a person has looked"
        )
        raise _refuse("work_left", msg)
    if read_check(store, role, version, manifest=manifest) is not None:
        raise _refuse("check_recorded", "the version has a check record already")
    held = _held_out_digests(store, role, version)
    if any(n != 1 for n in held.values()) or sum(held.values()) != manifest.held_out.count:
        msg = "the held-out tier's tasks are not each one id digest of the manifest's count"
        raise _refuse("tier_unreadable", msg)
    # An answer the check took: on this tier, in a session that ended as a session ends, whose
    # stream showed no canary, and, where its record says, one every gate of the check passed.
    answered = [
        kept
        for kept in kept_answers(store, role)
        if kept.answer is not None
        and set(kept.answer) == set(held)
        and kept.took
        and kept.ended
        and kept.taken is not False
    ]
    if not answered:
        msg = (
            f"no kept session of the role's blind check answered on the version {version[:8]}: "
            "its answer is not in the store, so nothing is recorded"
        )
        raise _refuse("check_session_missing", msg)
    if len(answered) > 1:
        msg = (
            f"{len(answered)} kept sessions of the role's blind check answered on the version "
            f"{version[:8]} ({', '.join(k.session_id for k in answered)}): which answer the check "
            "gave cannot be told from the store, so nothing is recorded; a person must look"
        )
        raise _refuse("check_sessions_several", msg)
    (kept,) = answered
    assert kept.answer is not None  # noqa: S101 - chosen above
    if kept.model.strip() == implementer_model.strip():
        msg = "the kept session ran on the implementers' model; a blind check runs on another"
        raise _refuse("checked_on_the_implementers_model", msg)
    bound_by: Literal["tasks_read", "answer_keys"] = "answer_keys"
    if kept.tasks_read is not None:
        if kept.tasks_read != _given_to_the_check(store, role, version):
            msg = (
                "the tasks the kept session read are not the ones the version's held-out tier "
                "gives a check: it is not this version's check"
            )
            raise _refuse("check_session_not_the_version", msg)
        bound_by = "tasks_read"
    flagged = sorted(k for k, a in kept.answer.items() if not all(a[q] for q in QUESTIONS))
    derived = {
        "tasks": len(held),
        "answered": True,
        "all_yes": len(held) - len(flagged),
        "flagged": flagged,
        "session": kept.spent,
    }
    if printed is not None and not _printed_agrees(printed, derived, version):
        msg = (
            "the line given as the check's printed answer is not exactly what its kept session "
            "shows it answered: nothing is recorded"
        )
        raise _refuse("check_answer_disagrees", msg)
    if printed is None and kept.taken is None:
        msg = (
            "the kept session's record is of the earlier kind, which does not say whether the "
            "check took its answer or what the answer file held as it read it: its answer is "
            "taken only with the line the check printed (--from), which must agree exactly"
        )
        raise _refuse("check_answer_unconfirmed", msg)
    if printed is None and (kept.touched_after or kept.answer_sha256 != kept.written_sha256):
        msg = (
            "after the kept session last wrote its answer file a tool call other than a read "
            "followed, or the file the check read is not the one the stream shows written, so "
            "what the check read at its end cannot be told from the stream alone; give the line "
            "the check printed (--from), which must agree with it exactly"
        )
        raise _refuse("check_answer_not_derivable", msg)
    record = make_check(
        role=role,
        version=version,
        tier="held_out",
        tier_sha256=manifest.held_out.sha256,
        source="imported",
        checked=kept.written_at,
        pins={
            "model": kept.model,
            "claude_version": kept.claude_version,
            "implementer_model": implementer_model,
        },
        kept={
            "session_id": kept.session_id,
            "stream_sha256": kept.stream_sha256,
            "bound_by": bound_by,
        },
        session=kept.spent,
        tasks=len(held),
        all_yes=len(held) - len(flagged),
        flagged=flagged,
        answer_sha256=kept.written_sha256,
    )
    write_check(store, role, record)
    return record


__all__ = [
    "CHECK_NAME",
    "CHECK_SUFFIX",
    "CheckError",
    "CheckPins",
    "CheckRecord",
    "CheckSpend",
    "ImportedPins",
    "KeptSession",
    "LeftOut",
    "LeftOutSaid",
    "check_in_place",
    "check_path",
    "counts",
    "import_check",
    "left_out",
    "make_check",
    "read_check",
    "record_digest",
    "said",
    "stream_digest",
    "write_check",
]
