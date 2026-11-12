"""A follow-up after sizing's closing pass is recorded where it is owed, and nowhere else.

When the closing pass changes a value whose edges reach a domain node no session wrote after it,
the propagation check at system scope would fail the run. Before the integration call, the loop
works out what the pass owes each domain module (from the journal and the change history), and
records one reopen of each module it reached, by code and naming the edges. That reopen is the
one a person's choice on a failed contract makes (a fresh worktree, the next attempt), with a
code cause in place of the decision.

Replay admits such a reopen only where the record can owe one: after the closing pass merged
and before the integration call, under a gate that runs, of a domain module that merged, once,
and all of them together, before any of their attempts begins. What it owes is held to the
journal when the run comes to the integration call again, and before integration's state is
issued: a recorded follow-up the journal does not owe halts the run. Each row reads the durable
record, as a fresh process reads it.
"""

from __future__ import annotations

import json
from collections.abc import Callable, Sequence
from pathlib import Path
from typing import Any

import pytest
from accounted import forged_account_before_each_open  # noqa: F401 - the rig's forger
from arbitration_runs import (
    CLOSING,
    entry,
    events_of,
    refusal,
    resume,
    rig_of,
    run,
)
from loop_fakes import Rig
from pydantic import ValidationError

from physgate.orchestrator.events import Event, SubtaskReopened

BUS = "sizing.bus"
DRIVER = "electrical.driver"
LOOP = "control.loop"


def node(
    node_id: str, owner: str, *, constrains: Sequence[str] = (), amps: float = 2.0
) -> dict[str, Any]:
    return {
        "id": node_id,
        "kind": "component",
        "domain": "cross" if owner == "sizing" else owner,
        "owner_role": owner,
        "quantities": {
            "peak_current": {"value": amps, "unit": "A", "source": "datasheet", "written_by": owner}
        },
        "constrains": list(constrains),
        "geometry_hash": "g0",
        "updated": "2026-11-01T00:00:00Z",
    }


def slice_rig(
    tmp_path: Path, *, closing_amps: float = 3.0, mode: str = "on", loop: bool = False
) -> Rig:
    """Sizing writes the bus, ``s1`` the driver the bus constrains, then the closing pass.

    With ``loop``, ``s2`` (control) writes a loop node the bus constrains too.
    """
    rig = rig_of(tmp_path / "run", mode=mode, script=((),))
    targets = [DRIVER, LOOP] if loop else [DRIVER]
    rig.diff.writes = {  # type: ignore[attr-defined]
        "z0": [node(BUS, "sizing", constrains=targets)],
        "s1": [node(DRIVER, "electrical", constrains=[BUS])],
        "s2": [node(LOOP, "control")],
        "zc": [node(BUS, "sizing", constrains=targets, amps=closing_amps)],
    }
    if loop:
        models = rig.config_overrides["models"]
        rig.config_overrides["models"] = models.model_copy(
            update={
                "roles": {**models.roles, "control": "claude-sonnet-5"},
                "reviewers": {**models.reviewers, "control": "claude-opus-5-5"},
            }
        )
    return rig


#: The slice with a second domain module the bus constrains.
TWO_MODULES = [*CLOSING[:2], entry("s2", "control"), CLOSING[2]]


def ended(rig: Rig, how: Callable[..., str] = run, **kwargs: Any) -> str:  # noqa: ANN401
    """How the run ended, or what escaped it: a row asserts on it, never on a raise."""
    try:
        return how(rig, **kwargs)
    except Exception as exc:  # noqa: BLE001 - any escape is an outcome a row compares
        return f"raised {type(exc).__name__}: {exc}"


def kinds(events: Sequence[Event]) -> list[str]:
    return [e.kind for e in events]


def follow_ups(events: Sequence[Event]) -> list[dict[str, Any]]:
    return [
        e.model_dump(mode="json")
        for e in events
        if isinstance(e, SubtaskReopened) and e.model_dump().get("cause") == "follow_up"
    ]


def recorded(tmp_path: Path) -> list[Event]:
    """The record of a run whose closing pass changed the bus, with its one follow-up."""
    rig = slice_rig(tmp_path)
    assert ended(rig, plan=CLOSING) == "done"
    events = events_of(rig)
    assert len(follow_ups(events)) == 1, "no follow-up was recorded"
    return events


def moved(events: list[Event], index: int, to: int) -> list[Event]:
    lines = list(events)
    lines.insert(to, lines.pop(index))
    return lines


def rewritten(event: Event, **changes: Any) -> Event:  # noqa: ANN401 - a line's own fields
    data = event.model_dump(mode="json") | changes
    return type(event).model_validate_json(json.dumps(data))


def at(events: Sequence[Event], kind: str) -> int:
    return next(i for i, e in enumerate(events) if e.kind == kind and _is_follow_up(e, kind))


def _is_follow_up(event: Event, kind: str) -> bool:
    return kind != "subtask_reopened" or event.model_dump().get("cause") == "follow_up"


# --- the loop records it, where it is owed ---------------------------------------------------


