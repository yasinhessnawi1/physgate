"""The whole-run answer is held to its schema whole, and a refusal is always a format error.

The unit tables below are this test's own statement of the contract, written apart from the
module, so a unit changed in the module is a red row here rather than a silent agreement.
"""

from __future__ import annotations

import copy
import json
import re
from pathlib import Path
from typing import Any

import pytest

from physgate.evaluation.per_role.exceptions import TaskFormatError
from physgate.evaluation.tiers.base import Measure
from physgate.evaluation.whole.answer import (
    MAX_ANSWER_BYTES,
    MAX_DELAY_SAMPLES,
    MAX_FILES,
    IncrementalRisingOffset,
    Parameters,
    StateFeedback,
    WholeRun,
    parse_whole_run,
    read_whole_run,
)

LOOP_UNITS = {"period": "s", "command_limit": "1", "sensor_delay": "1", "compute_delay": "1"}
RISING_UNITS = {
    **LOOP_UNITS,
    "rate_ratio": "s",
    "angle_gain": "1/rad",
    "distance_gain": "1/m",
    "speed_gain": "s/m",
}
FEEDBACK_UNITS = {
    **LOOP_UNITS,
    "angle_gain": "1/rad",
    "rate_gain": "s/rad",
    "distance_gain": "1/m",
    "speed_gain": "s/m",
}
PARAMETER_UNITS = {
    "update_rate": "Hz",
    "gyro_output_data_rate": "Hz",
    "gyro_full_scale": "deg/s",
    "pwm_frequency": "Hz",
    "pwm_full_scale": "1",
    "encoder_counts_per_wheel_revolution": "1",
}


def _m(value: object, unit: str) -> dict[str, object]:
    return {"value": value, "unit": unit}


def _loop() -> dict[str, Any]:
    return {
        "period": _m(0.01, "s"),
        "command_limit": _m(0.75, "1"),
        "sensor_delay": _m(0, "1"),
        "compute_delay": _m(1, "1"),
    }


def rising() -> dict[str, Any]:
    return {
        "structure": "incremental_rising_offset",
        **_loop(),
        "rate_ratio": _m(0.14, "s"),
        "angle_gain": _m(0.3, "1/rad"),
        "distance_gain": _m(2.0, "1/m"),
        "speed_gain": _m(0.9, "s/m"),
    }


def feedback() -> dict[str, Any]:
    return {
        "structure": "state_feedback",
        **_loop(),
        "angle_gain": _m(4.0, "1/rad"),
        "rate_gain": _m(0.5, "s/rad"),
        "distance_gain": _m(1.0, "1/m"),
        "speed_gain": _m(1.5, "s/m"),
    }


def parameters() -> dict[str, Any]:
    return {
        "update_rate": _m(100, "Hz"),
        "gyro_output_data_rate": _m(208, "Hz"),
        "gyro_full_scale": _m(1000, "deg/s"),
        "pwm_frequency": _m(20000, "Hz"),
        "pwm_full_scale": _m(400, "1"),
        "encoder_counts_per_wheel_revolution": _m(1322.9, "1"),
    }


def answer(**over: Any) -> dict[str, Any]:
    doc: dict[str, Any] = {
        "form": "whole_run",
        "version": 1,
        "controller": rising(),
        "parameters": parameters(),
        "files": ["firmware/src/main.cpp"],
    }
    doc.update(over)
    return doc


def _parse(doc: dict[str, Any]) -> WholeRun:
    return parse_whole_run(json.dumps(doc).encode())


def _with(doc: dict[str, Any], path: tuple[str, ...], value: object) -> dict[str, Any]:
    out = copy.deepcopy(doc)
    node = out
    for key in path[:-1]:
        node = node[key]
    node[path[-1]] = value
    return out


def _without(doc: dict[str, Any], path: tuple[str, ...]) -> dict[str, Any]:
    out = copy.deepcopy(doc)
    node = out
    for key in path[:-1]:
        node = node[key]
    del node[path[-1]]
    return out


def _wrong_unit(unit: str) -> str:
    return "s" if unit == "1" else "1"


