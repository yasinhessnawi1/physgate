"""A harness run's whole-run answer is exported from its design-state graph, by name, never guessed.

The graph is built here through the store's own writer, in a temporary run directory laid out
as the orchestrator lays one out (the canonical store at ``<run>/store``, the event log at
``<run>/events.jsonl``). The contract's names and units below are this test's own statement,
written apart from the module, so a name the module reads differently is a red row here rather
than a silent agreement.

The two event logs under ``recorded_runs`` were recorded from the loop over its fakes (two
electrical modules and integration): in ``finished`` integration declared both modules complete
and both completion lines were written; in ``unfinished`` it declared one, so the run ended with
a module never recorded complete.

The others were recorded from the loop over the same fakes with a control module, whose role
owes a person's sign-off (sizing, control, electrical and integration; or the control module and
integration alone, ``_alone``); each session's stream path is cut to the run's own ``/run``. In a
run that records decisions, none is taken on the sign-off item: ``records_a_sign_off_owed`` and
``records_a_sign_off_owed_alone`` end escalated with only the sign-off open, and
``records_a_sign_off_owed_and_a_failed_call`` with the system-scope call failed as well;
``records_a_sign_off_owed_and_a_call_failed_under_observe`` with it failed under ``observe``, so
integration ran and merged declaring nothing;
``records_a_sign_off_owed_and_integration_escalated`` with the call passed and integration's own
subtask escalated, every one of its attempts declaring the control module and refused. In a run
that acts, ``acts_waiting_on_a_sign_off`` waits for the person before the integration call,
``acts_signed`` is the same run once the person approved, and ``acts_rejected_a_sign_off_owed``
ended escalated after the person rejected the item and then the fix's item.
"""

from __future__ import annotations

import errno
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
_RECORDED = Path(__file__).resolve().parent / "recorded_runs"

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
    "output_data_rate": (208, "Hz"),
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


def _events(run: Path, recorded: str = "finished") -> None:
    """The run's event log, one of the recorded runs'."""
    (run / "events.jsonl").write_bytes((_RECORDED / f"{recorded}.jsonl").read_bytes())


def _run(tmp_path: Path, *nodes: dict[str, Any], recorded: str = "finished") -> Path:
    """A run directory whose canonical store holds ``nodes``, each written by its owner."""
    run = Path(os.path.realpath(tmp_path)) / "run"
    (run / "store").mkdir(parents=True)
    _events(run, recorded)
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
    _events(run)
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
    # The same value in another unit, and another value in the same unit: each alone.
    [(0.8, "1"), (0.75, "%")],
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


def test_a_disagreement_on_a_name_no_whole_structure_reads_is_listed_and_does_not_refuse(
    tmp_path: Path,
) -> None:
    controller, parameters = _split(FEEDBACK, PARAMETERS)
    one = _node("firmware.native_a", {"angle_response": (11, "1")}, owner="firmware")
    two = _node("firmware.native_b", {"angle_response": (12, "1")}, owner="firmware")
    run = _run(tmp_path, controller, parameters, one, two)
    record, out = _export(run, tmp_path)
    assert record.status == "exported"
    assert record.structure == "state_feedback"
    assert record.conflicts == {"angle_response": ("firmware.native_a", "firmware.native_b")}
    assert "angle_response" not in json.loads(out.read_bytes())["controller"]


def test_a_disagreement_on_a_setting_is_ambiguous(tmp_path: Path) -> None:
    controller, parameters = _split(FEEDBACK, PARAMETERS)
    other = _node("drivetrain.motor", {"pwm_frequency": (10000, "Hz")}, owner="sizing")
    run = _run(tmp_path, controller, parameters, other)
    record, out = _export(run, tmp_path)
    assert record.status == "ambiguous"
    assert record.conflicts == {"pwm_frequency": ("drivetrain.motor", "firmware.loop_timing")}
    assert not out.exists()


def test_a_disagreement_on_an_optional_name_the_chosen_structure_reads_is_ambiguous(
    tmp_path: Path,
) -> None:
    controller, parameters = _split({**RISING, **DECAY}, PARAMETERS)
    other = _node("firmware.leak", {"angle_decay_per_update": (0.998, "1")}, owner="firmware")
    run = _run(tmp_path, controller, parameters, other)
    record, out = _export(run, tmp_path)
    assert record.status == "ambiguous"
    assert set(record.conflicts) == {"angle_decay_per_update"}
    assert not out.exists()


