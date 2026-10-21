"""An approve on an ended run merges through the real loop, git, store and gate, and integrates.

ARCH-133's central acceptance case, end to end with no model: the physics gate's drive-power plan
run by the real loop with real git, the real design-state store and the real ``PhysicsGate`` in
``observe``, which merges what it checks. Two parts are stand-ins, labelled: the session, which
writes the plan's proposals as the scripted one does, and the reviewer, which reaches no verdict.
The run ends with the subtask in the queue and the integration call skipped as incomplete. A
person approves the item as the listing shows it; the run is resumed; the attempt's own commit is
merged into the run branch by git, its nodes are applied by the store, and the integration call
then runs on the run branch as it now stands.
"""

from __future__ import annotations

import subprocess
from pathlib import Path

from knowledge_fixture import build_fixture_library
from ui_rig import evaluation_rig
from ui_three_mode_rig import _drive, _start

from physgate.orchestrator.events import (
    DecisionTaken,
    IntegrationGateRan,
    IntegrationGateSkipped,
    Merged,
    WriteDone,
    read_events,
)
from physgate.orchestrator.exceptions import ReviewUnavailableError
from physgate.orchestrator.git import head_of
from physgate.orchestrator.protocols import Artefact, ReviewResult
from physgate.orchestrator.queue import (
    PersonDecision,
    ShownItem,
    read_queue,
    record_decision,
    statuses_now,
)


def _git(repo: Path, *args: str) -> str:
    return subprocess.run(
        ["git", "-C", str(repo), *args], check=True, capture_output=True, text=True
    ).stdout


class NoVerdict:
    """A reviewer that never reaches a verdict: the review a person stands in for."""

    def __init__(self, model: str) -> None:
        self.model = model

    def review(self, artefact: Artefact) -> ReviewResult:
        raise ReviewUnavailableError("no verdict", cause="invalid_verdict")


def test_an_ended_run_resumed_takes_its_approve_then_runs_the_integration_gate(
    tmp_path: Path,
) -> None:
    runs = tmp_path / "runs"
    library = build_fixture_library(tmp_path / "library")
    repo = evaluation_rig().target_repo(tmp_path / "target")
    cfg = _start(runs, "drive-act", repo, "observe", library, queue_decisions="act")
    reviewer = NoVerdict(cfg.models.reviewers["electrical"])
    assert _drive(runs, cfg, repo, reviewer=reviewer) == "done"
    run_dir = runs / "drive-act"
    events = read_events(run_dir / "events.jsonl")
    assert [type(e) for e in events if isinstance(e, IntegrationGateSkipped)] == [
        IntegrationGateSkipped
    ]
    assert not any(isinstance(e, Merged) for e in events)
    (item,) = read_queue(run_dir).open_items()
    assert item.source == "review_unavailable"
    assert item.consequence is not None and item.consequence.on_approve == "merge_attempt"
    commit = item.consequence.attempt_commit
    assert commit is not None

    view = read_queue(run_dir)
    record_decision(
        run_dir,
        item.item_id,
        person=PersonDecision(verb="approve", note=None),
        resolved_by="yasin",
        shown=ShownItem(
            item_sha256=view.digests[item.item_id],
            trajectories=statuses_now(run_dir, item.item_id),
        ),
    )
    assert _drive(runs, cfg, repo, reviewer=reviewer, resume=True) == "done"

    events = read_events(run_dir / "events.jsonl")
    (taken,) = [e for e in events if isinstance(e, DecisionTaken)]
    assert (taken.verb, taken.effect, taken.acts, taken.attempt_commit) == (
        "approve",
        "merge",
        True,
        commit,
    )
    (merged,) = [e for e in events if isinstance(e, Merged)]
    assert merged.attempt_commit == commit
    # The store applied the attempt's nodes, under its own refusals, after the decision.
    after = events.index(taken)
    applied = [e for e in events[after:] if isinstance(e, WriteDone)]
    assert applied and all(e.subtask_id == merged.subtask_id for e in applied)
    # Git merged exactly that commit into the run branch, with the approver named.
    branch = f"physgate/{cfg.run_id}/run"
    tip = head_of(repo, branch)
    assert tip == merged.merge_commit
    message = _git(repo, "log", "-1", "--format=%B", tip)
    assert 'Approved by "yasin" on queue item' in message
    parents = _git(repo, "log", "-1", "--format=%P", tip).split()
    assert commit in parents
    # The integration call ran, once, on the run branch as it now stands.
    ran = [e for e in events if isinstance(e, IntegrationGateRan)]
    assert len(ran) == 1 and ran[0].result.mode == "observe"
