"""A value is read off a record by a published extractor, on the record's own samples.

The frequency extractors are held to analytic loops,
``L(s) = K wn^2 / (s (s^2 + 2 zeta wn s + wn^2)) e^(-s tau)``, recorded on a logarithmic grid
of 2,000 points from 0.05 to 314 rad/s: a crossing-based value (phase margin, crossover,
delay margin, gain margin) against the exact value found by bisection; a peak or a distance
against the same formula applied to the same samples, since those are read at the samples by
definition. The arithmetic is the writer's own, so the value a role computes and the value
it is checked against come from one implementation.
"""

from __future__ import annotations

import cmath
import json
import math
from collections.abc import Callable
from typing import Any

import pytest
from series_fixture import DIGEST

from physgate.series import writer
from physgate.series.extract import ExtractionError, read_off
from physgate.series.record import Record, parse_record
from physgate.state.schema import SeriesRef

Loop = Callable[[float], complex]


def _loop(k: float, zeta: float, wn: float, tau: float) -> Loop:
    def at(w: float) -> complex:
        s = 1j * w
        return k * wn**2 / (s * (s**2 + 2 * zeta * wn * s + wn**2)) * cmath.exp(-s * tau)

    return at


def _grid(n: int = 2000, lo: float = 0.05, hi: float = 314.0) -> list[float]:
    return [lo * (hi / lo) ** (i / (n - 1)) for i in range(n)]


def _record(
    loop: Loop,
    *,
    unit: str = "rad/s",
    phase_unit: str = "rad",
    grid: list[float] | None = None,
    **extra: Any,  # noqa: ANN401 - fields overridden on the record
) -> Record:
    ws = grid or _grid()
    scale = 2 * math.pi if unit == "Hz" else 1.0
    points = [loop(w) for w in ws]
    to_unit = 180 / math.pi if phase_unit == "deg" else 1.0
    body: dict[str, Any] = {
        "format": "series.v1",
        "id": "loop_nominal",
        "title": "Analytic loop, not a simulation",
        "axis": "frequency",
        "x": {"name": "frequency", "unit": unit, "values": [w / scale for w in ws]},
        "traces": [
            {"name": "loop_magnitude", "unit": "dimensionless", "values": [abs(p) for p in points]},
            {
                "name": "loop_phase",
                "unit": phase_unit,
                "values": [cmath.phase(p) * to_unit for p in points],
            },
        ],
        "producer": {"script": {"path": "modules/control/margins.py", "sha256": DIGEST}},
    }
    body.update(extra)
    return parse_record(json.dumps(body).encode())


def _bisect(f: Callable[[float], float], lo: float, hi: float) -> float:
    for _ in range(200):
        mid = math.sqrt(lo * hi)
        lo, hi = (lo, mid) if f(lo) * f(mid) <= 0 else (mid, hi)
    return math.sqrt(lo * hi)


def _exact_crossover(loop: Loop) -> tuple[float, float]:
    ws = _grid(20_000)
    for a, b in zip(ws, ws[1:], strict=False):
        if (abs(loop(a)) - 1) * (abs(loop(b)) - 1) <= 0:
            w = _bisect(lambda x: abs(loop(x)) - 1, a, b)
            pm = math.pi + cmath.phase(loop(w))
            return w, (pm + math.pi) % (2 * math.pi) - math.pi
    raise AssertionError("no crossover")


def _read(record: Record, extract: str, trace: str | None = None) -> float:
    return read_off(record, SeriesRef(record=record.id, extract=extract, trace=trace)).value  # type: ignore[arg-type]


WELL_DAMPED = [(1.0, 0.7, 10.0, 0.0), (1.0, 0.7, 10.0, 0.02), (3.0, 0.5, 20.0, 0.02)]


@pytest.mark.parametrize("params", WELL_DAMPED)
def test_a_crossing_is_read_to_well_inside_the_tolerance(params: tuple[float, ...]) -> None:
    loop = _loop(*params)
    record = _record(loop)
    w, pm = _exact_crossover(loop)
    assert math.isclose(_read(record, "phase_margin"), pm, rel_tol=1e-4)
    assert math.isclose(_read(record, "gain_crossover_frequency"), w, rel_tol=1e-4)
    assert math.isclose(_read(record, "delay_margin"), pm / w, rel_tol=1e-4)