def test_a_disagreement_on_a_name_of_a_structure_otherwise_whole_is_ambiguous(
    tmp_path: Path,
) -> None:
    # Without the disagreement both structures would be whole, so which one the firmware
    # runs would be in doubt; the export must not resolve it by dropping the conflicted name.
    controller, parameters = _split({**FEEDBACK, **NATIVE}, {**PARAMETERS, **SENSITIVITY})
    other = _node("firmware.native_b", {"angle_response": (12, "1")}, owner="firmware")
    run = _run(tmp_path, controller, parameters, other)
    record, out = _export(run, tmp_path)
    assert record.status == "ambiguous"
    assert record.conflicts == {"angle_response": ("balance.controller", "firmware.native_b")}
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
    _events(run)
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


def test_a_run_that_did_not_record_every_module_complete_is_no_answer(tmp_path: Path) -> None:
    # The graph alone would export; the run ended with a module never recorded complete, so
    # its graph may hold a change no merge kept.
    run = _run(tmp_path, *_split(FEEDBACK, PARAMETERS), recorded="unfinished")
    record, out = _export(run, tmp_path)
    assert record.status == "unfinished"
    assert record.sha256 is None
    assert not out.exists()


def test_a_finished_run_names_no_sign_off_owed(tmp_path: Path) -> None:
    run = _run(tmp_path, *_split(FEEDBACK, PARAMETERS))
    record, _ = _export(run, tmp_path)
    assert record.status == "exported"
    assert record.sign_offs_owed == ()


@pytest.mark.parametrize("recorded", ["records_a_sign_off_owed", "records_a_sign_off_owed_alone"])
def test_a_run_that_records_decisions_ends_a_module_whose_sign_off_is_owed_and_is_exported(
    tmp_path: Path, recorded: str
) -> None:
    # No decision is taken in such a run, so a control module that merged ends with its sign-off
    # owed and the run ends escalated; every other precondition held. Its answer is exported,
    # and the record names the module whose sign-off a person still owes.
    run = _run(tmp_path, *_split(FEEDBACK, PARAMETERS), recorded=recorded)
    record, out = _export(run, tmp_path)
    assert record.status == "exported"
    assert record.sign_offs_owed == ("c1",)
    assert record.sha256 == hashlib.sha256(out.read_bytes()).hexdigest()


def test_a_run_whose_modules_owe_a_sign_off_each_names_all_of_them_in_plan_order(
    tmp_path: Path,
) -> None:
    # Two control modules merged and neither is signed; the electrical module is complete. The
    # run ended escalated with only the two sign-offs open: both are named, c1 before c3.
    run = _run(tmp_path, *_split(FEEDBACK, PARAMETERS), recorded="records_two_sign_offs_owed")
    record, out = _export(run, tmp_path)
    assert record.status == "exported"
    assert record.sign_offs_owed == ("c1", "c3")
    assert json.loads(_record_of(out).read_text())["sign_offs_owed"] == ["c1", "c3"]


def test_a_module_owing_a_sign_off_is_named_alone_beside_the_modules_that_are_complete(
    tmp_path: Path,
) -> None:
    # Sizing's module and the electrical one ended complete; only the control module owes.
    run = _run(tmp_path, *_split(FEEDBACK, PARAMETERS), recorded="records_a_sign_off_owed")
    record, _ = _export(run, tmp_path)
    assert record.status == "exported"
    assert record.sign_offs_owed == ("c1",)


@pytest.mark.parametrize(
    "recorded",
    [
        # Waiting before the integration call for a person to decide.
        "acts_waiting_on_a_sign_off",
        # Ended escalated after the person's rejects: no one signed.
        "acts_rejected_a_sign_off_owed",
    ],
)
def test_a_run_that_acts_is_unfinished_while_a_sign_off_is_owed(
    tmp_path: Path, recorded: str
) -> None:
    run = _run(tmp_path, *_split(FEEDBACK, PARAMETERS), recorded=recorded)
    record, out = _export(run, tmp_path)
    assert record.status == "unfinished"
    assert record.sign_offs_owed == ()
    assert not out.exists()


