"""A general sampled linear law is stated as the design states it, and held before it is used.

The law below is a recorded design's: a leaky tilt estimate, the previous encoder angle and the
previous command as memory, a command that is a sum of coefficient-weighted terms. The matrices
it gives are checked against the ones its own design analysis built by hand (the controller as a
state-space system over the gyro rate and the encoder angle), written here apart from the module.
Each refusal fires on its own mutation of the one law, by name: a term that is not one variable
is ``nonlinear``, a signal outside the closed list is ``out_of_scope``, and neither is a fail.
"""

from __future__ import annotations

import copy
import importlib
import json
from pathlib import Path
from typing import Any

import pytest

from physgate.evaluation.per_role.exceptions import TaskFormatError

_FIXTURE = Path(__file__).resolve().parent / "recorded_law" / "law.json"
_LAW = "physgate.evaluation.whole.law"
_ANSWER = "physgate.evaluation.whole.answer"

K_PHI, K_THETA, K_W, K_RATE, K_U, LEAK = (
    -0.0054505,
    -1.03529,
    -0.038326,
    -0.0625146,
    -0.346975,
    0.999,
)
T = 0.01

COEFFICIENTS: dict[str, dict[str, Any]] = {
    "k_phi": {"value": K_PHI, "unit": "1/rad"},
    "k_theta": {"value": K_THETA, "unit": "1/rad"},
    "k_w": {"value": K_W, "unit": "s/rad"},
    "k_rate": {"value": K_RATE, "unit": "s/rad"},
    "k_u": {"value": K_U, "unit": "1"},
    "leak": {"value": LEAK, "unit": "1"},
}
SETTINGS_V3: dict[str, Any] = {
    "update_rate": {"value": 100, "unit": "Hz"},
    "output_data_rate": {"value": 208, "unit": "Hz"},
    "gyro_full_scale": {"value": 1000, "unit": "deg/s"},
    "pwm_frequency": {"value": 20000, "unit": "Hz"},
    "pwm_full_scale": {"value": 400, "unit": "count"},
    "encoder_counts_per_wheel_revolution": {"value": 1322.9, "unit": "count"},
}
SETTINGS_V2: dict[str, Any] = {
    ("gyro_output_data_rate" if name == "output_data_rate" else name): value
    for name, value in SETTINGS_V3.items()
}


def _law() -> Any:
    return importlib.import_module(_LAW)


def _answer() -> Any:
    return importlib.import_module(_ANSWER)


def _file() -> dict[str, Any]:
    document: dict[str, Any] = json.loads(_FIXTURE.read_text())
    return document


def _controller() -> dict[str, Any]:
    """The recorded law as a controller of an answer: its body, its coefficients, its timing."""
    body = {key: copy.deepcopy(_file()[key]) for key in ("memory", "lines", "command")}
    return {
        "structure": "sampled_law",
        **body,
        "coefficients": copy.deepcopy(COEFFICIENTS),
        "period": {"value": T, "unit": "s"},
        "command_limit": {"value": 0.9425, "unit": "1"},
        "sensor_delay": {"value": 1 / 208, "unit": "s"},
        "compute_delay": {"value": 0.004, "unit": "s"},
    }


def _bytes(controller: dict[str, Any], *, version: int = 3, settings: Any = None) -> bytes:
    answer: dict[str, Any] = {
        "form": "whole_run",
        "version": version,
        "controller": controller,
        "parameters": SETTINGS_V3 if settings is None else settings,
        "files": [],
    }
    return json.dumps(answer).encode()


def _parse(controller: dict[str, Any]) -> Any:
    return _answer().parse_answer(_bytes(controller))


def test_the_recorded_law_is_a_version_3_answer_and_keeps_every_number_as_written() -> None:
    answer = _parse(_controller())
    assert answer.version == 3
    law = answer.controller
    assert law.structure == "sampled_law"
    assert {n: m.value for n, m in law.coefficients.items()} == {
        n: c["value"] for n, c in COEFFICIENTS.items()
    }
    assert answer.parameters.output_data_rate.value == 208