def test_a_gain_margin_is_read_where_the_phase_crosses_minus_pi() -> None:
    loop = _loop(2.0, 0.3, 10.0, 0.01)
    record = _record(loop)

    def phase_at(x: float) -> float:
        """The loop's phase measured from -pi: zero where the phase crosses -180 degrees."""
        return cmath.phase(loop(x) * cmath.exp(-1j * math.pi))

    ws = _grid(20_000)
    for a, b in zip(ws, ws[1:], strict=False):
        if phase_at(a) * phase_at(b) < 0 and abs(phase_at(a)) < 1:
            w180 = _bisect(phase_at, a, b)
            break
    exact = 1 / abs(loop(w180))
    assert exact > 1
    assert math.isclose(_read(record, "gain_margin_upper"), exact, rel_tol=1e-3)


def test_of_several_crossings_of_unit_gain_the_one_with_the_smallest_margin_is_read() -> None:
    # Crossings at sqrt(2), sqrt(12) and sqrt(30) rad/s, at phases of -2, -2.5 and -1.5 rad.
    body: dict[str, Any] = {
        "format": "series.v1",
        "id": "loop_nominal",
        "title": "Fixture loop with three crossings, not a simulation",
        "axis": "frequency",
        "x": {"name": "frequency", "unit": "rad/s", "values": [1.0, 2.0, 3.0, 4.0, 5.0, 6.0]},
        "traces": [
            {
                "name": "loop_magnitude",
                "unit": "dimensionless",
                "values": [2.0, 0.5, 0.5, 2.0, 2.0, 0.5],
            },
            {"name": "loop_phase", "unit": "rad", "values": [-2.0, -2.0, -2.5, -2.5, -1.5, -1.5]},
        ],
        "producer": {"script": {"path": "modules/control/margins.py", "sha256": DIGEST}},
    }
    record = parse_record(json.dumps(body).encode())
    assert math.isclose(_read(record, "phase_margin"), math.pi - 2.5, rel_tol=1e-12)
    assert math.isclose(_read(record, "gain_crossover_frequency"), math.sqrt(12), rel_tol=1e-12)
    delays = [(math.pi - 2) / math.sqrt(2), (math.pi - 2.5) / math.sqrt(12)]
    delays.append((math.pi - 1.5) / math.sqrt(30))
    assert math.isclose(_read(record, "delay_margin"), min(delays), rel_tol=1e-12)


def test_peaks_and_the_stability_margin_are_read_at_the_samples() -> None:
    loop = _loop(0.5, 0.1, 5.0, 0.0)
    record = _record(loop)
    points = [loop(w) for w in _grid()]
    assert _read(record, "stability_margin") == pytest.approx(min(abs(1 + p) for p in points))
    assert _read(record, "sensitivity_peak") == pytest.approx(max(1 / abs(1 + p) for p in points))
    assert _read(record, "complementary_sensitivity_peak") == pytest.approx(
        max(abs(p) / abs(1 + p) for p in points)
    )


def test_hertz_and_degrees_read_as_rad_per_second_and_radians() -> None:
    loop = _loop(1.0, 0.7, 10.0, 0.02)
    base = _record(loop)
    other = _record(loop, unit="Hz", phase_unit="deg")
    for name in ("phase_margin", "gain_crossover_frequency", "delay_margin"):
        assert math.isclose(_read(other, name), _read(base, name), rel_tol=1e-12), name
    reference = SeriesRef(record="loop_nominal", extract="phase_margin")
    assert read_off(other, reference).unit == "rad"


def test_the_role_s_copy_and_the_check_compute_one_value() -> None:
    loop = _loop(1.0, 0.7, 10.0, 0.02)
    record = _record(loop)
    ws = list(record.x.values)
    mags, phases = (list(t.values) for t in record.traces)
    for name in writer.FREQUENCY_EXTRACTORS:
        if name in ("gain_margin_upper", "gain_margin_lower"):
            continue
        direct = writer.extract(name, omega=ws, magnitude=mags, phase=phases)
        assert _read(record, name) == direct, name


