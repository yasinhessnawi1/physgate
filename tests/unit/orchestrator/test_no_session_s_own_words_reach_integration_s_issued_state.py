"""No session's own words reach integration's issued state: it is state, never a message.

Integration's issued state is built from the run's record, and the record holds more than state:
every session's stream, every reviewer's finding and every repair instruction quoting one, and
each node's free text (a quantity's source, a node's requirements, its model, and the reason its
owner gives for leaving it unchanged). A canary planted in each of those is shown to be on the
record, or in the graph, and then found in no form in the document the session is handed and its
reviewer reads. The walk runs over the fake gate and over the real one, which reads the graph's
free text into its check records: the real gate's finding, which the document quotes, never
carries it.
"""

from __future__ import annotations

import secrets
from pathlib import Path
from typing import Any

import pytest
import test_a_pairs_contract_is_tested_once_both_its_modules_merged_and_blocks_nothing as runner
from loop_fakes import FakeDispatcher, FakeGate, FakeReviewer, usage

from physgate import roles
from physgate.gate.runner import PhysicsGate
from physgate.orchestrator.canaries import canary_seen
from physgate.orchestrator.events import (
    AttemptRejected,
    IntegrationGateRan,
    IntegrationStateIssued,
    read_events,
)
from physgate.orchestrator.ports import SessionReport, SessionRequest, SpawnHook
from physgate.orchestrator.protocols import (
    GateResult,
    IntegrationArtefact,
    MessageUsage,
    ReviewResult,
    ReviewVerdict,
    RunningGateMode,
)
from physgate.orchestrator.trajectory import seal
from physgate.state.store import JOURNAL_NAME

INTEG, DRIVE, FW, BUDGET, CLOSING = (
    runner.INTEG,
    runner.DRIVE,
    runner.FW,
    runner.BUDGET,
    runner.CLOSING,
)