def test_the_matrices_are_the_ones_the_design_s_own_analysis_built_by_hand() -> None:
    # The design's analysis wrote the controller over [gyro rate, encoder angle] with states
    # [theta_hat, p_prev, u_prev] (each the value after the previous update):
    #   u_k = -(k_phi (p + th) + k_th th + k_w ((p - p_prev)/T + g) + k_rate g + k_u u_prev),
    #   th = LEAK th_prev + T g.
    c_th = K_PHI + K_THETA
    hand_d = [-(c_th * T + K_W + K_RATE), -(K_PHI + K_W / T)]
    hand_c = [-(c_th * LEAK), K_W / T, -K_U]
    law = _law()
    a, b, c, d = law.linear(
        law.Body.model_validate_json(json.dumps(_controller_body())),
        {n: v["value"] for n, v in COEFFICIENTS.items()},
        period=T,
    )
    # Inputs are (tilt, tilt_rate, wheel_angle, wheel_speed); this law reads the middle two.
    assert [row[1] for row in b] == pytest.approx([T, 0.0, hand_d[0]])
    assert d[1] == pytest.approx(hand_d[0])
    assert d[2] == pytest.approx(hand_d[1])
    assert c == pytest.approx(tuple(hand_c))
    assert a[0] == pytest.approx((LEAK, 0.0, 0.0))
    assert a[1] == (0.0, 0.0, 0.0)
    assert a[2] == pytest.approx(tuple(hand_c))
    assert [row[2] for row in b] == pytest.approx([0.0, 1.0, hand_d[1]])
    assert d[0] == 0.0
    assert d[3] == 0.0


def _controller_body() -> dict[str, Any]:
    return {key: _file()[key] for key in ("memory", "lines", "command")}


def _refused(mutate: Any, *words: str) -> None:
    controller = _controller()
    mutate(controller)
    with pytest.raises(TaskFormatError) as caught:
        _parse(controller)
    for word in words:
        assert word in str(caught.value), str(caught.value)


def _term(controller: dict[str, Any], line: str, at: int = 0) -> dict[str, Any]:
    found = next(x for x in controller["lines"] if x["name"] == line)
    term: dict[str, Any] = found["terms"][at]
    return term


def test_a_term_whose_units_do_not_balance_is_refused_and_says_which_line() -> None:
    _refused(
        lambda c: c["coefficients"]["k_phi"].update(unit="1/m"), "units_do_not_balance", "command"
    )


def test_a_wrong_scale_is_caught_by_units_where_a_wrong_sign_is_not() -> None:
    # k_w taken per metre instead of per radian: the scale r is missing, units say so.
    _refused(lambda c: c["coefficients"]["k_w"].update(unit="s/m"), "units_do_not_balance")
    controller = _controller()
    _term(controller, "command", 2)["sign"] = 1  # a flipped sign balances
    assert _parse(controller).controller.structure == "sampled_law"


def test_a_line_unit_that_the_terms_do_not_make_is_refused() -> None:
    _refused(
        lambda c: next(x for x in c["lines"] if x["name"] == "w_hat").update(unit="rad"),
        "units_do_not_balance",
        "w_hat",
    )


def test_a_command_that_is_not_dimensionless_is_refused() -> None:
    _refused(
        lambda c: c.update(command="phi_hat"),
        "units_do_not_balance",
    )


def test_a_command_that_is_no_line_is_refused() -> None:
    _refused(lambda c: c.update(command="nothing"), "malformed")


@pytest.mark.parametrize("of", ["tilt_rate*wheel_angle", "abs(tilt_rate)", "tilt_rate+wheel_angle"])
def test_a_term_that_is_not_one_variable_is_refused_as_nonlinear(of: str) -> None:
    _refused(lambda c: _term(c, "command", 3).update(of=of), "nonlinear")


@pytest.mark.parametrize("key", ["times", "function", "when"])
def test_a_term_with_more_than_a_sign_a_number_coefficients_and_one_variable_is_nonlinear(
    key: str,
) -> None:
    _refused(lambda c: _term(c, "command", 3).update({key: "wheel_angle"}), "nonlinear")


def test_a_signal_outside_the_closed_list_is_out_of_scope_and_named() -> None:
    _refused(
        lambda c: _term(c, "command", 3).update(of="accelerometer_tilt"),
        "out_of_scope",
        "accelerometer_tilt",
    )


