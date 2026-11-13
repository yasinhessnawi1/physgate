"""The whole-run answer is held to its schema whole, and a refusal is always a format error.

The unit tables below are this test's own statement of the contract, written apart from the
module, so a unit changed in the module is a red row here rather than a silent agreement.
"""

from __future__ import annotations

import copy
import json
import math
import os
import re
import threading
import tracemalloc
from collections.abc import Callable
from pathlib import Path
from typing import Any

import pytest

from physgate.evaluation.per_role.exceptions import TaskFormatError
from physgate.evaluation.tiers.base import Measure
from physgate.evaluation.whole import answer as contract
from physgate.evaluation.whole.answer import (
    MAX_ANSWER_BYTES,
    MAX_FILES,
    MAX_MAGNITUDE,
    IncrementalRisingOffset,
    Parameters,
    StateFeedback,
    WholeRun,
    parse_whole_run,
    read_whole_run,
)

#: The longest delay, in s: half a second, far past any delay a balancing loop survives.
MAX_DELAY = 0.5
DELAY_UNITS = {"sensor_delay": "s", "compute_delay": "s"}
LOOP_UNITS = {"period": "s", "command_limit": "1", **DELAY_UNITS}
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
#: The reference kit's balancing example as its code writes it: integers in the code's own
#: scalings (angle in millidegrees, rate in deg/s, travel in encoder counts, command in PWM
#: counts), with the two times in ms and the gyro's divisor in raw counts per deg/s.
NATIVE_UNITS = {
    **DELAY_UNITS,
    "update_time": "ms",
    "motor_speed_limit": "count",
    "angle_rate_ratio": "ms",
    "angle_response": "1",
    "distance_response": "1",
    "speed_response": "1",
    "response_divisor": "1",
    "gear_ratio_coefficient": "1",
    "gyro_divisor": "count*s/deg",
    "angle_decay_numerator": "1",
    "angle_decay_denominator": "1",
}
#: The native fields that are the code's integers, each held to a whole number.
NATIVE_WHOLE = [f for f in NATIVE_UNITS if f not in DELAY_UNITS]
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
        "sensor_delay": _m(0.0048, "s"),
        "compute_delay": _m(0.002, "s"),
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


def native() -> dict[str, Any]:
    return {
        "structure": "native_incremental_rising_offset",
        "sensor_delay": _m(0.0048, "s"),
        "compute_delay": _m(0.002, "s"),
        "update_time": _m(10, "ms"),
        "motor_speed_limit": _m(300, "count"),
        "angle_rate_ratio": _m(140, "ms"),
        "angle_response": _m(11, "1"),
        "distance_response": _m(73, "1"),
        "speed_response": _m(3300, "1"),
        "response_divisor": _m(100, "1"),
        "gear_ratio_coefficient": _m(111, "1"),
        "gyro_divisor": _m(29, "count*s/deg"),
        "angle_decay_numerator": _m(999, "1"),
        "angle_decay_denominator": _m(1000, "1"),
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
        "version": 2,
        "controller": rising(),
        "parameters": parameters(),
        "files": ["firmware/src/main.cpp"],
    }
    doc.update(over)
    return doc


def native_answer(**over: Any) -> dict[str, Any]:
    """An answer whose firmware controller is written natively, with the gyro's sensitivity."""
    doc = answer(controller=native(), **over)
    doc["parameters"]["gyro_sensitivity"] = _m(28.571, "count*s/deg")
    return doc


def _parse(doc: dict[str, Any]) -> WholeRun:
    return parse_whole_run(json.dumps(doc).encode())


def _taken(doc: dict[str, Any]) -> WholeRun:
    """The answer read; a refusal is a failed assertion that names the reason."""
    read = _raised(_parse, doc)
    assert read is None, f"refused: {read}"
    return _parse(doc)


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


