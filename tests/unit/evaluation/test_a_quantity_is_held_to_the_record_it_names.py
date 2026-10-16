"""A proposed quantity that names a simulation record is held to it before the attempt is gated.

Through the real loop, change check, git and collection: a stand-in session runs a stand-in
recording script (no physics; with seed 7 the step's trace reaches 0.07 m) and proposes a node whose
``step_peak`` names that record and reads it with ``max_abs``. Every such quantity is checked
and recorded, passes included. One that differs beyond three significant figures, or names a
record or a reading that cannot be made, refuses the attempt before the gate: no gate run and
no review is spent on it, and the repair names both numbers.
"""

from __future__ import annotations

import hashlib
from pathlib import Path
from typing import Any

import pytest
from observe_rig import fake_run, target_repo

from physgate.orchestrator.events import (
    AttemptRejected,
    GateRan,
    Merged,
    ProposalsChecked,
    ReviewRan,
    read_events,
)
from physgate.orchestrator.repair import repair_instruction

BRIEF = "Build two modules.\n"


@pytest.fixture(autouse=True)
def scripted_endpoint(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("ANTHROPIC_BASE_URL", "http://127.0.0.1:9")


def _run(tmp_path: Path, **linked: Any) -> list[Any]:  # noqa: ANN401
    repo = target_repo(tmp_path)
    reference = {"record": "step", "extract": "max_abs", "trace": "position"}
    link = {"value": 0.07, "unit": "m", "series": reference}
    link.update(linked)
    digest = hashlib.sha256(BRIEF.encode()).hexdigest()
    overrides = {"brief_sha256": digest}
    run = fake_run(tmp_path, "run-a", repo, overrides=overrides, records=7, linked=link)
    return read_events(run / "events.jsonl")


def _checks(events: list[Any]) -> list[Any]:
    return [c for e in events if isinstance(e, ProposalsChecked) for c in e.series_checks]


def test_a_quantity_that_agrees_with_its_record_passes_and_is_recorded(tmp_path: Path) -> None:
    events = _run(tmp_path)
    checks = _checks(events)
    assert len(checks) == 2  # one per subtask's attempt
    assert {(c.outcome, c.read_value, c.read_unit) for c in checks} == {("agrees", 0.07, "m")}
    assert all(c.session_id for c in checks)
    assert len([e for e in events if isinstance(e, Merged)]) == 2


def test_a_quantity_in_another_unit_of_the_same_kind_agrees(tmp_path: Path) -> None:
    checks = _checks(_run(tmp_path, value=7.0, unit="cm"))
    assert {c.outcome for c in checks} == {"agrees"}


def test_a_quantity_that_differs_refuses_the_attempt_before_the_gate(tmp_path: Path) -> None:
    events = _run(tmp_path, value=0.08)
    first = next(e for e in events if isinstance(e, ProposalsChecked))
    assert first.refused_by == "series"
    assert [c.outcome for c in first.series_checks] == ["differs"]
    rejected = next(e for e in events if isinstance(e, AttemptRejected))
    assert rejected.finding.source == "series"
    instruction = repair_instruction(1, rejected.finding)
    assert "0.08 m" in instruction and "gives 0.07 m" in instruction
    gated = [e for e in events if isinstance(e, GateRan) and e.attempt == first.attempt]
    reviewed = [e for e in events if isinstance(e, ReviewRan) and e.attempt == first.attempt]
    refused_subtask = first.subtask_id
    assert [e for e in gated if e.subtask_id == refused_subtask] == []
    assert [e for e in reviewed if e.subtask_id == refused_subtask] == []


@pytest.mark.parametrize(
    ("linked", "reason"),
    [
        ({"series": {"record": "bode", "extract": "max_abs", "trace": "position"}}, "did not seal"),
        ({"series": {"record": "step", "extract": "max_abs", "trace": "tilt"}}, "no trace"),
        ({"series": {"record": "step", "extract": "phase_margin"}}, "frequency response"),
        ({"unit": "V"}, "same kind of unit"),
        ({"unit": "10**10**10*m"}, "named units with small integer powers"),
    ],
    ids=[
        "unsealed_record",
        "missing_trace",
        "wrong_kind_of_record",
        "other_kind",
        "unbounded_unit",
    ],
)
def test_a_reading_that_cannot_be_made_refuses_the_attempt(
    tmp_path: Path, linked: dict[str, Any], reason: str
) -> None:
    events = _run(tmp_path, **linked)
    first = next(e for e in events if isinstance(e, ProposalsChecked))
    assert first.refused_by == "series", first
    assert [c.outcome for c in first.series_checks] == ["unreadable"]
    assert first.reason is not None and reason in first.reason


def test_the_store_s_reason_comes_first_when_a_proposal_breaks_both(tmp_path: Path) -> None:
    repo = target_repo(tmp_path)
    digest = hashlib.sha256(BRIEF.encode()).hexdigest()
    link = {
        "value": 0.06,
        "unit": "m",
        "series": {"record": "step", "extract": "max_abs", "trace": "position"},
    }
    run = fake_run(
        tmp_path,
        "run-a",
        repo,
        overrides={"brief_sha256": digest},
        records=7,
        linked=link,
        bare={1},
    )
    first = next(e for e in read_events(run / "events.jsonl") if isinstance(e, ProposalsChecked))
    assert first.refused_by == "proposal"
    assert first.series_checks == ()
