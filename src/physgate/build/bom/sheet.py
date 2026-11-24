"""The offline price sheet: one entry per purchasable part, every number a value with its unit.

A sheet is data, read and validated here, never fetched. Its header must say it is an example
fixture: the only sheet this slice has is one written by hand for demonstration, and a reader of
any output must be able to tell that from the sheet itself. Each entry names the plan node ids it
answers, exactly; the part's maker and the maker's part number; and up to the five facts ARCH-120
asks of a line, each with a note of where its figure came from, or that it is an example value.

A bare number where a quantity goes is a schema error, as everywhere in the design-state graph:
a price is ``{value, unit}`` with a currency code, a count is ``{value, unit: "1"}``, and a lead
time is ``{value, unit}`` in days or weeks, with the scope it holds for.
"""

from __future__ import annotations

import datetime
from fractions import Fraction
from pathlib import Path
from typing import Annotated, Literal

from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    StringConstraints,
    ValidationError,
    model_validator,
)

#: The sheet committed beside this code: an example written for the reference brief's plan names.
EXAMPLE_SHEET = Path(__file__).resolve().parent / "example_sheet.fixture.json"

#: The five facts ARCH-120 asks of every line, in the order they are shown.
FACTS: tuple[str, ...] = (
    "availability",
    "unit_price",
    "minimum_order_quantity",
    "order_multiple",
    "lead_time_to_norway",
)

#: Days in each unit a lead time may be written in.
DAYS_PER_UNIT: dict[str, int] = {"d": 1, "week": 7}

Text = Annotated[str, StringConstraints(min_length=1)]


class SheetError(ValueError):
    """The sheet, or the quantities a person gave, cannot be read as this check needs them."""


class _Frozen(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid", strict=True, allow_inf_nan=False)


class ExampleValue(_Frozen):
    """A figure written for the demonstration: no distributor gave it."""

    kind: Literal["example"]


class ReadFrom(_Frozen):
    """A figure read from a named place on a stated date."""

    kind: Literal["read"]
    where: Text
    read_on: datetime.date


Source = Annotated[ExampleValue | ReadFrom, Field(discriminator="kind")]


class Named(_Frozen):
    """A name of the part (its maker, or the maker's part number), with where it came from."""

    value: Text
    source: Source


class Availability(_Frozen):
    """Whether the part can be bought: in stock, orderable, or not purchasable."""

    status: Literal["in_stock", "orderable", "not_purchasable"]
    source: Source


class Price(_Frozen):
    """The price of one piece: an amount and its currency code."""

    value: Annotated[float | int, Field(ge=0)]
    unit: Annotated[str, StringConstraints(pattern=r"^[A-Z]{3}$")]
    source: Source


class Count(_Frozen):
    """A whole number of pieces, unit ``1``."""

    value: Annotated[int, Field(ge=1)]
    unit: Literal["1"]


class SourcedCount(Count):
    """A count the sheet states, with where it came from."""

    source: Source


class LeadTime(_Frozen):
    """How long the part takes to arrive, and whether that is to Norway or only in general."""

    value: Annotated[float | int, Field(ge=0)]
    unit: Literal["d", "week"]
    scope: Literal["norway", "generic"]
    source: Source

    def days(self) -> Fraction:
        """The lead time in days, exactly."""
        return Fraction(self.value) * DAYS_PER_UNIT[self.unit]


class Facts(_Frozen):
    """The five facts of one part; any may be absent, and an absent one is named, never assumed."""

    availability: Availability | None = None
    unit_price: Price | None = None
    minimum_order_quantity: SourcedCount | None = None
    order_multiple: SourcedCount | None = None
    lead_time_to_norway: LeadTime | None = None


class Entry(_Frozen):
    """One purchasable part, and the plan node ids it answers."""

    answers: Annotated[tuple[Text, ...], Field(min_length=1)]
    description: Text
    maker: Named
    maker_part_number: Named | None
    facts: Facts


class Header(_Frozen):
    """What the sheet is: an example fixture, for which plan's names, written on which date."""

    kind: Literal["example fixture"]
    statement: Text
    written_for: Text
    written_on: datetime.date


class Sheet(_Frozen):
    """A price sheet: its header and its entries, no node id answered twice."""

    header: Header
    entries: tuple[Entry, ...]

    @model_validator(mode="after")
    def _each_node_is_answered_once(self) -> Sheet:
        seen: set[str] = set()
        for entry in self.entries:
            for node in entry.answers:
                if node in seen:
                    msg = f"the node id {node!r} is answered by more than one entry"
                    raise ValueError(msg)
                seen.add(node)
        return self

    def entry_for(self, node: str) -> Entry | None:
        """The entry that names ``node`` exactly, or ``None``: no label or partial match."""
        for entry in self.entries:
            if node in entry.answers:
                return entry
        return None


def _first_problem(exc: ValidationError) -> str:
    error = exc.errors()[0]
    where = ".".join(str(part) for part in error["loc"]) or "the top"
    return f"{where}: {error['msg']}"


def load_sheet(path: Path) -> Sheet:
    """The sheet at ``path``, validated as a whole.

    Raises:
        SheetError: the file cannot be read, or is not a sheet (a bare number among them).
    """
    try:
        raw = Path(path).read_bytes()
    except OSError as exc:
        msg = f"the price sheet cannot be read: {exc.strerror}"
        raise SheetError(msg) from None
    try:
        return Sheet.model_validate_json(raw)
    except ValidationError as exc:
        msg = f"the price sheet is not one this check reads ({_first_problem(exc)})"
        raise SheetError(msg) from None


class Quantities(_Frozen):
    """The quantity needed of each line, as a person stated it for this check."""

    stated_by: Text
    quantities: dict[Text, Count]


def load_quantities(path: Path) -> Quantities:
    """The quantities a person gave in the file at ``path``.

    Raises:
        SheetError: the file cannot be read, or a quantity is not a count with its unit.
    """
    try:
        raw = Path(path).read_bytes()
    except OSError as exc:
        msg = f"the quantities file cannot be read: {exc.strerror}"
        raise SheetError(msg) from None
    try:
        return Quantities.model_validate_json(raw)
    except ValidationError as exc:
        msg = f"the quantities file is not one this check reads ({_first_problem(exc)})"
        raise SheetError(msg) from None
