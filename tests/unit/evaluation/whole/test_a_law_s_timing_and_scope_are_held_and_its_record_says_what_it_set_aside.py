"""The export holds a law's period, compute delay and scope, and its record says what it set aside.

The period equals the reciprocal of the interface's update rate (else a refusal by name); the
compute delay is flagged, by names of their own, when it leaves out a time-valued quantity of
the interface nodes it draws on or draws on a quantity the interface does not state; a term that
cannot affect the command is no ground for a scope refusal and is taken out, and a law refused
for scope has every other check run on it first. The record carries each mode the loop analysis
will set aside (its states, what feeds them, whether the command reads them) and the pin the
vectors achieve for each term and coefficient.
"""

from __future__ import annotations

import copy
import importlib
import json
from pathlib import Path
from typing import Any

import pytest

from physgate.evaluation.whole import law as law_module
from physgate.evaluation.whole.export import record_path

# The helpers of the recorded design's export rows: its graph, its repository, its law file.
helpers: Any = importlib.import_module(
    "test_a_recorded_design_s_law_is_exported_when_it_reproduces_its_own_vectors"
)
INTERFACE: dict[str, Any] = helpers.INTERFACE
COEFFICIENTS: dict[str, Any] = helpers.COEFFICIENTS


def _with(document: dict[str, Any], **sources: Any) -> bytes:
    document = copy.deepcopy(document)
    document.update(sources)
    raw: bytes = helpers._bytes(document)
    return raw


def _interface_with(extra: dict[str, Any]) -> dict[str, Any]:
    out = copy.deepcopy(INTERFACE)
    out["firmware.timing"].update(extra)
    return out


# ── the period ──────────────────────────────────────────────────────────────────────────────


def _stateless_graph() -> dict[str, Any]:
    return {
        "angle_gain": (1.6643, "1/rad"),
        "rate_gain": (0.191, "s/rad"),
        "distance_gain": (0.2853 * 0.04, "1/rad"),
        "speed_gain": (1.3421 * 0.04, "s/rad"),
        "update_rate": (100, "Hz"),
        "duty_cycle": (0.9425, "1"),
        "computation_delay_bound": (0.003, "s"),
        "update_lateness_bound": (0.001, "s"),
        "output_data_rate": (208, "Hz"),
    }


def _stateless_law(period: dict[str, Any]) -> dict[str, Any]:
    """The good gains as a law with no memory and no period in any term, its vectors its own.

    The period is in none of its terms, so no vector can notice what the period is: only what
    the run's interface states can hold it.
    """
    names = ("angle_gain", "rate_gain", "distance_gain", "speed_gain")
    document: dict[str, Any] = {
        "form": "sampled_law_file",
        "version": 1,
        "period": period,
        "command_limit": {"quantity": "duty_cycle"},
        "sensor_delay": {"reciprocal_of": "output_data_rate"},
        "compute_delay": {"sum_of": ["computation_delay_bound", "update_lateness_bound"]},
        "coefficients": {name: name for name in names},
        "memory": [],
        "lines": [
            {
                "name": "command",
                "unit": "1",
                "terms": [
                    {"sign": 1, "coefficients": [n], "of": signal}
                    for n, signal in zip(
                        names, ("tilt", "tilt_rate", "wheel_angle", "wheel_speed"), strict=True
                    )
                ],
            }
        ],
        "command": "command",
    }
    body = law_module.Body.model_validate_json(
        json.dumps({k: document[k] for k in ("memory", "lines", "command")})
    )
    graph = _stateless_graph()
    values = {name: graph[name][0] for name in names}
    rows = []
    for n in range(24):
        signals = {
            "tilt": 0.2 * ((n * 5) % 7 - 3) + 0.03,
            "tilt_rate": 0.3 * ((n * 7) % 5 - 2) + 0.05,
            "wheel_angle": 0.4 * ((n * 3) % 7 - 3) + 0.1,
            "wheel_speed": 0.5 * ((n * 5) % 6 - 2) + 0.07,
        }
        duty, _ = law_module.evaluate(body, values, period=0.01, state={}, signals=signals)
        held = min(max(duty, -0.9425), 0.9425)
        counts = int(held * 400 + (0.5 if held >= 0 else -0.5))
        rows.append({**signals, "duty": duty, "counts": counts})
    document["vectors"] = [{"name": "mixed", "rows": rows}]
    return document


