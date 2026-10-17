"""Something the sandbox's placeholder sweep would not remove refuses the attempt.

A link, a second name or a replaced directory at a path only the sandbox holds is
the session shaping its worktree where it should not: the loop takes nothing the
session did and halts the run for a person.
"""

from __future__ import annotations

from pathlib import Path

from loop_fakes import FakeDispatcher, Rig, plan

from physgate.orchestrator.events import Halted, Incident, Merged, ReviewRan, read_events


def test_a_refused_placeholder_is_an_incident_and_nothing_is_taken(tmp_path: Path) -> None:
    rig = Rig(tmp_path, dispatcher=FakeDispatcher(placeholders={1: ".bashrc: not a regular file"}))
    loop = rig.open()
    loop.start(plan("s1"))
    loop.run()
    loop.close()
    events = read_events(tmp_path / "events.jsonl")
    incidents = [e for e in events if isinstance(e, Incident)]
    assert [i.cause for i in incidents] == ["placeholder_refused"]
    assert ".bashrc" in incidents[0].detail
    assert [e for e in events if isinstance(e, Halted)]
    assert not [e for e in events if isinstance(e, ReviewRan | Merged)]


def test_a_withheld_file_unsure_at_the_commit_is_an_incident(tmp_path: Path) -> None:
    rig = Rig(tmp_path, dispatcher=FakeDispatcher(withheld={1: "x.json: has more than one name"}))
    loop = rig.open()
    loop.start(plan("s1"))
    loop.run()
    loop.close()
    events = read_events(tmp_path / "events.jsonl")
    incidents = [e for e in events if isinstance(e, Incident)]
    assert [i.cause for i in incidents] == ["withheld_file_unsure"]
    assert not [e for e in events if isinstance(e, ReviewRan | Merged)]
