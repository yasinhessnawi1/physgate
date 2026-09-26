"""The registered physics gate inside the real loop: refused work is never reviewed.

A real repository, a real store, the real change check, the real loop and the
gate the ``physgate`` command registers; only the session is a stand-in that
writes node proposals into its worktree. Four wrong artefacts, each refused at
its own stage:

- a bare number, by the change check, before the gate (the store's schema);
- a current compared with a voltage, by the gate at subtask scope;
- a module whose consumers draw more than it supplies, at module scope;
- two modules that each balance but together exceed their battery, at the
  integration call.

In each, the reviewer is never invoked for the refused work and review tokens
on it are zero (ARCH-004, ARCH-031).
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest
from gate_fixtures import JOINT_POWER, POWER, UNITS, graph, node
from git_rig import DispatchPort, GitDispatcher, Reviewer, config, plan_entry, run_layout

from physgate.orchestrator.accounting import TokenAccount
from physgate.orchestrator.apply import GitChangeChecker, StoreKeeper
from physgate.orchestrator.cli import default_registrations
from physgate.orchestrator.events import (
    AttemptRejected,
    Escalated,
    GateRan,
    IntegrationEscalated,
    IntegrationGateRan,
    ReviewRan,
    read_events,
)
from physgate.orchestrator.git import head_of
from physgate.orchestrator.loop import Loop
from physgate.orchestrator.merge import GitMerger
from physgate.orchestrator.protocols import MessageUsage, ReviewResult, Usage
from physgate.orchestrator.record import DecompositionCall, DecompositionSummary, RunRecord

pytestmark = [pytest.mark.integration, pytest.mark.injected]


class _PayingReviewer(Reviewer):
    """A reviewer that reports the tokens a real one would, so a zero means it never ran."""

    def review(self, artefact: Any) -> ReviewResult:
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


def run_loop(
    root: Path, subtasks: dict[str, str], proposals: dict[int, dict[str, dict[str, Any]]]
) -> tuple[list[Any], _PayingReviewer, str]:
    """Start a decomposed run over ``subtasks`` (id to module directory) and drive it."""
    run = run_layout(root)
    store_root = run.run_dir / "store"
    # The decomposition writes the interface nodes first, as a real run's does.
    head = graph(store_root, node("iface.power_bus", kind="interface", quantities={"v": (12, "V")}))
    record = RunRecord(config(), run.run_dir)
    record.start(
        [plan_entry(s, d) for s, d in subtasks.items()],
        call=DecompositionCall(session_id="decomp", usage=()),
        decomposed=DecompositionSummary(
            session_id="decomp",
            model="claude-sonnet-5",
            num_turns=1,
            subtasks=len(subtasks),
            interface_nodes=("iface.power_bus",),
            spec_commit=head_of(run.repo, run.run_branch),
            head_revision=head,
        ),
    )
    record.close()
    reviewer = _PayingReviewer()
    keeper = StoreKeeper(run, store_root)
    loop = Loop(
        config=config(),
        run_dir=run.run_dir,
        gate=default_registrations().gate,
        reviewers={"electrical": reviewer},
        dispatcher=DispatchPort(GitDispatcher(run, proposals=proposals)),
        changes=GitChangeChecker(run, store_root, subtasks),
        merger=GitMerger(run, removal_timeout_s=60.0),
        graph=keeper,
        sleep=lambda _: None,
    )
    try:
        step = loop.run().kind
    finally:
        loop.close()
        keeper.close()
    return read_events(run.run_dir / "events.jsonl"), reviewer, step


def by_id(payloads: tuple[dict[str, Any], ...]) -> dict[str, dict[str, Any]]:
    return {p["id"]: p for p in payloads}


def reviewer_tokens(events: list[Any]) -> int:
    return TokenAccount.from_events(events).by_kind()["reviewer"].total()


def test_a_bare_number_is_refused_at_the_change_check_before_the_gate(tmp_path: Path) -> None:
    bare = dict(UNITS[1])
    bare["quantities"] = {
        "stall_current": {"value": 2.4, "source": "datasheet", "written_by": "electrical"}
    }
    events, reviewer, step = run_loop(tmp_path, {"s1": "modules/power"}, {1: {bare["id"]: bare}})
    rejected = [e for e in events if isinstance(e, AttemptRejected)]
    assert [r.finding.source for r in rejected] == ["proposal"] * 3
    assert "not a valid node" in rejected[0].finding.text
    assert [e for e in events if isinstance(e, GateRan | ReviewRan)] == []
    assert reviewer.calls == 0 and reviewer_tokens(events) == 0
    assert [e.subtask_id for e in events if isinstance(e, Escalated)] == ["s1"]


def test_a_current_compared_with_a_voltage_is_refused_by_the_gate_at_subtask_scope(
    tmp_path: Path,
) -> None:
    events, reviewer, step = run_loop(tmp_path, {"s1": "modules/power"}, {1: by_id(UNITS)})
    gated = [e for e in events if isinstance(e, GateRan)]
    assert [(g.result.verdict, g.result.failing_check) for g in gated] == [("fail", "units")] * 3
    failing = [r for r in gated[0].result.checks if r.outcome == "fail"]
    assert {(r.name, r.scope) for r in failing} == {("units", "subtask")}
    assert [e for e in events if isinstance(e, ReviewRan)] == []
    assert reviewer.calls == 0 and reviewer_tokens(events) == 0
    assert step == "done" and any(isinstance(e, Escalated) for e in events)


def test_an_unbalanced_module_is_refused_at_module_scope(tmp_path: Path) -> None:
    events, reviewer, step = run_loop(tmp_path, {"s1": "modules/power"}, {1: by_id(POWER)})
    gated = [e for e in events if isinstance(e, GateRan)]
    assert [(g.result.verdict, g.result.failing_check) for g in gated] == [("fail", "power")] * 3
    failing = [r for r in gated[0].result.checks if r.outcome == "fail"]
    assert {(r.name, r.scope) for r in failing} == {("power", "module")}
    assert [e for e in events if isinstance(e, ReviewRan)] == []
    assert reviewer.calls == 0 and reviewer_tokens(events) == 0


def test_a_joint_power_deficit_is_refused_at_the_integration_call(tmp_path: Path) -> None:
    battery, drive, control = JOINT_POWER
    events, reviewer, step = run_loop(
        tmp_path,
        {"s1": "modules/power", "s2": "modules/control"},
        {1: by_id((battery, drive)), 2: by_id((control,))},
    )
    assert step == "escalated"
    (integrated,) = [e for e in events if isinstance(e, IntegrationGateRan)]
    assert (integrated.result.verdict, integrated.result.failing_check) == ("fail", "power")
    (escalated,) = [e for e in events if isinstance(e, IntegrationEscalated)]
    reviews = [e for e in events if isinstance(e, ReviewRan)]
    # The two subtasks passed the gate and were reviewed; the integrated design was not.
    assert len(reviews) == 2 and all(r.seq < integrated.seq for r in reviews)
    assert reviewer.calls == 2 and reviewer_tokens(events) == 2 * 49
    assert escalated.seq > integrated.seq
