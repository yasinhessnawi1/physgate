"""A mode held at 1 is set aside only where the wheels return, decided on the numbers as written.

The wheels, displaced alone, must return: a held mode is set aside only if the quantity the law
conserves at rest is fed by nothing the wheels' motion can add (not the command, not a wheel
speed). The plant's own motor force is one combination of the command and the wheel speed, so a
steady cruise has no tilt and no tilt rate: a state fed by those is settled when the wheels are
put back, and one fed by the wheel speed or the wheel angle is not. The rule is exact: the
conditions are solved in rational arithmetic on the decimals as written, so ``0.1`` and ``0.9``
are tenths and a state that carries ``0.9`` and ``0.1`` of itself is held, as one that carries
``0.75`` and ``0.25`` of itself is.
"""

from __future__ import annotations

import importlib
import json
from decimal import Decimal
from fractions import Fraction
from typing import Any

import pytest

from physgate.evaluation.per_role.exceptions import TaskFormatError

_LAW = "physgate.evaluation.whole.law"
_ANSWER = "physgate.evaluation.whole.answer"


def _law() -> Any:
    return importlib.import_module(_LAW)


def _body(memory: list[tuple[str, str]], lines: list[dict[str, Any]], command: list[Any]) -> Any:
    return _law().Body.model_validate_json(
        json.dumps(
            {
                "memory": [{"name": n, "unit": "1", "next": nxt} for n, nxt in memory],
                "lines": [*lines, {"name": "command", "unit": "1", "terms": command}],
                "command": "command",
            }
        )
    )


def _term(of: str, *coefficients: str, sign: int = 1, per: tuple[str, ...] = ()) -> dict[str, Any]:
    out: dict[str, Any] = {"sign": sign, "coefficients": list(coefficients), "of": of}
    if per:
        out["per"] = list(per)
    return out


# the command always holds the wheels with a gain g, so only the memory's own modes are in question
HOLD = [_term("wheel_angle", "g")]


def _state(name: str, *terms: dict[str, Any]) -> dict[str, Any]:
    return {"name": f"{name}_now", "unit": "1", "terms": list(terms)}


def _held(
    memory: list[tuple[str, str]],
    lines: list[dict[str, Any]],
    command: list[Any],
    values: dict[str, float],
) -> Any:
    return _law().held_modes(_body(memory, lines, command), values, period=0.01)


# ── the reviewer's laws: the memory that merely follows the wheel angle ─────────────────────


def test_a_backward_difference_speed_with_no_position_gain_sets_nothing_aside() -> None:
    # command += s·(wheel_angle − previous.last); last' = wheel_angle: the held vector (1, 1) is the
    # travel itself, the memory following it.
    command = [_term("wheel_angle", "s"), _term("previous.last", "s", sign=-1)]
    lines = [_state("last", _term("wheel_angle"))]
    assert _held([("last", "last_now")], lines, command, {"s": 0.05}) == ()


@pytest.mark.parametrize(("keep", "take"), [(0.75, 0.25), (0.9, 0.1), (0.6, 0.4), (0.3, 0.7)])
def test_a_washout_with_no_position_gain_sets_nothing_aside_whatever_its_decimals(
    keep: float, take: float
) -> None:
    command = [_term("wheel_angle", "s"), _term("previous.z", "s", sign=-1)]
    lines = [_state("z", _term("previous.z", "keep"), _term("wheel_angle", "take"))]
    values = {"s": 0.02, "keep": keep, "take": take}
    assert _held([("z", "z_now")], lines, command, values) == ()


def test_an_integral_of_the_wheel_angle_that_nothing_reads_is_not_set_aside() -> None:
    # z' = z + wheel_angle (an integral of the wheel angle that nothing reads): the wheels return
    # but z settles where the wheels' displacement says, so it is not set aside.
    lines = [_state("z", _term("previous.z", "one"), _term("wheel_angle"))]
    assert _held([("z", "z_now")], lines, HOLD, {"g": 0.3, "one": 1.0}) == ()


# ── what is set aside: states the wheels' displacement does not move ─────────────────────────


def _unread(*fed: dict[str, Any]) -> tuple[list[tuple[str, str]], list[dict[str, Any]]]:
    return [("z", "z_now")], [_state("z", _term("previous.z", "one"), *fed)]


@pytest.mark.parametrize(
    ("fed", "set_aside"),
    [
        ([], True),
        ([_term("tilt_rate", "period")], True),
        ([_term("tilt", "gain")], True),
        ([_term("wheel_speed", "period")], False),
        ([_term("wheel_angle")], False),
        ([_term("tilt_rate", "period"), _term("wheel_speed", "period")], False),
    ],
    ids=["inert", "tilt_rate", "tilt", "wheel_speed", "wheel_angle", "rate_and_speed"],
)
def test_an_unread_state_is_set_aside_unless_the_wheels_displaced_alone_move_it(
    fed: list[dict[str, Any]], set_aside: bool
) -> None:
    memory, lines = _unread(*fed)
    values = {"g": 0.3, "one": 1.0, "gain": 0.7}
    assert bool(_held(memory, lines, HOLD, values)) is set_aside


