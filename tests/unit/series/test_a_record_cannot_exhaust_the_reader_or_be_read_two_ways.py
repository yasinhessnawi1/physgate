"""A record cannot cost more than its bounds say, and what is validated is what is returned.

Two findings of a review of the record format, each pinned here:

- **Cost.** A unit's length did not bound what parsing it costs: the unit registry evaluates
  arithmetic in a unit string exactly, so a short exponent tower ran until a CPU limit killed
  the process. Units are now held to a spelling with no numbers but small exponents before
  the registry sees them. The test stubs the registry out, so on code without the check it
  fails at once instead of spending the time.
- **Two readings.** The bytes were checked by one JSON parser and validated by another, so
  the two could disagree; and JSON's unbounded integers let an input through that no float
  can hold. A record is now parsed once, and that one reading is validated and returned.

Every input here is inert: a short string or number, never a run of anything.
"""

from __future__ import annotations

import json
import random
import struct
from typing import Any

import pytest
from series_fixture import encode, record_dict

from physgate.gate import units
from physgate.series import record as record_module
from physgate.series.exceptions import RecordRefusedError
from physgate.series.record import MAX_DEPTH, MAX_INPUT_INTEGER, parse_record


@pytest.mark.parametrize(
    "unit", ["10**10**10*m", "m**(10**9)", "1e308*m", "1000*m", "m*2", "(m)", "m**999"]
)
def test_a_unit_holding_arithmetic_is_refused_before_the_registry_evaluates_it(
    unit: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    real_parse = units.parse
    reached: list[str] = []

    def parse_unless_it_is_the_one(value: float | int, spelled: str) -> Any:
        # Only the unit under test is kept from the registry; the record's other units
        # (its axis in seconds, its inputs) are parsed as usual.
        if spelled == unit:
            reached.append(spelled)
            msg = "the unit reached the registry"
            raise RuntimeError(msg)
        return real_parse(value, spelled)

    monkeypatch.setattr(units, "parse", parse_unless_it_is_the_one)
    record = record_dict()
    record["traces"][0]["unit"] = unit
    with pytest.raises(RecordRefusedError, match="named units with small integer powers"):
        parse_record(encode(record))
    assert reached == []


@pytest.mark.parametrize(
    "unit", ["s", "m", "rad/s", "1/s", "kg*m/s**2", "m**-1", "delta_degC", "V / A", "count"]
)
def test_the_units_a_simulation_carries_are_still_admitted(unit: str) -> None:
    record = record_dict()
    record["traces"][0]["unit"] = unit
    assert parse_record(encode(record)).traces[0].unit == unit


def test_an_integer_input_beyond_any_float_is_refused() -> None:
    record = record_dict()
    record["inputs"]["seed"] = {"value": 10**400, "unit": "dimensionless"}
    with pytest.raises(RecordRefusedError, match="integer input is at most"):
        parse_record(encode(record))


def test_a_64_bit_seed_is_still_an_input() -> None:
    record = record_dict()
    record["inputs"]["seed"] = {"value": MAX_INPUT_INTEGER, "unit": "dimensionless"}
    assert parse_record(encode(record)).inputs["seed"].value == MAX_INPUT_INTEGER


def test_an_integer_sample_beyond_any_float_is_refused() -> None:
    record = record_dict()
    record["traces"][0]["values"][3] = 10**400
    with pytest.raises(RecordRefusedError, match=r"traces\.0\.values\.3"):
        parse_record(encode(record))


def test_a_lone_surrogate_one_parser_accepts_is_refused_for_both() -> None:
    record = record_dict(title="\ud800 fixture")
    data = json.dumps(record).encode()
    assert json.loads(data)["title"].startswith("\ud800")
    with pytest.raises(RecordRefusedError, match="lone surrogate"):
        parse_record(data)


def test_a_record_nested_deeper_than_its_format_is_refused() -> None:
    record = record_dict()
    nested: Any = 1
    for _ in range(MAX_DEPTH + 2):
        nested = [nested]
    record["inputs"]["seed"]["value"] = nested
    with pytest.raises(RecordRefusedError, match="nests at most"):
        parse_record(encode(record))


def test_a_repeated_key_inside_a_nested_object_is_refused() -> None:
    text = encode(record_dict()).decode()
    marker = '"path": "modules/control/controller.py"'
    repeated = text.replace(marker, f'{marker}, "path": "/tmp/elsewhere.py"', 1)
    assert repeated != text
    with pytest.raises(RecordRefusedError, match="appears twice"):
        parse_record(repeated.encode())


def test_the_bytes_are_parsed_once_and_never_validated_by_a_second_parser(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def second_parser(*_: object, **__: object) -> Any:
        msg = "a record's bytes were handed to a second JSON parser"
        raise AssertionError(msg)

    monkeypatch.setattr(record_module.Record, "model_validate_json", second_parser)
    assert parse_record(encode(record_dict())).id == "step_nominal"


def _bits(value: float) -> bytes:
    return struct.pack("<d", value)


def test_every_sample_is_returned_exactly_as_the_one_parse_read_it() -> None:
    rng = random.Random(16102026)
    edges = [0.0, -0.0, 5e-324, -5e-324, 2.2250738585072014e-308, 1.7976931348623157e308, 0.1]
    samples = edges + [rng.uniform(-1e6, 1e6) for _ in range(1_000)]
    samples += [rng.choice([-1, 1]) * 10 ** rng.uniform(-300, 300) for _ in range(1_000)]
    samples += [rng.randrange(-(2**60), 2**60) for _ in range(200)]
    record = record_dict()
    record["x"]["values"] = [float(n) for n in range(len(samples))]
    record["traces"] = [{"name": "position", "unit": "m", "values": samples}]
    data = encode(record)
    read = parse_record(data).traces[0].values
    plain = json.loads(data)["traces"][0]["values"]
    assert len(read) == len(plain) == len(samples) == 2_207
    assert [_bits(v) for v in read] == [_bits(float(v)) for v in plain]
    assert record_module.MAX_DEPTH == MAX_DEPTH
