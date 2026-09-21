"""Seeded workload generator for R-OP-01. No model is involved.

Same seed, same node set, same operation sequence, byte for byte, for both
implementations. See CRITERIA.md S6 for the mandated counts.
"""

from __future__ import annotations

import copy
import random
from collections import deque
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from typing import Any

DOMAINS = ("mechanical", "electrical", "control", "firmware", "cross")
#: The role that owns each domain. "cross" is owned by integration.
DOMAIN_OWNER = {
    "mechanical": "mechanical",
    "electrical": "electrical",
    "control": "control",
    "firmware": "firmware",
    "cross": "integration",
}
ALL_ROLES = (*sorted(set(DOMAIN_OWNER.values())), "orchestrator")
INTERFACE_OWNER = "orchestrator"

N_NODES = 200
N_INTERFACE = 50
N_WRITES = 1000
N_CROSS_ROLE = 150
N_MISSING_UNIT = 50
N_INTERFACE_WRITES = 20
N_HIGH_DEGREE_WRITES = 100
N_ROLLBACKS = 30
HIGH_DEGREE = 3

QUANTITY_NAMES = (
    "stall_current",
    "mass",
    "loop_gain",
    "supply_voltage",
    "bore_diameter",
    "sample_rate",
    "thermal_margin",
    "torque_peak",
)
UNITS = {
    "stall_current": "A",
    "mass": "kg",
    "loop_gain": "1",
    "supply_voltage": "V",
    "bore_diameter": "mm",
    "sample_rate": "Hz",
    "thermal_margin": "K",
    "torque_peak": "N*m",
}
SOURCES = ("datasheet", "calculation", "measurement", "assumption")

BASE_TIME = datetime(2026, 9, 1, 8, 0, 0, tzinfo=UTC)


@dataclass(frozen=True)
class Op:
    """One operation in the workload."""

    index: int
    kind: str  # "create" | "write" | "rollback"
    node_id: str
    actor_role: str = ""
    payload: dict[str, Any] | None = None
    expect: str = ""  # "accept" or "reject:<reason>"
    to_ordinal: int = 0  # rollback only, 1 based index into history()
    fault: str = ""  # "", "cross_role", "missing_unit", "interface"


@dataclass
class Workload:
    """Everything one seed produces."""

    seed: int
    nodes: dict[str, dict[str, Any]]
    ops: list[Op]
    deepest_node_id: str
    counts: dict[str, int] = field(default_factory=dict)
    #: node id -> every payload the generator ever asks to be stored for it.
    legal_payloads: dict[str, list[dict[str, Any]]] = field(default_factory=dict)


def _quantities(
    rng: random.Random, n: int, writer: str, *, with_units: bool = True
) -> dict[str, Any]:
    out: dict[str, Any] = {}
    for name in rng.sample(QUANTITY_NAMES, n):
        entry = {
            "value": round(rng.uniform(0.1, 240.0), 3),
            "source": rng.choice(SOURCES),
            "written_by": writer,
        }
        if with_units:
            entry["unit"] = UNITS[name]
        out[name] = entry
    return out


def _closure_size(nodes: dict[str, dict[str, Any]], start: str) -> int:
    seen: set[str] = set()
    queue = deque(nodes[start]["constrains"])
    while queue:
        nid = queue.popleft()
        if nid in seen or nid not in nodes:
            continue
        seen.add(nid)
        queue.extend(nodes[nid]["constrains"])
    return len(seen)


