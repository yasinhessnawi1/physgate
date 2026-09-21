"""Runs one seed's workload against one store and returns the metrics.

Shared by both implementations. Charged to neither in C5.
"""

from __future__ import annotations

import copy
import time
from collections import deque
from typing import Any

import generator

# The frozen file imports this from its own copy of the interface. It is
# taken from the promoted package instead, which the interface comparison
# proves is the same code. That redirect is the only import that moved.
from physgate.state.protocol import canonical_json

TRAVERSE_EVERY = 10


def percentile(values: list[float], pct: float) -> float:
    """Nearest rank percentile, in the unit of ``values``."""
    if not values:
        return float("nan")
    ordered = sorted(values)
    k = max(1, int(round(pct / 100.0 * len(ordered))))
    return ordered[min(k, len(ordered)) - 1]


def expected_closure(nodes: dict[str, dict[str, Any]], start: str) -> set[str]:
    """The transitive constrains closure, computed off the generated graph."""
    seen: set[str] = set()
    queue = deque(nodes[start]["constrains"])
    while queue:
        nid = queue.popleft()
        if nid in seen or nid not in nodes:
            continue
        seen.add(nid)
        queue.extend(nodes[nid]["constrains"])
    return seen


class FailureError(AssertionError):
    """A hard failure: the store did something the criteria forbid."""


def run(store: Any, work: generator.Workload) -> dict[str, Any]:  # noqa: ANN401 - Protocol duck type
    """Replay ``work`` against ``store``, scoring C1, C2, C3 and write latency."""
    c1 = {
        "cross_role_attempted": 0,
        "cross_role_rejected": 0,
        "interface_attempted": 0,
        "interface_rejected": 0,
        "missing_unit_attempted": 0,
        "missing_unit_rejected": 0,
        "legal_attempted": 0,
        "legal_accepted": 0,
        "creates_attempted": 0,
        "creates_accepted": 0,
        "rollbacks_attempted": 0,
        "rollbacks_completed": 0,
        "rejected_writes_that_mutated_the_graph": 0,
        "wrong_rejection_reason": 0,
    }
    diff_ms: list[float] = []
    traverse_ms: list[float] = []
    write_ms: list[float] = []
    rollback_ms: list[float] = []

    node_payloads: dict[str, dict[int, dict[str, Any]]] = {}
    last_payload: dict[str, dict[str, Any]] = {}
    cursor = store.head_revision()
    pending: list[tuple[int, str, str]] = []
    write_index = 0
    want_closure = expected_closure(work.nodes, work.deepest_node_id)

    failures: list[str] = []
    t_start = time.perf_counter()

    for op in work.ops:
        if op.kind == "create":
            c1["creates_attempted"] += 1
            t0 = time.perf_counter()
            result = store.write_node(copy.deepcopy(op.payload), op.actor_role)
            write_ms.append((time.perf_counter() - t0) * 1000.0)
            if not result.accepted:
                failures.append(f"create rejected: {op.node_id} ({result.reason})")
                continue
            c1["creates_accepted"] += 1
            node_payloads.setdefault(op.node_id, {})[result.revision] = op.payload  # type: ignore[assignment]
            last_payload[op.node_id] = op.payload  # type: ignore[assignment]
            pending.append((result.revision, op.node_id, "create"))
            continue

        if op.kind == "rollback":
            c1["rollbacks_attempted"] += 1
            revs = store.history(op.node_id)
            target = revs[op.to_ordinal - 1]
            t0 = time.perf_counter()
            store.rollback(op.node_id, target)
            rollback_ms.append((time.perf_counter() - t0) * 1000.0)
            new_rev = store.head_revision()
            payload = node_payloads[op.node_id][target]
            node_payloads[op.node_id][new_rev] = payload
            last_payload[op.node_id] = payload
            pending.append((new_rev, op.node_id, "rollback"))
            c1["rollbacks_completed"] += 1
            continue

        # ---- a write operation -------------------------------------------
        write_index += 1
        bucket = {
            "cross_role": "cross_role",
            "missing_unit": "missing_unit",
            "interface": "interface",
        }.get(op.fault, "legal")
        c1[f"{bucket}_attempted"] += 1

        t0 = time.perf_counter()
        result = store.write_node(copy.deepcopy(op.payload), op.actor_role)
        write_ms.append((time.perf_counter() - t0) * 1000.0)

        if op.expect == "accept":
            if not result.accepted:
                failures.append(f"legal write rejected: {op.node_id} ({result.reason})")
            else:
                c1["legal_accepted"] += 1
                node_payloads.setdefault(op.node_id, {})[result.revision] = op.payload  # type: ignore[assignment]
                last_payload[op.node_id] = op.payload  # type: ignore[assignment]
                pending.append((result.revision, op.node_id, "write"))
        else:
            wanted_reason = op.expect.split(":", 1)[1]
            if result.accepted:
                failures.append(f"{bucket} write accepted: {op.node_id}")
            else:
                c1[f"{bucket}_rejected"] += 1
                if result.reason != wanted_reason:
                    c1["wrong_rejection_reason"] += 1
                    failures.append(f"{bucket} rejected for the wrong reason: {result.reason}")
                if canonical_json(store.read_node(op.node_id)) != canonical_json(
                    last_payload[op.node_id]
                ):
                    c1["rejected_writes_that_mutated_the_graph"] += 1
                    failures.append(f"rejected write mutated {op.node_id}")

        # C2: diff after every write operation, accepted or rejected.
        t0 = time.perf_counter()
        changes = store.diff(cursor)
        diff_ms.append((time.perf_counter() - t0) * 1000.0)
        got = [(c.revision, c.node_id, c.op) for c in changes]
        if got != pending:
            failures.append(f"diff mismatch at write {write_index}: {got} != {pending}")
        cursor = store.head_revision()
        pending = []

        # C3: traversal of the deepest node every tenth write operation.
        if write_index % TRAVERSE_EVERY == 0:
            t0 = time.perf_counter()
            reached = store.traverse_constrains(work.deepest_node_id)
            traverse_ms.append((time.perf_counter() - t0) * 1000.0)
            if set(reached) != want_closure:
                failures.append(
                    f"closure mismatch at write {write_index}: "
                    f"{len(set(reached))} != {len(want_closure)}"
                )

    wall_s = time.perf_counter() - t_start

    return {
        "seed": work.seed,
        "wall_s": round(wall_s, 3),
        "deepest_node": work.deepest_node_id,
        "closure_size": len(want_closure),
        "workload_counts": work.counts,
        "c1": c1,
        "c2_diff_ms": {
            "p50": percentile(diff_ms, 50),
            "p95": percentile(diff_ms, 95),
            "n": len(diff_ms),
        },
        "c3_traverse_ms": {
            "p50": percentile(traverse_ms, 50),
            "p95": percentile(traverse_ms, 95),
            "n": len(traverse_ms),
        },
        "write_ms": {
            "p50": percentile(write_ms, 50),
            "p95": percentile(write_ms, 95),
            "n": len(write_ms),
        },
        "rollback_ms": {
            "p50": percentile(rollback_ms, 50),
            "p95": percentile(rollback_ms, 95),
            "n": len(rollback_ms),
        },
        "failures": failures[:40],
        "failure_count": len(failures),
    }