def test_a_coefficient_the_law_does_not_declare_is_refused() -> None:
    _refused(
        lambda c: _term(c, "command", 0).update(coefficients=["k_phi_typo"]),
        "malformed",
        "k_phi_typo",
    )


def test_a_memory_state_or_an_earlier_line_that_does_not_exist_is_refused() -> None:
    _refused(lambda c: _term(c, "theta_now", 0).update(of="previous.nothing"), "malformed")
    _refused(lambda c: _term(c, "theta_now", 0).update(of="line.command"), "malformed")


def test_a_line_read_before_it_is_formed_is_refused() -> None:
    def swap(c: dict[str, Any]) -> None:
        c["lines"][0], c["lines"][2] = c["lines"][2], c["lines"][0]

    _refused(swap, "malformed")


def test_a_memory_state_that_takes_its_value_from_no_line_is_refused() -> None:
    _refused(lambda c: c["memory"][0].update(next="nothing"), "malformed")


def test_a_memory_state_in_another_unit_than_its_line_is_refused() -> None:
    _refused(lambda c: c["memory"][0].update(unit="rad/s"), "units_do_not_balance")


def test_an_applied_state_is_the_command_and_nothing_else() -> None:
    _refused(lambda c: c["memory"][0].update(applied=True), "malformed")


def test_a_name_used_twice_or_taken_from_a_signal_is_refused() -> None:
    _refused(lambda c: c["memory"][1].update(name="theta_hat"), "named twice")
    _refused(lambda c: c["memory"][1].update(name="tilt_rate"), "named twice")


def test_the_period_is_the_loop_s_own_and_never_a_coefficient() -> None:
    _refused(lambda c: c["coefficients"].update(period={"value": 0.01, "unit": "s"}), "period")


def test_a_coefficient_past_its_bound_or_in_no_unit_is_refused() -> None:
    _refused(lambda c: c["coefficients"]["k_phi"].update(value=2e6), "within")
    _refused(lambda c: c["coefficients"]["k_phi"].update(unit="1//rad"), "unit")


def test_a_number_that_is_zero_is_refused_since_a_term_of_zero_is_no_term() -> None:
    _refused(lambda c: _term(c, "command", 3).update(number=0), "number")


def test_a_law_past_its_sizes_is_refused_before_any_work() -> None:
    def many_states(c: dict[str, Any]) -> None:
        c["memory"] = [{"name": f"s{i}", "unit": "rad", "next": "p_now"} for i in range(9)]

    _refused(many_states, "at most 8")

    def many_terms(c: dict[str, Any]) -> None:
        line = next(x for x in c["lines"] if x["name"] == "command")
        line["terms"] = line["terms"] * 3

    _refused(many_terms, "at most 16")


def test_a_version_2_answer_with_the_old_name_parses_as_before() -> None:
    controller = {
        "structure": "state_feedback",
        "period": {"value": 0.01, "unit": "s"},
        "command_limit": {"value": 0.75, "unit": "1"},
        "sensor_delay": {"value": 0.0048, "unit": "s"},
        "compute_delay": {"value": 0.002, "unit": "s"},
        "angle_gain": {"value": 1.6643, "unit": "1/rad"},
        "rate_gain": {"value": 0.191, "unit": "s/rad"},
        "distance_gain": {"value": 0.2853, "unit": "1/m"},
        "speed_gain": {"value": 1.3421, "unit": "s/m"},
    }
    answer = _answer().parse_answer(_bytes(controller, version=2, settings=SETTINGS_V2))
    assert answer.version == 2
    assert answer.parameters.gyro_output_data_rate.value == 208


@pytest.mark.parametrize(
    ("version", "settings"),
    [(2, SETTINGS_V3), (3, SETTINGS_V2)],
    ids=["v2-new-name", "v3-old-name"],
)
def test_each_version_is_read_by_its_own_names_only(version: int, settings: Any) -> None:
    controller = {
        "structure": "state_feedback",
        "period": {"value": 0.01, "unit": "s"},
        "command_limit": {"value": 0.75, "unit": "1"},
        "sensor_delay": {"value": 0.0048, "unit": "s"},
        "compute_delay": {"value": 0.002, "unit": "s"},
        "angle_gain": {"value": 1.6643, "unit": "1/rad"},
        "rate_gain": {"value": 0.191, "unit": "s/rad"},
        "distance_gain": {"value": 0.2853, "unit": "1/m"},
        "speed_gain": {"value": 1.3421, "unit": "s/m"},
    }
    with pytest.raises(TaskFormatError):
        _answer().parse_answer(_bytes(controller, version=version, settings=settings))


