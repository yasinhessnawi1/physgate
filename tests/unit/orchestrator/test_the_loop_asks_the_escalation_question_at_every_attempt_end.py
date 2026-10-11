"""The loop asks the escalation question at every attempt end that did not merge.

ARCH-131: "does this subtask go to the approval queue" is asked through one interface,
at the end of an attempt, and every call is recorded so a backend's behaviour can be
audited after the fact. The loop asks once at each attempt end that did not merge (a
rejection, a blocked review, a review with no verdict), records the decision with the
state it was asked about, and then follows the decision: the queue where it routes,
the next attempt where it does not.

The replay holds each decision line in its context: it must be due, about the state the
lines before it imply, by the backend the run names at its registered version, routed by
the rule, and for the rules binding, the rules' own answer. An escalation, or a next
attempt, needs its decision. A log written before the interface existed has no decision
lines and replays as if the rules had answered at each attempt end.
"""

from __future__ import annotations

import json
from collections.abc import Callable
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import pytest
from escalation_paths import STAND_INS, blocked_review, unavailable
from escalation_states import STAND_IN, register_stand_in
from loop_fakes import FakeReviewer, KilledError, Rig, plan

from physgate.orchestrator.escalation import (
    REGISTER,
    BackendAnswer,
    BackendRow,
    EscalationInterface,
    Question,
    Register,
)
from physgate.orchestrator.escalation_state import EscalationState, escalation_state
from physgate.orchestrator.events import (
    AttemptRejected,
    Escalated,
    EscalationDecided,
    Event,
    Merged,
    ReviewRan,
    ReviewUnavailable,
    read_events,
)
from physgate.orchestrator.exceptions import CorruptEventLogError
from physgate.orchestrator.queue import ApprovalQueue
from physgate.orchestrator.replay import replay


@dataclass
class Answering:
    """A backend that answers what it is told, records what it was shown, and may be killed."""

    answer: str = "no"
    confidence: float = 1.0
    kill_on: int | None = None
    shown: list[EscalationState] = field(default_factory=list)

    def decide(self, question: Question, state: EscalationState) -> BackendAnswer:
        self.shown.append(state)
        if len(self.shown) == self.kill_on:
            raise KilledError
        return BackendAnswer.model_validate({"answer": self.answer, "confidence": self.confidence})


class RulesAnswering(Answering):
    """The rules' answers, from a backend that records what it was shown and may be killed."""

    def decide(self, question: Question, state: EscalationState) -> BackendAnswer:
        from physgate.orchestrator.escalation import RulesBackend  # noqa: PLC0415

        self.shown.append(state)
        if len(self.shown) == self.kill_on:
            raise KilledError
        return RulesBackend().decide(question, state)


def under_rules(backend: Answering) -> EscalationInterface:
    """``backend`` asked as the run's rules binding, as the loop requires."""
    return EscalationInterface(backend, REGISTER.row("rules"))


def drive(rig: Rig, *subtasks: str) -> list[Event]:
    loop = rig.open()
    try:
        loop.start(plan(*subtasks))
        loop.run()
    finally:
        loop.close()
    return read_events(rig.run_dir / "events.jsonl")


def ends(events: list[Event]) -> list[AttemptRejected | ReviewRan | ReviewUnavailable]:
    """The lines that end an attempt without a merge, in order."""
    found: list[AttemptRejected | ReviewRan | ReviewUnavailable] = []
    for e in events:
        blocked = isinstance(e, ReviewRan) and e.result.verdict == "blocked"
        final = isinstance(e, ReviewUnavailable) and not e.retry
        if isinstance(e, AttemptRejected | ReviewRan | ReviewUnavailable) and (
            isinstance(e, AttemptRejected) or blocked or final
        ):
            found.append(e)
    return found


