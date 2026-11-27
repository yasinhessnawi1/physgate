"""What a session's end records about its series: each sealed record, and what was set aside.

These shapes ride on the session's end line in the run's event log, so they import nothing
heavier than pydantic: the event log is read by every command, and the record format itself
loads the unit registry.

A sealed record is named by its id and held by its digest and length, the way a trajectory
is; with it go the script that produced it, by its path in the worktree, the digest of the
script's bytes, and the git blob id those bytes have in the run's repository, so the change
check can confirm that the script the record names is the one the attempt committed.

What the collector did not seal is listed too, never dropped in silence: a file refused
(not a record, or a record whose provenance does not hold) with its reason, and a file
discarded (a writer's temporary file, what an earlier session left in the outbox, or a record
whose module code changed or went after it was written). A discarded record carries the seal
of the bytes collected, so its review can name exactly the record set aside.
"""

from __future__ import annotations

from typing import Annotated, Literal, Self

from pydantic import BaseModel, ConfigDict, Field, StringConstraints, model_validator

#: The marker every record carries. A later shape is a new marker and a new model.
FORMAT = "series.v1"
#: The most bytes one record's file may hold.
MAX_FILE_BYTES = 4 * 1024 * 1024
#: An id, a group, a trace's name and an input's name: lower-case, safe as a file name.
NAME_PATTERN = r"^[a-z][a-z0-9_]{0,63}$"
#: The most entries one session's end may list, sealed or set aside.
MAX_ENTRIES = 512
#: The most files of code one record may name as loaded: the record format's own bound.
MAX_LOADED_FILES = 256
#: The name of the entry that closes a list cut at :data:`MAX_ENTRIES`, saying how many more.
OVERFLOW_NAME = "(more)"

Sha256 = Annotated[str, StringConstraints(pattern=r"^[0-9a-f]{64}$")]
BlobId = Annotated[str, StringConstraints(pattern=r"^(?:[0-9a-f]{40}|[0-9a-f]{64})$")]


