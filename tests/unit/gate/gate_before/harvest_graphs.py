"""A pytest plugin: record the latest node payloads of every graph a test has the gate read.

Used once, in a checkout of the commit before the coverage rules, to collect the graphs
``make_record.py`` judges there (see its docstring). It patches the graph reader for that one
session; nothing in the suite loads it. Under pytest-xdist each worker writes its own file,
``HARVEST_OUT`` with the worker's name appended, and ``make.py`` reads them all.
"""

from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any

import physgate.gate.graph as graph

SEEN: dict[str, list[dict[str, Any]]] = {}
_READ: Any = graph.GraphView.read


def _read(root: Path, base_revision: int, history: Any = None) -> Any:  # noqa: ANN401
    view = _READ(root, base_revision, history)
    payloads = [n.model_dump(mode="json") for n in view.nodes.values()]
    if any(p["quantities"] for p in payloads):
        SEEN[json.dumps(payloads, sort_keys=True)] = payloads
    return view


setattr(graph.GraphView, "read", staticmethod(_read))  # noqa: B010 - the patch is the point


def pytest_sessionfinish(session: object, exitstatus: int) -> None:
    """Write every graph seen, in a stable order."""
    worker = os.environ.get("PYTEST_XDIST_WORKER", "")
    with Path(os.environ["HARVEST_OUT"] + (f".{worker}" if worker else "")).open("w") as fh:
        json.dump(sorted(SEEN.values(), key=lambda p: json.dumps(p, sort_keys=True)), fh)
