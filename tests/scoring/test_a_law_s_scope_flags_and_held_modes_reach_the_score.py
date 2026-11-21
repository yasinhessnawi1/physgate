"""What a scored law's record says: its scope, its flags, the modes set aside, the signals it reads.

A term that cannot affect the command (zero weight, or in a line nothing reads) is no ground for a
scope refusal; scope is decided on what the law computes. A law refused for scope has every other
check run on it first, and any other fault is the ordinary fail, so a scope refusal never covers
an invalid or failing answer. The record lists each mode set aside (its memory states, what feeds
them, whether the command reads them) with the plain note that a held state can grow in the
firmware, the signals the law reads, and the flags on the compute delay, on the record and on every
row.
"""

from __future__ import annotations

import copy
import importlib
import json
from pathlib import Path
from typing import Any

import pytest

helpers: Any = importlib.import_module("test_a_sampled_law_is_scored_as_the_named_structures_are")


def _command(controller: dict[str, Any]) -> dict[str, Any]:
    line: dict[str, Any] = next(x for x in controller["lines"] if x["name"] == "command")
    return line


def _unstable(controller: dict[str, Any]) -> dict[str, Any]:
    out = copy.deepcopy(controller)
    out["coefficients"]["k_theta"]["value"] = 1.0  # the wrong sign: it falls over
    return out


def _scratch_line(of: str, *coefficients: str, name: str = "scratch") -> dict[str, Any]:
    return {
        "name": name,
        "unit": "rad",
        "terms": [{"sign": 1, "number": 2, "coefficients": list(coefficients), "of": of}],
    }


def _record(tmp_path: Path, controller: dict[str, Any], **document: Any) -> dict[str, Any]:
    """The scorer's record of an answer holding ``controller``, each in a directory of its own."""
    body = json.loads(helpers._answer(controller, 3))
    body.update(document)
    directory = tmp_path / f"answer_{len(list(tmp_path.iterdir()))}"
    directory.mkdir()
    try:
        return helpers._record_of(directory, body)  # type: ignore[no-any-return]
    except Exception as exc:  # noqa: BLE001 - an exception out of the scorer is the finding
        pytest.fail(f"{type(exc).__name__} escaped the scorer: {exc}")


# ── a scope refusal speaks only for an otherwise valid and otherwise scorable answer ─────────

DEAD = [
    pytest.param(lambda: _scratch_line("accelerometer_tilt"), id="out_of_scope_line"),
    pytest.param(lambda: _scratch_line("tilt_rate*wheel_angle"), id="nonlinear_line"),
    pytest.param(lambda: _scratch_line("tilt*tilt_rate", "k_u"), id="a_dead_tilt_times_rate"),
]


@pytest.mark.parametrize("dead", DEAD)
def test_an_unstable_law_with_one_dead_out_of_scope_term_is_a_fail_not_unscored(
    tmp_path: Path, dead: Any
) -> None:
    controller = _unstable(helpers._recorded_controller())
    controller["lines"].insert(0, dead())
    record = _record(tmp_path, controller)
    assert record["outcome"] == "fail", record.get("refusal")
    assert "refusal" not in record
    rows = {r["name"]: r for r in record["specs"]}
    assert rows["pm"]["verdict"] == "fail"
    assert "unstable" in rows["pm"]["reason"]


@pytest.mark.parametrize("dead", DEAD)
def test_a_law_with_an_undeclared_coefficient_and_one_dead_term_is_a_fail_not_unscored(
    tmp_path: Path, dead: Any
) -> None:
    controller = helpers._recorded_controller()
    controller["lines"].insert(0, dead())
    _command(controller)["terms"][1]["coefficients"] = ["k_theta_typo"]
    record = _record(tmp_path, controller)
    assert record["outcome"] == "fail"
    assert record["answer_valid"] is False
    assert "k_theta_typo" in record["reason"]
    assert "refusal" not in record


