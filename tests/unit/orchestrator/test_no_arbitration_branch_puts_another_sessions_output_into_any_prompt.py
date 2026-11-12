"""No branch of the arbitration stage puts one session's words where another session reads them.

A dispute's reason is the disputing session's text, and sizing's stream, and the ``source`` and
``written_by`` it wrote into the graph, are sizing's, and so is a unit sizing spelt as a bare word,
which the change check and the replay take when the dispute names the same word. Each carries a
canary here, and every
branch of the stage is driven by the loop: the gate's refusal, sizing's value under each gate
mode, and the queue on a repeat, on the last attempt and on the fix a person ordered. No canary
reaches a later session's prompt, a reviewer's artefact, integration's issued state, an
escalation state, a rejection's finding or repair instruction, or a queue item; through the
operator's routes, the reason is served only inside its own ``dispute_recorded`` line. Each
branch dispatches exactly the sessions its plan needs (ARCH-040).

A process killed at any line of the stage and resumed ends where an unkilled one does.
"""

from __future__ import annotations

import json
import sys
from collections.abc import Callable
from pathlib import Path
from typing import Any

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent))
sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
from arbitration_runs import (  # noqa: E402
    BUS,
    CANARIES,
    CLOSING,
    RAIL,
    TWO,
    KilledByRowError,
    bus,
    dispute,
    driven,
    events_of,
    refusal,
    resume,
    rig_of,
    run,
)
from test_a_blocked_review_is_a_review_that_goes_to_a_person import blocked_review  # noqa: E402
from test_a_person_chooses_a_position_only_on_an_arbitration_item import chose  # noqa: E402
from test_a_queue_decision_acts_at_a_boundary import decide  # noqa: E402
from ui_rig import context_over, fake_ui, serving  # noqa: E402

from physgate import roles  # noqa: E402
from physgate.evaluation.observe.sequence import decisions  # noqa: E402
from physgate.orchestrator.dispatch import role_prompt  # noqa: E402
from physgate.orchestrator.events import (  # noqa: E402
    ArbitrationDecided,
    AttemptRejected,
    Escalated,
    EscalationDecided,
    Event,
    StageEntered,
)
from physgate.orchestrator.integration_state import issued_state  # noqa: E402
from physgate.orchestrator.queue import ApprovalQueue, read_queue  # noqa: E402
from physgate.orchestrator.replay import replay  # noqa: E402
from physgate.reviewers.packet import person_order_text  # noqa: E402


