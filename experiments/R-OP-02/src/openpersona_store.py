"""Implementation B: Open Persona's typed versioned memory behind the Protocol.

persona-core 1.2.1. Uses the real package: ``SelfFactsStore`` over
``ChromaBackend`` with the package's JSONL audit logger. Nothing is
reimplemented; where persona-core cannot express what ARCH-010 needs, the gap is
bridged here and marked ``# ADAPTER:<tag>`` so C5c can count it.

Three changes against the R-OP-01 version of this file, each one permitted by
``../AMENDMENT.md`` and nothing else:

* ``current_view`` picks the head, instead of filtering ``superseded_by`` by
  hand (A2: use the narrowest read the new version offers).
* ``recover()`` runs ``TypedStore.repair``, the recovery routine 1.2.1 added and
  1.1.0 did not have (A3).
* the embedder is selectable, for the two arms B-st and B-hash (A4).

Nothing here is tuned after seeing numbers.
"""

from __future__ import annotations

import json
from collections import deque
from datetime import UTC, datetime
from pathlib import Path

from persona.audit import JSONLAuditLogger
from persona.schema.chunks import PersonaChunk, WriteSource
from persona.stores.chroma import ChromaBackend
from persona.stores.embedder import HashEmbedder, SentenceTransformerEmbedder
from persona.stores.self_facts import SelfFactsStore
from persona.stores.versioning import current_view
from protocol import (
    REJECT_CROSS_ROLE,
    REJECT_INTERFACE_IMMUTABLE,
    REJECT_MISSING_UNIT,
    NodeChange,
    NodeNotFoundError,
    Revision,
    WriteResult,
    canonical_json,
)

#: One design project maps to one persona.
PERSONA_ID = "wp4"
STORE_KIND = "self_facts"


def _unit_violation(node: dict) -> bool:
    """True if any quantity carries a bare number with no unit string."""
    for entry in (node.get("quantities") or {}).values():
        if not isinstance(entry, dict):
            return True
        unit = entry.get("unit")
        if not isinstance(unit, str) or not unit:
            return True
    return False


