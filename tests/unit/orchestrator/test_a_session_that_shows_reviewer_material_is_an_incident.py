"""A role session whose stream shows a canary of reviewer material is an incident.

The canary is found by the dispatcher in the session's own stream; the loop takes
nothing the session did, halts the run for a person, and writes no part of the
canary into the record later sessions can read.
"""

from __future__ import annotations

from pathlib import Path

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
