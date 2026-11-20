"""Gate results for the rows of a run's release: blocking records at chosen nodes, and quantities.

A blocking record of the magnitude check names its node and a value; one of the units check
names a node and no quantity, as the units check's observations name none.
"""

from __future__ import annotations

from collections.abc import Sequence

from physgate.orchestrator.protocols import (
    CheckRecord,
    GateResult,
    MagnitudeDetails,
    NumericOutput,
    PassDetails,
    QuantityRef,
    RunningGateMode,
    UnitDetails,
)


def record(mode: RunningGateMode, check: str, node: str | None) -> CheckRecord:
    """One blocking failure of ``check`` (``magnitude`` or ``units``) at ``node``."""
    if check == "units":
        return CheckRecord(
            check=1,
            name="units",
            scope="subtask",
            outcome="fail",
            blocking=True,
            node=node,
            module=None,
            value=None,
            expected=None,
            tool="test",
            message=f"the units of {node} do not agree",
            gate_mode=mode,
            details=UnitDetails(expression="a + b", left_unit="kg", right_unit="m"),
        )
    value = NumericOutput(value=1.5, unit="dimensionless")
    return CheckRecord(
        check=2,
        name="magnitude",
        scope="subtask",
        outcome="fail",
        blocking=True,
        node=node,
        module=None,
        value=value,
        expected="0 to 1",
        tool="test",
        message=f"efficiency 1.5 on {node} is outside 0 to 1",
        gate_mode=mode,
        details=MagnitudeDetails(
            value=value,
            low=NumericOutput(value=0, unit="dimensionless"),
            high=NumericOutput(value=1, unit="dimensionless"),
            source="the global envelope",
            table_sha256="b" * 64,
        ),
    )


def ref(node: str, name: str, value: float = 1.5, unit: str = "dimensionless") -> QuantityRef:
    return QuantityRef(node_id=node, name=name, value=value, unit=unit)


def failing(
    mode: RunningGateMode,
    records: Sequence[tuple[str, str | None]],
    quantities: Sequence[QuantityRef] = (),
) -> GateResult:
    """A failing result: one blocking record per ``(check, node)``, the given quantities."""
    checks = tuple(record(mode, check, node) for check, node in records)
    first = checks[0]
    return GateResult(
        verdict="fail",
        mode=mode,
        finding=first.message,
        failing_check=first.name,
        numeric_output=first.value,
        quantities=tuple(quantities),
        checks=checks,
        catalogue_sha256="c" * 64,
    )


def passing(mode: RunningGateMode) -> GateResult:
    check = CheckRecord(
        check=2,
        name="magnitude",
        scope="subtask",
        outcome="pass",
        blocking=True,
        node=None,
        module=None,
        value=None,
        expected=None,
        tool="test",
        message="the magnitude check found nothing wrong (1 evaluated)",
        gate_mode=mode,
        details=PassDetails(evaluated=1),
    )
    return GateResult(
        verdict="pass",
        mode=mode,
        finding="every check passed",
        failing_check=None,
        numeric_output=None,
        quantities=(),
        checks=(check,),
        catalogue_sha256="c" * 64,
    )
