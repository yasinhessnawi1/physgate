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
scorer's scope, refused by name (``out_of_scope``) and never scored as a fail, *if that term can
matter*: scope is decided on what the law computes, so a term of weight 0 or in a line nothing
the command reaches reads is taken out, and the law judged as it is (:func:`scoped`). A law
refused for scope has every other check run on it first (every name declared, the units of every
line that can be checked, the settings, the timing), and any other fault is the ordinary fail:
a scope refusal never covers an invalid answer. It does cover an answer that is valid and would
fail: a law with a live term the scorer cannot take is not judged, whatever else it would have
scored, and a dead term is never such a ground.

**What a stable verdict says, and what it does not.** Stable means stable with the wheels
returning. A memory state that integrates the wheel angle, the wheel speed or the command scores
unstable even if nothing reads it (a diagnostic counter, an odometer, an anti-windup memory fed by
the command): such memory belongs outside the control law. A state fed by the tilt, its rate or
the reference and read by the command is set aside (the loop analysis holds it bounded) and the
answer is flagged (:data:`HELD_STATE_FLAG`), for in the firmware a bias or a reference grows it
without bound. The rule is a radius below 1 by :data:`~physgate.evaluation.whole.loop
.STABILITY_EPSILON` (1e-12): a position gain of the right sign at 1e-9 scores stable, while none
and the wrong sign do not. Every number of a law is a number a float holds as it is written (one
that underflows, written as a nonzero that reads as zero, or overflows is refused by name), and
is written with at most 15 significant digits: a held state is decided on the decimals as
written, and two spellings of one float past 15 digits can be decided differently, always
towards unstable.

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

import json
import math
import re
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass, field
from decimal import Decimal
from fractions import Fraction
from typing import Annotated, Any, Literal

