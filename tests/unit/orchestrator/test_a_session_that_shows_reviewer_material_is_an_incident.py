"""A role session whose stream shows a canary of reviewer material is an incident.

The canary is found by the dispatcher in the session's own stream; the loop takes
nothing the session did, halts the run for a person, and writes no part of the
canary into the record later sessions can read.
"""

from __future__ import annotations

from pathlib import Path

import pytest
from loop_fakes import FakeDispatcher, Rig, plan

from physgate.orchestrator.events import Halted, Incident, Merged, ReviewRan, read_events


def test_a_session_that_showed_a_canary_is_an_incident_and_nothing_is_taken(
    tmp_path: Path,
) -> None:
    rig = Rig(tmp_path, dispatcher=FakeDispatcher(material={1: "f" * 32}))
    loop = rig.open()
    loop.start(plan("s1"))
    loop.run()
    loop.close()
    events = read_events(tmp_path / "events.jsonl")
    incidents = [e for e in events if isinstance(e, Incident)]
    assert [i.cause for i in incidents] == ["review_material_read"]
    assert "f" * 8 not in incidents[0].detail  # the canary is not written where sessions read
    assert [e for e in events if isinstance(e, Halted)]
    assert not [e for e in events if isinstance(e, ReviewRan | Merged)]
    assert rig.reviewer.seen == []


def test_a_session_that_showed_a_held_out_canary_is_an_incident_and_nothing_is_taken(
    tmp_path: Path,
) -> None:
    rig = Rig(tmp_path, dispatcher=FakeDispatcher(held_out={1: "e" * 32}))
    loop = rig.open()
    loop.start(plan("s1"))
    loop.run()
    loop.close()
    events = read_events(tmp_path / "events.jsonl")
    incidents = [e for e in events if isinstance(e, Incident)]
    assert [i.cause for i in incidents] == ["held_out_read"]
    assert "e" * 8 not in incidents[0].detail
    assert [e for e in events if isinstance(e, Halted)]
    assert not [e for e in events if isinstance(e, ReviewRan | Merged)]
    assert rig.reviewer.seen == []


#: Every other incident a session's report can raise, with the cause the loop records for it.
OTHER_INCIDENTS = {
    "tampered": ({1: "the stream goes on after its result"}, "trajectory_tampered"),
    "material": ({1: "f" * 32}, "review_material_read"),
    "withheld": ({1: "x.json: has more than one name"}, "withheld_file_unsure"),
    "placeholders": ({1: ".bashrc: not a regular file"}, "placeholder_refused"),
    "drift": ({1: "remote managed settings were delivered"}, "managed_settings_changed"),
}


@pytest.mark.parametrize("other", sorted(OTHER_INCIDENTS))
def test_a_held_out_exposure_is_recorded_whatever_other_incident_stops_the_run(
    tmp_path: Path, other: str
) -> None:
    """An exposure is never left unlogged: the tier's regeneration (ARCH-141) keys on it."""
    found, cause = OTHER_INCIDENTS[other]
    dispatcher = FakeDispatcher(held_out={1: "e" * 32})
    setattr(dispatcher, other, found)
    rig = Rig(tmp_path, dispatcher=dispatcher)
    loop = rig.open()
    loop.start(plan("s1"))
    assert loop.run().kind == "halted"
    loop.close()
    events = read_events(tmp_path / "events.jsonl")
    incidents = [e for e in events if isinstance(e, Incident)]
    assert sorted(i.cause for i in incidents) == sorted(["held_out_read", cause])
    assert all("e" * 8 not in i.detail for i in incidents)
    assert all(i.subtask_id == "s1" for i in incidents)
    # One halt, after both incidents: the run stops once, for a person.
    (halted,) = [e for e in events if isinstance(e, Halted)]
    assert events.index(halted) > max(events.index(i) for i in incidents)
    assert not [e for e in events if isinstance(e, ReviewRan | Merged)]
