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

**What the vectors do not check.** The signals are already in rad and rad/s: the conversion
from the sensors' counts to physical units (the encoder's counts per wheel revolution, the
gyro's full scale and sensitivity) takes part in nothing the scorer simulates for a law, and
the test vectors carry the converted numbers, so a wrong counts-to-rad conversion in the
transcription is invisible to them. The export's record says so beside the settings it reads.

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
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from fractions import Fraction
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
    ``coefficient_not_held``, ``vector_not_reproduced``, ``vectors_too_few``,
    ``vectors_do_not_exercise``, ``vectors_do_not_pin``, ``answer_not_valid`` and
    ``delay_or_limit_not_stated_by_the_interface``; ``detail`` says
    what, in words.
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
_OF = re.compile(r"(?:(previous|line)\.)?([a-z][a-z0-9_]*)")


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
            found = _OF.fullmatch(of)
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
    found = _OF.fullmatch(of)
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
    scaled: tuple[str, int, float] | None = None,
    seen: set[tuple[str, int]] | None = None,
) -> tuple[float, dict[str, float]]:
    """One update: the command before any limit, and each memory state's next value.

    ``values`` holds each coefficient's number as the graph holds it; ``state`` each memory
    state before the update, ``signals`` each signal this update (a missing one is 0).
    ``scaled`` is ``(line, term, factor)``: that term's value times ``factor``, for the vector
    check's perturbation; ``seen`` collects each ``(line, term)`` whose variable was not zero.
    """
    coefficients = _coefficients(values, period)
    lines: dict[str, float] = {}
    for line in body.lines:
        total = 0.0
        for at, term in enumerate(line.terms):
            kind, name = _OF.fullmatch(term.of).groups()  # type: ignore[union-attr]
            if kind is None:
                variable = signals.get(name, 0.0)
            elif kind == "previous":
                variable = state[name]
            else:
                variable = lines[name]
            if seen is not None and variable != 0.0:
                seen.add((line.name, at))
            contribution = _term(term, coefficients, [variable])[0]
            if scaled is not None and scaled[:2] == (line.name, at):
                contribution *= scaled[2]
            total += contribution
        lines[line.name] = total
    return lines[body.command], {m.name: lines[m.next] for m in body.memory}


def _rows[N: (float, Fraction)](
    body: Body, coefficients: Mapping[str, N], number: Callable[[float], N]
) -> tuple[list[list[N]], list[N]]:
    """Each memory state's next value and the command, as rows over (previous memory, inputs).

    ``number`` is ``float`` for the loop's matrices and ``Fraction`` for the exact ones the held
    modes are decided on: the same lines, the same order, the same arithmetic in either.
    """
    n, k = len(body.memory), len(LOOP_SIGNALS)
    zero, one = number(0.0), number(1.0)
    basis: dict[str, list[N]] = {}
    for i, m in enumerate(body.memory):
        basis[f"previous.{m.name}"] = [one if j == i else zero for j in range(n + k)]
    for i, name in enumerate(LOOP_SIGNALS):
        basis[name] = [one if j == n + i else zero for j in range(n + k)]
    basis["wheel_reference"] = [zero] * (n + k)
    for line in body.lines:
        row = [zero] * (n + k)
        for term in line.terms:
            found = _OF.fullmatch(term.of)
            assert found is not None  # held by check()
            kind, name = found.groups()
            key = name if kind is None else f"{kind}.{name}"
            scale = number(float(term.sign)) * number(float(term.number))
            for factor in term.coefficients:
                scale = scale * coefficients[factor]
            for factor in term.per:
                scale = scale / coefficients[factor]
            row = [a + scale * b for a, b in zip(row, basis[key], strict=True)]
        basis[f"line.{line.name}"] = row
    return [basis[f"line.{m.next}"] for m in body.memory], basis[f"line.{body.command}"]


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
    n = len(body.memory)
    rows, command = _rows(body, _coefficients(values, period), float)
    return (
        tuple(tuple(r[:n]) for r in rows),
        tuple(tuple(r[n:]) for r in rows),
        tuple(command[:n]),
        tuple(command[n:]),
    )


