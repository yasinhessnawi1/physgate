"""The bounds table: sourced ranges for magnitudes, per domain, read from protected files.

Each domain has its own directory under the tracked ``knowledge/`` tree, and
its bounds table is the one file in it named ``bounds.toml``. No agent session
can widen a range to make its own number pass: the physics gate always builds
in the orchestrator's own live process, from whatever checkout is driving the
run, never through the read-only installation copy a role session's hooks run
from, and a role or reviewer session's own hooks protect every curated domain
directory under ``knowledge/`` the same way they protect the gate itself. Each
range names the quantity, the bounds and their unit, the class of component it
is for, its source, the date the source was read, and a note on what the range
is and is not.

**A range without a source does not load, and a table that does not load stops
the gate from being built.** A bound nobody can trace is a number invented to
make a fixture pass, and a check against it measures nothing. Every record the
magnitude check writes carries the digest of the file it read.
"""

from __future__ import annotations

import hashlib
import tomllib
from collections.abc import Mapping
from datetime import date
from pathlib import Path
from types import MappingProxyType
from typing import Annotated

from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    StringConstraints,
    ValidationError,
    model_validator,
)

from physgate.gate.catalogue import kind_of
from physgate.gate.exceptions import GateError
from physgate.gate.units import PINT_ERRORS, UnitRefusedError, measure
from physgate.state.schema import DomainKind

#: One file name, one per domain directory.
BOUNDS_NAME = "bounds.toml"

#: Where the domain directories are: the tracked ``knowledge/`` tree, beside
#: ``src/`` at the repository root (gate -> physgate -> src -> the repository
#: root, four parents up from this module). This only resolves inside a live
#: checkout, which is exactly where the gate always builds: in the
#: orchestrator's own process, never through the read-only installation copy
#: a role session's hooks run from (verified: that copy is invoked only for
#: ``hooks install``, never to run a gate check).
KNOWLEDGE_DIR = Path(__file__).resolve().parents[3] / "knowledge"

_Text = Annotated[str, StringConstraints(min_length=1, strip_whitespace=True)]


class BoundsTableError(GateError):
    """A bounds table that does not load: missing a source, a date, or a sound range."""


class _Frozen(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid", strict=True, allow_inf_nan=False)


class Range(_Frozen):
    """One sourced range for one quantity."""

    model_config = ConfigDict(populate_by_name=True)

    quantity: _Text
    low: float | int
    high: float | int
    unit: _Text
    component_class: _Text = Field(alias="class")
    source: _Text
    retrieved: date
    note: _Text

    @model_validator(mode="after")
    def _sound(self) -> Range:
        kind = kind_of(self.quantity)
        if kind is None:
            msg = f"the catalogue does not know the quantity {self.quantity!r}"
            raise ValueError(msg)
        if self.low > self.high:
            msg = f"the range for {self.quantity} runs from {self.low} down to {self.high}"
            raise ValueError(msg)
        try:
            measure(kind, self.low, self.unit)
        except (UnitRefusedError, *PINT_ERRORS) as exc:
            msg = f"the unit {self.unit!r} is not one a {kind.name} is written in: {exc}"
            raise ValueError(msg) from None
        return self


class _Meta(_Frozen):
    domain: DomainKind
    curated_by: _Text


class _File(_Frozen):
    meta: _Meta
    range: Annotated[list[Range], Field(min_length=1)]


class BoundsTable(_Frozen):
    """One domain's ranges, and the digest of the file they came from."""

    domain: DomainKind
    ranges: Mapping[str, Range]
    sha256: Annotated[str, StringConstraints(pattern=r"^[0-9a-f]{64}$")]
    path: _Text


class Bounds:
    """Every domain's table, as the magnitude check reads them."""

    def __init__(self, tables: Mapping[str, BoundsTable]) -> None:
        """Hold ``tables``, keyed by domain."""
        self.tables: Mapping[str, BoundsTable] = MappingProxyType(dict(tables))

    def lookup(self, domain: str, quantity: str) -> tuple[Range, BoundsTable] | None:
        """The range for ``quantity`` in ``domain``, with its table, or ``None``."""
        table = self.tables.get(domain)
        if table is None or quantity not in table.ranges:
            return None
        return table.ranges[quantity], table


def load_table(path: Path) -> BoundsTable:
    """Load one domain's table.

    Raises:
        BoundsTableError: the file is not TOML, its directory is not named for
            its domain, or a range lacks a field, a source, a date, a sound
            interval or a unit its quantity's kind accepts.
    """
    raw = Path(path).read_bytes()
    try:
        parsed = _File.model_validate(tomllib.loads(raw.decode()))
    except (tomllib.TOMLDecodeError, UnicodeDecodeError) as exc:
        msg = "a bounds table is not TOML"
        raise BoundsTableError(msg, path=str(path), reason=str(exc)) from None
    except ValidationError as exc:
        first = exc.errors()[0]
        where = ".".join(str(p) for p in first["loc"])
        msg = "a bounds table does not load"
        raise BoundsTableError(msg, path=str(path), where=where, reason=first["msg"]) from None
    if parsed.meta.domain != Path(path).parent.name:
        msg = "a bounds table's directory is named for another domain than it declares"
        raise BoundsTableError(msg, path=str(path), declared=parsed.meta.domain)
    names = [r.quantity for r in parsed.range]
    if len(set(names)) != len(names):
        msg = "a bounds table gives one quantity two ranges"
        raise BoundsTableError(msg, path=str(path))
    return BoundsTable(
        domain=parsed.meta.domain,
        ranges=MappingProxyType({r.quantity: r for r in parsed.range}),
        sha256=hashlib.sha256(raw).hexdigest(),
        path=str(path),
    )


def load_bounds(directory: Path = KNOWLEDGE_DIR) -> Bounds:
    """Load every domain's ``bounds.toml`` found one level under ``directory``.

    Raises:
        BoundsTableError: any table does not load, or there is none.
    """
    paths = sorted(Path(directory).glob(f"*/{BOUNDS_NAME}"))
    if not paths:
        msg = "no bounds table was found"
        raise BoundsTableError(msg, directory=str(directory))
    return Bounds({table.domain: table for table in map(load_table, paths)})