def test_an_answer_with_the_incremental_rising_offset_controller_is_read_with_every_unit() -> None:
    read = _parse(answer())
    assert isinstance(read.controller, IncrementalRisingOffset)
    assert read.controller.rate_ratio == Measure(value=0.14, unit="s")
    assert read.controller.speed_gain == Measure(value=0.9, unit="s/m")
    assert read.controller.compute_delay == Measure(value=1, unit="1")
    assert read.parameters.encoder_counts_per_wheel_revolution == Measure(value=1322.9, unit="1")
    assert read.parameters.gyro_full_scale == Measure(value=1000, unit="deg/s")
    assert read.analysed_controller is None
    assert read.files == ("firmware/src/main.cpp",)


def test_an_answer_with_a_discrete_state_feedback_is_read_as_that_structure() -> None:
    read = _parse(answer(controller=feedback()))
    assert isinstance(read.controller, StateFeedback)
    assert read.controller.rate_gain == Measure(value=0.5, unit="s/rad")


def test_the_analysed_controller_is_kept_beside_the_one_the_firmware_runs() -> None:
    read = _parse(answer(analysed_controller=feedback()))
    assert isinstance(read.controller, IncrementalRisingOffset)
    assert isinstance(read.analysed_controller, StateFeedback)


def test_an_answer_names_no_files_when_it_has_none_to_name() -> None:
    assert getattr(_parse(_without(answer(), ("files",))), "files", None) == ()


_MEASURE_PATHS = [
    ("controller", "angle_gain"),
    ("controller", "period"),
    ("controller", "compute_delay"),
    ("parameters", "update_rate"),
    ("parameters", "pwm_full_scale"),
]


@pytest.mark.parametrize("path", _MEASURE_PATHS, ids=["/".join(p) for p in _MEASURE_PATHS])
@pytest.mark.parametrize("value", [2.0, 2], ids=["float", "int"])
def test_a_bare_number_where_a_measure_belongs_is_refused(
    path: tuple[str, ...], value: object
) -> None:
    with pytest.raises(TaskFormatError):
        _parse(_with(answer(), path, value))


@pytest.mark.parametrize("value", ["0.3", True, None], ids=["string", "boolean", "null"])
def test_a_value_that_is_not_a_number_is_refused_even_with_its_unit(value: object) -> None:
    with pytest.raises(TaskFormatError):
        _parse(_with(answer(), ("controller", "angle_gain"), _m(value, "1/rad")))


@pytest.mark.parametrize("token", ["NaN", "Infinity", "-Infinity"])
def test_nan_and_infinity_are_not_numbers_here(token: str) -> None:
    text = json.dumps(answer()).replace('"value": 0.3', '"value": ' + token)
    assert token in text
    with pytest.raises(TaskFormatError):
        parse_whole_run(text.encode())


@pytest.mark.parametrize(
    ("structure", "field", "unit"),
    [("rising", f, u) for f, u in RISING_UNITS.items()]
    + [("feedback", f, u) for f, u in FEEDBACK_UNITS.items()],
)
def test_each_gain_period_limit_and_delay_is_held_to_its_own_unit(
    structure: str, field: str, unit: str
) -> None:
    controller = rising() if structure == "rising" else feedback()
    assert _parse(answer(controller=controller)).controller is not None
    controller[field] = _m(controller[field]["value"], _wrong_unit(unit))
    with pytest.raises(TaskFormatError, match=re.escape(repr(unit))):
        _parse(answer(controller=controller))


@pytest.mark.parametrize(("field", "unit"), list(PARAMETER_UNITS.items()))
def test_each_parameter_is_held_to_its_own_unit(field: str, unit: str) -> None:
    doc = answer()
    doc["parameters"][field]["unit"] = _wrong_unit(unit)
    with pytest.raises(TaskFormatError, match=re.escape(repr(unit))):
        _parse(doc)


_REQUIRED = (
    [("form",), ("version",), ("controller",), ("parameters",)]
    + [("controller", f) for f in [*RISING_UNITS, "structure"]]
    + [("parameters", f) for f in PARAMETER_UNITS]
    + [("controller", "angle_gain", "unit"), ("controller", "angle_gain", "value")]
)