class _Frozen(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid", strict=True)


class CodeBlob(_Frozen):
    """A file of code a record names as loaded, by its path in the worktree and its blob id."""

    path: Annotated[str, StringConstraints(min_length=1, max_length=512)]
    blob: BlobId


class CodeDigest(_Frozen):
    """A file of the interpreter's own installation a record names as loaded, by its digest."""

    path: Annotated[str, StringConstraints(min_length=1, max_length=512)]
    sha256: Sha256


class SealedRecord(_Frozen):
    """One record the session left, as the collector sealed it."""

    record_id: Annotated[str, StringConstraints(pattern=NAME_PATTERN)]
    sha256: Sha256
    length: Annotated[int, Field(ge=0)]
    #: The producing script's path relative to the worktree, its digest, its git blob id.
    script: Annotated[str, StringConstraints(min_length=1, max_length=512)]
    script_sha256: Sha256
    script_blob: BlobId
    #: Every other file of code the producing process loaded from the worktree, the writer
    #: included, each with the blob id its bytes had when the record was collected.
    loaded: Annotated[tuple[CodeBlob, ...], Field(max_length=MAX_LOADED_FILES)] = ()
    #: Files of the interpreter's own installation the process loaded from outside the
    #: worktree (a distribution's ``sitecustomize``, for one), admitted because they lie
    #: outside every place the session can write and its user cannot write them; recorded,
    #: never bound to the commit.
    environment: Annotated[tuple[CodeDigest, ...], Field(max_length=MAX_LOADED_FILES)] = ()


class SetAside(_Frozen):
    """A file the collector did not seal, by a printable form of its name, and why."""

    name: Annotated[str, StringConstraints(min_length=1, max_length=200)]
    reason: Annotated[str, StringConstraints(min_length=1, max_length=500)]
    #: For a record discarded because its module code changed or went after it was written:
    #: the digest and length of the bytes collected. Not written for any other entry, so every
    #: other entry is recorded exactly as before.
    sha256: Sha256 | None = Field(default=None, exclude_if=lambda v: v is None)
    length: Annotated[int, Field(ge=0)] | None = Field(default=None, exclude_if=lambda v: v is None)

    @model_validator(mode="after")
    def _a_seal_is_whole(self) -> Self:
        if (self.sha256 is None) != (self.length is None):
            msg = "a seal is a digest and a length together"
            raise ValueError(msg)
        return self


RecordId = Annotated[str, StringConstraints(pattern=NAME_PATTERN)]


class Bytecode(_Frozen):
    """A compiled file found when the session ended, in its worktree or in its own places.

    In the worktree it is then removed; beneath a cache prefix in a directory of the session's
    own (an absolute path), it is left where it lies. By a printable form of its path, with the
    digest and length of its bytes (``None`` where they could not be read: a link, a file too
    large to read whole, one gone). An interpreter runs such a file in place of its source, so it
    is evidence of what may have run, not litter; the bytes are not kept.
    """

    path: Annotated[str, StringConstraints(min_length=1, max_length=1024)]
    sha256: Sha256 | None = None
    length: Annotated[int, Field(ge=0)] | None = None
    #: The session's sealed records this file lay beside: where the interpreter reads compiled
    #: code in place of the source of a file the record names, or of the series writer. Each is
    #: then not vouched for (:data:`NOT_VOUCHED`). Left out of a dump where there is none.
    records: Annotated[tuple[RecordId, ...], Field(max_length=MAX_ENTRIES)] = Field(
        default=(), exclude_if=lambda v: not v
    )


#: How a record with bytecode beside a file it names is marked, wherever it is shown.
NOT_VOUCHED = "not vouched for"


class ScratchFile(_Frozen):
    """One entry the scratch folder held when it was emptied, recorded before it was removed.

    By a printable form of its path in the worktree, what it was (a regular file, a link or
    another kind; a directory is not an entry), and for a regular file its length and the
    digest of its bytes (``None`` where they were not read: past the byte bound, or unreadable).
    """

    path: Annotated[str, StringConstraints(min_length=1, max_length=1024)]
    kind: Literal["file", "link", "other"]
    length: Annotated[int, Field(ge=0)] | None = None
    sha256: Sha256 | None = None


class SessionSeries(_Frozen):
    """Everything one session left in its outbox: sealed, refused or discarded.

    And the bytecode found at its end (``bytecode``: the first :data:`MAX_ENTRIES`, every file
    that marks a record among them; ``bytecode_found``, how many in all), why every one of its
    records is not vouched for where that is so (``not_vouched``), and what its scratch folder
    held when it was emptied (``scratch``, ``scratch_found``, ``scratch_cut``): each left out of
    a dump where there was none, so every end line before them is recorded exactly as it was.
    """

    records: Annotated[tuple[SealedRecord, ...], Field(max_length=MAX_ENTRIES)] = ()
    refused: Annotated[tuple[SetAside, ...], Field(max_length=MAX_ENTRIES)] = ()
    discarded: Annotated[tuple[SetAside, ...], Field(max_length=MAX_ENTRIES)] = ()
    bytecode: Annotated[tuple[Bytecode, ...], Field(max_length=MAX_ENTRIES)] = Field(
        default=(), exclude_if=lambda v: not v
    )
    bytecode_found: Annotated[int, Field(ge=0)] = Field(default=0, exclude_if=lambda v: v == 0)
    #: Whether the clearing at the session's end left something it could not record or remove;
    #: the change check then refuses the attempt (left out of a dump when ``False``).
    left_out_incomplete: bool = Field(default=False, exclude_if=lambda v: not v)
    #: Why none of the session's sealed records is vouched for, where the look for bytecode
    #: beside them could not be made whole (left out of a dump when ``None``).
    not_vouched: Annotated[str, StringConstraints(min_length=1, max_length=500)] | None = Field(
        default=None, exclude_if=lambda v: v is None
    )
    scratch: Annotated[tuple[ScratchFile, ...], Field(max_length=MAX_ENTRIES)] = Field(
        default=(), exclude_if=lambda v: not v
    )
    scratch_found: Annotated[int, Field(ge=0)] = Field(default=0, exclude_if=lambda v: v == 0)
    #: Where the scratch folder's record stopped at a bound, the bound in words.
    scratch_cut: Annotated[str, StringConstraints(min_length=1, max_length=500)] | None = Field(
        default=None, exclude_if=lambda v: v is None
    )


class SeriesCheck(_Frozen):
    """One graph quantity held to the record it names: what it declares, what the record gives.

    Recorded for every quantity that names a record, passes included, on the change check's
    line of the run's event log. ``outcome`` is ``agrees`` within the frozen tolerance,
    ``differs`` beyond it, or ``unreadable`` when the value cannot be read off the record (no
    such record in the attempt, a trace missing, a unit of another kind); the last two refuse
    the attempt.
    """

    node_id: Annotated[str, StringConstraints(min_length=1, max_length=128)]
    quantity: Annotated[str, StringConstraints(min_length=1, max_length=128)]
    record_id: Annotated[str, StringConstraints(pattern=NAME_PATTERN)]
    extract: Annotated[str, StringConstraints(min_length=1, max_length=64)]
    trace: Annotated[str, StringConstraints(pattern=NAME_PATTERN)] | None = None
    #: The session that sealed the record read, when one did.
    session_id: Annotated[str, StringConstraints(pattern=r"^[A-Za-z0-9_-]{1,128}$")] | None = None
    declared_value: float | int
    declared_unit: Annotated[str, StringConstraints(min_length=1, max_length=64)]
    read_value: float | None = None
    read_unit: Annotated[str, StringConstraints(min_length=1, max_length=64)] | None = None
    outcome: Literal["agrees", "differs", "unreadable"]
    reason: Annotated[str, StringConstraints(min_length=1, max_length=500)] | None = None


class AttemptRecord(_Frozen):
    """One record an attempt sealed, and the session whose end sealed it."""

    session_id: Annotated[str, StringConstraints(pattern=r"^[A-Za-z0-9_-]{1,128}$")]
    record: SealedRecord


class AttemptDiscard(_Frozen):
    """A record one of the attempt's sessions discarded, or the notice that its list was cut.

    ``entry`` is as the session's end line lists it: a record with its seal, or the entry
    named :data:`OVERFLOW_NAME` that says how many more its list could not hold.
    """

    session_id: Annotated[str, StringConstraints(pattern=r"^[A-Za-z0-9_-]{1,128}$")]
    entry: SetAside


class AttemptBytecode(_Frozen):
    """Bytecode found when one of the attempt's sessions ended, as its end line lists it."""

    session_id: Annotated[str, StringConstraints(pattern=r"^[A-Za-z0-9_-]{1,128}$")]
    found: Annotated[int, Field(ge=0)]
    files: tuple[Bytecode, ...]
    #: Why none of that session's records is vouched for, where its end line says so.
    not_vouched: str | None = Field(default=None, exclude_if=lambda v: v is None)


class AttemptScratch(_Frozen):
    """What one of the attempt's sessions left in its scratch folder, as its end line lists it."""

    session_id: Annotated[str, StringConstraints(pattern=r"^[A-Za-z0-9_-]{1,128}$")]
    found: Annotated[int, Field(ge=0)]
    files: tuple[ScratchFile, ...]
    cut: str | None = Field(default=None, exclude_if=lambda v: v is None)


class AttemptSeries(_Frozen):
    """What a review is told about an attempt's simulation records.

    The records the attempt's sessions sealed (a later session's superseding an earlier one's
    of the same id), the run directory they lie under, the result of holding each graph
    quantity that names one to it, and the records its sessions discarded, which are no
    evidence. It travels on the attempt as the gate and the reviewer receive it, and so
    reaches the review packet of both review arms by one route.
    """

    run_dir: Annotated[str, StringConstraints(min_length=1)]
    subtask_id: Annotated[str, StringConstraints(min_length=1)]
    attempt: Annotated[int, Field(ge=1)]
    records: tuple[AttemptRecord, ...] = ()
    checks: tuple[SeriesCheck, ...] = ()
    #: Left out of a dump when empty, so an attempt that discarded no record is recorded
    #: exactly as before.
    discarded: tuple[AttemptDiscard, ...] = Field(default=(), exclude_if=lambda v: not v)
    #: Each session whose end found bytecode, with what it found; left out when none.
    bytecode: tuple[AttemptBytecode, ...] = Field(default=(), exclude_if=lambda v: not v)
    #: Each session that left files in its scratch folder, with what they were; left out when none.
    scratch: tuple[AttemptScratch, ...] = Field(default=(), exclude_if=lambda v: not v)

    def not_vouched(self, session_id: str, record_id: str) -> tuple[str | None, list[Bytecode]]:
        """Why the record ``record_id`` of ``session_id`` is not vouched for, and the files why.

        Read from what that session's end found: the reason that covers all its records, if
        any, and every bytecode file it lists beside this record. ``(None, [])`` for a record
        that is not marked.
        """
        for held in self.bytecode:
            if held.session_id == session_id:
                beside = [b for b in held.files if record_id in b.records]
                return held.not_vouched, beside
        return None, []