def test_a_state_the_command_reads_is_set_aside_only_where_the_command_does_not_move_it() -> None:
    # u_prev holds the command: command = u_prev + g·wheel_angle − ... is the leak-free form
    lines = [_state("a", _term("previous.a", "one"), _term("tilt_rate", "period"))]
    command = [
        _term("previous.u", "one"),
        _term("line.a_now", "kangle"),
        _term("wheel_angle", "g"),
    ]
    memory = [("a", "a_now"), ("u", "command")]
    modes = _held(memory, lines, command, {"one": 1.0, "kangle": 0.14, "g": 0.17})
    assert len(modes) == 1
    beta, angle, command_state = modes[0]
    assert beta != 0.0 and angle != 0.0
    assert command_state == 0.0
    # a state that integrates the command into the memory the command reads is moved by the
    # command: not set aside (the loop sees its pole)
    memory = [("a", "a_now"), ("u", "command")]
    modes = _held(memory, lines, command, {"one": 1.0, "kangle": 0.14, "g": 0.0})
    assert modes == ()  # no position gain: the wheels are not restored


# ── the numbers as written ─────────────────────────────────────────────────────────────────


@pytest.mark.parametrize(
    ("first", "second"),
    [(0.75, 0.25), (0.9, 0.1), (0.6, 0.4), (0.7, 0.3), (0.3, 0.7), (0.2, 0.8), (0.1, 0.9)],
)
def test_a_state_that_carries_itself_by_two_decimals_that_sum_to_one_is_held(
    first: float, second: float
) -> None:
    lines = [_state("z", _term("previous.z", "first"), _term("previous.z", "second"))]
    assert _held([("z", "z_now")], lines, HOLD, {"g": 0.3, "first": first, "second": second}) == (
        (0.0, 1.0),
    )


@pytest.mark.parametrize(("p", "q"), [(0.3, 0.7), (0.5, 0.5), (0.1, 0.9), (0.25, 0.75)])
def test_a_sum_two_states_conserve_with_decimal_columns_is_held_once(p: float, q: float) -> None:
    # left' = p·left + p·right, right' = q·left + q·right with p + q = 1: left + right is conserved
    lines = [
        _state("left", _term("previous.left", "p"), _term("previous.right", "p")),
        _state("right", _term("previous.left", "q"), _term("previous.right", "q")),
    ]
    modes = _held(
        [("left", "left_now"), ("right", "right_now")], lines, HOLD, {"g": 0.3, "p": p, "q": q}
    )
    assert len(modes) == 1


def test_a_pole_that_is_not_one_in_decimals_is_not_held_however_near() -> None:
    lines = [_state("z", _term("previous.z", "first"), _term("previous.z", "second"))]
    values = {"g": 0.3, "first": 0.9, "second": 0.1000001}
    assert _held([("z", "z_now")], lines, HOLD, values) == ()


def test_the_numbers_are_read_as_the_decimals_they_were_written_as() -> None:
    law = _law()
    assert law.exact(0.1) == Fraction(1, 10)
    assert law.exact(1e-7) == Fraction(1, 10_000_000)
    assert law.exact(3) == 3
    assert law.exact(Decimal("0.10000000000000001")) == Fraction(10000000000000001, 10**17)
    assert law.exact(0.1) != Fraction(0.1)


def test_an_answer_keeps_each_number_as_the_text_wrote_it_and_decides_on_that() -> None:
    controller = _controller_with_split_pole("0.9", "0.1")
    answer = _answer().parse_answer(_bytes(controller))
    written = answer.controller.written
    assert written is not None
    assert written.coefficients["first"] == Fraction(9, 10)
    assert written.coefficients["second"] == Fraction(1, 10)
    assert written.coefficients["period"] == Fraction(1, 100)
    # a 17-digit decimal that is not the tenth, though it reads back as the same float
    refined = _controller_with_split_pole("0.9", "0.10000000000000001")
    again = _answer().parse_answer(_bytes(refined))
    assert again.controller.written.coefficients["second"] == Fraction(10000000000000001, 10**17)
    law = _law()
    values = {n: float(m.value) for n, m in again.controller.coefficients.items()}
    held = law.held_modes(again.controller, values, period=0.01, written=again.controller.written)
    assert held == ()  # as written the two do not sum to 1
    assert law.held_modes(answer.controller, values, period=0.01, written=answer.controller.written)


def _answer() -> Any:
    return importlib.import_module(_ANSWER)


SETTINGS: dict[str, Any] = {
    "update_rate": {"value": 100, "unit": "Hz"},
    "output_data_rate": {"value": 208, "unit": "Hz"},
    "gyro_full_scale": {"value": 1000, "unit": "deg/s"},
    "pwm_frequency": {"value": 20000, "unit": "Hz"},
    "pwm_full_scale": {"value": 400, "unit": "count"},
    "encoder_counts_per_wheel_revolution": {"value": 1322.9, "unit": "count"},
}


