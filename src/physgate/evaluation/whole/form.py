"""The whole-run answer's form, written as text for the designer who must produce it.

Both arms of a whole-design comparison are told the answer's form in one block, the same bytes
to each. A person who wrote that block by hand would let it drift from the schema; this module
writes it from the schema (:mod:`physgate.evaluation.whole.answer` and
:mod:`physgate.evaluation.whole.law`): every field name, unit, range, size limit and signal in it
is read from those modules' own constants and models, and only the connecting prose is a template
here. A schema change therefore changes the block, and the block's golden file and digest make
that change a visible line of a review (:func:`render_answer_form`, :func:`answer_form_sha256`).

**Proposal, not frozen.** The block's text is a proposal. Nothing here is a frozen criterion, a
threshold or a task: the block says nothing about any requirement's bound, any number of the
plant it is judged on, or how many ways an answer may differ from another.

**What is retyped, and why.** A fact the schema holds as a constant or a model is read from it. Two
kinds are not held that way and are read another way, each held by a row:

- the unit of the four timing fields (``period``, ``command_limit``, ``sensor_delay``,
  ``compute_delay``) is a literal inside a validator; it is read from the refusal the schema
  itself gives for a wrong unit (:func:`_timing_units`);
- the settings that must be whole numbers are found by asking the schema (``setting_problem``);
- the names the scorer reports for a refusal (:data:`REFUSED`, :data:`NOT_JUDGED`) are literals in
  the scorer; a row scores an answer built to break each rule and holds the name it reports to the
  one printed here;
- the number of significant digits a law's numbers may carry (:data:`SIGNIFICANT_DIGITS`) is stated
  in the law module's own text and held there by a row. That is a tie to a sentence, not to
  behaviour: the scorer accepts a number with more digits and decides it as written, so the block
  asks for at most that many and never says more is refused;
- the name's character classes and the set of a term's signs are read from the schema's own
  pattern and ``Literal`` (:func:`_name_pattern`, :func:`_signs`), and the symbols of a unit from
  the dimensions of the signals' units and the period's (:func:`_unit_symbols`).

The block says only what the scorer does. It lists what is refused, each by a case that breaks
that rule alone, and never claims that a rule it states is refused when it is not. A sign written
``true`` is refused as a sign that is not 1 or -1, as the list says; two states marked
``applied`` and a key written twice are refused too, each with a reason that names the rule, and
the block states both rules ("only on the one state", "each key once") without listing them. A
number with more significant digits than the block asks for is still read and decided as
written, so the block asks for at most that many and says nothing of a refusal (the rows that hold
each of these are named in the tests).

What is **not told** to a designer is listed, each with its reason, in :data:`NOT_TOLD`; a row
holds every field and bound of the answer's models to being named in the block or listed there.
"""

from __future__ import annotations

import hashlib
import json
import re
import textwrap
from dataclasses import dataclass
from pathlib import Path
from string import Template
from typing import Any, get_args

from pydantic import ValidationError

from physgate.evaluation.tiers.base import Measure
from physgate.evaluation.whole import answer as answer_module
from physgate.evaluation.whole import law as law_module

#: The file a designer writes. Not a schema fact: the name the task's answer path will carry.
ANSWER_FILE = "answer.json"
#: The committed example the block quotes, as its bytes were written.
EXAMPLE_PATH = Path(__file__).with_name("answer_form_example.json")
#: The most significant digits a law's numbers are written with (the law module's own statement:
#: past it, two spellings of one float can be decided differently). Held to that text by a row.
SIGNIFICANT_DIGITS = 15
#: Spellings of a unit the block prints, each held by a row to the one parser the scorer reads a
#: law's units with (:func:`physgate.evaluation.whole.law.dimension`): the written ones are read,
#: the ones below them refused. A spelling printed here that the parser reads otherwise fails a row.
UNIT_WRITTEN: tuple[str, ...] = ("rad*s", "rad**2", "s**-1", "s/rad", "1/(rad*s)")
#: Each refused spelling, in the plain words the block gives it.
_UNIT_REFUSED: tuple[tuple[str, str], ...] = (
    ("a space or a dot between symbols", "rad s, rad.s"),
    ("a number other than a leading 1", "2*rad"),
    ("a bracket anywhere else", "(rad*s)/rad"),
    ("a space inside a power", "rad ** 2"),
)
UNIT_NOT_WRITTEN: tuple[str, ...] = tuple(
    spelling for _, spellings in _UNIT_REFUSED for spelling in spellings.split(", ")
)
#: Read by the parser as the block says: ``/`` divides by the one factor that follows it.
UNIT_QUOTIENT: tuple[str, str] = ("1/rad*s", "s/rad")


