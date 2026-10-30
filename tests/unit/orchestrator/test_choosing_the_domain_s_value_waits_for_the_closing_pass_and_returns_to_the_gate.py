"""Choosing the domain's value resizes: the domain waits, sizing's closing pass writes the value.

On an arbitration item, choosing the domain's value acts only while the plan's closing sizing pass
has not started and every value it would carry is in a unit the gate's parser takes. Then the
domain subtask waits; the closing pass is ordered, by code, to write each chosen ``{value, unit}``
into its node, told under a fixed label with the item it was chosen on and never the dispute's
reason; and once the closing pass merges, the domain's disputed attempt returns to the gate: its
reading, change check, rulings and review run again with no new session and no attempt spent. A
dispute whose value the graph now holds as chosen is ruled at the level ``person`` and stands.

In a run that acts on decisions the closing pass waits for every open arbitration item, a held
choice included; in one that records only, it never waits. If the closing pass ends without a
merge, the waiting subtask ends rejected, naming the item. A process killed anywhere on the way
resumes to the same end, and replay refuses a return or an end the record does not give.
"""

from __future__ import annotations

import json
import sys
from collections.abc import Callable
from pathlib import Path
from typing import Any

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent))
import arbitration_runs  # noqa: E402
from arbitration_runs import (  # noqa: E402
    BIG,
    CANARIES,
    CLOSING,
    CLOSING_PASS,
    WORDED_DISPUTES,
    JournalGraph,
    KilledByRowError,
    bus,
    driven,
    entry,
    events_of,
    refusal,
    resume,
    rig_of,
    run,
)
from loop_fakes import FakeReviewer, Rig  # noqa: E402
from test_a_person_chooses_a_position_only_on_an_arbitration_item import (  # noqa: E402
    chose,
    one,
    taken,
)
from test_a_queue_decision_acts_at_a_boundary import _layer, decide  # noqa: E402

from physgate import roles  # noqa: E402
from physgate.evaluation.observe.sequence import decisions  # noqa: E402
from physgate.orchestrator import decisions as decisions_module  # noqa: E402
from physgate.orchestrator.dispatch import role_prompt  # noqa: E402
from physgate.orchestrator.events import (  # noqa: E402
    ArbitrationDecided,
    DecisionTaken,
    Event,
    Incident,
    Merged,
    ReviewRan,
    SessionEnded,
    StageEntered,
    SubtaskRejected,
    parse_events,
)
from physgate.orchestrator.exceptions import CorruptEventLogError  # noqa: E402
from physgate.orchestrator.loop import Loop  # noqa: E402
from physgate.orchestrator.queue import read_queue  # noqa: E402
from physgate.orchestrator.replay import replay  # noqa: E402
from physgate.orchestrator.run_config import ModelStrings  # noqa: E402
from physgate.reviewers.packet import person_order_text  # noqa: E402
from physgate.roles.integration import INTEGRATION  # noqa: E402


