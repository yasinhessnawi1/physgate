"""Implementation A: one JSON file per node plus an append only JSONL ledger.

The ledger is the authority. A mutation is durable once its ledger line is
fsynced; the per node JSON file is a derived materialisation that recovery
rebuilds. That ordering is what makes a SIGKILL between the two harmless.

Written from scratch for R-OP-01. Nothing here is tuned after seeing numbers.
"""

from __future__ import annotations

import json
import os
from collections import deque
from pathlib import Path

from protocol import (
    REJECT_CROSS_ROLE,
    REJECT_INTERFACE_IMMUTABLE,
    REJECT_MISSING_UNIT,
    NodeChange,
    NodeNotFoundError,
    Revision,
    WriteResult,
)


def _unit_violation(node: dict) -> bool:
    """True if any quantity carries a bare number with no unit string."""
    for entry in (node.get("quantities") or {}).values():
        if not isinstance(entry, dict):
            return True
        unit = entry.get("unit")
        if not isinstance(unit, str) or not unit:
            return True
    return False


class BaselineStore:
    """JSON node files on disk, an append only JSONL ledger beside them."""

    def __init__(self, root: Path) -> None:
        self.root = Path(root)
        self.nodes_dir = self.root / "nodes"
        self.ledger_path = self.root / "ledger.jsonl"
        self.nodes_dir.mkdir(parents=True, exist_ok=True)
        self.ledger_path.touch(exist_ok=True)

        # Location indexes, rebuilt at open from the ledger alone.
        self._offsets: dict[int, int] = {}
        self._node_revs: dict[str, list[int]] = {}
        self._head: dict[str, tuple[int, int]] = {}  # node_id -> (revision, version)
        self._next_rev = 1

        self.recover()
        self._ledger = self.ledger_path.open("ab")

    # ----- open and recovery ----------------------------------------------

    def recover(self) -> None:
        """Rebuild the indexes from the ledger and repair the node files.

        A torn final line (the process died between write and fsync) is
        truncated away. Any node file that does not match the ledger head is
        rewritten from the ledger payload.
        """
        good_end = 0
        with self.ledger_path.open("rb") as fh:
            while True:
                offset = fh.tell()
                raw = fh.readline()
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
                good_end = fh.tell()

        if good_end < self.ledger_path.stat().st_size:
            with self.ledger_path.open("r+b") as fh:
                fh.truncate(good_end)

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

    # ----- writes ----------------------------------------------------------

    def write_node(self, node: dict, actor_role: str) -> WriteResult:
        node_id = node["id"]
        known = self._head.get(node_id)

        if known is None:
            if actor_role != node.get("owner_role"):
                return WriteResult(False, None, REJECT_CROSS_ROLE)
        else:
            current = self.read_node(node_id)
            if actor_role != current["owner_role"]:
                return WriteResult(False, None, REJECT_CROSS_ROLE)
            if current["kind"] == "interface":
                return WriteResult(False, None, REJECT_INTERFACE_IMMUTABLE)

        if _unit_violation(node):
            return WriteResult(False, None, REJECT_MISSING_UNIT)

        version = 1 if known is None else known[1] + 1
        rev = self._append("create" if known is None else "write", node_id, version, node)
        self._materialise(node_id, rev, version, node)
        return WriteResult(True, rev, None)

    def rollback(self, node_id: str, to: Revision) -> None:
        entry = self._entry_at(to)
        if entry["node_id"] != node_id:
            msg = f"revision {to} does not belong to {node_id}"
            raise ValueError(msg)
        version = self._head[node_id][1] + 1
        rev = self._append("rollback", node_id, version, entry["payload"])
        self._materialise(node_id, rev, version, entry["payload"])

    # ----- reads ------------------------------------------------------------

    def read_node(self, node_id: str) -> dict:
        path = self._node_path(node_id)
        if not path.exists():
            raise NodeNotFoundError(node_id)
        return json.loads(path.read_text())["payload"]

    def diff(self, since: Revision) -> list[NodeChange]:
        head = self._next_rev - 1
        if since >= head:
            return []
        changes: list[NodeChange] = []
        with self.ledger_path.open("rb") as fh:
            fh.seek(self._offsets[since + 1])
            for raw in fh:
                if not raw.endswith(b"\n"):
                    break
                entry = json.loads(raw)
                changes.append(
                    NodeChange(entry["rev"], entry["node_id"], entry["version"], entry["op"])
                )
        return changes

    def traverse_constrains(self, node_id: str) -> list[str]:
        order: list[str] = []
        seen: set[str] = {node_id}
        queue = deque(self.read_node(node_id)["constrains"])
        while queue:
            nid = queue.popleft()
            if nid in seen or nid not in self._head:
                continue
            seen.add(nid)
            order.append(nid)
            queue.extend(self.read_node(nid)["constrains"])
        return order

    def history(self, node_id: str) -> list[Revision]:
        return list(self._node_revs.get(node_id, []))

    def head_revision(self) -> Revision:
        return self._next_rev - 1

    def close(self) -> None:
        if not self._ledger.closed:
            self._ledger.close()

    # ----- internals --------------------------------------------------------

    def _node_path(self, node_id: str) -> Path:
        return self.nodes_dir / f"{node_id}.json"

    def _append(self, op: str, node_id: str, version: int, payload: dict) -> int:
        rev = self._next_rev
        line = json.dumps(
            {"rev": rev, "op": op, "node_id": node_id, "version": version, "payload": payload},
            sort_keys=True,
            separators=(",", ":"),
        ).encode() + b"\n"
        offset = self._ledger.tell()
        self._ledger.write(line)
        self._ledger.flush()
        os.fsync(self._ledger.fileno())
        self._offsets[rev] = offset
        self._node_revs.setdefault(node_id, []).append(rev)
        self._head[node_id] = (rev, version)
        self._next_rev = rev + 1
        return rev

    def _entry_at(self, rev: Revision) -> dict:
        with self.ledger_path.open("rb") as fh:
            fh.seek(self._offsets[rev])
            return json.loads(fh.readline())

    def _materialise(self, node_id: str, rev: int, version: int, payload: dict) -> None:
        """Atomically replace the node file. Derived from the ledger, never authoritative."""
        path = self._node_path(node_id)
        tmp = path.with_suffix(".json.tmp")
        body = json.dumps(
            {"rev": rev, "version": version, "payload": payload},
            sort_keys=True,
            separators=(",", ":"),
        )
        with tmp.open("w") as fh:
            fh.write(body)
            fh.flush()
            os.fsync(fh.fileno())
        os.replace(tmp, path)