class FormError(Exception):
    """The block cannot be written true to the schema: a fact it needs is not where it was."""


@dataclass(frozen=True)
class Rule:
    """One thing the block tells a designer is refused or not judged.

    ``text`` is a sentence fragment (a ``$name`` is a fact filled from the schema); ``name`` is
    what the scorer reports it as, where it reports one, printed in brackets after the text.
    """

    key: str
    text: str
    name: str | None = None


#: What makes an answer refused: a failed answer, with its reason.
REFUSED: tuple[Rule, ...] = (
    Rule(
        "not_json",
        "the file is not valid JSON (a byte-order mark makes it not valid), or is not UTF-8 text",
    ),
    Rule("too_long", "the file is longer than $max_bytes bytes"),
    Rule("wrong_form", "the form or the version is not the one given above"),
    Rule("missing_key", "a key given above, not marked optional, is missing"),
    Rule(
        "unlisted_key",
        "a key this form does not name (the scorer reads a few optional keys that a designer never "
        "writes; any other is refused)",
    ),
    Rule(
        "bare_number",
        'a setting, a timing field or a coefficient that is not {"$Measure_value": N, '
        '"$Measure_unit": "U"}, or whose number is not a finite JSON number',
    ),
    Rule(
        "unit_spelling",
        "a setting or a timing field in any unit but the one given, however equivalent",
    ),
    Rule("out_of_range", "a number outside its range"),
    Rule("not_whole", "a setting that must be a whole number ($whole_names) and is not"),
    Rule(
        "over_a_limit", "more coefficients, states, lines, terms or factors than the limits above"
    ),
    Rule(
        "delays_too_long",
        "delays that together span more than $delay_samples periods",
    ),
    Rule(
        "term_number",
        "a term's number of 0, or a number of a term or a coefficient larger than $law_magnitude",
    ),
    Rule(
        "undeclared_name",
        "a name used and not declared: a coefficient a term uses, or a state or a line it reads",
        "malformed",
    ),
    Rule("later_line", "a line that reads a line after it", "malformed"),
    Rule("repeated_name", "a state or a line named twice, or named as a signal or as period"),
    Rule("bad_name", "a name that does not follow the name rule above"),
    Rule("bad_sign", "a term's sign that is not $signs"),
    Rule("period_declared", "a coefficient named period"),
    Rule("unit_not_a_unit", "a unit that is not written as the units rule above says"),
    Rule(
        "unit_imbalance",
        "a term whose coefficients and variable do not multiply to its line's unit, or a state "
        "whose unit is not its line's",
        "units_do_not_balance",
    ),
    Rule("command_not_a_line", "a command that is not a line in the unit 1"),
    Rule("state_without_line", "a state whose next is not the name of a line"),
    Rule(
        "applied_misplaced",
        'a state marked "$Memory_applied" whose next is not the command line',
        "malformed",
    ),
    Rule("zero_divisor", 'a "per" coefficient whose value is 0', "zero_divisor"),
    Rule(
        "number_underflows",
        "a number of a law (a coefficient, the period, a term's number) that reads as 0 as a float "
        "though it is not written as 0",
        answer_module.UNDERFLOWS,
    ),
    Rule(
        "number_overflows",
        "a number of a law that is infinite as a float",
        answer_module.OVERFLOWS,
    ),
    Rule(
        "law_too_large",
        "a law too large to analyse (a long delay, many states and a short period each add to "
        "the work)",
        "work_bound",
    ),
)

#: What makes an answer not judged: not a fail of the design, and never a pass.
NOT_JUDGED: tuple[Rule, ...] = (
    Rule(
        "nonlinear",
        "a term that is not one coefficient-weighted variable: a product of two variables, a "
        "function, a comparison, or any key in a term that is not given above",
        "nonlinear",
    ),
    Rule(
        "out_of_scope",
        "a variable that is a well-formed lower-case name but not one of the signals above (an "
        "accelerometer's reading, say)",
        "out_of_scope",
    ),
)