class OpenPersonaStore:
    """The WP4 design-state store, backed by persona-core typed memory."""

    def __init__(self, root: Path, *, embedder: str = "st") -> None:
        self.root = Path(root)
        self._embedder = HashEmbedder() if embedder == "hash" else SentenceTransformerEmbedder()
        self._backend = ChromaBackend(
            persist_path=self.root / "chroma", embedder=self._embedder
        )
        self._store = SelfFactsStore(
            backend=self._backend, audit_logger=JSONLAuditLogger(self.root / "audit")
        )
        # ADAPTER:revision
        # persona-core mints no store-wide revision and returns nothing from
        # write(), so a revision is defined here as the ordinal position of a
        # chunk in the (created_at, id) total order. The index below is a pure
        # location index: revision -> that key, plus the node and version it
        # belongs to. It is rebuilt at open from the durable store alone.
        self._rev_key: list[tuple[datetime, str]] = []
        self._rev_node: list[tuple[str, int, str]] = []  # (node_id, version, op)
        self.recover()
        # /ADAPTER

    # ----- open and recovery ------------------------------------------------

    def recover(self) -> None:
        """Run the package's repair routine, then rebuild the revision index.

        ``repair`` is persona-core's own recovery routine, the counterpart to the
        baseline's ledger replay. It arrived in 1.2.1; in 1.1.0 there was nothing
        to call.
        """
        self._store.repair(PERSONA_ID, written_by="orchestrator")
        # ADAPTER:revision
        chunks = self._store.get_all(PERSONA_ID, include_superseded=True)
        ordered = sorted(chunks, key=lambda c: (c.created_at, c.id))
        self._rev_key = [(c.created_at, c.id) for c in ordered]
        self._rev_node = [
            (
                c.provenance.logical_id if c.provenance else c.id,
                c.provenance.version if c.provenance else 1,
                "create" if (c.provenance and c.provenance.version == 1) else "write",
            )
            for c in ordered
        ]
        # /ADAPTER

    # ----- writes -------------------------------------------------------------

    def write_node(self, node: dict, actor_role: str) -> WriteResult:
        node_id = node["id"]
        head = self._head_chunk(node_id)

        if head is None:
            if actor_role != node.get("owner_role"):
                return WriteResult(False, None, REJECT_CROSS_ROLE)
        else:
            current = json.loads(head.text)
            if actor_role != current["owner_role"]:
                return WriteResult(False, None, REJECT_CROSS_ROLE)
            if current["kind"] == "interface":
                return WriteResult(False, None, REJECT_INTERFACE_IMMUTABLE)

        if _unit_violation(node):
            return WriteResult(False, None, REJECT_MISSING_UNIT)

        # ADAPTER:marshal
        # The node has no structured slot in the store. ``metadata`` is
        # ``dict[str, str]`` and the transport takes JSON primitives only, so
        # nested ``quantities`` and the ``constrains`` list cannot live there.
        # The whole node goes into ``text`` as canonical JSON and is parsed back
        # on every read. The id doubles as the logical id: the store derives the
        # chain key from the chunk id on first write.
        chunk = PersonaChunk(
            id=node_id,
            text=canonical_json(node),
            created_at=datetime.now(UTC),
        )
        # /ADAPTER
        self._store.write(
            PERSONA_ID,
            [chunk],
            source=WriteSource.SYSTEM,
            written_by=actor_role,
            reason="design-state write",
            force=True,  # SelfFactsStore is FORCE_ONLY for system writes
        )
        # ADAPTER:revision
        # write() returns None, so the revision it just minted has to be read
        # back out of the store before the caller can be told what happened.
        new_head = self._head_chunk(node_id)
        assert new_head is not None
        version = new_head.provenance.version if new_head.provenance else 1
        return WriteResult(
            True, self._record_revision(new_head, node_id, version, "create" if head is None else "write"), None
        )
        # /ADAPTER

    def rollback(self, node_id: str, to: Revision) -> None:
        # ADAPTER:rollback
        # persona-core rolls back to a per node version number, not to a store
        # revision, so the revision has to be translated first.
        target_node, target_version, _ = self._rev_node[to - 1]
        if target_node != node_id:
            msg = f"revision {to} does not belong to {node_id}"
            raise ValueError(msg)
        # /ADAPTER
        self._store.rollback(
            PERSONA_ID,
            node_id,
            target_version,
            source=WriteSource.SYSTEM,
            written_by="orchestrator",
            reason=f"rollback to revision {to}",
        )
        # ADAPTER:revision
        new_head = self._head_chunk(node_id)
        assert new_head is not None
        version = new_head.provenance.version if new_head.provenance else 1
        self._record_revision(new_head, node_id, version, "rollback")
        # /ADAPTER

    # ----- reads --------------------------------------------------------------

    def read_node(self, node_id: str) -> dict:
        head = self._head_chunk(node_id)
        if head is None:
            raise NodeNotFoundError(node_id)
        return json.loads(head.text)

    def diff(self, since: Revision) -> list[NodeChange]:
        # ADAPTER:diff
        # persona-core has no "what changed since" read. The narrowest call that
        # can return every change is get_all, which materialises and validates
        # every version of every node on every call.
        if since >= len(self._rev_key):
            return []
        cutoff = self._rev_key[since - 1] if since > 0 else None
        chunks = self._store.get_all(PERSONA_ID, include_superseded=True)
        fresh = [c for c in chunks if cutoff is None or (c.created_at, c.id) > cutoff]
        fresh.sort(key=lambda c: (c.created_at, c.id))
        changes: list[NodeChange] = []
        for offset, chunk in enumerate(fresh, start=since + 1):
            node_id, version, op = self._rev_node[offset - 1]
            changes.append(NodeChange(offset, node_id, version, op))
        return changes
        # /ADAPTER

    def traverse_constrains(self, node_id: str) -> list[str]:
        # ADAPTER:traverse
        # There is no edge concept in the store, so the closure is walked by
        # reading whole nodes. Reads are batched one breadth first level at a
        # time through the transport's logical id filter, which is the narrowest
        # multi node read persona-core offers.
        order: list[str] = []
        seen: set[str] = {node_id}
        frontier = list(self.read_node(node_id)["constrains"])
        while frontier:
            wanted = [n for n in dict.fromkeys(frontier) if n not in seen]
            if not wanted:
                break
            seen.update(wanted)
            heads = self._head_chunks(wanted)
            nxt: list[str] = []
            for nid in wanted:
                chunk = heads.get(nid)
                if chunk is None:
                    seen.discard(nid)
                    continue
                order.append(nid)
                nxt.extend(json.loads(chunk.text)["constrains"])
            frontier = nxt
        return order
        # /ADAPTER

    def history(self, node_id: str) -> list[Revision]:
        chain = self._store.history(PERSONA_ID, node_id)
        # ADAPTER:revision
        keys = {key: rev for rev, key in enumerate(self._rev_key, start=1)}
        return [keys[(c.created_at, c.id)] for c in chain]
        # /ADAPTER

    def head_revision(self) -> Revision:
        return len(self._rev_key)

    def close(self) -> None:
        return None

    # ----- internals ----------------------------------------------------------

    # ADAPTER:point_read
    # The MemoryStore protocol has no read by id: query() is semantic and
    # history() is a full scan, so a point read goes past the typed store to the
    # transport's logical id filter, which returns every version and leaves the
    # caller to pick the head.
    def _head_chunk(self, node_id: str) -> PersonaChunk | None:
        found = self._backend.get_by_logical_ids(
            persona_id=PERSONA_ID, store_kind=STORE_KIND, logical_ids=[node_id]
        )
        heads = current_view(found)
        if not heads:
            return None
        return max(heads, key=lambda c: c.provenance.version if c.provenance else 0)

    def _head_chunks(self, node_ids: list[str]) -> dict[str, PersonaChunk]:
        found = self._backend.get_by_logical_ids(
            persona_id=PERSONA_ID, store_kind=STORE_KIND, logical_ids=node_ids
        )
        heads: dict[str, PersonaChunk] = {}
        for chunk in current_view(found):
            prov = chunk.provenance
            if prov is not None:
                heads[prov.logical_id] = chunk
        return heads

    # /ADAPTER

    # ADAPTER:revision
    def _record_revision(self, chunk: PersonaChunk, node_id: str, version: int, op: str) -> int:
        self._rev_key.append((chunk.created_at, chunk.id))
        self._rev_node.append((node_id, version, op))
        return len(self._rev_key)

    # /ADAPTER