def _raised(call: Callable[[Any], object], argument: Any) -> BaseException | None:
    """What ``call(argument)`` raised, of any type, so a wrong type is a failed assertion."""
    try:
        call(argument)
    except Exception as exc:  # caught whole, so the row can assert which type it was
        return exc
    return None


def _wrong_unit(unit: str) -> str:
    return "s" if unit == "1" else "1"


def test_an_answer_with_the_incremental_rising_offset_controller_is_read_with_every_unit() -> None:
    read = _taken(answer())
    assert isinstance(read.controller, IncrementalRisingOffset)
    assert read.controller.rate_ratio == Measure(value=0.14, unit="s")
    assert read.controller.speed_gain == Measure(value=0.9, unit="s/m")
    assert read.controller.compute_delay == Measure(value=0.002, unit="s")
    assert read.parameters.encoder_counts_per_wheel_revolution == Measure(value=1322.9, unit="1")
    assert read.parameters.gyro_full_scale == Measure(value=1000, unit="deg/s")
    assert read.analysed_controller is None
    assert read.files == ("firmware/src/main.cpp",)


def test_an_answer_with_a_discrete_state_feedback_is_read_as_that_structure() -> None:
    read = _taken(answer(controller=feedback()))
    assert isinstance(read.controller, StateFeedback)
    assert read.controller.rate_gain == Measure(value=0.5, unit="s/rad")


def test_the_analysed_controller_is_kept_beside_the_one_the_firmware_runs() -> None:
    read = _taken(answer(analysed_controller=feedback()))
    assert isinstance(read.controller, IncrementalRisingOffset)
    assert isinstance(read.analysed_controller, StateFeedback)


def test_an_answer_names_no_files_when_it_has_none_to_name() -> None:
    assert getattr(_taken(_without(answer(), ("files",))), "files", None) == ()


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
    assert _taken(answer(controller=controller)).controller is not None
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
    read = _taken(_with(answer(), ("controller", "command_limit"), _m(value, "1")))
    assert isinstance(read.controller, IncrementalRisingOffset)
    assert read.controller.command_limit.value == value


def test_the_delay_bound_is_half_a_second() -> None:
    assert getattr(contract, "MAX_DELAY_SECONDS", None) == MAX_DELAY


@pytest.mark.parametrize("make", [answer, native_answer], ids=["si", "native"])
@pytest.mark.parametrize("field", list(DELAY_UNITS))
@pytest.mark.parametrize("value", [-0.001, math.nextafter(MAX_DELAY, math.inf), 1])
def test_a_delay_is_a_time_from_zero_to_its_bound(
    make: Callable[[], dict[str, Any]], field: str, value: float
) -> None:
    caught = _raised(_parse, _with(make(), ("controller", field), _m(value, "s")))
    assert isinstance(caught, TaskFormatError), repr(caught)
    assert "delay" in str(caught), str(caught)


@pytest.mark.parametrize("make", [answer, native_answer], ids=["si", "native"])
@pytest.mark.parametrize("field", list(DELAY_UNITS))
@pytest.mark.parametrize("value", [0, 0.0048, 0.01, 0.0125, MAX_DELAY])
def test_a_delay_of_any_time_up_to_the_bound_is_taken_sub_sample_included(
    make: Callable[[], dict[str, Any]], field: str, value: float
) -> None:
    read = _taken(_with(make(), ("controller", field), _m(value, "s")))
    assert getattr(read.controller, field) == Measure(value=value, unit="s")


@pytest.mark.parametrize("field", list(DELAY_UNITS))
def test_a_delay_in_samples_is_refused(field: str) -> None:
    caught = _raised(_parse, _with(answer(), ("controller", field), _m(1, "1")))
    assert isinstance(caught, TaskFormatError), repr(caught)
    assert "'s'" in str(caught), str(caught)


@pytest.mark.parametrize("value", [400.5, 0.5])
def test_the_pwm_full_scale_is_a_whole_count(value: float) -> None:
    with pytest.raises(TaskFormatError, match="whole"):
        _parse(_with(answer(), ("parameters", "pwm_full_scale"), _m(value, "1")))


