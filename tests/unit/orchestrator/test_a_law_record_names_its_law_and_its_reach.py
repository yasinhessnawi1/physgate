"""The record shape of the closed-form laws check: each record names its law, and its reach.

The laws check is the gate's eighth (ARCH-080). Its relations are data, one law per row, so
a record that did not name its law could not be counted per law, and a law on probation
could not be told from one that blocks. Three things are held here:

- a failing law record carries the law, its inputs with their own sources, both sides, the
  residual, the tolerance and the digest of the table that judged it, and a law on probation
  never blocks;
- a pass or unchecked record of the laws check names its law, and no other check's record
  names one;
- adding the optional law name changes no byte of what checks 1 to 7 record, so every earlier
  gate line reads and writes back exactly as it was.
"""

from __future__ import annotations

import json
from collections.abc import Callable
from typing import Any

import pytest
from pydantic import ValidationError

from physgate.orchestrator.protocols import (
    CHECK_NUMBERS,
    CheckRecord,
    GateResult,
    LawDetails,
    LawInput,
    NumericOutput,
    PassDetails,
    UncheckedDetails,
)


def refusal(error: type[Exception], build: Callable[[], object]) -> str:
    """The message ``build`` is refused with.

    An accepted build fails an assertion here, so a guard weakened on purpose turns a test red
    by a failing assertion and not by some other exception.
    """
    try:
        build()
    except error as exc:
        return str(exc)
    raise AssertionError("accepted, where a refusal was expected")


AMPS = NumericOutput(value=2, unit="A")


def law_details(**changes: Any) -> LawDetails:
    """A violated electrical-power law at one motor, every field filled."""
    fields: dict[str, Any] = {
        "law_id": "electrical_power",
        "statement": "the power a node draws is its supply voltage times its current",
        "source": "a circuits text, the definition of electrical power",
        "law_status": "block",
        "expression": (
            "power_draw(motor.left) == supply_voltage(motor.left) * current_draw(motor.left)"
        ),
        "inputs": (
            LawInput(
                node_id="motor.left",
                name="power_draw",
                declared=NumericOutput(value=20, unit="W"),
                canonical=NumericOutput(value=20, unit="W"),
                source="data sheet",
                written_by="electrical",
            ),
        ),
        "left": NumericOutput(value=20, unit="W"),
        "right": NumericOutput(value=12, unit="W"),
        "comparator": "==",
        "tolerance": "rounding",
        "residual": NumericOutput(value=8, unit="W"),
        "allowance": NumericOutput(value=0.16, unit="W"),
        "laws_sha256": "a" * 64,
        "evaluated": 3,
    }
    return LawDetails(**{**fields, **changes})


def record(**changes: Any) -> CheckRecord:
    fields: dict[str, Any] = {
        "check": 8,
        "name": "laws",
        "scope": "module",
        "outcome": "fail",
        "blocking": True,
        "node": "motor.left",
        "module": None,
        "value": NumericOutput(value=8, unit="W"),
        "expected": "a residual within 0.16 W",
        "tool": "pint and sympy over the law table",
        "message": "the electrical power law does not hold at motor.left",
        "gate_mode": "on",
        "details": law_details(),
    }
    return CheckRecord(**{**fields, **changes})


def test_the_laws_check_is_the_eighth() -> None:
    assert CHECK_NUMBERS["laws"] == 8
    assert record().check == 8


def test_a_failing_law_record_carries_the_law_its_inputs_and_its_table() -> None:
    details = record().details
    assert isinstance(details, LawDetails)
    assert details.law_id == "electrical_power"
    assert details.inputs[0].source == "data sheet"
    assert details.inputs[0].written_by == "electrical"
    assert details.laws_sha256 == "a" * 64
    assert details.evaluated == 3


def test_a_law_on_probation_never_blocks() -> None:
    probation = law_details(law_status="warn")
    assert record(outcome="warn", blocking=False, details=probation).outcome == "warn"
    assert "probation" in refusal(
        ValidationError, lambda: record(outcome="fail", blocking=True, details=probation)
    )


def test_an_inequality_has_no_allowance_and_an_equality_has_one() -> None:
    law_details(comparator="<=", tolerance="inequality", allowance=None)
    assert "allowance" in refusal(
        ValidationError, lambda: law_details(comparator="<=", tolerance="inequality")
    )
    assert "allowance" in refusal(ValidationError, lambda: law_details(allowance=None))


