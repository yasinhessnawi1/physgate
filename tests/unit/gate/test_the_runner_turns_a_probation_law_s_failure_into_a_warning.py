"""The runner, not the laws check, decides whether a law's failure blocks.

A law enters the gate on probation and blocks only once a person has moved it. The check that
evaluates the laws reports what it saw and never what that means: the runner looks each law up
in the table the gate was built with, and a probation law's failure becomes a warning that
blocks nothing, in ``on`` mode as well as ``observe``. A failure of a law that blocks fails the
verdict exactly as any other check's does.

The reach of each law is always on the record, whatever another law did: its own pass record
with its count where it failed nowhere, its count on its failing record where it failed, and
its unchecked records where it judged nothing.
"""

from __future__ import annotations

from collections.abc import Mapping
from pathlib import Path
from typing import Any, Literal

import pytest
from gate_fixtures import fixed, graph, node, unchecked

from physgate.gate.exceptions import LawRecordError
from physgate.gate.graph import GraphView
from physgate.gate.registry import RegisteredCheck
from physgate.gate.result import CheckRun, LawCount, Observation
from physgate.gate.runner import PhysicsGate
from physgate.orchestrator.protocols import (
    CheckRecord,
    LawDetails,
    LawInput,
    NumericOutput,
    PassDetails,
    QuantityRef,
    UncheckedDetails,
)

LawStatus = Literal["warn", "block"]

MOTOR = node("electrical.motor_left", quantities={"power_draw": (20, "W")})


@pytest.fixture
def view(tmp_path: Path) -> GraphView:
    graph(tmp_path / "g", MOTOR)
    return GraphView.read(tmp_path / "g", base_revision=0)


