"""Choosing sizing's value on an arbitration item orders the domain's next attempt to the graph's.

The item says up front what choosing sizing does, computed from the record: the next attempt while
the budget lasts; the one fix a person may order once no attempt is left and the fix is unused; and
otherwise the end of the subtask. The order is built by code from the rulings the item showed: the
graph's ``{value, unit}`` and who wrote it, never the ``source`` or ``written_by`` sizing typed and
never the dispute's reason, each held to the journal first, between the fixed fences, with the
person's note as data when there is one. It reaches the session as its instruction and the
attempt's reviewer as ``person_order.md``. Choosing the domain's value still records only.

A choice written while a session ran without the OS layer is held, and acts once confirmed; a
confirmation that names another position than the decision held is refused on replay.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import Any

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent))
import arbitration_runs  # noqa: E402
from arbitration_runs import (  # noqa: E402
    BIG,
    CANARIES,
    TWO,
    JournalGraph,
    KilledByRowError,
    driven,
    entry,
    events_of,
    refusal,
    resume,
    rig_of,
    run,
)
from loop_fakes import Rig  # noqa: E402
from test_a_person_chooses_a_position_only_on_an_arbitration_item import (  # noqa: E402
    chose,
    one,
    taken,
)
from test_a_queue_decision_acts_at_a_boundary import _layer  # noqa: E402
from test_no_arbitration_branch_puts_another_sessions_output_into_any_prompt import (  # noqa: E402
    _fixed,
)

from physgate import roles  # noqa: E402
from physgate.orchestrator import decisions as decisions_module  # noqa: E402
from physgate.orchestrator.dispatch import role_prompt  # noqa: E402
from physgate.orchestrator.events import (  # noqa: E402
    DecisionTaken,
    Event,
    Incident,
    Merged,
    StageEntered,
    SubtaskRejected,
    parse_events,
)
from physgate.orchestrator.exceptions import CorruptEventLogError  # noqa: E402
from physgate.orchestrator.loop import Loop  # noqa: E402
from physgate.orchestrator.queue import read_queue  # noqa: E402
from physgate.orchestrator.replay import replay  # noqa: E402
from physgate.reviewers.packet import person_order_text  # noqa: E402


@pytest.fixture(autouse=True)
def _sizing_registered(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setitem(roles.ROLES, roles.SIZING.name, roles.SIZING)


NOTE = "keep the graph's bus"
#: What the graph holds for the two disputed quantities, as the order renders them.
HELD = (
    'Node "sizing.bus", quantity "peak_current": the design graph holds 3 "ampere", written by '
    'subtask "z0" in the "sizing" role, at revision 2 of the graph.\n'
    f'Node "sizing.bus", quantity "supply_voltage": the design graph holds {BIG} "volt", written '
    'by subtask "z0" in the "sizing" role, at revision 2 of the graph.'
)
WITHDRAW = (
    "delete .physgate/disputes/sizing.bus.peak_current.json and "
    ".physgate/disputes/sizing.bus.supply_voltage.json to withdraw them"
)


def retry_text(note: str | None) -> str:
    said = f"A person wrote:\n<<<\n{note}\n>>>\n\n" if note is not None else ""
    return (
        "Attempt 2 of 3 disputed a value of a cross node, and a person chose sizing's value. "
        "Sizing alone writes the quantities of a cross node.\n\n"
        f"The values that stand, as the design graph holds them:\n<<<\n{HELD}\n>>>\n\n"
        f"{said}"
        f"Work to the values the graph holds; {WITHDRAW}. A dispute file left in place disputes "
        "its quantity again on the next attempt, and a quantity disputed again goes to a person.\n"
        "The specification as issued is unchanged and still governs.\n\n"
        "1 attempt remains before this goes to a person for a decision."
    )


def fix_text(note: str | None) -> str:
    ordered = (
        f"A person ordered one attempt to work to them, and wrote:\n<<<\n{note}\n>>>\n\n"
        if note is not None
        else "A person ordered one attempt to work to them.\n\n"
    )
    return (
        "Attempt 3 of 3, the subtask's last, disputed a value of a cross node, and a person chose "
        "sizing's value. Sizing alone writes the quantities of a cross node.\n\n"
        f"The values that stand, as the design graph holds them:\n<<<\n{HELD}\n>>>\n\n"
        f"{ordered}"
        f"Work to the values the graph holds; {WITHDRAW}. A dispute left in place goes to a "
        "person again, and choosing sizing's value then ends the subtask.\n"
        "The specification as issued is unchanged and still governs. Do not supply an input it "
        "lacks.\nThis is the last attempt."
    )


def _clean(where: str, text: str) -> None:
    found = [c for c in CANARIES if c in text]
    assert not found, (where, found)


def _item(rig: Rig) -> Any:  # noqa: ANN401 - the queue's model
    return one(read_queue(rig.run_dir).open_items())


def repeat(tmp_path: Path, *, script: Any = (TWO, TWO, ())) -> Rig:  # noqa: ANN401
    """Attempt 1 is ruled for sizing, attempt 2's repeat goes to a person: the item at attempt 2."""
    rig = rig_of(tmp_path / "run", script=list(script))
    driven(rig)
    assert _item(rig).consequence.attempt == 2
    return rig