from pydantic import (
    AfterValidator,
    BaseModel,
    ConfigDict,
    Field,
    PrivateAttr,
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
    ``zero_divisor``, ``coefficient_not_held``, ``vector_not_reproduced``, ``vectors_too_few``,
    ``vectors_do_not_exercise``, ``vectors_do_not_pin``, ``answer_not_valid``,
    ``delay_or_limit_not_stated_by_the_interface``, ``period_is_not_the_interface_s`` and
    ``written_numbers_do_not_match``;
    ``detail`` says what, in words.
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
    # an integer is always finite (and past a float, it is the bound that refuses it)
    if isinstance(value, float) and not math.isfinite(value):
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
#: A name a term reads as a line or a memory state, wherever it stands in what was written: how a
#: term that is not one variable is still seen to reach a line.
_REFERENCE = re.compile(r"\b(previous|line)\.([a-z][a-z0-9_]*)")
#: What the variable of a term that no linear law over the closed list can be is replaced by once
#: it has been named, so that every other check can run on the rest of the law: it is no
#: variable, and a law holding it is never evaluated.
OUTSIDE = "outside the scorer's scope"


@dataclass(frozen=True)
class Outside:
    """A term no linear law over the closed list of signals can be: where it is, and why."""

    line: str
    index: int
    code: str
    detail: str


def _outside(line: Mapping[str, Any], term: object, index: int) -> Outside | None:
    """Why ``term`` (the ``index``-th of ``line``, as written) is out of scope, or ``None``."""
    if not isinstance(term, dict):
        return None
    name = str(line.get("name"))
    extra = sorted(str(key) for key in set(term) - set(Term.model_fields))
    if extra:
        msg = (
            f"line {name!r} has a term with {', '.join(extra)}; a term is a sign, a number, "
            "coefficients and one variable"
        )
        return Outside(name, index, "nonlinear", msg)
    of = term.get("of")
    if not isinstance(of, str) or of == OUTSIDE:
        return None
    found = _OF.fullmatch(of)
    if found is None:
        return Outside(
            name, index, "nonlinear", f"line {name!r} reads {of!r}, which is not one variable"
        )
    kind, reading = found.groups()
    if kind is None and reading not in SIGNALS:
        msg = (
            f"line {name!r} reads {reading!r}, a signal outside the closed list "
            f"({', '.join(SIGNALS)})"
        )
        return Outside(name, index, "out_of_scope", msg)
    return None


def _is_number(value: object) -> bool:
    return isinstance(value, int | float | Decimal) and not isinstance(value, bool)


def _zero_weight(term: Mapping[str, Any], values: Mapping[str, object] | None) -> bool:
    """Whether ``term`` as written has no weight: its number or a coefficient of it is 0."""
    number = term.get("number", 1)
    if _is_number(number) and number == 0:
        return True
    coefficients = term.get("coefficients")
    if values is None or not isinstance(coefficients, list):
        return False
    return any(
        isinstance(c, str) and _is_number(values.get(c)) and values[c] == 0 for c in coefficients
    )


@dataclass(frozen=True)
class Scoped:
    """A law's document with its out-of-scope terms sorted by whether they can matter.

    ``body`` is the document with each ``dead`` term taken out and each ``live`` one's variable
    replaced by :data:`OUTSIDE`; ``live`` terms reach the command (or a memory state the command
    reads) with a weight, ``dead`` ones cannot affect it.
    """

    body: dict[str, Any]
    live: tuple[Outside, ...]
    dead: tuple[Outside, ...]
    #: For each line of ``body``, the place in the document as written of each term it keeps, in
    #: order: a term's identity, which survives a term taken out before it.
    origin: Mapping[str, tuple[int, ...]] = field(default_factory=dict)


def _identity(raw: Mapping[str, Any]) -> dict[str, tuple[int, ...]]:
    """Each line of ``raw`` with every term at its own place: nothing was taken out."""
    return {
        x["name"]: tuple(range(len(x["terms"])))
        for x in raw.get("lines") or ()
        if isinstance(x, dict)
        and isinstance(x.get("name"), str)
        and isinstance(x.get("terms"), list)
    }


def scoped(raw: object, values: Mapping[str, object] | None = None) -> Scoped:
    """Sort the out-of-scope terms of the document ``raw`` by whether they can matter.

    A term is out of scope when no linear law over the closed list of signals can be one (not
    one variable: ``nonlinear``; a signal outside the list: ``out_of_scope``). The scope is
    decided on what the law computes, so such a term that cannot affect the command is not a
    ground for refusing it. It cannot when its weight is 0 (its number is 0, or a coefficient it
    multiplies is, ``values`` giving each coefficient's number where they are known) or when
    its line is read by nothing the command reaches (not the command, not read by a live term,
    not the next value of a memory state a live term reads). A dead term of a live line is taken
    out of it; a dead term in a line nothing live reads takes the whole line out, and with it
    whatever else only that line gave meaning to (another unread line that reads it, a memory
    state taking its next value from it): none of them can affect the command. A dead term that is
    the only one of a live line cannot be taken out (the line would be empty), and counts as live.

    Looks at the document as written, before a schema reads it, so a term that tries a function, a
    product, or a signal outside the list is named for what it is. Nothing here raises.
    """
    if not isinstance(raw, dict) or not isinstance(raw.get("lines"), list):
        return Scoped(raw if isinstance(raw, dict) else {}, (), (), {})
    lines = [x for x in raw["lines"] if isinstance(x, dict) and isinstance(x.get("name"), str)]
    named: dict[str, list[Any]] = {
        x["name"]: x["terms"] for x in lines if isinstance(x.get("terms"), list)
    }
    found: dict[tuple[str, int], Outside] = {}
    for name, terms in named.items():
        for at, term in enumerate(terms):
            outside = _outside({"name": name}, term, at)
            if outside is not None:
                found[(name, at)] = outside
    if not found:
        return Scoped(raw, (), (), _identity(raw))
    states = raw.get("memory")
    memory: dict[str, Any] = {
        m["name"]: m.get("next")
        for m in (states if isinstance(states, list) else ())
        if isinstance(m, dict) and isinstance(m.get("name"), str)
    }
    live_lines = _live_lines(named, memory, raw.get("command"), values)
    dead = {
        key
        for key in found
        if key[0] not in live_lines
        or (isinstance(named[key[0]][key[1]], dict) and _zero_weight(named[key[0]][key[1]], values))
    }
    gone, gone_states = _unmeant(named, memory, live_lines, {n for n, _ in dead} - live_lines, dead)
    out_lines: list[Any] = []
    set_aside: list[Outside] = []
    live: list[Outside] = []
    origin: dict[str, tuple[int, ...]] = {}
    for item in raw["lines"]:
        label = item.get("name") if isinstance(item, dict) else None
        if not isinstance(label, str) or label not in named:
            out_lines.append(item)
            continue
        if label in gone:
            set_aside.extend(
                found[(label, at)] for at in range(len(named[label])) if (label, at) in found
            )
            continue
        kept: list[Any] = []
        places: list[int] = []
        others = sum(1 for at in range(len(named[label])) if (label, at) not in dead)
        for at, term in enumerate(named[label]):
            if (label, at) in dead and others:
                set_aside.append(found[(label, at)])
                continue
            if (
                (label, at) not in found
                and others > 1
                and _reads_what_went(term, gone, gone_states)
            ):
                # a term of weight 0 that read a line or a state taken out: it has nothing to read
                continue
            if (label, at) in found:
                live.append(found[(label, at)])
                kept.append(_marked(term))
            else:
                kept.append(term)
            places.append(at)
        origin[label] = tuple(places)
        out_lines.append({**item, "terms": kept})
    body = {**raw, "lines": out_lines}
    if "memory" in raw and isinstance(raw["memory"], list):
        body["memory"] = [
            m
            for m in raw["memory"]
            if not (
                isinstance(m, dict) and isinstance(m.get("name"), str) and m["name"] in gone_states
            )
        ]
    return Scoped(body, tuple(live), tuple(set_aside), origin)


def _reads_what_went(term: object, lines: set[str], states: set[str]) -> bool:
    return any(
        (kind == "line" and r in lines) or (kind == "previous" and r in states)
        for kind, r in _references(term)
    )


def _unmeant(
    named: Mapping[str, list[Any]],
    memory: Mapping[str, Any],
    live_lines: set[str],
    start: set[str],
    dead: set[tuple[str, int]],
) -> tuple[set[str], set[str]]:
    """The lines and memory states that go with the lines ``start``, which are taken out whole.

    A memory state goes when it takes its next value from a line that goes; a line nothing live
    reads goes when it reads a line or a state that goes, for its terms would name what is no
    more. A line the command reaches goes only when nothing of it is left: every term of it is one
    that cannot affect the command (``dead``) or reads what went, and one of them reads what went.
    Such a line is 0 at every update (its terms were weightless, the one that read what went
    being a term of weight 0), the term of any line that reads it reads nothing and goes too, and
    a state that takes it as its next value is 0 after one update and sets no pole: judged as the
    law it is without them. A live line with a dead term alone in it is not such a line: it is a
    term that can matter.
    """
    lines, states = set(start), set()
    changed = True
    while changed:
        changed = False
        for state, following in memory.items():
            if state not in states and isinstance(following, str) and following in lines:
                states.add(state)
                changed = True
        for name, terms in named.items():
            if name in lines:
                continue
            if name in live_lines:
                reads = [_reads_what_went(term, lines, states) for term in terms]
                left = [(name, at) not in dead and not read for at, read in enumerate(reads)]
                if any(reads) and not any(left):
                    lines.add(name)
                    changed = True
            elif any(_reads_what_went(term, lines, states) for term in terms):
                lines.add(name)
                changed = True
    return lines, states


def _marked(term: Mapping[str, Any]) -> dict[str, Any]:
    """``term`` with only the keys a term has, and :data:`OUTSIDE` as its variable."""
    return {key: value for key, value in term.items() if key in Term.model_fields} | {"of": OUTSIDE}


def _references(term: object) -> list[tuple[str, str]]:
    """The lines and memory states ``term`` reads, as ``(kind, name)``, even if it is nonlinear."""
    if not isinstance(term, dict) or not isinstance(term.get("of"), str):
        return []
    return [(kind, name) for kind, name in _REFERENCE.findall(term["of"])]


def _live_lines(
    named: Mapping[str, list[Any]],
    memory: Mapping[str, Any],
    command: object,
    values: Mapping[str, object] | None,
) -> set[str]:
    """The lines whose value can reach the command, through weights that are not 0."""
    live: set[str] = set()
    todo = [command] if isinstance(command, str) else []
    live.update(todo)
    states: set[str] = set()
    while todo:
        for term in named.get(todo.pop(), ()):
            if not isinstance(term, dict) or _zero_weight(term, values):
                continue
            for kind, reading in _references(term):
                if kind == "previous" and reading not in states:
                    states.add(reading)
                    following = memory.get(reading)
                    if isinstance(following, str) and following not in live:
                        live.add(following)
                        todo.append(following)
                elif kind == "line" and reading not in live:
                    live.add(reading)
                    todo.append(reading)
    return live


def scope(raw: object) -> None:
    """Refuse by name what no linear law over the closed list of signals can be.

    The first term of the document that is out of scope and that can matter (see
    :func:`scoped`, judged on the document alone: a zero weight needs the numbers).

    Raises:
        LawRefused: ``nonlinear``, or ``out_of_scope``.
    """
    live = scoped(raw).live
    if live:
        raise LawRefused(live[0].code, live[0].detail)


def check(body: Body, units: Mapping[str, str]) -> None:
    """Hold ``body`` to its own names, its order and its units, ``units`` the coefficients'.

    ``units`` maps each coefficient name the law may use to its unit; ``period`` is added.

    A term whose variable is :data:`OUTSIDE` (named out of scope by :func:`scoped`) has its
    coefficients checked as declared and nothing more: it has no unit to balance.

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
            if term.of == OUTSIDE:
                # Named out of scope (see :func:`scoped`): its variable has no unit to check,
                # and nothing else about it is left unchecked above.
                continue
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


def zero_divisors(body: Body, values: Mapping[str, float]) -> tuple[str, ...]:
    """The coefficients a term divides by whose number is 0, sorted: nothing is defined there."""
    divisors = {name for line in body.lines for term in line.terms for name in term.per}
    return tuple(sorted(name for name in divisors if name in values and values[name] == 0))


def zero_refusal(name: str) -> LawRefused:
    """The refusal for a term that divides by the coefficient ``name``, whose number is 0."""
    msg = f"a term divides by the coefficient {name!r}, whose number is 0; nothing is defined there"
    return LawRefused("zero_divisor", msg)


def _term(
    term: Term,
    coefficients: Mapping[str, float],
    variable: list[float],
) -> list[float]:
    scale = float(term.sign) * float(term.number)
    for name in term.coefficients:
        scale *= coefficients[name]
    for name in term.per:
        if coefficients[name] == 0:
            raise zero_refusal(name)
        scale /= coefficients[name]
    return [scale * v for v in variable]


def _coefficients[N: (float, Fraction)](values: Mapping[str, N], period: N) -> dict[str, N]:
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

    Raises:
        LawRefused: ``zero_divisor``: a term divides by a coefficient whose number is 0.
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


def _number(_line: int, _term_at: int, term: Term) -> float:
    return float(term.sign) * float(term.number)


def _rows[N: (float, Fraction)](
    body: Body,
    coefficients: Mapping[str, N],
    number: Callable[[int, int, Term], N],
) -> tuple[list[list[N]], list[N], list[list[N]]]:
    """Each memory state's next value and the command as rows over (previous memory, inputs).

    ``number`` gives a term's sign times its number, as ``float`` for the loop's matrices and
    as an exact ``Fraction`` for the ones the held modes are decided on: the same lines, the
    same order, the same arithmetic in either. The third value is each term's scale (its sign,
    number and coefficients, divided by its reciprocals), line by line.

    Raises:
        LawRefused: ``zero_divisor``: a term divides by a coefficient whose number is 0.
    """
    n, k = len(body.memory), len(LOOP_SIGNALS)
    zero = coefficients[PERIOD] * 0
    one = zero + 1
    basis: dict[str, list[N]] = {}
    for i, m in enumerate(body.memory):
        basis[f"previous.{m.name}"] = [one if j == i else zero for j in range(n + k)]
    for i, name in enumerate(LOOP_SIGNALS):
        basis[name] = [one if j == n + i else zero for j in range(n + k)]
    basis["wheel_reference"] = [zero] * (n + k)
    scales: list[list[N]] = []
    for li, line in enumerate(body.lines):
        row = [zero] * (n + k)
        line_scales: list[N] = []
        for ti, term in enumerate(line.terms):
            found = _OF.fullmatch(term.of)
            assert found is not None  # held by check()
            kind, name = found.groups()
            key = name if kind is None else f"{kind}.{name}"
            scale = number(li, ti, term)
            for factor in term.coefficients:
                scale = scale * coefficients[factor]
            for factor in term.per:
                if coefficients[factor] == 0:
                    raise zero_refusal(factor)
                scale = scale / coefficients[factor]
            line_scales.append(scale)
            row = [a + scale * b for a, b in zip(row, basis[key], strict=True)]
        scales.append(line_scales)
        basis[f"line.{line.name}"] = row
    return [basis[f"line.{m.next}"] for m in body.memory], basis[f"line.{body.command}"], scales


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

    Raises:
        LawRefused: ``zero_divisor``: a term divides by a coefficient whose number is 0.
    """
    n = len(body.memory)
    rows, command, _ = _rows(body, _coefficients(values, period), _number)
    return (
        tuple(tuple(r[:n]) for r in rows),
        tuple(tuple(r[n:]) for r in rows),
        tuple(command[:n]),
        tuple(command[n:]),
    )


