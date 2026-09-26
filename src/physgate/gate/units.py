"""Quantities as the gate measures them: pint's arithmetic, plus the rules pint cannot see.

pint does the unit arithmetic, and where it refuses (a current compared with a
voltage, an addition to an offset temperature, a unit it does not know) its own
error is the refusal. Three things it gets wrong on its own, measured on 0.26.1:

- it treats the radian as dimensionless, so ``1 Hz + 1 rad/s`` comes out as
  ``2 rad/s``, a factor of 2 pi lost without a word;
- a torque in ``N*m`` converts to energy in ``J``, as if the two were one thing;
- an absolute temperature in degrees Celsius cannot be added to anything, which
  would refuse every legitimate thermal margin.

So a quantity is measured against the **kind** its name has in the catalogue,
in this order, stopping at the first failure:

1. its unit parses (pint's error);
2. it converts to the kind's canonical unit (pint's error);
3. an offset unit such as the degree Celsius appears only on an absolute
   temperature (pint's error, provoked on purpose);
4. the power of the radian in its root units is the kind's (this gate's rule);
5. its unit has the kind's factor shape, where the kind has one: a torque is a
   force times a length, an energy an energy unit or a power times a time (this
   gate's rule).

Additions and comparisons then need one kind, except for temperature, which has
its own algebra: absolute minus absolute is a difference, absolute plus
difference is absolute, and two absolute temperatures are never added. Absolute
temperatures are converted to kelvin before any arithmetic. Rules 4 and 5 and the
kind algebra are this gate's own, and their refusals say so.

Arithmetic is exact: values enter as fractions of their decimal spelling, and the
registry computes in fractions. The registry is built once, when the gate is
imported, and nothing here changes it afterwards.
"""

from __future__ import annotations

from dataclasses import dataclass
from fractions import Fraction
from typing import Any

import pint

from physgate.gate.catalogue import KINDS, PRODUCTS, Kind
from physgate.gate.exceptions import GateError

# pint's registry, computing in exact fractions. Built once at import; the gate
# only reads it. ``Any`` for its quantities: pint's own types are generic over
# the magnitude and do not narrow to Fraction, so the wrappers below carry them.
UREG = pint.UnitRegistry(non_int_type=Fraction)
PINT = f"pint {pint.__version__}"
#: The longest unit spelling the gate parses. Nothing physical needs more, and a
#: bound keeps a pathological string from making the gate slow; a longer one is
#: refused, which is the closed default.
MAX_UNIT_LENGTH = 64

#: pint's refusals, which are the tool's own output wherever they fire.
PINT_ERRORS = (pint.DimensionalityError, pint.OffsetUnitCalculusError)
OWN_RULE = "a rule of this gate, because unit arithmetic alone cannot see it"


def _said(kind_name: str) -> str:
    """A kind's name as prose, with its article."""
    said = kind_name.replace("_", " ")
    return ("an " if said[0] in "aeiou" else "a ") + said


def _dimensions(container: Any) -> str:
    return " * ".join(k if v == 1 else f"{k}**{v}" for k, v in container.items()) or "none"


def pint_message(exc: Exception) -> str:
    """Pint's refusal, as text.

    pint 0.26.1 cannot print its own dimensionality error when it computes in
    fractions: the exponents are fractions, and its formatter asks them for a
    format they do not support (measured). The refusal is still pint's; only the
    text is put together here, from the fields pint gives.
    """
    if isinstance(exc, pint.DimensionalityError):
        return (
            f"pint cannot convert '{exc.units1}' ({_dimensions(exc.dim1)}) to "
            f"'{exc.units2}' ({_dimensions(exc.dim2)})"
        )
    return f"pint: {exc}"


class UnitRefusedError(GateError):
    """A quantity or an expression the unit rules refuse, with the reason as prose."""


@dataclass(frozen=True)
class Measured:
    """A quantity that passed its kind's rules, in its kind's canonical unit."""

    kind: Kind
    #: A pint quantity with a Fraction magnitude.
    quantity: Any

    @property
    def magnitude(self) -> Fraction:
        """The value in the kind's canonical unit, exactly."""
        return Fraction(self.quantity.magnitude)


def exact(value: float | int) -> Fraction:
    """A declared number as the fraction its decimal spelling says."""
    return Fraction(repr(value)) if isinstance(value, float) else Fraction(value)


def parse(value: float | int, unit: str) -> Any:
    """Rule 1: ``value`` in ``unit`` as a pint quantity.

    Raises:
        UnitRefusedError: the unit is too long or does not parse. pint's parser raises
            several unrelated types for a malformed spelling, so every one of them
            is caught and reported with the unit.
    """
    if len(unit) > MAX_UNIT_LENGTH:
        msg = f"the unit {unit[:32]!r}... is longer than {MAX_UNIT_LENGTH} characters"
        raise UnitRefusedError(msg, unit=unit[:64])
    try:
        return UREG.Quantity(exact(value), unit)
    except Exception as exc:  # noqa: BLE001 - pint raises many types for one fault
        msg = f"the unit {unit!r} is not one pint can read ({type(exc).__name__}: {exc})"
        raise UnitRefusedError(msg, unit=unit) from None


