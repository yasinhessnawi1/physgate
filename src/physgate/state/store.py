"""The design-state graph store: JSON files per node over an append-only journal.

Promoted from the store that won the pre-registered comparison in
``experiments/R-OP-01/``. The design is unchanged and the reasons for it are
worth restating, because both are load-bearing:

**The journal is the authority.** A mutation is durable once its journal line is
synced; the per-node JSON file is a materialisation that recovery rebuilds from
the journal. That ordering is what makes a kill between the two harmless, and it
is why recovery reads the journal and repairs the files rather than the reverse.

**Reads come off the durable record.** The node payloads, the change list and the
traversal all answer from files. What this class keeps in memory is location
information — byte offsets into the journal, the revisions each node has, the
current head — every bit of it rebuilt at open from the journal alone. The
architecture runs agents as separate processes in separate worktrees and the
orchestrator diffs what they committed, so a handle that answered from a cache of
its own writes would be a false green in exactly the case that matters.

Four things here differ from the code that was measured, each decided and each
inert against the frozen workload:

- a handle refuses to answer when the journal has moved underneath it, instead of
  answering from indexes that predate the move;
- a malformed node id raises rather than becoming a rejection reason;
- a rollback to a revision of another node raises a domain exception rather than
  a bare one;
- payloads are validated against the node schema on the way in and on the way
  out.
"""

from __future__ import annotations

import hashlib
import json
import os
from collections import deque
from pathlib import Path
from typing import Annotated, Any, Literal

from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    ValidationError,
    field_validator,
    model_validator,
)

from physgate.state.exceptions import (
    CorruptRecordError,
    DesignStateError,
    MalformedNodeIdError,
    StoreStaleError,
)
from physgate.state.protocol import (
    REJECT_CROSS_ROLE,
    REJECT_INTERFACE_IMMUTABLE,
    REJECT_MISSING_UNIT,
    NodeChange,
    NodeNotFoundError,
    Revision,
    WriteResult,
    canonical_json,
)
from physgate.state.schema import quantities_are_valid, validate_node, validate_node_id

# A node payload is a plain JSON object on the way in and on the way out. The
# frozen interface types it that way and the schema is what gives it structure;
# typing it as a model here would change the surface the comparison measured.
Payload = dict[str, Any]

#: What to do about a complete journal line that is not a valid record.
OnCorrupt = Literal["raise", "truncate"]

JOURNAL_NAME = "journal.jsonl"
NODES_DIRNAME = "nodes"


def _op_agrees_with_what_came_before(
    line: JournalLine,
    version_of: dict[str, int],
    payloads_of: dict[str, set[str]],
) -> str | None:
    """Why ``line`` could not have been written, given the lines before it.

    The writing path creates a node it has not seen, at version one, and writes
    or rolls back a node it has seen, at one version more. A record that does
    otherwise is a record this package did not write.

    This is the per-node half of the rule the consecutive-revision check is the
    global half of, and it closes the same shape of defect one level down: an
    injected record rewinding a counter that the store then carries on from, so
    that the store manufactures the damage itself on its next legitimate write.
    A version chain of ``[1, 2, 3, 4, 5, 1, 2]`` is what that looked like.

    A rollback carries one more constraint than a write, because the writing path
    imposes one: :meth:`Store.rollback` only ever appends a payload it has just
    read out of an earlier revision of that same node. A rollback record carrying
    a payload that was never any revision of that node is therefore a record this
    package could not have written, however well-formed it looks.

    Args:
        line: the record being replayed.
        version_of: the version each node was last seen at.
        payloads_of: the canonical payloads each node has held, for the rollback
            rule. Held as digests, so this grows with revisions rather than with
            their size, and it is discarded when recovery returns.

    Returns:
        ``None`` when the record is coherent, otherwise the reason it is not.
    """
    previous = version_of.get(line.node_id)
    if line.op == "create":
        if previous is not None:
            return f"a create for {line.node_id!r}, which the journal has already created"
        if line.version != 1:
            return f"a create at version {line.version}; a created node is at version 1"
        return None
    if previous is None:
        return f"a {line.op} for {line.node_id!r}, which the journal has never created"
    if line.version != previous + 1:
        return (
            f"version {line.version} does not follow {previous} for {line.node_id!r}; "
            "this package only ever mints consecutive versions"
        )
    if line.op == "rollback" and payload_digest(line.payload) not in payloads_of.get(
        line.node_id, set()
    ):
        return (
            f"a rollback of {line.node_id!r} to a payload that was never any of its "
            "revisions; a rollback only ever replays a payload this node has held"
        )
    return None