#: Every field and bound of an answer that the block does not tell, each with why. A new field or
#: bound fails the introspection row until it is told or listed here.
_NAMED = (
    "belongs to a named structure, which the scorer accepts and the block does not describe: one "
    "structure only is told, and telling the others would hint at a design"
)
_VECTORS = (
    "belongs to the test vectors of a law file, which an answer does not carry and only the "
    "harness's exporter reads; a designer is not asked for vectors"
)
_CHECKS = (
    "a tolerance of the exporter's check of a law against its own vectors, which an answer does "
    "not carry"
)
NOT_TOLD: dict[str, str] = {
    "WholeRunV3.analysed_controller": (
        "the controller the analysis is shown for; the harness's exporter never writes it, so a "
        "requirement on it is not judged for both arms and is left out of every task"
    ),
    "WholeRunV3.files": "names module files the answer refers to; reading them grants nothing",
    "WholeRunV3.files:max_length": "belongs to files, which is not told",
    "ParametersV3.gyro_sensitivity": (
        "optional; needed only by a controller written natively, which is not described"
    ),
    "SampledLaw.no_interface_statement": (
        "a flag the harness's exporter sets from the run's interface; a designer never states it"
    ),
    "SampledLaw.compute_delay_flags": (
        "a flag the harness's exporter sets about where the compute delay comes from"
    ),
    "SampledLaw.compute_delay_omitted": (
        "the names the exporter's compute-delay flag refers to; a designer never states it"
    ),
    "SampledLaw.compute_delay_omitted:max_length": "belongs to compute_delay_omitted, not told",
    "Term.of:max_length": "far above any variable the form names; no designer reaches it",
    "answer.MAX_MAGNITUDE": (
        "bounds every number of an answer; every range the block states lies well inside it"
    ),
    "Measure.unit:min_length": (
        "an empty unit is no unit; every unit the block shows is a word or 1, so none is told empty"
    ),
    "answer.NOT_A_NUMBER": (
        "no JSON text can write a number that is not a number; the block says a number is a "
        "finite JSON number, and the other two refusals of a law's number are told by name"
    ),
    "answer.MAX_FILES": "belongs to files, which is not told",
    "answer.MAX_PATH_LENGTH": "belongs to files, which is not told",
    "law.MAX_VECTORS": _VECTORS,
    "law.MAX_ROWS": _VECTORS,
    "law.MAX_TOTAL_ROWS": _VECTORS,
    "law.MAX_CHECK_WORK": "bounds the exporter's check of a law against its vectors",
    "law.MAX_FILE_BYTES": "bounds a law file, which an answer does not carry",
    "unit_spelling.MAX_LENGTH": (
        "the longest unit of a coefficient; the block tells the smaller bound a state's or a "
        "line's unit has, which is the one a designer must keep to"
    ),
    "scenario.MAX_WORK": (
        "a frozen constant of the scorer; the block says only that a law too large to analyse is "
        "refused, never how large"
    ),
    "FIELD_BOUNDS.update_time": _NAMED,
    "FIELD_BOUNDS.angle_gain": _NAMED,
    "FIELD_BOUNDS.rate_gain": _NAMED,
    "FIELD_BOUNDS.distance_gain": _NAMED,
    "FIELD_BOUNDS.speed_gain": _NAMED,
    "FIELD_BOUNDS.rate_ratio": _NAMED,
    "FIELD_BOUNDS.angle_decay_per_update": _NAMED,
    "FIELD_BOUNDS.motor_speed_limit": _NAMED,
    "FIELD_BOUNDS.angle_rate_ratio": _NAMED,
    "FIELD_BOUNDS.angle_response": _NAMED,
    "FIELD_BOUNDS.distance_response": _NAMED,
    "FIELD_BOUNDS.speed_response": _NAMED,
    "FIELD_BOUNDS.gear_ratio_coefficient": _NAMED,
    "FIELD_BOUNDS.response_divisor": _NAMED,
    "FIELD_BOUNDS.gyro_divisor": _NAMED,
    "FIELD_BOUNDS.angle_decay_numerator": _NAMED,
    "FIELD_BOUNDS.angle_decay_denominator": _NAMED,
    "FIELD_BOUNDS.gyro_sensitivity": "bounds gyro_sensitivity, which is not told",
    "law.DUTY_TOLERANCE": _CHECKS,
    "law.COUNT_TOLERANCE": _CHECKS,
    "law.MIN_ROWS": _VECTORS,
    "law.PIN_RELATIVE": _CHECKS,
    "law.PIN_STEPS": _CHECKS,
}

#: What each signal is, in the words the block uses. Held to the schema's own list of signals.
SIGNAL_MEANINGS: dict[str, str] = {
    "tilt": "the body's true tilt from vertical; positive leaning forward",
    "tilt_rate": "the tilt's rate (the gyro)",
    "wheel_angle": (
        "the mean of the two wheels' turn relative to the body (the encoders); positive rolling "
        "forward"
    ),
    "wheel_speed": "the wheel angle's rate (the encoders)",
    "wheel_reference": (
        "the wheel angle the law holds; it advances at the commanded wheel speed, and is zero "
        "where no speed is commanded and in the loop whose stability is judged"
    ),
}