def _root_angle(quantity: Any) -> int:
    # pint keeps the radian as a unit of its own in root units although its
    # dimensionality is empty; its power there is the angle count.
    root = UREG.get_root_units(quantity.units)[1]
    power: Any = dict(root._units).get("radian", 0)  # noqa: SLF001 - no public view
    return int(power)


def _factors(quantity: Any) -> list[tuple[Any, Any]]:
    units = dict(quantity.units._units)  # noqa: SLF001 - no public view of the factors
    return [(UREG.Unit(name).dimensionality, power) for name, power in units.items()]


def _shape_holds(shape: str, quantity: Any) -> bool:
    factors = _factors(quantity)

    def made_of(*wanted: str) -> bool:
        dims = [UREG.Unit(u).dimensionality for u in wanted]
        return len(factors) == len(dims) and all(
            any(d == w and p == 1 for d, p in factors) for w in dims
        )

    if shape == "force*length":
        return made_of("N", "m")
    return made_of("J") or made_of("W", "s")


def measure(kind: Kind, value: float | int, unit: str) -> Measured:
    """Measure one quantity against its kind: rules 1 to 5, in order.

    Raises:
        UnitRefusedError: the unit does not parse, or one of this gate's own rules
            refuses it.
        pint.DimensionalityError: it does not convert to the kind's unit.
        pint.OffsetUnitCalculusError: an offset unit on a kind that is not an
            absolute temperature.
    """
    quantity = parse(value, unit)
    converted = quantity.to(kind.canonical)
    if not kind.absolute:
        # pint refuses arithmetic on an offset unit; provoking it is the test.
        quantity * 1  # noqa: B018 - the refusal is the point
    if _root_angle(quantity) != kind.angle:
        msg = (
            f"{_said(kind.name)} is written with the radian to the power "
            f"{kind.angle}, and {unit!r} has it to the power {_root_angle(quantity)} "
            f"({OWN_RULE})"
        )
        raise UnitRefusedError(msg, unit=unit, kind=kind.name)
    if kind.shape is not None and not _shape_holds(kind.shape, quantity):
        msg = f"{_said(kind.name)} is written as {kind.shape}, not {unit!r} ({OWN_RULE})"
        raise UnitRefusedError(msg, unit=unit, kind=kind.name)
    return Measured(kind=kind, quantity=converted)


def add(left: Measured, right: Measured) -> Measured:
    """``left + right``, under the kind algebra.

    Raises:
        UnitRefusedError: the kinds may not be added.
    """
    kinds = (left.kind.name, right.kind.name)
    if kinds == ("temperature", "temperature"):
        msg = f"two absolute temperatures are never added ({OWN_RULE})"
        raise UnitRefusedError(msg)
    if left.kind.name == right.kind.name:
        return Measured(kind=left.kind, quantity=left.quantity + right.quantity)
    if set(kinds) == {"temperature", "temperature_difference"}:
        return Measured(kind=KINDS["temperature"], quantity=left.quantity + right.quantity)
    msg = f"{_said(kinds[0])} is not added to {_said(kinds[1])} ({OWN_RULE})"
    raise UnitRefusedError(msg, left=kinds[0], right=kinds[1])


def subtract(left: Measured, right: Measured) -> Measured:
    """``left - right``, under the kind algebra.

    Raises:
        UnitRefusedError: the kinds may not be subtracted.
    """
    kinds = (left.kind.name, right.kind.name)
    if kinds == ("temperature", "temperature"):
        return Measured(
            kind=KINDS["temperature_difference"], quantity=left.quantity - right.quantity
        )
    if left.kind.name == right.kind.name or kinds == ("temperature", "temperature_difference"):
        return Measured(kind=left.kind, quantity=left.quantity - right.quantity)
    msg = f"{_said(kinds[1])} is not taken from {_said(kinds[0])} ({OWN_RULE})"
    raise UnitRefusedError(msg, left=kinds[0], right=kinds[1])


def multiply(left: Measured, right: Measured) -> Measured:
    """``left * right``, where the catalogue names the product's kind.

    Raises:
        UnitRefusedError: the catalogue names no kind for this product.
    """
    product = PRODUCTS.get((left.kind.name, right.kind.name))
    if product is None:
        msg = f"the catalogue names no kind for {left.kind.name} times {right.kind.name}"
        raise UnitRefusedError(msg, left=left.kind.name, right=right.kind.name)
    kind = KINDS[product]
    return Measured(kind=kind, quantity=(left.quantity * right.quantity).to(kind.canonical))


def compare(left: Measured, right: Measured) -> Fraction:
    """``left - right`` as a number in ``right``'s canonical unit, for an inequality.

    Raises:
        UnitRefusedError: the kinds may not be compared.
    """
    comparable = left.kind.name == right.kind.name
    if not comparable:
        what = f"{_said(left.kind.name)} is not compared with {_said(right.kind.name)}"
        msg = f"{what} ({OWN_RULE})"
        raise UnitRefusedError(msg, left=left.kind.name, right=right.kind.name)
    return Fraction((left.quantity - right.quantity).to(right.kind.canonical).magnitude)