def exact(number: float | int | Decimal | Fraction) -> Fraction:
    """``number`` as the exact rational of the decimal it was written as.

    A decimal (``Decimal``) and an integer are themselves. A ``float`` is the one number that
    reads back as it: the shortest decimal that round-trips (``repr``), so ``0.1`` is one tenth,
    not the binary fraction nearest it. That is the written decimal for any number written with up
    to 15 significant digits, and the shortest decimal of the same float for one written with more
    (a reader that kept only the float has nothing finer).
    """
    if isinstance(number, Fraction):
        return number
    if isinstance(number, Decimal | int):
        return Fraction(number)
    return Fraction(Decimal(repr(number)))


@dataclass(frozen=True)
class Written:
    """The numbers of a law as written: each coefficient and the period, and each term's number.

    Exact rationals of the decimals in the text the law was read from (:func:`written_from`),
    so that a decision on the law's structure is made on ``0.1`` and ``0.9`` and not on the bits
    of their binary forms.

    A term's number is found by its identity, not by its position in the law that is scored: the
    line's name and the term's own place in the text as written (the place does not move when a
    term before it is taken out, :func:`scoped`). ``numbers`` is keyed by ``(line name, place)`` and
    holds only the terms the law keeps; ``origin`` gives, for each line of the law, the place of
    each of its terms in order. :func:`check_written` holds the two to the law, one to one.
    """

    coefficients: Mapping[str, Fraction]
    numbers: Mapping[tuple[str, int], Fraction]
    origin: Mapping[str, tuple[int, ...]] = field(default_factory=dict)

    def number(self, line: str, at: int) -> Fraction | None:
        """The number written for the ``at``-th term of the law's line ``line``, if there is one."""
        places = self.origin.get(line)
        if places is None or not 0 <= at < len(places):
            return None
        return self.numbers.get((line, places[at]))