def test_a_closing_pass_change_reaching_a_domain_node_reopens_that_module_once_by_code(
    tmp_path: Path,
) -> None:
    events = recorded(tmp_path)
    (line,) = follow_ups(events)
    merged = next(e for e in events if e.kind == "merged" and e.model_dump()["subtask_id"] == "s1")
    assert line["subtask_id"] == "s1"
    assert line["owed"] == [{"source": BUS, "target": DRIVER}]
    assert line["attempt"] == 2
    assert line["merge_commit"] == merged.model_dump()["merge_commit"]
    assert "item_id" not in line and "shown_sha256" not in line
    closing = max(
        i
        for i, e in enumerate(events)
        if e.kind == "merged" and e.model_dump()["subtask_id"] == "zc"
    )
    reopen = at(events, "subtask_reopened")
    assert closing < reopen < kinds(events).index("integration_gate_ran")
    assert refusal(events) is None


def test_a_closing_pass_that_keeps_every_value_owes_no_follow_up(tmp_path: Path) -> None:
    rig = slice_rig(tmp_path, closing_amps=2.0)
    assert ended(rig, plan=CLOSING) == "done"
    events = events_of(rig)
    assert "integration_gate_ran" in kinds(events)
    assert follow_ups(events) == []
    assert "subtask_reopened" not in kinds(events)


def test_with_the_gate_off_nothing_is_owed(tmp_path: Path) -> None:
    rig = slice_rig(tmp_path, mode="off")
    assert ended(rig, plan=CLOSING) == "done"
    events = events_of(rig)
    assert "integration_gate_skipped" in kinds(events)
    assert follow_ups(events) == []


def test_under_observe_a_follow_up_is_owed_as_under_on(tmp_path: Path) -> None:
    rig = slice_rig(tmp_path, mode="observe")
    assert ended(rig, plan=CLOSING) == "done"
    assert [f["subtask_id"] for f in follow_ups(events_of(rig))] == ["s1"]


def test_a_recorded_follow_up_the_journal_does_not_owe_halts_the_run(tmp_path: Path) -> None:
    # Killed right after the follow-up was written; its edges rewritten before the resume.
    rig = slice_rig(tmp_path)
    written: list[Event] = []

    def after_the_follow_up(line: Event) -> bool:
        if follow_ups(written):
            return True
        written.append(line)
        return False

    assert ended(rig, plan=CLOSING, kill=after_the_follow_up) == "killed"
    path = rig.run_dir / "events.jsonl"
    lines = path.read_text().splitlines()
    (place,) = [i for i, ln in enumerate(lines) if '"follow_up"' in ln]
    data = json.loads(lines[place])
    assert data["owed"] == [{"source": BUS, "target": DRIVER}]
    data["owed"] = [{"source": BUS, "target": "electrical.other"}]
    lines[place] = json.dumps(data, separators=(",", ":"))
    path.write_text("\n".join(lines) + "\n")
    outcome = ended(rig, how=resume)
    events = events_of(rig)
    incidents = [e.model_dump() for e in events if e.kind == "incident"]
    assert outcome == "halted", outcome
    assert [i["cause"] for i in incidents] == ["foreign_journal_line"]
    assert "follow-up" in incidents[0]["detail"]
    assert "integration_gate_ran" not in kinds(events)


# --- replay admits it only where the record can owe one -----------------------------------


def test_a_follow_up_after_the_integration_call_is_refused(tmp_path: Path) -> None:
    # A run that owed none, its call made, and a follow-up of s1's merge written after it.
    line = next(e for e in recorded(tmp_path / "owed") if _is_follow_up(e, "subtask_reopened"))
    rig = slice_rig(tmp_path / "kept", closing_amps=2.0)
    assert ended(rig, plan=CLOSING) == "done"
    events = events_of(rig)
    merged = next(e for e in events if e.kind == "merged" and e.model_dump()["subtask_id"] == "s1")
    late = rewritten(line, merge_commit=merged.model_dump()["merge_commit"])
    call = kinds(events).index("integration_gate_ran")
    assert "before the integration call" in (refusal([*events[: call + 1], late]) or "")


@pytest.mark.parametrize("subtask_id", ["z0", "zc"])
def test_a_follow_up_of_sizing_s_own_module_is_refused(tmp_path: Path, subtask_id: str) -> None:
    events = recorded(tmp_path)
    place = at(events, "subtask_reopened")
    lines = list(events)
    lines[place] = rewritten(lines[place], subtask_id=subtask_id)
    assert "a domain module" in (refusal(lines) or "")


def test_a_follow_up_before_the_closing_pass_merged_is_refused(tmp_path: Path) -> None:
    events = recorded(tmp_path)
    closing = max(
        i
        for i, e in enumerate(events)
        if e.kind == "merged" and e.model_dump()["subtask_id"] == "zc"
    )
    lines = moved(events, at(events, "subtask_reopened"), closing)
    assert "after sizing's closing pass merged" in (refusal(lines) or "")


def test_a_second_follow_up_of_one_module_is_refused(tmp_path: Path) -> None:
    events = recorded(tmp_path)
    place = at(events, "subtask_reopened")
    lines = [*events[: place + 1], events[place], *events[place + 1 :]]
    assert "once" in (refusal(lines) or "")