def test_a_run_that_acts_is_exported_once_a_person_signed(tmp_path: Path) -> None:
    run = _run(tmp_path, *_split(FEEDBACK, PARAMETERS), recorded="acts_signed")
    record, _ = _export(run, tmp_path)
    assert record.status == "exported"
    assert record.sign_offs_owed == ()


@pytest.mark.parametrize(
    "recorded",
    [
        # The system-scope call failed under ``on``: integration's subtask never ran.
        "records_a_sign_off_owed_and_a_failed_call",
        # It failed under ``observe``: integration ran and merged, declaring nothing.
        "records_a_sign_off_owed_and_a_call_failed_under_observe",
    ],
)
def test_a_module_whose_sign_off_is_owed_with_another_precondition_open_is_unfinished(
    tmp_path: Path, recorded: str
) -> None:
    """A guard: the check that a module owes its sign-off alone refused both runs already.

    The export's reading of what is owed (the open preconditions being the sign-off and nothing
    else) turned these away before the record existed; the row keeps it so.
    """
    # The run records decisions, and the system-scope call failed: the control module's
    # sign-off is owed, and so is a passing call. It did not end only for want of a signature.
    run = _run(tmp_path, *_split(FEEDBACK, PARAMETERS), recorded=recorded)
    record, out = _export(run, tmp_path)
    assert record.status == "unfinished"
    assert record.sign_offs_owed == ()
    assert not out.exists()


def _record_of(out: Path) -> Path:
    """Where the export's record of an answer at ``out`` is: beside it, named after it."""
    return out.parent / f"{out.name}.record.json"


def test_the_record_beside_the_answer_names_each_sign_off_owed_and_the_answer_s_digest(
    tmp_path: Path,
) -> None:
    # The scorer reads the answer alone, and the answer of a run that ended owing a sign-off is
    # byte for byte the answer of a signed one: the record beside it is where that shows.
    run = _run(tmp_path, *_split(FEEDBACK, PARAMETERS), recorded="records_a_sign_off_owed")
    record, out = _export(run, tmp_path)
    assert record.status == "exported"
    assert sorted(p.name for p in out.parent.iterdir()) == sorted([out.name, _record_of(out).name])
    written = json.loads(_record_of(out).read_bytes())
    assert written["answer"] == out.name
    assert written["answer_sha256"] == hashlib.sha256(out.read_bytes()).hexdigest()
    assert written["status"] == "exported"
    assert written["structure"] == "state_feedback"
    assert written["taken_from"] == {k: list(v) for k, v in record.taken_from.items()}
    assert written["taken_from"]["update_rate"] == ["firmware.loop_timing"]
    assert written["left_out"] == list(record.left_out)
    assert written["sign_offs_owed"] == ["c1"]
    said = written["sign_off"]
    assert isinstance(said, str), said
    assert "sign_offs_owed" in said
    assert "no person" in said.lower()
    assert "raw agent" in said


def test_the_record_of_a_run_that_owes_no_sign_off_says_none_is_owed(tmp_path: Path) -> None:
    run = _run(tmp_path, *_split(FEEDBACK, PARAMETERS), recorded="acts_signed")
    _, out = _export(run, tmp_path)
    written = json.loads(_record_of(out).read_bytes())
    assert written["sign_offs_owed"] == []
    assert written["sign_off"] is None
    assert written["answer_sha256"] == hashlib.sha256(out.read_bytes()).hexdigest()


@pytest.mark.parametrize(
    "recorded",
    ["unfinished", "acts_waiting_on_a_sign_off", "records_a_sign_off_owed_and_a_failed_call"],
)
def test_an_export_that_is_not_exported_writes_no_record(tmp_path: Path, recorded: str) -> None:
    """A guard, not a row that fails without the record: the answer's own refusal came first.

    A run that is not finished is refused before anything is written, so no file of either kind
    was ever put down; this holds that to the record as well, now that there is one.
    """
    run = _run(tmp_path, *_split(FEEDBACK, PARAMETERS), recorded=recorded)
    record, out = _export(run, tmp_path)
    assert record.status == "unfinished"
    assert not out.parent.exists() or list(out.parent.iterdir()) == []


def test_an_ambiguous_graph_writes_no_record(tmp_path: Path) -> None:
    other = _node("drivetrain.motor", {"command_limit": (0.5, "1")}, owner="sizing")
    run = _run(tmp_path, *_split(FEEDBACK, PARAMETERS), other)
    record, out = _export(run, tmp_path)
    assert record.status == "ambiguous"
    assert not out.parent.exists() or list(out.parent.iterdir()) == []