def last(tmp_path: Path, *, script: Any = (TWO, TWO, TWO, ())) -> Rig:  # noqa: ANN401
    """The gate refuses attempt 1, sizing stands on 2, the last attempt goes to a person."""
    rig = rig_of(tmp_path / "run", gate=["fail"], script=list(script))
    driven(rig)
    assert _item(rig).consequence.attempt == 3
    return rig


# --- what the item says -----------------------------------------------------------------------


def test_the_item_says_choosing_sizing_retries_fixes_or_ends_from_the_record(
    tmp_path: Path,
) -> None:
    with_left = repeat(tmp_path / "left")
    assert _item(with_left).consequence.on_choose == {"sizing": "retry", "domain": "record_only"}
    on_last = last(tmp_path / "last")
    assert _item(on_last).consequence.on_choose == {"sizing": "fix", "domain": "record_only"}
    # The fix disputes again: its item's choice of sizing ends the subtask, the fix being spent.
    on_fix = last(tmp_path / "fix", script=(TWO,))
    chose(on_fix.run_dir, "sizing")
    driven(on_fix, resume)
    item = _item(on_fix)
    assert item.item_id != one(taken(events_of(on_fix))).item_id
    assert item.consequence.on_choose == {"sizing": "end_subtask", "domain": "record_only"}


def test_the_item_of_a_fix_ordered_after_a_blocked_review_says_choosing_sizing_ends_it(
    tmp_path: Path,
) -> None:
    # The fix is attempt 2 here, with budget left by number: it is still the subtask's last.
    rig = rig_of(tmp_path / "run", script=[(), TWO])
    driven(rig, _fixed)
    item = _item(rig)
    assert item.consequence.attempt == 2
    assert item.consequence.on_choose == {"sizing": "end_subtask", "domain": "record_only"}


# --- the next attempt, while the budget lasts -------------------------------------------------


@pytest.mark.parametrize("note", [NOTE, None], ids=["with a note", "without one"])
def test_choosing_sizing_retries_the_domain_with_the_graphs_value(
    tmp_path: Path, note: str | None
) -> None:
    rig = repeat(tmp_path)
    item = _item(rig)
    chose(rig.run_dir, "sizing", note)
    driven(rig, resume)
    events = events_of(rig)
    assert refusal(events) is None
    line = one(taken(events))
    assert (line.verb, line.position, line.effect, line.acts, line.why_not) == (
        "choose", "sizing", "retry", True, None,
    )  # fmt: skip
    # One session more: the domain's attempt 3, told the graph's value, which merges.
    assert [(r.subtask_id, r.attempt) for r in rig.dispatcher.requests] == [
        ("z0", 1), ("s1", 1), ("s1", 2), ("s1", 3),
    ]  # fmt: skip
    request = rig.dispatcher.requests[-1]
    assert request.kind == "attempt"
    assert request.repair_instruction == retry_text(note)
    assert [m.subtask_id for m in events if isinstance(m, Merged)] == ["z0", "s1"]
    # Its reviewer is told, under the fixed label, what the session was told.
    artefact = rig.reviewer.seen[-1]
    order = artefact.ordered_by_person
    assert order is not None
    assert (order.kind, order.item_id, order.of_attempt) == (
        "retry_after_arbitration", item.item_id, 2,
    )  # fmt: skip
    assert order.instruction == retry_text(note)
    told = person_order_text(order).decode()
    assert told.startswith(
        "This attempt is the retry a person ordered by choosing sizing's value on the dispute of "
        f"attempt 2 (queue item {item.item_id})."
    )
    # Nothing a session wrote in its own words reaches either.
    _clean("the prompt", role_prompt(request))
    _clean("the artefact", artefact.model_dump_json())
    _clean("person_order.md", told)


# --- the one fix, once no attempt is left -----------------------------------------------------


