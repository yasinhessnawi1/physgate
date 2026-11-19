"""A version's blind check, kept as one record beside the version: written once, read whole.

The blind check (:func:`physgate.evaluation.per_role.author_session.blind_check`) asks a model
three yes-or-no questions of each task of a version's held-out tier: does the brief state every
specification, can it be read one way only, can it be met with an answer of the form it asks
for. A task with any "no" is *flagged*. What the check found is kept as one record per version,
in the role's root beside the version, never inside it, since a version is never written again::

    <store>/<role>/<version>.check.json

**What it holds.** The version's id; the held-out tier's digest and task count as the version's
manifest names them; where the answer came from (``check``: written by the check itself as it
ended; ``imported``: an earlier check's printed answer, taken in once by ``physgate per-role
record-check``, whose pins and time are what the person importing it stated); the checking
model and its pins; when it ran; the session's spend; the counts; and the flagged tasks by the
digest of their ids alone (:func:`.task.id_digest`), never an id, a brief or an answer. And
``sha256``, the digest of the record's canonical JSON with that field left out: a record whose
bytes were changed by hand without it no longer names itself, and is refused.

**Written once.** The record is made as a new file and never replaced (:func:`write_check`); a
check on a version that has one is refused before its session starts, since running a check
again until it passes is what the record is there to stop.

**Read whole, or refused** (:func:`read_check`): a link, anything but a plain file of its own,
a file larger than any record, one that is not a record, one whose digest is not its own, or
one that names another version, role, tier digest or task count than the version's manifest is
refused, with ``refused_because`` naming which. A record that is not there is ``None``: the
version has not been checked.

**The rule it carries** (:func:`left_out`). Every held-out count, pass rate, gap and interval of
the version leaves out the tasks the record flags, and carries beside it how many it left out,
which (by digest) and the record's digest. Every reader that opens the held-out tier holds each
flagged digest to exactly one of its tasks, so a record that names a task the tier does not
hold is refused there. A version with no record is not scored at all: a held-out tier nobody
checked is no measurement. The visible and validation tiers are not touched: the check reads
the held-out tier alone. Were a validation tier ever checked, its answer would be a record of
its own under a name of its own, read by the same readers the same way; none is made, and
nothing reads one.

**A stated limit:** whoever can write the role's root can remove the record. A removed record
reads as none, so the version is refused as unchecked rather than scored whole, and a check
could then be made again; every check's session is kept under the role's withheld root
(``withheld/check/``), where a person sees how many ran.
"""

from __future__ import annotations

import hashlib
import json
import os
import re
import stat
from collections import Counter
from collections.abc import Mapping
from pathlib import Path
from typing import Annotated, Any, Literal

from pydantic import Field, StringConstraints, ValidationError, model_validator

from physgate.evaluation.per_role.exceptions import PerRoleError
from physgate.evaluation.tiers.base import _Frozen
from physgate.evaluation.tiers.manifest import TierSet, read_version
from physgate.evaluation.tiers.store import role_root, version_dir
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
#: The largest check record read or written: counts, pins and a few dozen digests.
MOST_CHECK_BYTES = 64 * 1024
#: The largest printed answer an import reads: the check's one line of counts and digests.
MOST_PRINTED_BYTES = 64 * 1024
FORMAT = 1

Sha1 = Annotated[str, StringConstraints(pattern=r"^[0-9a-f]{40}$")]
Name = Annotated[str, StringConstraints(min_length=1, max_length=200)]
Short = Annotated[str, StringConstraints(min_length=1, max_length=64)]
#: When a check ran: a UTC time to the second, or (an imported answer's) a date.
Checked = Annotated[
    str, StringConstraints(pattern=r"^[0-9]{4}-[0-9]{2}-[0-9]{2}(T[0-9]{2}:[0-9]{2}:[0-9]{2}Z)?$")
]
Count = Annotated[int, Field(ge=0)]


class CheckError(PerRoleError):
    """A check record cannot be written, read or imported as asked; it names no task."""