@pytest.mark.parametrize(
    ("comparator", "tolerance"),
    [("<=", "rounding"), ("==", "inequality"), ("<=", "model"), (">=", "model")],
)
def test_a_comparator_outside_its_tolerance_class_is_refused(
    comparator: str, tolerance: str
) -> None:
    allowance = None if tolerance == "inequality" else AMPS
    assert "tolerance" in refusal(
        ValidationError,
        lambda: law_details(comparator=comparator, tolerance=tolerance, allowance=allowance),
    )


def test_a_pass_and_an_unchecked_record_of_the_laws_check_name_their_law() -> None:
    passed = record(
        outcome="pass",
        node=None,
        value=None,
        expected=None,
        details=PassDetails(evaluated=4, law_id="electrical_power"),
    )
    assert isinstance(passed.details, PassDetails)
    assert passed.details.law_id == "electrical_power"
    unchecked = record(
        outcome="unchecked",
        blocking=True,
        value=None,
        expected=None,
        details=UncheckedDetails(quantities=("current_draw",), law_id="electrical_power"),
    )
    assert isinstance(unchecked.details, UncheckedDetails)
    assert unchecked.details.law_id == "electrical_power"


def test_an_unchecked_law_record_without_its_law_is_refused() -> None:
    assert "names its law" in refusal(
        ValidationError,
        lambda: record(
            outcome="unchecked",
            value=None,
            expected=None,
            details=UncheckedDetails(quantities=("current_draw",)),
        ),
    )


def test_a_pass_of_the_laws_check_without_a_law_judged_nothing() -> None:
    # With no law loaded the check still records that it ran over nothing.
    empty = record(
        outcome="pass", node=None, value=None, expected=None, details=PassDetails(evaluated=0)
    )
    assert empty.details.form == "pass"
    assert "names its law" in refusal(
        ValidationError,
        lambda: record(
            outcome="pass", node=None, value=None, expected=None, details=PassDetails(evaluated=2)
        ),
    )


@pytest.mark.parametrize(
    "details",
    [
        PassDetails(evaluated=1, law_id="electrical_power"),
        UncheckedDetails(quantities=("gizmo",), law_id="electrical_power"),
    ],
)
def test_no_other_check_names_a_law(details: PassDetails | UncheckedDetails) -> None:
    assert "only the laws check" in refusal(
        ValidationError,
        lambda: CheckRecord(
            check=1,
            name="units",
            scope="subtask",
            outcome=details.form,
            blocking=True,
            node=None,
            module=None,
            value=None,
            expected=None,
            tool="pint",
            message="m",
            gate_mode="on",
            details=details,
        ),
    )


def test_law_details_never_stand_under_another_check() -> None:
    refusal(ValidationError, lambda: record(check=4, name="power"))


#: A gate line exactly as checks 1 to 7 wrote it before the laws check existed.
EARLIER = {
    "verdict": "pass",
    "mode": "on",
    "finding": "every check passed",
    "failing_check": None,
    "numeric_output": None,
    "quantities": [],
    "checks": [
        {
            "check": 1,
            "name": "units",
            "scope": "subtask",
            "outcome": "pass",
            "blocking": True,
            "node": None,
            "module": None,
            "value": None,
            "expected": None,
            "tool": "pint 0.26.1",
            "message": "the units check found nothing wrong (3 evaluated)",
            "gate_mode": "on",
            "reviewer_had_passed": None,
            "details": {"form": "pass", "evaluated": 3},
        },
        {
            "check": 5,
            "name": "conservation",
            "scope": "module",
            "outcome": "unchecked",
            "blocking": True,
            "node": "electrical.motor_left",
            "module": None,
            "value": None,
            "expected": None,
            "tool": "sympy 1.14.0",
            "message": "it declares no mass",
            "gate_mode": "on",
            "reviewer_had_passed": None,
            "details": {"form": "unchecked", "quantities": ["mass"]},
        },
    ],
    "catalogue_sha256": "c" * 64,
}


def test_an_earlier_gate_line_reads_and_writes_back_byte_for_byte() -> None:
    text = json.dumps(EARLIER, sort_keys=True)
    parsed = GateResult.model_validate_json(text)
    assert json.dumps(parsed.model_dump(mode="json"), sort_keys=True) == text
    assert "law_id" not in parsed.model_dump_json()