def test_a_version_2_answer_cannot_state_a_sampled_law() -> None:
    with pytest.raises(TaskFormatError):
        _answer().parse_answer(_bytes(_controller(), version=2, settings=SETTINGS_V2))


def test_the_law_file_is_read_by_name_and_the_recorded_one_holds() -> None:
    parsed = _law().parse_file(_FIXTURE.read_bytes())
    assert parsed.command == "command"
    assert parsed.graph_names() == (
        "computation_delay_bound",
        "duty_cycle",
        "k_phi",
        "k_rate",
        "k_theta",
        "k_u",
        "k_w",
        "leak",
        "output_data_rate",
        "update_lateness_bound",
        "update_rate",
    )


@pytest.mark.parametrize(
    ("mutate", "code"),
    [
        (lambda d: d["lines"][4]["terms"][0].update(of="abs(line.phi_hat)"), "nonlinear"),
        (lambda d: d["lines"][4]["terms"][0].update(of="accelerometer_tilt"), "out_of_scope"),
        (lambda d: d.update(form="other"), "malformed"),
        (lambda d: d.update(vectors=[]), "malformed"),
        (lambda d: d["coefficients"].update(period="update_rate"), "malformed"),
    ],
)
def test_a_law_file_is_refused_by_name(mutate: Any, code: str) -> None:
    document = _file()
    mutate(document)
    with pytest.raises(_law().LawRefused) as caught:
        _law().parse_file(json.dumps(document).encode())
    assert caught.value.code == code


def test_a_law_file_that_is_not_json_or_is_too_large_is_refused() -> None:
    law = _law()
    with pytest.raises(law.LawRefused) as caught:
        law.parse_file(b"{")
    assert caught.value.code == "malformed"
    with pytest.raises(law.LawRefused) as big:
        law.parse_file(b" " * (law.MAX_FILE_BYTES + 1))
    assert big.value.code == "malformed"


@pytest.mark.parametrize(
    ("unit", "expected"),
    [
        ("Hz", (("s", -1),)),
        ("1/rad", (("rad", -1),)),
        ("count*s/deg", (("count", 1), ("deg", -1), ("s", 1))),
        ("m/s**2", (("m", 1), ("s", -2))),
        ("1", ()),
        ("s*Hz", ()),
        ("1/(rad*s)", (("rad", -1), ("s", -1))),
    ],
)
def test_a_unit_is_its_symbols_with_their_powers(unit: str, expected: Any) -> None:
    assert _law().dimension(unit) == expected


@pytest.mark.parametrize("unit", ["", "//", "rad rad", "1/", "m**x", "*s", "a" * 65])
def test_a_string_that_is_no_unit_is_refused(unit: str) -> None:
    with pytest.raises(_law().LawRefused):
        _law().dimension(unit)


def test_a_source_is_exactly_one_of_a_name_a_reciprocal_and_a_sum() -> None:
    sources: tuple[dict[str, Any], ...] = (
        {"quantity": "a", "reciprocal_of": "b"},
        {},
        {"sum_of": []},
    )
    for source in sources:
        document = _file()
        document["period"] = source
        with pytest.raises(_law().LawRefused) as caught:
            _law().parse_file(json.dumps(document).encode())
        assert caught.value.code == "malformed"