@pytest.mark.parametrize("name", sorted(STAND_INS))
def test_every_attempt_end_that_did_not_merge_is_decided_once_right_after_it(
    name: str, tmp_path: Path
) -> None:
    modes, build = STAND_INS[name]
    run_dir = build(tmp_path, modes[0])
    events = read_events(run_dir / "events.jsonl")
    decided = [e for e in events if isinstance(e, EscalationDecided)]
    ended = ends(events)
    assert len(decided) == len(ended)
    for end in ended:
        after = events[end.seq + 1]
        assert isinstance(after, EscalationDecided)
        assert (after.subtask_id, after.attempt) == (end.subtask_id, end.attempt)
    merged = {(e.subtask_id, e.attempt) for e in events if isinstance(e, Merged)}
    assert not merged & {(d.subtask_id, d.attempt) for d in decided}
    for d in decided:
        assert (d.decision.backend_id, d.decision.backend_version) == ("rules", "rules/1")
        assert d.decision.confidence == 1.0
        assert d.decision.latency_ms >= 0
        assert d.decision.routed is d.decision.forced
    escalated = [e for e in events if isinstance(e, Escalated)]
    assert len(escalated) == sum(1 for d in decided if d.decision.routed)


def test_the_backend_is_shown_the_state_the_line_records(tmp_path: Path) -> None:
    backend = RulesAnswering()
    rig = Rig(
        tmp_path,
        reviewer=FakeReviewer(verdicts=["fail"], results={2: blocked_review(2)}),
        escalation=under_rules(backend),
    )
    events = drive(rig, "s1")
    decided = [e for e in events if isinstance(e, EscalationDecided)]
    assert [d.state for d in decided] == backend.shown
    assert [s.attempt_end for s in backend.shown] == ["rejected", "review_blocked"]
    for d in decided:
        assert d.state == escalation_state(replay(events[: d.seq]), d.subtask_id)


@pytest.fixture
def stand_in_registered(monkeypatch: pytest.MonkeyPatch) -> None:
    """The register as the configuration and the replay read it, with the stand-in in it."""
    register_stand_in(monkeypatch)


def test_a_stand_in_cannot_pass_as_the_rules(tmp_path: Path) -> None:
    rig = Rig(
        tmp_path,
        reviewer=FakeReviewer(verdicts=["fail"]),
        escalation=under_rules(Answering(answer="no", confidence=0.5)),
    )
    loop = rig.open()
    loop.start(plan("s1"))
    with pytest.raises(ValueError, match="not the rules' own"):
        loop.run()
    loop.close()
    assert not [e for e in read_events(tmp_path / "events.jsonl") if e.kind == "escalation_decided"]


@pytest.mark.usefixtures("stand_in_registered")
def test_a_route_that_is_not_forced_is_recorded_and_followed(tmp_path: Path) -> None:
    rig = Rig(
        tmp_path,
        reviewer=FakeReviewer(verdicts=["fail"]),
        escalation=EscalationInterface(Answering(answer="no", confidence=0.5), STAND_IN),
        config_overrides={"escalation_backend": "stand_in"},
    )
    events = drive(rig, "s1")
    (decided,) = [e for e in events if isinstance(e, EscalationDecided)]
    assert (decided.decision.basis, decided.decision.forced) == ("floor", False)
    (escalated,) = [e for e in events if isinstance(e, Escalated)]
    assert escalated.seq > decided.seq
    assert replay(events).subtasks["s1"].status == "escalated"


