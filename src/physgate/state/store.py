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
from typing import Any, Literal

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

        self.recover()
        self._durable_size = self.journal_path.stat().st_size
        self._journal = self.journal_path.open("ab")

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
        with self.journal_path.open("rb") as handle:
            while True:
                offset = handle.tell()
                raw = handle.readline()
                if not raw:
                    break
                if not raw.endswith(b"\n"):
                    break  # torn tail, drop it
                try:
                    entry = json.loads(raw)
                except json.JSONDecodeError:
                    corrupt = (offset, "the line is complete but is not valid JSON")
                    break
                try:
                    validate_node_id(entry.get("node_id"))
                except MalformedNodeIdError as exc:
                    corrupt = (offset, f"the line names an illegal node id: {exc}")
                    break
                self._offsets[entry["rev"]] = offset
                self._node_revs.setdefault(entry["node_id"], []).append(entry["rev"])
                self._head[entry["node_id"]] = (entry["rev"], entry["version"])
                self._next_rev = entry["rev"] + 1
                good_end = handle.tell()

        size = self.journal_path.stat().st_size
        if corrupt is not None and self._on_corrupt == "raise":
            offset, reason = corrupt
            msg = "the journal holds a record this package could not have written"
            raise CorruptRecordError(
                msg, journal=str(self.journal_path), offset=str(offset), reason=reason
            )
        self._torn_tail_bytes = size - good_end
        if self._torn_tail_bytes:
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
        """How many bytes the last :meth:`recover` dropped. Zero if none."""
        return self._torn_tail_bytes

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