@pytest.fixture(autouse=True)
def _sizing_registered(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setitem(roles.ROLES, roles.SIZING.name, roles.SIZING)


ITEM = "run-1-s1"
#: The two values the domain disputed with, as the closing pass is ordered to write them.
VALUES = (
    f'Node "sizing.bus", quantity "peak_current": 5 "ampere", chosen on queue item "{ITEM}" for '
    'subtask "s1".\n'
    f'Node "sizing.bus", quantity "supply_voltage": 24 "volt", chosen on queue item "{ITEM}" for '
    'subtask "s1".'
)
HEAD = (
    "A person chose a domain's value over sizing's for 2 quantities of cross nodes. Each is a "
    "fixed input of this pass: write it into its node as given, value and unit. The domain's work "
    "waits for this pass to merge, and is judged again against the graph it leaves."
)
ORDER = (
    f"{HEAD}\n\nThe values chosen:\n<<<\n{VALUES}\n>>>\n"
    "The specification as issued otherwise still governs."
)
OPENING = (
    "This attempt is sizing's closing pass, ordered to write the values a person chose on queue "
    f"item {ITEM}."
)


def _clean(where: str, text: str) -> None:
    found = [c for c in CANARIES if c in text]
    assert not found, (where, found)


def _graph(rig: Rig) -> JournalGraph:
    graph = rig.diff
    assert isinstance(graph, JournalGraph)
    return graph


def _lines(events: list[Event]) -> list[dict[str, Any]]:
    return [json.loads(e.model_dump_json()) for e in events]


def _kinds(rig: Rig) -> list[str]:
    raw = (rig.run_dir / "events.jsonl").read_bytes().splitlines()
    return [json.loads(line)["kind"] for line in raw]


def _first(lines: list[dict[str, Any]], **fields: Any) -> int:  # noqa: ANN401
    """Where the first line holding ``fields`` is, asserted to be there."""
    at = [i for i, ln in enumerate(lines) if all(ln.get(k) == v for k, v in fields.items())]
    assert at, fields
    return at[0]


def _refusal_of(lines: list[dict[str, Any]]) -> str | None:
    """Why ``lines``, renumbered, do not replay; ``None`` when they do."""
    data = b"".join(json.dumps(line | {"seq": i}).encode() + b"\n" for i, line in enumerate(lines))
    try:
        replay(parse_events(data, log="events.jsonl"))
    except CorruptEventLogError as exc:
        return str(exc.context.get("reason", exc))
    except Exception as exc:  # noqa: BLE001 - any other escape is a refusal no rule gave
        return f"raised {type(exc).__name__}: {exc}"
    return None


def at_the_item(
    tmp_path: Path,
    *,
    plan: list[Any] | None = None,
    **rigged: Any,  # noqa: ANN401
) -> Rig:
    """Attempt 1 is ruled for sizing, attempt 2's repeat goes to a person; the closing pass next."""
    rig = rig_of(tmp_path / "run", **rigged)
    driven(rig, lambda r: run(r, plan=plan or CLOSING))
    return rig


def _item(rig: Rig) -> Any:  # noqa: ANN401 - the queue's model
    return one(read_queue(rig.run_dir).open_items())


def resized(tmp_path: Path, **rigged: Any) -> Rig:  # noqa: ANN401
    """A person chooses the domain's value on the item; the run is driven to its end."""
    rig = at_the_item(tmp_path, **rigged)
    chose(rig.run_dir, "domain")
    driven(rig, resume)
    return rig


def _sessions(rig: Rig) -> list[tuple[str, int]]:
    return [(r.subtask_id, r.attempt) for r in rig.dispatcher.requests]


# --- what the item says, and the wait ------------------------------------------------------------


def test_the_closing_pass_waits_for_an_open_dispute_item_only_in_a_run_that_acts(
    tmp_path: Path,
) -> None:
    acts = rig_of(tmp_path / "acts")
    assert run(acts, plan=CLOSING) == "wait"
    assert _sessions(acts) == [("z0", 1), ("s1", 1), ("s1", 2)]
    assert _item(acts).consequence.on_choose == {"sizing": "retry", "domain": "resize"}
    started = json.loads((acts.run_dir / "events.jsonl").read_bytes().splitlines()[0])
    assert started["queue_decisions"] == "act"
    # The closing pass's first attempt is refused on replay while the item is open.
    lines = _lines(events_of(acts))
    assert _refusal_of(lines) is None
    first_resolve = lines[_first(lines, stage="resolve")]
    resolve = first_resolve | {"subtask_id": "zc", "attempt": 1}
    said = _refusal_of([*lines, resolve])
    assert said is not None and "waits" in said, said
    # A run that records only never waits: the closing pass runs, and no line names a choice.
    records = rig_of(tmp_path / "records")
    records.config_overrides["queue_decisions"] = "record"
    run(records, plan=CLOSING)
    assert _sessions(records) == [("z0", 1), ("s1", 1), ("s1", 2), ("zc", 1)]
    first = json.loads((records.run_dir / "events.jsonl").read_bytes().splitlines()[0])
    assert "queue_decisions" not in first
    assert refusal(events_of(records)) is None


@pytest.mark.parametrize(
    ("worded", "domain"), [(False, "resize"), (True, "record_only")], ids=["parses", "a unit word"]
)
def test_choosing_the_domain_resizes_only_when_every_chosen_unit_parses(
    tmp_path: Path, worded: bool, domain: str
) -> None:
    rigged: dict[str, Any] = {"mode": "off", "script": [WORDED_DISPUTES]} if worded else {}
    rig = rig_of(tmp_path / "run", **rigged)
    if worded:
        _graph(rig).writes["z0"] = [bus(24, 3, unit="UNITCANARY")]
    driven(rig, lambda r: run(r, plan=CLOSING))
    assert _item(rig).consequence.on_choose == {"sizing": "retry", "domain": domain}


def test_choosing_the_domain_records_only_with_no_closing_pass_planned(
    tmp_path: Path,
) -> None:
    # No closing pass in the plan: the domain's choice records only, as it always did.
    plain = rig_of(tmp_path / "plain")
    driven(plain)
    assert _item(plain).consequence.on_choose == {"sizing": "retry", "domain": "record_only"}


# --- the closing pass's order --------------------------------------------------------------------


def test_choosing_the_domain_dispatches_one_sizing_attempt_with_the_persons_value_as_fixed_input(
    tmp_path: Path,
) -> None:
    rig = resized(tmp_path)
    events = events_of(rig)
    assert refusal(events) is None
    line = one(taken(events))
    assert (line.verb, line.position, line.effect, line.acts, line.why_not) == (
        "choose", "domain", "resize", True, None,
    )  # fmt: skip
    assert _sessions(rig) == [("z0", 1), ("s1", 1), ("s1", 2), ("zc", 1)]
    closing = rig.dispatcher.requests[-1]
    assert (closing.kind, closing.repair_instruction) == ("attempt", ORDER)
    artefact = next(a for a in rig.reviewer.seen if a.subtask_id == "zc")
    order = artefact.ordered_by_person
    assert order is not None
    assert (order.kind, order.item_id, order.of_attempt) == ("arbitration_value", ITEM, 2)
    assert [(c.item_id, c.subtask_id, c.attempt, c.position.name) for c in order.chosen] == [
        (ITEM, "s1", 2, "peak_current"), (ITEM, "s1", 2, "supply_voltage"),
    ]  # fmt: skip
    told = person_order_text(order).decode()
    assert told.startswith(OPENING), told
    for where, text in (("prompt", role_prompt(closing)), ("person_order.md", told)):
        _clean(where, text)
        assert "REASON-CANARY" not in text


def test_the_domain_attempt_returns_to_the_gate_after_the_closing_pass_merges(
    tmp_path: Path,
) -> None:
    rig = resized(tmp_path)
    events = events_of(rig)
    assert refusal(events) is None
    kinds = _kinds(rig)
    assert kinds.count("attempt_returned") == 1
    returned = _first(_lines(events), kind="attempt_returned")
    merged = [(m.subtask_id, m.attempt) for m in events if isinstance(m, Merged)]
    assert merged == [("z0", 1), ("zc", 1), ("s1", 2)]
    # After the closing pass's merge, and before the domain's reading is verified again.
    zc_merge = next(
        i for i, e in enumerate(events) if isinstance(e, Merged) and e.subtask_id == "zc"
    )
    assert zc_merge < returned
    again = [
        e.stage for e in events[returned:]
        if isinstance(e, StageEntered) and e.subtask_id == "s1"
    ]  # fmt: skip
    assert again == ["verify_reading", "implement", "gate", "review", "decide", "diff"]
    # The disputes stand as the person chose them: ruled at the level ``person``.
    ruled = [
        (e.attempt, e.level, e.standing.chosen)
        for e in events[returned:] if isinstance(e, ArbitrationDecided)
    ]  # fmt: skip
    assert ruled == [(2, "person", True), (2, "person", True)]
    assert [r.attempt for r in events if isinstance(r, ReviewRan) and r.subtask_id == "s1"] == [2]
    # No session and no attempt spent: the domain's sessions are its two attempts.
    assert _sessions(rig) == [("z0", 1), ("s1", 1), ("s1", 2), ("zc", 1)]
    steps = [s["step"] for s in decisions(_lines(events))]
    assert "returned" in steps


def test_a_choice_that_holds_the_value_leaves_the_line_and_the_old_lines_their_bytes(
    tmp_path: Path,
) -> None:
    rig = resized(tmp_path)
    raw = (rig.run_dir / "events.jsonl").read_bytes().splitlines()
    standings = [json.loads(ln)["standing"] for ln in raw if b'"arbitration_decided"' in ln]
    # ``chosen`` is written where it holds, and left out of every line where it does not.
    assert [s.get("chosen") for s in standings] == [None, None, None, None, True, True]


# --- when sizing writes something else -----------------------------------------------------------


def test_a_value_the_closing_pass_did_not_carry_goes_to_a_person_again_and_records_only(
    tmp_path: Path,
) -> None:
    rig = at_the_item(tmp_path)
    _graph(rig).writes["zc"] = [bus(30, 5)]
    chose(rig.run_dir, "domain")
    driven(rig, resume)
    events = events_of(rig)
    assert refusal(events) is None
    returned = _first(_lines(events), kind="attempt_returned")
    ruled = [
        (e.conflict.quantity, e.level) for e in events[returned:]
        if isinstance(e, ArbitrationDecided)
    ]  # fmt: skip
    assert ruled == [("peak_current", "person"), ("supply_voltage", "queue")]
    second = _item(rig)
    assert second.item_id == f"{ITEM}-r2"
    assert second.consequence.on_choose == {"sizing": "retry", "domain": "record_only"}


def test_a_resize_whose_order_could_not_be_read_whole_ends_the_subtask(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    rig = at_the_item(tmp_path)
    monkeypatch.setattr(decisions_module, "fits_one_read", lambda data: False)
    chose(rig.run_dir, "domain")
    driven(rig, resume)
    events = events_of(rig)
    assert refusal(events) is None
    line = one(taken(events))
    assert (line.effect, line.acts, line.order_too_long) == ("end_subtask", True, True)
    ended = one(e for e in events if isinstance(e, SubtaskRejected))
    assert (ended.subtask_id, ended.by, ended.item_id) == ("s1", "person", ITEM)
    # The closing pass runs as planned, told nothing of a choice that did not act.
    closing = rig.dispatcher.requests[-1]
    assert (closing.subtask_id, closing.repair_instruction) == ("zc", None)


# --- the take's seal, and a held choice ----------------------------------------------------------


def test_the_take_of_a_resize_holds_every_linked_stream_to_its_seal(tmp_path: Path) -> None:
    rig = at_the_item(tmp_path)
    chose(rig.run_dir, "domain")
    # Sizing's own stream, which the item links and no scan of the domain's reads, is rewritten.
    sizing = next(e for e in events_of(rig) if isinstance(e, SessionEnded) and e.subtask_id == "z0")
    assert sizing.trajectory is not None
    path = Path(sizing.trajectory)
    path.write_bytes(path.read_bytes() + b"{}\n")
    driven(rig, resume)
    events = events_of(rig)
    assert [e.cause for e in events if isinstance(e, Incident)] == ["trajectory_tampered"]
    assert taken(events) == []
    assert _sessions(rig) == [("z0", 1), ("s1", 1), ("s1", 2)]


THREE = [entry("z0", "sizing"), entry("s1", "electrical"), entry("s2", "electrical"), CLOSING_PASS]


@pytest.fixture
def without_the_layer(monkeypatch: pytest.MonkeyPatch) -> None:
    """Sessions run without the OS layer, the run's refusal of that switched off to reach it."""
    monkeypatch.setattr(Loop, "_require_os_layer", lambda self: None)
    monkeypatch.setattr(arbitration_runs, "_layer", lambda loop: _layer(loop, present=False))


@pytest.mark.usefixtures("without_the_layer")
def test_a_held_choice_keeps_the_closing_pass_waiting_until_it_is_confirmed(
    tmp_path: Path,
) -> None:
    rig = rig_of(tmp_path / "run")

    def choosing() -> None:
        chose(rig.run_dir, "domain")

    rig.dispatcher.during[4] = choosing  # while s2's session runs
    assert run(rig, plan=THREE) == "wait"
    held = one(taken(events_of(rig)))
    assert (held.effect, held.acts, held.why_not) == ("resize", False, "held_os_layer_off")
    assert _sessions(rig) == [("z0", 1), ("s1", 1), ("s1", 2), ("s2", 1)]
    loop = rig.open()
    _layer(loop, present=False)
    loop.resume(confirm=(held.item_id,), confirmed_by="operator")
    loop.close()
    events = events_of(rig)
    assert refusal(events) is None
    assert _sessions(rig)[-1] == ("zc", 1)
    assert rig.dispatcher.requests[-1].repair_instruction == ORDER
    assert ("s1", 2) in [(m.subtask_id, m.attempt) for m in events if isinstance(m, Merged)]


# --- the closing pass ends without a merge -------------------------------------------------------


def _closing_rejected(tmp_path: Path, kill: Callable[[Event], bool] | None = None) -> Rig:
    """The closing pass's review fails three times; a person ends it; the domain ends with it."""
    reviewer = FakeReviewer(verdicts=["pass", "fail", "fail", "fail"])
    rig = resized(tmp_path, reviewer=reviewer)
    assert _sessions(rig)[-3:] == [("zc", 1), ("zc", 2), ("zc", 3)]
    decide(rig.run_dir, "reject", "this pass is not taken", item_id="run-1-zc")
    if kill is None:
        driven(rig, resume)
    else:
        _killed_at(rig, kill)
        driven(rig, resume)
    return rig


def test_the_closing_pass_s_later_attempts_wrap_what_they_are_told_in_the_values(
    tmp_path: Path,
) -> None:
    reviewer = FakeReviewer(verdicts=["pass", "fail", "pass"])
    rig = resized(tmp_path, reviewer=reviewer)
    second = rig.dispatcher.requests[-1]
    assert (second.subtask_id, second.attempt, second.kind) == ("zc", 2, "attempt")
    told = second.repair_instruction or ""
    assert told.startswith(f"{HEAD}\n\nThe values chosen:\n<<<\n{VALUES}\n>>>\n")
    assert "\nThis attempt also starts from:\n<<<\nAttempt 1 of 3 was rejected by" in told
    assert told.endswith(">>>\nThe specification as issued otherwise still governs.")


def test_the_domain_ends_rejected_naming_the_item_when_the_closing_pass_does_not_merge(
    tmp_path: Path,
) -> None:
    rig = _closing_rejected(tmp_path)
    events = events_of(rig)
    assert refusal(events) is None
    ends = [(e.subtask_id, e.by, e.item_id) for e in events if isinstance(e, SubtaskRejected)]
    assert ends == [("zc", "person", "run-1-zc"), ("s1", "closing_pass", ITEM)]
    lines = _lines(events)
    at = _first(lines, by="closing_pass")
    for forged in ({"item_id": "run-1-zc"}, {"item_id": None}, {"by": "person"}):
        said = _refusal_of([*lines[:at], lines[at] | forged])
        assert said is not None, forged


def test_replay_refuses_an_end_by_the_closing_pass_of_a_subtask_that_does_not_wait(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    rig = at_the_item(tmp_path)
    monkeypatch.setattr(decisions_module, "fits_one_read", lambda data: False)
    chose(rig.run_dir, "domain")
    driven(rig, resume)
    lines = _lines(events_of(rig))
    at = _first(lines, kind="subtask_rejected")
    assert _refusal_of(lines[: at + 1]) is None
    said = _refusal_of([*lines[:at], lines[at] | {"by": "closing_pass"}])
    assert said is not None and "raised" not in said, said


# --- replay holds the return to the record -------------------------------------------------------


def _returned_lines(tmp_path: Path) -> tuple[list[dict[str, Any]], int]:
    rig = resized(tmp_path)
    lines = _lines(events_of(rig))
    at = _first(lines, kind="attempt_returned")
    assert _refusal_of(lines[: at + 1]) is None
    return lines, at


def test_replay_refuses_a_return_the_record_does_not_give(tmp_path: Path) -> None:
    lines, at = _returned_lines(tmp_path / "resized")
    back = lines[at]
    taken_at = _first(lines, kind="decision_taken")
    forged = {
        "twice": [*lines[: at + 1], back],
        "another item": [*lines[:at], back | {"item_id": "run-1-s2"}],
        "another attempt": [*lines[:at], back | {"attempt": 1}],
        "before the closing pass merged": [*lines[: taken_at + 1], back],
    }
    for name, at_lines in forged.items():
        said = _refusal_of(at_lines)
        assert said is not None and "raised" not in said, (name, said)
    # And where no choice resized: a run that records only, its closing pass merged.
    records = rig_of(tmp_path / "records")
    records.config_overrides["queue_decisions"] = "record"
    run(records, plan=CLOSING)
    recorded = _lines(events_of(records))
    said = _refusal_of([*recorded, back])
    assert said is not None and "raised" not in said, said


# --- killed anywhere, resumed once ---------------------------------------------------------------


class _Nth:
    """True at the ``n``-th line that is a ``kind`` with ``fields``."""

    def __init__(self, kind: str, n: int = 1, **fields: Any) -> None:  # noqa: ANN401
        self.kind, self.n, self.fields, self.seen = kind, n, fields, 0

    def __call__(self, line: Event) -> bool:
        data = json.loads(line.model_dump_json())
        if data["kind"] == self.kind and all(data.get(k) == v for k, v in self.fields.items()):
            self.seen += 1
            return self.seen == self.n
        return False


def _killed_at(rig: Rig, kill: Callable[[Event], bool]) -> None:
    loop = rig.open()
    _layer(loop)
    emit = loop._emit
    died: list[bool] = []

    def dies(line: Event) -> None:
        if not died and kill(line):
            died.append(True)
            raise KilledByRowError
        emit(line)

    setattr(loop, "_emit", dies)  # noqa: B010 - a process that dies at a line
    try:
        loop.resume()
    except KilledByRowError:
        pass
    finally:
        loop.close()
    assert died, "the process reached no line the row kills at"


def _outcome(rig: Rig) -> tuple[Any, ...]:
    events = events_of(rig)
    assert refusal(events) is None
    told = [(r.subtask_id, r.attempt, r.repair_instruction) for r in rig.dispatcher.requests]
    merged = [(m.subtask_id, m.attempt) for m in events if isinstance(m, Merged)]
    ruled = [
        (e.subtask_id, e.attempt, e.level) for e in events if isinstance(e, ArbitrationDecided)
    ]
    ends = [(e.subtask_id, e.by, e.item_id) for e in events if isinstance(e, SubtaskRejected)]
    taken_ = [(t.item_id, t.effect, t.acts) for t in events if isinstance(t, DecisionTaken)]
    return told, merged, ruled[-2:], ends, taken_, _kinds(rig).count("attempt_returned")


def test_a_killed_run_between_the_choice_and_the_closing_pass_resumes_once(tmp_path: Path) -> None:
    whole = resized(tmp_path / "whole")
    killed = at_the_item(tmp_path / "killed")
    chose(killed.run_dir, "domain")
    _killed_at(killed, _Nth("stage_entered", subtask_id="zc", stage="resolve"))
    assert [(t.effect, t.acts) for t in taken(events_of(killed))] == [("resize", True)]
    driven(killed, resume)
    assert _sessions(killed).count(("zc", 1)) == 1
    assert killed.dispatcher.requests[-1].repair_instruction is not None
    assert _outcome(killed) == _outcome(whole)


KILLS: dict[str, Callable[[], Callable[[Event], bool]]] = {
    "inside the closing pass": lambda: _Nth("gate_ran", subtask_id="zc"),
    "closing pass done, before the return": lambda: _Nth("attempt_returned"),
    "after the return, before the reading": lambda: _Nth(
        "stage_entered", subtask_id="s1", stage="verify_reading"
    ),
    "mid re-run, between rulings": lambda: _Nth("arbitration_decided", 2),
}


@pytest.mark.parametrize("kill", list(KILLS))
def test_a_process_killed_on_the_way_back_resumes_to_the_same_end(
    tmp_path: Path, kill: str
) -> None:
    whole = resized(tmp_path / "whole")
    killed = at_the_item(tmp_path / "killed")
    chose(killed.run_dir, "domain")
    _killed_at(killed, KILLS[kill]())
    driven(killed, resume)
    assert _outcome(killed) == _outcome(whole)


def test_a_process_killed_between_the_closing_pass_s_end_and_the_domain_s_resumes_once(
    tmp_path: Path,
) -> None:
    whole = _closing_rejected(tmp_path / "whole")
    killed = _closing_rejected(
        tmp_path / "killed", kill=_Nth("subtask_rejected", by="closing_pass")
    )
    assert _outcome(killed) == _outcome(whole)
    ends = [e.subtask_id for e in events_of(killed) if isinstance(e, SubtaskRejected)]
    assert ends == ["zc", "s1"]


# --- B1's precondition, pinned before it lands ----------------------------------------------------


@pytest.mark.parametrize("mode", ["act", "record"])
def test_an_open_arbitration_item_leaves_integration_undispatched_in_either_mode(
    tmp_path: Path, mode: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setitem(roles.ROLES, INTEGRATION.name, INTEGRATION)
    rig = rig_of(tmp_path / "run")
    names = ("electrical", "sizing", INTEGRATION.name)
    rig.config_overrides["models"] = ModelStrings(
        decomposition="claude-sonnet-5",
        roles=dict.fromkeys(names, "claude-sonnet-5"),
        reviewers=dict.fromkeys(names, "claude-opus-5-5"),
    )
    rig.config_overrides["queue_decisions"] = mode
    plan = [*CLOSING, entry("integ", INTEGRATION.name, "modules/integration")]
    driven(rig, lambda r: run(r, plan=plan))
    assert read_queue(rig.run_dir).open_items()[-1].source == "arbitration"
    assert "integ" not in [r.subtask_id for r in rig.dispatcher.requests]
    events = events_of(rig)
    assert not [e for e in events if isinstance(e, StageEntered) and e.subtask_id == "integ"]
    assert refusal(events) is None


def test_a_value_held_exact_is_carried_exact(tmp_path: Path) -> None:
    # The domain disputes with a value too large for a float; the order quotes it exact.
    exact = BIG - 1
    rig = at_the_item(tmp_path, script=[(arbitration_runs.dispute("supply_voltage", exact, "V"),)])
    _graph(rig).writes["zc"] = [bus(exact, 3)]
    chose(rig.run_dir, "domain")
    driven(rig, resume)
    closing = next(r for r in rig.dispatcher.requests if r.subtask_id == "zc")
    assert f'quantity "supply_voltage": {exact} "volt"' in (closing.repair_instruction or "")
    merged = [(m.subtask_id, m.attempt) for m in events_of(rig) if isinstance(m, Merged)]
    assert merged == [("z0", 1), ("zc", 1), ("s1", 2)]
