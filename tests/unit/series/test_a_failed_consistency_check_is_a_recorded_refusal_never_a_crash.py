"""Every way a consistency check can fail is a recorded refusal, never an exception or a stall.

Each case is inert data that once escaped, or could escape, as an exception from the check,
which runs inside the orchestrator's change check: a phase trace of huge magnitudes (it
overflowed the unwrapping), magnitudes so small a gain margin came out infinite, a record that
cannot be opened, a unit conversion that fails inside the registry. And the check's cost is
bounded: each record is read once, each extraction made once, and an attempt naming more
quantities to check than the bound is refused rather than read.
"""

from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any

import pytest
from series_fixture import DIGEST

from physgate.gate import units
from physgate.orchestrator.trajectory import seal
from physgate.series import consistency, reader, writer
from physgate.series.consistency import MAX_SERIES_CHECKS, check_proposals
from physgate.series.reader import SealedEntry, record_path
from physgate.series.seal import SealedRecord, SeriesCheck


def _sealed(run_dir: Path, x: list[float], traces: list[dict[str, Any]]) -> SealedEntry:
    body = {
        "format": "series.v1",
        "id": "loop_nominal",
        "title": "Fixture, not a simulation",
        "axis": "frequency",
        "x": {"name": "frequency", "unit": "rad/s", "values": x},
        "traces": traces,
        "producer": {"script": {"path": "modules/control/margins.py", "sha256": DIGEST}},
    }
    data = json.dumps(body).encode()
    path = record_path(run_dir, "control-1", 1, "session-1", "loop_nominal")
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(data)
    held = seal(data)
    record = SealedRecord(
        record_id="loop_nominal",
        sha256=held.sha256,
        length=held.length,
        script="modules/control/margins.py",
        script_sha256=DIGEST,
        script_blob="b" * 40,
    )
    return SealedEntry("control-1", 1, "session-1", record)


def _loop(magnitude: list[float], phase: list[float]) -> list[dict[str, Any]]:
    return [
        {"name": "loop_magnitude", "unit": "dimensionless", "values": magnitude},
        {"name": "loop_phase", "unit": "rad", "values": phase},
    ]


#: A loop crossing unit gain between 1 and 2 rad/s at a phase of -2 rad: a margin of pi - 2.
PLAIN = ([1.0, 2.0, 3.0], _loop([2.0, 0.5, 0.5], [-2.0, -2.0, -2.0]))


def _proposal(*quantities: tuple[str, float, str, str]) -> dict[str, Any]:
    return {
        "id": "control.loop_gain",
        "quantities": {
            name: {
                "value": value,
                "unit": unit,
                "source": "read off the record",
                "written_by": "control",
                "series": {"record": "loop_nominal", "extract": extract},
            }
            for name, value, unit, extract in quantities
        },
    }


@pytest.fixture
def run_dir(tmp_path: Path) -> Path:
    return Path(os.path.realpath(tmp_path)) / "run"


def _one(run_dir: Path, entry: SealedEntry, quantity: tuple[str, float, str, str]) -> SeriesCheck:
    (result,) = check_proposals([_proposal(quantity)], [entry], run_dir)
    return result


def test_a_phase_of_huge_magnitude_is_refused_not_an_overflow(run_dir: Path) -> None:
    entry = _sealed(run_dir, [1.0, 2.0, 3.0], _loop([2.0, 0.5, 0.5], [1e308, -1e308, 1e308]))
    result = _one(run_dir, entry, ("phase_margin", 0.6, "rad", "phase_margin"))
    assert result.outcome == "unreadable"
    assert result.reason is not None and "cannot be read off" in result.reason


def test_a_gain_margin_that_would_be_infinite_is_refused(run_dir: Path) -> None:
    tiny = [5e-324, 5e-324, 5e-324]
    entry = _sealed(run_dir, [1.0, 2.0, 3.0], _loop(tiny, [-3.0, -3.3, -3.6]))
    result = _one(run_dir, entry, ("gain_margin_upper", 2.0, "dimensionless", "gain_margin_upper"))
    assert result.outcome == "unreadable"
    assert result.reason is not None and "not a finite number" in result.reason


def test_a_record_that_cannot_be_opened_is_refused(run_dir: Path) -> None:
    entry = _sealed(run_dir, *PLAIN)
    path = entry.path(run_dir)
    path.chmod(0)
    try:
        result = _one(run_dir, entry, ("phase_margin", 1.14, "rad", "phase_margin"))
    finally:
        path.chmod(0o644)
    assert result.outcome == "unreadable"
    assert result.reason is not None and "cannot be read" in result.reason


