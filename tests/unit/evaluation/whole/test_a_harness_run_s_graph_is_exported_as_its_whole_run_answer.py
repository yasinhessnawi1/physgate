"""A harness run's whole-run answer is exported from its design-state graph, by name, never guessed.

The graph is built here through the store's own writer, in a temporary run directory laid out
as the orchestrator lays one out (the canonical store at ``<run>/store``). The contract's names
and units below are this test's own statement, written apart from the module, so a name the
module reads differently is a red row here rather than a silent agreement.
"""

from __future__ import annotations

import hashlib
import importlib
import importlib.util
import json
import os
from pathlib import Path
from types import ModuleType
from typing import Any

import pytest

from physgate.evaluation.per_role.exceptions import TaskFormatError
from physgate.evaluation.whole.answer import parse_whole_run
from physgate.state.store import Store

_MODULE = "physgate.evaluation.whole.export"
_RUN4 = Path(__file__).resolve().parents[2] / "gate" / "run4" / "plan_interfaces.json"

Values = dict[str, tuple[float | int, str]]

DELAYS: Values = {"sensor_delay": (0.0048, "s"), "compute_delay": (0.002, "s")}
LOOP: Values = {**DELAYS, "period": (0.01, "s"), "command_limit": (0.75, "1")}
RISING: Values = {
    **LOOP,
    "rate_ratio": (0.14, "s"),
    "angle_gain": (1.25, "1/rad"),
    "distance_gain": (0.21, "1/m"),
    "speed_gain": (0.95, "s/m"),
}
FEEDBACK: Values = {
    **LOOP,
    "angle_gain": (1.6643, "1/rad"),
    "rate_gain": (0.191, "s/rad"),
    "distance_gain": (0.2853, "1/m"),
    "speed_gain": (1.3421, "s/m"),
}
#: The reference kit's balancing example as its code writes it.
NATIVE: Values = {
    **DELAYS,
    "update_time": (10, "ms"),
    "motor_speed_limit": (300, "count"),
    "angle_rate_ratio": (140, "ms"),
    "angle_response": (11, "1"),
    "distance_response": (73, "1"),
    "speed_response": (3300, "1"),
    "response_divisor": (100, "1"),
    "gear_ratio_coefficient": (111, "1"),
    "gyro_divisor": (29, "count*s/deg"),
    "angle_decay_numerator": (999, "1"),
    "angle_decay_denominator": (1000, "1"),
}
PARAMETERS: Values = {
    "update_rate": (100, "Hz"),
    "gyro_output_data_rate": (208, "Hz"),
    "gyro_full_scale": (1000, "deg/s"),
    "pwm_frequency": (20000, "Hz"),
    "pwm_full_scale": (400, "count"),
    "encoder_counts_per_wheel_revolution": (1322.9, "count"),
}
SENSITIVITY: Values = {"gyro_sensitivity": (28.571, "count*s/deg")}
DECAY: Values = {"angle_decay_per_update": (0.999, "1")}

STRUCTURES: dict[str, Values] = {
    "incremental_rising_offset": RISING,
    "state_feedback": FEEDBACK,
    "native_incremental_rising_offset": NATIVE,
}


def _module() -> ModuleType:
    assert importlib.util.find_spec(_MODULE) is not None, f"{_MODULE} does not exist"
    return importlib.import_module(_MODULE)


def _node(
    node_id: str,
    values: Values,
    *,
    owner: str = "control",
    domain: str = "control",
    kind: str = "module",
) -> dict[str, Any]:
    return {
        "id": node_id,
        "kind": kind,
        "domain": domain,
        "owner_role": owner,
        "quantities": {
            name: {"value": value, "unit": unit, "source": "fixture", "written_by": owner}
            for name, (value, unit) in values.items()
        },
        "requirements": [],
        "constrains": [],
        "model": None,
        "geometry_hash": "none",
        "updated": "2026-11-20",
    }