@pytest.mark.parametrize("dead", DEAD)
def test_a_law_whose_units_do_not_balance_and_one_dead_term_is_a_fail_not_unscored(
    tmp_path: Path, dead: Any
) -> None:
    controller = helpers._recorded_controller()
    controller["lines"].insert(0, dead())
    controller["coefficients"]["k_phi"]["unit"] = "1/m"
    record = _record(tmp_path, controller)
    assert record["outcome"] == "fail"
    assert "units_do_not_balance" in record["reason"]
    assert "refusal" not in record


def test_a_term_of_zero_weight_that_is_out_of_scope_is_taken_out_and_the_law_judged(
    tmp_path: Path,
) -> None:
    controller = helpers._recorded_controller()
    controller["coefficients"]["k_zero"] = helpers._m(0.0, "1/rad")
    _command(controller)["terms"].append(
        {"sign": 1, "coefficients": ["k_zero"], "of": "accelerometer_tilt"}
    )
    record = _record(tmp_path, controller)
    rows = {r["name"]: r for r in record["specs"]}
    assert rows["pm"]["verdict"] == "pass"
    assert record["set_aside"] == [
        {
            "line": "command",
            "term": 7,
            "code": "out_of_scope",
            "detail": record["set_aside"][0]["detail"],
        }
    ]
    assert "accelerometer_tilt" in record["set_aside"][0]["detail"]
    # and unstable it is a fail, whatever it carries
    again = _record(tmp_path, _unstable(controller))
    assert again["outcome"] == "fail"


def test_a_line_nothing_reads_is_taken_out_and_the_law_is_scored_as_it_would_be_without_it(
    tmp_path: Path,
) -> None:
    plain = _record(tmp_path, helpers._recorded_controller())
    controller = helpers._recorded_controller()
    controller["lines"].insert(0, _scratch_line("accelerometer_tilt"))
    carried = _record(tmp_path, controller)
    assert carried["set_aside"][0]["line"] == "scratch"
    assert carried["specs"] == plain["specs"]
    assert carried["outcome"] == plain["outcome"]
    assert plain["set_aside"] == []


def test_a_live_nonlinear_term_and_nothing_else_wrong_is_unscored_by_name(tmp_path: Path) -> None:
    controller = helpers._recorded_controller()
    _command(controller)["terms"][0]["of"] = "line.phi_hat*tilt_rate"
    record = _record(tmp_path, controller)
    assert record["refusal"]["name"] == "nonlinear"
    assert record["outcome"] == "unscored"
    assert record["specs"] == []


def _undeclared(controller: dict[str, Any]) -> None:
    _command(controller)["terms"][1]["coefficients"] = ["nope"]


def _unbalanced(controller: dict[str, Any]) -> None:
    controller["coefficients"]["k_phi"]["unit"] = "1/m"


def _divides_by_zero(controller: dict[str, Any]) -> None:
    controller["coefficients"]["k_u"]["value"] = 0.0
    _command(controller)["terms"][1]["per"] = ["k_u"]


@pytest.mark.parametrize(
    ("fault", "word"),
    [
        (_undeclared, "nope"),
        (_unbalanced, "units_do_not_balance"),
        (_divides_by_zero, "zero_divisor"),
    ],
)
def test_a_live_term_out_of_scope_with_another_fault_in_the_law_is_a_fail(
    tmp_path: Path, fault: Any, word: str
) -> None:
    controller = helpers._recorded_controller()
    _command(controller)["terms"][0]["of"] = "accelerometer_tilt"
    fault(controller)
    record = _record(tmp_path, controller)
    assert record["outcome"] == "fail"
    assert record["answer_valid"] is False
    assert "refusal" not in record
    assert word in record["reason"]


def test_an_analysed_law_out_of_scope_with_another_fault_is_a_fail_too(tmp_path: Path) -> None:
    analysed = helpers._recorded_controller()
    _command(analysed)["terms"][0]["of"] = "accelerometer_tilt"
    _command(analysed)["terms"][1]["coefficients"] = ["nope"]
    record = _record(tmp_path, helpers._recorded_controller(), analysed_controller=analysed)
    assert record["outcome"] == "fail"
    assert record["answer_valid"] is False
    assert "nope" in record["reason"]


