"""Record what the equilibrium check said before the load readings, over the hand-made shapes.

Run inside a checkout of the commit before the readings (``b614325``, master after the
equilibrium fix), with that checkout's environment, after copying this directory into it;
with ``D`` the absolute path of this directory in that checkout:

    PYTHONPATH="$D" uv run python "$D/make.py" /abs/record.json

Each shape is a whole graph written as one revision and judged at system scope. Only what the
comparison reads is kept: every failing record's node, outcome, message and value, and every
other record's node and outcome. The test pins the record's digest.
"""

from __future__ import annotations

import json
import sys
import tempfile
from pathlib import Path
from typing import Any

import shapes

from physgate.gate import check_equilibrium
from physgate.gate.bounds_table import load_bounds
from physgate.gate.context import CheckContext
from physgate.gate.graph import GraphView
from physgate.state.store import Store


def judge(payloads: list[dict[str, Any]], tmp: Path) -> list[dict[str, Any]]:
    """Every equilibrium record over ``payloads`` at system scope."""
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
    """Judge every shape and write the record."""
    out = Path(sys.argv[1])
    rows = []
    with tempfile.TemporaryDirectory() as tmp:
        for k, (name, payloads, _) in enumerate(shapes.SHAPES):
            before = judge(payloads, Path(tmp) / str(k))
            kept = [
                {key: o[key] for key in ("node", "outcome", "message", "value")}
                if o["outcome"] == "fail"
                else {"node": o["node"], "outcome": o["outcome"]}
                for o in before
            ]
            rows.append({"name": name, "nodes": payloads, "before": kept})
    fails = sum(1 for r in rows for o in r["before"] if o["outcome"] == "fail")
    out.write_text(
        json.dumps({"made_at": "b614325", "cases": rows}, sort_keys=True, separators=(",", ":"))
        + "\n"
    )
    print(len(rows), "shapes,", fails, "failing records before the readings")


if __name__ == "__main__":
    main()