def written_from(
    document: Mapping[str, Any], origin: Mapping[str, tuple[int, ...]] | None = None
) -> Written:
    """The numbers of the law ``document`` states, read from a document parsed with ``Decimal``.

    ``document`` is a controller's or a body's JSON as written (nothing taken out of it), parsed
    with ``parse_float=Decimal``, so the text ``0.1`` is the decimal ``0.1``. ``origin`` is where
    each term the law keeps stands in it (:attr:`Scoped.origin`): only those terms' numbers are
    taken, each by its place; with none given, every term of every line is kept. What is not a
    number there is left out.
    """
    coefficients: dict[str, Fraction] = {}
    for name, measure in (document.get("coefficients") or {}).items():
        if isinstance(measure, dict) and _is_number(measure.get("value")):
            coefficients[name] = exact(measure["value"])
    period = document.get("period")
    if isinstance(period, dict) and _is_number(period.get("value")):
        coefficients[PERIOD] = exact(period["value"])
    kept = _identity(document) if origin is None else origin
    terms_of = {
        x["name"]: x["terms"]
        for x in document.get("lines") or ()
        if isinstance(x, dict)
        and isinstance(x.get("name"), str)
        and isinstance(x.get("terms"), list)
    }
    numbers: dict[tuple[str, int], Fraction] = {}
    for name, places in kept.items():
        terms = terms_of.get(name, [])
        for place in places:
            term = terms[place] if 0 <= place < len(terms) else None
            if isinstance(term, dict) and _is_number(term.get("number", 1)):
                numbers[(name, place)] = exact(term.get("number", 1))
    return Written(coefficients, numbers, dict(kept))


