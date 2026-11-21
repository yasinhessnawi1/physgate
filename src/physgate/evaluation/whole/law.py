"""A sampled linear law: how a design states its control law, and what is done with it.

A design's control law is a sampled linear map from what the kit measures to the motor command,
with a few memory states (a leaky tilt estimate, the previous encoder angle, the previous
command). The closed list of named structures holds three such laws; a design whose law is
none of them states it here, in words a control engineer already writes it in, and the scorer
turns that into the matrices its loop analysis already uses. Nothing here is executed from a
run: the description is data, held to a schema and to bounds before any number in it is used,
and no code of a run is ever imported.

**The form.** One update reads the signals, forms the ordered ``lines``, and sets each memory
state from one of them. A line is a sum of terms; a term is a sign, a number, named coefficients
(and the reciprocals of named coefficients) and exactly one variable: a signal, the previous value
of a memory state (``previous.<state>``), or an earlier line (``line.<line>``). A product of two
variables, a function, a comparison: none can be written, so the law is linear by construction,
and a file that tries is refused by name (``nonlinear``) rather than scored.

**The closed list of signals**, each in the unit given here and in SI (the scorer's convention):

- ``tilt``, the body's tilt from vertical, rad, positive leaning forward;
- ``tilt_rate``, its rate, rad/s (the gyro);
- ``wheel_angle``, the mean of the two wheels' turn relative to the body, rad, positive rolling
  forward (the encoders; the ground travel less ``r·tilt``, over the wheel radius);
- ``wheel_speed``, its rate, rad/s;
- ``wheel_reference``, the wheel angle the law holds, rad: zero in the loop the scorer analyses
  (the loop is judged on deviations from its reference) and the vector's own in a test vector.

A design that needs a signal outside the list (an accelerometer's tilt, say) is out of the
scorer's scope, refused by name (``out_of_scope``) and never scored as a fail.

**The coefficients** are named by the design, each ``{value, unit}`` as the graph holds it. The
reserved name ``period`` is the loop's own period, in s. Units are checked line by line: every
term's coefficients, reciprocals and variable multiply to the line's unit, and the command's is
``1``. A wrong sign is not caught by units; a wrong scale is.

**The command** is the line named ``command``'s value (a duty, before the limit). A memory state
marked ``applied`` holds the command as applied: clamped to the limit and rounded to whole counts
in a test vector, and the linear command in the loop analysis, where the limit and the integer
rounding are outside the linear loop, as for every named structure.
"""

from __future__ import annotations

import math
import re
from collections.abc import Mapping
from typing import Annotated, Literal

from pydantic import (
    AfterValidator,
    BaseModel,
    ConfigDict,
    Field,
    StringConstraints,
    ValidationError,
    model_validator,
)

from physgate.unit_spelling import UnitSpellingError, canonical_unit, require_bounded_spelling

#: The signals a law may read, each with its unit, in the order a controller's inputs are.
SIGNALS: dict[str, str] = {
    "tilt": "rad",
    "tilt_rate": "rad/s",
    "wheel_angle": "rad",
    "wheel_speed": "rad/s",
    "wheel_reference": "rad",
}
#: The signals the loop analysis feeds; the reference is zero there.
LOOP_SIGNALS = ("tilt", "tilt_rate", "wheel_angle", "wheel_speed")
#: The reserved coefficient: the loop's period, in s.
PERIOD = "period"

#: The most memory states, lines, terms, coefficients and factors a law may have. Chosen: the
#: reference law has 3 states, 5 lines and 6 terms in a line; these leave room and bound the
#: work (the closed loop's state count) and the size of a crafted description.
MAX_MEMORY = 8
MAX_LINES = 32
MAX_TERMS = 16
MAX_COEFFICIENTS = 32
MAX_FACTORS = 4
MAX_VECTORS = 32
MAX_ROWS = 64
MAX_TOTAL_ROWS = 512

Name = Annotated[str, StringConstraints(pattern=r"^[a-z][a-z0-9_]{0,31}$")]

_FACTOR = re.compile(r"([A-Za-z_\u00b5\u03bc\u03a9]+)(?:\*\*(-?[0-9]{1,2}))?")
#: What a unit's symbols stand for: ``Hz`` is exactly one per second, nothing else is rewritten.
_ALIASES: dict[str, dict[str, int]] = {"Hz": {"s": -1}}

Dimension = tuple[tuple[str, int], ...]