@pytest.mark.parametrize("path", _REQUIRED, ids=["/".join(p) for p in _REQUIRED])
def test_a_missing_field_is_refused(path: tuple[str, ...]) -> None:
    with pytest.raises(TaskFormatError):
        _parse(_without(answer(), path))


@pytest.mark.parametrize("field", list(FEEDBACK_UNITS))
def test_a_missing_field_of_a_state_feedback_is_refused(field: str) -> None:
    with pytest.raises(TaskFormatError):
        _parse(_without(answer(controller=feedback()), ("controller", field)))


_EXTRA = [
    ("note",),
    ("controller", "note"),
    ("parameters", "note"),
    ("controller", "angle_gain", "source"),
]


@pytest.mark.parametrize("path", _EXTRA, ids=["/".join(p) for p in _EXTRA])
def test_an_unknown_field_is_refused_at_every_level(path: tuple[str, ...]) -> None:
    with pytest.raises(TaskFormatError):
        _parse(_with(answer(), path, "x"))


def test_a_gain_of_the_other_structure_is_refused() -> None:
    with pytest.raises(TaskFormatError):
        _parse(_with(answer(), ("controller", "rate_gain"), _m(0.5, "s/rad")))
    with pytest.raises(TaskFormatError):
        _parse(_with(answer(controller=feedback()), ("controller", "rate_ratio"), _m(0.14, "s")))


@pytest.mark.parametrize("structure", ["pid", "lti_tf", "", "Incremental_Rising_Offset"])
def test_a_structure_off_the_closed_list_is_refused(structure: str) -> None:
    with pytest.raises(TaskFormatError):
        _parse(_with(answer(), ("controller", "structure"), structure))


_POSITIVE = [
    (("controller", "period"), "s"),
    (("parameters", "update_rate"), "Hz"),
    (("parameters", "gyro_output_data_rate"), "Hz"),
    (("parameters", "gyro_full_scale"), "deg/s"),
    (("parameters", "pwm_frequency"), "Hz"),
    (("parameters", "pwm_full_scale"), "1"),
    (("parameters", "encoder_counts_per_wheel_revolution"), "1"),
]


@pytest.mark.parametrize(("path", "unit"), _POSITIVE, ids=["/".join(p) for p, _ in _POSITIVE])
@pytest.mark.parametrize("value", [0, -1.0])
def test_the_period_and_every_rate_scale_and_count_are_positive(
    path: tuple[str, ...], unit: str, value: float
) -> None:
    with pytest.raises(TaskFormatError, match="positive"):
        _parse(_with(answer(), path, _m(value, unit)))


@pytest.mark.parametrize("value", [0, -0.5, 1.2])
def test_the_command_limit_is_a_duty_above_zero_and_at_most_one(value: float) -> None:
    with pytest.raises(TaskFormatError, match="duty"):
        _parse(_with(answer(), ("controller", "command_limit"), _m(value, "1")))


@pytest.mark.parametrize("value", [1, 1.0, 0.75])
def test_a_command_limit_of_a_duty_up_to_one_is_taken(value: float) -> None:
    read = _parse(_with(answer(), ("controller", "command_limit"), _m(value, "1")))
    assert isinstance(read.controller, IncrementalRisingOffset)
    assert read.controller.command_limit.value == value


@pytest.mark.parametrize("field", ["sensor_delay", "compute_delay"])
@pytest.mark.parametrize("value", [1.5, -1, MAX_DELAY_SAMPLES + 1])
def test_a_delay_is_a_whole_number_of_samples_within_its_bound(field: str, value: float) -> None:
    with pytest.raises(TaskFormatError, match="samples"):
        _parse(_with(answer(), ("controller", field), _m(value, "1")))


@pytest.mark.parametrize("field", ["sensor_delay", "compute_delay"])
@pytest.mark.parametrize("value", [0, 2.0, MAX_DELAY_SAMPLES])
def test_a_delay_of_whole_samples_up_to_the_bound_is_taken(field: str, value: float) -> None:
    read = _parse(_with(answer(), ("controller", field), _m(value, "1")))
    assert isinstance(read.controller, IncrementalRisingOffset)
    assert getattr(read.controller, field).value == value


