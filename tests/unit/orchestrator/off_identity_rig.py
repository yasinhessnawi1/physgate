"""A seeded reference run and what it leaves behind, as digests: the same bytes on every machine.

Three things a run writes, each made here from fixed inputs with a fixed clock and no model:

- the decomposition's prompt and schema, for a fixed brief and three sets of roles;
- the run's configuration, its event log, its ledger and the queue's two files, from a loop
  over stand-in sessions that carries two subtasks to their merges;
- the store's journal, from the stand-in plan's interface node and two node writes.

The digests are taken over the files as written, so a byte added to any line changes one. A
test holds them to the values recorded from the code as it was before a switch was added, so a
run with the switch off is shown to write what a run wrote before the switch existed.
"""

from __future__ import annotations

import hashlib
from pathlib import Path
from typing import Any

from loop_fakes import Rig, plan
from orch_helpers import CLEAN_HARNESS

from physgate.orchestrator.decompose import plan_schema, prompt_for
from physgate.orchestrator.events import read_events
from physgate.orchestrator.run_config import ModelStrings
from physgate.state.store import Store

BRIEF = "Build a robot.\n\nAcceptance criteria\n\n1. It balances.\n2. It drives.\n"
ROLE_SETS: tuple[tuple[str, ...], ...] = (
    ("control", "firmware"),
    ("control", "electrical", "firmware", "mechanical"),
    ("control", "firmware", "integration", "sizing"),
)


#: A role whose sessions are dispatched, so the run goes past its plan.
MODELS = ModelStrings(
    decomposition="claude-sonnet-5",
    roles={"control": "claude-sonnet-5"},
    reviewers={"control": "claude-opus-5-5"},
)


#: What the run directory holds that is the same bytes on every machine. The write account
#: beside them names each file it guards by where the file system put it, and is left out.
RUN_FILES = ("run.json", "events.jsonl", "ledger.jsonl", "queue.jsonl", "queue_decisions.jsonl")


def _sha(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _node(node_id: str, kind: str, quantities: dict[str, Any]) -> dict[str, Any]:
    return {
        "id": node_id,
        "kind": kind,
        "domain": "electrical",
        "owner_role": "electrical",
        "quantities": {
            name: {"value": value, "unit": unit, "source": "brief", "written_by": "electrical"}
            for name, (value, unit) in quantities.items()
        },
        "requirements": [],
        "constrains": [],
        "model": None,
        "geometry_hash": "sha256:0",
        "updated": "2026-09-26T00:00:00Z",
    }


def sent() -> dict[str, str]:
    """The digest of the prompt and of the schema each set of roles is sent."""
    found: dict[str, str] = {}
    for roles in ROLE_SETS:
        key = "+".join(roles)
        found[f"prompt:{key}"] = _sha(prompt_for(BRIEF, list(roles)).encode())
        found[f"schema:{key}"] = _sha(plan_schema(list(roles), BRIEF).encode())
    return found


def driven(run_dir: Path) -> dict[str, str]:
    """How a run driven to its end ended, and the digest of each file it left."""
    run_dir.mkdir(parents=True, exist_ok=True)
    rig = Rig(run_dir, config_overrides={"harness": CLEAN_HARNESS, "models": MODELS})
    loop = rig.open()
    loop.start(
        [entry.model_copy(update={"assigned_role": "control"}) for entry in plan("s1", "s2")]
    )
    ended = loop.run().kind
    loop.close()
    left = {name: _sha((run_dir / name).read_bytes()) for name in RUN_FILES}
    return {"ended": ended, "events": str(len(read_events(run_dir / "events.jsonl"))), **left}


def stored(root: Path) -> dict[str, str]:
    """The digest of the store's journal and of each node file after three fixed writes."""
    store = Store(root)
    try:
        writes = (
            _node("iface.power_bus", "interface", {"v": (12, "V")}),
            _node("electrical.battery", "component", {"energy_capacity": (20, "W*h")}),
            _node("electrical.battery", "component", {"energy_capacity": (24, "W*h")}),
        )
        for payload in writes:
            assert store.write_node(payload, actor_role="electrical").accepted
    finally:
        store.close()
    return {
        str(path.relative_to(root)): _sha(path.read_bytes())
        for path in sorted(root.rglob("*"))
        if path.is_file()
    }


def reference(tmp: Path) -> dict[str, str]:
    """Everything the reference run leaves, by name: the fixture a test holds the code to."""
    found = sent()
    found.update({f"run:{name}": digest for name, digest in driven(tmp / "run").items()})
    found.update({f"store:{name}": digest for name, digest in stored(tmp / "store").items()})
    return found
