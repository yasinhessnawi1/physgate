"""No session's own words reach integration's issued state: it is state, never a message.

Integration's issued state is built from the run's record, and the record holds more than state:
every session's stream, every reviewer's finding and every repair instruction quoting one, each
node's free text (a quantity's source, a node's requirements, its model, the reason its owner gives
for leaving it unchanged), and what sessions name things: a unit and a quantity's name, which no
check holds to a pattern at write, and a node id, which the store holds to its pattern and bound.
A canary planted in each is shown to be on the record, or in the graph, and then found in no form
in the document the session is handed and its reviewer reads; a node id only whole, as the
identifier it is. The walk runs over the fake gate and over the real one, whose finding and check
records quote units, quantity names and a node's free text: the document copies none of them.
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
from physgate.gate.units import UnitRefusedError, parse
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
from physgate.state.schema import NODE_ID_MAX_LENGTH, NODE_ID_PATTERN
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


def walk(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    gate: FakeGate,
    *,
    identifiers: bool = False,
    short: bool = False,
) -> dict[str, Any]:
    """A run with sizing's two passes and integration, a canary in every session's own words.

    With ``identifiers``, firmware's node also carries a canary in a unit and in a quantity's
    name, each far longer than any identifier (or, with ``short``, each the canary alone, as
    short as an identifier), and firmware writes a node whose id carries one, as long as the
    store's id pattern allows.
    """
    words = {field: canary() for field in ("source", "requirements", "model", "justified")}
    said = {field: canary() for field in ("unit", "name", "node_id")}
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
    long_id = f"c{said['node_id']}." + "z" * (NODE_ID_MAX_LENGTH - 2 - len(said["node_id"]))
    if identifiers:
        fw = graph.writes[FW][0]
        # Read by the clause and the gate, and refused by both.
        unit = said["unit"] + ("" if short else "_" * 967)
        with pytest.raises(UnitRefusedError):
            parse(1, unit)
        fw["quantities"]["v"]["unit"] = unit
        name = said["name"] + ("" if short else "_" + "q" * 967)
        fw["quantities"][name] = {
            "value": 1,
            "unit": "V",
            "source": "brief",
            "written_by": "firmware",
        }
        graph.writes[FW].append(runner.node(long_id, "firmware", "iface.tilt", period=10))
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
        "said": said,
        "long_id": long_id,
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
    # The document copies none of the gate's words, and none of them reaches it.
    quoted = ran.result.model_dump_json(
        include={"verdict", "mode", "finding", "failing_check", "numeric_output", "quantities"}
    )
    assert canary_seen(quoted.encode(), seen["node"]) is None
    assert canary_seen(seen["state"], seen["node"] | seen["session"] | seen["review"]) is None
    assert [e for e in seen["events"] if isinstance(e, IntegrationStateIssued)]


@pytest.mark.parametrize("size", ["long", "short"], ids=["far longer", "as short as an id"])
@pytest.mark.parametrize("which", ["fake", "real"], ids=["the fake gate", "the real gate"])
def test_a_unit_or_a_quantity_name_reaches_the_state_in_no_form_and_a_node_id_only_whole(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, which: str, size: str
) -> None:
    gate = FakeGate() if which == "fake" else RealSystemGate()
    seen = walk(tmp_path, monkeypatch, gate, identifiers=True, short=size == "short")
    said, long_id = seen["said"], seen["long_id"]
    # Each is on the record: in the graph, and, held to nothing at write, a unit and a quantity's
    # name are what a clause's reason and a gate's message quote.
    for words in said.values():
        assert canary_seen(seen["journal"], frozenset({words})) == words
    log = (seen["rig"].run_dir / "events.jsonl").read_bytes()
    assert canary_seen(log, frozenset({said["unit"]})) == said["unit"]
    if which == "real":
        (ran,) = [e for e in seen["events"] if isinstance(e, IntegrationGateRan)]
        assert canary_seen(ran.result.model_dump_json().encode(), frozenset({said["name"]}))
    # Neither reaches the document, in any form.
    assert canary_seen(seen["state"], frozenset({said["unit"], said["name"]})) is None
    # A node id is held at every write to the store's pattern and bound, so it may be named, and
    # only whole, as the identifier it is.
    assert NODE_ID_PATTERN.fullmatch(long_id) and len(long_id) == NODE_ID_MAX_LENGTH
    text = seen["state"].decode()
    assert text.count(f'"{long_id}"') >= 1
    assert text.count(said["node_id"]) == text.count(f'"{long_id}"')
