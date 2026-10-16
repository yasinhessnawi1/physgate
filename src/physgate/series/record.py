"""A series record: one simulation run's output, as named traces with a unit on every axis.

A record is evidence, never design state: it lives beside the run, is sealed when the
session that wrote it ends, and never enters the design-state graph. A graph quantity
may name a record it was computed from, and is then checked against it.

**The format is columnar JSON, one file per record.** One x axis, time or frequency,
and one to :data:`MAX_TRACES` traces sharing it, each a column of numbers with exactly
one unit. That is the shape the operator UI's plot takes (shared x values, one unit per
axis), so the UI draws a record without a second parser. Units are written once per
axis rather than once per sample, and a file cut short is not JSON at all, so it is
refused rather than read as a shorter run.

**What makes a record admissible**, each refused with its reason:

- every axis carries a unit, non-empty, that the physics gate's own unit registry
  parses; a logarithmic unit (``dB`` and its kin) is refused, because the registry reads
  a decibel as a power ratio where a loop's magnitude is an amplitude ratio, and a
  magnitude is therefore recorded as a plain ratio;
- every sample is a finite number: not a boolean, not a string, not ``NaN`` or an
  infinity, including one that overflows to infinity from a literal such as ``1e999``,
  which a plain JSON read accepts;
- x is strictly increasing, its unit is a time on a time axis and a reciprocal time on a
  frequency axis, and a frequency is positive;
- every trace has exactly one value per x, and trace names are distinct;
- every input the run took is a value with a unit, the seed included;
- the code that produced it is named: the script, and every file of code the producing
  process loaded from outside the interpreter, each with the digest of its bytes as the
  writer saw them. Whether that code may stand behind a record is the collector's
  judgement, not this schema's;
- nothing exceeds the bounds below, and no JSON object repeats a key: a plain JSON read
  keeps the last of two equal keys silently, so a record could otherwise say two things.

Validation is strict, as the graph's is: nothing is coerced but an integer to a float,
which JSON cannot tell apart.
"""

from __future__ import annotations

import json
from collections.abc import Mapping
from typing import Annotated, Any, Literal

from pydantic import (
    AfterValidator,
    BaseModel,
    ConfigDict,
    Field,
    StringConstraints,
    ValidationError,
    model_validator,
)

from physgate.gate import units
from physgate.series.exceptions import RecordRefusedError
from physgate.series.seal import NAME_PATTERN as NAME_PATTERN
from physgate.unit_spelling import UNIT_SPELLING, UnitSpellingError, require_bounded_spelling

#: The marker every record carries. A later shape is a new marker and a new model.
FORMAT = "series.v1"
#: The most samples one axis may hold.
MAX_SAMPLES = 100_000
#: The most traces one record may hold.
MAX_TRACES = 32
#: The most bytes one record's file may hold.
MAX_FILE_BYTES = 4 * 1024 * 1024
#: The most records one session may leave, and the most bytes they may hold together.
MAX_RECORDS_PER_SESSION = 256
MAX_SESSION_BYTES = 64 * 1024 * 1024
#: The most inputs one record may name.
MAX_INPUTS = 64
#: The most files of code one record may name as loaded.
MAX_LOADED = 256
#: The longest title, and the longest path of a file of code.
MAX_TITLE = 200
MAX_PATH = 512

Name = Annotated[str, StringConstraints(pattern=NAME_PATTERN)]
Sha256 = Annotated[str, StringConstraints(pattern=r"^[0-9a-f]{64}$")]


#: How a unit must be spelt before the registry sees it, so that parsing it has a bounded
#: cost: the shared guard for units written by roles (:mod:`physgate.unit_spelling`).
UNIT_GRAMMAR = UNIT_SPELLING