def test_a_version_3_native_controller_needs_its_scales_and_a_file_is_named_once() -> None:
    native = {
        "structure": "native_incremental_rising_offset",
        "sensor_delay": {"value": 0.0048, "unit": "s"},
        "compute_delay": {"value": 0.002, "unit": "s"},
        "update_time": {"value": 10, "unit": "ms"},
        "motor_speed_limit": {"value": 300, "unit": "count"},
        "angle_rate_ratio": {"value": 140, "unit": "ms"},
        "angle_response": {"value": 11, "unit": "1"},
        "distance_response": {"value": 73, "unit": "1"},
        "speed_response": {"value": 3300, "unit": "1"},
        "response_divisor": {"value": 100, "unit": "1"},
        "gear_ratio_coefficient": {"value": 111, "unit": "1"},
        "gyro_divisor": {"value": 29, "unit": "count*s/deg"},
        "angle_decay_numerator": {"value": 999, "unit": "1"},
        "angle_decay_denominator": {"value": 1000, "unit": "1"},
    }
    with pytest.raises(TaskFormatError) as caught:
        _answer().parse_answer(_bytes(native))
    assert "sensitivity" in str(caught.value)
    settings = {**SETTINGS_V3, "gyro_sensitivity": {"value": 28.571, "unit": "count*s/deg"}}
    assert _answer().parse_answer(_bytes(native, settings=settings)).version == 3
    over = {**settings, "pwm_full_scale": {"value": 250, "unit": "count"}}
    with pytest.raises(TaskFormatError) as past:
        _answer().parse_answer(_bytes(native, settings=over))
    assert "past the PWM full scale" in str(past.value)
    document = json.loads(_bytes(native, settings=settings))
    document["files"] = ["a/x.py", "A/X.py"]
    with pytest.raises(TaskFormatError) as twice:
        _answer().parse_answer(json.dumps(document).encode())
    assert "twice" in str(twice.value)


# ── the vectors must demand something of the law (law.verify) ───────────────────────────────


def _two_term_law(extra: list[dict[str, Any]] | None = None) -> Any:
    """``command = a·tilt_rate + b·wheel_angle`` (and ``extra`` terms): no memory."""
    terms = [
        {"sign": 1, "coefficients": ["a"], "of": "tilt_rate"},
        {"sign": 1, "coefficients": ["b"], "of": "wheel_angle"},
        *(extra or []),
    ]
    return _law().Body.model_validate_json(
        json.dumps(
            {
                "memory": [],
                "lines": [{"name": "command", "unit": "1", "terms": terms}],
                "command": "command",
            }
        )
    )


def _rows_of(count: int, angle_step: float, values: dict[str, float], **more: float) -> Any:
    """One vector of ``count`` rows whose honest duty is ``a·rate + b·angle`` at ``values``."""
    rows = []
    for n in range(1, count + 1):
        rate, angle = 0.1 * n, angle_step * n
        duty = (
            values["a"] * rate
            + values["b"] * angle
            + sum(values.get(k, 0.0) * v * n for k, v in more.items())
        )
        rows.append(
            {
                "tilt_rate": rate,
                "wheel_angle": angle,
                **{k: v * n for k, v in more.items()},
                "duty": duty,
                "counts": round(duty * 400),
            }
        )
    return (_law().Vector.model_validate_json(json.dumps({"name": "ramp", "rows": rows})),)


def _verify(body: Any, values: dict[str, float], vectors: Any) -> Any:
    return _law().verify(body, values, vectors, period=0.01, limit=0.9425, full_scale=400.0)


VALUES = {"a": 0.5, "b": 0.4}


def test_ten_rows_that_exercise_and_pin_a_law_are_enough_and_nine_are_not() -> None:
    body = _two_term_law()
    verified = _verify(body, VALUES, _rows_of(10, 0.01, VALUES))
    assert verified.rows == 10
    assert verified.signals == ("tilt_rate", "wheel_angle")
    assert _law().MIN_ROWS == 10
    with pytest.raises(_law().LawRefused) as caught:
        _verify(body, VALUES, _rows_of(9, 0.01, VALUES))
    assert caught.value.code == "vectors_too_few"
    assert "9 rows" in caught.value.detail


@pytest.mark.parametrize(
    ("angle_step", "pinned"),
    [
        # b·angle at the last row is 0.4·10·step; 2 % of it must be above the duty tolerance 1e-5.
        (1.5e-4, True),
        (1.0e-4, False),
    ],
)
def test_a_coefficient_is_pinned_when_two_percent_of_it_moves_a_row_past_the_tolerance(
    angle_step: float, pinned: bool
) -> None:
    body = _two_term_law()
    vectors = _rows_of(10, angle_step, VALUES)
    if pinned:
        assert _verify(body, VALUES, vectors).rows == 10
        return
    with pytest.raises(_law().LawRefused) as caught:
        _verify(body, VALUES, vectors)
    assert caught.value.code == "vectors_do_not_pin"
    assert "the coefficient 'b'" in caught.value.detail
    assert "term 2 of line 'command'" in caught.value.detail
    assert "the coefficient 'a'" not in caught.value.detail