def _agrees(written: Fraction, number: float | int) -> bool:
    """Whether the decimal ``written`` is the number the law was validated with."""
    try:
        return written == number if isinstance(number, int) else float(written) == number
    except OverflowError:
        return False


def check_written(body: Body, values: Mapping[str, float], period: float, written: Written) -> None:
    """Hold the numbers as written to the law, one to one, before anything is decided on them.

    Every line of the law has its places and no other line has any; each of its terms has one
    place, none shared, and one number at it, and no number is held for a place that is no term;
    each number is the very number the law was validated with (read as a float, the decimal is
    the float); each coefficient the law uses has its number, and the period; and no coefficient
    is held that the law does not have. Anything else is a decision that would be made on
    another law's numbers, and nothing is decided.

    Raises:
        LawRefused: ``written_numbers_do_not_match``, saying what does not correspond.
    """

    def refuse(what: str) -> LawRefused:
        return LawRefused("written_numbers_do_not_match", f"the numbers as written: {what}")

    if set(written.origin) != {line.name for line in body.lines}:
        raise refuse("the lines they are held for are not the law's lines")
    wanted: set[tuple[str, int]] = set()
    for line in body.lines:
        places = written.origin[line.name]
        if len(places) != len(line.terms) or len(set(places)) != len(places):
            raise refuse(
                f"line {line.name!r} has {len(line.terms)} terms, not {len(places)} places"
            )
        for place, term in zip(places, line.terms, strict=True):
            wanted.add((line.name, place))
            number = written.numbers.get((line.name, place))
            if number is None or not _agrees(number, term.number):
                raise refuse(f"line {line.name!r}, the term written at {place + 1}, has no number")
    if set(written.numbers) != wanted:
        raise refuse("a number is held for a term the law does not have")
    if set(written.coefficients) - {PERIOD} != set(values):
        raise refuse("the coefficients are not the law's")
    for name, value in values.items():
        if not _agrees(written.coefficients[name], value):
            raise refuse(f"the coefficient {name!r} is not the number the law has")
    if PERIOD not in written.coefficients or not _agrees(written.coefficients[PERIOD], period):
        raise refuse("the period is not the number the law has")


@dataclass(frozen=True)
class _Held:
    """What the exact conditions at rest say: the modes held at 1, and whether any is set aside.

    ``kernel`` is a basis of the held vectors ``(β, m_1, .., m_n)``; ``rows``, ``command`` and
    ``scales`` are the law's exact rows and each term's scale (:func:`_rows`). ``set_aside`` is
    whether those modes may be set aside: they exist, none is the wheels alone, and every
    quantity the law conserves at rest is settled whatever the wheels do first.
    """

    kernel: list[list[Fraction]]
    rows: list[list[Fraction]]
    command: list[Fraction]
    scales: list[list[Fraction]]
    set_aside: bool


def _held(body: Body, values: Mapping[str, float], period: float, written: Written | None) -> _Held:
    n = len(body.memory)
    exact_values = {name: exact(v) for name, v in values.items()}
    exact_period = exact(period)
    if written is not None:
        check_written(body, values, period, written)
        exact_values.update({k: v for k, v in written.coefficients.items() if k != PERIOD})
        exact_period = written.coefficients[PERIOD]

    def number(li: int, ti: int, term: Term) -> Fraction:
        if written is not None:
            at = written.number(body.lines[li].name, ti)
            assert at is not None  # held by check_written()
            return exact(term.sign) * at
        return exact(term.sign) * exact(term.number)

    rows, command, scales = _rows(body, _coefficients(exact_values, exact_period), number)
    if n == 0:
        return _Held([], rows, command, scales, False)
    wheel = n + LOOP_SIGNALS.index("wheel_angle")
    stacked = [[command[wheel], *command[:n]]]
    for i, row in enumerate(rows):
        stacked.append([row[wheel], *(row[j] - (1 if i == j else 0) for j in range(n))])
    kernel = _null_space(stacked)
    if not kernel:
        return _Held(kernel, rows, command, scales, False)
    # A vector of the kernel that is the wheels alone is the plant's own travel, held by nothing:
    # then the memory parts are fewer than the vectors.
    if _rank([v[1:] for v in kernel]) < len(kernel):
        return _Held(kernel, rows, command, scales, False)
    cruise = n + LOOP_SIGNALS.index("wheel_speed")
    for y in _null_space([list(column) for column in zip(*stacked, strict=True)]):
        fed = sum((y[1 + i] * rows[i][cruise] for i in range(n)), Fraction(0))
        if y[0] != 0 or fed != 0:
            return _Held(kernel, rows, command, scales, False)
    return _Held(kernel, rows, command, scales, True)