def _first_free_name(path: Path) -> Path:
    """The first unused ``<name>.json.orphan.<n>`` beside ``path``.

    Quarantining used a single fixed name, so planting a file, being let past it,
    and planting a file of the same name again left only the second one: the
    first was overwritten by the move that was supposed to preserve it. The
    number makes each one keep its own bytes.

    Refusing on a collision was the other option and is the wrong one — it would
    leave a caller who asked to be let past damage unable to open the store at
    all, which is the opposite of what asking for that means.
    """
    n = 1
    while True:
        candidate = path.with_suffix(f".json.orphan.{n}")
        if not candidate.exists():
            return candidate
        n += 1


def payload_digest(payload: Payload) -> str:
    """A short, stable identity for a payload, over its canonical serialisation."""
    return hashlib.sha256(canonical_json(payload).encode()).hexdigest()


def node_file_body(rev: int, version: int, payload: Payload) -> str:
    """Exactly what a node file holds for a revision, canonically serialised.

    One definition, used to write the file and to check it, so that recovery
    compares against what writing actually produces rather than against a
    second opinion about it.

    Public because a second reader needs the same answer without opening a
    store: the hook layer re-derives every node file from the journal after each
    agent tool call, to catch a file changed behind the store's back, and
    constructing a store to ask would run recovery, which rewrites files. A pure
    function of the journal record is the one way to ask without writing.
    """
    return json.dumps(
        {"rev": rev, "version": version, "payload": payload},
        sort_keys=True,
        separators=(",", ":"),
    )


def journal_records_after(root: Path, revision: Revision) -> list[JournalLine]:
    """Every journal record after ``revision``, read without opening a store.

    Opening a store runs recovery, which rewrites node files and moves unknown
    files aside, so it is a write. The orchestrator needs to read the journal's
    newest lines exactly when it must not write: when its handle refuses because
    the journal moved underneath it, and when it resumes. It compares those lines
    against the writes it recorded intending to make, and any line it did not
    intend is a foreign write. Reopening instead would replay that line as
    genuine.

    Read-only, from the journal alone: the file is opened for reading and nothing
    else, no node file is read or trusted, and every complete line is held to the
    same rules recovery applies (a valid record, consecutive revisions, versions
    that follow). A line that breaks them is reported, not skipped, since a
    foreign write must not pass by also being malformed. An unterminated final
    line is a write in progress and is not returned.

    Raises:
        CorruptRecordError: a complete line is not one this package could have
            written, given the lines before it.
    """
    try:
        fd = os.open(Path(root) / JOURNAL_NAME, os.O_RDONLY)
    except FileNotFoundError:
        return []
    with os.fdopen(fd, "rb") as handle:
        raw_lines = handle.read().split(b"\n")[:-1]
    found: list[JournalLine] = []
    version_of: dict[str, int] = {}
    payloads_of: dict[str, set[str]] = {}
    offset = 0
    for index, raw in enumerate(raw_lines, start=1):
        reason: str | None = None
        try:
            line = JournalLine.model_validate_json(raw)
        except ValidationError as exc:
            reason = _first_validation_problem(exc)
        else:
            if line.rev != index:
                reason = f"revision {line.rev} does not follow {index - 1}"
            else:
                reason = _op_agrees_with_what_came_before(line, version_of, payloads_of)
        if reason is not None:
            msg = "the journal holds a record this package could not have written"
            raise CorruptRecordError(
                msg, journal=str(Path(root) / JOURNAL_NAME), offset=str(offset), reason=reason
            )
        version_of[line.node_id] = line.version
        payloads_of.setdefault(line.node_id, set()).add(payload_digest(line.payload))
        if line.rev > revision:
            found.append(line)
        offset += len(raw) + 1
    return found


