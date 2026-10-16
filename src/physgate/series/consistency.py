"""Holding a graph quantity to the simulation record it names, before the attempt is gated.

A quantity that names a record (``Quantity.series``) claims it was read off that record. The
claim is checked: the record must be one this attempt's sessions sealed, it is read back held
to its seal, the named extractor reads the value off it, and the quantity must agree with
that value within the frozen tolerance (three significant figures, relative). A quantity
naming no record is not touched.

Units are compared as the physics gate compares them, never loosely: the quantity's unit is
first held to a spelling whose parse has a bounded cost (it is written by a role), then
converted to the value's unit only within one dimension and one power of the radian, so a
phase margin in degrees reads against radians and one in a dimensionless unit does not. An
angular frequency and a frequency in hertz are related by an explicit factor of two pi,
never by the unit registry, which would take them as equal.

Every result is returned, passes included, so the change check can record them all. A
quantity that differs, or that names a record or a reading that cannot be made, refuses the
attempt; the reason names both numbers, so the repair carries them.
"""

from __future__ import annotations

import math
from collections.abc import Iterable, Mapping
from pathlib import Path
from typing import Any

from physgate.gate import units
from physgate.series.exceptions import SeriesError
from physgate.series.extract import read_off
from physgate.series.reader import SealedEntry, read_record
from physgate.series.seal import SeriesCheck
from physgate.series.tolerance import agrees
from physgate.state.schema import Quantity
from physgate.unit_spelling import UnitSpellingError, require_bounded_spelling


class _UnitsDifferError(Exception):
    """The quantity's unit cannot be converted to the value's; the message says why."""


def _radian_power(quantity: Any) -> float:  # noqa: ANN401 - a pint quantity
    return float(dict(quantity.to_root_units().unit_items()).get("radian", 0))


def _in_unit(value: float | int, unit: str, target: str) -> float:
    """``value`` in ``unit``, converted to ``target``; refused across kinds.

    Raises:
        _UnitsDifferError: the unit is not spelt with a bounded parse, does not parse, or is
            of another dimension or another power of the radian than ``target``.
    """
    try:
        require_bounded_spelling(unit)
    except UnitSpellingError as exc:
        raise _UnitsDifferError(str(exc)) from None
    if unit == target:
        return float(value)
    if (unit, target) == ("Hz", "rad/s"):
        return float(value) * 2 * math.pi
    try:
        declared = units.parse(value, unit)
        wanted = units.parse(1, target)
    except units.UnitRefusedError as exc:
        raise _UnitsDifferError(str(exc)) from None
    if declared.dimensionality != wanted.dimensionality or _radian_power(declared) != _radian_power(
        wanted
    ):
        msg = f"{unit} is not the same kind of unit as {target}"
        raise _UnitsDifferError(msg)
    return float(declared.to(target).magnitude)


def _check(
    node_id: str,
    name: str,
    quantity: Quantity,
    entries: Mapping[str, SealedEntry],
    run_dir: Path,
) -> SeriesCheck:
    reference = quantity.series
    assert reference is not None  # only quantities naming a record are checked
    base: dict[str, Any] = {
        "node_id": node_id,
        "quantity": name,
        "record_id": reference.record,
        "extract": reference.extract,
        "trace": reference.trace,
        "declared_value": quantity.value,
        "declared_unit": quantity.unit[:64],
    }
    entry = entries.get(reference.record)
    if entry is None:
        reason = (
            f"{node_id}.{name} names the record {reference.record}, which this attempt did not seal"
        )
        return SeriesCheck(**base, outcome="unreadable", reason=reason)
    base["session_id"] = entry.session_id
    try:
        record = read_record(entry.path(run_dir), entry.seal())
        found = read_off(record, reference)
    except SeriesError as exc:
        reason = f"{node_id}.{name} cannot be read off the record {reference.record}: {exc}"
        return SeriesCheck(**base, outcome="unreadable", reason=reason[:500])
    base.update(read_value=found.value, read_unit=found.unit)
    try:
        declared = _in_unit(quantity.value, quantity.unit, found.unit)
    except _UnitsDifferError as exc:
        reason = f"{node_id}.{name} is in {quantity.unit}, which cannot be compared: {exc}"
        return SeriesCheck(**base, outcome="unreadable", reason=reason[:500])
    if agrees(declared, found.value):
        return SeriesCheck(**base, outcome="agrees")
    reason = (
        f"{node_id}.{name} is {quantity.value} {quantity.unit}, and {reference.extract} read off "
        f"the record {reference.record} gives {found.value:.6g} {found.unit}; they differ by more "
        "than three significant figures. Report the value read off the recorded samples."
    )
    return SeriesCheck(**base, outcome="differs", reason=reason[:500])


def check_proposals(
    proposals: Iterable[Mapping[str, Any]], entries: Iterable[SealedEntry], run_dir: Path
) -> tuple[SeriesCheck, ...]:
    """Every quantity of ``proposals`` that names a record, held to it; in a stable order."""
    by_id = {entry.record.record_id: entry for entry in entries}
    results: list[SeriesCheck] = []
    for payload in proposals:
        node_id = str(payload.get("id"))
        quantities = payload.get("quantities") or {}
        for name in sorted(quantities):
            quantity = Quantity.model_validate(quantities[name])
            if quantity.series is not None:
                results.append(_check(node_id, name, quantity, by_id, run_dir))
    return tuple(results)
