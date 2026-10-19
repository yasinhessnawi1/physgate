r"""Record what the gate's checks said before the coverage rules, over every graph we have.

Run inside a clean checkout of the commit before the rules (the record names it), with that
checkout's own environment:

    HARVEST_OUT=harvested.json PYTHONPATH=<this directory> \
        uv run pytest -q -n 6 -p harvest_graphs tests/unit tests/injected
    PYTHONPATH=<tests/unit/gate>:<tests>:<tests/unit/evaluation> \
        uv run python make_record.py record.json <commit> harvested.json*

Cases, each a whole graph written as one revision and judged at system scope:
- every graph the unit and injected-error suites had the gate read that carries a quantity
  (harvested with harvest_graphs.py);
- every graph of the equilibrium check's own record (``check_3_before``), its seeded random
  mounts included;
- the gate's fixtures, the stand-in drive plan, the integration fixtures' designs and
  revisions, and the instrument's two test corpora, each base with each clean and each
  injected revision.

Equilibrium is left out: its own record holds it. Propagation is left out: it judges changes
between revisions, and a case here is one revision. Only what the comparison reads is kept:
every failing record's check, node, message and value, and every other record's check, node
and outcome.
"""

from __future__ import annotations

import json
import sys
import tempfile
from pathlib import Path
from typing import Any

from physgate.gate.bounds_table import load_bounds
from physgate.gate.context import CheckContext
from physgate.gate.graph import GraphView
from physgate.gate.registry import REGISTRY
from physgate.state.store import Store

#: The checks the record holds.
CHECKS = ("units", "magnitude", "power", "conservation", "thermal")


def merged(base: Any, *revisions: Any) -> list[dict[str, Any]]:  # noqa: ANN401 - fixture shapes
    """``base`` with each revision's nodes written over it, by id."""
    nodes = {n["id"]: n for n in base}
    for revision in revisions:
        for n in revision:
            nodes[n["id"]] = n
    return list(nodes.values())


def designs() -> list[tuple[str, list[dict[str, Any]]]]:
    """The designs kept in the repository's own fixtures."""
    sys.path.insert(0, str(Path.cwd() / "tests" / "integration" / "orchestrator"))
    import domain_review_artefacts as d
    import gate_fixtures as g
    import instrument_corpus as ic
    import pilot_corpus as pc
    import stand_in_drive_plan as s

    found: list[tuple[str, list[dict[str, Any]]]] = []
    for name in ("UNITS", "MAGNITUDE", "EQUILIBRIUM", "POWER", "JOINT_POWER", "CONSERVATION"):
        found.append((f"fixtures:{name}", list(getattr(g, name))))
    found.append(("fixtures:THERMAL", list(g.THERMAL)))
    found.append(("fixtures:all_six", list(g.all_six())))
    found.append(("stand_in:DRIVE_MODULE", merged([s.POWER_BUS], s.DRIVE_MODULE)))
    for name, (_, base, revision) in d.REVISIONS.items():
        found.append((f"integration:{name}:base", list(base)))
        found.append((f"integration:{name}", merged(base, revision)))
    for name, (_, _, proposal, _) in d.ATTEMPTS.items():
        found.append((f"integration:{name}", [proposal]))
    for label, corpus in (("instrument", ic), ("pilot", pc)):
        found.append((f"{label}:base", list(corpus.BASE_NODES)))
        for artefact in corpus.ARTEFACTS:
            for side in ("clean", "injected"):
                nodes = artefact[side]["nodes"]
                found.append((f"{label}:{artefact['id']}:{side}", merged(corpus.BASE_NODES, nodes)))
    return found


def judge(payloads: list[dict[str, Any]], tmp: Path) -> list[dict[str, Any]]:
    """Every record the recorded checks write over ``payloads`` at system scope."""
    store = Store(tmp)
    try:
        for p in payloads:
            result = store.write_node(dict(p), str(p["owner_role"]))
            if not result.accepted:
                raise ValueError(f"refused {p['id']}: {result.reason}")
    finally:
        store.close()
    view = GraphView.read(tmp, base_revision=0)
    ctx = CheckContext(view=view, scope="system", bounds=load_bounds())
    records = []
    for check in REGISTRY:
        if check.name in CHECKS:
            for o in check.run(ctx).observations:
                records.append({"check": check.name, **o.model_dump(mode="json")})
    return records


def kept(record: dict[str, Any]) -> dict[str, Any]:
    """What the comparison reads of one record."""
    if record["outcome"] == "fail":
        return {k: record[k] for k in ("check", "node", "outcome", "message", "value")}
    return {k: record[k] for k in ("check", "node", "outcome")}


def main() -> None:
    """Judge every case and write the record."""
    out, commit, harvested = Path(sys.argv[1]), sys.argv[2], [Path(a) for a in sys.argv[3:]]
    import check_3_cases

    statics = Path(__file__).parent.parent / "check_3_before" / "record.json"
    equilibrium = json.loads(statics.read_text())
    drawn = dict(check_3_cases.random_mounts())
    graphs = {
        json.dumps(p, sort_keys=True): p for path in harvested for p in json.loads(path.read_text())
    }
    cases: list[tuple[str, list[dict[str, Any]]]] = [
        (f"tests:{i:04d}", graphs[k]) for i, k in enumerate(sorted(graphs))
    ]
    cases += [
        (f"check_3:{c['id']}", c.get("nodes") or drawn[c["id"]]) for c in equilibrium["cases"]
    ]
    cases += designs()
    rows, seen = [], set()
    with tempfile.TemporaryDirectory() as tmp:
        for k, (cid, payloads) in enumerate(cases):
            key = json.dumps(sorted(payloads, key=lambda p: p["id"]), sort_keys=True)
            if key in seen:
                continue
            seen.add(key)
            try:
                before = judge(payloads, Path(tmp) / str(k))
            except ValueError as exc:
                print("skipped", cid, exc)
                continue
            row: dict[str, Any] = {"id": cid, "before": [kept(o) for o in before]}
            if not cid.startswith("check_3:random:"):
                row["nodes"] = payloads
            rows.append(row)
    fails = sum(1 for r in rows for o in r["before"] if o["outcome"] == "fail")
    out.write_text(
        json.dumps({"made_at": commit, "cases": rows}, sort_keys=True, separators=(",", ":")) + "\n"
    )
    print(len(rows), "cases,", fails, "failing records before the rules")


if __name__ == "__main__":
    main()