def _run(tmp_path: Path, *nodes: dict[str, Any]) -> Path:
    """A run directory whose canonical store holds ``nodes``, each written by its owner."""
    run = Path(os.path.realpath(tmp_path)) / "run"
    (run / "store").mkdir(parents=True)
    store = Store(run / "store")
    try:
        for node in nodes:
            result = store.write_node(node, node["owner_role"])
            assert result.accepted, result.reason
    finally:
        store.close()
    return run


def _split(controller: Values, parameters: Values) -> tuple[dict[str, Any], dict[str, Any]]:
    """The controller in one node and the parameters in another, as a plan splits them."""
    return (
        _node("balance.controller", controller),
        _node("firmware.loop_timing", parameters, owner="firmware", domain="firmware"),
    )


def _export(run: Path, tmp_path: Path) -> tuple[Any, Path]:
    out = Path(os.path.realpath(tmp_path)) / "answers" / "whole_run.json"
    return _module().export_whole_run(run, out), out


def _measures(values: Values) -> dict[str, dict[str, object]]:
    return {name: {"value": value, "unit": unit} for name, (value, unit) in values.items()}


@pytest.mark.parametrize("structure", sorted(STRUCTURES))
def test_a_graph_naming_one_structure_and_every_setting_is_exported_as_it_states_them(
    tmp_path: Path, structure: str
) -> None:
    run = _run(tmp_path, *_split(STRUCTURES[structure], {**PARAMETERS, **SENSITIVITY}))
    record, out = _export(run, tmp_path)
    assert record.status == "exported"
    assert record.structure == structure
    raw = out.read_bytes()
    answer = json.loads(raw)
    assert answer["form"] == "whole_run"
    assert answer["version"] == 2
    assert answer["controller"] == {"structure": structure, **_measures(STRUCTURES[structure])}
    assert answer["parameters"] == _measures({**PARAMETERS, **SENSITIVITY})
    assert "analysed_controller" not in answer
    assert answer["files"] == []
    parse_whole_run(raw)  # the scorer's own reading takes it whole
    assert record.sha256 == hashlib.sha256(raw).hexdigest()
    assert record.missing == {}
    assert record.conflicts == {}


def test_every_exported_value_names_the_node_it_was_taken_from(tmp_path: Path) -> None:
    run = _run(tmp_path, *_split(FEEDBACK, PARAMETERS))
    record, _ = _export(run, tmp_path)
    assert record.taken_from == {
        **{name: ("balance.controller",) for name in FEEDBACK},
        **{name: ("firmware.loop_timing",) for name in PARAMETERS},
    }


def test_the_angle_s_leak_and_the_gyro_s_sensitivity_are_exported_only_when_the_graph_states_them(
    tmp_path: Path,
) -> None:
    with_both = _run(tmp_path / "a", *_split({**RISING, **DECAY}, {**PARAMETERS, **SENSITIVITY}))
    record, out = _export(with_both, tmp_path / "a")
    answer = json.loads(out.read_bytes())
    assert record.status == "exported"
    assert answer["controller"]["angle_decay_per_update"] == {"value": 0.999, "unit": "1"}
    assert answer["parameters"]["gyro_sensitivity"] == {"value": 28.571, "unit": "count*s/deg"}

    without = _run(tmp_path / "b", *_split(RISING, PARAMETERS))
    record, out = _export(without, tmp_path / "b")
    answer = json.loads(out.read_bytes())
    assert record.status == "exported"
    assert "angle_decay_per_update" not in answer["controller"]
    assert "gyro_sensitivity" not in answer["parameters"]


def test_a_value_in_another_unit_is_exported_unconverted_and_the_answer_then_fails(
    tmp_path: Path,
) -> None:
    parameters = {**PARAMETERS, "gyro_full_scale": (17.453, "rad/s")}
    run = _run(tmp_path, *_split(FEEDBACK, parameters))
    record, out = _export(run, tmp_path)
    assert record.status == "exported"
    raw = out.read_bytes()
    assert json.loads(raw)["parameters"]["gyro_full_scale"] == {"value": 17.453, "unit": "rad/s"}
    with pytest.raises(TaskFormatError, match="deg/s"):
        parse_whole_run(raw)