def test_a_follow_up_at_another_attempt_or_of_another_merge_is_refused(tmp_path: Path) -> None:
    events = recorded(tmp_path)
    place = at(events, "subtask_reopened")
    for change, said in (
        ({"attempt": 3}, "next attempt"),
        ({"merge_commit": "f" * 40}, "last merge"),
    ):
        lines = list(events)
        lines[place] = rewritten(lines[place], **change)
        assert said in (refusal(lines) or ""), change


def test_a_change_reaching_sizing_s_own_node_owes_sizing_no_follow_up(tmp_path: Path) -> None:
    # The bus also constrains a rail sizing's opening pass wrote: that edge is sizing's own work,
    # judged by the check as written, and only the domain module is reopened.
    rig = slice_rig(tmp_path)
    rail = node("sizing.rail", "sizing")
    rig.diff.writes["z0"] = [node(BUS, "sizing", constrains=[DRIVER, "sizing.rail"]), rail]  # type: ignore[attr-defined]
    rig.diff.writes["zc"] = [node(BUS, "sizing", constrains=[DRIVER, "sizing.rail"], amps=3.0)]  # type: ignore[attr-defined]
    assert ended(rig, plan=CLOSING) == "done"
    owed = [(f["subtask_id"], f["owed"]) for f in follow_ups(events_of(rig))]
    assert owed == [("s1", [{"source": BUS, "target": DRIVER}])]


def test_two_modules_reached_are_each_owed_one_follow_up_written_together(
    tmp_path: Path,
) -> None:
    rig = slice_rig(tmp_path, loop=True)
    assert ended(rig, plan=TWO_MODULES) == "done"
    events = events_of(rig)
    owed = [(f["subtask_id"], f["owed"]) for f in follow_ups(events)]
    assert owed == [
        ("s1", [{"source": BUS, "target": DRIVER}]),
        ("s2", [{"source": BUS, "target": LOOP}]),
    ]
    first = at(events, "subtask_reopened")
    second = next(i for i in range(first + 1, len(events)) if events[i].kind == "subtask_reopened")
    # Between them, only the next module's old worktree, removed before its reopen.
    assert kinds(events)[first + 1 : second] == ["worktree_removed"]
    assert refusal(events) is None
    # One round: every follow-up is written together, before any of their attempts begins.
    begun = next(i for i in range(second + 1, len(events)) if events[i].kind == "stage_entered")
    lines = moved(events, second, begun)
    assert "together, before" in (refusal(lines) or "")


# --- the line ----------------------------------------------------------------------------


def _line(**fields: Any) -> dict[str, Any]:  # noqa: ANN401 - a line's own fields
    base = {
        "seq": 9,
        "ts": "2026-11-01T00:00:00.000000Z",
        "run_id": "r1",
        "gate_mode": "on",
        "kind": "subtask_reopened",
        "subtask_id": "s1",
        "merge_commit": "a" * 40,
        "attempt": 2,
    }
    return base | fields


DECIDED = {"item_id": "r1-s1-contract-1", "shown_sha256": "b" * 64}
OWED = {"cause": "follow_up", "owed": [{"source": BUS, "target": DRIVER}]}


def test_a_decision_s_reopen_keeps_its_bytes() -> None:
    line = SubtaskReopened.model_validate_json(json.dumps(_line(**DECIDED)))
    assert set(json.loads(line.model_dump_json())) == set(_line(**DECIDED))


def test_a_follow_up_line_carries_its_cause_and_edges_and_no_decision() -> None:
    try:
        line = SubtaskReopened.model_validate_json(json.dumps(_line(**OWED)))
    except ValidationError as exc:
        pytest.fail(f"a follow-up line does not read: {exc}")
    assert json.loads(line.model_dump_json()) == _line(**OWED)


@pytest.mark.parametrize(
    "fields",
    [
        pytest.param({}, id="neither a decision nor a cause"),
        pytest.param(DECIDED | OWED, id="both"),
        pytest.param({**OWED, "owed": []}, id="a follow-up owing nothing"),
        pytest.param({"cause": "follow_up"}, id="a follow-up with no edges"),
        pytest.param({**DECIDED, "owed": OWED["owed"]}, id="a decision with edges"),
        pytest.param({**OWED, "item_id": None}, id="an explicit null"),
        pytest.param(
            {**OWED, "owed": [{"source": BUS, "target": DRIVER}, {"source": BUS, "target": "a.b"}]},
            id="edges out of order",
        ),
        pytest.param({**OWED, "owed": [OWED["owed"][0], OWED["owed"][0]]}, id="an edge twice"),
    ],
)
def test_a_reopen_line_is_a_decision_s_or_a_follow_up_s_and_never_both(
    fields: dict[str, Any],
) -> None:
    # A follow-up line must read first, so these refusals are not the old model's.
    try:
        SubtaskReopened.model_validate_json(json.dumps(_line(**OWED)))
    except ValidationError as exc:
        pytest.fail(f"a follow-up line does not read: {exc}")
    with pytest.raises(ValidationError):
        SubtaskReopened.model_validate_json(json.dumps(_line(**fields)))
