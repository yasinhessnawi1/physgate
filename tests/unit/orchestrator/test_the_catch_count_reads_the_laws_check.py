"""The readers of gate records take the laws check as they take the other seven.

Catch accounting (ARCH-083) counts per check number. A law record is check 8, so the per-check
events, the catch table and the escalation state's summary of a gate line must each accept it;
a reader capped at seven would drop the law library's catches, or refuse the line outright.
"""

from __future__ import annotations

from synthetic_ledger import Log, result

from physgate.orchestrator.catches import catches
from physgate.orchestrator.escalation_state import GateCheck
from physgate.orchestrator.events import GateRan
from physgate.orchestrator.gate_events import gate_events
from physgate.orchestrator.protocols import (
    CheckRecord,
    LawDetails,
    LawInput,
    NumericOutput,
    PassDetails,
)

WATTS = NumericOutput(value=8, unit="W")


def law_failure(*, blocking: bool) -> CheckRecord:
    return CheckRecord(
        check=8,
        name="laws",
        scope="module",
        outcome="fail" if blocking else "warn",
        blocking=blocking,
        node="motor.left",
        module=None,
        value=WATTS,
        expected="a residual within 0.16 W",
        tool="t",
        message="electrical_power does not hold at motor.left",
        gate_mode="observe",
        details=LawDetails(
            law_id="electrical_power",
            statement="P = V I",
            source="a circuits text",
            law_status="block" if blocking else "warn",
            expression="power_draw(motor.left) == 12 W",
            inputs=(
                LawInput(
                    node_id="motor.left",
                    name="power_draw",
                    declared=NumericOutput(value=20, unit="W"),
                    canonical=NumericOutput(value=20, unit="W"),
                    source="data sheet",
                    written_by="electrical",
                ),
            ),
            left=NumericOutput(value=20, unit="W"),
            right=NumericOutput(value=12, unit="W"),
            comparator="==",
            tolerance="rounding",
            residual=WATTS,
            allowance=NumericOutput(value=0.16, unit="W"),
            laws_sha256="a" * 64,
            evaluated=1,
        ),
    )


def law_pass(law_id: str) -> CheckRecord:
    return CheckRecord(
        check=8,
        name="laws",
        scope="module",
        outcome="pass",
        blocking=True,
        node=None,
        module=None,
        value=None,
        expected=None,
        tool="t",
        message=f"the {law_id} law found nothing wrong (2 evaluated)",
        gate_mode="observe",
        details=PassDetails(evaluated=2, law_id=law_id),
    )


def logged() -> Log:
    log = Log()
    log.lines.append(
        GateRan(
            **log.env(),
            subtask_id="s1",
            attempt=1,
            result=result((law_failure(blocking=True), law_pass("within_rating")), log.mode),
        )
    )
    log.review("s1", 1, "pass")
    log.lines.append(
        GateRan(
            **log.env(),
            subtask_id="s2",
            attempt=1,
            result=result((law_failure(blocking=False),), log.mode),
        )
    )
    return log


def test_law_records_become_gate_events_under_check_eight() -> None:
    log = logged()
    events = gate_events(log.lines, log.manifest_id)
    assert {(e.check, e.name) for e in events} == {(8, "laws")}
    assert [e.evaluated for e in events if e.outcome == "pass"] == [2]


def test_the_catch_table_counts_a_blocking_law_and_not_a_warning() -> None:
    log = logged()
    rows = catches(gate_events(log.lines, log.manifest_id))
    (laws,) = [r for r in rows if r.name == "laws"]
    assert laws.check == 8
    assert laws.blocking_failures == 1
    assert laws.reviewer_had_passed == 1
    assert laws.artefacts_caught == 1
    assert laws.caught_after_reviewer_passed == 1


def test_the_escalation_state_reads_a_law_record() -> None:
    summary = GateCheck(check="laws", scope="module", outcome="warn", blocking=False)
    assert summary.check == "laws"