class LawRefused(Exception):  # noqa: N818 - a refusal by name, not an error of the scorer
    """The description cannot be used, for the reason named by ``code``.

    ``code`` is one of ``malformed``, ``nonlinear``, ``out_of_scope``, ``units_do_not_balance``,
    ``coefficient_not_held`` and ``vector_not_reproduced``; ``detail`` says what, in words.
    """

    def __init__(self, code: str, detail: str) -> None:
        """Keep the refusal's name and its detail."""
        super().__init__(f"{code}: {detail}")
        self.code = code
        self.detail = detail


def dimension(unit: str) -> Dimension:
    """``unit`` as its symbols with their exponents, ``Hz`` as ``s**-1``, ``1`` as nothing.

    Spelt as the rest of the repository spells a unit (:mod:`physgate.unit_spelling`): the
    same grammar that reads every quantity's unit reads a law's.

    Raises:
        LawRefused: ``malformed``: the unit is not spelt in that grammar.
    """
    try:
        canonical = canonical_unit(require_bounded_spelling(unit))
    except UnitSpellingError as exc:
        raise LawRefused("malformed", f"the unit {unit!r} is not a unit") from exc
    exponents: dict[str, int] = {}
    for symbol, power in _FACTOR.findall(canonical):
        times = int(power) if power else 1
        for name, exponent in _ALIASES.get(symbol, {symbol: 1}).items():
            exponents[name] = exponents.get(name, 0) + times * exponent
    return tuple(sorted((n, e) for n, e in exponents.items() if e))


def _product(parts: list[tuple[Dimension, int]]) -> Dimension:
    exponents: dict[str, int] = {}
    for dim, times in parts:
        for name, exponent in dim:
            exponents[name] = exponents.get(name, 0) + times * exponent
    return tuple(sorted((n, e) for n, e in exponents.items() if e))


class _Frozen(BaseModel):
    model_config = ConfigDict(frozen=True, strict=True, extra="forbid", allow_inf_nan=False)


def _finite_number(value: float) -> float:
    if not math.isfinite(value):
        msg = "a number is finite"
        raise ValueError(msg)
    return value


class Term(_Frozen):
    """One term of a line: ``sign · number · Π coefficients / Π per · of``."""

    sign: Literal[1, -1]
    number: Annotated[float | int, AfterValidator(_finite_number)] = 1
    coefficients: tuple[Name, ...] = Field(default=(), max_length=MAX_FACTORS)
    per: tuple[Name, ...] = Field(default=(), max_length=MAX_FACTORS)
    of: str = Field(max_length=80)


class Line(_Frozen):
    """A named quantity formed each update: a sum of terms, in ``unit``."""

    name: Name
    unit: str = Field(max_length=40)
    terms: tuple[Term, ...] = Field(min_length=1, max_length=MAX_TERMS)


class Memory(_Frozen):
    """A memory state: its unit, the line that gives its next value, and whether it is applied."""

    name: Name
    unit: str = Field(max_length=40)
    next: Name
    applied: bool = False


class Body(_Frozen):
    """The law itself: memory, ordered lines and the command's line, without any number."""

    memory: tuple[Memory, ...] = Field(default=(), max_length=MAX_MEMORY)
    lines: tuple[Line, ...] = Field(min_length=1, max_length=MAX_LINES)
    command: Name

    @model_validator(mode="after")
    def _names_are_distinct(self) -> Body:
        names = [m.name for m in self.memory] + [line.name for line in self.lines]
        if len(set(names)) != len(names) or set(names) & (set(SIGNALS) | {PERIOD}):
            msg = "a memory state or a line is named twice, or after a signal or the period"
            raise ValueError(msg)
        return self


#: What a term's ``of`` may be written as: a bare name, or ``previous.`` or ``line.`` and a name.
_OF = re.compile(r"^(?:(previous|line)\.)?([a-z][a-z0-9_]*)$")


def scope(raw: object) -> None:
    """Refuse by name what no linear law over the closed list of signals can be.

    Looks at the description as written, before a schema reads it, so a term that tries a
    function, a product, or a signal outside the list is named for what it is.

    Raises:
        LawRefused: ``nonlinear``, or ``out_of_scope``.
    """
    if not isinstance(raw, dict):
        return
    for line in raw.get("lines", ()):
        if not isinstance(line, dict):
            continue
        for term in line.get("terms", ()):
            if not isinstance(term, dict):
                continue
            extra = sorted(set(term) - set(Term.model_fields))
            if extra:
                msg = (
                    f"line {line.get('name')!r} has a term with {', '.join(extra)}; a term is "
                    "a sign, a number, coefficients and one variable"
                )
                raise LawRefused("nonlinear", msg)
            of = term.get("of")
            if not isinstance(of, str):
                continue
            found = _OF.match(of)
            if found is None:
                msg = f"line {line.get('name')!r} reads {of!r}, which is not one variable"
                raise LawRefused("nonlinear", msg)
            kind, name = found.groups()
            if kind is None and name not in SIGNALS:
                msg = (
                    f"line {line.get('name')!r} reads {name!r}, a signal outside the closed "
                    f"list ({', '.join(SIGNALS)})"
                )
                raise LawRefused("out_of_scope", msg)