@pytest.mark.parametrize("left", ["file", "link", "directory"])
def test_the_record_is_never_written_over_or_through_what_is_at_its_name_nor_the_answer(
    tmp_path: Path, left: str
) -> None:
    run = _run(tmp_path, *_split(FEEDBACK, PARAMETERS))
    out = Path(os.path.realpath(tmp_path)) / "answers" / "whole_run.json"
    out.parent.mkdir()
    target = Path(os.path.realpath(tmp_path)) / "elsewhere.json"
    target.write_text("untouched")
    at = _record_of(out)
    if left == "file":
        at.write_text("earlier")
    elif left == "link":
        at.symlink_to(target)
    else:
        at.mkdir()
    with pytest.raises(Exception) as caught:  # noqa: PT011
        _module().export_whole_run(run, out)
    assert isinstance(caught.value, _module().ExportError)
    assert target.read_text() == "untouched"
    assert [p.name for p in out.parent.iterdir()] == [at.name]
    if left == "file":
        assert at.read_text() == "earlier"


def test_a_run_whose_integration_did_not_merge_is_unfinished_though_only_a_sign_off_is_open(
    tmp_path: Path,
) -> None:
    # The run records decisions, the call passed, and the control module's only open
    # precondition is its sign-off; but integration declared the module on every attempt, each
    # was refused, and its subtask ended escalated. The run ended without integration's merge,
    # so the graph may hold a change no merge kept.
    recorded = "records_a_sign_off_owed_and_integration_escalated"
    run = _run(tmp_path, *_split(FEEDBACK, PARAMETERS), recorded=recorded)
    record, out = _export(run, tmp_path)
    assert record.status == "unfinished"
    assert record.sign_offs_owed == ()
    assert not out.parent.exists() or list(out.parent.iterdir()) == []


def test_a_run_that_records_decisions_and_halted_after_integration_merged_is_unfinished(
    tmp_path: Path,
) -> None:
    """A guard: a run that did not end escalated was already refused as unfinished.

    The next step of a halted run is not the escalated end, which the reading of what is owed
    requires; this holds the halt after a merge to that, whatever else the record owes.
    """
    # Integration merged and the control module owes only its sign-off, but the run then halted
    # on an incident: it did not end escalated, and a person looks before anything is read off it.
    run = _run(tmp_path, *_split(FEEDBACK, PARAMETERS))
    raw = (_RECORDED / "records_a_sign_off_owed_alone.jsonl").read_bytes()
    last = json.loads(raw.splitlines()[-1])
    envelope = {k: last[k] for k in ("run_id", "gate_mode")} | {"ts": last["ts"]}
    incident = envelope | {
        "seq": last["seq"] + 1,
        "kind": "incident",
        "subtask_id": None,
        "cause": "foreign_journal_line",
        "detail": "a journal line no merge wrote",
    }
    halted = envelope | {
        "seq": last["seq"] + 2,
        "kind": "halted",
        "reason": "incident",
        "detail": "foreign_journal_line",
    }
    extra = b"".join(json.dumps(line).encode() + b"\n" for line in (incident, halted))
    (run / "events.jsonl").write_bytes(raw + extra)
    record, out = _export(run, tmp_path)
    assert record.status == "unfinished"
    assert record.sign_offs_owed == ()
    assert not out.parent.exists() or list(out.parent.iterdir()) == []


def test_a_run_that_records_decisions_and_has_not_ended_is_unfinished(tmp_path: Path) -> None:
    # The control module's only open precondition is its sign-off, but integration's own
    # attempt has not merged yet: the graph may hold a change no merge kept.
    run = _run(tmp_path, *_split(FEEDBACK, PARAMETERS))
    lines = (_RECORDED / "records_a_sign_off_owed_alone.jsonl").read_bytes().splitlines(True)
    call = next(n for n, line in enumerate(lines) if b'"kind":"integration_gate_ran"' in line)
    (run / "events.jsonl").write_bytes(b"".join(lines[: call + 1]))
    record, out = _export(run, tmp_path)
    assert record.status == "unfinished"
    assert not out.exists()


