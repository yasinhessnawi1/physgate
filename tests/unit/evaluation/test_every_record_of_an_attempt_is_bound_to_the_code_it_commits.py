"""Every record an attempt sealed is bound to code the attempt commits, from every session.

A record names the script that produced it and every file of code the producing process
loaded. The change check holds each of those files to the attempt commit: committed, at
exactly the path the record names, as a regular file, with the bytes the record was collected
with. That holds for every record of the attempt, a record sealed by a session that ended for
infrastructure included, and for loaded code as for the script: code the attempt does not
commit (ignored, or never added) cannot stand behind a curve. A loaded file changed after the
record was written refuses the record when it is collected.

Through the real loop, change check, git and collection, with stand-in sessions and stand-in
recording scripts (no physics; numbers made up and labelled so).
"""

from __future__ import annotations

import hashlib
from pathlib import Path
from typing import Any

import pytest
from observe_rig import RECORDING_SCRIPT, fake_run, target_repo

from physgate.orchestrator.events import Merged, ProposalsChecked, SessionEnded, read_events
from physgate.orchestrator.run_config import RunBounds

BRIEF = "Build two modules.\n"
LINK = {
    "value": 0.07,
    "unit": "m",
    "series": {"record": "step", "extract": "max_abs", "trace": "position"},
}
PRELUDE = """import os, sys
here = os.path.dirname(os.path.abspath(__file__))
while not os.path.isfile(os.path.join(here, ".physgate", "lib", "series_writer.py")):
    here = os.path.dirname(here)
sys.path.insert(0, os.path.join(here, ".physgate", "lib"))
import series_writer
module = os.path.dirname(os.path.abspath(__file__))
"""
RECORD = """sys.path.insert(0, module)
import helper
series_writer.record("step", title="Stand-in step, not a simulation", axis="time",
    x=("time", "s", [0.0, 0.01, 0.02]), traces=[("position", "m", [0.0, helper.PEAK, 0.05])],
    inputs={"seed": (7, "dimensionless")})
"""
WRITE_HELPER = """with open(os.path.join(module, "helper.py"), "w") as f:
    f.write("PEAK = 0.07\\n")
"""
#: Loads a helper the module's own ignore file keeps out of every commit.
IGNORED_HELPER = (
    PRELUDE
    + WRITE_HELPER
    + """with open(os.path.join(module, ".gitignore"), "w") as f:
    f.write("helper.py\\n")
"""
    + RECORD
)
#: Loads a helper, records, then changes the helper: the curve no longer has its code.
CHANGED_HELPER = (
    PRELUDE
    + WRITE_HELPER
    + RECORD
    + """with open(os.path.join(module, "helper.py"), "w") as f:
    f.write("PEAK = 0.09\\n")
"""
)
#: A committed helper, loaded and unchanged: the control case.
COMMITTED_HELPER = PRELUDE + WRITE_HELPER + RECORD


@pytest.fixture(autouse=True)
def scripted_endpoint(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("ANTHROPIC_BASE_URL", "http://127.0.0.1:9")


def _run(tmp_path: Path, **drive: Any) -> list[Any]:  # noqa: ANN401
    repo = target_repo(tmp_path)
    overrides: dict[str, Any] = {"brief_sha256": hashlib.sha256(BRIEF.encode()).hexdigest()}
    overrides.update(drive.pop("overrides", {}))
    run = fake_run(tmp_path, "run-a", repo, overrides=overrides, records=7, linked=LINK, **drive)
    return read_events(run / "events.jsonl")


def _first_check(events: list[Any]) -> ProposalsChecked:
    return next(e for e in events if isinstance(e, ProposalsChecked))


def test_a_record_from_a_session_ended_for_infrastructure_is_bound_to_the_retry_s_commit(
    tmp_path: Path,
) -> None:
    # The first session records `step` and ends on an API error. The retry changes the script
    # and never runs it, so the curve the quantity names was written by code no commit holds.
    retried = RECORDING_SCRIPT + "# changed in the retry, never run\n"
    events = _run(
        tmp_path,
        session={"infra": {1}, "unrun": {2}, "scripts": {2: retried}},
        overrides={
            "bounds": RunBounds(
                binary_max_retries=0,
                session_wall_clock_s=120.0,
                session_max_turns=20,
                infra_retry_delays_s=(0.0,),
            )
        },
    )
    ended = [e for e in events if isinstance(e, SessionEnded)]
    assert [e.outcome for e in ended[:2]] == ["infrastructure", "completed"]
    assert [r.record_id for r in ended[0].series.records] == ["step"]
    checked = _first_check(events)
    assert checked.refused_by == "series", checked
    assert checked.reason is not None and "did not commit that script" in checked.reason
    assert checked.subject == "step"


def test_loaded_code_the_attempt_does_not_commit_refuses_the_record(tmp_path: Path) -> None:
    events = _run(tmp_path, script=IGNORED_HELPER)
    ended = next(e for e in events if isinstance(e, SessionEnded))
    (record,) = ended.series.records
    assert [c.path.endswith("/helper.py") for c in record.loaded].count(True) == 1
    checked = _first_check(events)
    assert checked.refused_by == "series", checked
    assert checked.reason is not None
    assert "helper.py" in checked.reason and "did not commit" in checked.reason


def test_a_loaded_file_changed_after_the_record_was_written_refuses_the_record(
    tmp_path: Path,
) -> None:
    events = _run(tmp_path, script=CHANGED_HELPER)
    ended = next(e for e in events if isinstance(e, SessionEnded))
    assert ended.series.records == ()
    (refused,) = ended.series.refused
    assert refused.name == "step.json"
    assert "helper.py changed after the record was written" in refused.reason
    assert _first_check(events).refused_by == "series"


def test_committed_loaded_code_unchanged_is_admitted(tmp_path: Path) -> None:
    events = _run(tmp_path, script=COMMITTED_HELPER)
    ended = next(e for e in events if isinstance(e, SessionEnded))
    (record,) = ended.series.records
    assert any(c.path.endswith("/helper.py") for c in record.loaded)
    assert [c.refused_by for c in events if isinstance(c, ProposalsChecked)] == [None, None]
    assert len([e for e in events if isinstance(e, Merged)]) == 2