def check(body: Body, units: Mapping[str, str]) -> None:
    """Hold ``body`` to its own names, its order and its units, ``units`` the coefficients'.

    ``units`` maps each coefficient name the law may use to its unit; ``period`` is added.

    Raises:
        LawRefused: ``malformed`` (a name used before it exists, a command that is not a
            line, an applied state that is not the command's), or ``units_do_not_balance``.
    """
    coefficient_units = {**units, PERIOD: "s"}
    memory = {m.name: m for m in body.memory}
    lines: dict[str, Line] = {}
    for line in body.lines:
        line_dim = dimension(line.unit)
        for term in line.terms:
            parts: list[tuple[Dimension, int]] = []
            for name in term.coefficients:
                parts.append((_known(coefficient_units, name, line.name), 1))
            for name in term.per:
                parts.append((_known(coefficient_units, name, line.name), -1))
            parts.append((_variable(term.of, memory, lines, line.name), 1))
            if _product(parts) != line_dim:
                msg = (
                    f"in line {line.name!r}, a term in {term.of!r} is not in {line.unit!r}: its "
                    f"coefficients and variable multiply to {_spelt(_product(parts))}"
                )
                raise LawRefused("units_do_not_balance", msg)
        lines[line.name] = line
    command = lines.get(body.command)
    if command is None or dimension(command.unit) != ():
        msg = f"the command {body.command!r} is not a line in the unit '1'"
        raise LawRefused("units_do_not_balance" if command else "malformed", msg)
    for state in memory.values():
        source = lines.get(state.next)
        if source is None:
            msg = f"the memory state {state.name!r} takes its next value from no line"
            raise LawRefused("malformed", msg)
        if dimension(source.unit) != dimension(state.unit):
            msg = (
                f"the memory state {state.name!r} is in {state.unit!r}, its line in {source.unit!r}"
            )
            raise LawRefused("units_do_not_balance", msg)
        if state.applied and (state.next != body.command or dimension(state.unit) != ()):
            msg = f"the memory state {state.name!r} is applied, so it is the command in '1'"
            raise LawRefused("malformed", msg)


def _spelt(dim: Dimension) -> str:
    return "*".join(f"{n}**{e}" for n, e in dim) or "1"


def _known(units: Mapping[str, str], name: str, line: str) -> Dimension:
    if name not in units:
        msg = f"line {line!r} uses the coefficient {name!r}, which the law does not declare"
        raise LawRefused("malformed", msg)
    return dimension(units[name])


def _variable(
    of: str, memory: Mapping[str, Memory], lines: Mapping[str, Line], line: str
) -> Dimension:
    found = _OF.match(of)
    if found is None:
        msg = f"line {line!r} reads {of!r}, which is not one variable"
        raise LawRefused("nonlinear", msg)
    kind, name = found.groups()
    if kind is None:
        if name not in SIGNALS:
            msg = f"line {line!r} reads {name!r}, a signal outside the closed list"
            raise LawRefused("out_of_scope", msg)
        return dimension(SIGNALS[name])
    table = memory if kind == "previous" else lines
    held = table.get(name)
    if held is None:
        what = "a memory state" if kind == "previous" else "an earlier line"
        msg = f"line {line!r} reads {of!r}, which is not {what}"
        raise LawRefused("malformed", msg)
    return dimension(held.unit)


# ── what the law does ───────────────────────────────────────────────────────────────────────


def _term(
    term: Term,
    coefficients: Mapping[str, float],
    variable: list[float],
) -> list[float]:
    scale = float(term.sign) * float(term.number)
    for name in term.coefficients:
        scale *= coefficients[name]
    for name in term.per:
        scale /= coefficients[name]
    return [scale * v for v in variable]


def _coefficients(values: Mapping[str, float], period: float) -> dict[str, float]:
    return {**values, PERIOD: period}


