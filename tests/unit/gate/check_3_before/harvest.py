"""pytest plugin: record the latest node payloads of every graph a test has the gate read."""

import json
import os

import physgate.gate.graph as graph

STATICS = {"support_position", "mount_position", "reaction_force", "reaction_moment", "load_force"}
SEEN: dict[str, list[dict]] = {}
_orig = graph.GraphView.read.__func__


def _read(cls, root, base_revision, history=None):
    view = _orig(cls, root, base_revision, history)
    payloads = [n.model_dump(mode="json") for n in view.nodes.values()]
    if any(STATICS & set(p["quantities"]) for p in payloads):
        SEEN[json.dumps(payloads, sort_keys=True)] = payloads
    return view


graph.GraphView.read = classmethod(_read)


def pytest_sessionfinish(session, exitstatus):
    with open(os.environ["HARVEST_OUT"], "w") as fh:
        json.dump(sorted(SEEN.values(), key=lambda p: json.dumps(p, sort_keys=True)), fh)