@pytest.fixture(autouse=True)
def _sizing_registered(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setitem(roles.ROLES, roles.SIZING.name, roles.SIZING)


def canary() -> str:
    return secrets.token_hex(16)


class Streaming(FakeDispatcher):
    """A dispatcher whose every session's stream says a canary of its own."""

    def __init__(self, root: Path) -> None:
        super().__init__(trajectories=root)
        self.said: list[str] = []

    def run(self, request: SessionRequest, on_spawn: SpawnHook | None = None) -> SessionReport:
        report = super().run(request, on_spawn)
        assert report.trajectory is not None
        words = canary()
        self.said.append(words)
        path = Path(report.trajectory)
        path.write_bytes(
            b'{"type": "assistant", "message": {"content": [{"type": "text", "text": "'
            + f"I am sure of it: {words}".encode()
            + b'"}]}}\n'
            + path.read_bytes()
        )
        return report.model_copy(update={"trajectory_seal": seal(path.read_bytes())})


class Wordy(FakeReviewer):
    """A reviewer whose every finding carries a canary; the first review fails on one."""

    def __init__(self) -> None:
        super().__init__()
        self.said: list[str] = []

    def review(self, artefact: Any) -> ReviewResult:  # noqa: ANN401 - the artefact
        n = len(self.seen) + 1
        verdict: ReviewVerdict = "fail" if n == 1 else "pass"
        words = canary()
        self.said.append(words)
        self.results[n] = ReviewResult(
            verdict=verdict,
            finding=f"the reviewer's own words: {words}",
            reviewer_model=self.model,
            session_id=f"rev-{n}",
            usage=(MessageUsage(message_id=f"r{n}", usage=usage(7)),),
        )
        return super().review(artefact)


def free_text(node: dict[str, Any], words: dict[str, str]) -> dict[str, Any]:
    """``node`` with a canary in each of its free-text fields."""
    quantities = {
        name: {**quantity, "source": f"read from {words['source']}"}
        for name, quantity in node["quantities"].items()
    }
    return {
        **node,
        "quantities": quantities,
        "requirements": [f"must hold {words['requirements']}"],
        "model": f"models/{words['model']}.py",
    }


class RealSystemGate(FakeGate):
    """The real gate at system scope over the run's own store; the fake's per attempt."""

    def check_integration(
        self, artefact: IntegrationArtefact, *, mode: RunningGateMode
    ) -> GateResult:
        self.integrations.append(artefact)
        return PhysicsGate().check_integration(artefact, mode=mode)


def walk(tmp_path: Path, monkeypatch: pytest.MonkeyPatch, gate: FakeGate) -> dict[str, Any]:
    """A run with sizing's two passes and integration, a canary in every session's own words."""
    words = {field: canary() for field in ("source", "requirements", "model", "justified")}
    dispatcher = Streaming(tmp_path / "streams")
    reviewer = Wordy()
    rig = runner.rig_for(
        tmp_path / "run", gate_mode="observe", gate=gate, dispatcher=dispatcher, reviewer=reviewer
    )
    graph = rig.diff
    assert isinstance(graph, runner.StoreGraph)
    both = ("iface.drive", "iface.tilt")
    # Drive's motor constrains sizing's supply, and the closing pass rewrites the supply with its
    # value kept, its owner saying in its own words why it need not follow. Firmware's node
    # constrains the motor, which is never rewritten after it: a blocking failure, whose finding
    # the document quotes.
    supply = runner.node("budget.supply", "sizing", "iface.drive", v=12)
    kept = {
        **supply,
        "no_change_justified": {"drive.motor": f"left as it is: {words['justified']}"},
    }
    graph.writes.update(
        {
            BUDGET: [free_text(supply, words)],
            DRIVE: [
                free_text(
                    runner.node("drive.motor", "control", *both, "budget.supply", v=12, period=10),
                    words,
                )
            ],
            FW: [
                free_text(
                    runner.node("fw.main", "firmware", *both, "drive.motor", v=12, period=10), words
                )
            ],
            CLOSING: [free_text(kept, words)],
        }
    )
    loop = rig.open()
    runner.hooked(monkeypatch, loop, declared=(BUDGET, DRIVE, FW))
    runner.start(loop, sizing=True)
    loop.run()
    loop.close()
    events = read_events(rig.run_dir / "events.jsonl")
    (request,) = [r for r in dispatcher.requests if r.subtask_id == INTEG]
    (artefact,) = [a for a in reviewer.seen if a.subtask_id == INTEG]
    assert request.issued_state is not None and artefact.integration_state == request.issued_state
    return {
        "rig": rig,
        "events": events,
        "state": request.issued_state.text.encode("utf-8"),
        "session": frozenset(dispatcher.said),
        "review": frozenset(reviewer.said),
        "node": frozenset(words.values()),
        "journal": (graph.root / JOURNAL_NAME).read_bytes(),
        "streams": b"".join(p.read_bytes() for p in (tmp_path / "streams").rglob("*.jsonl")),
    }


def test_no_dispute_reason_or_trajectory_reaches_the_state(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    seen = walk(tmp_path, monkeypatch, FakeGate())
    log = (seen["rig"].run_dir / "events.jsonl").read_bytes()
    # Each canary is where a later session could be shown it, were it a message: every session's
    # stream, every reviewer's words on the record (sizing's first rejection among them, which its
    # next attempt was told), and each node's free text in the journal.
    for words in seen["session"]:
        assert canary_seen(seen["streams"], frozenset({words})) == words
    for words in seen["review"]:
        assert canary_seen(log, frozenset({words})) == words
    rejected = [e for e in seen["events"] if isinstance(e, AttemptRejected)]
    assert [e.subtask_id for e in rejected] == [BUDGET]
    for words in seen["node"]:
        assert canary_seen(seen["journal"], frozenset({words})) == words
    # And in no form in the issued state.
    every = seen["session"] | seen["review"] | seen["node"]
    assert canary_seen(seen["state"], every) is None
    # What it does hold: the record's state.
    text = seen["state"].decode()
    assert '### Pair 1: "drive" to "budget"' in text and "## System-scope result" in text


def test_the_real_gates_finding_carries_no_nodes_free_text_into_the_state(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    seen = walk(tmp_path, monkeypatch, RealSystemGate())
    (ran,) = [e for e in seen["events"] if isinstance(e, IntegrationGateRan)]
    # The real gate reads the graph's free text: the supply's owner's reason is in a check record,
    # and the run's system-scope result failed, so its finding is a check's own message.
    justified = next(
        w for w in seen["node"] if f"left as it is: {w}" in ran.result.model_dump_json()
    )
    assert any(justified in record.message for record in ran.result.checks)
    assert (ran.result.verdict, ran.result.failing_check) == ("fail", "propagation")
    # Its finding, failing check and quantities, which the document quotes, carry none of it.
    quoted = ran.result.model_dump_json(
        include={"verdict", "mode", "finding", "failing_check", "numeric_output", "quantities"}
    )
    assert canary_seen(quoted.encode(), seen["node"]) is None
    assert canary_seen(seen["state"], seen["node"] | seen["session"] | seen["review"]) is None
    assert [e for e in seen["events"] if isinstance(e, IntegrationStateIssued)]
