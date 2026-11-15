"""The runs the Evidence screen's routes are proven on: each kind, a drifted run, two refused.

Made by the real loop with stand-in sessions and no model, under ``<out>/runs``, all against one
target repository, so they differ only where each is meant to:

- ``ev-reportable``: a reportable run, from a clean commit inside the OS layer, protecting a
  held-out tier of two roots made beside the runs (``<out>/tier``), never under them;
- ``ev-development``: neither reportable nor an ablation, the gate observing;
- ``ev-ablation``: an ablation run with the hooks off, from a clean commit inside the OS layer;
- ``ev-drifted``: a development run whose role is pinned to another model and whose output-token
  limit differs, so it is refused against ``ev-development`` by name;
- ``ev-tampered``: a development run whose configuration was rewritten after it started, so its
  first line names another configuration;
- ``ev-unreadable``: a development run whose log ends in a line of a kind this package does not
  know, as a run recorded by a later harness would hold.

Every run's first attempt fails the gate, so each records gate events.
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from pathlib import Path

from ui_rig import evaluation_rig

from physgate.orchestrator.run_config import HarnessState
from physgate.oslayer.probe import Present

#: A clean commit for the measured runs, which start only from one.
CLEAN = HarnessState(commit="c" * 40, clean=True, uncommitted_sha256=None)
#: The OS layer a measured run is held inside.
LAYER = Present(mechanism="seatbelt", claude_version="2.1.301")
#: One canary per held-out task: 32 hexadecimal characters, as the record's type requires.
CANARIES = ("9a1e7c0d5b3f42e8a6c1d0f7b2e94a37", "d00dfeed7d2b4e19a8f63c0d1e2b7a95")
#: Every run, in the order the root lists them.
RUNS = (
    "ev-ablation",
    "ev-development",
    "ev-drifted",
    "ev-reportable",
    "ev-tampered",
    "ev-unreadable",
)
#: The model the drifted run's role is pinned to, and its output-token limit.
DRIFTED_MODEL = "claude-opus-5-5"
DRIFTED_TOKENS = 32000
#: The line the unreadable run's log ends in.
LATER_LINE = b'{"kind": "a_kind_a_later_harness_writes", "seq": 999}\n'


@dataclass(frozen=True)
class EvidenceRuns:
    #: The root the runs lie under.
    runs: Path
    #: The reportable run's held-out tier, beside the root.
    tier: tuple[Path, ...]


def tier_digest(root: Path) -> str:
    return hashlib.sha256(f"held-out root {root.name}".encode()).hexdigest()


def evidence_runs(out: Path) -> EvidenceRuns:
    """Build every run under ``out/runs`` and the held-out tier under ``out/tier``."""
    rig = evaluation_rig()
    runs = out / "runs"
    repo = rig.target_repo(out / "target")
    tier = tuple(out / "tier" / name for name in ("scenarios-e3a1", "answers-e3a1"))
    for root in tier:
        root.mkdir(parents=True)
        (root / "task.json").write_text("{}\n")
    measured = {"harness": CLEAN, "os_layer": LAYER, "os_layer_absent": "refuse"}
    gate = rig.Gate(fail_on={1})
    rig.fake_run(
        runs,
        "ev-reportable",
        repo,
        gate=gate,
        overrides={
            **measured,
            "reportable": True,
            "held_out": tuple(str(r) for r in tier),
            "held_out_canaries": CANARIES,
            "held_out_sha256": tuple(tier_digest(r) for r in tier),
        },
    )
    development = {"gate_mode": "observe"}
    rig.fake_run(runs, "ev-development", repo, gate=gate, overrides=development)
    rig.fake_run(
        runs,
        "ev-ablation",
        repo,
        gate=gate,
        overrides={**measured, "ablation": True, "hooks": "off"},
    )
    drifted = rig.config("ev-drifted", repo).models.model_copy(
        update={"roles": {"electrical": DRIFTED_MODEL}}
    )
    rig.fake_run(
        runs,
        "ev-drifted",
        repo,
        gate=gate,
        overrides={**development, "models": drifted, "max_output_tokens": DRIFTED_TOKENS},
    )
    tampered = rig.fake_run(runs, "ev-tampered", repo, gate=gate, overrides=development)
    recorded = json.loads((tampered / "run.json").read_bytes())
    (tampered / "run.json").write_text(json.dumps({**recorded, "seed": recorded["seed"] + 1}))
    unreadable = rig.fake_run(runs, "ev-unreadable", repo, gate=gate, overrides=development)
    with (unreadable / "events.jsonl").open("ab") as log:
        log.write(LATER_LINE)
    return EvidenceRuns(runs=runs, tier=tier)