def test_a_conversion_that_fails_inside_the_registry_is_refused(
    run_dir: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    entry = _sealed(run_dir, *PLAIN)
    real_parse = units.parse

    def failing(value: float | int, unit: str) -> Any:  # noqa: ANN401 - a pint quantity
        if unit == "deg":
            msg = "an error inside the registry"
            raise RuntimeError(msg)
        return real_parse(value, unit)

    monkeypatch.setattr(units, "parse", failing)
    result = _one(run_dir, entry, ("phase_margin", 65.4, "deg", "phase_margin"))
    assert result.outcome == "unreadable"
    assert result.reason is not None and "an error inside the registry" in result.reason


@pytest.mark.parametrize(
    ("declared", "outcome"), [(0.0, "agrees"), (1e-300, "differs")], ids=["both_zero", "zero_read"]
)
def test_a_zero_read_value_is_compared_without_dividing_by_it(
    run_dir: Path, declared: float, outcome: str
) -> None:
    # The phase at the crossing is exactly -pi, so the margin read is exactly zero.
    entry = _sealed(run_dir, [1.0, 2.0], _loop([2.0, 0.5], [-3.141592653589793] * 2))
    assert _one(run_dir, entry, ("pm", declared, "rad", "phase_margin")).outcome == outcome


def test_each_record_is_read_once_and_each_extraction_made_once(
    run_dir: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    entry = _sealed(run_dir, *PLAIN)
    reads: list[str] = []
    extractions: list[str] = []
    real_read, real_extract = reader.read_record, writer.extract

    def counting_read(path: Path, held: Any) -> Any:  # noqa: ANN401 - passed through
        reads.append(str(path))
        return real_read(path, held)

    def counting_extract(name: str, **samples: Any) -> float:  # noqa: ANN401 - passed through
        extractions.append(name)
        return real_extract(name, **samples)

    monkeypatch.setattr(consistency, "read_record", counting_read)
    monkeypatch.setattr(writer, "extract", counting_extract)
    quantities = [(f"q{n}", 1.14, "rad", "phase_margin") for n in range(10)]
    quantities.append(("crossover", 1.41, "rad/s", "gain_crossover_frequency"))
    results = check_proposals([_proposal(*quantities)], [entry], run_dir)
    assert [r.outcome for r in results] == ["agrees"] * 11
    assert len(reads) == 1
    assert sorted(extractions) == ["gain_crossover_frequency", "phase_margin"]


def test_more_quantities_to_check_than_the_bound_are_refused_unread(
    run_dir: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    entry = _sealed(run_dir, *PLAIN)
    reads: list[str] = []
    monkeypatch.setattr(consistency, "read_record", lambda p, h: reads.append(str(p)))
    quantities = [(f"q{n}", 1.14, "rad", "phase_margin") for n in range(MAX_SERIES_CHECKS + 1)]
    results = check_proposals([_proposal(*quantities)], [entry], run_dir)
    assert len(results) == MAX_SERIES_CHECKS + 1
    assert {r.outcome for r in results} == {"unreadable"}
    assert all(r.reason and f"more than {MAX_SERIES_CHECKS}" in r.reason for r in results)
    assert reads == []


def test_as_many_quantities_as_the_bound_are_all_checked(run_dir: Path) -> None:
    entry = _sealed(run_dir, *PLAIN)
    quantities = [(f"q{n}", 1.14, "rad", "phase_margin") for n in range(MAX_SERIES_CHECKS)]
    results = check_proposals([_proposal(*quantities)], [entry], run_dir)
    assert {r.outcome for r in results} == {"agrees"}


@pytest.mark.parametrize(
    ("quantity", "says"),
    [
        (("pm", 1e308, "krad", "phase_margin"), "too large"),
        (("crossover", 1e308, "Hz", "gain_crossover_frequency"), "not a finite number"),
    ],
    ids=["through_the_registry", "through_two_pi"],
)
def test_a_declared_value_that_converts_past_the_largest_float_is_refused(
    run_dir: Path, quantity: tuple[str, float, str, str], says: str
) -> None:
    entry = _sealed(run_dir, *PLAIN)
    result = _one(run_dir, entry, quantity)
    assert result.outcome == "unreadable"
    assert result.reason is not None and says in result.reason


@pytest.mark.parametrize(
    ("unit", "says"),
    [
        ("dB", "logarithmic"),
        ("decibel", "logarithmic"),
        ("Np", "logarithmic"),
        ("octave", "logarithmic"),
        ("decade", "logarithmic"),
        ("B", "not the same kind"),
    ],
)
def test_a_declared_unit_that_is_logarithmic_or_counts_information_is_refused(
    run_dir: Path, unit: str, says: str
) -> None:
    # Declared as exactly the read value converted into the unit, so only the unit can refuse.
    entry = _sealed(run_dir, *PLAIN)
    ws, (mags, phases) = PLAIN[0], (t["values"] for t in PLAIN[1])
    read = writer.extract("stability_margin", omega=ws, magnitude=mags, phase=phases)
    declared = float(units.parse(read, "dimensionless").to(unit).magnitude)
    result = _one(run_dir, entry, ("margin", declared, unit, "stability_margin"))
    assert result.outcome == "unreadable", result
    assert result.reason is not None and says in result.reason