def _first_validation_problem(exc: ValidationError) -> str:
    """The first thing wrong with a record, as a sentence rather than a report.

    Pydantic's string form ends with a documentation link, so taking its last
    line names the library instead of the defect. This names the field and what
    was wrong with it, which is what an operator reading a refusal needs.
    """
    problems = exc.errors()
    if not problems:
        return "the line is not a valid record"
    first = problems[0]
    where = ".".join(str(part) for part in first["loc"]) or "the record"
    return f"{where}: {first['msg']}"


class JournalLine(BaseModel):
    """One accepted mutation, as it is written to and read back from the journal.

    **The journal is a boundary, because every open crosses it.** The store
    replays this file to rebuild itself, so a line in it is untrusted input in
    exactly the way a node payload is — and for a while it was not treated that
    way. Only the identifier was checked and the rest was read raw, which let a
    line carrying a revision of zero rewind the head on the next open: the change
    list then reported nothing, and a foreign write sitting on disk became
    invisible to the check whose whole job is to name it.

    Strict, so a boolean is not an integer and a string is not a number. Frozen
    and closed, so an unknown field is a refusal rather than something ignored.

    **One rule generates the rest of them, here and in recovery:** every replayed
    line must be one the writing code could have produced, given everything
    replayed before it. Within a single record that means the payload is a whole
    node and its identifier is the one the record names — the writing path takes
    the record's identifier *from* the payload, so the two can never disagree
    there, and a record where they do disagree is a record this package did not
    write. Across records it means a create is for a node not yet seen at version
    one, and a write or a rollback is for a node already seen at one version
    more; recovery checks those, because a single line cannot.
    """

    model_config = ConfigDict(frozen=True, extra="forbid", strict=True)

    rev: Annotated[int, Field(gt=0)]
    op: Literal["create", "write", "rollback"]
    node_id: str
    version: Annotated[int, Field(gt=0)]
    payload: dict[str, Any]

    @field_validator("rev", "version", mode="before")
    @classmethod
    def _not_a_boolean(cls, value: object) -> object:
        """Refuse a boolean where a count belongs.

        Strict mode already refuses it. This says so in the model rather than
        leaving it to a configuration flag, so that dropping the flag is caught
        by this model's own tests rather than only by whatever else happened to
        depend on strictness.
        """
        if isinstance(value, bool):
            msg = "a boolean is not a revision or a version"
            raise ValueError(msg)
        return value

    @model_validator(mode="after")
    def _payload_is_the_node_this_record_names(self) -> JournalLine:
        """The payload is a whole node, and it is the node the record names.

        Typing the payload as an object and stopping there left two holes. A
        payload that is not a node at all reaches every reader of the graph, and
        the divergence check died on one with a bare key error — the failure this
        model exists to convert into a refusal with an offset. And a payload
        whose identifier differs from the record's leaves the file's name and its
        contents disagreeing, with the revision history split across two
        identifiers and nothing to notice.
        """
        try:
            payload = validate_node(self.payload)
        except DesignStateError as exc:
            raise ValueError(f"payload: {exc}") from exc
        except ValidationError as exc:
            # The node model's own complaint, which names the offending field.
            # Prefixed, so a reader of the refusal can tell a malformed payload
            # from a malformed record without knowing which fields belong to
            # which.
            raise ValueError(f"payload: {_first_validation_problem(exc)}") from exc
        if payload.id != self.node_id:
            msg = (
                f"the record names {self.node_id!r} and its payload is "
                f"{payload.id!r}; a record names the node it carries"
            )
            raise ValueError(msg)
        return self

    @field_validator("node_id")
    @classmethod
    def _legal_identifier(cls, value: str) -> str:
        """The identifier rule, applied where the record is read rather than later.

        The domain error is re-raised as the kind of error a validator is allowed
        to raise, so that this failure arrives as a validation failure like every
        other one. That matters for more than tidiness: a failure that escapes
        validation escapes the corruption policy with it, and the caller who
        asked to be allowed through cannot be.
        """
        try:
            return validate_node_id(value)
        except MalformedNodeIdError as exc:
            raise ValueError(str(exc)) from exc