#: What each told key of the answer is, where it is not a literal.
_KEY_PROSE: dict[str, str] = {
    "controller": "the law, below",
    "parameters": "the $setting_count settings, below",
}

_INTRO = (
    "Write one file, $answer_file, in the directory you work in. It is UTF-8 JSON, with no "
    "byte-order mark, of at most $max_bytes bytes. It states the choices of your design: "
    "$setting_count settings and the control law your firmware runs. It holds no model of the "
    "robot. A fixed scorer computes every consequence itself, on a model of the kit that is not "
    "given to you. A requirement that depends on the robot's physics (a current, a margin) is "
    "judged over the stated tolerances and uncertainty of that model, not only at nominal values."
)
_NUMBERS = (
    'Every setting, every timing field and every coefficient is {"$Measure_value": N, '
    '"$Measure_unit": "U"}; a bare number there is refused. A number is a finite JSON number. For '
    "the settings and the timing fields, the unit is spelt exactly as given here; any other "
    "spelling of the same unit is refused. Units inside the law are written as UNITS IN THE LAW "
    "says. Write each number of a law with at most $digits significant digits, and each key once."
)

_RATE = (
    '"$update_rate_name" and the controller\'s "$SampledLaw_period" are two statements: each is '
    "held to its own range, and nothing else ties one to the other."
)
_UNIT_RULES = (
    "Two writings with the same symbols and powers are one unit. A state's or a line's unit is at "
    'most $unit_length characters. Every term\'s coefficients, "$Term_per" coefficients and '
    "variable must multiply to the line's unit, and the command's unit is \"1\". Use rad, never "
    "deg, in a law."
)

_PARAGRAPHS: dict[str, str] = {
    "p_coefficients": (
        '"$SampledLaw_coefficients": an object, name to {"$Measure_value": N, "$Measure_unit": '
        '"U"}. At most $max_coefficients. A name is one character of $name_head then at most '
        "$name_tail characters of $name_rest. A coefficient's name is its own: a state or a line "
        "may bear the same name. A value's size is at most $law_magnitude; 0 is allowed. Do not "
        'declare "$reserved_name": it is the period above, in $period_unit, and any term may use '
        "it."
    ),
    "p_memory": (
        '"$SampledLaw_memory" (optional): a list of at most $max_memory states kept from one '
        'update to the next. Each is {"$Memory_name": ..., "$Memory_unit": ..., "$Memory_next": '
        "<name of a line>}. A state's value at the next update is the value of the line "
        "\"$Memory_next\" at this update, and that line's unit must be the state's. Add "
        '"$Memory_applied": true only on the one state that holds the command as applied; its '
        '"$Memory_next" is then the command line and its unit "1".'
    ),
    "p_lines": (
        '"$SampledLaw_lines": an ordered list of $min_lines to $max_lines lines. Each is '
        '{"$Line_name": ..., "$Line_unit": ..., "$Line_terms": [...]} with $min_terms to '
        "$max_terms terms. A line's value is the sum of its terms. A line may read only lines "
        "before it. A state and a line are named as a coefficient is, each name once, and never "
        'as a signal below or as "$reserved_name".'
    ),
    "p_term": (
        'A term: {"$Term_sign": the number $signs, "$Term_number": N (optional, default '
        '$default_number), "$Term_coefficients": [names] (optional, at most $max_factors), '
        '"$Term_per": [names] (optional, at most $max_factors), "$Term_of": <one variable>}. A '
        "term's sign and number "
        "are plain JSON numbers. Its value = sign * number * (the coefficients multiplied) / "
        '(the "$Term_per" coefficients multiplied) * the variable. "$Term_number" is never 0 and '
        "its size is at most $law_magnitude: to switch a term off give a coefficient the value 0. "
        'A "$Term_per" coefficient must not be 0.'
    ),
    "p_command": (
        '"$SampledLaw_command": the name of the line that is the motor command. Its unit is "1".'
    ),
}