def held_modes(
    body: Body,
    values: Mapping[str, float],
    *,
    period: float,
    written: Written | None = None,
) -> tuple[tuple[float, ...], ...]:
    """The modes the law holds at exactly 1 and the wheels' restoring does not depend on.

    **Held by the law's structure.** With the plant at rest but for the wheels' angle ``β`` (the
    travel, the plant's one pole at 1) and the memory at some ``m``, one update gives the command 0
    and the same memory back::

        D_w·β + C·m = 0        B_w·β + (A - I)·m = 0

    ``A, B, C, D`` are the law's matrices (:func:`linear`), ``D_w`` and ``B_w`` the column that
    reads the wheel angle. Then ``(β, m)`` is held at every gain: the command that would move the
    plant is 0 and nothing changes. The equations are solved in exact rational arithmetic on the
    numbers as written (:func:`exact`, :class:`Written`), so a mode is held or it is not, whatever
    the size of any coefficient and however a decimal is spelt in binary, with no tolerance to
    widen: a state that carries itself and nothing else, a sum of states the updates conserve, the
    velocity form's offset (the angle estimate's start against the travel it settles to), a
    state read by nothing. A pole at ``1 + 1e-6``, or a command-fed integrator with a gain of
    ``1e-6``, is no solution, exactly.

    **Set aside only where the wheels return.** A held mode is the offset of something the law
    conserves at rest: a combination of the command and of the memory's updates that vanishes
    identically (a left null vector ``y`` of the conditions above). Displace the wheels alone and
    the loop settles where the conserved quantity says; the wheels return, and the mode may be
    set aside, only if that quantity gathers nothing the wheels' motion can add: ``y`` has no
    weight on the command, and the memory it weighs is fed by no wheel speed. The reason is the
    plant's own: the motor's force is one combination of the command and the wheel speed, so a
    steady cruise has the body upright and still (no tilt, no rate) and only the wheel speed
    moves: whatever the law conserves that is fed by the tilt or its rate is settled when the
    wheels are put back, and what is fed by the wheel speed or the command is not. The test is
    on the law's numbers and holds for every plant and every gain; a law that would pass it only
    at a plant's one special value is judged as one that does not (the conservative side).
    Where any conserved quantity fails it, or one of the held vectors is the wheels alone (the
    law reads the wheel angle nowhere), nothing is set aside, and the loop is judged with the
    pole at 1 in it: the wheels are not restored, the loop is unstable. The leak-free incremental
    form's offset passes (it is fed by the tilt rate only); the backward-difference speed with
    no position gain, a washout without one, and a position gain of zero do not.

    The modes returned are a basis of the held vectors, each ``(β, m_1, .., m_n)`` scaled to its
    largest entry 1, or ``()``.

    Raises:
        LawRefused: ``zero_divisor``: a term divides by a coefficient whose number is 0.
    """
    held = _held(body, values, period, written)
    if not held.set_aside:
        return ()
    out = []
    for vector in held.kernel:
        top = max(abs(x) for x in vector)
        out.append(tuple(float(x / top) for x in vector))
    return tuple(out)


#: Said beside every mode set aside: the loop analysis bounds it, the firmware does not.
HELD_NOTE = (
    "A held state is set aside in the stability test and its margins are those of the rest of the "
    "loop. In the firmware it can grow without bound under a sensor bias (the gyro's, the "
    "encoder's) or a constant reference, to overflow or saturation, which this score cannot see."
)


@dataclass(frozen=True)
class HeldMode:
    """One mode set aside: its memory states, what feeds them, whether the command reads them."""

    states: tuple[str, ...]
    wheel_angle: bool
    fed_by_signals: tuple[str, ...]
    fed_by_memory: tuple[str, ...]
    read_by_command: bool
    note: str = HELD_NOTE

    def as_record(self) -> dict[str, Any]:
        """The mode as a plain record."""
        return {
            "memory_states": list(self.states),
            "involves_wheel_angle": self.wheel_angle,
            "fed_by_signals": list(self.fed_by_signals),
            "fed_by_memory_states": list(self.fed_by_memory),
            "fed_by_the_reference": "wheel_reference" in self.fed_by_signals,
            "read_by_the_command": self.read_by_command,
            "note": self.note,
        }


#: The flag, by its name, on an answer whose law holds a state that a signal feeds and the command
#: reads: the reference (which the loop analysis holds at zero) or a sensor (which can carry a
#: bias) integrates into it, the firmware's value of it is unbounded, and this score cannot see
#: that. Such an answer is a class of its own, never counted with the others.
HELD_STATE_FLAG = "held_state_fed_by_reference_or_bias_and_read"