@pytest.mark.parametrize("note", [NOTE, None], ids=["with a note", "without one"])
def test_choosing_sizing_on_the_last_attempt_orders_the_one_fix(
    tmp_path: Path, note: str | None
) -> None:
    rig = last(tmp_path)
    item = _item(rig)
    chose(rig.run_dir, "sizing", note)
    driven(rig, resume)
    events = events_of(rig)
    assert refusal(events) is None
    line = one(taken(events))
    assert (line.effect, line.acts) == ("fix", True)
    request = rig.dispatcher.requests[-1]
    assert (request.subtask_id, request.attempt, request.kind) == ("s1", 4, "fix")
    assert request.repair_instruction == fix_text(note)
    assert "This session is the one fix a person ordered" in role_prompt(request)
    order = rig.reviewer.seen[-1].ordered_by_person
    assert order is not None
    assert (order.kind, order.item_id, order.of_attempt) == (
        "fix_after_arbitration", item.item_id, 3,
    )  # fmt: skip
    assert (
        person_order_text(order)
        .decode()
        .startswith(
            "This attempt is the single fix a person ordered by choosing sizing's value on the "
            f"dispute of attempt 3, the subtask's last (queue item {item.item_id})."
        )
    )
    assert [m.subtask_id for m in events if isinstance(m, Merged)] == ["z0", "s1"]
    _clean("the prompt", role_prompt(request))
    _clean("person_order.md", person_order_text(order).decode())


def test_choosing_sizing_on_the_fix_s_own_item_ends_the_subtask(tmp_path: Path) -> None:
    rig = last(tmp_path, script=(TWO,))
    chose(rig.run_dir, "sizing")
    driven(rig, resume)
    second = _item(rig)
    chose(rig.run_dir, "sizing", NOTE)
    driven(rig, resume)
    events = events_of(rig)
    assert refusal(events) is None
    assert [(t.effect, t.acts) for t in taken(events)] == [("fix", True), ("end_subtask", True)]
    ended = one(e for e in events if isinstance(e, SubtaskRejected))
    assert (ended.subtask_id, ended.by, ended.item_id) == ("s1", "person", second.item_id)
    assert [(r.subtask_id, r.attempt) for r in rig.dispatcher.requests][-1] == ("s1", 4)