# Proposal, not frozen: the text of this block is a proposal. Nothing in it is a frozen
# criterion, threshold or task, and it is meant to change whenever the schema or a reviewer says.
_TEMPLATE = Template(
    """\
THE ANSWER

$intro

Write exactly these $key_count keys:
$keys

$numbers

PARAMETERS (all $setting_count, each in its one unit, within its range)
$parameters
A setting the requirements above do not fix is still stated, within its range.
$rate

CONTROLLER
  "$SampledLaw_structure": "$structure_value"
$timing
  The two delays together span at most $delay_samples periods.
  State the delays your design has.
$p_coefficients
$p_memory
$p_lines
$p_term
$p_command

  The variable of a term, exactly one of:
$signals
$signal_notes

UNITS IN THE LAW
$unit_grammar
$unit_rules

WHAT IS JUDGED
  The law, sampled at the period with the two delays, is closed around a linearised model of the
  kit. The command limit, integer rounding, noise and sensor bias are not part of that analysis.
  The loop must be stable with the wheels returning, not only the body upright.
  A memory state that adds up the wheel angle, the wheel speed or the command (a counter, an
  odometer, an anti-windup memory) and that the command does not read makes the loop unstable; keep
  such a state out of the law. A state the command reads is judged with the loop, like any other.
  A state that keeps its value exactly (a leak of exactly 1) is allowed where the loop drives it
  back. If the tilt, its rate or the reference feeds such a state and the command reads it, the
  answer is then reported in a class of its own. A leak that is not exactly 1 but within a rounding
  error of it is judged unstable.

WHAT IS REFUSED, AND WHAT IS NOT JUDGED
  Where a name is given in brackets, the scorer reports the fault by that name.
  Refused (a failed answer, with its reason):
$refused
  Not judged (the answer counts as not passed, and stays in the count; it is never a failed
  design):
$not_judged
  A law is judged only if it is otherwise valid: a fault listed under refused, anywhere in the
  answer, fails it whatever else it holds. Write only linear laws over the listed signals.

AN EXAMPLE OF THE FORM ONLY
  It shows the form and nothing else. Its numbers are arbitrary placeholders: it is not a design,
  not advice and not a starting point, and it is not claimed to meet any requirement above.
$example
"""
)

#: The models whose field names the template writes; each field not in :data:`NOT_TOLD` is a fact
#: ``<Model>_<field>`` the template must read, or the block is not written.
_FIELD_MODELS: tuple[Any, ...] = (
    answer_module.SampledLaw,
    law_module.Memory,
    law_module.Line,
    law_module.Term,
    Measure,
)
#: The timing fields of the controller, each with what it means; the unit and the range are read.
_TIMING_MEANING: dict[str, str] = {
    "period": "the law runs once every period",
    "command_limit": (
        "a duty: the average motor voltage as a fraction of the pack voltage; the command is held "
        "to [-command_limit, +command_limit]"
    ),
    "sensor_delay": (
        "the measurements the law reads at an update were taken this long before the update"
    ),
    "compute_delay": "the command computed at an update reaches the motors this long after it",
}


class _Facts(dict[str, str]):
    """The facts the block is written from; every fact must be read by the text."""

    def __init__(self, items: dict[str, str]) -> None:
        super().__init__(items)
        self.read: set[str] = set()

    def __getitem__(self, key: str) -> str:
        self.read.add(key)
        return super().__getitem__(key)


def _n(value: float) -> str:
    """``value`` as a plain number: a whole one without a point, any other as written."""
    return str(int(value)) if float(value).is_integer() else repr(float(value))


def _range(bound: answer_module.FieldBound) -> str:
    return f"{'above' if bound.low_open else 'from'} {_n(bound.low)} to {_n(bound.high)}"


def _literal(model: Any, field: str) -> Any:
    args = get_args(model.model_fields[field].annotation)
    if len(args) != 1:
        msg = f"{model.__name__}.{field} is not one literal value"
        raise FormError(msg)
    return args[0]


def _limit(model: Any, field: str, kind: str) -> int:
    """The ``kind`` (``max_length`` or ``min_length``) limit the model puts on ``field``."""
    for meta in model.model_fields[field].metadata:
        if hasattr(meta, kind):
            return int(getattr(meta, kind))
    msg = f"{model.__name__}.{field} has no {kind}"
    raise FormError(msg)


#: The units the probe of :func:`_timing_units` writes the fields it does not probe in, so that
#: only the probed one is wrong. Never printed: a unit the schema gives otherwise makes the probe
#: fail loudly (a :class:`FormError`), never the block say a wrong one.
_ASSUMED_UNITS = {"period": "s", "command_limit": "1", "sensor_delay": "s", "compute_delay": "s"}