def _stateless_export(
    tmp_path: Path, period: dict[str, Any], own: float | None = None, **kwargs: Any
) -> Any:
    graph = _stateless_graph()
    if own is not None:
        graph["my_period"] = (own, "s")
    return helpers._export(
        tmp_path, helpers._bytes(_stateless_law(period)), coefficients=graph, **kwargs
    )


def test_a_stateless_law_exports_at_the_period_the_interface_states(tmp_path: Path) -> None:
    record, out, _, _ = _stateless_export(
        tmp_path, {"reciprocal_of": "update_rate"}, interface=INTERFACE
    )
    assert record.status == "exported", (record.law_reason, record.law_detail)
    assert json.loads(out.read_bytes())["controller"]["period"] == {"value": 0.01, "unit": "s"}


@pytest.mark.parametrize(
    ("own", "label"),
    [
        (0.002, "500 Hz, the control node's own quantity"),
        (1 / 208, "208 Hz, the gyro's own"),
        (0.02, "a longer period"),
        (0.0099, "slightly shorter"),
        (0.01 * (1 + 1e-6), "slightly longer"),
    ],
)
def test_a_period_that_is_not_the_reciprocal_of_the_interface_s_update_rate_is_refused(
    tmp_path: Path, own: float, label: str
) -> None:
    # no vector can tell: the period is in none of the law's terms
    record, out, _, _ = _stateless_export(
        tmp_path, {"quantity": "my_period"}, own, interface=INTERFACE
    )
    assert record.status == "law_unverified", (label, record.status)
    assert record.law_reason == "period_is_not_the_interface_s", record.law_detail
    assert "period" in record.law_detail
    assert "update_rate" in record.law_detail
    helpers._nothing_written(out)


def test_the_same_period_by_another_quantity_is_exported_and_held_against_the_interface(
    tmp_path: Path,
) -> None:
    record, _, _, _ = _stateless_export(
        tmp_path, {"quantity": "my_period"}, 0.01, interface=INTERFACE
    )
    assert record.status == "exported", (record.law_reason, record.law_detail)
    assert record.law_timing["period"]["held_against"]["value"] == 0.01
    assert record.law_timing["period"]["no_interface_statement"] is False


def test_the_period_the_interface_states_is_exported_and_held_against_it(tmp_path: Path) -> None:
    record, out, _, _ = helpers._export(tmp_path, interface=INTERFACE)
    assert record.status == "exported"
    held = record.law_timing["period"]
    assert held["held_against"] == {"name": "update_rate", "node": "firmware.timing", "value": 0.01}
    assert held["no_interface_statement"] is False
    assert json.loads(out.read_bytes())["controller"]["period"] == {"value": 0.01, "unit": "s"}


def test_a_period_is_flagged_where_the_interface_states_no_update_rate(tmp_path: Path) -> None:
    document = helpers._file()
    document["coefficients"]["my_period"] = "my_period"
    record, out, _, _ = helpers._export(
        tmp_path,
        _with(document, period={"quantity": "my_period"}),
        coefficients={**COEFFICIENTS, "my_period": (0.01, "s")},
    )
    assert record.status == "exported", (record.law_reason, record.law_detail)
    assert record.law_timing["period"]["no_interface_statement"] is True
    assert "period" in json.loads(out.read_bytes())["controller"]["no_interface_statement"]


# ── the compute delay, by its own flags ─────────────────────────────────────────────────────


def _exported(tmp_path: Path, document: dict[str, Any], **kwargs: Any) -> Any:
    record, out, _, _ = helpers._export(tmp_path, helpers._bytes(document), **kwargs)
    assert record.status == "exported", (record.law_reason, record.law_detail)
    return (
        record,
        json.loads(out.read_bytes())["controller"],
        json.loads(record_path(out).read_text()),
    )