@pytest.mark.parametrize("value", [400.5, 0.5])
def test_the_pwm_full_scale_is_a_whole_count(value: float) -> None:
    with pytest.raises(TaskFormatError, match="whole"):
        _parse(_with(answer(), ("parameters", "pwm_full_scale"), _m(value, "1")))


def test_a_pwm_full_scale_written_as_a_whole_float_is_taken() -> None:
    read = _parse(_with(answer(), ("parameters", "pwm_full_scale"), _m(400.0, "1")))
    assert isinstance(read.parameters, Parameters)
    assert read.parameters.pwm_full_scale.value == 400.0


@pytest.mark.parametrize(
    "path",
    [
        "/etc/passwd",
        "../outside.c",
        "firmware/../../outside.c",
        "firmware//main.c",
        "firmware/./main.c",
        "firmware\\main.c",
        ".git/config",
        "firmware/",
        "",
        "firmware/méin.c",
        "firmware/main.c\n",
        "a/" * 100 + "b",
    ],
    ids=[
        "absolute",
        "parent",
        "parent_inside",
        "empty_part",
        "dot_part",
        "backslash",
        "hidden",
        "trailing_slash",
        "empty",
        "non_ascii",
        "newline",
        "too_long",
    ],
)
def test_a_file_is_named_by_a_path_inside_the_answer_s_directory(path: str) -> None:
    with pytest.raises(TaskFormatError):
        _parse(answer(files=[path]))


def test_files_named_by_plain_relative_paths_are_taken() -> None:
    files = ["firmware/src/main.cpp", "README.md", "control/design_v2.py"]
    assert _parse(answer(files=files)).files == tuple(files)


def test_a_file_named_twice_however_it_is_cased_is_refused() -> None:
    with pytest.raises(TaskFormatError, match="twice"):
        _parse(answer(files=["firmware/Main.c", "firmware/main.c"]))
    with pytest.raises(TaskFormatError, match="twice"):
        _parse(answer(files=["firmware/main.c", "firmware/main.c"]))


def test_more_files_than_the_bound_are_refused_and_the_bound_itself_is_taken() -> None:
    names = [f"f{i}.c" for i in range(MAX_FILES + 1)]
    with pytest.raises(TaskFormatError):
        _parse(answer(files=names))
    assert len(_parse(answer(files=names[:MAX_FILES])).files) == MAX_FILES


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("form", "lti_tf"),
        ("form", "Whole_Run"),
        ("version", 2),
        ("version", True),
        ("version", "1"),
    ],
)
def test_the_form_and_its_version_are_named_exactly(field: str, value: object) -> None:
    with pytest.raises(TaskFormatError):
        _parse(answer(**{field: value}))


def test_a_good_answer_on_disk_is_read(tmp_path: Path) -> None:
    target = tmp_path / "whole_run.json"
    target.write_text(json.dumps(answer()))
    assert isinstance(read_whole_run(target).controller, IncrementalRisingOffset)


def test_reading_refuses_a_missing_file_a_link_a_directory_and_an_oversized_file(
    tmp_path: Path,
) -> None:
    good = tmp_path / "good.json"
    good.write_text(json.dumps(answer()))
    link = tmp_path / "link.json"
    link.symlink_to(good)
    large = tmp_path / "large.json"
    large.write_text(json.dumps(answer()) + " " * MAX_ANSWER_BYTES)
    for path in (tmp_path / "missing.json", link, tmp_path):
        with pytest.raises(TaskFormatError, match="no answer file"):
            read_whole_run(path)
    with pytest.raises(TaskFormatError, match="larger"):
        read_whole_run(large)


@pytest.mark.parametrize(
    "raw",
    [b"\xff\xfe{}", b"{", b"[]", b"null", b"", json.dumps(answer()).encode() + b"\x00"],
    ids=["not_utf8", "cut", "list", "null", "empty", "nul"],
)
def test_bytes_that_are_not_an_answer_are_a_refused_answer_never_another_error(
    raw: bytes,
) -> None:
    with pytest.raises(TaskFormatError):
        parse_whole_run(raw)