def test_a_term_on_a_signal_no_row_sets_is_not_exercised_and_the_signal_is_named() -> None:
    extra = [{"sign": 1, "coefficients": ["c"], "of": "wheel_speed"}]
    body = _two_term_law(extra)
    with pytest.raises(_law().LawRefused) as caught:
        _verify(body, {**VALUES, "c": 0.3}, _rows_of(10, 0.01, VALUES))
    assert caught.value.code == "vectors_do_not_exercise"
    assert "wheel_speed" in caught.value.detail


def test_a_term_whose_coefficient_is_zero_is_exercised_by_its_signal_and_not_moved() -> None:
    extra = [{"sign": 1, "coefficients": ["c"], "of": "wheel_speed"}]
    values = {**VALUES, "c": 0.0}
    vectors = _rows_of(10, 0.01, values, wheel_speed=0.05)
    assert _verify(_two_term_law(extra), values, vectors).signals == (
        "tilt_rate",
        "wheel_angle",
        "wheel_speed",
    )


def test_a_memory_state_no_term_reads_is_named() -> None:
    body = _law().Body.model_validate_json(
        json.dumps(
            {
                "memory": [{"name": "dead", "unit": "1", "next": "dead_now"}],
                "lines": [
                    {
                        "name": "dead_now",
                        "unit": "1",
                        "terms": [{"sign": 1, "coefficients": ["a"], "of": "tilt_rate"}],
                    },
                    {
                        "name": "command",
                        "unit": "1",
                        "terms": [
                            {"sign": 1, "coefficients": ["a"], "of": "tilt_rate"},
                            {"sign": 1, "coefficients": ["b"], "of": "wheel_angle"},
                        ],
                    },
                ],
                "command": "command",
            }
        )
    )
    with pytest.raises(_law().LawRefused) as caught:
        _verify(body, VALUES, _rows_of(10, 0.01, VALUES))
    assert caught.value.code == "vectors_do_not_exercise"
    assert "the memory state 'dead' is read by no term" in caught.value.detail


@pytest.mark.parametrize(
    ("duty", "expected"),
    [
        (0.00125, 1),  # half a count rounds away from 0
        (-0.00125, -1),
        (0.001, 0),
        (-0.001, 0),
        (2.0, 360),  # held to the limit first: 0.9 of 400
        (-2.0, -360),
    ],
)
def test_the_command_is_held_to_its_limit_then_rounded_to_whole_counts_half_away_from_zero(
    duty: float, expected: int
) -> None:
    assert _law().counts(duty, 0.9, 400.0) == expected


# ── the modes a law holds at exactly 1, decided from its lines ──────────────────────────────


def _held_body(
    memory: list[tuple[str, str]], lines: list[dict[str, Any]], command: list[Any]
) -> Any:
    return _law().Body.model_validate_json(
        json.dumps(
            {
                "memory": [{"name": n, "unit": "1", "next": nxt} for n, nxt in memory],
                "lines": [*lines, {"name": "command", "unit": "1", "terms": command}],
                "command": "command",
            }
        )
    )


def _carry(name: str, coefficient: str) -> dict[str, Any]:
    """``name_now = coefficient · previous.name``: a state that carries itself and nothing else."""
    return {
        "name": f"{name}_now",
        "unit": "1",
        "terms": [{"sign": 1, "coefficients": [coefficient], "of": f"previous.{name}"}],
    }


GAINS = [{"sign": 1, "coefficients": ["g"], "of": "wheel_angle"}]


def test_a_state_that_carries_itself_exactly_is_held_and_one_that_almost_does_is_not() -> None:
    body = _held_body([("z", "z_now")], [_carry("z", "pole")], GAINS)
    held = _law().held_modes(body, {"pole": 1.0, "g": 0.3}, period=0.01)
    assert held == ((0.0, 1.0),)
    for pole in (1.0 + 1e-12, 1.0 - 1e-12, 1.001, 0.999):
        assert _law().held_modes(body, {"pole": pole, "g": 0.3}, period=0.01) == ()