def test_a_run_with_no_event_log_is_refused_not_scored(tmp_path: Path) -> None:
    run = _run(tmp_path, *_split(FEEDBACK, PARAMETERS))
    (run / "events.jsonl").unlink()
    with pytest.raises(Exception) as caught:  # noqa: PT011
        _export(run, tmp_path)
    assert isinstance(caught.value, _module().ExportError)
    assert "event log" in str(caught.value)


def test_a_run_whose_event_log_no_run_could_have_written_is_refused(tmp_path: Path) -> None:
    run = _run(tmp_path, *_split(FEEDBACK, PARAMETERS))
    log = run / "events.jsonl"
    log.write_bytes(log.read_bytes() + b'{"seq": 0}\n')
    with pytest.raises(Exception) as caught:  # noqa: PT011
        _export(run, tmp_path)
    assert isinstance(caught.value, _module().ExportError)
    assert "event log" in str(caught.value)


def _tree(root: Path) -> list[tuple[str, bool, int, bytes, int]]:
    """Every entry under ``root``: its path, whether a directory, size, bytes and mtime."""
    rows = []
    for path in sorted(root.rglob("*")):
        info = path.lstat()
        body = b"" if path.is_dir() else path.read_bytes()
        rows.append(
            (str(path.relative_to(root)), path.is_dir(), info.st_size, body, info.st_mtime_ns)
        )
    return rows


def test_the_run_directory_is_left_byte_for_byte_as_it_was(tmp_path: Path) -> None:
    # A torn last line and a stray file are what opening a store would repair and move aside.
    run = _run(tmp_path, *_split(FEEDBACK, PARAMETERS))
    journal = run / "store" / "journal.jsonl"
    journal.write_bytes(journal.read_bytes() + b'{"rev": 3, "op": "wri')
    (run / "store" / "stray.json").write_text("{}")
    before = _tree(run)
    record, _ = _export(run, tmp_path)
    assert record.status == "exported"
    assert _tree(run) == before


def test_a_place_the_answer_cannot_be_made_is_an_export_error(tmp_path: Path) -> None:
    run = _run(tmp_path, *_split(FEEDBACK, PARAMETERS))
    blocker = Path(os.path.realpath(tmp_path)) / "blocker"
    blocker.write_text("a file, not a directory")
    with pytest.raises(Exception) as caught:  # noqa: PT011
        _module().export_whole_run(run, blocker / "answers" / "whole_run.json")
    assert isinstance(caught.value, _module().ExportError)


@pytest.mark.parametrize("inside", ["store", "run", "nested"])
def test_the_answer_is_never_written_inside_the_run_it_was_exported_from(
    tmp_path: Path, inside: str
) -> None:
    run = _run(tmp_path, *_split(FEEDBACK, PARAMETERS))
    out = {
        "store": run / "store" / "whole_run.json",
        "run": run / "whole_run.json",
        "nested": run / "answers" / "whole_run.json",
    }[inside]
    before = _tree(run)
    with pytest.raises(Exception) as caught:  # noqa: PT011
        _module().export_whole_run(run, out)
    assert isinstance(caught.value, _module().ExportError)
    assert _tree(run) == before