@pytest.mark.parametrize("kill_on", [1, 2, 3])
def test_a_kill_between_the_attempt_end_and_its_decision_loses_nothing(
    kill_on: int, tmp_path: Path
) -> None:
    whole = drive(Rig(tmp_path / "whole", reviewer=FakeReviewer(verdicts=["fail"] * 3)), "s1")

    killed = Rig(
        tmp_path / "killed",
        reviewer=FakeReviewer(verdicts=["fail"] * 3),
        escalation=under_rules(RulesAnswering(kill_on=kill_on)),
    )
    loop = killed.open()
    loop.start(plan("s1"))
    with pytest.raises(KilledError):
        loop.run()
    loop.close()
    cut = read_events(killed.run_dir / "events.jsonl")
    assert isinstance(cut[-1], AttemptRejected)
    assert replay(cut).next_step().kind == "decide"
    # A fresh process, on the rules binding, carries on from the file.
    resumed = Rig(killed.run_dir, reviewer=FakeReviewer(verdicts=["fail"] * 3))
    loop = resumed.open()
    loop.run()
    loop.close()
    after = read_events(killed.run_dir / "events.jsonl")

    def shape(events: list[Event]) -> list[tuple[str, Any]]:
        return [(e.kind, getattr(e, "attempt", None)) for e in events if e.kind != "tokens_used"]

    assert shape(after) == shape(whole)
    # The resumed stand-in dispatcher numbers its sessions from one again, so the commit
    # ids and trajectory paths it hands out differ from the uninterrupted run's; every
    # other field of the item is the same.
    stand_in = {"ts", "artefact_diff", "trajectories"}
    queue = ApprovalQueue(killed.run_dir / "queue.jsonl")
    whole_queue = ApprovalQueue(tmp_path / "whole" / "queue.jsonl")
    assert [i.model_dump(exclude=stand_in) for i in queue.items()] == [
        i.model_dump(exclude=stand_in) for i in whole_queue.items()
    ]
    assert [len(i.trajectories) for i in queue.items()] == [3]


# -- the replay holds each decision line in its context ---------------------------------


def _lines(path: Path) -> list[dict[str, Any]]:
    return [json.loads(raw) for raw in path.read_text().splitlines()]


def _replayed(lines: list[dict[str, Any]], path: Path) -> None:
    for seq, line in enumerate(lines):
        line["seq"] = seq
    path.write_text("".join(json.dumps(line) + "\n" for line in lines))
    replay(read_events(path))


def _decision_index(lines: list[dict[str, Any]], nth: int = 0) -> int:
    return [i for i, line in enumerate(lines) if line["kind"] == "escalation_decided"][nth]


def _three_rejections(tmp_path: Path) -> list[dict[str, Any]]:
    drive(Rig(tmp_path / "run", reviewer=FakeReviewer(verdicts=["fail"] * 3)), "s1")
    return _lines(tmp_path / "run" / "events.jsonl")


def _tamper(
    tmp_path: Path, change: Callable[[list[dict[str, Any]]], None], *, refused: str
) -> None:
    lines = _three_rejections(tmp_path)
    _replayed([dict(line) for line in lines], tmp_path / "untouched.jsonl")  # it replays as is
    change(lines)
    with pytest.raises(CorruptEventLogError) as caught:
        _replayed(lines, tmp_path / "changed.jsonl")
    assert refused in caught.value.context["reason"]


def test_a_decision_about_a_state_the_log_does_not_imply_is_refused(tmp_path: Path) -> None:
    def change(lines: list[dict[str, Any]]) -> None:
        lines[_decision_index(lines)]["state"]["ended"]["repeats_previous"] = True

    _tamper(tmp_path, change, refused="a state the lines before it do not imply")


def test_a_decision_whose_forced_route_is_not_the_state_s_is_refused(tmp_path: Path) -> None:
    def change(lines: list[dict[str, Any]]) -> None:
        decision = lines[_decision_index(lines, 2)]["decision"]
        decision.update(forced=False, basis="answer")

    _tamper(tmp_path, change, refused="forced route is not the state's")


def test_a_rules_decision_whose_answer_is_not_the_rules_own_is_refused(tmp_path: Path) -> None:
    def change(lines: list[dict[str, Any]]) -> None:
        lines[_decision_index(lines, 2)]["decision"]["answer"] = "no"

    _tamper(tmp_path, change, refused="not the rules' own")


def test_a_decision_under_another_version_is_refused(tmp_path: Path) -> None:
    def change(lines: list[dict[str, Any]]) -> None:
        lines[_decision_index(lines)]["decision"]["backend_version"] = "rules/0"

    _tamper(tmp_path, change, refused="another backend version")