def _unit(unit: str) -> str:
    """``unit`` if it is one a record may carry; refused otherwise."""
    if not unit.strip():
        msg = "a unit is required on every axis; an empty one is not a unit"
        raise ValueError(msg)
    try:
        require_bounded_spelling(unit)
    except UnitSpellingError as exc:
        raise ValueError(str(exc)) from None
    try:
        quantity = units.parse(1, unit)
    except units.UnitRefusedError as exc:
        raise ValueError(str(exc)) from None
    # The registry's own record of how each unit converts. A logarithmic converter is
    # how pint marks the decibel, the neper and their kin (pint 0.26.x, measured).
    registry = quantity._REGISTRY
    for name in quantity._units:
        if getattr(registry._units[name].converter, "is_logarithmic", False):
            msg = f"the unit {unit!r} is logarithmic; record a magnitude as a plain ratio"
            raise ValueError(msg)
    return unit


Unit = Annotated[str, StringConstraints(min_length=1, max_length=64), AfterValidator(_unit)]


def _code_path(path: str) -> str:
    """``path`` if it names a file of code without a parent step or a NUL."""
    if "\0" in path or ".." in path.split("/"):
        msg = "a file of code is named by a path with no parent step and no NUL"
        raise ValueError(msg)
    return path


CodePath = Annotated[
    str, StringConstraints(min_length=1, max_length=MAX_PATH), AfterValidator(_code_path)
]


