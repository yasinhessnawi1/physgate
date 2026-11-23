"""Only a run that acts and began under ``release_2`` writes the incident of a wait on nothing.

A record of an earlier mark, or of a run that records only, holds no such incident, so replay
refuses one appended to it. A record of a run that ended with a module never run, whose first
line is changed to the earlier mark, is another matter: its lines are those the earlier rule
writes for the same plan, which ends done with the module not run, so it replays as that run.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest
import test_a_builder_is_held_until_the_design_it_implements_merges as held
from accounted import forged_account_before_each_open  # noqa: F401 - the rig's forger
from test_a_failed_contract_is_ruled_by_clause_and_goes_to_a_person_as_one_item import (
    lines,
    refusal,
)
from test_a_queue_decision_acts_at_a_boundary import decide
from test_a_run_that_ends_unrun_is_counted_decided_on_and_named_as_the_rules_say import (
    _sizing_registered,  # noqa: F401 - the fixture, by name
    ended,
)

from physgate.orchestrator import record
from physgate.orchestrator.events import parse_events
from physgate.orchestrator.replay import replay


def with_the_incident(rows: list[dict[str, Any]], mark: str | None) -> list[dict[str, Any]]:
    """``rows`` under ``mark``, ending in the incident of a wait on nothing and its halt."""
    first = dict(rows[0])
    if mark is None:
        first.pop("wait_cycle", None)
    else:
        first["wait_cycle"] = mark
    last = rows[-1]
    env = {k: last[k] for k in ("ts", "run_id", "gate_mode")}
    incident = {
        **env,
        "kind": "incident",
        "subtask_id": None,
        "cause": "waits_on_nothing",
        "detail": "the run waits and no item is open to a person: nothing is held.",
    }
    halted = {**env, "kind": "halted", "reason": "incident", "detail": "waits_on_nothing"}
    return [first, *rows[1:], incident, halted]


@pytest.mark.parametrize("mark", ["release", None])
def test_an_incident_of_a_wait_on_nothing_in_a_record_of_an_earlier_mark_is_refused(
    mark: str | None, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    rig, _, step = ended(tmp_path, monkeypatch)
    assert step == "unrun"
    said = refusal(with_the_incident(lines(rig), mark))
    assert said is not None and "under release_2 only" in said


def test_the_same_incident_in_a_record_of_a_run_under_release_2_replays(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    rig, _, step = ended(tmp_path, monkeypatch)
    assert step == "unrun"
    assert refusal(with_the_incident(lines(rig), "release_2")) is None


def designer_rejected(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, mark: str
) -> tuple[Any, str]:
    """The plan whose designer ends unmerged, so its builder is held for good, under ``mark``."""
    monkeypatch.setattr(record, "WAIT_CYCLE", mark)
    rig = held.rigged(tmp_path / mark)
    assert held.first_run(rig, monkeypatch) == "wait"
    decide(rig.run_dir, "reject", "no attempt is left", item_id=held.drive_item(lines(rig)))
    return rig, held.resumed(rig, monkeypatch)


def test_an_unrun_record_with_its_mark_changed_to_release_is_the_record_release_writes(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    # Why a record of a run that ended unrun, with its first line's mark changed to the earlier
    # one, is not refused: under ``release`` the same plan writes these very lines (the end is
    # derived from the mark and written nowhere) and ends done with the builder not run, so the
    # changed record is a genuine one of that mark and replay cannot tell the two apart.
    new, new_end = designer_rejected(tmp_path, monkeypatch, "release_2")
    old, old_end = designer_rejected(tmp_path, monkeypatch, "release")
    assert (new_end, old_end) == ("unrun", "done")
    rows, earlier = lines(new), lines(old)
    assert rows[0]["wait_cycle"] == "release_2" and earlier[0]["wait_cycle"] == "release"
    assert [(r["kind"], r.get("subtask_id"), r.get("item_id")) for r in rows] == [
        (r["kind"], r.get("subtask_id"), r.get("item_id")) for r in earlier
    ]
    changed = [rows[0] | {"wait_cycle": "release"}, *rows[1:]]
    assert refusal(changed) is None
    data = b"".join(json.dumps(r | {"seq": i}).encode() + b"\n" for i, r in enumerate(changed))
    assert replay(parse_events(data, log="events.jsonl")).next_step().kind == "done"


def test_the_status_serves_the_incident_a_halt_rests_on_and_none_where_there_is_none(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from physgate.ui.readers import _halt_served, _incident_of

    rig, _, _ = ended(tmp_path, monkeypatch)
    rows = with_the_incident(lines(rig), "release_2")
    last = rows[-1]
    env = {k: last[k] for k in ("ts", "run_id", "gate_mode")}
    # A second incident and its halt after the first (a resume between them is not needed to
    # read which incident a halt rests on), then a halt that is no incident's at all.
    rows += [
        {**env, "kind": "incident", "subtask_id": None, "cause": "no_progress", "detail": "again"},
        {**env, "kind": "halted", "reason": "incident", "detail": "no_progress"},
        {**env, "kind": "halted", "reason": "disk_full", "detail": "the disk is full"},
    ]
    numbered = [r | {"seq": i} for i, r in enumerate(rows)]
    events = parse_events(
        b"".join(json.dumps(r).encode() + b"\n" for r in numbered), log="events.jsonl"
    )
    first_halt, second_halt, other_halt = (
        numbered[-4]["seq"],
        numbered[-2]["seq"],
        numbered[-1]["seq"],
    )
    waits = "the run waits and no item is open to a person: nothing is held."
    assert _incident_of(events, first_halt) == {"cause": "waits_on_nothing", "detail": waits}
    assert _incident_of(events, second_halt) == {"cause": "no_progress", "detail": "again"}
    assert _incident_of(events, 0) is None
    served = {e.seq: _halt_served(events, e) for e in events if e.kind == "halted"}
    assert served[first_halt]["incident"] == {"cause": "waits_on_nothing", "detail": waits}
    assert served[second_halt]["incident"] == {"cause": "no_progress", "detail": "again"}
    # A halt that is not an incident's rests on none, whatever incident came before it.
    assert "incident" not in served[other_halt]