def evaluate(
    body: Body,
    values: Mapping[str, float],
    *,
    period: float,
    state: Mapping[str, float],
    signals: Mapping[str, float],
) -> tuple[float, dict[str, float]]:
    """One update: the command before any limit, and each memory state's next value.

    ``values`` holds each coefficient's number as the graph holds it; ``state`` each memory
    state before the update, ``signals`` each signal this update (a missing one is 0).
    """
    coefficients = _coefficients(values, period)
    lines: dict[str, float] = {}
    for line in body.lines:
        total = 0.0
        for term in line.terms:
            kind, name = _OF.match(term.of).groups()  # type: ignore[union-attr]
            if kind is None:
                variable = signals.get(name, 0.0)
            elif kind == "previous":
                variable = state[name]
            else:
                variable = lines[name]
            total += _term(term, coefficients, [variable])[0]
        lines[line.name] = total
    return lines[body.command], {m.name: lines[m.next] for m in body.memory}


def linear(
    body: Body, values: Mapping[str, float], *, period: float
) -> tuple[
    tuple[tuple[float, ...], ...],
    tuple[tuple[float, ...], ...],
    tuple[float, ...],
    tuple[float, ...],
]:
    """The law as ``(A, B, C, D)``.

    Memory next = A·memory + B·inputs, command = C·memory + D·inputs.

    The inputs are :data:`LOOP_SIGNALS`, the reference being zero. Exact for a linear law: each
    variable is carried as its row over (the previous memory, the inputs).
    """
    n, k = len(body.memory), len(LOOP_SIGNALS)
    coefficients = _coefficients(values, period)
    basis: dict[str, list[float]] = {}
    for i, m in enumerate(body.memory):
        basis[f"previous.{m.name}"] = [1.0 if j == i else 0.0 for j in range(n + k)]
    for i, name in enumerate(LOOP_SIGNALS):
        basis[name] = [1.0 if j == n + i else 0.0 for j in range(n + k)]
    basis["wheel_reference"] = [0.0] * (n + k)
    for line in body.lines:
        row = [0.0] * (n + k)
        for term in line.terms:
            found = _OF.match(term.of)
            assert found is not None  # held by check()
            kind, name = found.groups()
            key = name if kind is None else f"{kind}.{name}"
            row = [a + b for a, b in zip(row, _term(term, coefficients, basis[key]), strict=True)]
        basis[f"line.{line.name}"] = row
    rows = [basis[f"line.{m.next}"] for m in body.memory]
    command = basis[f"line.{body.command}"]
    return (
        tuple(tuple(r[:n]) for r in rows),
        tuple(tuple(r[n:]) for r in rows),
        tuple(command[:n]),
        tuple(command[n:]),
    )


def counts(duty: float, limit: float, full_scale: float) -> int:
    """``duty`` held to ``±limit``, rounded to whole counts of ``full_scale``, half away from 0."""
    held = min(max(duty, -limit), limit)
    whole = math.floor(abs(held) * full_scale + 0.5)
    return int(whole if held >= 0 else -whole)


#: A vector's duty and memory are printed to six decimals, so they must match to one in 100,000;
#: its command is whole counts, so it must match within one (the design note's own tolerance).
DUTY_TOLERANCE = 1e-5
COUNT_TOLERANCE = 1


def reproduce(
    body: Body,
    values: Mapping[str, float],
    vectors: tuple[Vector, ...],
    *,
    period: float,
    limit: float,
    full_scale: float,
) -> tuple[int, str | None]:
    """How many rows of ``vectors`` the law reproduces, and the first that it does not.

    Each vector starts from its own memory (a missing state is 0) and runs one update per row.
    A row holds when the duty before the limit and each named memory state are within
    :data:`DUTY_TOLERANCE` and the command, held to the limit and rounded to whole counts of
    ``full_scale``, within :data:`COUNT_TOLERANCE`. A state marked applied then holds that
    command as applied.
    """
    checked = 0
    for vector in vectors:
        state = {m.name: vector.start.get(m.name, 0.0) for m in body.memory}
        for at, row in enumerate(vector.rows, 1):
            signals = {name: getattr(row, name) for name in SIGNALS}
            duty, following = evaluate(body, values, period=period, state=state, signals=signals)
            command = counts(duty, limit, full_scale)
            where = f"vector {vector.name!r}, update {at}"
            if not abs(duty - row.duty) <= DUTY_TOLERANCE:
                return checked, f"{where}: the duty is {duty:.6f}, the vector says {row.duty:.6f}"
            if abs(command - row.counts) > COUNT_TOLERANCE:
                return checked, f"{where}: the command is {command}, the vector says {row.counts}"
            for name, expected in row.memory.items():
                if name not in following:
                    return checked, f"{where}: the vector names {name!r}, which is no memory state"
                if not abs(following[name] - expected) <= DUTY_TOLERANCE:
                    got = following[name]
                    return checked, f"{where}: {name} is {got:.6f}, the vector says {expected:.6f}"
            state = {
                m.name: (command / full_scale if m.applied else following[m.name])
                for m in body.memory
            }
            checked += 1
    return checked, None


