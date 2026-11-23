"""Answers each built to break exactly one rule the answer-form block names.

A reader who has only the block must be able to follow it: for every rule it lists as refused or
not judged, the answer here that breaks that rule and no other is read as the block says. The
cases are written apart from the form module, from the committed example: a case is the example
with one edit. Pure data and ``json``: it needs neither numpy nor the scorer, so the unit rows and
the scoring rows share it.

``parse`` says what reading the answer gives: ``refused`` (a failed answer), ``outside`` (a law
the scorer cannot take: not judged) or ``parses`` (valid, and refused later by the scorer's own
work bound). ``outcome`` is what the scorer's record says.
"""

from __future__ import annotations

import copy
import json
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from typing import Any

EXAMPLE = (
    Path(__file__).resolve().parents[4] / "src/physgate/evaluation/whole/answer_form_example.json"
)


@dataclass(frozen=True)
class Case:
    """One answer built to break one rule: the bytes, how they read, and the scorer's outcome."""

    label: str
    data: bytes
    parse: str
    outcome: str


def example() -> dict[str, Any]:
    """The committed example as a document."""
    doc: dict[str, Any] = json.loads(EXAMPLE.read_text(encoding="utf-8"))
    return doc


def _measure(value: object, unit: str) -> dict[str, object]:
    return {"value": value, "unit": unit}


def _edited(edit: Callable[[dict[str, Any]], None]) -> bytes:
    doc = copy.deepcopy(example())
    edit(doc)
    return json.dumps(doc).encode()


def _command_terms(doc: dict[str, Any]) -> list[dict[str, Any]]:
    terms: list[dict[str, Any]] = doc["controller"]["lines"][1]["terms"]
    return terms


def _refused(label: str, edit: Callable[[dict[str, Any]], None]) -> Case:
    return Case(label, _edited(edit), "refused", "fail")


def _text(label: str, old: str, new: str, parse: str = "refused", outcome: str = "fail") -> Case:
    text = json.dumps(example())
    assert text.count(old) == 1, old
    return Case(label, text.replace(old, new).encode(), parse, outcome)


def _put(path: tuple[str | int, ...], value: object) -> Callable[[dict[str, Any]], None]:
    def edit(doc: dict[str, Any]) -> None:
        node: Any = doc
        for key in path[:-1]:
            node = node[key]
        node[path[-1]] = value

    return edit


def _drop(path: tuple[str | int, ...]) -> Callable[[dict[str, Any]], None]:
    def edit(doc: dict[str, Any]) -> None:
        node: Any = doc
        for key in path[:-1]:
            node = node[key]
        del node[path[-1]]

    return edit


def _more_coefficients(doc: dict[str, Any]) -> None:
    for at in range(28):
        doc["controller"]["coefficients"][f"spare{at}"] = _measure(1, "1")


def _more_states(doc: dict[str, Any]) -> None:
    for at in range(8):
        doc["controller"]["memory"].append(
            {"name": f"spare{at}", "unit": "rad", "next": "tilt_est_now"}
        )


def _more_lines(doc: dict[str, Any]) -> None:
    extra = [
        {
            "name": f"spare{at}",
            "unit": "rad",
            "terms": [{"sign": 1, "coefficients": ["period"], "of": "tilt_rate"}],
        }
        for at in range(31)
    ]
    doc["controller"]["lines"][1:1] = extra


def _more_terms(doc: dict[str, Any]) -> None:
    term = {"sign": 1, "coefficients": ["k_rate"], "of": "tilt_rate"}
    _command_terms(doc).extend([copy.deepcopy(term) for _ in range(13)])


def _more_factors(doc: dict[str, Any]) -> None:
    _command_terms(doc)[0]["coefficients"] = ["leak"] * 5


def _swap_lines(doc: dict[str, Any]) -> None:
    lines = doc["controller"]["lines"]
    lines[0], lines[1] = lines[1], lines[0]


def _timing(period: float, sensor: float, compute: float) -> Callable[[dict[str, Any]], None]:
    def edit(doc: dict[str, Any]) -> None:
        controller = doc["controller"]
        controller["period"]["value"] = period
        controller["sensor_delay"]["value"] = sensor
        controller["compute_delay"]["value"] = compute

    return edit