def test_a_pwm_full_scale_written_as_a_whole_float_is_taken() -> None:
    read = _taken(_with(answer(), ("parameters", "pwm_full_scale"), _m(400.0, "1")))
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
    assert _taken(answer(files=files)).files == tuple(files)


@pytest.mark.parametrize(
    "files",
    [
        ["firmware/Main.c", "firmware/main.c"],
        ["firmware/main.c", "firmware/Main.c"],
        ["firmware/main.c", "firmware/main.c"],
    ],
    ids=["upper_first", "lower_first", "exact"],
)
def test_a_file_named_twice_however_it_is_cased_is_refused(files: list[str]) -> None:
    with pytest.raises(TaskFormatError, match="twice"):
        _parse(answer(files=files))


def test_more_files_than_the_bound_are_refused_and_the_bound_itself_is_taken() -> None:
    names = [f"f{i}.c" for i in range(MAX_FILES + 1)]
    with pytest.raises(TaskFormatError):
        _parse(answer(files=names))
    assert len(_taken(answer(files=names[:MAX_FILES])).files) == MAX_FILES


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("form", "lti_tf"),
        ("form", "Whole_Run"),
        ("version", 1),
        ("version", 3),
        ("version", True),
        ("version", "2"),
    ],
)
def test_the_form_and_its_version_are_named_exactly(field: str, value: object) -> None:
    with pytest.raises(TaskFormatError):
        _parse(answer(**{field: value}))


def _root(tmp_path: Path) -> Path:
    """The test's root as the filesystem spells it: the reader follows no link at all."""
    root = Path(os.path.realpath(tmp_path)) / "answers"
    root.mkdir()
    return root


def _reading(path: Path, root: Path) -> WholeRun | BaseException:
    """The answer read, or what reading it raised, of any type."""
    try:
        return read_whole_run(path, root=root)
    except Exception as exc:  # caught whole, so the row can assert which type it was
        return exc


def _refused(path: Path, root: Path, says: str) -> None:
    caught = _reading(path, root)
    assert isinstance(caught, TaskFormatError), repr(caught)
    assert says in str(caught), str(caught)


def test_a_good_answer_on_disk_is_read(tmp_path: Path) -> None:
    root = _root(tmp_path)
    (root / "run").mkdir()
    target = root / "run" / "whole_run.json"
    target.write_text(json.dumps(answer()))
    read = _reading(target, root)
    assert isinstance(read, WholeRun), repr(read)
    assert isinstance(read.controller, IncrementalRisingOffset)


def test_reading_refuses_a_missing_file_a_link_a_directory_and_an_oversized_file(
    tmp_path: Path,
) -> None:
    root = _root(tmp_path)
    good = root / "good.json"
    good.write_text(json.dumps(answer()))
    link = root / "link.json"
    link.symlink_to(good)
    folder = root / "folder.json"
    folder.mkdir()
    large = root / "large.json"
    large.write_text(json.dumps(answer()) + " " * MAX_ANSWER_BYTES)
    for path in (root / "missing.json", link, folder, root):
        _refused(path, root, "no answer file")
    _refused(large, root, "larger")


def test_an_answer_reached_through_a_linked_directory_is_refused(tmp_path: Path) -> None:
    root = _root(tmp_path)
    real = root / "real"
    real.mkdir()
    (real / "whole_run.json").write_text(json.dumps(answer()))
    (root / "linked").symlink_to(real, target_is_directory=True)
    assert isinstance(_reading(real / "whole_run.json", root), WholeRun)
    _refused(root / "linked" / "whole_run.json", root, "no answer file")