# ── the file ────────────────────────────────────────────────────────────────────────────────


class Source(_Frozen):
    """Where one loop quantity comes from on the graph: one name, a reciprocal, or a sum.

    ``reciprocal_of`` takes a rate in ``Hz`` to the period in ``s``; ``sum_of`` adds quantities
    in one unit. Nothing else is derived, and nothing is converted.
    """

    quantity: Name | None = None
    reciprocal_of: Name | None = None
    sum_of: tuple[Name, ...] | None = Field(default=None, min_length=1, max_length=4)

    @model_validator(mode="after")
    def _exactly_one(self) -> Source:
        given = [x for x in (self.quantity, self.reciprocal_of, self.sum_of) if x is not None]
        if len(given) != 1:
            msg = "a source is exactly one of quantity, reciprocal_of, sum_of"
            raise ValueError(msg)
        return self

    def names(self) -> tuple[str, ...]:
        """The graph names this source reads."""
        if self.quantity is not None:
            return (self.quantity,)
        if self.reciprocal_of is not None:
            return (self.reciprocal_of,)
        assert self.sum_of is not None
        return self.sum_of


class Row(_Frozen):
    """One update of a test vector: the signals in, the duty before the limit and the counts out."""

    tilt: float = 0.0
    tilt_rate: float = 0.0
    wheel_angle: float = 0.0
    wheel_speed: float = 0.0
    wheel_reference: float = 0.0
    duty: float
    counts: int
    memory: dict[Name, float] = Field(default_factory=dict, max_length=MAX_MEMORY)


class Vector(_Frozen):
    """A test vector: the memory it starts from and its rows, one update each."""

    name: str = Field(max_length=80)
    start: dict[Name, float] = Field(default_factory=dict, max_length=MAX_MEMORY)
    rows: tuple[Row, ...] = Field(min_length=1, max_length=MAX_ROWS)


class LawFile(Body):
    """The file a control module states its law in, beside its design note.

    ``coefficients`` maps each name the law uses to the graph's quantity holding it; the numbers
    stay on the graph. ``period``, ``command_limit``, ``sensor_delay`` and ``compute_delay`` say
    where the loop's timing comes from. ``vectors`` are the design note's own test vectors, the
    law's own check.
    """

    form: Literal["sampled_law_file"]
    version: Literal[1]
    period: Source
    command_limit: Source
    sensor_delay: Source
    compute_delay: Source
    coefficients: dict[Name, Name] = Field(max_length=MAX_COEFFICIENTS)
    vectors: tuple[Vector, ...] = Field(min_length=1, max_length=MAX_VECTORS)

    @model_validator(mode="after")
    def _bounded_vectors(self) -> LawFile:
        if PERIOD in self.coefficients:
            msg = "the period is the loop's own, not a coefficient"
            raise ValueError(msg)
        if sum(len(v.rows) for v in self.vectors) > MAX_TOTAL_ROWS:
            msg = f"the test vectors have more than {MAX_TOTAL_ROWS} rows"
            raise ValueError(msg)
        return self

    def graph_names(self) -> tuple[str, ...]:
        """Every name the file reads from the graph, sorted and without repeats."""
        names = set(self.coefficients.values())
        for source in (self.period, self.command_limit, self.sensor_delay, self.compute_delay):
            names.update(source.names())
        return tuple(sorted(names))


def parse_file(raw: bytes) -> LawFile:
    """``raw`` as a law file, or refused by name.

    Raises:
        LawRefused: ``malformed`` (not JSON, not the schema, too large), ``nonlinear`` or
            ``out_of_scope``.
    """
    import json  # noqa: PLC0415

    if len(raw) > MAX_FILE_BYTES:
        raise LawRefused("malformed", f"the law file is larger than {MAX_FILE_BYTES} bytes")
    try:
        text = raw.decode("utf-8")
        document = json.loads(text)
    except (UnicodeDecodeError, ValueError, RecursionError) as exc:
        raise LawRefused("malformed", "the law file is not JSON") from exc
    scope(document)
    try:
        return LawFile.model_validate_json(text)
    except ValidationError as exc:
        raise LawRefused("malformed", exc.errors()[0]["msg"]) from exc


#: The largest law file read: 256 KiB, well past the reference law's few kilobytes.
MAX_FILE_BYTES = 256 * 1024
