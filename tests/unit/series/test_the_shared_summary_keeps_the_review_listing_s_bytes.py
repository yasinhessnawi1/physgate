"""The review listing's per-column arithmetic, shared with the operator UI, and its bytes kept.

The listing a reviewer reads summarises each column of each record by its unit, its number of
samples, and its first, last, smallest and largest value. The operator UI shows the same
numbers, so the arithmetic is one function both call. Making it one function must not change a
byte of the listing: the bytes are held here to the listing as it was written before the
function existed, over the format's fixture records and a set of edge values (a negative zero
tied with a zero, a value near the smallest double, very large and very small values, integer
samples, an integer input beyond what a float holds exactly).

The reader's identifier patterns are public too, so the UI's routes spell a subtask and a
session exactly as the reader does, and cannot drift from it.
"""

from __future__ import annotations

import hashlib
import json
import math
from pathlib import Path
from typing import Any

from series_fixture import DIGEST, encode, frequency_record_dict, record_dict

from physgate.series import reader, summary
from physgate.series.reader import SealedEntry, read_record
from physgate.series.seal import AttemptRecord, AttemptSeries, SealedRecord, SeriesCheck

#: The listing's bytes as written before its column arithmetic became a shared function.
GOLDEN = Path(__file__).with_name("review_listing_golden.md")

SUBTASK = "s1"
SESSION = "fixture-session"


def _edges() -> dict[str, Any]:
    """A record whose columns hold the values a summary is easiest to get subtly wrong."""
    return record_dict(
        id="edge_values",
        title="Edge values, made up for the listing's tests",
        group="edges",
        x={"name": "time", "unit": "s", "values": [0.0, 0.1, 0.2, 0.3, 0.4]},
        traces=[
            {"name": "signed_zero", "unit": "m", "values": [-0.0, 0.0, -0.0, 0.0, -0.0]},
            {"name": "zero_first", "unit": "m", "values": [0.0, -0.0, 0.0, -0.0, 0.0]},
            {"name": "spread", "unit": "V", "values": [1e-05, 2.5e-308, 1e16, -1e16, 3]},
            {"name": "integers", "unit": "count", "values": [0, 1, 2, 3, 4]},
        ],
        inputs={
            "seed": {"value": 2**63 - 1, "unit": "dimensionless"},
            "gain": {"value": 0.1, "unit": "dimensionless"},
        },
    )


def _long() -> dict[str, Any]:
    """A step-like record of 501 samples, from arithmetic that is exact on every platform."""
    times = [k / 50 for k in range(501)]
    return record_dict(
        id="long_step",
        title="A long made-up step, not a simulation result",
        group="step",
        x={"name": "time", "unit": "s", "values": times},
        traces=[
            {"name": "position", "unit": "m", "values": [t * t / (1 + t * t) for t in times]},
            {"name": "error", "unit": "m", "values": [1 / (1 + t * t) for t in times]},
        ],
    )


def _records() -> list[dict[str, Any]]:
    return [record_dict(), frequency_record_dict(), _edges(), _long()]


def _series(run_dir: Path) -> AttemptSeries:
    """The fixture records written where a session's end would seal them, with two checks."""
    held = []
    for record in _records():
        data = encode(record)
        sealed = SealedRecord(
            record_id=record["id"],
            sha256=hashlib.sha256(data).hexdigest(),
            length=len(data),
            script="modules/control/sim.py",
            script_sha256=DIGEST,
            script_blob="0" * 40,
        )
        path = SealedEntry(SUBTASK, 1, SESSION, sealed).path(run_dir)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(data)
        held.append(AttemptRecord(session_id=SESSION, record=sealed))
    checks = (
        SeriesCheck(
            node_id="control.loop",
            quantity="step_peak",
            record_id="long_step",
            extract="max",
            trace="position",
            session_id=SESSION,
            declared_value=0.99,
            declared_unit="m",
            read_value=0.9900990099009901,
            read_unit="m",
            outcome="agrees",
        ),
        SeriesCheck(
            node_id="control.loop",
            quantity="phase_margin",
            record_id="loop_elsewhere",
            extract="phase_margin",
            declared_value=0.7,
            declared_unit="rad",
            outcome="unreadable",
            reason="the attempt sealed no record loop_elsewhere",
        ),
    )
    return AttemptSeries(
        run_dir=str(run_dir), subtask_id=SUBTASK, attempt=1, records=tuple(held), checks=checks
    )


def test_the_listing_keeps_every_byte_it_had(tmp_path: Path) -> None:
    written = summary.listing(_series(tmp_path))
    assert written.count(b"\n## ") == len(_records()), "a listing of fewer records proves less"
    assert written == GOLDEN.read_bytes()


def test_the_reader_names_its_identifier_patterns_publicly_and_unchanged() -> None:
    subtask = getattr(reader, "SUBTASK_PATTERN", None)
    session = getattr(reader, "SESSION_PATTERN", None)
    assert subtask is not None and session is not None, "the patterns are the reader's to share"
    assert subtask.pattern == r"^[A-Za-z0-9][A-Za-z0-9_-]{0,63}$"
    assert session.pattern == r"^[A-Za-z0-9_-]{1,128}$"


def test_one_function_gives_each_column_s_summary_as_the_listing_writes_it(
    tmp_path: Path,
) -> None:
    column_summary = getattr(summary, "column_summary", None)
    assert callable(column_summary), "the listing's column arithmetic is a function of its own"
    series = _series(tmp_path)
    seen = 0
    for held in series.records:
        entry = SealedEntry(SUBTASK, 1, held.session_id, held.record)
        record = read_record(entry.path(tmp_path), entry.seal())
        for column in (record.x, *record.traces):
            values = column.values
            found = column_summary(column)
            assert (found.unit, found.samples) == (column.unit, len(values))
            for got, expected in (
                (found.first, values[0]),
                (found.last, values[-1]),
                (found.smallest, min(values)),
                (found.largest, max(values)),
            ):
                # Equal as numbers and in sign: a negative zero is the value the record holds.
                assert got == expected and math.copysign(1, got) == math.copysign(1, expected)
            seen += 1
    assert seen >= 12


def test_a_tie_between_zero_and_negative_zero_keeps_the_first_as_the_listing_does(
    tmp_path: Path,
) -> None:
    column_summary = getattr(summary, "column_summary", None)
    assert callable(column_summary)
    data = encode(_edges())
    sealed = SealedRecord(
        record_id="edge_values",
        sha256=hashlib.sha256(data).hexdigest(),
        length=len(data),
        script="modules/control/sim.py",
        script_sha256=DIGEST,
        script_blob="0" * 40,
    )
    path = SealedEntry(SUBTASK, 1, SESSION, sealed).path(tmp_path)
    path.parent.mkdir(parents=True)
    path.write_bytes(data)
    record = read_record(path, SealedEntry(SUBTASK, 1, SESSION, sealed).seal())
    signs = {
        trace.name: tuple(
            math.copysign(1, v)
            for v in (column_summary(trace).smallest, column_summary(trace).largest)
        )
        for trace in record.traces
    }
    assert signs["signed_zero"] == (-1.0, -1.0)
    assert signs["zero_first"] == (1.0, 1.0)
    assert json.loads(json.dumps(column_summary(record.traces[0]).first)) == 0.0
