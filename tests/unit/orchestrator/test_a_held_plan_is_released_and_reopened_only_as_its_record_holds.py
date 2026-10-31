"""A held plan's release, a reviewed run's opening and the plan's item hold to the run's record.

- A release is taken only while the decomposition's stream still holds the seal the review
  recorded, as a merge is taken only over sealed streams: a stream changed after the approve
  halts the run with nothing dispatched.
- No session is named as the decomposition's stream is read: replay refuses a session line with
  that id, so the stream's key is never a session's by construction.
- A run whose opening was cut after its plan and before its review's line is refused with what
  happened and what to do, not with a raw error at the first dispatch.
- A decision on the plan's item is never one held while a session ran without the OS layer: no
  session runs while the plan is held, so replay refuses such a line.
- The plan's item says what deciding it does in the run it is in: in a run that records decisions
  only, that a decision is recorded and releases nothing.
- An ``act`` run whose first line does not name its decision mode is refused with why: a run
  recorded before the first line named it, or an edited one, and what to do.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest
from design_review_rig import line, outcome_of, refusal, started
from design_review_rig import lines as log_lines
from plan_hold_rig import (
    PRESENT,
    again,
    decide,
    dispatched,
    items,
    kinds,
    opened,
    rig,
    stream_path,
)
from test_a_plan_s_hold_is_replayed_as_the_record_allows import _decision, _log

from physgate.orchestrator.exceptions import RunConfigError, RunStateError
from physgate.orchestrator.record import RunRecord
from physgate.orchestrator.run_config import load_run_config


def _held(tmp_path: Path, *, acts: bool = True) -> Path:
    the_rig = rig(tmp_path / "run", acts=acts)
    loop = outcome_of(lambda: opened(the_rig, review="fail"))
    assert not isinstance(loop, Exception), loop
    loop.close()
    assert again(the_rig) == ("wait" if acts else "escalated")
    return the_rig.run_dir


def test_a_release_is_taken_only_while_the_decomposition_s_stream_holds_its_seal(
    tmp_path: Path,
) -> None:
    run_dir = _held(tmp_path)
    decide(run_dir, "approve")
    stream_path(run_dir).write_text("{}\n")  # changed after the approve, before the take
    again(rig(run_dir))
    found = [e for e in kinds(run_dir) if e in ("incident", "halted", "decision_taken")]
    assert found[:2] == ["incident", "halted"], kinds(run_dir)
    assert dispatched(run_dir) == []
    incident = next(e for e in log_lines(run_dir) if e["kind"] == "incident")
    assert incident["cause"] == "trajectory_tampered"


def test_a_release_over_the_stream_as_sealed_dispatches(tmp_path: Path) -> None:
    run_dir = _held(tmp_path / "a")
    decide(run_dir, "approve")
    again(rig(run_dir))
    assert "stage_entered" in dispatched(run_dir)
    assert "incident" not in kinds(run_dir)


@pytest.mark.parametrize("named", ["decomposition", "a1b2c3"])
def test_no_session_is_named_as_the_decomposition_s_stream(tmp_path: Path, named: str) -> None:
    log = _log(tmp_path)
    spawned = line("session_spawned", log[-1], session_id=named, pid=4242, started="Mon 1")
    found = refusal(tmp_path, [*log, spawned])
    if named == "decomposition":
        assert "decomposition" in found, found
    else:
        assert found == ""


@pytest.mark.parametrize("cut", ["design_review_ran", "tokens_used"])
def test_an_opening_cut_before_its_review_is_refused_with_what_to_do(
    tmp_path: Path, cut: str
) -> None:
    run_dir = outcome_of(lambda: started(tmp_path, "on", queue_decisions="act", os_layer=PRESENT))
    assert isinstance(run_dir, Path), run_dir
    log = log_lines(run_dir)
    last_plan = max(i for i, one in enumerate(log) if one["kind"] == "subtask_planned")
    kept = log if cut == "design_review_ran" else log[: last_plan + 1]
    kept = [one for one in kept if one["kind"] != "design_review_ran"]
    assert any(one["kind"] == "decomposed" for one in kept)
    (run_dir / "events.jsonl").write_text("".join(json.dumps(one) + "\n" for one in kept))
    found = outcome_of(lambda: RunRecord(load_run_config(run_dir / "run.json"), run_dir))
    assert isinstance(found, RunStateError), found
    assert "before its review" in str(found) and "decompose" in str(found)


def test_a_whole_opening_opens(tmp_path: Path) -> None:
    run_dir = outcome_of(lambda: started(tmp_path, "on", queue_decisions="act", os_layer=PRESENT))
    assert isinstance(run_dir, Path), run_dir
    opened_record = outcome_of(lambda: RunRecord(load_run_config(run_dir / "run.json"), run_dir))
    assert isinstance(opened_record, RunRecord), opened_record
    opened_record.close()


def test_a_decision_on_the_plan_s_item_is_never_one_held_for_the_os_layer(
    tmp_path: Path,
) -> None:
    log = _log(tmp_path)
    held = _decision(log, "approve", acts=False, why_not="held_os_layer_off")
    assert refusal(tmp_path, [*log, held]) != ""
    assert refusal(tmp_path, [*log, _decision(log, "approve")]) == ""


def test_the_plan_s_item_says_a_decision_releases_nothing_in_a_run_that_records_only(
    tmp_path: Path,
) -> None:
    recorded = items(_held(tmp_path / "record", acts=False))
    acting = items(_held(tmp_path / "act"))
    assert len(recorded) == 1 and len(acting) == 1
    said = recorded[0].decision_required
    assert "records decisions only" in said and "releases nothing" in said, said
    assert "Approve to run the plan" not in said
    # The item of a run that acts says what it always said.
    assert acting[0].decision_required.startswith(
        "The design reviewer did not pass the plan the decomposition submitted, and nothing "
        "has been dispatched. Approve to run the plan as it stands"
    )


def test_an_act_run_whose_first_line_does_not_name_it_says_why_it_is_refused(
    tmp_path: Path,
) -> None:
    run_dir = outcome_of(lambda: started(tmp_path, queue_decisions="act", os_layer=PRESENT))
    assert isinstance(run_dir, Path), run_dir
    log: list[dict[str, Any]] = log_lines(run_dir)
    first = {k: v for k, v in log[0].items() if k != "queue_decisions"}
    (run_dir / "events.jsonl").write_text(
        "".join(json.dumps(one) + "\n" for one in [first, *log[1:]])
    )
    found = outcome_of(lambda: RunRecord(load_run_config(run_dir / "run.json"), run_dir))
    assert isinstance(found, RunConfigError), found
    assert "recorded before its first line named" in str(found), str(found)
