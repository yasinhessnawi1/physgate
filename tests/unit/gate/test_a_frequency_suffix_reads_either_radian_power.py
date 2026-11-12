"""A name ending in ``_frequency`` is read at either power of the radian.

"Frequency" names both f, in hertz, and the angular frequency omega, in radians per second, in
control and vibration alike: run 4 wrote ``tilt_mode_natural_frequency`` as 13.885 rad/s, and the
suffix read it as a hertz figure written wrong (gate seq 271). The suffix now reads the
dimension 1/s at either radian power, and keeps the frequency's sign: neither f nor omega is
negative. The dimension is still read, so a ``_frequency`` in metres is still recorded.

Only the suffix reading widens. A catalogued name keeps its kind's one radian power and is
refused when it is written in the other: ``sample_rate`` and ``update_rate`` are hertz, and
``gain_crossover_frequency`` is radians per second.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest
from gate_fixtures import graph, node

from physgate.gate import check_units
from physgate.gate.bounds_table import load_bounds
from physgate.gate.catalogue import KINDS, kind_of
from physgate.gate.context import CheckContext
from physgate.gate.graph import GraphView
from physgate.orchestrator.protocols import UncheckedDetails

NODE = "control.balance"


def _units(tmp_path: Path, name: str, value: float, unit: str) -> Any:
    graph(tmp_path / "g", node(NODE, domain="control", quantities={name: (value, unit)}))
    view = GraphView.read(tmp_path / "g", base_revision=0)
    try:
        return check_units.run(CheckContext(view=view, scope="subtask", bounds=load_bounds()))
    except Exception as exc:  # noqa: BLE001 - a crash is the finding
        # At a64e805f, pint_message cannot print a refusal whose unit has a power other than
        # one (rad/s**2), so the unit check raises instead of recording.
        pytest.fail(f"the unit check raised on {name} = {value} {unit}: {type(exc).__name__}")


def _mismatches(ran: Any, name: str) -> list[str]:
    return [
        o.message
        for o in ran.observations
        if isinstance(o.details, UncheckedDetails)
        and o.details.quantities == (name,)
        and "refuses nothing" in o.message
    ]


@pytest.mark.parametrize(
    ("name", "value", "unit"),
    [
        ("tilt_mode_natural_frequency", 13.885, "rad/s"),
        ("notch_frequency", 314.16, "rad/s"),
        ("notch_frequency", 50, "Hz"),
        ("notch_frequency", 50, "1/s"),
        ("pwm_frequency", 20000, "Hz"),
        # a qualifier, then the suffix
        ("tilt_mode_natural_frequency_nominal", 13.9, "rad/s"),
        ("pwm_frequency_max", 20, "kHz"),
    ],
)
def test_a_frequency_at_either_radian_power_is_read_without_a_mismatch(
    tmp_path: Path, name: str, value: float, unit: str
) -> None:
    ran = _units(tmp_path, name, value, unit)
    assert not any(o.outcome == "fail" for o in ran.observations)
    assert _mismatches(ran, name) == []
    # It is read, not merely parsed: the kind is the suffix's.
    assert kind_of(name) is KINDS["frequency"]


@pytest.mark.parametrize(("value", "unit"), [(3, "m"), (2, "rad"), (5, "rad/s**2"), (1, "s")])
def test_a_frequency_in_another_dimension_is_still_recorded(
    tmp_path: Path, value: float, unit: str
) -> None:
    # Guard.
    ran = _units(tmp_path, "notch_frequency", value, unit)
    assert not any(o.outcome == "fail" for o in ran.observations)
    assert len(_mismatches(ran, "notch_frequency")) == 1


@pytest.mark.parametrize(("value", "unit"), [(-50, "Hz"), (-5, "rad/s")])
def test_a_negative_frequency_at_either_radian_power_is_recorded_as_one(
    tmp_path: Path, value: float, unit: str
) -> None:
    ran = _units(tmp_path, "notch_frequency", value, unit)
    assert not any(o.outcome == "fail" for o in ran.observations)
    (mismatch,) = _mismatches(ran, "notch_frequency") or [""]
    assert "never negative" in mismatch, mismatch


@pytest.mark.parametrize(
    ("name", "value", "unit", "why"),
    [
        (
            "sample_rate",
            100,
            "rad/s",
            "the radian to the power 0, and 'rad/s' has it to the power 1",
        ),
        (
            "update_rate",
            100,
            "rad/s",
            "the radian to the power 0, and 'rad/s' has it to the power 1",
        ),
        ("sample_rate", -100, "Hz", "a frequency is never negative"),
        ("update_rate", -100, "Hz", "a frequency is never negative"),
        (
            "gain_crossover_frequency",
            2.4,
            "Hz",
            "the radian to the power 1, and 'Hz' has it to the power 0",
        ),
    ],
)
def test_a_catalogued_name_keeps_its_one_radian_power_and_its_sign(
    tmp_path: Path, name: str, value: float, unit: str, why: str
) -> None:
    ran = _units(tmp_path, name, value, unit)
    assert [o.outcome for o in ran.observations] == ["fail"]
    # Refused for its reason: the radian's power or the sign, not another.
    assert name in ran.observations[0].message and why in ran.observations[0].message, (
        ran.observations[0].message
    )


@pytest.mark.parametrize(
    ("name", "value", "unit"),
    [
        # another suffix of the frequency kind: a sensor's output data rate is in hertz
        ("gyro_output_data_rate", 208, "rad/s"),
        # a catalogued frequency name with a qualifier keeps the name's one power
        ("sample_rate_max", 100, "rad/s"),
        ("update_rate_nominal", 100, "rad/s"),
    ],
)
def test_only_a_frequency_suffix_reads_either_power(
    tmp_path: Path, name: str, value: float, unit: str
) -> None:
    ran = _units(tmp_path, name, value, unit)
    assert kind_of(name) is KINDS["frequency"]
    assert not any(o.outcome == "fail" for o in ran.observations)
    (mismatch,) = _mismatches(ran, name) or [""]
    assert "the radian to the power 0, and 'rad/s' has it to the power 1" in mismatch, mismatch