def _bytes(controller: str | dict[str, Any]) -> bytes:
    if isinstance(controller, dict):
        controller = json.dumps(controller)
    settings = json.dumps(SETTINGS)
    return (
        '{"form": "whole_run", "version": 3, "parameters": '
        + settings
        + ', "controller": '
        + controller
        + "}"
    ).encode()


def _controller_with_split_pole(first: str, second: str) -> str:
    """The controller as TEXT, so that each number is spelt exactly as the test writes it."""
    return (
        '{"structure": "sampled_law", "period": {"value": 0.01, "unit": "s"}, '
        '"command_limit": {"value": 0.75, "unit": "1"}, '
        '"sensor_delay": {"value": 0.0048, "unit": "s"}, '
        '"compute_delay": {"value": 0.004, "unit": "s"}, '
        '"coefficients": {"g": {"value": 0.3, "unit": "1/rad"}, '
        f'"first": {{"value": {first}, "unit": "1"}}, '
        f'"second": {{"value": {second}, "unit": "1"}}}}, '
        '"memory": [{"name": "z", "unit": "1", "next": "z_now"}], '
        '"lines": [{"name": "z_now", "unit": "1", "terms": ['
        '{"sign": 1, "coefficients": ["first"], "of": "previous.z"}, '
        '{"sign": 1, "coefficients": ["second"], "of": "previous.z"}]}, '
        '{"name": "command", "unit": "1", "terms": ['
        '{"sign": 1, "coefficients": ["g"], "of": "wheel_angle"}]}], "command": "command"}'
    )


# ── a zero where a reciprocal is taken ────────────────────────────────────────────────────


def _dividing() -> Any:
    command = [_term("wheel_angle", "g", per=("scale",))]
    return _body([], [], command)


def _refusal(call: Any) -> Any:
    """The refusal ``call`` makes: anything else it raises is a failure, never an escape."""
    try:
        call()
    except Exception as exc:  # noqa: BLE001 - what escaped is the finding
        assert isinstance(exc, _law().LawRefused), f"{type(exc).__name__} escaped: {exc}"
        return exc
    pytest.fail("the law was not refused")


def test_a_term_that_divides_by_a_zero_coefficient_is_refused_by_name_never_an_exception() -> None:
    law = _law()
    body = _dividing()
    values = {"g": 0.3, "scale": 0.0}
    assert law.zero_divisors(body, values) == ("scale",)
    assert _refusal(lambda: law.linear(body, values, period=0.01)).code == "zero_divisor"
    signals = {"wheel_angle": 1.0}
    assert (
        _refusal(lambda: law.evaluate(body, values, period=0.01, state={}, signals=signals)).code
        == "zero_divisor"
    )
    stateful = _body(
        [("z", "z_now")],
        [_state("z", _term("previous.z", "one"))],
        [_term("wheel_angle", "g", per=("scale",))],
    )
    held = {"g": 0.3, "scale": 0.0, "one": 1.0}
    assert _refusal(lambda: law.held_modes(stateful, held, period=0.01)).code == "zero_divisor"
    assert law.zero_divisors(body, {"g": 0.3, "scale": 2.0}) == ()


def test_an_answer_whose_law_divides_by_a_zero_is_a_named_fault_not_an_exception() -> None:
    controller = json.loads(_controller_with_split_pole("0.9", "0.1"))
    controller["coefficients"]["scale"] = {"value": 0.0, "unit": "1"}
    controller["lines"][-1]["terms"][0]["per"] = ["scale"]
    try:
        _answer().parse_answer(_bytes(controller))
    except TaskFormatError as exc:
        assert "zero_divisor" in str(exc)
    except Exception as exc:  # noqa: BLE001
        pytest.fail(f"{type(exc).__name__} escaped: {exc}")
    else:
        pytest.fail("the answer was read")


# ── a copy of a law with other numbers decides on its own numbers, never on the original's ──


def test_a_copy_of_a_law_with_a_changed_coefficient_gives_the_decision_of_its_own_numbers() -> None:
    parsed = _answer().parse_answer(_bytes(_controller_with_split_pole("0.9", "0.1")))
    # A law without the text it was read from, so that a changed number is read as it is.
    law = type(parsed.controller).model_validate(parsed.controller.model_dump())
    before = law.decision()
    assert (before.circle.algebraic_at_one, before.circle.set_aside) == (1, 1)
    coefficients = dict(law.coefficients)
    coefficients["first"] = type(coefficients["first"]).model_validate({"value": 0.8, "unit": "1"})
    copy = law.model_copy(update={"coefficients": coefficients})
    after = copy.decision()
    assert after is not before
    assert (after.circle.algebraic_at_one, after.circle.set_aside) == (0, 0)
    assert law.decision() is before