def _timing_units() -> dict[str, str]:
    """The unit each timing field is given in, read from the schema's own refusal of another.

    The four units are literals inside a validator. A probe with a unit no model has (every other
    field valid) is refused with ``it is given in 'U'``, which is the one place the schema says it.
    """
    # every field valid, at the middle of its own range, so only the probed unit is wrong
    valid: dict[str, Any] = {}
    for field in _TIMING_MEANING:
        bound = answer_module.FIELD_BOUNDS[field]
        valid[field] = {"value": (bound.low + bound.high) / 2, "unit": _ASSUMED_UNITS[field]}
    units: dict[str, str] = {}
    for field in _TIMING_MEANING:
        probe = {**valid, field: {**valid[field], "unit": "probe_unit"}}
        try:
            answer_module._Loop.model_validate(probe)  # noqa: SLF001
        except ValidationError as exc:
            found = re.search(r"it is given in '([^']*)'", exc.errors()[0]["msg"])
            if found is not None:
                units[field] = found.group(1)
                continue
        msg = f"the schema does not say what unit {field} is given in"
        raise FormError(msg)
    return units


def _setting_unit(name: str) -> str:
    return answer_module.SETTINGS[name][0]


def _whole_settings(told: list[str]) -> list[str]:
    """The told settings the schema holds to whole numbers, found by asking it about 1.5."""
    return [
        name
        for name in told
        if "whole number" in (answer_module.setting_problem(name, 1.5, _setting_unit(name)) or "")
    ]


def _told_settings() -> list[str]:
    if set(answer_module.SETTINGS) != set(answer_module.ParametersV3.model_fields):
        msg = "the settings the schema lists are not the fields of its parameters"
        raise FormError(msg)
    told = [n for n in answer_module.SETTINGS if f"ParametersV3.{n}" not in NOT_TOLD]
    optional = [n for n in told if not answer_module.ParametersV3.model_fields[n].is_required()]
    if optional:
        msg = f"a setting that is optional cannot be told as one of all the settings: {optional}"
        raise FormError(msg)
    return told


def _told_setting(name: str, told: list[str]) -> str:
    if name not in told:
        msg = f"the block's text names the setting {name}, which it does not tell"
        raise FormError(msg)
    return name


def _parameters(told: list[str]) -> str:
    whole = _whole_settings(told)
    width = max(len(n) for n in told)
    rows = []
    for name in told:
        unit, bound_name = answer_module.SETTINGS[name]
        note = ""
        if name in whole:
            note = "   (a whole number)"
        elif unit == "count":
            note = "   (need not be whole)"
        bound = answer_module.FIELD_BOUNDS[bound_name]
        rows.append(f"  {name:<{width}}  {unit:<5}  {_range(bound)}{note}")
    return "\n".join(rows)


def _wrap(text: str, indent: str, hang: str, width: int = 100) -> str:
    return textwrap.fill(
        text, width=width, initial_indent=indent, subsequent_indent=hang, break_long_words=False
    )


def _timing(units: dict[str, str], facts: _Facts) -> str:
    return "\n".join(
        _wrap(
            f'"{facts[f"SampledLaw_{field}"]}": unit "{units[field]}", '
            f"{_range(answer_module.FIELD_BOUNDS[field])}. {text[0].upper()}{text[1:]}.",
            "  ",
            "      ",
        )
        for field, text in _TIMING_MEANING.items()
    )


def _signals() -> str:
    if list(SIGNAL_MEANINGS) != list(law_module.SIGNALS):
        msg = "the block's meaning of the signals is not the schema's list of signals"
        raise FormError(msg)
    width = max(len("previous.<state>"), *(len(n) for n in law_module.SIGNALS))
    rows = [
        _wrap(
            f"{name:<{width}}  {unit:<5} {SIGNAL_MEANINGS[name]}",
            "    ",
            "    " + " " * (width + 8),
        )
        for name, unit in law_module.SIGNALS.items()
    ]
    rows.append(
        f"    {'previous.<state>':<{width}}  the value of a memory state before this update"
    )
    rows.append(f"    {'line.<name>':<{width}}  the value of an earlier line this update")
    return "\n".join(rows)


def _keys(setting_count: str) -> list[str]:
    model = answer_module.WholeRunV3
    rows = []
    for field in model.model_fields:
        if f"WholeRunV3.{field}" in NOT_TOLD:
            continue
        if field in _KEY_PROSE:
            prose = Template(_KEY_PROSE[field]).substitute(setting_count=setting_count)
            rows.append(f'  "{field}": {prose}')
        else:
            rows.append(f'  "{field}": {json.dumps(_literal(model, field))}')
    return rows