def _refuse(reason: str, msg: str) -> CheckError:
    return CheckError(msg, refused_because=reason)


def _sorted_unique(digests: tuple[str, ...], what: str) -> None:
    if list(digests) != sorted(set(digests)):
        msg = f"{what} are listed once each, in order"
        raise ValueError(msg)


class CheckPins(_Frozen):
    """What the check's session ran under: its model, the binary and how it was asked."""

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
    source: Literal["check", "imported"]
    checked: Checked
    pins: CheckPins
    session: CheckSpend
    tasks: Annotated[int, Field(ge=1)]
    all_yes: Count
    flagged: tuple[TaskDigest, ...]

    @model_validator(mode="after")
    def _holds_its_counts(self) -> _CheckBody:
        _sorted_unique(self.flagged, "the flagged tasks")
        if self.all_yes + len(self.flagged) != self.tasks:
            msg = "the tasks with all three answers yes and those flagged are not every task"
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
    """What every held-out figure of a version carries beside it: the tasks left out of it.

    ``count`` tasks, named by ``digests``, which the version's check record (``check_sha256``)
    flagged. ``count`` is 0 when the check flagged none; it is said all the same.
    """

    count: Count
    digests: tuple[TaskDigest, ...]
    check_sha256: Sha256

    @model_validator(mode="after")
    def _counts_its_digests(self) -> LeftOut:
        _sorted_unique(self.digests, "the tasks left out")
        if self.count != len(self.digests):
            msg = "the count left out is not the number of tasks named"
            raise ValueError(msg)
        return self


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
    return LeftOut(count=len(record.flagged), digests=record.flagged, check_sha256=record.sha256)


def check_path(store: Path, role: Role, version: str) -> Path:
    """Where the version's check record lies: in the role's root, beside the version."""
    return role_root(store, role) / f"{version}{CHECK_SUFFIX}"


def _record_at(path: Path) -> CheckRecord | None:
    """The record at ``path``, read without following a link; ``None`` if it is not there.

    Raises:
        CheckError: it is a link, not a plain file of its own, larger than any record, or not a
            record (``check_record_unreadable``), or its digest is not its own
            (``check_record_changed``).
    """
    try:
        fd = os.open(path, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK)
    except FileNotFoundError:
        return None
    except OSError as exc:
        msg = f"the check record cannot be opened as a plain file: {exc.strerror}"
        raise _refuse("check_record_unreadable", msg) from None
    try:
        info = os.fstat(fd)
        if not stat.S_ISREG(info.st_mode) or info.st_nlink != 1:
            raise _refuse("check_record_unreadable", "the check record is not a file of its own")
        with os.fdopen(os.dup(fd), "rb") as handle:
            raw = handle.read(MOST_CHECK_BYTES + 1)
    finally:
        os.close(fd)
    if len(raw) > MOST_CHECK_BYTES:
        raise _refuse("check_record_unreadable", "the check record is larger than any record is")
    try:
        shape = json.loads(raw)
    except ValueError:
        raise _refuse("check_record_unreadable", "the check record is not a record") from None
    if isinstance(shape, dict) and shape.get("sha256") != record_digest(shape):
        msg = "the check record's bytes are not the ones its digest names: it was changed"
        raise _refuse("check_record_changed", msg)
    try:
        return CheckRecord.model_validate_json(raw)
    except ValidationError:
        raise _refuse("check_record_unreadable", "the check record is not a record") from None


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