class RevisionNotFoundError(DesignStateError):
    """A revision was named that this store has never minted for that node."""


class Store:
    """One JSON file per node, an append-only journal beside them.

    A handle is a view as of open: it rebuilds its indexes when it opens and not
    afterwards, and refuses to answer if the journal has moved since. One process
    holds the store at a time. See ``README.md`` beside this file.
    """

    def __init__(self, root: Path, *, on_corrupt: OnCorrupt = "raise") -> None:
        """Open the store rooted at ``root``, recovering it first.

        Args:
            root: the directory holding the journal and the node files.
            on_corrupt: what to do about a complete journal line that is not a
                valid record. ``"raise"`` refuses to open and names the offset.
                ``"truncate"`` drops that line and everything after it, and
                reports the byte count. The default is to refuse, because
                dropping silently would discard valid records too.
        """
        self.root = Path(root)
        self._on_corrupt = on_corrupt
        self.nodes_dir = self.root / NODES_DIRNAME
        self.journal_path = self.root / JOURNAL_NAME
        self.nodes_dir.mkdir(parents=True, exist_ok=True)
        self.journal_path.touch(exist_ok=True)

        # Location indexes. Every one is rebuilt at open from the journal alone;
        # none of them holds a payload.
        self._offsets: dict[int, int] = {}
        self._node_revs: dict[str, list[int]] = {}
        self._head: dict[str, tuple[int, int]] = {}
        self._next_rev = 1
        self._torn_tail_bytes = 0
        self._corrupt_tail_bytes = 0
        self._repaired_node_files = 0
        self._quarantined: tuple[str, ...] = ()

        # Bound before recovery, not after. Recovery can refuse to open, and a
        # caller that closes in a finally block should see the error that
        # actually happened rather than an attribute that was never assigned.
        self._journal = self.journal_path.open("ab")
        try:
            self.recover()
        except Exception:
            # Bound first so it is always closeable, so it is always closed: an
            # open that refuses must not leave a descriptor behind.
            self._journal.close()
            raise
        # Recovery may have truncated the file through another handle, which
        # leaves this one's idea of the end stale; the append offsets are read
        # from it, so it is re-seeked rather than trusted.
        self._journal.seek(0, os.SEEK_END)
        self._durable_size = self.journal_path.stat().st_size

    # ----- open and recovery ------------------------------------------------

    def recover(self) -> None:
        """Rebuild the indexes from the journal and repair the node files.

        A torn final line — the process died between the write and the sync — is
        truncated away rather than parsed. Any node file that does not match the
        journal's head for that node is rewritten from the journal payload,
        because the journal is the authority and the file is derived from it.
        """
        self._offsets = {}
        self._node_revs = {}
        self._head = {}
        self._next_rev = 1

        good_end = 0
        corrupt: tuple[int, str] | None = None
        expected_rev = 1
        version_of: dict[str, int] = {}
        payloads_of: dict[str, set[str]] = {}
        with self.journal_path.open("rb") as handle:
            while True:
                offset = handle.tell()
                raw = handle.readline()
                if not raw:
                    break
                if not raw.endswith(b"\n"):
                    break  # torn tail, drop it
                try:
                    line = JournalLine.model_validate_json(raw)
                except ValidationError as exc:
                    corrupt = (offset, _first_validation_problem(exc))
                    break
                if line.rev != expected_rev:
                    corrupt = (
                        offset,
                        f"revision {line.rev} does not follow {expected_rev - 1}; "
                        "this package only ever mints consecutive revisions",
                    )
                    break
                coherent = _op_agrees_with_what_came_before(line, version_of, payloads_of)
                if coherent is not None:
                    corrupt = (offset, coherent)
                    break
                version_of[line.node_id] = line.version
                payloads_of.setdefault(line.node_id, set()).add(payload_digest(line.payload))
                self._offsets[line.rev] = offset
                self._node_revs.setdefault(line.node_id, []).append(line.rev)
                self._head[line.node_id] = (line.rev, line.version)
                self._next_rev = line.rev + 1
                expected_rev = line.rev + 1
                good_end = handle.tell()

        size = self.journal_path.stat().st_size
        if corrupt is not None and self._on_corrupt == "raise":
            offset, reason = corrupt
            msg = "the journal holds a record this package could not have written"
            raise CorruptRecordError(
                msg, journal=str(self.journal_path), offset=str(offset), reason=reason
            )
        # A torn tail and a dropped corrupt line are both bytes removed from the
        # end, and they mean different things: one is a process that died
        # mid-write, the other is a record written by something that is not this
        # package. A report that cannot tell them apart cannot say which
        # happened, so they are counted separately.
        dropped = size - good_end
        if corrupt is not None:
            self._corrupt_tail_bytes = dropped
            self._torn_tail_bytes = 0
        else:
            self._torn_tail_bytes = dropped
            self._corrupt_tail_bytes = 0
        if dropped:
            with self.journal_path.open("r+b") as handle:
                handle.truncate(good_end)

        # The node files are derived from the journal, so recovery compares them
        # against what the journal says they should contain -- all of it, not the
        # revision number written inside them. That number is under the control
        # of whatever edited the file: an in-place change to a quantity that
        # leaves `rev` alone used to survive every open, and the graph then served
        # a value the journal had never recorded, with nothing in any change list
        # and nothing for the divergence check to see.
        self._repaired_node_files = 0
        for node_id, (rev, version) in self._head.items():
            payload = self._entry_at(rev)["payload"]
            # Compared as **bytes**. Reading the file as text meant a node file
            # that is not valid UTF-8 raised a decode error out of recovery
            # itself, which escaped the corruption policy entirely: the caller
            # who had asked to be let past damage was not let past, and the
            # caller who had asked to be told got a decode error instead of a
            # refusal. There is no decode in a byte comparison, so a named file
            # holding any wrong bytes at all is repaired from the journal like
            # every other tamper.
            expected = node_file_body(rev, version, payload).encode()
            try:
                actual: bytes | None = self._node_path(node_id).read_bytes()
            except OSError:
                actual = None
            if actual != expected:
                self._materialise(node_id, rev, version, payload)
                self._repaired_node_files += 1

        self._quarantine_orphan_node_files()

    @property
    def torn_tail_bytes(self) -> int:
        """Bytes dropped because the final line had no terminator. Zero if none.

        A process that died mid-write. Distinct from
        :attr:`corrupt_tail_bytes`, which is a complete record this package
        could not have written.

        Zero also when a corrupt record was found, because recovery stops there
        and does not look past it — so this being zero does not mean the tail
        was intact, only that nothing reached it.
        """
        return self._torn_tail_bytes

    @property
    def repaired_node_files(self) -> int:
        """How many node files the last :meth:`recover` rewrote from the journal.

        Non-zero after a kill between the journal sync and the file replace,
        after a file is lost or damaged, and after one is edited in place.
        """
        return self._repaired_node_files

    @property
    def quarantined_node_files(self) -> tuple[str, ...]:
        """Node files the journal never named, moved aside by the last recovery.

        Non-empty only when the handle was opened asking to be let past damage,
        since refusing is the default.
        """
        return self._quarantined

    def _quarantine_orphan_node_files(self) -> None:
        """Deal with node files for ids the journal has never named.

        The journal is the authority and the files are derived from it, so a file
        the journal never mentions was not put there by this package. It used to
        be neither examined nor mentioned: ``read_node`` served it, ``history``
        was empty for it, and it appeared in no change list — a node in the graph
        that the divergence check could not see.

        It goes through the same policy as a corrupt journal record. Refusing is
        the default. When the caller asks to be let past, the file is **moved
        aside rather than deleted**, because dropping a journal's trailing bytes
        loses bytes this package did not write, while deleting a node file would
        destroy a whole file whose provenance is exactly what is unclear. The
        suffix takes it out of the graph and out of any later scan.

        Raises:
            CorruptRecordError: a node file names an id the journal has not, and
                the handle was opened with the default policy.
        """
        self._quarantined = ()
        orphans = sorted(
            path for path in self.nodes_dir.glob("*.json") if path.stem not in self._head
        )
        if not orphans:
            return
        if self._on_corrupt == "raise":
            msg = "the graph holds a node file the journal has never named"
            raise CorruptRecordError(
                msg,
                nodes_dir=str(self.nodes_dir),
                node_id=orphans[0].stem,
                count=str(len(orphans)),
            )
        moved = []
        for path in orphans:
            os.replace(path, _first_free_name(path))
            moved.append(path.stem)
        self._quarantined = tuple(moved)

    @property
    def corrupt_tail_bytes(self) -> int:
        """Bytes dropped from a corrupt record onwards. Zero if none.

        A **corrupt record hides whatever follows it**, including a torn final
        line: recovery stops at the corrupt record and counts everything from
        there to the end as corruption, rather than scanning past it to find out
        what else is there. That is a choice and not an accident. Scanning past a
        record this package could not have written means parsing bytes whose
        provenance is exactly what is in doubt, to refine a number in a report;
        the count is diagnostic and the refusal is the outcome. So when both
        kinds of damage are present, the count says corruption and says nothing
        about the tail.


        Non-zero only when the handle was opened asking for that, since the
        default is to refuse.
        """
        return self._corrupt_tail_bytes

    # ----- the staleness guard ----------------------------------------------

    def _assert_current(self) -> None:
        """Refuse to answer if the journal has grown or shrunk since the last sync.

        The journal is strictly append-only, so its size is monotonic and moves on
        exactly the event this cares about. Modification time would not do: it is
        coarse on some filesystems and can move backwards.

        Raises:
            StoreStaleError: another writer has touched the journal.
        """
        size = os.stat(self.journal_path).st_size
        if size != self._durable_size:
            msg = "the journal moved underneath this handle"
            raise StoreStaleError(
                msg,
                journal=str(self.journal_path),
                size_at_last_sync=str(self._durable_size),
                size_now=str(size),
            )

    # ----- writes ------------------------------------------------------------

    def write_node(self, node: Payload, actor_role: str) -> WriteResult:
        """Create or update ``node`` on behalf of ``actor_role``.

        The guards run in the order the comparison measured them — role
        ownership, then interface immutability, then the quantities — and that
        order is semantics, not an accident: a write carrying two faults is
        rejected for the first of them, and the rejection reasons are what the
        frozen correctness score is counted in.

        Raises:
            StoreStaleError: the journal moved underneath this handle.
            MalformedNodeIdError: the node id is not a legal identifier.
            MissingUnitError: the payload is malformed in a way that is not one
                of the three rejections.
        """
        self._assert_current()
        node_id = validate_node_id(node.get("id"))
        known = self._head.get(node_id)

        if known is None:
            if actor_role != node.get("owner_role"):
                return WriteResult(False, None, REJECT_CROSS_ROLE)
        else:
            current = self._read_node(node_id)
            if actor_role != current["owner_role"]:
                return WriteResult(False, None, REJECT_CROSS_ROLE)
            if current["kind"] == "interface":
                return WriteResult(False, None, REJECT_INTERFACE_IMMUTABLE)

        if not quantities_are_valid(node):
            return WriteResult(False, None, REJECT_MISSING_UNIT)

        validate_node(node)

        version = 1 if known is None else known[1] + 1
        rev = self._append("create" if known is None else "write", node_id, version, node)
        self._materialise(node_id, rev, version, node)
        return WriteResult(True, rev, None)

    def rollback(self, node_id: str, to: Revision) -> None:
        """Append a new head whose payload equals the payload at ``to``.

        Nothing is deleted and no revision is rewritten: a rollback is a forward
        move whose payload happens to be an older one.

        Raises:
            StoreStaleError: the journal moved underneath this handle.
            RevisionNotFoundError: ``to`` is not a revision of ``node_id``.
        """
        self._assert_current()
        validate_node_id(node_id)
        if to not in self._offsets:
            msg = "no such revision"
            raise RevisionNotFoundError(msg, node_id=node_id, revision=str(to))
        entry = self._entry_at(to)
        if entry["node_id"] != node_id:
            msg = "revision belongs to a different node"
            raise RevisionNotFoundError(
                msg, node_id=node_id, revision=str(to), belongs_to=entry["node_id"]
            )
        # The payload comes out of an earlier revision of this node by
        # construction. Checking it anyway states the rule in the place that
        # makes it true, so that the replay-side check has a counterpart here
        # rather than being the only statement of it.
        payload: Payload = entry["payload"]
        if payload_digest(payload) not in {
            payload_digest(self._entry_at(each)["payload"])
            for each in self._node_revs.get(node_id, [])
        }:  # pragma: no cover - unreachable while `to` is a revision of this node
            msg = "a rollback payload that was never a revision of this node"
            raise RevisionNotFoundError(msg, node_id=node_id, revision=str(to))

        version = self._head[node_id][1] + 1
        rev = self._append("rollback", node_id, version, payload)
        self._materialise(node_id, rev, version, payload)

    # ----- reads --------------------------------------------------------------

    def read_node(self, node_id: str) -> Payload:
        """Return the current payload of ``node_id``, read from its file.

        Raises:
            StoreStaleError: the journal moved underneath this handle.
            MalformedNodeIdError: the id is not a legal identifier.
            NodeNotFoundError: the store has never held this id.
        """
        self._assert_current()
        validate_node_id(node_id)
        return self._read_node(node_id)

    def diff(self, since: Revision) -> list[NodeChange]:
        """Return every accepted mutation with a revision greater than ``since``.

        Read by seeking to a known byte offset in the journal and reading the
        tail, which is what made this design worth promoting.

        Raises:
            StoreStaleError: the journal moved underneath this handle.
            RevisionNotFoundError: ``since`` is not a revision this store minted.
        """
        self._assert_current()
        head = self._next_rev - 1
        if since >= head:
            return []
        if since + 1 not in self._offsets:
            msg = "no such revision to diff from"
            raise RevisionNotFoundError(msg, revision=str(since))
        changes: list[NodeChange] = []
        with self.journal_path.open("rb") as handle:
            handle.seek(self._offsets[since + 1])
            for raw in handle:
                if not raw.endswith(b"\n"):
                    break
                entry = json.loads(raw)
                changes.append(
                    NodeChange(entry["rev"], entry["node_id"], entry["version"], entry["op"])
                )
        return changes

    def traverse_constrains(self, node_id: str) -> list[str]:
        """Return the transitive ``constrains`` closure of ``node_id``, breadth first.

        Raises:
            StoreStaleError: the journal moved underneath this handle.
            MalformedNodeIdError: the id is not a legal identifier.
            NodeNotFoundError: the store has never held ``node_id``.
        """
        self._assert_current()
        validate_node_id(node_id)
        order: list[str] = []
        seen: set[str] = {node_id}
        queue = deque(self._read_node(node_id)["constrains"])
        while queue:
            nid = queue.popleft()
            if nid in seen or nid not in self._head:
                continue
            seen.add(nid)
            order.append(nid)
            queue.extend(self._read_node(nid)["constrains"])
        return order

    def history(self, node_id: str) -> list[Revision]:
        """Return every revision of ``node_id``, oldest first.

        Raises:
            StoreStaleError: the journal moved underneath this handle.
            MalformedNodeIdError: the id is not a legal identifier.
        """
        self._assert_current()
        validate_node_id(node_id)
        return list(self._node_revs.get(node_id, []))

    def head_revision(self) -> Revision:
        """The highest revision this store has minted. Zero on an empty store.

        Raises:
            StoreStaleError: the journal moved underneath this handle.
        """
        self._assert_current()
        return self._next_rev - 1

    def close(self) -> None:
        """Release the journal handle. Idempotent, and never refuses."""
        if not self._journal.closed:
            self._journal.close()

    # ----- internals ----------------------------------------------------------

    def _node_path(self, node_id: str) -> Path:
        """The file holding ``node_id``, and the only place a node path is built.

        Every read, write and repair goes through here, so this is where the
        identifier rule is made unconditional rather than being remembered at
        each call site. The name it produces is then checked as well: the pattern
        is the rule, and the containment check is what catches a future change to
        the pattern that the pattern's own tests would still pass.

        The containment check is a **string test on the file name**, and the
        spelling is measured rather than chosen. Resolving the path and comparing
        it to the resolved directory — the obvious version, and the one written
        first — touches the filesystem once per path component, and a traversal
        calls this once per hop. Collapsing the path as text instead was cheaper
        and still cost nine microseconds a call to re-prove what the identifier
        pattern already guarantees, since that pattern admits no separator and no
        parent reference. What is left is the part the pattern does not cover: a
        name holding a separator, or beginning with a parent reference, cannot
        stay in this directory whatever a future pattern allows. Fifteen
        microseconds a call became one and a half.

        Raises:
            MalformedNodeIdError: the id is illegal, or the name it produces
                would not stay in the graph directory.
        """
        validate_node_id(node_id)
        name = f"{node_id}.json"
        if os.sep in name or (os.altsep and os.altsep in name) or name.startswith(".."):
            msg = "the node path would fall outside the graph directory"
            raise MalformedNodeIdError(msg, node_id=node_id, file_name=name)
        return self.nodes_dir / name

    def _read_node(self, node_id: str) -> Payload:
        """Read a node's payload from its file, without the staleness check."""
        path = self._node_path(node_id)
        if not path.exists():
            raise NodeNotFoundError(node_id)
        payload: Payload = json.loads(path.read_text())["payload"]
        validate_node(payload)
        return payload

    def _append(self, op: str, node_id: str, version: int, payload: Payload) -> int:
        rev = self._next_rev
        line = (
            json.dumps(
                {"rev": rev, "op": op, "node_id": node_id, "version": version, "payload": payload},
                sort_keys=True,
                separators=(",", ":"),
            ).encode()
            + b"\n"
        )
        offset = self._journal.tell()
        self._journal.write(line)
        self._journal.flush()
        os.fsync(self._journal.fileno())
        self._offsets[rev] = offset
        self._node_revs.setdefault(node_id, []).append(rev)
        self._head[node_id] = (rev, version)
        self._next_rev = rev + 1
        self._durable_size = self.journal_path.stat().st_size
        return rev

    def payload_at(self, revision: Revision) -> Payload:
        """The payload as it stood at ``revision``, read from the journal.

        The journal holds every revision's payload, so a question about the past
        is answerable without a second record. This is not on the frozen
        interface and is not meant to be: the interface is the one the store
        comparison measured, and this is a read the divergence check needs.

        Raises:
            StoreStaleError: the journal moved underneath this handle.
            RevisionNotFoundError: this store never minted ``revision``.
        """
        self._assert_current()
        if revision not in self._offsets:
            msg = "no such revision"
            raise RevisionNotFoundError(msg, revision=str(revision))
        payload: Payload = self._entry_at(revision)["payload"]
        return payload

    def _entry_at(self, rev: Revision) -> dict[str, Any]:
        with self.journal_path.open("rb") as handle:
            handle.seek(self._offsets[rev])
            entry: dict[str, Any] = json.loads(handle.readline())
            return entry

    def _materialise(self, node_id: str, rev: int, version: int, payload: Payload) -> None:
        """Replace the node file atomically. Derived from the journal, never authoritative."""
        path = self._node_path(node_id)
        tmp = path.with_suffix(".json.tmp")
        body = node_file_body(rev, version, payload)
        with tmp.open("w") as handle:
            handle.write(body)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(tmp, path)
