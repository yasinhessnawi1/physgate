"""Each session and review of a run that asked about parts is given the record, held to its line.

ARCH-122. The release line names the record's digest and length. At every dispatch the loop builds
the record again from the plan and the released decisions and holds it to that line: a record that
is no longer the one the release named is an incident and no session is spawned; one that holds
is carried on the request as the bytes the dispatcher writes for the session to read, and on the
attempt as what its reviewer is shown. A run whose plan names no part has no record to read.

"""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any

import pytest
from parts_rig import COMPONENTS, body, decide, log_of, started
from plan_hold_rig import again, kinds

from physgate.orchestrator import loop as loop_module

IDS = ["run-1-parts-1", "run-1-parts-2", "run-1-parts-3"]


def _ran(tmp_path: Path) -> tuple[Path, Any]:
    the_rig = started(tmp_path / "run")
    assert again(the_rig) == "wait"
    run_dir = the_rig.run_dir
    assert not isinstance(decide(run_dir, IDS[0], "have", body({"mass": (0.4, "kg")})), Exception)
    made = body({"mass": (0.1, "kg")}, texts=("printed in PETG",))
    assert not isinstance(decide(run_dir, IDS[1], "make", made), Exception)
    assert not isinstance(decide(run_dir, IDS[2], "find"), Exception)
    return run_dir, the_rig


def _released(run_dir: Path) -> dict[str, Any]:
    found = [one for one in log_of(run_dir) if one["kind"] == "parts_released"]
    assert found, "the log holds no parts_released line"
    return found[0]


def test_every_request_carries_the_record_the_release_names(tmp_path: Path) -> None:
    run_dir, the_rig = _ran(tmp_path)
    assert again(the_rig) == "done"
    released = _released(run_dir)
    requests = the_rig.dispatcher.requests
    assert requests, "no session was dispatched"
    for request in requests:
        held = request.parts_record
        assert held is not None, f"{request.subtask_id} was given no parts record"
        data = held.text.encode("utf-8")
        assert hashlib.sha256(data).hexdigest() == released["record_sha256"]
        assert (held.sha256, held.length) == (released["record_sha256"], released["record_length"])
        components = json.loads(data)["components"]
        assert [c["node"] for c in components] == [c.node for c in COMPONENTS]
        assert [c["choice"] for c in components] == ["have", "make", "find"]


def test_every_review_is_shown_the_record_its_session_read(tmp_path: Path) -> None:
    run_dir, the_rig = _ran(tmp_path)
    assert again(the_rig) == "done"
    released = _released(run_dir)
    seen = the_rig.reviewer.seen
    assert seen, "nothing was reviewed"
    for artefact in seen:
        assert artefact.parts_record is not None, f"{artefact.subtask_id} was reviewed without it"
        assert artefact.parts_record.sha256 == released["record_sha256"]


def test_a_record_that_is_not_the_release_s_is_an_incident_and_no_session_is_spawned(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    run_dir, the_rig = _ran(tmp_path)
    assert again(the_rig, kill_after="parts_released") == "killed"
    real = loop_module.parts_record
    monkeypatch.setattr(loop_module, "parts_record", lambda *a, **k: real(*a, **k) + b" ")
    again(the_rig)
    order = kinds(run_dir)
    incidents = [one for one in log_of(run_dir) if one["kind"] == "incident"]
    assert [one["cause"] for one in incidents] == ["parts_record_mismatch"]
    assert "stage_entered" not in order
    assert the_rig.dispatcher.requests == []


def test_a_plan_that_names_no_part_has_no_record_to_read(tmp_path: Path) -> None:
    the_rig = started(tmp_path / "run", components=())
    assert again(the_rig) == "done"
    assert the_rig.dispatcher.requests
    assert all(r.parts_record is None for r in the_rig.dispatcher.requests)
    assert all(a.parts_record is None for a in the_rig.reviewer.seen)
