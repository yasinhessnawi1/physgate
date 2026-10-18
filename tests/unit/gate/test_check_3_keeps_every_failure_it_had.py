"""The equilibrium check refuses everything it refused before the fix, in the same words.

The fix made the check read balances it used to pass unread. It must not turn any balance
it refused into a pass or an unchecked record, so a declared force or a second reading
can never un-block a mount. The record in ``check_3_before/record.json`` holds what the
check said before the fix about every graph that carries a statics quantity: every graph
the gate's own tests and the injected-error tests build, the hand-made reproduction
designs with their errors, the integration fixtures' revisions and the seeded random
mounts of ``check_3_cases``. ``check_3_before/make.py`` says how it was made, and from
which commit.
"""

from __future__ import annotations

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
#: The failing records the check wrote before the fix, counted when the record was made.
FAILURES_BEFORE = 310


def _cases() -> list[tuple[str, list[dict[str, Any]], list[dict[str, Any]]]]:
    record = json.loads(RECORD.read_text())["cases"]
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


def test_the_record_covers_the_shapes_the_fix_reads_anew() -> None:
    # Mixed loads, unplaced reactions and members with a load force and no position are
    # all in the record, so the comparison reaches every new branch beside a refusal.
    cases = _cases()

    def has(payloads: list[dict[str, Any]], *names: str) -> bool:
        return any(set(names) <= set(p["quantities"]) for p in payloads)

    def refused(before: list[dict[str, Any]]) -> bool:
        return any(o["outcome"] == "fail" for o in before)

    mixed = [c for c, p, b in cases if refused(b) and has(p, "mass", "load_force")]
    stray = [
        c
        for c, p, b in cases
        if refused(b)
        and any(
            "reaction_force" in q["quantities"] and "support_position" not in q["quantities"]
            for q in p
        )
    ]
    assert len(mixed) >= 20 and len(stray) >= 20
