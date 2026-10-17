"""The base of every per-role record: a number with its unit, and the identifiers.

Every number is a ``{value, unit}`` pair, validated strictly, the unit held to a spelling
whose parse has a bounded cost. A bare number, NaN, infinity or an empty unit is refused.
"""

from __future__ import annotations

from typing import Annotated

from pydantic import AfterValidator, BaseModel, ConfigDict, StringConstraints

from physgate.unit_spelling import UnitSpellingError, require_bounded_spelling

#: A task id, a spec name, a metric name and a requirement id: lower-case identifiers,
#: because they become file names and keys in records.
Identifier = Annotated[str, StringConstraints(pattern=r"^[a-z][a-z0-9_]*$", max_length=64)]


def _spelt(unit: str) -> str:
    try:
        return require_bounded_spelling(unit)
    except UnitSpellingError as exc:
        raise ValueError(str(exc)) from exc


Unit = Annotated[str, StringConstraints(min_length=1), AfterValidator(_spelt)]


class _Frozen(BaseModel):
    model_config = ConfigDict(frozen=True, strict=True, extra="forbid", allow_inf_nan=False)


class Measure(_Frozen):
    """A number with its unit: the only way a number appears in a task or an answer."""

    value: float | int
    unit: Unit


class NamedMeasure(Measure):
    """A measure with a name: an input the brief gives, or a scorer parameter."""

    name: Identifier