def _a_zero_divisor(doc: dict[str, Any]) -> None:
    doc["controller"]["coefficients"]["nothing"] = _measure(0, "1")
    _command_terms(doc).append(
        {"sign": 1, "coefficients": ["k_rate"], "per": ["nothing"], "of": "tilt_rate"}
    )


def _a_term(of: str, **extra: object) -> Callable[[dict[str, Any]], None]:
    def edit(doc: dict[str, Any]) -> None:
        _command_terms(doc).append({"sign": 1, "coefficients": ["k_rate"], "of": of, **extra})

    return edit


def _not_judged(label: str, edit: Callable[[dict[str, Any]], None]) -> Case:
    return Case(label, _edited(edit), "outside", "unscored")


def cases() -> dict[str, list[Case]]:
    """Every rule's key (:data:`~physgate.evaluation.whole.form.REFUSED` and ``NOT_JUDGED``)."""
    long_file = json.dumps(example()).encode() + b" " * 70_000
    return {
        "not_json": [
            Case("not JSON", b"{not json", "refused", "fail"),
            Case("not UTF-8", b"\xff\xfe{}", "refused", "fail"),
        ],
        "too_long": [Case("padded past the limit", long_file, "refused", "fail")],
        "wrong_form": [
            _refused("a wrong form", _put(("form",), "whole_runs")),
            _refused("a version that is none", _put(("version",), 4)),
            _refused("a version written as text", _put(("version",), "3")),
        ],
        "missing_key": [
            _refused("no parameters", _drop(("parameters",))),
            _refused("no period", _drop(("controller", "period"))),
            _refused("no lines", _drop(("controller", "lines"))),
            _refused("no setting", _drop(("parameters", "pwm_frequency"))),
        ],
        "unlisted_key": [
            _refused("test vectors in the controller", _put(("controller", "vectors"), [])),
            _refused("a key in the answer", _put(("notes",), "x")),
            _refused("a key in the parameters", _put(("parameters", "gyro_range"), 1)),
            _refused("a key in a state", _put(("controller", "memory", 0, "kind"), "x")),
            _refused("a key in a line", _put(("controller", "lines", 0, "kind"), "x")),
            _refused(
                "version 2's name of a setting",
                lambda d: d["parameters"].update(
                    gyro_output_data_rate=d["parameters"].pop("output_data_rate")
                ),
            ),
        ],
        "bare_number": [
            _refused("a bare setting", _put(("parameters", "update_rate"), 50)),
            _refused("a bare period", _put(("controller", "period"), 0.02)),
            _refused("a bare coefficient", _put(("controller", "coefficients", "leak"), 0.8)),
            _text("a number written as text", "0.6", '"0.6"'),
        ],
        "unit_spelling": [
            _refused("update rate in 1/s", _put(("parameters", "update_rate", "unit"), "1/s")),
            _refused("period in seconds", _put(("controller", "period", "unit"), "sec")),
            _refused("a limit in a percent", _put(("controller", "command_limit", "unit"), "%")),
            _refused(
                "a scale in deg per s", _put(("parameters", "gyro_full_scale", "unit"), "deg/sec")
            ),
        ],
        "out_of_range": [
            _refused("period of 2 s", _put(("controller", "period", "value"), 2)),
            _refused("period of 0.0001 s", _put(("controller", "period", "value"), 0.0001)),
            _refused("update rate of 0", _put(("parameters", "update_rate", "value"), 0)),
            _refused("a limit of 1.5", _put(("controller", "command_limit", "value"), 1.5)),
            _refused("a delay of 0.6 s", _put(("controller", "sensor_delay", "value"), 0.6)),
            _refused("a negative delay", _put(("controller", "compute_delay", "value"), -0.001)),
            _refused(
                "a PWM frequency of 2 MHz", _put(("parameters", "pwm_frequency", "value"), 2e6)
            ),
        ],
        "not_whole": [
            _refused(
                "a PWM full scale of 255.5", _put(("parameters", "pwm_full_scale", "value"), 255.5)
            )
        ],
        "over_a_limit": [
            _refused("33 coefficients", _more_coefficients),
            _refused("9 states", _more_states),
            _refused("33 lines", _more_lines),
            _refused("17 terms", _more_terms),
            _refused("5 factors", _more_factors),
            _refused("a name of 33 characters", _put(("controller", "command"), "c" * 33)),
        ],
        "delays_too_long": [
            _refused("60 periods of delay", _timing(0.001, 0.04, 0.02)),
        ],
        "term_number": [
            _refused("a number of 0", _put(("controller", "lines", 1, "terms", 0, "number"), 0)),
            _refused(
                "a number past the limit",
                _put(("controller", "lines", 1, "terms", 0, "number"), 2_000_000),
            ),
            _refused(
                "a coefficient past the limit",
                _put(("controller", "coefficients", "k_angle", "value"), 2_000_000),
            ),
        ],
        "undeclared_name": [
            _refused(
                "a coefficient not declared",
                _put(("controller", "lines", 1, "terms", 1, "coefficients"), ["ghost"]),
            ),
            _refused(
                "a state not declared",
                _put(("controller", "lines", 0, "terms", 0, "of"), "previous.ghost"),
            ),
            _refused(
                "a line not declared",
                _put(("controller", "lines", 1, "terms", 0, "of"), "line.ghost"),
            ),
        ],
        "later_line": [_refused("the command first", _swap_lines)],
        "repeated_name": [
            _refused("two lines of one name", _put(("controller", "lines", 0, "name"), "command")),
            _refused("a line named as a signal", _put(("controller", "lines", 0, "name"), "tilt")),
            _refused(
                "a state named as the period", _put(("controller", "memory", 0, "name"), "period")
            ),
        ],
        "period_declared": [
            _refused(
                "a period among the coefficients",
                _put(("controller", "coefficients", "period"), _measure(1, "s")),
            )
        ],
        "unit_not_a_unit": [
            _refused(
                "a unit with a bracket open",
                _put(("controller", "coefficients", "k_angle", "unit"), "1/(rad"),
            ),
            _refused(
                "a unit of 41 characters",
                _put(("controller", "memory", 0, "unit"), "rad" + "*rad**-1" * 5),
            ),
        ],
        "unit_imbalance": [
            _refused(
                "a gain in 1/deg", _put(("controller", "coefficients", "k_angle", "unit"), "1/deg")
            ),
            _refused("a state in another unit", _put(("controller", "memory", 0, "unit"), "s")),
            _refused("a command in rad", _put(("controller", "lines", 1, "unit"), "rad")),
        ],
        "command_not_a_line": [
            _refused("a command that is no line", _put(("controller", "command"), "ghost"))
        ],
        "state_without_line": [
            _refused(
                "a state that takes no line", _put(("controller", "memory", 0, "next"), "ghost")
            )
        ],
        "zero_divisor": [_refused("a divisor of 0", _a_zero_divisor)],
        "number_underflows": [_text("a coefficient of 1e-400", "0.8", "1e-400")],
        "number_overflows": [_text("a coefficient of 1e999", "0.8", "1e999")],
        "law_too_large": [
            Case(
                "50 periods of delay at 1 ms",
                _edited(_timing(0.001, 0.025, 0.025)),
                "parses",
                "fail",
            ),
        ],
        "nonlinear": [
            _not_judged("a product of two variables", _a_term("tilt*tilt_rate")),
            _not_judged("a function", _a_term("sin(tilt)")),
            _not_judged("a comparison", _a_term("tilt>0")),
            _not_judged("a key a term does not have", _a_term("tilt_rate", power=2)),
        ],
        "out_of_scope": [
            _not_judged("an accelerometer", _a_term("accelerometer")),
            _not_judged("a state named without its prefix", _a_term("tilt_est")),
        ],
    }


def precedence() -> list[Case]:
    """A law with a term not judged and also a fault of the answer: the fault fails it."""

    def edit(doc: dict[str, Any]) -> None:
        _a_term("accelerometer")(doc)
        doc["parameters"]["update_rate"]["value"] = 0

    return [Case("an accelerometer and an update rate of 0", _edited(edit), "refused", "fail")]