def test_an_order_its_reviewer_could_not_read_whole_ends_the_subtask_without_a_note(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    rig = repeat(tmp_path)
    item = _item(rig)
    # Long enough for no read, whatever made it so: the order is measured with or without a note.
    monkeypatch.setattr(decisions_module, "fits_one_read", lambda data: False)
    chose(rig.run_dir, "sizing")
    driven(rig, resume)
    events = events_of(rig)
    line = one(taken(events))
    assert (line.effect, line.acts, line.order_too_long) == ("end_subtask", True, True)
    ended = one(e for e in events if isinstance(e, SubtaskRejected))
    assert (ended.by, ended.item_id) == ("person", item.item_id)
    assert len(rig.dispatcher.requests) == 3


# --- held, then confirmed ---------------------------------------------------------------------


@pytest.fixture
def without_the_layer(monkeypatch: pytest.MonkeyPatch) -> None:
    """Sessions run without the OS layer, the run's refusal of that switched off to reach it."""
    monkeypatch.setattr(Loop, "_require_os_layer", lambda self: None)
    monkeypatch.setattr(arbitration_runs, "_layer", lambda loop: _layer(loop, present=False))


THREE = [entry("z0", "sizing"), entry("s1", "electrical"), entry("s2", "electrical")]


@pytest.mark.usefixtures("without_the_layer")
def test_a_choice_written_beside_a_session_without_the_layer_acts_once_confirmed(
    tmp_path: Path,
) -> None:
    rig = rig_of(tmp_path / "run", script=[TWO, TWO, ()])

    # The item is listed at s1's attempt 2; a person chooses while s2's session runs.
    def choosing() -> None:
        chose(rig.run_dir, "sizing", NOTE)

    rig.dispatcher.during[4] = choosing
    driven(rig, lambda r: run(r, plan=THREE))
    held = one(taken(events_of(rig)))
    assert (held.effect, held.acts, held.why_not) == ("retry", False, "held_os_layer_off")
    assert len(rig.dispatcher.requests) == 4
    loop = rig.open()
    _layer(loop, present=False)
    loop.resume(confirm=(held.item_id,), confirmed_by="operator")
    loop.close()
    events = events_of(rig)
    assert refusal(events) is None
    assert [(t.acts, t.confirmed_by, t.position) for t in taken(events)] == [
        (False, None, "sizing"), (True, "operator", "sizing"),
    ]  # fmt: skip
    assert (rig.dispatcher.requests[-1].subtask_id, rig.dispatcher.requests[-1].attempt) == (
        "s1", 3,
    )  # fmt: skip
    # Replay holds the confirmation to the decision held, its position included.
    lines = [json.loads(e.model_dump_json()) for e in events]
    at = [i for i, ln in enumerate(lines) if ln["kind"] == "decision_taken"][-1]
    lines[at] |= {"position": "domain", "decision_offset": lines[at]["decision_offset"]}
    said = _refusal_of(lines[: at + 1])
    assert said is not None and "a confirmation is of the decision that was held" in said, said


# --- replay -----------------------------------------------------------------------------------


def _refusal_of(lines: list[dict[str, Any]]) -> str | None:
    data = b"".join(json.dumps(line).encode() + b"\n" for line in lines)
    try:
        replay(parse_events(data, log="events.jsonl"))
    except CorruptEventLogError as exc:
        return str(exc.context.get("reason", exc))
    except Exception as exc:  # noqa: BLE001 - any other escape is a refusal no rule gave
        return f"raised {type(exc).__name__}: {exc}"
    return None


@pytest.mark.parametrize(
    "change",
    [
        {"effect": "none", "acts": False, "why_not": "record_only_source"},
        {"effect": "fix"},
        {"effect": "end_subtask"},
        {"position": "domain"},
    ],
    ids=["recorded only", "a fix with an attempt left", "the end", "the domain's, acting"],
)
def test_replay_refuses_a_choice_of_sizing_that_does_other_than_the_record_gives(
    tmp_path: Path, change: dict[str, Any]
) -> None:
    rig = repeat(tmp_path)
    chose(rig.run_dir, "sizing", NOTE)
    driven(rig, resume)
    lines = [json.loads(e.model_dump_json()) for e in events_of(rig)]
    at = next(i for i, ln in enumerate(lines) if ln["kind"] == "decision_taken")
    assert _refusal_of(lines[: at + 1]) is None
    lines[at] |= change
    said = _refusal_of(lines[: at + 1])
    assert said is not None and "a decision that does other than the record allows" in said, said


# --- killed between the choice and the attempt it orders --------------------------------------


def test_a_run_killed_after_the_choice_dispatches_the_ordered_attempt_once(tmp_path: Path) -> None:
    whole = repeat(tmp_path / "whole")
    chose(whole.run_dir, "sizing", NOTE)
    driven(whole, resume)
    killed = repeat(tmp_path / "killed")
    chose(killed.run_dir, "sizing", NOTE)
    loop = killed.open()
    _layer(loop)
    emit = loop._emit

    died: list[Event] = []

    def dies(line: Event) -> None:
        if isinstance(line, StageEntered) and (line.subtask_id, line.attempt) == ("s1", 3):
            died.append(line)
            raise KilledByRowError
        emit(line)

    setattr(loop, "_emit", dies)  # noqa: B010 - a process that dies at a line
    try:
        loop.resume()
    except KilledByRowError:
        pass
    finally:
        loop.close()
    assert died, "the process reached no attempt the choice orders"
    assert [(t.effect, t.acts) for t in taken(events_of(killed))] == [("retry", True)]
    driven(killed, resume)
    events = events_of(killed)
    assert refusal(events) is None
    assert len(taken(events)) == 1

    def told(rig: Rig) -> list[tuple[str, int, str | None]]:
        return [(r.subtask_id, r.attempt, r.repair_instruction) for r in rig.dispatcher.requests]

    assert told(killed) == told(whole)
    assert [type(e).__name__ for e in events if not isinstance(e, DecisionTaken)][-6:] == [
        type(e).__name__ for e in events_of(whole) if not isinstance(e, DecisionTaken)
    ][-6:]


def test_a_value_the_journal_no_longer_holds_halts_before_the_ordered_session(
    tmp_path: Path,
) -> None:
    rig = repeat(tmp_path)
    chose(rig.run_dir, "sizing", NOTE)
    loop = rig.open()
    _layer(loop)
    emit = loop._emit
    died: list[Event] = []

    def dies(line: Event) -> None:
        if isinstance(line, StageEntered) and (line.subtask_id, line.attempt) == ("s1", 3):
            died.append(line)
            raise KilledByRowError
        emit(line)

    setattr(loop, "_emit", dies)  # noqa: B010 - a process that dies at a line
    try:
        loop.resume()
    except KilledByRowError:
        pass
    finally:
        loop.close()
    assert died and [(t.effect, t.acts) for t in taken(events_of(rig))] == [("retry", True)]
    # The journal line the rulings were held to is rewritten in place after the choice was taken:
    # the order would quote a value the graph no longer holds, so the run halts first.
    graph = rig.diff
    assert isinstance(graph, JournalGraph)
    sized = graph.journal[1]
    quantities = dict(sized.payload["quantities"])
    quantities["peak_current"] = {**quantities["peak_current"], "value": 4}
    graph.journal[1] = sized.model_copy(
        update={"payload": {**sized.payload, "quantities": quantities}}
    )
    driven(rig, resume)
    events = events_of(rig)
    assert [e.cause for e in events if isinstance(e, Incident)] == ["foreign_journal_line"]
    assert len(rig.dispatcher.requests) == 3
