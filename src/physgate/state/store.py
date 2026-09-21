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
from typing import Any

from physgate.state.exceptions import (
    DesignStateError,
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

    def __init__(self, root: Path) -> None:
        """Open the store rooted at ``root``, recovering it first."""
        self.root = Path(root)
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
                    break
                self._offsets[entry["rev"]] = offset
                self._node_revs.setdefault(entry["node_id"], []).append(entry["rev"])
                self._head[entry["node_id"]] = (entry["rev"], entry["version"])
                self._next_rev = entry["rev"] + 1
                good_end = handle.tell()

        size = self.journal_path.stat().st_size
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
            NodeNotFoundError: the store has never held this id.
        """
        self._assert_current()
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
            NodeNotFoundError: the store has never held ``node_id``.
        """
        self._assert_current()
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
        """
        self._assert_current()
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
        return self.nodes_dir / f"{node_id}.json"

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
