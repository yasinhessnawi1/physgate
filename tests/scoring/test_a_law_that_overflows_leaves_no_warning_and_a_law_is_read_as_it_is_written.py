"""What the scorer's own numerics say and keep: no warning in the log, and each law its own numbers.

An overflowing law ends in a named numerical failure, and the floating-point warnings that came
with it are not left in the scorer's log, in the plant's system nor in the margins. A law's numbers
as written belong to that law: an analysed law has its own, not the primary's, and a law with no
text behind it is decided on the decimals its floats print as. A kernel that holds the wheels alone
is never set aside, and is never stable.
"""

from __future__ import annotations

import importlib
import json
import warnings
from fractions import Fraction
from typing import Any

from physgate.evaluation.whole import loop as loop_module
from physgate.evaluation.whole.answer import (
    OutsideScope,
    WholeRunV3,
    parse_answer,
    parse_answer_scoped,
)
from physgate.evaluation.whole.convert import ScaleFactor, to_si
from physgate.evaluation.whole.plant import nominal

helpers: Any = importlib.import_module("test_a_sampled_law_is_scored_as_the_named_structures_are")
unit_circle: Any = importlib.import_module(
    "test_a_mode_at_one_or_minus_one_is_decided_exactly_never_by_a_float"
)

VALUES = nominal(helpers._plant())


def _chain(extra_line: float | None) -> dict[str, Any]:
    """Lines of 1e12 each: 25 (finite), 26 (overflowing), or 25 and one more by ``extra_line``."""
    coefficients = {**helpers._good_coefficients(0.04), "big": helpers._m(1e6, "1")}
    chain = 26 if extra_line is None else 25
    lines = [
        {
            "name": f"l{n}",
            "unit": "rad",
            "terms": [
                {
                    "sign": 1,
                    "number": 1e6,
                    "coefficients": ["big"],
                    "of": "tilt" if n == 0 else f"line.l{n - 1}",
                }
            ],
        }
        for n in range(chain)
    ]
    reading = f"line.l{chain - 1}"
    terms = [
        *helpers._no_travel_terms(),
        {"sign": 1, "coefficients": ["distance_gain"], "of": "wheel_angle"},
    ]
    if extra_line is not None:
        lines.append(
            {
                "name": "l25",
                "unit": "rad",
                "terms": [{"sign": 1, "number": extra_line, "of": reading}],
            }
        )
        reading = "line.l25"
        terms += [
            {"sign": 1, "number": 1e6, "coefficients": ["distance_gain"], "of": reading}
            for _ in range(12)
        ]
    else:
        terms.append({"sign": 1, "coefficients": ["distance_gain"], "of": reading})
    built: dict[str, Any] = helpers._law(terms, coefficients, [], lines)
    return built


def _no_warning(call: Any) -> Any:
    """The exception ``call`` raises, once it is shown to have left no warning anywhere."""
    with warnings.catch_warnings(record=True) as caught:
        warnings.simplefilter("always")
        try:
            call()
        except loop_module.NUMERICAL_FAILURES as exc:
            raised = exc
        else:
            raised = None
    assert [str(w.message) for w in caught] == []
    return raised


def test_an_overflowing_plant_system_leaves_no_warning_and_is_a_numerical_failure() -> None:
    loop = helpers._loop_of(_chain(None), VALUES)
    raised = _no_warning(lambda: loop_module.system(VALUES, loop))
    assert isinstance(raised, loop_module.SimulationError)


def test_margins_that_overflow_leave_no_warning_and_are_a_numerical_failure() -> None:
    loop: Any = helpers._loop_of(_chain(1e3), VALUES)
    assert max(abs(x) for x in loop.law.d) < float("inf"), "finite in the law, past a float later"
    raised = _no_warning(lambda: loop_module.margins(VALUES, loop))
    assert raised is not None


# ── an analysed law is read on its own numbers, and a refused primary is the one reported ──


