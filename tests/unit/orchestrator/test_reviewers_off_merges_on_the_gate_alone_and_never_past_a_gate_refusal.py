"""``reviewers: off`` merges on the gate's result alone, and never past a gate that refused.

An ablation run's arm. Every role still names a pinned, registered reviewer, but none is
invoked: each attempt the gate lets reach review records that its review was skipped, once, and
merges on the gate's result. The gate's order is the code's, as under every other value: under
``gate_mode: on`` an attempt the gate refused is rejected before review, so it never merges;
under ``observe`` and ``off`` the gate blocks nothing, and the attempt merges with its review
skipped.

Replay holds the record to the arm: under ``off`` the skipped line is the only review line, once
per attempt, after a gate line that lets review follow; a review that ran or was unavailable is
refused there, and a skipped review is refused under every other value. The ledger records the
review as ``skipped``, and no gate event says a reviewer passed what none reviewed.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest
from design_review_rig import outcome_of, refusal
from loop_fakes import FakeGate, FakeReviewer, Rig, plan
from orch_helpers import CLEAN_HARNESS, make_config

import physgate.flags as flags
import physgate.orchestrator.events as events
from physgate.orchestrator import run_config
from physgate.orchestrator.exceptions import ReviewerNotRegisteredError
from physgate.orchestrator.gate_events import recorded_gate_events
from physgate.orchestrator.loop import refuse_unregistered
from physgate.orchestrator.run_config import RunConfig

#: Every attempt the gate refuses: more than the run's repair attempts.
ALWAYS_FAILS = ["fail"] * 10


def _arm(value: str) -> dict[str, Any]:
    return {"reviewers": value, "ablation": value != "paired", "harness": CLEAN_HARNESS}


def _run(tmp: Path, gate_mode: str, verdicts: list[str], reviewers: str = "off") -> tuple[Rig, Any]:  # noqa: ANN401 - the loop's last step
    rig = Rig(
        tmp,
        gate_mode=gate_mode,  # type: ignore[arg-type]
        gate=FakeGate(verdicts=verdicts),
        config_overrides=_arm(reviewers),
    )
    loop = outcome_of(rig.open)
    assert not isinstance(loop, Exception), f"the run is refused at its configuration: {loop}"
    loop.start(plan("s1"))
    step = loop.run()
    loop.close()
    return rig, step


def _lines(tmp: Path) -> list[dict[str, Any]]:
    return [json.loads(raw) for raw in (tmp / "events.jsonl").read_text().splitlines()]


def _kinds(tmp: Path) -> list[str]:
    return [line["kind"] for line in _lines(tmp) if line.get("subtask_id") == "s1"]


def _ledger(tmp: Path) -> dict[str, Any]:
    return dict(json.loads((tmp / "ledger.jsonl").read_text().splitlines()[-1]))


# -- the register -----------------------------------------------------------------------------


def test_every_value_of_the_reviewers_switch_is_built() -> None:
    assert run_config.BUILT["reviewers"] == flags.REVIEWERS.values


@pytest.mark.parametrize("value", ["generalist", "off"])
def test_an_ablation_run_takes_the_arm_and_no_other_run_does(value: str) -> None:
    taken = outcome_of(lambda: make_config(**_arm(value)))
    assert isinstance(taken, RunConfig), f"an ablation run is refused reviewers: {value}: {taken}"
    assert taken.reviewers == value
    with pytest.raises(ValueError, match=f"reviewers: {value} is an ablation arm"):
        make_config(reviewers=value, ablation=False)


def test_the_register_says_which_runs_take_each_arm() -> None:
    for value in ("generalist", "off"):
        meaning = flags.REVIEWERS.meanings[value]
        assert "until the arm is built" not in meaning, value
        assert "only an ablation run takes it" in meaning, value


def test_every_role_still_names_a_registered_reviewer_under_off() -> None:
    config = outcome_of(lambda: make_config(**_arm("off")))
    assert isinstance(config, RunConfig), f"an ablation run is refused reviewers: off: {config}"
    with pytest.raises(ReviewerNotRegisteredError, match="every role needs a registered reviewer"):
        refuse_unregistered(config, FakeGate(), {})
    refuse_unregistered(config, FakeGate(), dict.fromkeys(config.models.roles, FakeReviewer()))


# -- through the loop -------------------------------------------------------------------------


def test_under_gate_on_an_attempt_the_gate_refused_never_merges(tmp_path: Path) -> None:
    rig, _ = _run(tmp_path, "on", ALWAYS_FAILS)
    kinds = _kinds(tmp_path)
    assert rig.merger.merges == [], "reviewers: off merged an attempt the gate refused"
    assert "merged" not in kinds
    assert "attempt_rejected" in kinds
    assert "review_skipped" not in kinds, "a refused attempt reached the review stage"
    assert rig.reviewer.seen == []


@pytest.mark.parametrize(
    ("gate_mode", "verdicts", "gate_line"),
    [("on", [], "gate_ran"), ("observe", ALWAYS_FAILS, "gate_ran"), ("off", [], "gate_skipped")],
)
def test_an_attempt_the_gate_lets_through_merges_with_its_review_skipped(
    tmp_path: Path, gate_mode: str, verdicts: list[str], gate_line: str
) -> None:
    rig, step = _run(tmp_path, gate_mode, verdicts)
    kinds = _kinds(tmp_path)
    assert step.kind == "done", step
    assert kinds.count("review_skipped") == 1, kinds
    assert "review_ran" not in kinds and "review_unavailable" not in kinds
    assert kinds.index(gate_line) < kinds.index("review_skipped") < kinds.index("merged")
    skipped = next(line for line in _lines(tmp_path) if line["kind"] == "review_skipped")
    assert skipped["reason"] == "reviewers=off"
    assert (skipped["subtask_id"], skipped["attempt"]) == ("s1", 1)
    assert rig.reviewer.seen == [], "reviewers: off invoked a reviewer"
    assert len(rig.merger.merges) == 1
    assert _ledger(tmp_path)["review_result"] == "skipped"


def test_the_run_s_opening_names_the_arm(tmp_path: Path) -> None:
    _run(tmp_path, "on", [])
    opening = _lines(tmp_path)[0]
    assert opening["kind"] == "run_started"
    assert opening["reviewers"] == "off"


def test_no_gate_event_says_a_reviewer_passed_what_none_reviewed(tmp_path: Path) -> None:
    _run(tmp_path, "observe", ALWAYS_FAILS)
    found = recorded_gate_events(tmp_path / "events.jsonl", tmp_path / "run.json")
    assert found, "the run recorded no gate event"
    assert all(event.reviewer_had_passed is None for event in found)


def test_under_paired_the_attempt_is_reviewed_as_it_always_was(tmp_path: Path) -> None:
    rig, step = _run(tmp_path, "on", [], reviewers="paired")
    kinds = _kinds(tmp_path)
    assert step.kind == "done"
    assert "review_skipped" not in kinds and kinds.count("review_ran") == 1
    assert len(rig.reviewer.seen) == 1
    assert _ledger(tmp_path)["review_result"] == "pass"
    assert "reviewers" not in _lines(tmp_path)[0]


# -- replay -----------------------------------------------------------------------------------


def _review_line(template: dict[str, Any], tmp: Path) -> dict[str, Any]:
    """A review line of the paired run's, for the skipped one's attempt."""
    _run(tmp, "on", [], reviewers="paired")
    ran = next(line for line in _lines(tmp) if line["kind"] == "review_ran")
    envelope = {k: template[k] for k in ("seq", "ts", "run_id", "gate_mode")}
    return {**ran, **envelope}


def test_replay_refuses_a_review_that_ran_under_off(tmp_path: Path) -> None:
    _run(tmp_path / "off", "on", [])
    log = _lines(tmp_path / "off")
    at = next(i for i, line in enumerate(log) if line["kind"] == "review_skipped")
    log[at] = _review_line(log[at], tmp_path / "paired")
    assert refusal(tmp_path, log), "replay took a review that ran under reviewers: off"


def test_replay_refuses_a_review_unavailable_under_off(tmp_path: Path) -> None:
    _run(tmp_path, "on", [])
    log = _lines(tmp_path)
    at = next(i for i, line in enumerate(log) if line["kind"] == "review_skipped")
    envelope = {k: log[at][k] for k in ("seq", "ts", "run_id", "gate_mode")}
    log[at] = {
        **envelope,
        "kind": "review_unavailable",
        "subtask_id": "s1",
        "attempt": 1,
        "cause": "infrastructure",
        "detail": "the reviewer's session ended early",
        "retry": False,
    }
    assert refusal(tmp_path, log), "replay took an unavailable review under reviewers: off"


def test_replay_refuses_a_skipped_review_under_paired(tmp_path: Path) -> None:
    _run(tmp_path, "on", [], reviewers="paired")
    log = _lines(tmp_path)
    at = next(i for i, line in enumerate(log) if line["kind"] == "review_ran")
    envelope = {k: log[at][k] for k in ("seq", "ts", "run_id", "gate_mode")}
    log[at] = {**envelope, "kind": "review_skipped", "subtask_id": "s1", "attempt": 1}
    log[at]["reason"] = "reviewers=off"
    assert refusal(tmp_path, log), "replay took a skipped review in a run that reviews"


def test_replay_refuses_a_second_skipped_review(tmp_path: Path) -> None:
    _run(tmp_path, "on", [])
    log = _lines(tmp_path)
    at = next(i for i, line in enumerate(log) if line["kind"] == "review_skipped")
    log.insert(at + 1, dict(log[at]))
    assert refusal(tmp_path, log), "replay took two skipped reviews of one attempt"


def test_replay_refuses_a_skipped_review_after_a_gate_that_refused(tmp_path: Path) -> None:
    _run(tmp_path, "on", ALWAYS_FAILS)
    log = _lines(tmp_path)
    at = next(i for i, line in enumerate(log) if line["kind"] == "gate_ran")
    envelope = {k: log[at][k] for k in ("seq", "ts", "run_id", "gate_mode")}
    stage = {**envelope, "kind": "stage_entered", "subtask_id": "s1", "attempt": 1}
    stage["stage"] = "review"
    skipped = {**envelope, "kind": "review_skipped", "subtask_id": "s1", "attempt": 1}
    skipped["reason"] = "reviewers=off"
    log[at + 1 : at + 1] = [stage, skipped]
    assert refusal(tmp_path, log), "replay took a skipped review past a gate that refused"


def test_the_skipped_line_is_a_kind_of_its_own() -> None:
    model = getattr(events, "ReviewSkipped", None)
    assert model is not None, "no line records a skipped review"
    assert model.model_fields["kind"].default == "review_skipped"
