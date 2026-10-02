"""A deliberately wrong control artefact, refused by the gate, zero review tokens.

``control.loop_gain`` is already catalogued (``gate/catalogue.py``) as a
dimensionless quantity, so writing it in volts is a unit-shape fault check 1
already refuses — nothing added to the gate for this. What this proves is the
whole chain: the real registered gate, inside the real loop, at subtask
cadence, with the reviewer never invoked and its token spend at zero
(ARCH-031's own acceptance test, for a control artefact specifically rather
than the electrical one the rest of the suite uses).

Built without touching ``git_rig.py``'s ``config``/``plan_entry`` helpers (both
hardcode ``assigned_role="electrical"``): this test assembles its own
``RunConfig``/``PlanEntry`` for the ``control`` role so it needs no change to a
fixture other specs share.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest
from gate_fixtures import graph, node
from git_rig import DispatchPort, GitDispatcher, Reviewer, config, run_layout

from physgate.orchestrator.accounting import TokenAccount
from physgate.orchestrator.apply import GitChangeChecker, StoreKeeper
from physgate.orchestrator.cli import default_registrations
from physgate.orchestrator.events import GateRan, ReviewRan, read_events
from physgate.orchestrator.git import head_of
from physgate.orchestrator.loop import Loop
from physgate.orchestrator.merge import GitMerger
from physgate.orchestrator.record import (
    DecompositionCall,
    DecompositionSummary,
    PlanEntry,
    RunRecord,
)
from physgate.orchestrator.run_config import ModelStrings, RunConfig

pytestmark = [pytest.mark.integration, pytest.mark.injected]

ROLE = "control"
SUBTASK = "s1"
MODULE_DIR = "modules/control"

#: Otherwise sound; its one fault is the unit on ``loop_gain`` (dimensionless, catalogued).
WRONG_GAIN = node(
    "control.loop_gain",
    domain="control",
    quantities={"loop_gain": (2.5, "V")},
)


class _PayingReviewer(Reviewer):
    """Reports the tokens a real reviewer would, so a zero count means it never ran."""

    def review(self, artefact: Any) -> Any:
        from physgate.orchestrator.protocols import MessageUsage, Usage

        result = super().review(artefact)
        usage = Usage(
            input_tokens=40,
            output_tokens=9,
            cache_read_input_tokens=0,
            cache_creation_input_tokens=0,
        )
        return result.model_copy(
            update={"usage": (MessageUsage(message_id=f"r{self.calls}", usage=usage),)}
        )


def _run_config() -> RunConfig:
    return config(run_id="a0-injected-1").model_copy(
        update={
            "models": ModelStrings(
                decomposition="claude-opus-5-5",
                roles={ROLE: "claude-opus-5-5"},
                reviewers={ROLE: "claude-sonnet-5"},
            )
        }
    )


def test_a_unit_inconsistent_loop_gain_is_refused_by_the_gate_with_zero_review_tokens(
    tmp_path: Path,
) -> None:
    run = run_layout(tmp_path)
    store_root = run.run_dir / "store"
    # The decomposition writes an interface node first, as a real run's does
    # (``DecompositionSummary``/``Decomposed`` both require at least one).
    bus = node("iface.power_bus", kind="interface", quantities={"v": (12, "V")})
    head = graph(store_root, bus)
    cfg = _run_config()
    record = RunRecord(cfg, run.run_dir)
    record.start(
        [
            PlanEntry(
                subtask_id=SUBTASK,
                spec_path=f".physgate/specs/{SUBTASK}.md",
                assigned_role=ROLE,
                module_dir=MODULE_DIR,
            )
        ],
        call=DecompositionCall(session_id="decomp", usage=()),
        decomposed=DecompositionSummary(
            session_id="decomp",
            model="claude-opus-5-5",
            num_turns=1,
            subtasks=1,
            interface_nodes=("iface.power_bus",),
            spec_commit=head_of(run.repo, run.run_branch),
            head_revision=head,
        ),
    )
    record.close()

    reviewer = _PayingReviewer(model="claude-sonnet-5")
    dispatcher = GitDispatcher(run, proposals={1: {WRONG_GAIN["id"]: WRONG_GAIN}})
    keeper = StoreKeeper(run, store_root)
    loop = Loop(
        config=cfg,
        run_dir=run.run_dir,
        gate=default_registrations().gate,
        reviewers={ROLE: reviewer},
        dispatcher=DispatchPort(dispatcher),
        changes=GitChangeChecker(run, store_root, {SUBTASK: MODULE_DIR}),
        merger=GitMerger(run, removal_timeout_s=60.0),
        graph=keeper,
        sleep=lambda _: None,
    )
    try:
        loop.run()
    finally:
        loop.close()
        keeper.close()

    events = read_events(run.run_dir / "events.jsonl")
    gated = [e for e in events if isinstance(e, GateRan)]
    assert [(g.result.verdict, g.result.failing_check) for g in gated] == [("fail", "units")] * 3
    failing = [r for r in gated[0].result.checks if r.outcome == "fail"]
    assert {(r.name, r.scope) for r in failing} == {("units", "subtask")}
    assert [e for e in events if isinstance(e, ReviewRan)] == []
    assert reviewer.calls == 0
    assert TokenAccount.from_events(events).by_kind()["reviewer"].total() == 0