def test_the_time_extractors_read_a_named_trace() -> None:
    body = {
        "format": "series.v1",
        "id": "step_nominal",
        "title": "Fixture step",
        "axis": "time",
        "x": {"name": "time", "unit": "s", "values": [0.0, 0.01, 0.02, 0.03]},
        "traces": [{"name": "tilt", "unit": "rad", "values": [0.0, -0.05, 0.03, 0.01]}],
        "producer": {"script": {"path": "modules/control/sim.py", "sha256": DIGEST}},
    }
    record = parse_record(json.dumps(body).encode())
    expected = {"max": 0.03, "min": -0.05, "max_abs": 0.05, "final": 0.01}
    for name, value in expected.items():
        found = read_off(record, SeriesRef(record="step_nominal", extract=name, trace="tilt"))  # type: ignore[arg-type]
        assert (found.value, found.unit) == (value, "rad"), name
    with pytest.raises(ExtractionError, match="no trace"):
        read_off(record, SeriesRef(record="step_nominal", extract="max", trace="position"))
    with pytest.raises(ExtractionError, match="reads a frequency response"):
        read_off(record, SeriesRef(record="step_nominal", extract="phase_margin"))


@pytest.mark.parametrize(
    ("change", "match"),
    [
        ({"x": {"name": "frequency", "unit": "1/s", "values": [0.1, 1.0, 10.0]}}, "rad/s or Hz"),
        ({"traces": "magnitude in V"}, "ratio"),
        ({"traces": "phase without the radian"}, "ratio"),
        ({"traces": "no magnitude"}, "no trace"),
    ],
    ids=["frequency_not_angular", "magnitude_in_volts", "phase_dimensionless", "missing_trace"],
)
def test_a_frequency_response_in_other_units_is_refused(change: dict[str, Any], match: str) -> None:
    base: dict[str, Any] = {
        "format": "series.v1",
        "id": "loop_nominal",
        "title": "Fixture loop",
        "axis": "frequency",
        "x": {"name": "frequency", "unit": "rad/s", "values": [0.1, 1.0, 10.0]},
        "traces": [
            {"name": "loop_magnitude", "unit": "dimensionless", "values": [10.0, 1.0, 0.1]},
            {"name": "loop_phase", "unit": "rad", "values": [-1.6, -2.2, -2.9]},
        ],
        "producer": {"script": {"path": "modules/control/margins.py", "sha256": DIGEST}},
    }
    if change.get("traces") == "magnitude in V":
        base["traces"][0]["unit"] = "V"
    elif change.get("traces") == "phase without the radian":
        base["traces"][1]["unit"] = "dimensionless"
    elif change.get("traces") == "no magnitude":
        base["traces"] = base["traces"][1:]
    else:
        base.update(change)
    record = parse_record(json.dumps(base).encode())
    with pytest.raises(ExtractionError, match=match):
        read_off(record, SeriesRef(record="loop_nominal", extract="phase_margin"))


def test_what_is_not_on_the_grid_cannot_be_read() -> None:
    always_above = _record(_loop(1000.0, 0.7, 10.0, 0.0), grid=_grid(200, 0.05, 1.0))
    with pytest.raises(ExtractionError, match="no gain crossover"):
        _read(always_above, "phase_margin")
    # 1 / (s (0.1 s + 1)): its phase stays between -90 and -180 degrees and never reaches -180.
    no_phase_crossing = _record(lambda w: 1 / ((1j * w) * (0.1j * w + 1)))
    with pytest.raises(ExtractionError, match="no phase crossing"):
        _read(no_phase_crossing, "gain_margin_upper")


def test_the_writer_publishes_exactly_the_schema_s_extractors() -> None:
    from physgate.state import schema

    assert writer.FREQUENCY_EXTRACTORS == schema.FREQUENCY_EXTRACTORS
    assert writer.TIME_EXTRACTORS == schema.TIME_EXTRACTORS