def test_the_recorded_design_names_both_interface_time_bounds_and_is_not_flagged(
    tmp_path: Path,
) -> None:
    record, controller, written = _exported(tmp_path, helpers._file(), interface=INTERFACE)
    timing = record.law_timing["compute_delay"]
    assert timing["flags"] == []
    assert timing["omitted_interface_times"] == []
    assert timing["not_the_interface_s"] == []
    assert controller["compute_delay_flags"] == []
    assert controller["compute_delay_omitted"] == []
    assert written["law_timing"]["compute_delay"]["flags"] == []


@pytest.mark.parametrize(
    "source",
    [{"quantity": "update_lateness_bound"}, {"sum_of": ["update_lateness_bound"]}],
    ids=["quantity", "sum_of_one"],
)
def test_a_compute_delay_naming_only_a_1_ms_bound_is_flagged_and_names_what_it_leaves_out(
    tmp_path: Path, source: dict[str, Any]
) -> None:
    document = helpers._file()
    document["compute_delay"] = source
    record, controller, written = _exported(tmp_path, document, interface=INTERFACE)
    assert controller["compute_delay"] == {"value": 0.001, "unit": "s"}
    for flags, omitted in (
        (
            record.law_timing["compute_delay"]["flags"],
            record.law_timing["compute_delay"]["omitted_interface_times"],
        ),
        (controller["compute_delay_flags"], controller["compute_delay_omitted"]),
        (
            written["law_timing"]["compute_delay"]["flags"],
            written["law_timing"]["compute_delay"]["omitted_interface_times"],
        ),
    ):
        assert flags == ["compute_delay_omits_interface_times"]
        assert omitted == ["computation_delay_bound"]
    # a flag of its own, not the no-statement flag: the quantity is the interface's
    assert controller["no_interface_statement"] == []


def test_a_compute_delay_naming_a_2_microsecond_interface_quantity_is_flagged(
    tmp_path: Path,
) -> None:
    document = helpers._file()
    document["compute_delay"] = {"quantity": "dead_time"}
    interface = _interface_with({"dead_time": (2e-6, "s")})
    record, controller, _ = _exported(tmp_path, document, interface=interface)
    assert controller["compute_delay"] == {"value": 2e-6, "unit": "s"}
    assert controller["compute_delay_flags"] == ["compute_delay_omits_interface_times"]
    assert controller["compute_delay_omitted"] == [
        "computation_delay_bound",
        "update_lateness_bound",
    ]
    assert record.law_timing["compute_delay"]["not_the_interface_s"] == []


def test_naming_every_time_quantity_of_the_node_is_not_flagged_even_with_a_tiny_one(
    tmp_path: Path,
) -> None:
    document = helpers._file()
    document["compute_delay"] = {
        "sum_of": ["computation_delay_bound", "update_lateness_bound", "dead_time"]
    }
    interface = _interface_with({"dead_time": (2e-6, "s")})
    _, controller, _ = _exported(tmp_path, document, interface=interface)
    assert controller["compute_delay_flags"] == []
    assert controller["compute_delay"]["value"] == pytest.approx(0.004002)


def test_a_compute_delay_drawn_on_a_quantity_the_interface_does_not_state_is_flagged_apart(
    tmp_path: Path,
) -> None:
    document = helpers._file()
    document["compute_delay"] = {"quantity": "short_delay"}
    record, controller, _ = _exported(
        tmp_path,
        document,
        coefficients={**COEFFICIENTS, "short_delay": (0.0005, "s")},
        interface=INTERFACE,
    )
    assert controller["compute_delay_flags"] == ["compute_delay_names_a_non_interface_quantity"]
    assert record.law_timing["compute_delay"]["not_the_interface_s"] == ["short_delay"]
    # the existing flag is still there, under its own name
    assert "compute_delay" in controller["no_interface_statement"]


def test_a_quantity_only_control_wrote_in_an_interface_node_is_not_the_interface_s(
    tmp_path: Path,
) -> None:
    # control's own copy of an interface quantity in the interface node is not its statement
    helpers._OWNERS["firmware.timing"] = "control"
    try:
        record, controller, _ = _exported(tmp_path, helpers._file(), interface=INTERFACE)
    finally:
        helpers._OWNERS["firmware.timing"] = "firmware"
    assert controller["compute_delay_flags"] == ["compute_delay_names_a_non_interface_quantity"]
    assert record.law_timing["compute_delay"]["not_the_interface_s"]