def test_a_write_that_fails_leaves_nothing_at_the_answer_s_name_or_beside_it(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    run = _run(tmp_path, *_split(FEEDBACK, PARAMETERS))
    out = Path(os.path.realpath(tmp_path)) / "answers" / "whole_run.json"
    out.parent.mkdir()

    def half_then_full_disk(fd: int, raw: bytes) -> None:
        os.write(fd, raw[: len(raw) // 2])
        raise OSError(errno.ENOSPC, os.strerror(errno.ENOSPC))

    module = _module()
    monkeypatch.setattr(module, "_write_all", half_then_full_disk, raising=False)
    with pytest.raises(Exception) as caught:  # noqa: PT011
        module.export_whole_run(run, out)
    assert isinstance(caught.value, module.ExportError)
    assert list(out.parent.iterdir()) == []
    monkeypatch.undo()
    record = module.export_whole_run(run, out)
    assert record.status == "exported"
    assert record.sha256 == hashlib.sha256(out.read_bytes()).hexdigest()


def test_an_answer_name_taken_while_the_answer_is_written_is_left_as_it_was_taken(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    run = _run(tmp_path, *_split(FEEDBACK, PARAMETERS))
    out = Path(os.path.realpath(tmp_path)) / "answers" / "whole_run.json"
    module = _module()
    write_all = module._write_all  # noqa: SLF001 - the write the swap goes beside

    def written_then_swapped(fd: int, raw: bytes) -> None:
        write_all(fd, raw)
        out.unlink()
        out.write_text("theirs")

    monkeypatch.setattr(module, "_write_all", written_then_swapped)
    with pytest.raises(Exception) as caught:  # noqa: PT011
        module.export_whole_run(run, out)
    assert isinstance(caught.value, module.ExportError)
    assert out.read_text() == "theirs"
    assert [p.name for p in out.parent.iterdir()] == ["whole_run.json"]


def test_a_new_name_that_cannot_be_made_leaves_nothing_at_the_answer_s_name(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    run = _run(tmp_path, *_split(FEEDBACK, PARAMETERS))
    out = Path(os.path.realpath(tmp_path)) / "answers" / "whole_run.json"
    module = _module()

    def no_space(*_: object, **__: object) -> tuple[int, str]:
        raise OSError(errno.ENOSPC, os.strerror(errno.ENOSPC))

    monkeypatch.setattr(module.tempfile, "mkstemp", no_space)
    with pytest.raises(Exception) as caught:  # noqa: PT011
        module.export_whole_run(run, out)
    assert isinstance(caught.value, module.ExportError)
    assert list(out.parent.iterdir()) == []


def test_a_process_killed_between_the_two_renames_leaves_a_record_and_never_an_answer_without_one(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    run = _run(tmp_path, *_split(FEEDBACK, PARAMETERS), recorded="records_a_sign_off_owed")
    out = Path(os.path.realpath(tmp_path)) / "answers" / "whole_run.json"
    module = _module()
    replace = os.replace
    beside = module.record_path(out)
    # What stood at the answer's name and at the record's, as each rename was about to be made.
    before: dict[str, tuple[bytes, bytes]] = {}

    def watched(src: str, dst: object) -> None:
        before[str(dst)] = (out.read_bytes(), beside.read_bytes())
        replace(src, dst)  # type: ignore[arg-type]

    monkeypatch.setattr(module.os, "replace", watched)
    module.export_whole_run(run, out)
    # The first rename puts one whole file down; the second finds that one placed. A kill at the
    # second leaves what the first put: it is the record, so an answer is never alone.
    first, second = list(before)
    assert (first, second) == (str(beside), str(out))
    assert before[second][1] != b"" and before[second][0] == b""


def test_an_answer_that_cannot_be_put_in_place_takes_the_record_put_before_it_away(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    # The record is renamed into place first; the answer's rename then fails. A record with no
    # answer is harmless, but neither is left, so the next export is not refused.
    run = _run(tmp_path, *_split(FEEDBACK, PARAMETERS), recorded="records_a_sign_off_owed")
    out = Path(os.path.realpath(tmp_path)) / "answers" / "whole_run.json"
    module = _module()
    replace = os.replace
    renamed: list[str] = []

    def record_then_no_space(src: str, dst: object) -> None:
        if renamed:
            raise OSError(errno.ENOSPC, os.strerror(errno.ENOSPC))
        replace(src, dst)  # type: ignore[arg-type]
        renamed.append(str(dst))

    monkeypatch.setattr(module.os, "replace", record_then_no_space)
    with pytest.raises(Exception) as caught:  # noqa: PT011
        module.export_whole_run(run, out)
    assert isinstance(caught.value, module.ExportError)
    assert renamed == [str(module.record_path(out))]
    assert list(out.parent.iterdir()) == []
    monkeypatch.undo()
    record = module.export_whole_run(run, out)
    assert record.status == "exported"
    assert _record_of(out).exists()


def test_a_temporary_that_cannot_be_removed_after_a_failed_second_rename_stops_nothing_else(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    # The answer's rename fails, and its temporary then cannot be removed either: the export
    # removes what it can (the record it placed, and its claim on the answer's name), and says
    # the answer could not be written, not that a temporary could not be removed.
    run = _run(tmp_path, *_split(FEEDBACK, PARAMETERS), recorded="records_a_sign_off_owed")
    out = Path(os.path.realpath(tmp_path)) / "answers" / "whole_run.json"
    module = _module()
    replace, unlink = os.replace, os.unlink
    renamed: list[str] = []

    def record_then_no_space(src: str, dst: object) -> None:
        if renamed:
            raise OSError(errno.ENOSPC, os.strerror(errno.ENOSPC))
        replace(src, dst)  # type: ignore[arg-type]
        renamed.append(str(dst))

    def stubborn(path: str) -> None:
        if Path(path).name.startswith(f".{out.name}."):
            raise PermissionError(errno.EPERM, os.strerror(errno.EPERM))
        unlink(path)

    monkeypatch.setattr(module.os, "replace", record_then_no_space)
    monkeypatch.setattr(module.os, "unlink", stubborn)
    with pytest.raises(module.ExportError):
        module.export_whole_run(run, out)
    left = sorted(p.name for p in out.parent.iterdir())
    assert not out.exists() and not module.record_path(out).exists(), left
    assert all(name.startswith(f".{out.name}.") for name in left), left


def test_an_event_log_that_is_a_directory_is_an_export_error_not_a_raw_one(tmp_path: Path) -> None:
    run = _run(tmp_path, *_split(FEEDBACK, PARAMETERS))
    (run / "events.jsonl").unlink()
    (run / "events.jsonl").mkdir()
    with pytest.raises(Exception) as caught:  # noqa: PT011
        _export(run, tmp_path)
    assert isinstance(caught.value, _module().ExportError)
    assert "event log" in str(caught.value)


def test_an_answer_reached_through_a_name_the_filesystem_sees_as_the_run_is_never_written(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    # A path whose spelling differs from the run's, yet is the run's own directory on disk: a
    # link here, the same directory in another case on a case-insensitive filesystem. The
    # spelling the filesystem resolves it to is not what decides; the directory itself is.
    run = _run(tmp_path, *_split(FEEDBACK, PARAMETERS))
    elsewhere = Path(os.path.realpath(tmp_path)) / "elsewhere"
    elsewhere.symlink_to(run, target_is_directory=True)
    module = _module()
    monkeypatch.setattr(module.os.path, "realpath", lambda p, **_: os.path.abspath(p))
    before = _tree(run)
    with pytest.raises(module.ExportError):
        module.export_whole_run(run, elsewhere / "answers" / "whole_run.json")
    assert _tree(run) == before


def test_an_answer_named_in_another_case_inside_the_run_is_never_written_there(
    tmp_path: Path,
) -> None:
    run = _run(tmp_path, *_split(FEEDBACK, PARAMETERS))
    shouted = run.with_name(run.name.upper())
    if not shouted.exists():
        pytest.skip("this filesystem tells one case from another")
    before = _tree(run)
    with pytest.raises(Exception) as caught:  # noqa: PT011
        _module().export_whole_run(run, shouted / "answers" / "whole_run.json")
    assert isinstance(caught.value, _module().ExportError)
    assert _tree(run) == before


def test_a_sibling_directory_whose_name_starts_with_the_run_s_is_not_inside_it(
    tmp_path: Path,
) -> None:
    run = _run(tmp_path, *_split(FEEDBACK, PARAMETERS))
    record, out = _export(run, tmp_path)
    assert record.status == "exported"
    sibling = run.with_name(run.name + "_answers") / "whole_run.json"
    other = _module().export_whole_run(run, sibling)
    assert other.status == "exported"
    assert sibling.exists()


def test_the_files_an_export_puts_down_are_readable_as_a_plain_file_is(tmp_path: Path) -> None:
    run = _run(tmp_path, *_split(FEEDBACK, PARAMETERS))
    previous = os.umask(0o022)
    try:
        _, out = _export(run, tmp_path)
    finally:
        os.umask(previous)
    assert out.stat().st_mode & 0o777 == 0o644
    assert _record_of(out).stat().st_mode & 0o777 == 0o644


def test_a_name_left_by_an_earlier_write_that_was_killed_is_refused_with_what_to_remove(
    tmp_path: Path,
) -> None:
    run = _run(tmp_path, *_split(FEEDBACK, PARAMETERS))
    out = Path(os.path.realpath(tmp_path)) / "answers" / "whole_run.json"
    out.parent.mkdir()
    out.write_bytes(b"")
    with pytest.raises(Exception) as caught:  # noqa: PT011
        _module().export_whole_run(run, out)
    assert isinstance(caught.value, _module().ExportError)
    message = str(caught.value)
    assert "killed" in message and "temporary" in message
