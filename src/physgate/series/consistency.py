"""Holding a graph quantity to the simulation record it names, before the attempt is gated.

A quantity that names a record (``Quantity.series``) claims it was read off that record. The
claim is checked: the record must be one this attempt's sessions sealed, it is read back held
to its seal, the named extractor reads the value off it, and the quantity must agree with
that value within the frozen tolerance (three significant figures, relative). A quantity
naming no record is not touched.

Units are compared as the physics gate compares them, never loosely: the quantity's unit is
first held to a spelling whose parse has a bounded cost (it is written by a role), then
converted to the value's unit only within one dimension and one power of the radian (and of
the bit, which the registry also counts as dimensionless), so a phase margin in degrees reads
against radians and one in a dimensionless unit does not. A logarithmic unit (the decibel, the
neper, the octave, the decade) is refused by the gate's own unit parser, as on a record: no
convention is stated for it. An
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
from physgate.series.extract import Extracted, read_off
from physgate.series.reader import SealedEntry, read_record
from physgate.series.record import Record
from physgate.series.seal import SeriesCheck
from physgate.series.tolerance import agrees
from physgate.state.schema import Quantity, SeriesRef
from physgate.unit_spelling import UnitSpellingError, require_bounded_spelling

#: The most quantities naming a record that one attempt's proposals may hold.
MAX_SERIES_CHECKS = 64


class _UnitsDifferError(Exception):
    """The quantity's unit cannot be converted to the value's; the message says why."""


#: Root units the registry counts as dimensionless that are still a kind of their own: an
#: angle, and information (a byte reads as eight bits, a plain ratio as none).
_KINDS = ("radian", "bit")


def _kind_powers(quantity: Any) -> tuple[float, ...]:  # noqa: ANN401 - a pint quantity
    roots = dict(quantity.to_root_units().unit_items())
    return tuple(float(roots.get(name, 0)) for name in _KINDS)


def _in_unit(value: float | int, unit: str, target: str) -> float:
    """``value`` in ``unit``, converted to ``target``; refused across kinds.

    Raises:
        _UnitsDifferError: the unit is not spelt with a bounded parse, does not parse, is of
            another dimension or another power of the radian than ``target``, or the value
            converted is not a finite number.
    """
    try:
        require_bounded_spelling(unit)
    except UnitSpellingError as exc:
        raise _UnitsDifferError(str(exc)) from None
    converted = _converted(value, unit, target)
    if not math.isfinite(converted):
        msg = f"{value} {unit} is not a finite number in {target}"
        raise _UnitsDifferError(msg)
    return converted


def _converted(value: float | int, unit: str, target: str) -> float:
    if unit == target:
        return float(value)
    if (unit, target) == ("Hz", "rad/s"):
        return float(value) * 2 * math.pi
    try:
        # A logarithmic unit is refused here, by the gate's parser, with or without numpy.
        declared = units.parse(value, unit)
        wanted = units.parse(1, target)
        same_kind = declared.dimensionality == wanted.dimensionality and _kind_powers(
            declared
        ) == _kind_powers(wanted)
        converted = float(declared.to(target).magnitude) if same_kind else None
    except Exception as exc:  # noqa: BLE001 - the registry raises many types for one fault
        raise _UnitsDifferError(str(exc) or type(exc).__name__) from None
    if converted is None:
        msg = f"{unit} is not the same kind of unit as {target}"
        raise _UnitsDifferError(msg)
    return converted


class _Readings:
    """The attempt's records, each read once, and each value read off one once."""

    def __init__(self, run_dir: Path) -> None:
        self._run_dir = run_dir
        self._records: dict[str, Record | SeriesError] = {}
        self._values: dict[tuple[str, str, str | None], Extracted | SeriesError] = {}

    def value(self, entry: SealedEntry, reference: SeriesRef) -> Extracted:
        """What ``reference`` reads off the record ``entry`` sealed.

        Raises:
            SeriesError: the record cannot be read, or the value cannot be read off it; the
                same error each time it is asked for again.
        """
        key = (reference.record, reference.extract, reference.trace)
        if key not in self._values:
            try:
                self._values[key] = read_off(self._record(entry), reference)
            except SeriesError as exc:
                self._values[key] = exc
        found = self._values[key]
        if isinstance(found, SeriesError):
            raise found
        return found

    def _record(self, entry: SealedEntry) -> Record:
        record_id = entry.record.record_id
        if record_id not in self._records:
            try:
                self._records[record_id] = read_record(entry.path(self._run_dir), entry.seal())
            except SeriesError as exc:
                self._records[record_id] = exc
        found = self._records[record_id]
        if isinstance(found, SeriesError):
            raise found
        return found


def _base(node_id: str, name: str, quantity: Quantity, reference: SeriesRef) -> dict[str, Any]:
    return {
        "node_id": node_id[:128],
        "quantity": name[:128],
        "record_id": reference.record,
        "extract": reference.extract,
        "trace": reference.trace,
        "declared_value": quantity.value,
        "declared_unit": quantity.unit[:64],
    }


def _check(
    node_id: str,
    name: str,
    quantity: Quantity,
    entries: Mapping[str, SealedEntry],
    readings: _Readings,
) -> SeriesCheck:
    reference = quantity.series
    assert reference is not None  # only quantities naming a record are checked
    base = _base(node_id, name, quantity, reference)
    entry = entries.get(reference.record)
    if entry is None:
        reason = (
            f"{node_id}.{name} names the record {reference.record}, which this attempt did not seal"
        )
        return SeriesCheck(**base, outcome="unreadable", reason=reason)
    base["session_id"] = entry.session_id
    try:
        found = readings.value(entry, reference)
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
    """Every quantity of ``proposals`` that names a record, held to it; in a stable order.

    Each record is read at most once and each value read off it at most once. Proposals naming
    records from more than :data:`MAX_SERIES_CHECKS` quantities are not read at all: every one
    of those quantities is refused, so the check's cost is bounded by the attempt's records.
    """
    by_id = {entry.record.record_id: entry for entry in entries}
    named: list[tuple[str, str, Quantity, SeriesRef]] = []
    for payload in proposals:
        node_id = str(payload.get("id"))
        quantities = payload.get("quantities") or {}
        for name in sorted(quantities):
            quantity = Quantity.model_validate(quantities[name])
            if quantity.series is not None:
                named.append((node_id, name, quantity, quantity.series))
    if len(named) > MAX_SERIES_CHECKS:
        reason = (
            f"the proposals name records from {len(named)} quantities, more than "
            f"{MAX_SERIES_CHECKS}; none is read. Name a record only from the quantities read "
            "off one."
        )
        return tuple(
            SeriesCheck(
                **_base(node_id, name, quantity, reference), outcome="unreadable", reason=reason
            )
            for node_id, name, quantity, reference in named
        )
    readings = _Readings(run_dir)
    return tuple(
        _check(node_id, name, quantity, by_id, readings) for node_id, name, quantity, _ in named
    )