def held_state_flags(modes: Sequence[HeldMode]) -> tuple[str, ...]:
    """:data:`HELD_STATE_FLAG` if some mode set aside is read by the command and fed by a signal."""
    flagged = any(mode.read_by_command and mode.fed_by_signals for mode in modes)
    return (HELD_STATE_FLAG,) if flagged else ()


def held_report(
    body: Body,
    values: Mapping[str, float],
    *,
    period: float,
    written: Written | None = None,
) -> tuple[HeldMode, ...]:
    """Each mode :func:`held_modes` sets aside: its memory states, their feeders, who reads them.

    ``fed_by_signals`` are the signals (the reference among them, which the loop analysis holds
    at zero) whose terms of nonzero weight reach the next value of any state in the mode,
    through lines and through other states; ``read_by_command`` is whether the command reads any
    of its states, directly or through the states that feed the command.
    """
    held = _held(body, values, period, written)
    if not held.set_aside:
        return ()
    line_reads: dict[str, set[str]] = {}
    for li, line in enumerate(body.lines):
        reads: set[str] = set()
        for ti, term in enumerate(line.terms):
            if held.scales[li][ti] == 0:
                continue
            kind, name = _OF.fullmatch(term.of).groups()  # type: ignore[union-attr]
            if kind == "line":
                reads |= line_reads[name]
            else:
                reads.add(name if kind is None else f"previous.{name}")
        line_reads[line.name] = reads
    following = {m.name: m.next for m in body.memory}
    reached = {r.removeprefix("previous.") for r in line_reads[body.command] if "." in r}
    pending = list(reached)
    while pending:
        for r in line_reads[following[pending.pop()]]:
            state = r.removeprefix("previous.")
            if "." in r and state not in reached:
                reached.add(state)
                pending.append(state)
    modes = []
    for vector in held.kernel:
        states = tuple(m.name for m, x in zip(body.memory, vector[1:], strict=True) if x != 0)
        feeds: set[str] = set()
        for name in states:
            feeds |= line_reads[following[name]]
        modes.append(
            HeldMode(
                states=states,
                wheel_angle=vector[0] != 0,
                fed_by_signals=tuple(s for s in SIGNALS if s in feeds),
                fed_by_memory=tuple(sorted(r.removeprefix("previous.") for r in feeds if "." in r)),
                read_by_command=any(state in reached for state in states),
            )
        )
    return tuple(modes)


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
#: How many times the interval from nothing to :data:`PIN_RELATIVE` is halved to find the smallest
#: change the vectors notice: the pin is found to within ``PIN_RELATIVE / 2**PIN_STEPS``.
PIN_STEPS = 20
#: The most term evaluations the vector check may make (counting the search for each pin), so a
#: crafted file cannot cost hours.
MAX_CHECK_WORK = 50_000_000


@dataclass(frozen=True)
class Pin:
    """The pin the vectors achieve for one term, or one coefficient in all its terms.

    The smallest relative change, up and down, that the vectors notice. ``None``: it was not
    moved (its number is 0).
    """

    up: float | None
    down: float | None

    @property
    def smallest(self) -> float | None:
        """The smaller of the two, ``None`` where neither was moved."""
        found = [x for x in (self.up, self.down) if x is not None]
        return min(found) if found else None

    def as_record(self) -> dict[str, float | None]:
        """The pin as a plain record."""
        return {"up": self.up, "down": self.down, "smallest": self.smallest}