def held_modes(
    body: Body, values: Mapping[str, float], *, period: float
) -> tuple[tuple[float, ...], ...]:
    """The modes the law itself holds at exactly 1 whatever the gain: its structure, not a window.

    A mode is *held by the law's structure* when, with the plant at rest but for the wheels'
    angle ``β`` (the travel, the plant's one pole at 1) and the memory at some ``m``, one update
    gives the command 0 and gives the same memory back::

        D_w·β + C·m = 0        B_w·β + (A - I)·m = 0

    ``A, B, C, D`` are the law's matrices (:func:`linear`), ``D_w`` and ``B_w`` the column that
    reads the wheel angle. Then ``(β, m)`` is held at every gain: the command that would move the
    plant is 0 and nothing changes. The two equations are solved in exact rational arithmetic on
    the numbers the law has (a float is one exact rational), so a mode is held or it is not,
    whatever the size of any coefficient in the law and with no tolerance to widen: a memory state
    that carries itself and nothing else, a sum of states conserved by the updates, the velocity
    form's offset (the angle estimate's start against the travel it settles to), a state read by
    nothing. A pole at ``1 + 1e-6``, or a command-fed integrator with a gain of ``1e-6``, is no
    solution, exactly.

    The solutions that are the plant alone (``m = 0``, which exist only when the law reads the
    wheel angle nowhere) are the plant's own travel, never set aside; the others are returned,
    one for each independent memory part, each as ``(β, m_1, .., m_n)`` scaled to its largest
    entry 1. The travel and a memory-only mode can be in one space; only the second is returned.
    """
    n = len(body.memory)
    if n == 0:
        return ()
    rows, command = _rows(
        body, {k: Fraction(v) for k, v in _coefficients(values, period).items()}, Fraction
    )
    wheel = n + LOOP_SIGNALS.index("wheel_angle")
    stacked = [[command[wheel], *command[:n]]]
    for i, row in enumerate(rows):
        stacked.append([row[wheel], *(row[j] - (1 if i == j else 0) for j in range(n))])
    chosen: list[list[Fraction]] = []
    memory_parts: list[list[Fraction]] = []
    for vector in _null_space(stacked):
        part = vector[1:]
        if _rank([*memory_parts, part]) > len(memory_parts):
            memory_parts.append(part)
            chosen.append(vector)
    out = []
    for vector in chosen:
        top = max(abs(x) for x in vector)
        out.append(tuple(float(x / top) for x in vector))
    return tuple(out)


def _echelon(rows: list[list[Fraction]]) -> tuple[list[list[Fraction]], list[int]]:
    """``rows`` reduced to row echelon form over the rationals, with the pivot columns."""
    reduced = [list(r) for r in rows]
    pivots: list[int] = []
    at = 0
    for col in range(len(reduced[0]) if reduced else 0):
        found = next((r for r in range(at, len(reduced)) if reduced[r][col] != 0), None)
        if found is None:
            continue
        reduced[at], reduced[found] = reduced[found], reduced[at]
        lead = reduced[at][col]
        reduced[at] = [x / lead for x in reduced[at]]
        for r in range(len(reduced)):
            if r != at and reduced[r][col] != 0:
                factor = reduced[r][col]
                reduced[r] = [a - factor * b for a, b in zip(reduced[r], reduced[at], strict=True)]
        pivots.append(col)
        at += 1
    return reduced, pivots


def _rank(rows: list[list[Fraction]]) -> int:
    return len(_echelon(rows)[1])


def _null_space(rows: list[list[Fraction]]) -> list[list[Fraction]]:
    """A basis of the vectors ``x`` with ``rows · x = 0``, exactly."""
    reduced, pivots = _echelon(rows)
    width = len(rows[0])
    basis = []
    for free in (c for c in range(width) if c not in pivots):
        vector = [Fraction(0)] * width
        vector[free] = Fraction(1)
        for r, col in enumerate(pivots):
            vector[col] = -reduced[r][free]
        basis.append(vector)
    return basis


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
    scaled: tuple[str, int, float] | None = None,
    seen: set[tuple[str, int]] | None = None,
) -> tuple[int, str | None]:
    """How many rows of ``vectors`` the law reproduces, and the first that it does not.

    Each vector starts from its own memory (a missing state is 0) and runs one update per row.
    A row holds when the duty before the limit and each named memory state are within
    :data:`DUTY_TOLERANCE` and the command, held to the limit and rounded to whole counts of
    ``full_scale``, within :data:`COUNT_TOLERANCE`. A state marked applied then holds that
    command as applied. ``scaled`` and ``seen`` are :func:`evaluate`'s.
    """
    checked = 0
    for vector in vectors:
        state = {m.name: vector.start.get(m.name, 0.0) for m in body.memory}
        for at, row in enumerate(vector.rows, 1):
            signals = {name: getattr(row, name) for name in SIGNALS}
            duty, following = evaluate(
                body,
                values,
                period=period,
                state=state,
                signals=signals,
                scaled=scaled,
                seen=seen,
            )
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


#: The fewest rows the test vectors may have in all. Chosen: a law of the size this kit's
#: controllers have (six numbers, three memory states) is first seen working only from the
#: second update of a vector, and ten is a floor that every honest set in hand clears three
#: times over (the recorded design's has 30 and its note states 41), while one row, or the few
#: a hand writes to look as if it checked, cannot. It is the floor; what the rows must do is
#: :func:`verify`'s other rules, not their number.
MIN_ROWS = 10
#: The relative change by which a term, or a coefficient in all its terms, is moved to see
#: whether the vectors notice: both up and down by this much must make a vector miss. Chosen:
#: 2 % moves the recorded design's phase margin by at most 1.4 degrees and its upward gain
#: margin by at most 0.11 of 5.17 (any one coefficient, either way); it is twice the loosest
#: pin that design's vectors hold (one coefficient, 1.0 %), so that design passes it with room.
PIN_RELATIVE = 0.02
#: The most term evaluations the vector check may make, so a crafted file cannot cost hours.
MAX_CHECK_WORK = 50_000_000