def write_check(store: Path, role: Role, record: CheckRecord) -> None:
    """Write ``record`` beside its version as a new file; one already there is never replaced.

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
    data = canonical_json(record.model_dump(mode="json"))
    try:
        fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o600)
    except FileExistsError:
        msg = (
            f"the version {record.version[:8]} has a check record already; a version is checked "
            "once, and its record is never replaced"
        )
        raise _refuse("check_recorded", msg) from None
    except OSError as exc:
        msg = f"the check record cannot be written: {exc.strerror}"
        raise _refuse("check_record_unwritten", msg) from None
    try:
        os.write(fd, data)
        os.fsync(fd)
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


class _Printed(_Frozen):
    """The blind check's answer as the command printed it: counts, digests and the spend."""

    tasks: Annotated[int, Field(ge=1)]
    answered: Literal[True]
    all_yes: Count
    flagged: tuple[TaskDigest, ...]
    session: CheckSpend
    #: Printed by a check that recorded its answer itself; an earlier check printed neither.
    version: Sha256 | None = None
    record: Sha256 | None = None


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


def import_check(
    store: Path,
    role: Role,
    version: str,
    printed: bytes,
    *,
    pins: CheckPins,
    checked: str,
) -> CheckRecord:
    """Take an earlier check's printed answer in as the version's check record, once.

    For a version whose check ran before checks kept their record, and whose answer exists
    only as the line the command printed. The version is read as every reader reads it
    (:func:`.manifest.read_version`). The printed answer names no version, so it is held to
    this one by what it says: an answer (``answered``), for as many tasks as the version's
    held-out tier holds, whose counts add up, and each of whose flagged digests is the digest
    of exactly one task of that tier. Where it names a version (a later check's line), that
    version is this one. ``pins`` and ``checked`` are what the person importing it states; the
    record says it was imported.

    Raises:
        CheckError: the answer is not one, is not this version's, or the version has a record
            already; the reason is counted, and no task is named.
        TierSetError: the version is not what its manifest says.
    """
    manifest = read_version(version_dir(store, role, version))
    if len(printed) > MOST_PRINTED_BYTES:
        raise _refuse("check_answer_unreadable", "the printed answer is larger than any is")
    try:
        shape = json.loads(printed)
    except ValueError:
        raise _refuse(
            "check_answer_unreadable", "the printed answer is not one line of JSON"
        ) from None
    if isinstance(shape, dict) and shape.get("answered") is False:
        msg = "the check gave no answer (answered: false), so there is nothing to record"
        raise _refuse("check_gave_no_answer", msg)
    try:
        answer = _Printed.model_validate_json(printed)
    except ValidationError:
        msg = "the printed answer is not the blind check's: counts, flagged digests and the spend"
        raise _refuse("check_answer_unreadable", msg) from None
    if answer.version is not None and answer.version != version:
        raise _refuse("check_answer_not_the_version", "the printed answer names another version")
    if answer.tasks != manifest.held_out.count or answer.all_yes + len(answer.flagged) != (
        answer.tasks
    ):
        msg = (
            f"the printed answer counts {answer.tasks} task(s), {answer.all_yes} all yes and "
            f"{len(answer.flagged)} flagged; the version's held-out tier holds "
            f"{manifest.held_out.count}"
        )
        raise _refuse("check_answer_not_the_version", msg)
    if len(set(answer.flagged)) != len(answer.flagged):
        raise _refuse("check_answer_not_the_version", "the printed answer flags a task twice")
    held = _held_out_digests(store, role, version)
    if any(held[digest] != 1 for digest in answer.flagged):
        unmatched = sum(1 for digest in answer.flagged if held[digest] != 1)
        msg = (
            f"{unmatched} flagged digest(s) of the printed answer are not each the digest of "
            "exactly one task of the version's held-out tier"
        )
        raise _refuse("check_answer_not_the_version", msg)
    record = make_check(
        role=role,
        version=version,
        tier="held_out",
        tier_sha256=manifest.held_out.sha256,
        source="imported",
        checked=checked,
        pins=pins.model_dump(mode="json"),
        session=answer.session.model_dump(mode="json"),
        tasks=answer.tasks,
        all_yes=answer.all_yes,
        flagged=list(answer.flagged),
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
    "LeftOut",
    "check_in_place",
    "check_path",
    "counts",
    "import_check",
    "left_out",
    "make_check",
    "read_check",
    "record_digest",
    "write_check",
]
