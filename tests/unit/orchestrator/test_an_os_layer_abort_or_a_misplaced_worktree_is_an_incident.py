"""An aborted command and a misplaced worktree are incidents of their own, never a refusal.

A session whose commands bubblewrap aborted was told of failures nothing judged: the
loop records the abort under its own cause, takes nothing the session did, and halts
for a person. A session the dispatcher would not start, because its worktree lies where
the OS layer lets every session write, is recorded with the dispatcher's reason; no
session ran, and the run halts.
"""

from __future__ import annotations

from pathlib import Path

import pytest
from loop_fakes import FakeDispatcher, Rig, plan

from physgate.orchestrator.events import (
    Halted,
    Incident,
    Merged,
    ReviewRan,
    SessionEnded,
    read_events,
)

MISPLACED = (
    "the worktree /tmp/run/worktrees/s1 lies inside /tmp, a place the OS layer makes "
    "writable; sandboxed sessions there can abort each other's commands"
)


def test_an_aborted_command_is_an_incident_of_its_own_and_nothing_is_taken(
    tmp_path: Path,
) -> None:
    rig = Rig(tmp_path, dispatcher=FakeDispatcher(aborted={1: ("toolu_7", "toolu_9")}))
    loop = rig.open()
    loop.start(plan("s1"))
    assert loop.run().kind == "halted"
    loop.close()
    events = read_events(tmp_path / "events.jsonl")
    incidents = [e for e in events if isinstance(e, Incident)]
    assert [i.cause for i in incidents] == ["os_layer_aborted"]
    assert "toolu_7, toolu_9" in incidents[0].detail and "sess-1" in incidents[0].detail
    assert incidents[0].detail.startswith("possible abort")
    assert [e for e in events if isinstance(e, Halted)]
    assert not [e for e in events if isinstance(e, ReviewRan | Merged)]
    assert rig.reviewer.seen == []


def test_an_aborted_command_in_a_session_that_ended_for_infrastructure_is_recorded_too(
    tmp_path: Path,
) -> None:
    dispatcher = FakeDispatcher(infra={1: "wall_clock"}, aborted={1: ("toolu_3",)})
    rig = Rig(tmp_path, dispatcher=dispatcher)
    loop = rig.open()
    loop.start(plan("s1"))
    assert loop.run().kind == "halted"
    loop.close()
    events = read_events(tmp_path / "events.jsonl")
    assert [i.cause for i in events if isinstance(i, Incident)] == ["os_layer_aborted"]
    assert len(dispatcher.requests) == 1  # no infrastructure retry ran over it


def test_a_misplaced_worktree_is_an_incident_with_the_dispatcher_s_reason(
    tmp_path: Path,
) -> None:
    rig = Rig(tmp_path, dispatcher=FakeDispatcher(misplaced={1: MISPLACED}))
    loop = rig.open()
    loop.start(plan("s1"))
    assert loop.run().kind == "halted"
    loop.close()
    events = read_events(tmp_path / "events.jsonl")
    (incident,) = [e for e in events if isinstance(e, Incident)]
    assert (incident.cause, incident.detail, incident.subtask_id) == (
        "os_layer_misplaced",
        MISPLACED,
        "s1",
    )
    assert not [e for e in events if isinstance(e, SessionEnded | ReviewRan | Merged)]


def test_a_session_with_no_abort_goes_on_as_before(tmp_path: Path) -> None:
    rig = Rig(tmp_path, dispatcher=FakeDispatcher())
    loop = rig.open()
    loop.start(plan("s1"))
    loop.run()
    loop.close()
    events = read_events(tmp_path / "events.jsonl")
    assert not [e for e in events if isinstance(e, Incident)]
    assert [e for e in events if isinstance(e, Merged)]


#: Every other incident a session's report can raise, with the cause the loop records for it.
OTHER_INCIDENTS = {
    "held_out": ({1: "e" * 32}, "held_out_read"),
    "tampered": ({1: "the stream goes on after its result"}, "trajectory_tampered"),
    "material": ({1: "f" * 32}, "review_material_read"),
    "withheld": ({1: "x.json: has more than one name"}, "withheld_file_unsure"),
    "placeholders": ({1: ".bashrc: not a regular file"}, "placeholder_refused"),
    "drift": ({1: "remote managed settings were delivered"}, "managed_settings_changed"),
}


@pytest.mark.parametrize("other", sorted(OTHER_INCIDENTS))
def test_a_possible_abort_never_takes_the_place_of_another_incident(
    tmp_path: Path, other: str
) -> None:
    """``bwrap:`` in a result is the session's own output: it is recorded beside, never instead.

    Any command can print bubblewrap's words, so a session could otherwise hide an incident
    behind them. Every other incident is recorded first, the possible abort after it, and
    the run halts once, for the other incident.
    """
    found, cause = OTHER_INCIDENTS[other]
    dispatcher = FakeDispatcher(aborted={1: ("toolu_5",)})
    setattr(dispatcher, other, found)
    rig = Rig(tmp_path, dispatcher=dispatcher)
    loop = rig.open()
    loop.start(plan("s1"))
    assert loop.run().kind == "halted"
    loop.close()
    events = read_events(tmp_path / "events.jsonl")
    incidents = [e for e in events if isinstance(e, Incident)]
    assert [i.cause for i in incidents] == [cause, "os_layer_aborted"]
    (halted,) = [e for e in events if isinstance(e, Halted)]
    assert halted.detail == f"{cause} in s1"
    assert events.index(halted) > max(events.index(i) for i in incidents)
    assert not [e for e in events if isinstance(e, ReviewRan | Merged)]


def test_a_command_whose_reaper_could_not_be_heard_from_is_an_incident(tmp_path: Path) -> None:
    # The hook layer logged ``reaper_unverified``: Claude Code cut the output where the
    # survivor reaper's done line stands. Recorded in the run's event log, nothing taken.
    said = ('{"command": "pytest -x"}',)
    rig = Rig(tmp_path, dispatcher=FakeDispatcher(unverified={1: said}))
    loop = rig.open()
    loop.start(plan("s1"))
    assert loop.run().kind == "halted"
    loop.close()
    events = read_events(tmp_path / "events.jsonl")
    (incident,) = [e for e in events if isinstance(e, Incident)]
    assert (incident.cause, incident.subtask_id) == ("reaper_unverified", "s1")
    assert "pytest -x" in incident.detail and "sess-1" in incident.detail
    assert [e for e in events if isinstance(e, Halted)]
    assert not [e for e in events if isinstance(e, ReviewRan | Merged)]


def test_an_unverified_reaping_is_recorded_beside_an_abort(tmp_path: Path) -> None:
    dispatcher = FakeDispatcher(aborted={1: ("toolu_7",)}, unverified={1: ("{}",)})
    rig = Rig(tmp_path, dispatcher=dispatcher)
    loop = rig.open()
    loop.start(plan("s1"))
    assert loop.run().kind == "halted"
    loop.close()
    events = read_events(tmp_path / "events.jsonl")
    causes = [i.cause for i in events if isinstance(i, Incident)]
    assert causes == ["os_layer_aborted", "reaper_unverified"]