@dataclass(frozen=True)
class Verified:
    """What the vectors verified: the rows reproduced and the signals the law reads."""

    rows: int
    signals: tuple[str, ...]


def signals_read(body: Body) -> tuple[str, ...]:
    """The signals some term of ``body`` reads, in the closed list's order."""
    named = set()
    for line in body.lines:
        for term in line.terms:
            found = _OF.fullmatch(term.of)
            if found is not None and found.group(1) is None:
                named.add(found.group(2))
    return tuple(name for name in SIGNALS if name in named)


def _where(line: Line, at: int) -> str:
    term = line.terms[at]
    sign = "-" if term.sign < 0 else "+"
    factors = "*".join(term.coefficients) or "1"
    divide = "".join(f"/{name}" for name in term.per)
    return f"term {at + 1} of line {line.name!r} ({sign}{factors}{divide} * {term.of})"


def verify(
    body: Body,
    values: Mapping[str, float],
    vectors: tuple[Vector, ...],
    *,
    period: float,
    limit: float,
    full_scale: float,
) -> Verified:
    """Hold ``body`` to its vectors, and the vectors to what they must demand of it.

    The rules, each a refusal by its name, in this order:

    - ``vectors_too_few``: fewer than :data:`MIN_ROWS` rows in all;
    - ``vector_not_reproduced``: a row the law does not reproduce (:func:`reproduce`);
    - ``vectors_do_not_exercise``: a term whose variable is zero at every update of every
      vector (a signal no row sets, a memory state that is never not zero, a line that is
      always zero), or a memory state no term reads: the vectors say nothing of it, so a
      number on it could be anything;
    - ``vectors_do_not_pin``: a term, or a coefficient in all its terms, that can be moved by
      :data:`PIN_RELATIVE`, up and down, with every row still reproduced: the vectors cannot
      tell its number from another within that, so they do not pin it. A term or coefficient
      whose value is 0 is exercised but not moved (nothing is 2 % of 0).

    Every refusal names what is missing or loose, and none depends on a tolerance that grows with
    a coefficient: the rows' own tolerances are absolute, and a number that the rows are blind
    to, as a small signal is to a large tolerance, is what the last rule finds.

    Raises:
        LawRefused: by one of the codes above.
    """
    total = sum(len(v.rows) for v in vectors)
    if total < MIN_ROWS:
        msg = (
            f"the vectors have {total} row{'s' if total != 1 else ''} in all; at least "
            f"{MIN_ROWS} are required, since fewer cannot exercise a law's signals and memory"
        )
        raise LawRefused("vectors_too_few", msg)
    checked, mismatch = reproduce(
        body, values, vectors, period=period, limit=limit, full_scale=full_scale
    )
    if mismatch is not None:
        raise LawRefused("vector_not_reproduced", mismatch)
    terms = sum(len(line.terms) for line in body.lines)
    coefficients = sorted(
        {n for line in body.lines for t in line.terms for n in (*t.coefficients, *t.per)}
    )
    if (2 * (terms + len(coefficients)) + 1) * total * terms > MAX_CHECK_WORK:
        msg = "the law and its vectors are too large for the vectors to be checked"
        raise LawRefused("malformed", msg)
    seen: set[tuple[str, int]] = set()
    reproduce(body, values, vectors, period=period, limit=limit, full_scale=full_scale, seen=seen)
    silent = [
        f"{_where(line, at)} reads {term.of!r}, which is zero at every update of every vector"
        for line in body.lines
        for at, term in enumerate(line.terms)
        if (line.name, at) not in seen
    ]
    read = {t.of.removeprefix("previous.") for line in body.lines for t in line.terms}
    silent += [
        f"the memory state {m.name!r} is read by no term" for m in body.memory if m.name not in read
    ]
    if silent:
        raise LawRefused("vectors_do_not_exercise", "; ".join(silent))

    def notices(held: Mapping[str, float], scaled: tuple[str, int, float] | None) -> bool:
        return (
            reproduce(
                body,
                held,
                vectors,
                period=period,
                limit=limit,
                full_scale=full_scale,
                scaled=scaled,
            )[1]
            is not None
        )

    loose = []
    for name in coefficients:
        if values.get(name, 0.0) == 0.0:
            continue
        both = [
            notices({**values, name: values[name] * (1 + sign * PIN_RELATIVE)}, None)
            for sign in (1, -1)
        ]
        if not all(both):
            loose.append(f"the coefficient {name!r}")
    for line in body.lines:
        for at, term in enumerate(line.terms):
            if any(values.get(n, 0.0) == 0.0 for n in term.coefficients):
                continue
            both = [notices(values, (line.name, at, 1 + sign * PIN_RELATIVE)) for sign in (1, -1)]
            if not all(both):
                loose.append(_where(line, at))
    if loose:
        msg = (
            f"the vectors do not pin {'; '.join(loose)}: changed by {PIN_RELATIVE:.0%} up or "
            "down, every row is still reproduced"
        )
        raise LawRefused("vectors_do_not_pin", msg)
    return Verified(rows=checked, signals=signals_read(body))


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