@pytest.fixture(autouse=True)
def _sizing_registered(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setitem(roles.ROLES, roles.SIZING.name, roles.SIZING)


#: A unit only the spelling guard holds: a word, which the gate's parser refuses.
UNIT = "UNITCANARY"
WORDED = (dispute("peak_current", 5, UNIT), dispute("supply_voltage", 24, UNIT))


def _worded(rig: Any) -> Any:  # noqa: ANN401 - the rig
    """Sizing writes the bus in a unit word, with the gate off; the domain disputes in that word.

    The plan has sizing's closing pass, which waits for the item: a value in a unit word is never
    carried to it, so choosing the domain's records only.
    """
    rig.diff.writes["z0"] = [bus(24, 3, unit=UNIT)]
    run(rig, plan=CLOSING)
    return rig


def _choosing(position: str, *, times: int = 1, plan: Any = None) -> Callable[[Any], Any]:  # noqa: ANN401
    """The run to its item, then a person's choice of ``position`` on each of ``times`` items."""

    def drive(rig: Any) -> Any:  # noqa: ANN401 - the rig
        run(rig, plan=plan)
        for _ in range(times):
            chose(rig.run_dir, position, "keep it")
            resume(rig)
        return rig

    return drive


def _fixed(rig: Any) -> Any:  # noqa: ANN401 - the rig
    """A person orders the fix after attempt 1's review blocked; the fix disputes."""
    rig.reviewer.results[2] = blocked_review()
    run(rig)
    decide(rig.run_dir, "reject", "the bus needs a margin the specification gives")
    resume(rig)
    return rig


#: Each branch: how its rig is made and driven, and the levels its attempts are ruled at.
BRANCHES: dict[str, tuple[dict[str, Any], Callable[[Any], Any] | None, list[tuple[int, str]]]] = {
    "L1 on, then L2, then L3 on the last attempt": (
        {"gate": ["fail"]}, None,
        [(1, "gate"), (1, "gate"), (2, "sizing"), (2, "sizing"), (3, "queue"), (3, "queue")],
    ),
    "L2 on, then L3 on a repeat": (
        {}, None, [(1, "sizing"), (1, "sizing"), (2, "queue"), (2, "queue")],
    ),
    "L2 observe, failing, then L3": (
        {"mode": "observe", "gate": ["fail"]}, None,
        [(1, "sizing"), (1, "sizing"), (2, "queue"), (2, "queue")],
    ),
    "L2 off, then L3": (
        {"mode": "off"}, None, [(1, "sizing"), (1, "sizing"), (2, "queue"), (2, "queue")],
    ),
    "L3 on the fix": ({"script": [(), (RAIL, BUS)]}, _fixed, [(2, "queue"), (2, "queue")]),
    "L2 off, then L3, in a unit word": (
        {"mode": "off", "script": [WORDED]}, _worded,
        [(1, "sizing"), (1, "sizing"), (2, "queue"), (2, "queue")],
    ),
    "L3, sizing chosen: the next attempt": (
        {"script": [TWO, TWO, ()]}, _choosing("sizing"),
        [(1, "sizing"), (1, "sizing"), (2, "queue"), (2, "queue")],
    ),
    "L3 on the last attempt, sizing chosen: the fix": (
        {"gate": ["fail"], "script": [TWO, TWO, TWO, ()]}, _choosing("sizing"),
        [(1, "gate"), (1, "gate"), (2, "sizing"), (2, "sizing"), (3, "queue"), (3, "queue")],
    ),
    "L3 on the fix, sizing chosen: the end": (
        {"gate": ["fail"]}, _choosing("sizing", times=2),
        [(1, "gate"), (1, "gate"), (2, "sizing"), (2, "sizing"), (3, "queue"), (3, "queue"),
         (4, "queue"), (4, "queue")],
    ),
    "L3, the domain chosen: the closing pass, the return, the merge": (
        {}, _choosing("domain", plan=CLOSING),
        [(1, "sizing"), (1, "sizing"), (2, "queue"), (2, "queue"), (2, "person"), (2, "person")],
    ),
}  # fmt: skip
#: The sessions each branch's plan needs: sizing's one, and one per attempt of the domain's.
DISPATCHED = {
    "L1 on, then L2, then L3 on the last attempt": 4,
    "L2 on, then L3 on a repeat": 3,
    "L2 observe, failing, then L3": 3,
    "L2 off, then L3": 3,
    "L3 on the fix": 3,
    "L2 off, then L3, in a unit word": 3,
    "L3, sizing chosen: the next attempt": 4,
    "L3 on the last attempt, sizing chosen: the fix": 5,
    "L3 on the fix, sizing chosen: the end": 5,
    "L3, the domain chosen: the closing pass, the return, the merge": 4,
}


def _clean(where: str, text: str) -> None:
    found = [c for c in (*CANARIES, UNIT) if c in text]
    assert not found, (where, found)


def _routes(run_dir: Path, base: Path) -> dict[str, bytes]:
    served: dict[str, bytes] = {}
    with serving(context_over(run_dir.parent, ui_root=fake_ui(base / "checkout"))) as live:
        for route in ("events", "queue", "status", "decisions", "queue/items/0"):
            status, _, body = live.request("GET", f"/api/runs/0/{run_dir.name}/{route}")
            assert status == 200, (route, body[:300])
            served[route] = body
    return served


@pytest.mark.parametrize("branch", list(BRANCHES))
def test_no_arbitration_branch_puts_another_sessions_output_into_any_prompt(
    tmp_path: Path, branch: str
) -> None:
    rigged, drive, ruled = BRANCHES[branch]
    rig = rig_of(tmp_path / "runs" / "run", **rigged)
    drive(rig) if drive is not None else run(rig)
    events = events_of(rig)
    assert [(e.attempt, e.level) for e in events if isinstance(e, ArbitrationDecided)] == ruled
    assert len(rig.dispatcher.requests) == DISPATCHED[branch]
    assert refusal(events) is None
    # Every session's prompt, every reviewer's artefact, integration's issued state.
    for request in rig.dispatcher.requests:
        _clean(f"prompt of {request.subtask_id}/{request.attempt}", role_prompt(request))
    for artefact in rig.reviewer.seen:
        _clean(f"artefact of {artefact.subtask_id}", artefact.model_dump_json())
        if artefact.ordered_by_person is not None:
            told = person_order_text(artefact.ordered_by_person).decode()
            _clean(f"person_order.md of {artefact.subtask_id}", told)
    _clean("integration_state.md", issued_state(replay(events)).decode())
    for event in events:
        if isinstance(event, EscalationDecided):
            _clean("escalation state", event.state.model_dump_json())
        if isinstance(event, AttemptRejected):
            _clean("rejection", event.finding.model_dump_json())
    # Every item the run listed, decided or open.
    items = read_queue(rig.run_dir).items
    assert [i.source for i in items][-1:] == ["arbitration"]
    for item in items:
        _clean(f"item {item.item_id}", item.model_dump_json())
    if "unit word" in branch:
        assert items[-1].consequence is not None
        assert items[-1].consequence.on_choose == {"sizing": "retry", "domain": "record_only"}
    # The operator's routes: the reason only inside its own line.
    served = _routes(rig.run_dir, tmp_path)
    for route in ("queue", "status", "decisions", "queue/items/0"):
        _clean(f"/{route}", served[route].decode())
    lines = [json.loads(raw) for raw in (rig.run_dir / "events.jsonl").read_bytes().splitlines()]
    for line in lines:
        text = json.dumps(line)
        if line["kind"] == "dispute_recorded":
            # The dispute's own words: its reason, and the unit it names.
            blank = {**line, "reason": "", "position": {**line["position"], "unit": ""}}
            _clean("a dispute's line but its reason and unit", json.dumps(blank))
        elif line["kind"] == "arbitration_decided":
            # The held value says what the graph held: the unit as sizing spelt it, and the source
            # and author sizing wrote beside it (never rendered); no other field of the line
            # carries a session's words.
            position = {**line["held"]["position"], "unit": ""}
            held = {**line["held"], "position": position, "source": "", "written_by": ""}
            _clean(
                "a ruling's line but its held source and author", json.dumps({**line, "held": held})
            )
        else:
            _clean(f"the {line['kind']} line", text)
    _clean("decisions()", json.dumps(decisions(lines)))
    assert b"REASON-CANARY" in served["events"]


# --- the kill points ------------------------------------------------------------------------------


def _nth(kind: type[Any], n: int = 1, **fields: Any) -> Callable[[Event], bool]:  # noqa: ANN401
    seen: list[Event] = []

    def hit(line: Event) -> bool:
        if isinstance(line, kind) and all(getattr(line, k) == v for k, v in fields.items()):
            seen.append(line)
        return len(seen) == n and seen[-1] is line

    return hit


KILLS: dict[str, tuple[dict[str, Any], Callable[[], Callable[[Event], bool]] | str]] = {
    "K1 gate line, first ruling": ({}, lambda: _nth(ArbitrationDecided, 1)),
    "K2 between two rulings": ({}, lambda: _nth(ArbitrationDecided, 2)),
    "K3 last sizing ruling, decide": (
        {}, lambda: _nth(StageEntered, stage="decide", subtask_id="s1"),
    ),
    "K4 decide, rejection": ({}, lambda: _nth(AttemptRejected, 1)),
    "K5 last queue ruling, decision": ({}, lambda: _nth(EscalationDecided, 2)),
    "K6 decision, item": ({}, "item"),
    "K7 item, escalated": ({}, lambda: _nth(Escalated, 1)),
    "L1 gate ruling, rejection": ({"gate": ["fail"]}, lambda: _nth(AttemptRejected, 1)),
}  # fmt: skip


def _outcome(rig: Any) -> tuple[Any, ...]:  # noqa: ANN401 - the rig
    events = events_of(rig)
    assert refusal(events) is None
    last: dict[int, list[str]] = {}
    for e in events:
        if isinstance(e, StageEntered) and e.subtask_id == "s1" and e.stage == "gate":
            last[e.attempt] = []
        if isinstance(e, ArbitrationDecided):
            last.setdefault(e.attempt, []).append(e.level)
    rejected = [(e.attempt, e.finding.source, e.finding.text) for e in events
                if isinstance(e, AttemptRejected)]  # fmt: skip
    items = [(i.source, i.triggering_finding, i.quantities, i.decision_required)
             for i in read_queue(rig.run_dir).open_items()]  # fmt: skip
    escalated = [e.subtask_id for e in events if isinstance(e, Escalated)]
    return last, rejected, items, escalated, len(rig.dispatcher.requests)


@pytest.mark.parametrize("kill", list(KILLS))
def test_a_process_killed_anywhere_in_the_stage_resumes_to_the_same_end(
    tmp_path: Path, kill: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    rigged, at = KILLS[kill]
    whole = rig_of(tmp_path / "whole", **rigged)
    driven(whole)
    assert any(_outcome(whole)[0].values()), "the run rules no dispute"
    killed = rig_of(tmp_path / "killed", **rigged)
    if at == "item":
        add = ApprovalQueue.add
        died: list[bool] = []

        def dies(self: ApprovalQueue, item: Any) -> None:  # noqa: ANN401 - the item
            if not died:
                died.append(True)
                raise KilledByRowError
            add(self, item)

        monkeypatch.setattr(ApprovalQueue, "add", dies)
        with pytest.raises(KilledByRowError):
            run(killed)
        assert died
    else:
        assert callable(at)
        assert run(killed, kill=at()) == "killed"
    assert refusal(events_of(killed)) is None
    driven(killed, resume)
    assert _outcome(killed) == _outcome(whole)