@dataclass(frozen=True)
class Verified:
    """What the vectors verified: the rows reproduced, the signals the law reads and each pin.

    ``pins`` maps ``coefficient <name>`` and ``<term position>`` to what the vectors pin it to.
    """

    rows: int
    signals: tuple[str, ...]
    pins: Mapping[str, Pin]


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

    The pin each term and coefficient achieves (the smallest relative change, up and down, that
    some row notices, found by halving the interval to :data:`PIN_RELATIVE`) is returned with the
    rows reproduced: the check says no more than a pin it can state.

    Raises:
        LawRefused: by one of the codes above, or ``zero_divisor``.
    """
    divisors = zero_divisors(body, values)
    if divisors:
        raise zero_refusal(divisors[0])
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
        {n for line in body.lines for t in line.terms for n in (*t.coefficients, *t.per)} - {PERIOD}
    )
    if (2 * (terms + len(coefficients)) * (1 + PIN_STEPS) + 1) * total * terms > MAX_CHECK_WORK:
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
    pins: dict[str, Pin] = {}
    for name in coefficients:
        if values.get(name, 0.0) == 0.0:
            pins[f"coefficient {name}"] = Pin(None, None)
            continue

        def moved_by(change: float, name: str = name) -> bool:
            return notices({**values, name: values[name] * (1 + change)}, None)

        both = [moved_by(sign * PIN_RELATIVE) for sign in (1, -1)]
        if not all(both):
            loose.append(f"the coefficient {name!r}")
            continue
        pins[f"coefficient {name}"] = _pin(moved_by)
    for line in body.lines:
        for at, term in enumerate(line.terms):
            key = _where(line, at)
            if any({**values, PERIOD: period}.get(n, 0.0) == 0.0 for n in term.coefficients):
                pins[key] = Pin(None, None)
                continue

            def term_moved_by(change: float, line: Line = line, at: int = at) -> bool:
                return notices(values, (line.name, at, 1 + change))

            both = [term_moved_by(sign * PIN_RELATIVE) for sign in (1, -1)]
            if not all(both):
                loose.append(key)
                continue
            pins[key] = _pin(term_moved_by)
    if loose:
        msg = (
            f"the vectors do not pin {'; '.join(loose)}: changed by {PIN_RELATIVE:.0%} up or "
            "down, every row is still reproduced"
        )
        raise LawRefused("vectors_do_not_pin", msg)
    return Verified(rows=checked, signals=signals_read(body), pins=pins)


def _pin(noticed: Callable[[float], bool]) -> Pin:
    """The pin of a change ``noticed`` tells (a relative change, signed): up, then down."""

    def downward(change: float) -> bool:
        return noticed(-change)

    return Pin(_smallest(noticed), _smallest(downward))


def _smallest(noticed: Callable[[float], bool]) -> float:
    """The smallest relative change up to :data:`PIN_RELATIVE` that ``noticed`` says is noticed.

    ``noticed`` is false for no change and true at :data:`PIN_RELATIVE` (the caller has checked),
    and the interval is halved :data:`PIN_STEPS` times; the answer is the upper end, a change
    that is noticed, within ``PIN_RELATIVE / 2**PIN_STEPS`` of the smallest.
    """
    low, high = 0.0, PIN_RELATIVE
    for _ in range(PIN_STEPS):
        middle = (low + high) / 2
        if noticed(middle):
            high = middle
        else:
            low = middle
    return high


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

    #: The file as read, before any term was set aside, and the out-of-scope terms that matter
    #: (``outside``, each marked) and those set aside (``set_aside``): see :func:`scoped`.
    _document: dict[str, Any] = PrivateAttr(default_factory=dict)
    _outside: tuple[Outside, ...] = PrivateAttr(default=())
    _set_aside: tuple[Outside, ...] = PrivateAttr(default=())

    @property
    def outside(self) -> tuple[Outside, ...]:
        """The terms out of scope that can matter, still in the law marked :data:`OUTSIDE`."""
        return self._outside

    @property
    def set_aside(self) -> tuple[Outside, ...]:
        """The out-of-scope terms that cannot affect the command, taken out of the law."""
        return self._set_aside

    def with_numbers(self, values: Mapping[str, float]) -> LawFile:
        """The file with each out-of-scope term of no weight, now the numbers are known, set aside.

        ``values`` gives each coefficient's number by the law's own name. A term of weight 0, or in
        a line only such terms reach, cannot affect the command.
        """
        sorted_out = scoped(self._document, values)
        if len(sorted_out.live) == len(self._outside):
            return self
        body = Body.model_validate_json(
            json.dumps(
                {
                    k: sorted_out.body[k]
                    for k in ("memory", "lines", "command")
                    if k in sorted_out.body
                }
            )
        )
        return _with_scope(
            self.model_copy(update={"memory": body.memory, "lines": body.lines}),
            self._document,
            sorted_out,
        )

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


def _with_scope(file: LawFile, document: dict[str, Any], sorted_out: Scoped) -> LawFile:
    file._document = document  # noqa: SLF001 - private state of the model, set where it is made
    file._outside = sorted_out.live  # noqa: SLF001
    file._set_aside = sorted_out.dead  # noqa: SLF001
    return file


def parse_file(raw: bytes, *, defer_scope: bool = False) -> LawFile:
    """``raw`` as a law file, or refused by name.

    Out-of-scope terms that cannot affect the command are set aside (:func:`scoped`, judged on the
    file alone). One that can is a refusal by name, unless ``defer_scope``: then the file is
    returned with the term marked, and the caller runs every other check before refusing.

    Raises:
        LawRefused: ``malformed`` (not JSON, not the schema, too large), ``nonlinear`` or
            ``out_of_scope``.
    """
    if len(raw) > MAX_FILE_BYTES:
        raise LawRefused("malformed", f"the law file is larger than {MAX_FILE_BYTES} bytes")
    try:
        text = raw.decode("utf-8")
        document = json.loads(text)
    except (UnicodeDecodeError, ValueError, RecursionError) as exc:
        raise LawRefused("malformed", "the law file is not JSON") from exc
    sorted_out = scoped(document)
    if sorted_out.live and not defer_scope:
        raise LawRefused(sorted_out.live[0].code, sorted_out.live[0].detail)
    changed = sorted_out.live or sorted_out.dead
    try:
        file = LawFile.model_validate_json(json.dumps(sorted_out.body) if changed else text)
    except ValidationError as exc:
        raise LawRefused("malformed", exc.errors()[0]["msg"]) from exc
    return _with_scope(file, document, sorted_out)


#: The largest law file read: 256 KiB, well past the reference law's few kilobytes.
MAX_FILE_BYTES = 256 * 1024