def test_an_answer_with_a_second_name_is_refused(tmp_path: Path) -> None:
    # A hard link is a second name the file can be changed or read through, from outside the
    # directory the answer was looked for in.
    root = _root(tmp_path)
    outside = Path(os.path.realpath(tmp_path)) / "outside.json"
    outside.write_text(json.dumps(answer()))
    os.link(outside, root / "whole_run.json")
    _refused(root / "whole_run.json", root, "second name")


def test_an_answer_outside_its_root_or_spelt_round_about_is_refused(tmp_path: Path) -> None:
    root = _root(tmp_path)
    outside = Path(os.path.realpath(tmp_path)) / "whole_run.json"
    outside.write_text(json.dumps(answer()))
    (root / "run").mkdir()
    (root / "run" / "whole_run.json").write_text(json.dumps(answer()))
    _refused(outside, root, "no answer file")
    _refused(root / "run" / ".." / ".." / "whole_run.json", root, "no answer file")
    _refused(root / "run" / ".." / "run" / "whole_run.json", root, "no answer file")
    _refused(Path("run") / "whole_run.json", root, "no answer file")


def test_a_fifo_is_refused_without_waiting_for_a_writer(tmp_path: Path) -> None:
    root = _root(tmp_path)
    fifo = root / "whole_run.json"
    os.mkfifo(fifo)
    outcome: list[WholeRun | BaseException] = []
    reader = threading.Thread(target=lambda: outcome.append(_reading(fifo, root)), daemon=True)
    reader.start()
    reader.join(timeout=5)
    try:
        assert not reader.is_alive(), "the reader is waiting for a writer to open the FIFO"
    finally:
        if reader.is_alive():
            # Release the blocked open, so the row ends instead of hanging the run.
            os.close(os.open(fifo, os.O_WRONLY | os.O_NONBLOCK))
            reader.join(timeout=5)
    caught = outcome[0]
    assert isinstance(caught, TaskFormatError), repr(caught)
    assert "no answer file" in str(caught)


def test_an_oversized_answer_is_refused_before_it_is_read_into_memory(tmp_path: Path) -> None:
    root = _root(tmp_path)
    huge = root / "whole_run.json"
    with huge.open("wb") as handle:
        handle.truncate(64 * 1024 * 1024)
    tracemalloc.start()
    try:
        caught = _reading(huge, root)
        _, peak = tracemalloc.get_traced_memory()
    finally:
        tracemalloc.stop()
    assert isinstance(caught, TaskFormatError), repr(caught)
    assert "larger" in str(caught)
    assert peak < 4 * MAX_ANSWER_BYTES, peak


