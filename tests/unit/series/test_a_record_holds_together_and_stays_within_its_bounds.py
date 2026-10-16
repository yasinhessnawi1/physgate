"""A series record's axis, traces, names and size are refused when they do not hold together."""

from __future__ import annotations

import json
from typing import Any

import pytest
from series_fixture import encode, frequency_record_dict, record_dict

from physgate.series.exceptions import RecordRefusedError
from physgate.series.record import (
    MAX_FILE_BYTES,
    MAX_INPUTS,
    MAX_SAMPLES,
    MAX_TRACES,
    parse_record,
)


def _refused(record: Any, match: str) -> None:
    with pytest.raises(RecordRefusedError, match=match):
        parse_record(encode(record))


@pytest.mark.parametrize("values", [[0.0, 0.0, 0.02, 0.03], [0.0, 0.02, 0.01, 0.03]])
def test_an_x_axis_that_does_not_strictly_increase_is_refused(values: list[float]) -> None:
    record = record_dict()
    record["x"]["values"] = values
    _refused(record, "strictly increasing")


def test_a_trace_without_one_value_per_x_is_refused() -> None:
    record = record_dict()
    record["traces"][0]["values"] = [0.0, 0.02, 0.05]
    _refused(record, "one value per x")


def test_two_traces_with_one_name_are_refused() -> None:
    record = record_dict()
    record["traces"][1]["name"] = "position"
    _refused(record, "share a name")


@pytest.mark.parametrize("unit", ["m", "dimensionless", "1/s"])
def test_a_time_axis_not_in_time_is_refused(unit: str) -> None:
    record = record_dict()
    record["x"]["unit"] = unit
    _refused(record, "time axis")


@pytest.mark.parametrize("unit", ["s", "rad", "m/s"])
def test_a_frequency_axis_not_in_reciprocal_time_is_refused(unit: str) -> None:
    record = frequency_record_dict()
    record["x"]["unit"] = unit
    _refused(record, "frequency axis")


@pytest.mark.parametrize("unit", ["rad/s", "Hz", "1/s"])
def test_a_frequency_axis_may_be_in_any_reciprocal_time(unit: str) -> None:
    record = frequency_record_dict()
    record["x"]["unit"] = unit
    assert parse_record(encode(record)).x.unit == unit


def test_a_frequency_axis_holds_no_zero_or_negative_frequency() -> None:
    record = frequency_record_dict()
    record["x"]["values"] = [0.0, 1.0, 10.0]
    _refused(record, "positive")


@pytest.mark.parametrize("name", ["Step", "1step", "step-nominal", "step.json", "../x", "s" * 65])
def test_an_id_that_is_not_a_safe_name_is_refused(name: str) -> None:
    _refused(record_dict(id=name), "id")


def test_a_trace_name_and_an_input_name_are_held_to_the_same_pattern() -> None:
    record = record_dict()
    record["traces"][0]["name"] = "Position"
    _refused(record, "traces.0.name")
    record = record_dict()
    record["inputs"]["Seed"] = {"value": 7, "unit": "dimensionless"}
    _refused(record, "inputs")


def test_an_unknown_field_or_another_format_is_refused() -> None:
    _refused(record_dict(extra="x"), "extra")
    _refused(record_dict(format="series.v2"), "format")


@pytest.mark.parametrize("path", ["modules/../etc/passwd", "a\0b", ""])
def test_a_code_path_with_a_parent_step_a_nul_or_nothing_is_refused(path: str) -> None:
    record = record_dict()
    record["producer"]["script"]["path"] = path
    _refused(record, "producer.script.path")


def test_a_record_naming_no_script_is_refused() -> None:
    record = record_dict()
    del record["producer"]["script"]
    _refused(record, "producer.script")
    record = record_dict()
    del record["producer"]
    _refused(record, "producer")


def test_a_repeated_key_is_refused_rather_than_read_as_the_last() -> None:
    text = encode(record_dict()).decode()
    repeated = text.replace('"axis": "time",', '"axis": "time", "axis": "frequency",', 1)
    assert repeated != text
    with pytest.raises(RecordRefusedError, match="appears twice"):
        parse_record(repeated.encode())


@pytest.mark.parametrize(
    "data", [b"\xff\xfe not utf-8", b"[1, 2, 3]", b'{"format": "series.v1"', b"", b"null"]
)
def test_bytes_that_are_not_one_json_object_are_refused(data: bytes) -> None:
    with pytest.raises(RecordRefusedError):
        parse_record(data)


def test_too_many_traces_are_refused() -> None:
    record = record_dict()
    record["traces"] = [
        {"name": f"t{n}", "unit": "m", "values": [0.0, 0.1, 0.2, 0.3]}
        for n in range(MAX_TRACES + 1)
    ]
    _refused(record, "traces")
    record["traces"] = record["traces"][:MAX_TRACES]
    assert len(parse_record(encode(record)).traces) == MAX_TRACES


def test_too_many_samples_are_refused() -> None:
    ints = list(range(MAX_SAMPLES + 1))
    record = record_dict()
    record["x"]["values"] = ints
    record["traces"] = [{"name": "position", "unit": "m", "values": [0] * len(ints)}]
    _refused(record, "x.values")
    record["x"]["values"] = ints[:MAX_SAMPLES]
    record["traces"][0]["values"] = [0] * MAX_SAMPLES
    assert len(parse_record(encode(record)).x.values) == MAX_SAMPLES


def test_too_many_inputs_are_refused() -> None:
    record = record_dict()
    record["inputs"] = {f"i{n}": {"value": n, "unit": "m"} for n in range(MAX_INPUTS + 1)}
    _refused(record, "inputs")


def test_a_file_over_the_byte_bound_is_refused_before_it_is_parsed() -> None:
    data = encode(record_dict())
    padded = data[:-1] + b" " * (MAX_FILE_BYTES - len(data) + 1) + b"}"
    assert len(padded) == MAX_FILE_BYTES + 1
    with pytest.raises(RecordRefusedError, match="at most"):
        parse_record(padded)
    exactly = data[:-1] + b" " * (MAX_FILE_BYTES - len(data)) + b"}"
    assert len(exactly) == MAX_FILE_BYTES
    assert parse_record(exactly).id == "step_nominal"


def test_the_record_round_trips_through_its_own_json() -> None:
    record = parse_record(encode(record_dict()))
    again = parse_record(json.dumps(record.model_dump(mode="json")).encode())
    assert again == record
