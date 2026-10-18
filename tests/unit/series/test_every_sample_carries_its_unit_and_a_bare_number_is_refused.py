"""Every axis of a series record carries a unit, and every sample is a finite number.

The graph's rule, held for simulation output: a bare number is a schema error. Each case
differs from the well-formed record in exactly the thing under test, so a refusal can
only come from that rule.
"""

from __future__ import annotations

from typing import Any

import pytest
from series_fixture import encode, frequency_record_dict, record_dict

from physgate.series.exceptions import RecordRefusedError
from physgate.series.record import FORMAT, Record, parse_record


def _refused(record: Any, match: str) -> None:
    with pytest.raises(RecordRefusedError, match=match):
        parse_record(encode(record))


def test_the_well_formed_records_are_admitted() -> None:
    step = parse_record(encode(record_dict()))
    assert isinstance(step, Record)
    assert step.format == FORMAT
    assert step.traces[1].values[-1] == 0.0  # an integer sample reads as a float
    loop = parse_record(encode(frequency_record_dict()))
    assert loop.axis == "frequency"


def test_a_trace_without_a_unit_is_refused() -> None:
    record = record_dict()
    del record["traces"][0]["unit"]
    _refused(record, "traces.0.unit")


def test_an_axis_without_a_unit_is_refused() -> None:
    record = record_dict()
    del record["x"]["unit"]
    _refused(record, "x.unit")


@pytest.mark.parametrize("unit", ["", " ", "\t"])
def test_an_empty_unit_is_not_a_unit(unit: str) -> None:
    record = record_dict()
    record["traces"][0]["unit"] = unit
    _refused(record, "traces.0.unit")


def test_a_column_of_bare_numbers_is_refused() -> None:
    record = record_dict()
    record["traces"][0] = [0.0, 0.02, 0.05, 0.08]
    _refused(record, "traces.0")


def test_a_sample_written_with_its_own_unit_is_not_this_format() -> None:
    record = record_dict()
    record["traces"][0]["values"] = [{"value": 0.0, "unit": "m"}] * 4
    _refused(record, "traces.0.values.0")


@pytest.mark.parametrize("unit", ["metre_per_bogus", "kg**", "furlongs/fortnight/"])
def test_a_unit_the_gate_cannot_read_is_refused(unit: str) -> None:
    record = record_dict()
    record["traces"][0]["unit"] = unit
    _refused(record, "traces.0.unit")


@pytest.mark.parametrize("unit", ["dB", "dBm", "Np", "decade", "dB*V", "1/dB"])
def test_a_logarithmic_unit_is_refused(unit: str) -> None:
    record = frequency_record_dict()
    record["traces"][0]["unit"] = unit
    _refused(record, "logarithmic")


@pytest.mark.parametrize("token", ["NaN", "Infinity", "-Infinity"])
def test_a_non_finite_constant_is_refused_before_validation(token: str) -> None:
    text = encode(record_dict()).decode().replace("0.05, 0.08]", f"0.05, {token}]", 1)
    assert token in text
    with pytest.raises(RecordRefusedError, match="not a finite number"):
        parse_record(text.encode())


def test_a_literal_that_overflows_to_infinity_is_refused_by_the_schema() -> None:
    text = encode(record_dict()).decode().replace("0.05, 0.08]", "0.05, 1e999]", 1)
    assert "1e999" in text
    with pytest.raises(RecordRefusedError, match="traces.0.values.3"):
        parse_record(text.encode())


@pytest.mark.parametrize("sample", [True, "0.08", None, [0.08]])
def test_a_sample_that_is_not_a_number_is_refused(sample: object) -> None:
    record = record_dict()
    record["traces"][0]["values"][3] = sample
    _refused(record, "traces.0.values.3")


def test_an_input_without_a_unit_is_refused() -> None:
    record = record_dict()
    record["inputs"]["seed"] = 7
    _refused(record, "inputs.seed")
    record = record_dict()
    del record["inputs"]["step"]["unit"]
    _refused(record, "inputs.step.unit")


def test_an_input_that_is_a_boolean_is_refused() -> None:
    record = record_dict()
    record["inputs"]["seed"] = {"value": True, "unit": "dimensionless"}
    _refused(record, "inputs.seed.value")