def test_a_file_that_grows_after_its_size_is_taken_is_read_no_further_than_the_bound(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    root = _root(tmp_path)
    grown = root / "whole_run.json"
    with grown.open("wb") as handle:
        handle.truncate(64 * 1024 * 1024)
    real_fstat = os.fstat

    def small(fd: int) -> os.stat_result:
        found = list(real_fstat(fd))
        found[6] = 10  # st_size, as it was before the file grew
        return os.stat_result(found)

    monkeypatch.setattr(os, "fstat", small)
    tracemalloc.start()
    try:
        caught = _reading(grown, root)
        _, peak = tracemalloc.get_traced_memory()
    finally:
        tracemalloc.stop()
    monkeypatch.undo()
    assert isinstance(caught, TaskFormatError), repr(caught)
    assert "larger" in str(caught)
    assert peak < 4 * MAX_ANSWER_BYTES, peak


def test_the_bytes_read_are_the_file_opened_whatever_the_path_names_afterwards(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    root = _root(tmp_path)
    target = root / "whole_run.json"
    target.write_text(json.dumps(answer()))
    swapped = root / "swapped.json"
    swapped.write_text(json.dumps(answer(controller=feedback())))
    real_fstat = os.fstat
    calls: list[int] = []

    def swap_after(fd: int) -> os.stat_result:
        found = real_fstat(fd)
        if not calls:
            os.replace(swapped, target)
        calls.append(fd)
        return found

    monkeypatch.setattr(os, "fstat", swap_after)
    read = _reading(target, root)
    monkeypatch.undo()
    assert calls, "the reader took no size from its descriptor"
    assert isinstance(read, WholeRun), repr(read)
    assert isinstance(read.controller, IncrementalRisingOffset)


_EVERY_MEASURE = [("controller", f) for f in RISING_UNITS] + [
    ("parameters", f) for f in PARAMETER_UNITS
]


@pytest.mark.parametrize("path", _EVERY_MEASURE, ids=["/".join(p) for p in _EVERY_MEASURE])
def test_a_value_too_large_for_a_float_is_a_refused_answer_never_a_crash(
    path: tuple[str, ...],
) -> None:
    doc = answer()
    unit = doc[path[0]][path[1]]["unit"]
    caught = _raised(parse_whole_run, json.dumps(_with(doc, path, _m(10**400, unit))).encode())
    assert isinstance(caught, TaskFormatError), repr(caught)


@pytest.mark.parametrize(
    "path",
    [
        ("controller", "angle_gain"),
        ("controller", "rate_ratio"),
        ("controller", "speed_gain"),
        ("parameters", "pwm_frequency"),
        ("parameters", "encoder_counts_per_wheel_revolution"),
    ],
)
def test_a_value_beyond_the_magnitude_bound_is_refused_and_the_bound_itself_is_taken(
    path: tuple[str, ...],
) -> None:
    doc = answer()
    unit = doc[path[0]][path[1]]["unit"]
    assert _taken(_with(doc, path, _m(MAX_MAGNITUDE, unit))) is not None
    for value in (math.nextafter(MAX_MAGNITUDE, math.inf), 10 * MAX_MAGNITUDE):
        with pytest.raises(TaskFormatError, match="magnitude"):
            _parse(_with(doc, path, _m(value, unit)))
    if path[0] == "controller":
        assert _taken(_with(doc, path, _m(-MAX_MAGNITUDE, unit))) is not None
        with pytest.raises(TaskFormatError, match="magnitude"):
            _parse(_with(doc, path, _m(-10 * MAX_MAGNITUDE, unit)))


@pytest.mark.parametrize("token", ["NaN", "Infinity", "-Infinity", "1e400"])
def test_nan_and_infinity_are_named_in_the_refusal(token: str) -> None:
    text = json.dumps(answer()).replace('"value": 0.3', '"value": ' + token)
    assert token in text
    caught = _raised(parse_whole_run, text.encode())
    assert isinstance(caught, TaskFormatError), repr(caught)
    assert "nan or inf" in str(caught), str(caught)


def test_bytes_past_the_size_bound_are_refused_and_the_bound_itself_is_taken() -> None:
    good = json.dumps(answer()).encode()
    at_bound = good + b" " * (MAX_ANSWER_BYTES - len(good))
    assert len(at_bound) == MAX_ANSWER_BYTES
    assert isinstance(_raised(parse_whole_run, at_bound) or parse_whole_run(at_bound), WholeRun)
    caught = _raised(parse_whole_run, at_bound + b" ")
    assert isinstance(caught, TaskFormatError), repr(caught)
    assert "larger" in str(caught)


@pytest.mark.parametrize(
    "raw",
    [b"\xff\xfe{}", b"{", b"[]", b"null", b"", json.dumps(answer()).encode() + b"\x00"],
    ids=["not_utf8", "cut", "list", "null", "empty", "nul"],
)
def test_bytes_that_are_not_an_answer_are_a_refused_answer_never_another_error(
    raw: bytes,
) -> None:
    caught = _raised(parse_whole_run, raw)
    assert isinstance(caught, TaskFormatError), repr(caught)


# The amendment of 13.11: the code's own integer form, the angle's leak, delays as a time.


def test_the_native_structure_is_read_with_every_field_in_its_own_unit() -> None:
    read = _taken(native_answer())
    assert type(read.controller).__name__ == "NativeRisingOffset"
    for field, unit in NATIVE_UNITS.items():
        assert getattr(read.controller, field).unit == unit, field
    assert getattr(read.controller, "speed_response", None) == Measure(value=3300, unit="1")
    assert getattr(read.controller, "gyro_divisor", None) == Measure(value=29, unit="count*s/deg")
    assert getattr(read.parameters, "gyro_sensitivity", None) == Measure(
        value=28.571, unit="count*s/deg"
    )


def test_a_native_controller_may_be_the_analysed_one_beside_a_native_firmware_controller() -> None:
    read = _taken(native_answer(analysed_controller=native()))
    assert type(read.analysed_controller).__name__ == "NativeRisingOffset"


@pytest.mark.parametrize(("field", "unit"), list(NATIVE_UNITS.items()))
def test_each_native_field_is_held_to_its_own_unit(field: str, unit: str) -> None:
    doc = native_answer()
    _taken(doc)
    wrong = "1" if unit != "1" else "count"
    doc["controller"][field]["unit"] = wrong
    caught = _raised(_parse, doc)
    assert isinstance(caught, TaskFormatError), repr(caught)
    assert repr(unit) in str(caught), str(caught)


@pytest.mark.parametrize("field", list(NATIVE_UNITS))
def test_a_missing_native_field_is_refused(field: str) -> None:
    caught = _raised(_parse, _without(native_answer(), ("controller", field)))
    assert isinstance(caught, TaskFormatError), repr(caught)


@pytest.mark.parametrize("field", NATIVE_WHOLE)
def test_each_native_integer_is_a_whole_number(field: str) -> None:
    doc = native_answer()
    value = doc["controller"][field]["value"]
    caught = _raised(_parse, _with(doc, ("controller", field, "value"), value + 0.5))
    assert isinstance(caught, TaskFormatError), repr(caught)
    assert "whole" in str(caught), str(caught)
    assert _taken(_with(doc, ("controller", field, "value"), float(value))) is not None


_NATIVE_POSITIVE = [
    "update_time",
    "motor_speed_limit",
    "response_divisor",
    "gear_ratio_coefficient",
    "gyro_divisor",
    "angle_decay_numerator",
    "angle_decay_denominator",
]


@pytest.mark.parametrize("field", _NATIVE_POSITIVE)
@pytest.mark.parametrize("value", [0, -1])
def test_a_native_time_limit_divisor_or_decay_term_is_positive(field: str, value: int) -> None:
    caught = _raised(_parse, _with(native_answer(), ("controller", field, "value"), value))
    assert isinstance(caught, TaskFormatError), repr(caught)
    assert "positive" in str(caught), str(caught)


@pytest.mark.parametrize("field", ["angle_response", "distance_response", "speed_response"])
@pytest.mark.parametrize("value", [0, -11])
def test_a_native_response_may_be_zero_or_negative(field: str, value: int) -> None:
    read = _taken(_with(native_answer(), ("controller", field, "value"), value))
    assert getattr(read.controller, field).value == value


def test_the_native_rate_ratio_may_be_zero_but_not_negative() -> None:
    assert _taken(_with(native_answer(), ("controller", "angle_rate_ratio", "value"), 0))
    caught = _raised(
        _parse, _with(native_answer(), ("controller", "angle_rate_ratio", "value"), -1)
    )
    assert isinstance(caught, TaskFormatError), repr(caught)


def test_the_native_decay_never_grows_the_angle() -> None:
    doc = _with(native_answer(), ("controller", "angle_decay_numerator", "value"), 1001)
    caught = _raised(_parse, doc)
    assert isinstance(caught, TaskFormatError), repr(caught)
    assert "decay" in str(caught), str(caught)
    same = _with(native_answer(), ("controller", "angle_decay_numerator", "value"), 1000)
    assert _taken(same) is not None


@pytest.mark.parametrize("limit", [401, 1000])
def test_the_native_speed_limit_is_at_most_the_pwm_full_scale(limit: int) -> None:
    caught = _raised(
        _parse, _with(native_answer(), ("controller", "motor_speed_limit", "value"), limit)
    )
    assert isinstance(caught, TaskFormatError), repr(caught)
    assert "full scale" in str(caught), str(caught)
    assert _taken(_with(native_answer(), ("controller", "motor_speed_limit", "value"), 400))


@pytest.mark.parametrize("where", ["controller", "analysed_controller"])
def test_a_native_controller_without_the_gyro_s_stated_sensitivity_is_refused(where: str) -> None:
    doc = answer(**{where: native()})
    caught = _raised(_parse, doc)
    assert isinstance(caught, TaskFormatError), repr(caught)
    assert "sensitivity" in str(caught), str(caught)


def test_the_gyro_s_sensitivity_is_optional_when_no_controller_is_native() -> None:
    assert getattr(_taken(answer()).parameters, "gyro_sensitivity", "absent") is None
    doc = answer()
    doc["parameters"]["gyro_sensitivity"] = _m(28.571, "count*s/deg")
    assert getattr(_taken(doc).parameters, "gyro_sensitivity", None) == Measure(
        value=28.571, unit="count*s/deg"
    )


@pytest.mark.parametrize(
    "measure",
    [_m(28.571, "1"), _m(0, "count*s/deg"), _m(-28.571, "count*s/deg"), _m(1e13, "count*s/deg")],
    ids=["unit", "zero", "negative", "magnitude"],
)
def test_the_gyro_s_sensitivity_is_positive_in_counts_per_degree_per_second(
    measure: dict[str, object],
) -> None:
    doc = native_answer()
    doc["parameters"]["gyro_sensitivity"] = measure
    caught = _raised(_parse, doc)
    assert isinstance(caught, TaskFormatError), repr(caught)


def test_the_angle_decay_is_optional_on_the_incremental_structure_and_absent_by_default() -> None:
    assert getattr(_taken(answer()).controller, "angle_decay_per_update", "absent") is None
    doc = _with(answer(), ("controller", "angle_decay_per_update"), _m(0.999, "1"))
    assert getattr(_taken(doc).controller, "angle_decay_per_update", None) == Measure(
        value=0.999, unit="1"
    )


@pytest.mark.parametrize(
    "measure",
    [_m(0, "1"), _m(-0.5, "1"), _m(1.001, "1"), _m(0.999, "1/s")],
    ids=["zero", "negative", "growing", "unit"],
)
def test_the_angle_decay_is_a_factor_above_zero_and_at_most_one(measure: dict[str, object]) -> None:
    caught = _raised(_parse, _with(answer(), ("controller", "angle_decay_per_update"), measure))
    assert isinstance(caught, TaskFormatError), repr(caught)
    assert "decay" in str(caught), str(caught)
    assert _taken(_with(answer(), ("controller", "angle_decay_per_update"), _m(1, "1")))


def test_a_state_feedback_has_no_angle_decay() -> None:
    doc = _with(
        answer(controller=feedback()), ("controller", "angle_decay_per_update"), _m(0.999, "1")
    )
    caught = _raised(_parse, doc)
    assert isinstance(caught, TaskFormatError), repr(caught)


def test_the_incremental_structure_states_the_leak_s_continuous_time_meaning() -> None:
    doc = IncrementalRisingOffset.__doc__ or ""
    assert "high-pass" in doc and "τ_L" in doc, doc


@pytest.mark.parametrize("field", NATIVE_WHOLE)
def test_a_native_value_too_large_for_a_float_is_a_refused_answer(field: str) -> None:
    doc = native_answer()
    unit = doc["controller"][field]["unit"]
    caught = _raised(
        parse_whole_run, json.dumps(_with(doc, ("controller", field), _m(10**400, unit))).encode()
    )
    assert isinstance(caught, TaskFormatError), repr(caught)
