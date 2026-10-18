"""A pytest plugin: record the latest node payloads of every graph a test has the gate read.

Used once, in a checkout of the commit before the equilibrium fix, to collect the graphs
``make.py`` judges there (see its docstring). It patches the graph reader for that one
session; nothing in the suite loads it.
"""

from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any

import physgate.gate.graph as graph

STATICS = {"support_position", "mount_position", "reaction_force", "reaction_moment", "load_force"}
SEEN: dict[str, list[dict[str, Any]]] = {}
_READ: Any = graph.GraphView.read


def _read(root: Path, base_revision: int, history: Any = None) -> Any:  # noqa: ANN401
    view = _READ(root, base_revision, history)
    payloads = [n.model_dump(mode="json") for n in view.nodes.values()]
    if any(STATICS & set(p["quantities"]) for p in payloads):
        SEEN[json.dumps(payloads, sort_keys=True)] = payloads
    return view


setattr(graph.GraphView, "read", staticmethod(_read))  # noqa: B010 - the patch is the point


def pytest_sessionfinish(session: object, exitstatus: int) -> None:
    """Write every graph seen, in a stable order."""
    with Path(os.environ["HARVEST_OUT"]).open("w") as fh:
        json.dump(sorted(SEEN.values(), key=lambda p: json.dumps(p, sort_keys=True)), fh)