def test_a_value_past_its_bound_is_exported_as_the_graph_holds_it(tmp_path: Path) -> None:
    run = _run(tmp_path, *_split({**FEEDBACK, "command_limit": (1.5, "1")}, PARAMETERS))
    record, out = _export(run, tmp_path)
    assert record.status == "exported"
    raw = out.read_bytes()
    assert json.loads(raw)["controller"]["command_limit"] == {"value": 1.5, "unit": "1"}
    with pytest.raises(TaskFormatError):
        parse_whole_run(raw)


_REQUIRED = [(s, name) for s, values in sorted(STRUCTURES.items()) for name in sorted(values)]


@pytest.mark.parametrize(("structure", "name"), _REQUIRED, ids=[f"{s}-{n}" for s, n in _REQUIRED])
def test_a_structure_lacking_any_of_its_names_is_no_answer_and_the_name_is_said(
    tmp_path: Path, structure: str, name: str
) -> None:
    controller = {k: v for k, v in STRUCTURES[structure].items() if k != name}
    run = _run(tmp_path, *_split(controller, {**PARAMETERS, **SENSITIVITY}))
    record, out = _export(run, tmp_path)
    assert record.status == "contract_lost"
    assert name in record.missing.get(structure, ())
    assert record.structure is None
    assert record.sha256 is None
    assert not out.exists()
    assert not out.parent.exists() or list(out.parent.iterdir()) == []


@pytest.mark.parametrize("name", sorted(PARAMETERS))
def test_a_graph_lacking_any_setting_is_no_answer_and_the_setting_is_said(
    tmp_path: Path, name: str
) -> None:
    parameters = {k: v for k, v in PARAMETERS.items() if k != name}
    run = _run(tmp_path, *_split(FEEDBACK, parameters))
    record, out = _export(run, tmp_path)
    assert record.status == "contract_lost"
    assert record.missing == {"parameters": (name,)}
    assert record.structure == "state_feedback"
    assert not out.exists()


def test_a_graph_with_no_structure_complete_says_what_each_lacks(tmp_path: Path) -> None:
    run = _run(tmp_path, *_split(LOOP, PARAMETERS))
    record, _ = _export(run, tmp_path)
    assert record.status == "contract_lost"
    assert record.missing == {
        "incremental_rising_offset": ("angle_gain", "distance_gain", "rate_ratio", "speed_gain"),
        "native_incremental_rising_offset": tuple(sorted(set(NATIVE) - set(DELAYS))),
        "state_feedback": ("angle_gain", "distance_gain", "rate_gain", "speed_gain"),
    }


def test_an_empty_graph_is_no_answer_at_revision_zero(tmp_path: Path) -> None:
    run = Path(os.path.realpath(tmp_path)) / "run"
    (run / "store").mkdir(parents=True)
    record, out = _export(run, tmp_path)
    assert record.status == "contract_lost"
    assert record.revision == 0
    assert not out.exists()


def test_a_name_two_nodes_agree_on_is_exported_once_and_names_both(tmp_path: Path) -> None:
    controller, parameters = _split(FEEDBACK, PARAMETERS)
    copy = _node("drivetrain.motor", {"pwm_full_scale": (400, "count")}, owner="sizing")
    run = _run(tmp_path, controller, parameters, copy)
    record, out = _export(run, tmp_path)
    assert record.status == "exported"
    assert record.taken_from["pwm_full_scale"] == ("drivetrain.motor", "firmware.loop_timing")
    assert json.loads(out.read_bytes())["parameters"]["pwm_full_scale"] == {
        "value": 400,
        "unit": "count",
    }


