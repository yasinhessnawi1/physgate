"""Record what the equilibrium check said before the fix, over every statics graph we have.

Run inside a checkout of the commit before the fix (``247427b``), with that checkout's
environment, after copying the fix's gate tests and this directory into it, so the
graphs those tests build are judged too (they fail there, as they should):

    HARVEST_OUT=harvested.json PYTHONPATH=<this directory> \
        uv run pytest -q -p harvest tests/unit/gate tests/injected
    PYTHONPATH=<this directory>:<tests/unit/gate> uv run python make.py harvested.json record.json

Everything it reads is in the repository, so a clean clone remakes the record; the
test pins its digest.

Cases, each a whole graph written as one revision and judged at system scope:
- every graph the gate's own tests and the injected-error tests had the gate read that
  carries a statics quantity (harvested with harvest.py);
- the hand-made designs, their errors and the probe shapes of ``handmade``;
- the integration fixtures' designed revisions (domain_review_artefacts.REVISIONS);
- the seeded random mounts of ``check_3_cases``.

Only what the comparison reads is kept: every failing record's node, outcome, message and
value, and every other record's node and outcome.
"""

from __future__ import annotations

import json
import sys
import tempfile
from pathlib import Path
from typing import Any

from physgate.gate import check_equilibrium
from physgate.gate.bounds_table import load_bounds
from physgate.gate.context import CheckContext
from physgate.gate.graph import GraphView
from physgate.state.store import Store


def from_integration(root: Path) -> list[tuple[str, list[dict[str, Any]]]]:
    sys.path.insert(0, str(root / "tests" / "integration" / "orchestrator"))
    sys.path.insert(0, str(root / "tests"))
    import domain_review_artefacts as d

    found = []
    for name, (_, base, revision) in d.REVISIONS.items():
        merged = {n["id"]: n for n in base}
        for n in revision:
            merged[n["id"]] = n
        found.append((f"integration:{name}", list(merged.values())))
    return found


def judge(payloads: list[dict[str, Any]], tmp: Path) -> list[dict[str, Any]]:
    store = Store(tmp)
    try:
        for p in payloads:
            result = store.write_node(dict(p), str(p["owner_role"]))
            if not result.accepted:
                raise ValueError(f"refused {p['id']}: {result.reason}")
    finally:
        store.close()
    view = GraphView.read(tmp, base_revision=0)
    ran = check_equilibrium.run(CheckContext(view=view, scope="system", bounds=load_bounds()))
    return [o.model_dump(mode="json") for o in ran.observations]


def main() -> None:
    harvested, out = Path(sys.argv[1]), Path(sys.argv[2])
    cases: list[tuple[str, list[dict[str, Any]]]] = [
        (f"tests:{i:03d}", p) for i, p in enumerate(json.loads(harvested.read_text()))
    ]
    import handmade

    cases += handmade.handmade()
    cases += from_integration(Path.cwd())
    import check_3_cases

    cases += check_3_cases.random_mounts()
    rows = []
    with tempfile.TemporaryDirectory() as tmp:
        for k, (cid, payloads) in enumerate(cases):
            try:
                before = judge(payloads, Path(tmp) / str(k))
            except ValueError as exc:
                print("skipped", cid, exc)
                continue
            kept = [
                {k: o[k] for k in ("node", "outcome", "message", "value")}
                if o["outcome"] == "fail"
                else {"node": o["node"], "outcome": o["outcome"]}
                for o in before
            ]
            row: dict[str, Any] = {"id": cid, "before": kept}
            if not cid.startswith("random:"):
                row["nodes"] = payloads
            rows.append(row)
    fails = sum(1 for r in rows for o in r["before"] if o["outcome"] == "fail")
    out.write_text(
        json.dumps({"made_at": "247427b", "cases": rows}, sort_keys=True, separators=(",", ":"))
        + "\n"
    )
    print(len(rows), "cases,", fails, "failing records before the fix")


if __name__ == "__main__":
    main()
