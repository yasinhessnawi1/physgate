"""Opens a store after a SIGKILL and scores C4.

Consistent means all four checks in CRITERIA.md S7 C4 pass.
"""

from __future__ import annotations

import json
import sys
import time
from pathlib import Path

import generator
from protocol import canonical_json
from stores import open_store

T_PROCESS_START = time.perf_counter()


def _chain_report(impl: str, store: object, root: Path, node_ids: list[str]) -> list[str]:
    """Check 4: every version chain is 1..k, no gaps, no duplicates, one head."""
    problems: list[str] = []
    if impl == "baseline":
        versions: dict[str, list[int]] = {}
        with (root / "ledger.jsonl").open() as fh:
            for raw in fh:
                if not raw.endswith("\n"):
                    break
                entry = json.loads(raw)
                versions.setdefault(entry["node_id"], []).append(entry["version"])
        for node_id, seq in versions.items():
            if seq != list(range(1, len(seq) + 1)):
                problems.append(f"{node_id}: version chain {seq[:6]}...")
    else:
        # persona-core validates the chain inside history(): contiguous versions
        # from 1, one head, links intact. A broken chain raises.
        from persona.errors import BrokenVersionChainError

        for node_id in node_ids:
            try:
                store.history(node_id)  # type: ignore[attr-defined]
            except BrokenVersionChainError as exc:
                problems.append(f"{node_id}: {exc}")
    return problems


def main() -> None:
    impl, seed, root, ack_path = sys.argv[1], int(sys.argv[2]), Path(sys.argv[3]), Path(sys.argv[4])
    work = generator.build(seed)

    acks: list[dict] = []
    if ack_path.exists():
        with ack_path.open() as fh:
            for raw in fh:
                if not raw.endswith("\n"):
                    break  # torn tail of the acknowledgement file itself
                acks.append(json.loads(raw))

    report: dict = {"impl": impl, "seed": seed, "acknowledged_ops": len(acks)}

    opened = True
    try:
        store = open_store(impl, root)
    except Exception as exc:  # noqa: BLE001 - any failure to open is the finding
        report.update(consistent=False, opened=False, error=f"{type(exc).__name__}: {exc}")
        print(json.dumps(report))
        return
    open_and_recover_ms = (time.perf_counter() - T_PROCESS_START) * 1000.0

    t0 = time.perf_counter()
    problems: list[str] = []

    accepted = [a for a in acks if a["accepted"] and a["revision"] is not None]
    head = store.head_revision()
    last_ack_rev = max((a["revision"] for a in accepted), default=0)

    # Check 2: no acknowledged write is lost.
    touched = sorted({a["node_id"] for a in accepted})
    per_node: dict[str, list[int]] = {}
    for a in accepted:
        per_node.setdefault(a["node_id"], []).append(a["revision"])
    for node_id, revs in per_node.items():
        got = set(store.history(node_id))
        missing = [r for r in revs if r not in got]
        if missing:
            problems.append(f"{node_id}: lost acknowledged revisions {missing[:5]}")

    # Check 3: no node holds a payload that was never written.
    for node_id in touched:
        payload = canonical_json(store.read_node(node_id))
        allowed = {canonical_json(p) for p in work.legal_payloads[node_id]}
        if payload not in allowed:
            problems.append(f"{node_id}: current payload was never written")

    # Check 4: version chains intact.
    problems.extend(_chain_report(impl, store, root, touched))

    verify_ms = (time.perf_counter() - t0) * 1000.0
    report.update(
        consistent=not problems and opened,
        opened=opened,
        open_and_recover_ms=round(open_and_recover_ms, 3),
        verify_ms=round(verify_ms, 3),
        head_revision=head,
        last_acknowledged_revision=last_ack_rev,
        lost_after_last_ack=max(0, last_ack_rev - head),
        unacknowledged_extra=max(0, head - last_ack_rev),
        nodes_checked=len(touched),
        problems=problems[:20],
        problem_count=len(problems),
    )
    store.close()
    print(json.dumps(report))


if __name__ == "__main__":
    main()