def test_a_law_that_divides_by_a_zero_is_a_named_fault_never_an_exception(tmp_path: Path) -> None:
    controller = helpers._recorded_controller()
    controller["coefficients"]["scale"] = helpers._m(0.0, "1")
    _command(controller)["terms"][1]["per"] = ["scale"]
    record = _record(tmp_path, controller)
    assert record["outcome"] == "fail"
    assert "zero_divisor" in record["reason"]


# ── every way an answer ends unscored ──────────────────────────────────────────────────────


def test_a_law_with_a_live_term_out_of_scope_and_a_passing_primary_is_unscored_only_on_c19(
    tmp_path: Path,
) -> None:
    analysed = helpers._recorded_controller()
    _command(analysed)["terms"][0]["of"] = "accelerometer_tilt"
    record = _record(tmp_path, helpers._recorded_controller(), analysed_controller=analysed)
    rows = {r["name"]: r for r in record["specs"]}
    assert rows["pm"]["verdict"] == "pass"
    assert rows["same"]["verdict"] == "unscored"
    assert record["outcome"] == "unscored"


# ── the record: signals, modes set aside, flags ────────────────────────────────────────────


def test_the_record_names_the_signals_the_law_reads(tmp_path: Path) -> None:
    record = _record(tmp_path, helpers._recorded_controller())
    assert record["law_signals"] == ["tilt_rate", "wheel_angle", "wheel_reference"]


def _stable_with(extra: list[dict[str, Any]], terms: list[dict[str, Any]]) -> dict[str, Any]:
    """The good gains with the wheel-angle gain, plus an unread state ``z`` fed by ``extra``."""
    wheel = {"sign": 1, "coefficients": ["distance_gain"], "of": "wheel_angle"}
    controller = helpers._law(
        [*helpers._no_travel_terms(), wheel, *terms],
        helpers._good_coefficients(0.04),
        [{"name": "z", "unit": "rad", "next": "z_now"}],
        [
            {
                "name": "z_now",
                "unit": "rad",
                "terms": [{"sign": 1, "of": "previous.z"}, *extra],
            }
        ],
    )
    return controller  # type: ignore[no-any-return]


def test_a_gyro_integrator_nothing_reads_is_listed_as_fed_by_the_gyro_and_not_read(
    tmp_path: Path,
) -> None:
    controller = _stable_with([{"sign": 1, "coefficients": ["period"], "of": "tilt_rate"}], [])
    record = _record(tmp_path, controller)
    (mode,) = record["held_modes"]
    assert mode["memory_states"] == ["z"]
    assert mode["fed_by_signals"] == ["tilt_rate"]
    assert mode["fed_by_the_reference"] is False
    assert mode["read_by_the_command"] is False
    assert "bias" in mode["note"] and "reference" in mode["note"] and "grow" in mode["note"]
    assert all(r["verdict"] != "fail" for r in record["specs"] if r["name"] in ("pm", "up"))


def test_a_reference_integrator_is_listed_as_fed_by_the_reference(tmp_path: Path) -> None:
    controller = _stable_with([{"sign": 1, "of": "wheel_reference"}], [])
    record = _record(tmp_path, controller)
    (mode,) = record["held_modes"]
    assert mode["fed_by_signals"] == ["wheel_reference"]
    assert mode["fed_by_the_reference"] is True
    assert mode["read_by_the_command"] is False


def test_a_state_the_command_reads_through_the_leak_free_form_is_said_to_be_read(
    tmp_path: Path,
) -> None:
    plant = helpers._plant()
    radius = helpers.nominal(plant)["wheel_radius"]
    legacy = helpers._si(helpers._incremental(None), radius)
    controller = helpers._as_law(legacy, radius)
    record = _record(tmp_path, controller)
    (mode,) = record["held_modes"]
    assert mode["memory_states"] == ["angle"]
    assert mode["involves_wheel_angle"] is True
    assert mode["fed_by_signals"] == ["tilt_rate"]
    assert mode["read_by_the_command"] is True


def test_a_law_that_holds_no_mode_lists_none(tmp_path: Path) -> None:
    assert _record(tmp_path, helpers._recorded_controller())["held_modes"] == []