def build(seed: int) -> Workload:
    """Build the full workload for ``seed``."""
    rng = random.Random(seed)

    # ---- nodes -----------------------------------------------------------
    interface_ids = [f"iface.{DOMAINS[i % len(DOMAINS)]}.{i:02d}" for i in range(N_INTERFACE)]
    member_ids: list[str] = []
    for i in range(N_NODES - N_INTERFACE):
        domain = DOMAINS[i % len(DOMAINS)]
        member_ids.append(f"{domain}.node{i:03d}")
    all_ids = interface_ids + member_ids

    nodes: dict[str, dict[str, Any]] = {}
    for nid in all_ids:
        is_iface = nid in set(interface_ids)
        domain = nid.split(".")[1] if is_iface else nid.split(".")[0]
        owner = INTERFACE_OWNER if is_iface else DOMAIN_OWNER[domain]
        nodes[nid] = {
            "id": nid,
            "kind": "interface" if is_iface else rng.choice(["component", "module", "requirement"]),
            "domain": domain,
            "owner_role": owner,
            "quantities": _quantities(rng, rng.randint(1, 3), owner),
            "requirements": [f"REQ-{rng.randint(1, 120):03d}" for _ in range(rng.randint(0, 3))],
            "constrains": [],
            "model": f"models/{nid.replace('.', '_')}.py" if rng.random() < 0.4 else None,
            "geometry_hash": "sha256:" + "".join(rng.choice("0123456789abcdef") for _ in range(64)),
            "updated": BASE_TIME.isoformat(),
        }

    # ---- constrains edges ------------------------------------------------
    # Every member node points at zero to five others. At least a quarter of
    # the member nodes are forced to three or more so the workload can put
    # ten per cent of its writes on a high degree node.
    forced = set(rng.sample(member_ids, k=max(40, len(member_ids) // 4)))
    for nid in member_ids:
        low = HIGH_DEGREE if nid in forced else 0
        k = rng.randint(low, 5)
        targets = [t for t in rng.sample(all_ids, k=min(k + 2, len(all_ids))) if t != nid][:k]
        nodes[nid]["constrains"] = targets

    high_degree_ids = sorted(n for n in member_ids if len(nodes[n]["constrains"]) >= HIGH_DEGREE)
    deepest = max(sorted(all_ids), key=lambda n: (_closure_size(nodes, n),))
    # Tie break by lexicographic id: max() keeps the first maximum of a sorted
    # list, which is the lexicographically smallest among ties.

    # ---- create ops ------------------------------------------------------
    ops: list[Op] = []
    legal_payloads: dict[str, list[dict[str, Any]]] = {nid: [] for nid in all_ids}
    idx = 0
    for nid in interface_ids + member_ids:  # interfaces first: decomposition
        payload = copy.deepcopy(nodes[nid])
        ops.append(
            Op(
                index=idx,
                kind="create",
                node_id=nid,
                actor_role=nodes[nid]["owner_role"],
                payload=payload,
                expect="accept",
            )
        )
        legal_payloads[nid].append(payload)
        idx += 1

    # ---- write ops -------------------------------------------------------
    writes: list[Op] = []

    def _mutated(nid: str, writer: str, *, with_units: bool) -> dict[str, Any]:
        p = copy.deepcopy(nodes[nid])
        p["quantities"] = _quantities(rng, rng.randint(1, 3), writer, with_units=with_units)
        p["updated"] = (BASE_TIME + timedelta(seconds=len(writes) + 1)).isoformat()
        return p

    # 100 legal writes forced onto high degree nodes, then the rest anywhere.
    legal_targets = [high_degree_ids[i % len(high_degree_ids)] for i in range(N_HIGH_DEGREE_WRITES)]
    legal_targets += [
        rng.choice(member_ids)
        for _ in range(
            N_WRITES - N_CROSS_ROLE - N_MISSING_UNIT - N_INTERFACE_WRITES - N_HIGH_DEGREE_WRITES
        )
    ]
    for nid in legal_targets:
        owner = nodes[nid]["owner_role"]
        writes.append(
            Op(
                index=-1,
                kind="write",
                node_id=nid,
                actor_role=owner,
                payload=_mutated(nid, owner, with_units=True),
                expect="accept",
            )
        )

    for _ in range(N_CROSS_ROLE):
        nid = rng.choice(member_ids)
        owner = nodes[nid]["owner_role"]
        intruder = rng.choice([r for r in ALL_ROLES if r != owner])
        writes.append(
            Op(
                index=-1,
                kind="write",
                node_id=nid,
                actor_role=intruder,
                payload=_mutated(nid, intruder, with_units=True),
                expect="reject:cross_role_write",
                fault="cross_role",
            )
        )

    for _ in range(N_MISSING_UNIT):
        nid = rng.choice(member_ids)
        owner = nodes[nid]["owner_role"]
        writes.append(
            Op(
                index=-1,
                kind="write",
                node_id=nid,
                actor_role=owner,
                payload=_mutated(nid, owner, with_units=False),
                expect="reject:quantity_missing_unit",
                fault="missing_unit",
            )
        )

    for _ in range(N_INTERFACE_WRITES):
        nid = rng.choice(interface_ids)
        writes.append(
            Op(
                index=-1,
                kind="write",
                node_id=nid,
                actor_role=INTERFACE_OWNER,
                payload=_mutated(nid, INTERFACE_OWNER, with_units=True),
                expect="reject:interface_immutable",
                fault="interface",
            )
        )

    rng.shuffle(writes)

    # ---- rollbacks, placed only where a node already has two revisions ----
    accepted_so_far: dict[str, int] = {nid: 1 for nid in all_ids}  # the create
    positions: list[tuple[int, str, int]] = []
    for pos, op in enumerate(writes):
        if op.expect == "accept":
            accepted_so_far[op.node_id] += 1
            if accepted_so_far[op.node_id] >= 2:
                positions.append((pos + 1, op.node_id, accepted_so_far[op.node_id]))
    chosen = rng.sample(positions, k=min(N_ROLLBACKS, len(positions)))
    chosen.sort(key=lambda t: t[0])

    merged: list[Op] = []
    rb_by_pos: dict[int, list[tuple[str, int]]] = {}
    for pos, nid, revs in chosen:
        rb_by_pos.setdefault(pos, []).append((nid, rng.randint(1, max(1, revs - 1))))
    for pos, op in enumerate(writes):
        merged.append(op)
        for nid, ordinal in rb_by_pos.get(pos + 1, []):
            merged.append(Op(index=-1, kind="rollback", node_id=nid, to_ordinal=ordinal))

    for op in merged:
        ops.append(
            Op(
                index=idx,
                kind=op.kind,
                node_id=op.node_id,
                actor_role=op.actor_role,
                payload=op.payload,
                expect=op.expect,
                to_ordinal=op.to_ordinal,
                fault=op.fault,
            )
        )
        if op.kind == "write" and op.expect == "accept" and op.payload is not None:
            legal_payloads[op.node_id].append(op.payload)
        idx += 1

    counts = {
        "nodes": len(all_ids),
        "interface_nodes": len(interface_ids),
        "creates": len(all_ids),
        "writes": len(writes),
        "cross_role_writes": N_CROSS_ROLE,
        "missing_unit_writes": N_MISSING_UNIT,
        "interface_writes": N_INTERFACE_WRITES,
        "legal_writes": len(legal_targets),
        "writes_on_high_degree_nodes": sum(
            1 for o in writes if len(nodes[o.node_id]["constrains"]) >= HIGH_DEGREE
        ),
        "rollbacks": len(chosen),
        "deepest_closure_size": _closure_size(nodes, deepest),
    }
    return Workload(
        seed=seed,
        nodes=nodes,
        ops=ops,
        deepest_node_id=deepest,
        counts=counts,
        legal_payloads=legal_payloads,
    )


if __name__ == "__main__":
    import json
    import sys

    w = build(int(sys.argv[1]) if len(sys.argv) > 1 else 1)
    print(json.dumps({"deepest": w.deepest_node_id, "ops": len(w.ops), **w.counts}, indent=2))