def _controller_text(second: str) -> dict[str, Any]:
    """A law whose one state carries itself by 0.9 and ``second``, the text spelling each number."""
    text = (
        '{"structure": "sampled_law", "period": {"value": 0.01, "unit": "s"}, '
        '"command_limit": {"value": 0.75, "unit": "1"}, '
        '"sensor_delay": {"value": 0.0048, "unit": "s"}, '
        '"compute_delay": {"value": 0.004, "unit": "s"}, '
        '"coefficients": {"g": {"value": 0.3, "unit": "1/rad"}, '
        '"first": {"value": 0.9, "unit": "1"}, '
        f'"second": {{"value": {second}, "unit": "1"}}}}, '
        '"memory": [{"name": "z", "unit": "1", "next": "z_now"}], '
        '"lines": [{"name": "z_now", "unit": "1", "terms": ['
        '{"sign": 1, "coefficients": ["first"], "of": "previous.z"}, '
        '{"sign": 1, "coefficients": ["second"], "of": "previous.z"}]}, '
        '{"name": "command", "unit": "1", "terms": ['
        '{"sign": 1, "coefficients": ["g"], "of": "wheel_angle"}]}], "command": "command"}'
    )
    controller: dict[str, Any] = json.loads(text)
    return controller


def _two(first: str, second: str) -> bytes:
    """An answer whose law carries itself by 0.9 and ``first``, the analysed one by ``second``."""
    body = {
        "form": "whole_run",
        "version": 3,
        "parameters": {
            **helpers.SETTINGS,
            "output_data_rate": helpers._m(208, "Hz"),
        },
        "controller": _controller_text(first),
        "analysed_controller": _controller_text(second),
    }
    return json.dumps(body).encode()


def test_an_analysed_law_has_its_own_numbers_as_written_not_the_primary_s() -> None:
    parsed: Any = parse_answer(_two("0.1", "0.2"))
    assert parsed.controller.written.coefficients["second"] == Fraction(1, 10)
    assert parsed.analysed_controller.written.coefficients["second"] == Fraction(1, 5)


def _refusal(raw: bytes) -> OutsideScope | None:
    try:
        parse_answer_scoped(raw)
    except OutsideScope as exc:
        return exc
    return None


def test_when_both_laws_are_refused_the_primary_s_refusal_is_the_one_raised() -> None:
    document = json.loads(_two("0.1", "0.2"))
    document["controller"]["lines"][-1]["terms"].append({"sign": 1, "of": "tilt*tilt_rate"})
    document["analysed_controller"]["lines"][-1]["terms"].append(
        {"sign": 1, "of": "accelerometer_tilt"}
    )
    refusal = _refusal(json.dumps(document).encode())
    assert refusal is not None, "the primary is refused, whatever the analysed law is"
    assert refusal.name == "nonlinear"
    assert str(refusal).startswith("controller is out of the scorer's reach")


# ── a law with no text behind it, and a kernel that is the wheels alone ──


def test_a_law_built_without_its_text_is_decided_on_the_decimals_its_floats_print_as() -> None:
    controller = unit_circle._reviewer()
    raw = helpers._answer(controller, 3)
    answer: Any = WholeRunV3.model_validate_json(raw)
    assert answer.controller.written is None
    radius = ScaleFactor("wheel_radius", VALUES["wheel_radius"], "m", "this test's plant")
    loop: Any = to_si(answer.controller, answer.parameters, wheel_radius=radius)
    assert loop.law.circle.at_one == 1, "0.9 and 0.1 are tenths: an eigenvalue at exactly 1"


def _wheels_alone() -> dict[str, Any]:
    """The command reads a constant memory and never the wheel angle: the kernel is the travel."""
    coefficients = {**helpers._good_coefficients(0.04), "c": helpers._m(0.5, "1")}
    terms = [*helpers._no_travel_terms(), {"sign": 1, "coefficients": ["c"], "of": "previous.z"}]
    lines = [{"name": "z_now", "unit": "1", "terms": [{"sign": 1, "of": "previous.z"}]}]
    memory = [{"name": "z", "unit": "1", "next": "z_now"}]
    built: dict[str, Any] = helpers._law(terms, coefficients, memory, lines)
    return built


def test_a_kernel_that_holds_the_wheels_alone_is_never_set_aside_and_never_stable() -> None:
    loop: Any = helpers._loop_of(_wheels_alone(), VALUES)
    assert loop.law.held == (), "the travel is no mode to set aside"
    assert loop.law.circle.at_one == 1
    assert not any(unit_circle._stable_at(_wheels_alone(), values) for values in unit_circle.POINTS)