def test_a_large_coefficient_elsewhere_does_not_widen_what_is_held() -> None:
    lines = [
        _carry("z", "pole"),
        {
            "name": "loud_now",
            "unit": "1",
            "terms": [{"sign": 1, "coefficients": ["big"], "of": "tilt"}],
        },
    ]
    body = _held_body([("z", "z_now"), ("q", "loud_now")], lines, GAINS)
    values = {"pole": 1.0 + 1e-6, "g": 0.3, "big": 1e6}
    assert _law().held_modes(body, values, period=0.01) == ()
    assert len(_law().held_modes(body, {**values, "pole": 1.0}, period=0.01)) == 1


def test_a_command_fed_integrator_is_held_only_when_the_command_does_not_read_it() -> None:
    lines = [
        {
            "name": "total_now",
            "unit": "1",
            "terms": [
                {"sign": 1, "of": "previous.total"},
                {"sign": 1, "of": "wheel_angle"},
            ],
        }
    ]
    reads = [*GAINS, {"sign": 1, "coefficients": ["ki"], "of": "previous.total"}]
    for ki in (1e-6, -1e-6, 1e-12):
        body = _held_body([("total", "total_now")], lines, reads)
        assert _law().held_modes(body, {"g": 0.3, "ki": ki}, period=0.01) == ()


def test_a_sum_the_updates_conserve_is_held_once_not_per_state() -> None:
    lines = [
        {
            "name": f"{name}_now",
            "unit": "1",
            "terms": [
                {"sign": 1, "coefficients": ["half"], "of": "previous.left"},
                {"sign": 1, "coefficients": ["half"], "of": "previous.right"},
            ],
        }
        for name in ("left", "right")
    ]
    body = _held_body([("left", "left_now"), ("right", "right_now")], lines, GAINS)
    (mode,) = _law().held_modes(body, {"half": 0.5, "g": 0.3}, period=0.01)
    assert mode == (0.0, 1.0, 1.0)


def test_the_travel_alone_is_never_returned_and_a_law_with_no_memory_holds_nothing() -> None:
    # No term reads the wheel angle, so the plant's travel is a mode at 1 with no memory in it.
    reads = [{"sign": 1, "coefficients": ["g"], "of": "tilt"}]
    body = _held_body([("z", "z_now")], [_carry("z", "pole")], reads)
    assert _law().held_modes(body, {"pole": 1.0, "g": 0.3}, period=0.01) == ((0.0, 1.0),)
    stateless = _held_body([], [], reads)
    assert _law().held_modes(stateless, {"g": 0.3}, period=0.01) == ()
    only = _held_body([("z", "z_now")], [_carry("z", "pole")], reads)
    assert _law().held_modes(only, {"pole": 0.5, "g": 0.3}, period=0.01) == ()


def test_the_velocity_form_s_offset_has_the_wheel_angle_in_it() -> None:
    # angle[k] = angle[k-1] + T·rate; command = angle_gain·angle[k] + wheel_gain·wheel_angle:
    # (wheel angle β, angle m) with wheel_gain·β + angle_gain·m = 0 is held.
    lines = [
        {
            "name": "angle_now",
            "unit": "1",
            "terms": [
                {"sign": 1, "of": "previous.angle"},
                {"sign": 1, "coefficients": ["period"], "of": "tilt_rate"},
            ],
        }
    ]
    command = [
        {"sign": 1, "coefficients": ["angle_gain"], "of": "line.angle_now"},
        {"sign": 1, "coefficients": ["wheel_gain"], "of": "wheel_angle"},
    ]
    body = _held_body([("angle", "angle_now")], lines, command)
    (mode,) = _law().held_modes(body, {"angle_gain": 2.0, "wheel_gain": 0.5}, period=0.01)
    beta, memory = mode
    assert 0.5 * beta + 2.0 * memory == pytest.approx(0.0, abs=1e-15)
    assert beta != 0.0 and memory != 0.0


def test_a_variable_with_a_trailing_newline_is_not_one_variable() -> None:
    document = _file()
    next(x for x in document["lines"] if x["name"] == "command")["terms"][0]["of"] = "tilt\n"
    with pytest.raises(_law().LawRefused) as caught:
        _law().parse_file(json.dumps(document).encode())
    assert caught.value.code == "nonlinear"