def test_the_compute_delay_flags_reach_the_record_and_every_row_by_their_own_names(
    tmp_path: Path,
) -> None:
    flagged = helpers._recorded_controller()
    flagged["no_interface_statement"] = ["command_limit"]
    flagged["compute_delay_flags"] = ["compute_delay_omits_interface_times"]
    flagged["compute_delay_omitted"] = ["computation_delay_bound"]
    record = _record(tmp_path, flagged)
    for holder in (record, *record["specs"]):
        assert holder["no_interface_statement"] == ["command_limit"]
        assert holder["compute_delay_flags"] == ["compute_delay_omits_interface_times"]
        assert holder["compute_delay_omitted"] == ["computation_delay_bound"]
    clean = _record(tmp_path, helpers._recorded_controller())
    for holder in (clean, *clean["specs"]):
        assert holder["compute_delay_flags"] == []
        assert holder["compute_delay_omitted"] == []


# ── a chain of large coefficients ends in a named refusal and no warning in the scorer's log ──


def test_an_overflowing_chain_of_lines_is_a_numerical_refusal_and_says_nothing_to_the_log(
    tmp_path: Path,
) -> None:
    import warnings

    chain = 30
    coefficients = {**helpers._good_coefficients(0.04), "big": helpers._m(1e6, "1")}
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
    terms = [
        *helpers._no_travel_terms(),
        {"sign": 1, "coefficients": ["distance_gain"], "of": "wheel_angle"},
        {"sign": 1, "coefficients": ["distance_gain"], "of": f"line.l{chain - 1}"},
    ]
    controller = helpers._law(terms, coefficients, [], lines)
    with warnings.catch_warnings(record=True) as caught:
        warnings.simplefilter("always")
        record = _record(tmp_path, controller)
    assert [str(w.message) for w in caught] == []
    assert record["refusal"]["name"] == "numerical_failure"
    assert record["outcome"] == "fail"


def test_a_term_of_weight_zero_feeds_nothing_and_is_not_listed_as_a_feeder(tmp_path: Path) -> None:
    controller = _stable_with(
        [
            {"sign": 1, "coefficients": ["period"], "of": "tilt_rate"},
            {"sign": 1, "coefficients": ["off"], "of": "tilt"},
        ],
        [],
    )
    controller["coefficients"]["off"] = helpers._m(0.0, "1")
    record = _record(tmp_path, controller)
    (mode,) = record["held_modes"]
    assert mode["fed_by_signals"] == ["tilt_rate"]


def _spelt_as_text(controller: dict[str, Any], old: str, new: str) -> bytes:
    raw: str = helpers._answer(controller, 3).decode()
    assert raw.count(old) == 1
    return raw.replace(old, new).encode()


def test_a_decimal_written_to_17_digits_is_what_was_written_and_not_the_tenth_it_rounds_to(
    tmp_path: Path,
) -> None:
    """0.9 and 0.1 are tenths and sum to 1; 0.9 and 0.10000000000000001 do not, as written."""
    from physgate.evaluation.whole import loop as loop_module
    from physgate.evaluation.whole.answer import SampledLaw, parse_answer
    from physgate.evaluation.whole.convert import ScaleFactor, to_si

    base = _stable_with([], [])
    base["coefficients"]["pole"] = helpers._m(0.9, "1")
    base["coefficients"]["rest"] = helpers._m(0.1, "1")
    base["lines"][0]["terms"] = [
        {"sign": 1, "coefficients": ["pole"], "of": "previous.z"},
        {"sign": 1, "coefficients": ["rest"], "of": "previous.z"},
    ]
    values = helpers.nominal(helpers._plant())
    radius = ScaleFactor("wheel_radius", values["wheel_radius"], "m", "this test's plant")

    def stable(raw: bytes) -> bool:
        answer = parse_answer(raw)
        return loop_module.margins(
            values, to_si(answer.controller, answer.parameters, wheel_radius=radius)
        ).stable

    assert stable(helpers._answer(base, 3))
    longer = _spelt_as_text(
        base, '"rest": {"value": 0.1,', '"rest": {"value": 0.10000000000000001,'
    )
    parsed = parse_answer(longer).controller
    assert isinstance(parsed, SampledLaw)
    assert parsed.coefficients["rest"].value == 0.1  # the same float
    assert not stable(longer)