def violated(law_id: str, status: LawStatus, *, evaluated: int = 1) -> Observation:
    """A law that does not hold at the motor, as the laws check reports it."""
    watts = NumericOutput(value=8, unit="W")
    return Observation(
        outcome="fail",
        node="electrical.motor_left",
        module=None,
        value=watts,
        expected="a residual within 0.16 W",
        message=f"{law_id} does not hold at electrical.motor_left",
        details=LawDetails(
            law_id=law_id,
            statement="the power a node draws is its supply voltage times its current",
            source="a circuits text",
            law_status=status,
            expression="power_draw(electrical.motor_left) == 12 W",
            inputs=(
                LawInput(
                    node_id="electrical.motor_left",
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
            residual=watts,
            allowance=NumericOutput(value=0.16, unit="W"),
            laws_sha256="a" * 64,
            evaluated=evaluated,
        ),
        quantities=(
            QuantityRef(node_id="electrical.motor_left", name="power_draw", value=20, unit="W"),
        ),
    )


def unformed(law_id: str) -> Observation:
    """An instance of a law missing an input: recorded unchecked, naming the law."""
    return Observation(
        outcome="unchecked",
        node="electrical.motor_left",
        module=None,
        value=None,
        expected=None,
        message=f"{law_id} cannot be judged at electrical.motor_left: no current_draw",
        details=UncheckedDetails(quantities=("current_draw",), law_id=law_id),
    )


def laws_check(observations: list[Observation], counts: Mapping[str, int]) -> RegisteredCheck:
    """A laws check that reports ``observations`` and each law's count, wherever it runs."""
    found = tuple(observations)
    per_law = tuple(LawCount(law_id=k, evaluated=v) for k, v in sorted(counts.items()))
    return RegisteredCheck(
        name="laws",
        run=lambda ctx: CheckRun(
            tool="pint and sympy over the law table",
            evaluated=sum(counts.values()),
            observations=found,
            law_evaluated=per_law,
        ),
    )


def gate(check: RegisteredCheck, statuses: Mapping[str, LawStatus], *others: Any) -> PhysicsGate:
    return PhysicsGate((*others, check), law_status=statuses)


def law_records(records: tuple[CheckRecord, ...]) -> list[CheckRecord]:
    return [r for r in records if r.name == "laws"]


def test_a_probation_law_s_failure_warns_and_blocks_nothing_in_on_mode(view: GraphView) -> None:
    check = laws_check([violated("electrical_power", "warn")], {"electrical_power": 1})
    result = gate(check, {"electrical_power": "warn"}).run(view, ["module"], "on")
    (only,) = law_records(result.checks)
    assert (only.outcome, only.blocking, only.check) == ("warn", False, 8)
    assert result.verdict == "pass"
    assert result.failing_check is None
    assert result.quantities == ()
    assert "1 warning" in result.finding


def test_a_blocking_law_s_failure_fails_the_verdict(view: GraphView) -> None:
    check = laws_check([violated("electrical_power", "block")], {"electrical_power": 1})
    result = gate(check, {"electrical_power": "block"}).run(view, ["module"], "on")
    (only,) = law_records(result.checks)
    assert (only.outcome, only.blocking) == ("fail", True)
    assert result.verdict == "fail"
    assert result.failing_check == "laws"
    assert [q.name for q in result.quantities] == ["power_draw"]


def test_observe_records_the_same_verdict_and_a_probation_law_still_never_blocks(
    view: GraphView,
) -> None:
    check = laws_check(
        [violated("electrical_power", "block"), violated("within_rating", "warn")],
        {"electrical_power": 1, "within_rating": 1},
    )
    statuses: dict[str, LawStatus] = {"electrical_power": "block", "within_rating": "warn"}
    result = gate(check, statuses).run(view, ["module"], "observe")
    by_law = {r.details.law_id: r for r in law_records(result.checks)}  # type: ignore[union-attr]
    assert (by_law["electrical_power"].outcome, by_law["electrical_power"].blocking) == (
        "fail",
        True,
    )
    assert (by_law["within_rating"].outcome, by_law["within_rating"].blocking) == ("warn", False)
    assert result.verdict == "fail"
    assert {r.gate_mode for r in result.checks} == {"observe"}


def test_each_law_s_reach_is_recorded_whatever_another_law_did(view: GraphView) -> None:
    check = laws_check(
        [violated("electrical_power", "block", evaluated=2)],
        {"electrical_power": 2, "within_rating": 5, "rate_throughput_sample_rate": 0},
    )
    statuses: dict[str, LawStatus] = {
        "electrical_power": "block",
        "within_rating": "block",
        "rate_throughput_sample_rate": "warn",
    }
    result = gate(check, statuses).run(view, ["module"], "on")
    records = law_records(result.checks)
    passes = {
        r.details.law_id: r.details.evaluated for r in records if isinstance(r.details, PassDetails)
    }
    assert passes == {"within_rating": 5, "rate_throughput_sample_rate": 0}
    (failed,) = [r for r in records if r.outcome == "fail"]
    assert isinstance(failed.details, LawDetails)
    assert failed.details.evaluated == 2
    assert all("found nothing wrong" in r.message for r in records if r.outcome == "pass")
    assert [r for r in records if r.outcome == "pass" and "within_rating" in r.message]


def test_a_law_that_judged_nothing_and_left_something_unchecked_writes_no_pass(
    view: GraphView,
) -> None:
    check = laws_check([unformed("electrical_power")], {"electrical_power": 0})
    result = gate(check, {"electrical_power": "warn"}).run(view, ["module"], "on")
    (only,) = law_records(result.checks)
    assert only.outcome == "unchecked"
    assert isinstance(only.details, UncheckedDetails)
    assert only.details.law_id == "electrical_power"
    assert only.blocking is False


def test_records_of_a_law_that_blocks_carry_its_blocking_scope(view: GraphView) -> None:
    check = laws_check([unformed("electrical_power")], {"electrical_power": 1})
    result = gate(check, {"electrical_power": "block"}).run(view, ["module", "system"], "on")
    records = law_records(result.checks)
    assert {(r.scope, r.outcome, r.blocking) for r in records} == {
        ("module", "pass", True),
        ("module", "unchecked", True),
        ("system", "pass", True),
        ("system", "unchecked", True),
    }


def test_with_no_law_loaded_the_check_records_that_it_judged_nothing(view: GraphView) -> None:
    check = laws_check([], {})
    result = gate(check, {}).run(view, ["module"], "on")
    (only,) = law_records(result.checks)
    assert only.outcome == "pass"
    assert only.details == PassDetails(evaluated=0)


def test_the_laws_records_come_in_the_order_of_their_law_ids(view: GraphView) -> None:
    observations = [violated("within_rating", "warn"), violated("electrical_power", "warn")]
    counts = {"within_rating": 1, "electrical_power": 1, "cell_energy": 3}
    statuses: dict[str, LawStatus] = {k: "warn" for k in counts}
    first = gate(laws_check(observations, counts), statuses).run(view, ["module"], "on")
    second = gate(laws_check(observations[::-1], counts), statuses).run(view, ["module"], "on")
    ids = [r.details.law_id for r in law_records(first.checks)]  # type: ignore[union-attr]
    assert ids == ["cell_energy", "electrical_power", "within_rating"]
    assert first.model_dump_json() == second.model_dump_json()


def test_a_law_the_table_does_not_hold_stops_the_gate(view: GraphView) -> None:
    check = laws_check([violated("electrical_power", "block")], {"electrical_power": 1})
    with pytest.raises(LawRecordError, match="not in the table"):
        gate(check, {}).run(view, ["module"], "on")


def test_a_law_reported_at_another_status_than_the_table_s_stops_the_gate(
    view: GraphView,
) -> None:
    check = laws_check([violated("electrical_power", "block")], {"electrical_power": 1})
    with pytest.raises(LawRecordError, match="status"):
        gate(check, {"electrical_power": "warn"}).run(view, ["module"], "on")


def test_a_failing_record_s_count_must_be_the_law_s_count(view: GraphView) -> None:
    check = laws_check([violated("electrical_power", "warn", evaluated=1)], {"electrical_power": 4})
    with pytest.raises(LawRecordError, match="count"):
        gate(check, {"electrical_power": "warn"}).run(view, ["module"], "on")


def test_a_law_without_a_count_stops_the_gate(view: GraphView) -> None:
    check = laws_check([violated("electrical_power", "warn")], {})
    with pytest.raises(LawRecordError, match="count"):
        gate(check, {"electrical_power": "warn"}).run(view, ["module"], "on")


def test_another_check_cannot_report_a_law(view: GraphView) -> None:
    other = RegisteredCheck(
        name="power",
        run=lambda ctx: CheckRun(
            tool="t",
            evaluated=1,
            observations=(),
            law_evaluated=(LawCount(law_id="electrical_power", evaluated=1),),
        ),
    )
    with pytest.raises(LawRecordError, match="only the laws check"):
        PhysicsGate((other,), law_status={"electrical_power": "block"}).run(view, ["module"], "on")


def test_checks_one_to_seven_are_stamped_as_before_beside_the_laws(view: GraphView) -> None:
    alone = PhysicsGate((fixed("units", [unchecked("gizmo")]),)).run(view, ["subtask"], "on")
    beside = gate(
        laws_check([violated("electrical_power", "warn")], {"electrical_power": 1}),
        {"electrical_power": "warn"},
        fixed("units", [unchecked("gizmo")]),
    ).run(view, ["subtask", "module"], "on")
    units = [r.model_dump_json() for r in beside.checks if r.name == "units"]
    assert units == [r.model_dump_json() for r in alone.checks]