@pytest.mark.parametrize(
    "other",
    [(0.8, "1"), (75, "%")],
    ids=["another value", "another unit"],
)
def test_a_name_two_nodes_disagree_on_is_ambiguous_and_nothing_is_written(
    tmp_path: Path, other: tuple[float, str]
) -> None:
    controller, parameters = _split(FEEDBACK, PARAMETERS)
    other_node = _node("drivetrain.motor", {"command_limit": other}, owner="sizing")
    run = _run(tmp_path, controller, parameters, other_node)
    record, out = _export(run, tmp_path)
    assert record.status == "ambiguous"
    assert record.conflicts == {"command_limit": ("balance.controller", "drivetrain.motor")}
    assert record.sha256 is None
    assert not out.exists()


def test_a_disagreement_on_a_name_the_chosen_structure_does_not_read_is_still_ambiguous(
    tmp_path: Path,
) -> None:
    controller, parameters = _split(FEEDBACK, PARAMETERS)
    one = _node("firmware.native_a", {"angle_response": (11, "1")}, owner="firmware")
    two = _node("firmware.native_b", {"angle_response": (12, "1")}, owner="firmware")
    run = _run(tmp_path, controller, parameters, one, two)
    record, out = _export(run, tmp_path)
    assert record.status == "ambiguous"
    assert record.conflicts == {"angle_response": ("firmware.native_a", "firmware.native_b")}
    assert not out.exists()


@pytest.mark.parametrize(
    ("controller", "complete"),
    [
        (
            {**RISING, "rate_gain": (0.191, "s/rad")},
            ("incremental_rising_offset", "state_feedback"),
        ),
        ({**RISING, **NATIVE}, ("incremental_rising_offset", "native_incremental_rising_offset")),
    ],
    ids=["rising and feedback", "rising and native"],
)
def test_a_graph_naming_two_whole_structures_is_ambiguous_and_names_both(
    tmp_path: Path, controller: Values, complete: tuple[str, ...]
) -> None:
    run = _run(tmp_path, *_split(controller, {**PARAMETERS, **SENSITIVITY}))
    record, out = _export(run, tmp_path)
    assert record.status == "ambiguous"
    assert record.complete == tuple(sorted(complete))
    assert record.structure is None
    assert not out.exists()


def test_a_second_structure_s_partial_names_are_left_out_and_said(tmp_path: Path) -> None:
    controller = {**FEEDBACK, "angle_response": (11, "1"), "update_time": (10, "ms")}
    run = _run(tmp_path, *_split(controller, PARAMETERS))
    record, out = _export(run, tmp_path)
    assert record.status == "exported"
    assert record.left_out == ("angle_response", "update_time")
    answer = json.loads(out.read_bytes())
    assert "angle_response" not in answer["controller"]
    assert "update_time" not in answer["controller"]


def test_a_name_outside_the_contract_is_never_read(tmp_path: Path) -> None:
    # Run 4's own spellings beside the contract's: a near name is not the name.
    extra = {"sample_rate": (50, "Hz"), "encoder_counts_per_wheel_rev": (999, "count")}
    run = _run(tmp_path, *_split({**FEEDBACK, **extra}, PARAMETERS))
    record, out = _export(run, tmp_path)
    assert record.status == "exported"
    answer = json.loads(out.read_bytes())
    assert answer["parameters"]["update_rate"] == {"value": 100, "unit": "Hz"}
    assert answer["parameters"]["encoder_counts_per_wheel_revolution"] == {
        "value": 1322.9,
        "unit": "count",
    }
    assert "sample_rate" not in record.taken_from
    assert record.left_out == ()


def test_the_graph_is_read_as_its_newest_revision_leaves_it(tmp_path: Path) -> None:
    controller, parameters = _split(FEEDBACK, PARAMETERS)
    run = _run(tmp_path, controller, parameters)
    store = Store(run / "store")
    try:
        later = _split({**FEEDBACK, "angle_gain": (2.0, "1/rad")}, PARAMETERS)[0]
        assert store.write_node(later, "control").accepted
        head = store.head_revision()
    finally:
        store.close()
    record, out = _export(run, tmp_path)
    assert record.revision == head == 3
    assert json.loads(out.read_bytes())["controller"]["angle_gain"] == {
        "value": 2.0,
        "unit": "1/rad",
    }


