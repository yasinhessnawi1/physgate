"""Each gate event can be read with what its check said: the bound, the message, the details.

The catch-accounting event carries the fields the headline counts. A reader that shows a
check also needs the bound it held the value to, and for an unchecked record why nothing
could judge it. Those come from the record the gate wrote in its line, beside the event and
from the same derivation, so the two cannot disagree about which record an event is. These
tests build logs by hand with every outcome, and hold each check to the record at the same
place in the gate's own lines, walked here independently.
"""

from __future__ import annotations

from pathlib import Path

import pytest
from synthetic_ledger import Log, record
from ui_rig import real_runs

from physgate.orchestrator.events import Event, GateRan, IntegrationGateRan, read_events
from physgate.orchestrator.gate_events import (
    GateCheck,
    gate_checks,
    gate_events,
    recorded_gate_checks,
)
from physgate.orchestrator.protocols import (
    CheckRecord,
    MagnitudeDetails,
    NumericOutput,
    PassDetails,
    RunningGateMode,
    UncheckedDetails,
)
from physgate.orchestrator.run_config import load_run_config

MODE: RunningGateMode = "observe"


def _unchecked(node: str, *quantities: str) -> CheckRecord:
    return CheckRecord(
        check=2,
        name="magnitude",
        scope="system",
        outcome="unchecked",
        blocking=True,
        node=node,
        module=None,
        value=None,
        expected=None,
        tool="t",
        message=f"{', '.join(quantities)} of {node} have no sourced range for their domain",
        gate_mode=MODE,
        details=UncheckedDetails(quantities=quantities),
    )


def _warning() -> CheckRecord:
    kelvin = NumericOutput(value=-20, unit="K")
    return CheckRecord(
        check=2,
        name="magnitude",
        scope="system",
        outcome="warn",
        blocking=False,
        node="electrical.driver",
        module=None,
        value=kelvin,
        expected="a margin of at least 0 K",
        tool="t",
        message="the driver runs 20 K over its limit",
        gate_mode=MODE,
        details=MagnitudeDetails(
            value=kelvin,
            low=NumericOutput(value=0, unit="K"),
            high=NumericOutput(value=200, unit="K"),
            source="s",
            table_sha256="d" * 64,
        ),
    )


def _over_nothing() -> CheckRecord:
    return CheckRecord(
        check=3,
        name="equilibrium",
        scope="system",
        outcome="pass",
        blocking=True,
        node=None,
        module=None,
        value=None,
        expected=None,
        tool="t",
        message="the equilibrium check found nothing wrong (0 evaluated)",
        gate_mode=MODE,
        details=PassDetails(evaluated=0),
    )


def _every_outcome() -> Log:
    log = Log(mode=MODE)
    log.session("s1", 1)
    log.gate("s1", 1)
    log.review("s1", 1, "pass")
    log.session("s1", 2)
    log.gate("s1", 2, fails=False)
    log.review("s1", 2, "pass")
    log.wrote("s1", 2, "electrical.battery", 3)
    log.integration(
        record("pass", None, scope="system", mode=MODE),
        _over_nothing(),
        _unchecked("electrical.battery", "energy_capacity", "power_supply"),
        _warning(),
        record("fail", "electrical.battery", scope="system", mode=MODE),
    )
    return log


@pytest.fixture(scope="module")
def runs(tmp_path_factory: pytest.TempPathFactory) -> Path:
    """Three runs the real loop made: gated on, observed and clean."""
    return real_runs(tmp_path_factory.mktemp("real"))


def _records_in_the_lines(lines: list[Event]) -> list[CheckRecord]:
    """Every check record in the gate's lines, in order, walked without the reader."""
    return [
        check
        for line in lines
        if isinstance(line, GateRan | IntegrationGateRan)
        for check in line.result.checks
    ]


def test_the_checks_are_the_gate_events_in_the_same_order() -> None:
    log = _every_outcome()
    checks = gate_checks(log.lines, log.manifest_id)
    assert [c.event for c in checks] == gate_events(log.lines, log.manifest_id)
    assert {c.event.outcome for c in checks} == {"pass", "fail", "warn", "unchecked"}


def test_each_check_carries_its_own_record_s_bound_message_and_details() -> None:
    log = _every_outcome()
    checks = gate_checks(log.lines, log.manifest_id)
    records = _records_in_the_lines(log.lines)
    assert len(checks) == len(records) == 7
    for check, written in zip(checks, records, strict=True):
        assert (check.expected, check.message, check.details) == (
            written.expected,
            written.message,
            written.details,
        )
        assert (check.event.name, check.event.outcome, check.event.node) == (
            written.name,
            written.outcome,
            written.node,
        )


def test_an_unchecked_record_says_what_it_could_not_judge_and_why() -> None:
    log = _every_outcome()
    (unchecked,) = [
        c for c in gate_checks(log.lines, log.manifest_id) if c.event.outcome == "unchecked"
    ]
    assert isinstance(unchecked.details, UncheckedDetails)
    assert unchecked.details.quantities == ("energy_capacity", "power_supply")
    assert "no sourced range" in unchecked.message
    assert unchecked.event.evaluated is None


def test_a_pass_over_nothing_says_so() -> None:
    log = _every_outcome()
    passes = [c for c in gate_checks(log.lines, log.manifest_id) if c.event.outcome == "pass"]
    over_nothing = [c for c in passes if c.event.name == "equilibrium"]
    assert [c.event.evaluated for c in over_nothing] == [0]
    for check in passes:
        assert isinstance(check.details, PassDetails)
        assert check.event.evaluated == check.details.evaluated


def test_a_warning_carries_its_bound_and_never_blocks() -> None:
    log = _every_outcome()
    (warning,) = [c for c in gate_checks(log.lines, log.manifest_id) if c.event.outcome == "warn"]
    assert warning.expected == "a margin of at least 0 K"
    assert warning.event.blocking is False


@pytest.mark.parametrize("name", ["run-on", "run-observe", "run-clean"])
def test_the_recorded_checks_are_the_run_s(runs: Path, name: str) -> None:
    run = runs / name
    events = read_events(run / "events.jsonl")
    manifest = load_run_config(run / "run.json").sha256()
    found = recorded_gate_checks(run / "events.jsonl", run / "run.json")
    assert found, "the run gated nothing"
    assert found == gate_checks(events, manifest)
    assert all(isinstance(c, GateCheck) for c in found)