def test_a_time_quantity_control_wrote_in_an_interface_node_need_not_be_in_the_sum(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    original = helpers._node

    def node(*args: Any, **kwargs: Any) -> dict[str, Any]:
        made: dict[str, Any] = original(*args, **kwargs)
        if "control_bound" in made["quantities"]:
            made["quantities"]["control_bound"]["written_by"] = "control"
        return made

    monkeypatch.setattr(helpers, "_node", node)
    interface = _interface_with({"control_bound": (0.5, "s")})
    _, controller, _ = _exported(tmp_path, helpers._file(), interface=interface)
    assert controller["compute_delay_flags"] == []
    assert controller["compute_delay_omitted"] == []


def test_a_time_quantity_in_another_unit_of_time_is_left_out_all_the_same(tmp_path: Path) -> None:
    # the interface states a 5 ms bound in ms: the sum (in s) cannot name it, so it is flagged
    interface = _interface_with({"jitter": (5, "ms")})
    _, controller, _ = _exported(tmp_path, helpers._file(), interface=interface)
    assert controller["compute_delay_flags"] == ["compute_delay_omits_interface_times"]
    assert controller["compute_delay_omitted"] == ["jitter"]


# ── a term that cannot affect the command is no ground for refusing the law ─────────────────


def _command(document: dict[str, Any]) -> dict[str, Any]:
    line: dict[str, Any] = next(x for x in document["lines"] if x["name"] == "command")
    return line


def _with_an_unread_line(of: str) -> dict[str, Any]:
    document: dict[str, Any] = helpers._file()
    document["lines"].insert(
        0,
        {
            "name": "scratch",
            "unit": "rad",
            "terms": [{"sign": 1, "coefficients": [], "of": of}],
        },
    )
    return document


@pytest.mark.parametrize("of", ["accelerometer_tilt", "tilt_rate*wheel_angle", "abs(tilt)"])
def test_an_out_of_scope_line_nothing_reads_is_set_aside_and_the_law_is_exported(
    tmp_path: Path, of: str
) -> None:
    record, controller, written = _exported(tmp_path, _with_an_unread_line(of), interface=INTERFACE)
    assert all(line["name"] != "scratch" for line in controller["lines"])
    assert len(record.law_set_aside) == 1
    assert record.law_set_aside[0]["line"] == "scratch"
    assert record.law_set_aside[0]["code"] in {"out_of_scope", "nonlinear"}
    assert written["law_set_aside"] == list(record.law_set_aside)


def test_an_out_of_scope_term_of_zero_weight_is_set_aside(tmp_path: Path) -> None:
    document = helpers._file()
    _command(document)["terms"].append(
        {"sign": 1, "coefficients": ["k_zero"], "of": "accelerometer_tilt"}
    )
    document["coefficients"]["k_zero"] = "k_zero"
    record, controller, _ = _exported(
        tmp_path, document, coefficients={**COEFFICIENTS, "k_zero": (0.0, "1/rad")}
    )
    assert len(record.law_set_aside) == 1
    assert len(_command(controller)["terms"]) == len(_command(helpers._file())["terms"])


def test_an_out_of_scope_term_the_command_uses_is_refused_by_name(tmp_path: Path) -> None:
    document = helpers._file()
    _command(document)["terms"][0]["of"] = "accelerometer_tilt"
    record = helpers._refused(tmp_path, "out_of_scope", law=helpers._bytes(document))
    assert "accelerometer_tilt" in record.law_detail


def test_a_law_refused_for_scope_has_every_other_check_run_first(tmp_path: Path) -> None:
    live = helpers._file()
    _command(live)["terms"][0]["of"] = "accelerometer_tilt"
    # a unit that does not balance elsewhere is the refusal, not the scope
    units = copy.deepcopy(live)
    next(x for x in units["lines"] if x["name"] == "theta_now")["terms"][1]["coefficients"] = []
    helpers._refused(tmp_path, "units_do_not_balance", law=helpers._bytes(units))
    # a coefficient the graph does not hold
    held = {k: v for k, v in COEFFICIENTS.items() if k != "k_u"}
    for name in ("held", "zero", "floor", "period"):
        (tmp_path / name).mkdir()
    helpers._refused(
        tmp_path / "held", "coefficient_not_held", law=helpers._bytes(live), coefficients=held
    )
    # a coefficient that divides by zero
    dividing = copy.deepcopy(live)
    _command(dividing)["terms"][1]["per"] = ["k_u"]
    helpers._refused(
        tmp_path / "zero",
        "zero_divisor",
        law=helpers._bytes(dividing),
        coefficients={**COEFFICIENTS, "k_u": (0.0, "1")},
    )
    # a sensor delay kinder than the interface's
    kinder = copy.deepcopy(live)
    kinder["coefficients"]["fast_delay"] = "fast_delay"
    kinder["sensor_delay"] = {"quantity": "fast_delay"}
    helpers._refused(
        tmp_path / "floor",
        "delay_or_limit_not_stated_by_the_interface",
        law=helpers._bytes(kinder),
        coefficients={**COEFFICIENTS, "fast_delay": (0.001, "s")},
        interface=INTERFACE,
    )
    # a period that is not the interface's
    quick = copy.deepcopy(live)
    quick["coefficients"]["my_period"] = "my_period"
    quick["period"] = {"quantity": "my_period"}
    helpers._refused(
        tmp_path / "period",
        "period_is_not_the_interface_s",
        law=helpers._bytes(quick),
        coefficients={**COEFFICIENTS, "my_period": (0.002, "s")},
        interface=INTERFACE,
    )


# ── a zero where a reciprocal is taken ──────────────────────────────────────────────────────


def test_a_coefficient_of_zero_where_a_reciprocal_is_taken_is_refused_by_name(
    tmp_path: Path,
) -> None:
    document = helpers._file()
    _command(document)["terms"][1]["per"] = ["k_u"]
    record = helpers._refused(
        tmp_path,
        "zero_divisor",
        law=helpers._bytes(document),
        coefficients={**COEFFICIENTS, "k_u": (0.0, "1")},
    )
    assert "k_u" in record.law_detail


# ── the record carries the pin the vectors achieve, and the modes set aside ──────────────────


def test_the_record_carries_the_pin_each_term_and_coefficient_achieves(tmp_path: Path) -> None:
    record, out, _, _ = helpers._export(tmp_path)
    assert record.status == "exported"
    pins = record.law_pins
    assert {
        f"coefficient {n}" for n in ("k_phi", "k_theta", "k_w", "k_rate", "k_u", "leak")
    } <= set(pins)
    assert sum(1 for key in pins if key.startswith("term ")) == 14
    for key, pin in pins.items():
        assert 0.0 < pin["smallest"] <= law_module.PIN_RELATIVE, key
        assert pin["up"] is not None and pin["down"] is not None
    # the loosest pin is the position gain's, about one per cent: the one the margins need told
    assert 0.005 < pins["coefficient k_phi"]["smallest"] < 0.0105
    assert pins["coefficient k_theta"]["smallest"] < 1e-4
    assert json.loads(record_path(out).read_text())["law_pins"] == pins


def test_a_pin_is_the_smallest_change_the_rows_notice_found_by_halving(tmp_path: Path) -> None:
    record, _, _, _ = helpers._export(tmp_path)
    pin = record.law_pins["coefficient k_phi"]["up"]
    values = {
        n: float(COEFFICIENTS[n][0]) for n in ("k_phi", "k_theta", "k_w", "k_rate", "k_u", "leak")
    }
    law = law_module.parse_file(helpers._LAW.read_bytes())
    vectors = law.vectors
    more = {**values, "k_phi": values["k_phi"] * (1 + pin)}
    less = {**values, "k_phi": values["k_phi"] * (1 + pin * 0.99)}
    held = {"period": 0.01, "limit": 0.9425, "full_scale": 400.0}
    assert law_module.reproduce(law, more, vectors, **held)[1] is not None  # type: ignore[arg-type]
    assert law_module.reproduce(law, less, vectors, **held)[1] is None  # type: ignore[arg-type]


def test_the_record_of_a_law_that_holds_a_mode_lists_it(tmp_path: Path) -> None:
    document = _leak_free_incremental()
    record, out, _, _ = helpers._export(
        tmp_path,
        helpers._bytes(document),
        coefficients=_incremental_graph(),
        interface=INTERFACE,
    )
    assert record.status == "exported", (record.law_reason, record.law_detail)
    (mode,) = record.law_held_modes
    assert mode["memory_states"] == ["angle"]
    assert mode["involves_wheel_angle"] is True
    assert mode["fed_by_signals"] == ["tilt_rate"]
    assert mode["fed_by_the_reference"] is False
    assert mode["read_by_the_command"] is True
    assert "grow" in mode["note"]
    assert json.loads(record_path(out).read_text())["law_held_modes"] == [mode]


def test_a_law_that_holds_no_mode_lists_none(tmp_path: Path) -> None:
    record, _, _, _ = helpers._export(tmp_path)
    assert record.law_held_modes == ()


def _incremental_graph() -> dict[str, Any]:
    return {
        "angle_gain": (0.13984913700800736, "1/rad"),
        "rate_gain": (0.13984913700800736 * 0.14, "s/rad"),
        "distance_gain": (0.17308404749760797 * 0.04, "1/rad"),
        "speed_gain": (0.07824347352631594 * 0.04, "s/rad"),
        "decay": (1.0, "1"),
        "update_rate": (100, "Hz"),
        "duty_cycle": (0.9425, "1"),
        "computation_delay_bound": (0.003, "s"),
        "update_lateness_bound": (0.001, "s"),
        "output_data_rate": (208, "Hz"),
    }


def _leak_free_incremental() -> dict[str, Any]:
    """The velocity form with no leak, as a law file, its vectors made by the law itself."""
    document: dict[str, Any] = {
        "form": "sampled_law_file",
        "version": 1,
        "period": {"reciprocal_of": "update_rate"},
        "command_limit": {"quantity": "duty_cycle"},
        "sensor_delay": {"reciprocal_of": "output_data_rate"},
        "compute_delay": {"sum_of": ["computation_delay_bound", "update_lateness_bound"]},
        "coefficients": {
            name: name
            for name in ("angle_gain", "rate_gain", "distance_gain", "speed_gain", "decay")
        },
        "memory": [
            {"name": "angle", "unit": "rad", "next": "angle_now"},
            {"name": "applied", "unit": "1", "next": "command", "applied": True},
        ],
        "lines": [
            {
                "name": "angle_now",
                "unit": "rad",
                "terms": [
                    {"sign": 1, "coefficients": ["decay"], "of": "previous.angle"},
                    {"sign": 1, "coefficients": ["decay", "period"], "of": "tilt_rate"},
                ],
            },
            {
                "name": "command",
                "unit": "1",
                "terms": [
                    {"sign": 1, "of": "previous.applied"},
                    {"sign": 1, "coefficients": ["angle_gain"], "of": "line.angle_now"},
                    {"sign": 1, "coefficients": ["rate_gain"], "of": "tilt_rate"},
                    {"sign": 1, "coefficients": ["distance_gain"], "of": "wheel_angle"},
                    {"sign": 1, "coefficients": ["speed_gain"], "of": "wheel_speed"},
                ],
            },
        ],
        "command": "command",
    }
    body = law_module.Body.model_validate_json(
        json.dumps({k: document[k] for k in ("memory", "lines", "command")})
    )
    graph = _incremental_graph()
    values = {name: graph[name][0] for name in document["coefficients"]}
    state = {"angle": 0.0, "applied": 0.0}
    rows = []
    for n in range(24):
        signals = {
            "tilt_rate": 0.3 * ((n * 7) % 5 - 2) + 0.05,
            "wheel_angle": 0.4 * ((n * 3) % 7 - 3) + 0.1,
            "wheel_speed": 0.5 * ((n * 5) % 6 - 2) + 0.07,
        }
        duty, following = law_module.evaluate(
            body, values, period=0.01, state=state, signals=signals
        )
        held = min(max(duty, -0.9425), 0.9425)
        counts = int(held * 400 + (0.5 if held >= 0 else -0.5))
        rows.append({**signals, "duty": duty, "counts": counts})
        state = {"angle": following["angle"], "applied": counts / 400.0}
    document["vectors"] = [{"name": "mixed", "rows": rows}]
    return document