def test_a_rolled_back_value_is_exported_as_the_rollback_left_it(tmp_path: Path) -> None:
    controller, parameters = _split(FEEDBACK, PARAMETERS)
    run = _run(tmp_path, controller, parameters)
    store = Store(run / "store")
    try:
        later = _split({**FEEDBACK, "angle_gain": (2.0, "1/rad")}, PARAMETERS)[0]
        assert store.write_node(later, "control").accepted
        store.rollback("balance.controller", 1)
    finally:
        store.close()
    _, out = _export(run, tmp_path)
    assert json.loads(out.read_bytes())["controller"]["angle_gain"] == {
        "value": 1.6643,
        "unit": "1/rad",
    }


def test_the_same_graph_is_exported_to_the_same_bytes(tmp_path: Path) -> None:
    nodes = _split(NATIVE, {**PARAMETERS, **SENSITIVITY})
    one = _run(tmp_path / "a", *nodes)
    two = _run(tmp_path / "b", *reversed(nodes))
    first, out_one = _export(one, tmp_path / "a")
    second, out_two = _export(two, tmp_path / "b")
    assert out_one.read_bytes() == out_two.read_bytes()
    assert first.sha256 == second.sha256


def test_a_run_with_no_store_is_refused_not_scored(tmp_path: Path) -> None:
    run = Path(os.path.realpath(tmp_path)) / "run"
    run.mkdir()
    with pytest.raises(_module().ExportError, match="store"):
        _export(run, tmp_path)


def test_a_store_whose_journal_no_store_could_have_written_is_refused(tmp_path: Path) -> None:
    run = _run(tmp_path, *_split(FEEDBACK, PARAMETERS))
    journal = next(p for p in (run / "store").iterdir() if p.is_file() and p.suffix == ".jsonl")
    journal.write_bytes(journal.read_bytes() + b'{"rev": 9}\n')
    # Any exception is caught, so one of another type is a failed assertion, not an error.
    with pytest.raises(Exception) as caught:  # noqa: PT011
        _export(run, tmp_path)
    assert isinstance(caught.value, _module().ExportError)
    assert "journal" in str(caught.value)


@pytest.mark.parametrize("left", ["file", "link", "directory"])
def test_the_answer_is_never_written_over_or_through_what_is_already_at_its_name(
    tmp_path: Path, left: str
) -> None:
    run = _run(tmp_path, *_split(FEEDBACK, PARAMETERS))
    out = Path(os.path.realpath(tmp_path)) / "answers" / "whole_run.json"
    out.parent.mkdir()
    target = Path(os.path.realpath(tmp_path)) / "elsewhere.json"
    target.write_text("untouched")
    if left == "file":
        out.write_text("earlier")
    elif left == "link":
        out.symlink_to(target)
    else:
        out.mkdir()
    with pytest.raises(_module().ExportError):
        _module().export_whole_run(run, out)
    assert target.read_text() == "untouched"
    if left == "file":
        assert out.read_text() == "earlier"


def test_the_reference_run_s_plan_as_written_exports_no_answer_and_says_why(
    tmp_path: Path,
) -> None:
    # The interface nodes a real decomposition wrote on the reference brief. They spell the
    # update rate ``sample_rate``, the counts ``encoder_counts_per_wheel_rev`` and the command
    # limit in counts, and name no delay: the contract's names are not there.
    nodes = json.loads(_RUN4.read_text())
    run = _run(tmp_path, *nodes)
    record, out = _export(run, tmp_path)
    assert record.status == "contract_lost"
    assert not out.exists()
    assert "update_rate" in record.missing.get("parameters", ())
    assert "encoder_counts_per_wheel_revolution" in record.missing.get("parameters", ())
    for structure in STRUCTURES:
        assert "sensor_delay" in record.missing.get(structure, ())
