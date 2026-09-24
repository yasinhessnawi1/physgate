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

import json
import os
from collections import deque
from pathlib import Path
from typing import Annotated, Any, Literal

from pydantic import BaseModel, ConfigDict, Field, ValidationError, field_validator

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

        for node_id, (rev, version) in self._head.items():
            path = self._node_path(node_id)
            if path.exists():
                try:
                    on_disk = json.loads(path.read_text())
                except json.JSONDecodeError:
                    on_disk = None
                if isinstance(on_disk, dict) and on_disk.get("rev") == rev:
                    continue
            entry = self._entry_at(rev)
            self._materialise(node_id, rev, version, entry["payload"])

    @property
    def torn_tail_bytes(self) -> int:
        """Bytes dropped because the final line had no terminator. Zero if none.

        A process that died mid-write. Distinct from
        :attr:`corrupt_tail_bytes`, which is a complete record this package
        could not have written.
        """
        return self._torn_tail_bytes

    @property
    def corrupt_tail_bytes(self) -> int:
        """Bytes dropped from a corrupt record onwards. Zero if none.

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
        version = self._head[node_id][1] + 1
        rev = self._append("rollback", node_id, version, entry["payload"])
        self._materialise(node_id, rev, version, entry["payload"])

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
        body = json.dumps(
            {"rev": rev, "version": version, "payload": payload},
            sort_keys=True,
            separators=(",", ":"),
        )
        with tmp.open("w") as handle:
            handle.write(body)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(tmp, path)
