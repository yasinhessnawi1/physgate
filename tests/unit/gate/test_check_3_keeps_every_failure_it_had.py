"""The equilibrium check refuses everything it refused before the fix, in the same words.

The fix made the check read balances it used to pass unread. It must not turn any balance
it refused into a pass or an unchecked record, so a declared force or a second reading
can never un-block a mount. The record in ``check_3_before/record.json`` holds what the
check said before the fix about every graph that carries a statics quantity: every graph
the gate's own tests and the injected-error tests build, the hand-made designs, errors
and probe shapes of ``check_3_before/handmade.py``, the integration fixtures' revisions
and the seeded random mounts of ``check_3_cases``. ``check_3_before/make.py`` says how
it was made, and from which commit.
"""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any

from check_3_cases import random_mounts

from physgate.gate import check_equilibrium
from physgate.gate.bounds_table import load_bounds
from physgate.gate.context import CheckContext
from physgate.gate.graph import GraphView
from physgate.state.store import Store

RECORD = Path(__file__).parent / "check_3_before" / "record.json"
#: The record's digest: a regenerated or edited record is a different record.
RECORD_SHA256 = "d37b3981fc4cf59ad7e4c0a772f588e3ce2b49d59e145339f081e3209865aaed"
#: The failing records the check wrote before the fix, counted when the record was made.
FAILURES_BEFORE = 314


def _cases() -> list[tuple[str, list[dict[str, Any]], list[dict[str, Any]]]]:
    data = RECORD.read_bytes()
    assert hashlib.sha256(data).hexdigest() == RECORD_SHA256
    record = json.loads(data)["cases"]
    drawn = dict(random_mounts())
    return [(c["id"], c.get("nodes") or drawn[c["id"]], c["before"]) for c in record]


def _now(root: Path, payloads: list[dict[str, Any]]) -> list[dict[str, Any]]:
    store = Store(root)
    try:
        for payload in payloads:
            assert store.write_node(dict(payload), str(payload["owner_role"])).accepted
    finally:
        store.close()
    view = GraphView.read(root, base_revision=0)
    ran = check_equilibrium.run(CheckContext(view=view, scope="system", bounds=load_bounds()))
    return [o.model_dump(mode="json") for o in ran.observations]


def test_every_balance_the_check_refused_before_the_fix_it_still_refuses_in_the_same_words(
    tmp_path: Path,
) -> None:
    cases = _cases()
    failing = [(cid, o) for cid, _, before in cases for o in before if o["outcome"] == "fail"]
    # The comparison is over a record that holds refusals, or it proves nothing.
    assert len(failing) == FAILURES_BEFORE
    lost = []
    for k, (cid, payloads, before) in enumerate(cases):
        if not any(o["outcome"] == "fail" for o in before):
            continue
        now = [
            {f: o[f] for f in ("node", "outcome", "message", "value")}
            for o in _now(tmp_path / str(k), payloads)
        ]
        lost += [(cid, o["node"]) for o in before if o["outcome"] == "fail" and o not in now]
    assert lost == []


def test_the_record_covers_the_shapes_the_fix_reads_anew(tmp_path: Path) -> None:
    # Beside a refusal: loads with both a mass and a load force (some in a refused unit),
    # reactions with no position, and load forces with no position, so the comparison
    # reaches every new branch of the placed path. And structures with no positions at
    # all, which the check now judges by forces alone, both refused and passed.
    cases = _cases()

    def has(payloads: list[dict[str, Any]], *names: str) -> bool:
        return any(set(names) <= set(p["quantities"]) for p in payloads)

    def refused(before: list[dict[str, Any]]) -> bool:
        return any(o["outcome"] == "fail" for o in before)

    def bare(p: dict[str, Any], name: str, place: str) -> bool:
        return name in p["quantities"] and place not in p["quantities"]

    beside = [(p, b) for _, p, b in cases if refused(b)]
    mixed = [p for p, _ in beside if has(p, "mass", "load_force")]
    refused_unit = [
        p
        for p in mixed
        if any(q["quantities"].get("load_force", {}).get("unit") not in (None, "N") for q in p)
    ]
    stray = [p for p, _ in beside if any(bare(q, "reaction_force", "support_position") for q in p)]
    forces = [
        p
        for p, _ in beside
        if any(bare(q, "load_force", "mount_position") and "mass" not in q["quantities"] for q in p)
    ]
    assert len(mixed) >= 20 and len(stray) >= 20 and len(refused_unit) >= 3 and len(forces) >= 5
    by_forces = {"fail": 0, "pass": 0}
    for k, (_, payloads, _) in enumerate(cases):
        if any(
            set(q["quantities"]) & {"support_position", "mount_position"} for q in payloads
        ) or not any("reaction_force" in q["quantities"] for q in payloads):
            continue
        now = _now(tmp_path / str(k), payloads)
        if any(o["outcome"] == "fail" for o in now):
            by_forces["fail"] += 1
        elif not any(o["outcome"] == "unchecked" for o in now):
            by_forces["pass"] += 1
    assert by_forces["fail"] >= 20 and by_forces["pass"] >= 5, by_forces