def _rules(rules: tuple[Rule, ...], facts: _Facts, final: str) -> str:
    rows = []
    for at, rule in enumerate(rules):
        text = Template(rule.text).substitute(facts)
        end = final if at == len(rules) - 1 else ";"
        rows.append(
            _wrap(f"- {text}" + (f" ({rule.name})" if rule.name else "") + end, "    ", "      ")
        )
    return "\n".join(rows)


def _prose(text: str, facts: _Facts) -> str:
    return textwrap.fill(Template(text).substitute(facts), width=100, break_long_words=False)


def example_text() -> str:
    """The committed example, as written, without its final newline."""
    return EXAMPLE_PATH.read_text(encoding="utf-8").rstrip("\n")


_WORDS = {1: "one", 2: "two", 3: "three", 4: "four", 5: "five", 6: "six", 7: "seven", 8: "eight"}


def _count(n: int) -> str:
    return _WORDS.get(n, str(n))


def _name_pattern() -> tuple[str, str, str]:
    """The character classes of a name's first and later characters and its tail length.

    Read from the schema's own pattern; a pattern of another shape is a :class:`FormError`.
    """
    rules: tuple[Any, ...] = getattr(law_module.Name, "__metadata__", ())
    pattern = str(getattr(rules[0], "pattern", "")) if rules else ""
    found = re.fullmatch(r"\^\[([^\]]+)\]\[([^\]]+)\]\{0,(\d+)\}\$", pattern)
    if found is None:
        msg = "the schema's pattern for a name is not a first class, a later class and a length"
        raise FormError(msg)
    return found.group(1), found.group(2), found.group(3)


def _class_words(chars: str) -> str:
    """A pattern's character class as the block spells it: ``a-z0-9_`` as ``a-z, 0-9, _``."""
    return ", ".join(re.findall(r"[A-Za-z0-9]-[A-Za-z0-9]|.", chars))


def _signs() -> str:
    """The values a term's sign may have, as the block says them: ``1 or -1``."""
    values = [str(v) for v in get_args(law_module.Term.model_fields["sign"].annotation)]
    if not values:
        msg = "a term's sign is not a set of values"
        raise FormError(msg)
    return " or ".join([", ".join(values[:-1]), values[-1]] if len(values) > 1 else values)


def _unit_symbols(period_unit: str) -> str:
    """The unit symbols a law is written in: those of the signals' units and of the period."""
    names = {
        name
        for unit in (*law_module.SIGNALS.values(), period_unit)
        for name, _ in law_module.dimension(unit)
    }
    ordered = sorted(names)
    if len(ordered) < 2:
        return ", ".join(ordered)
    return ", ".join(ordered[:-1]) + " and " + ordered[-1]


def _signal(name: str) -> str:
    if name not in law_module.SIGNALS:
        msg = f"the block's notes name a signal the schema does not have: {name}"
        raise FormError(msg)
    return name


def _signal_notes() -> str:
    """What the signals' list does not say: their signs, what the tilt is, a speed command."""
    wheel_angle, wheel_speed = _signal("wheel_angle"), _signal("wheel_speed")
    tilt, tilt_rate = _signal("tilt"), _signal("tilt_rate")
    reference = _signal("wheel_reference")
    notes = (
        f"A positive command drives the wheels forward: the {wheel_angle} and the {wheel_speed} "
        f"increase under it. The {wheel_angle} is measured against the body, so the body leaning "
        f"forward over wheels that stay put reads as a negative {wheel_angle}.",
        f"No sensor of the kit gives the {tilt}: the gyro gives its rate ({tilt_rate}). A law that "
        f"reads {tilt} is judged as if it knew the tilt exactly.",
        f"A speed command appears as {reference}: an angle in rad that advances at the commanded "
        f"wheel speed in rad/s. A law that wants the commanded speed takes the change of "
        f"{reference} since the last update, over the period; that needs a memory state holding "
        f"the last {reference}.",
    )
    return "\n".join(_wrap(note, "  ", "  ") for note in notes)


def _unit_grammar(period_unit: str) -> str:
    written = ", ".join(UNIT_WRITTEN)
    refused = ", ".join(f"{words} ({spellings})" for words, spellings in _UNIT_REFUSED)
    text = (
        "The unit of a coefficient, a state or a line is a product of unit symbols with whole "
        f"powers. The symbols are {_unit_symbols(period_unit)}, and 1 for none. Write a product "
        f"with *, a quotient with /, a power with **: {written}. A bracket is allowed only after "
        f"a /, to divide by a product. A / divides by the one factor that follows it, so "
        f"{UNIT_QUOTIENT[0]} is {UNIT_QUOTIENT[1]}. A unit starts with a symbol or with 1. "
        f"Refused: {refused}."
    )
    return _wrap(text, "  ", "  ")