class _Frozen(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid", strict=True, allow_inf_nan=False)


class Column(_Frozen):
    """One axis or trace: its name, its one unit, and its samples."""

    name: Name
    unit: Unit
    values: Annotated[tuple[float, ...], Field(min_length=1, max_length=MAX_SAMPLES)]


#: The largest integer an input may hold: a 64-bit seed fits, and every such integer is a
#: finite float. JSON's integers are unbounded, and a 400-digit one would otherwise pass
#: as a finite input that no float can hold (found by a review, 16.10.2026).
MAX_INPUT_INTEGER = 2**63 - 1


def _bounded(value: float | int) -> float | int:
    if isinstance(value, int) and abs(value) > MAX_INPUT_INTEGER:
        msg = f"an integer input is at most {MAX_INPUT_INTEGER} in size"
        raise ValueError(msg)
    return value


class Input(_Frozen):
    """One input the run took: a value with its unit. A seed is ``dimensionless``."""

    value: Annotated[float | int, AfterValidator(_bounded)]
    unit: Unit


class CodeFile(_Frozen):
    """A file of code, and the digest of its bytes as the writer read them.

    The path is relative to the worktree when the file lies in it, absolute otherwise.
    """

    path: CodePath
    sha256: Sha256


class Producer(_Frozen):
    """The code that produced a record: the script that ran, and every file it loaded."""

    script: CodeFile
    loaded: Annotated[tuple[CodeFile, ...], Field(max_length=MAX_LOADED)] = ()


def _dimension(unit: str) -> Any:
    return units.parse(1, unit).dimensionality


class Record(_Frozen):
    """One simulation run's output: a shared x axis, its traces, and how it was produced."""

    format: Literal["series.v1"]
    id: Name
    title: Annotated[str, StringConstraints(min_length=1, max_length=MAX_TITLE)]
    group: Name | None = None
    axis: Literal["time", "frequency"]
    x: Column
    traces: Annotated[tuple[Column, ...], Field(min_length=1, max_length=MAX_TRACES)]
    inputs: Annotated[dict[Name, Input], Field(max_length=MAX_INPUTS)] = Field(default_factory=dict)
    producer: Producer

    @model_validator(mode="after")
    def _the_axis_holds_together(self) -> Record:
        expected = _dimension("s") if self.axis == "time" else _dimension("1/s")
        if _dimension(self.x.unit) != expected:
            what = "a time" if self.axis == "time" else "a reciprocal time (rad/s, Hz)"
            msg = f"a {self.axis} axis is in {what}, and {self.x.unit!r} is not"
            raise ValueError(msg)
        values = self.x.values
        if any(later <= earlier for earlier, later in zip(values, values[1:], strict=False)):
            msg = "the x axis is not strictly increasing"
            raise ValueError(msg)
        if self.axis == "frequency" and values[0] <= 0:
            msg = "a frequency axis holds only positive frequencies"
            raise ValueError(msg)
        names = [trace.name for trace in self.traces]
        if len(set(names)) != len(names):
            msg = "two traces share a name"
            raise ValueError(msg)
        for trace in self.traces:
            if len(trace.values) != len(values):
                msg = f"the trace {trace.name!r} does not have one value per x"
                raise ValueError(msg)
        return self


def _refuse_constant(token: str) -> float:
    msg = f"{token} is not a finite number"
    raise ValueError(msg)


def _refuse_repeated_keys(pairs: list[tuple[str, Any]]) -> Mapping[str, Any]:
    found: dict[str, Any] = {}
    for key, value in pairs:
        if key in found:
            msg = f"the key {key!r} appears twice in one object"
            raise ValueError(msg)
        found[key] = value
    return found


#: How deep a record nests: record, traces, a trace, its values, a value is five levels.
MAX_DEPTH = 8


def _as_validated(parsed: Mapping[str, Any]) -> dict[str, Any]:
    """The parsed record with its arrays as tuples, held to the format's depth.

    The walk that checks the depth is iterative, so a nesting the JSON parser accepted
    cannot exhaust the stack here; the conversion after it recurses at most
    :data:`MAX_DEPTH` levels. A string that cannot be written back as UTF-8 (a lone
    surrogate, which the parser accepts from an escape) is refused, so every record read
    can be served as it was read.

    Raises:
        RecordRefusedError: the nesting is deeper than the format's, or a string is not
            encodable.
    """
    stack: list[tuple[Any, int]] = [(parsed, 1)]
    while stack:
        node, depth = stack.pop()
        if depth > MAX_DEPTH:
            msg = f"a record nests at most {MAX_DEPTH} levels deep"
            raise RecordRefusedError(msg)
        if isinstance(node, Mapping):
            for name, value in node.items():
                _encodable(name)
                stack.append((value, depth + 1))
        elif isinstance(node, list):
            stack.extend((value, depth + 1) for value in node)
        elif isinstance(node, str):
            _encodable(node)
    return {name: _tuples(value) for name, value in parsed.items()}


def _encodable(text: str) -> None:
    try:
        text.encode("utf-8")
    except UnicodeEncodeError:
        msg = "a record's text holds a character that is not valid UTF-8 (a lone surrogate)"
        raise RecordRefusedError(msg) from None


def _tuples(node: Any) -> Any:
    if isinstance(node, Mapping):
        return {name: _tuples(value) for name, value in node.items()}
    if isinstance(node, list):
        return tuple(_tuples(value) for value in node)
    return node


def _first_problem(exc: ValidationError) -> str:
    first = exc.errors()[0]
    where = ".".join(str(part) for part in first["loc"]) or "the record"
    return f"{where}: {first['msg']}"


def parse_record(data: bytes) -> Record:
    """The record ``data`` holds, if it is one this format admits.

    Raises:
        RecordRefusedError: it is too large, not UTF-8, not one JSON object, repeats a
            key, holds a non-finite constant, or does not validate; the reason says which.
    """
    if len(data) > MAX_FILE_BYTES:
        msg = f"a record holds at most {MAX_FILE_BYTES} bytes"
        raise RecordRefusedError(msg, bytes=str(len(data)))
    try:
        text = data.decode("utf-8")
        parsed = json.loads(
            text, parse_constant=_refuse_constant, object_pairs_hook=_refuse_repeated_keys
        )
    except (UnicodeDecodeError, ValueError, RecursionError) as exc:
        msg = f"a record is one UTF-8 JSON object ({type(exc).__name__}: {exc})"
        raise RecordRefusedError(msg) from None
    if not isinstance(parsed, Mapping):
        msg = "a record is one JSON object"
        raise RecordRefusedError(msg)
    # One parse, and the schema validates exactly what it produced. Validating the bytes a
    # second time, with another JSON parser, would let the two disagree: the record's
    # checks would run on one reading and the record returned would be the other.
    normalised = _as_validated(parsed)
    try:
        return Record.model_validate(normalised)
    except ValidationError as exc:
        msg = f"a record does not validate: {_first_problem(exc)}"
        raise RecordRefusedError(msg, record=str(parsed.get("id"))[:64]) from None