def test_a_decision_by_another_backend_than_the_run_names_is_refused(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    # A second backend that ships at its own version, so only the run's name can refuse it:
    # every other row in the register today has no version, which a version check refuses.
    other = BackendRow(
        name="other", status="ships", entry_condition="a test's", evidence=(), version="o/1"
    )
    monkeypatch.setattr(
        "physgate.orchestrator.replay.REGISTER", Register(rows=(*REGISTER.rows, other))
    )

    def change(lines: list[dict[str, Any]]) -> None:
        lines[_decision_index(lines)]["decision"].update(backend_id="other", backend_version="o/1")

    _tamper(tmp_path, change, refused="another backend than the one the run names")


def test_an_escalation_without_its_routed_decision_is_refused(tmp_path: Path) -> None:
    def change(lines: list[dict[str, Any]]) -> None:
        del lines[_decision_index(lines, 2)]

    _tamper(tmp_path, change, refused="an escalation cannot come")


def test_a_next_attempt_without_its_decision_is_refused(tmp_path: Path) -> None:
    def change(lines: list[dict[str, Any]]) -> None:
        del lines[_decision_index(lines, 0)]

    _tamper(tmp_path, change, refused="cannot start now")


def test_a_second_decision_on_one_attempt_end_is_refused(tmp_path: Path) -> None:
    def change(lines: list[dict[str, Any]]) -> None:
        at = _decision_index(lines, 0)
        lines.insert(at + 1, dict(lines[at]))

    _tamper(tmp_path, change, refused="an escalation decision cannot come")


def test_a_decision_line_in_a_log_whose_run_names_no_binding_is_refused(tmp_path: Path) -> None:
    def change(lines: list[dict[str, Any]]) -> None:
        del lines[0]["escalation_backend"]

    _tamper(tmp_path, change, refused="names no escalation backend")


# -- a log written before the interface ---------------------------------------------------


def _before_the_interface(lines: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """The log as the loop wrote it before the escalation interface existed."""
    old = [dict(line) for line in lines if line["kind"] != "escalation_decided"]
    old[0] = {k: v for k, v in old[0].items() if k != "escalation_backend"}
    return old


@pytest.mark.parametrize("name", sorted(STAND_INS))
def test_a_log_written_before_the_interface_replays_as_if_the_rules_answered(
    name: str, tmp_path: Path
) -> None:
    modes, build = STAND_INS[name]
    run_dir = build(tmp_path, modes[0])
    now = replay(read_events(run_dir / "events.jsonl"))
    old_path = tmp_path / "old.jsonl"
    old_lines = _before_the_interface(_lines(run_dir / "events.jsonl"))
    for seq, line in enumerate(old_lines):
        line["seq"] = seq
    old_path.write_text("".join(json.dumps(line) + "\n" for line in old_lines))
    old = replay(read_events(old_path))
    assert old.escalation_backend is None
    assert old.ledger == now.ledger
    assert {k: s.status for k, s in old.subtasks.items()} == {
        k: s.status for k, s in now.subtasks.items()
    }
    assert old.next_step() == now.next_step()
    assert [a.routed for s in old.subtasks.values() for a in s.attempts] == [
        a.routed for s in now.subtasks.values() for a in s.attempts
    ]


def test_an_unfinished_old_log_waits_on_the_rules_route_not_a_decision(tmp_path: Path) -> None:
    rig = Rig(tmp_path / "run", reviewer=FakeReviewer(unavailable={1: unavailable("refused")}))
    events = drive(rig, "s1")
    lines = _before_the_interface(_lines(rig.run_dir / "events.jsonl"))
    # Killed before its escalation line: the log ends where the escalation would come.
    cut = lines[: next(i for i, line in enumerate(lines) if line["kind"] == "escalated")]
    for seq, line in enumerate(cut):
        line["seq"] = seq
    path = tmp_path / "old.jsonl"
    path.write_text("".join(json.dumps(line) + "\n" for line in cut))
    assert replay(read_events(path)).next_step().kind == "escalate"
    assert any(isinstance(e, Escalated) for e in events)