def _facts() -> _Facts:
    told = _told_settings()
    period_unit = _timing_units()["period"]
    keys = _keys(_count(len(told)))
    facts: dict[str, str] = {}
    for model in _FIELD_MODELS:
        for field in model.model_fields:
            if f"{model.__name__}.{field}" not in NOT_TOLD:
                facts[f"{model.__name__}_{field}"] = field
    facts.update(
        {
            "answer_file": ANSWER_FILE,
            "max_bytes": _n(answer_module.MAX_ANSWER_BYTES),
            "setting_count": _count(len(told)),
            "key_count": _count(len(keys)),
            "keys": "\n".join(keys),
            "digits": str(SIGNIFICANT_DIGITS),
            "parameters": _parameters(told),
            "structure_value": _literal(answer_module.SampledLaw, "structure"),
            "delay_samples": _n(answer_module.MAX_DELAY_SAMPLES),
            "max_coefficients": _n(law_module.MAX_COEFFICIENTS),
            "name_head": _class_words(_name_pattern()[0]),
            "name_rest": _class_words(_name_pattern()[1]),
            "name_tail": _name_pattern()[2],
            "signs": _signs(),
            "update_rate_name": _told_setting("update_rate", told),
            "period_unit": period_unit,
            "signal_notes": _signal_notes(),
            "unit_grammar": _unit_grammar(period_unit),
            "law_magnitude": _n(answer_module.LAW_MAGNITUDE),
            "reserved_name": law_module.PERIOD,
            "max_memory": _n(law_module.MAX_MEMORY),
            "min_lines": _n(_limit(answer_module.SampledLaw, "lines", "min_length")),
            "max_lines": _n(law_module.MAX_LINES),
            "min_terms": _n(_limit(law_module.Line, "terms", "min_length")),
            "max_terms": _n(law_module.MAX_TERMS),
            "max_factors": _n(law_module.MAX_FACTORS),
            "default_number": _n(law_module.Term.model_fields["number"].default),
            "signals": _signals(),
            "unit_length": _n(
                min(
                    _limit(law_module.Line, "unit", "max_length"),
                    _limit(law_module.Memory, "unit", "max_length"),
                )
            ),
            "whole_names": ", ".join(_whole_settings(told)),
        }
    )
    return _Facts(facts)


def render_answer_form() -> str:
    """The block every whole-design brief ends with: the answer's form as a designer is told it.

    Every fact the schema holds is read from it. The result is the same bytes on every call and
    holds no placeholder. A fact the text never reads (a field of the schema the block does not
    place) or a placeholder with no fact (a field the schema no longer has) is a :class:`FormError`.

    Raises:
        FormError: the block cannot be written true to the schema.
    """
    facts = _facts()
    try:
        facts["timing"] = _timing(_timing_units(), facts)
        for key, text in _PARAGRAPHS.items():
            facts[key] = textwrap.fill(
                Template(text).substitute(facts),
                width=100,
                initial_indent="  ",
                subsequent_indent="      ",
                break_long_words=False,
            )
        facts["intro"] = _prose(_INTRO, facts)
        facts["numbers"] = _prose(_NUMBERS, facts)
        for key, text in (("rate", _RATE), ("unit_rules", _UNIT_RULES)):
            facts[key] = textwrap.fill(
                Template(text).substitute(facts),
                width=100,
                initial_indent="  ",
                subsequent_indent="  ",
                break_long_words=False,
            )
        facts["refused"] = _rules(REFUSED, facts, ".")
        facts["not_judged"] = _rules(NOT_JUDGED, facts, ".")
        facts["example"] = "\n".join(
            "  " + line if line else line for line in example_text().splitlines()
        )
        block = _TEMPLATE.substitute(facts)
    except KeyError as exc:
        msg = f"the text reads {exc}, which the schema no longer has"
        raise FormError(msg) from exc
    unread = set(facts) - facts.read
    if unread:
        msg = f"facts the text does not read (a field or a bound placed nowhere): {sorted(unread)}"
        raise FormError(msg)
    if "$" in block:
        msg = "a placeholder is left in the block"
        raise FormError(msg)
    return block


def answer_form_sha256() -> str:
    """The block's sha256, in hex: what a tier version's requirements pin."""
    return hashlib.sha256(render_answer_form().encode("utf-8")).hexdigest()
