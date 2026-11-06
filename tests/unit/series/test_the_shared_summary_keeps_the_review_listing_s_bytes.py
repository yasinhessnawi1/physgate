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

The reader's checked read of a record's bytes is a function of its own as well, so the UI can
serve the very bytes the reader held to their seal, from the one open, rather than a re-encoding
of what it parsed. Reading a record is that read followed by the format's one parser, so the two
admit and refuse exactly the same files, and neither reads past the format's byte bound.
"""

from __future__ import annotations

import hashlib
import json
import math
import os
from collections.abc import Callable
from pathlib import Path
from typing import Any

import pytest
from series_fixture import DIGEST, encode, frequency_record_dict, record_dict

from physgate.orchestrator.trajectory import Seal
from physgate.series import reader, summary
from physgate.series.exceptions import RecordRefusedError, RecordTamperedError, SeriesError
from physgate.series.reader import SealedEntry, read_record
from physgate.series.record import MAX_FILE_BYTES, parse_record
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


def _sealed_bytes() -> Callable[[Path, Seal], bytes]:
    found = getattr(reader, "read_sealed_bytes", None)
    assert callable(found), "the reader's checked read of a record's bytes is a function of its own"
    return found  # type: ignore[no-any-return]


def test_the_checked_bytes_are_the_sealed_file_s_and_parse_to_the_record_the_reader_reads(
    tmp_path: Path,
) -> None:
    read_sealed_bytes = _sealed_bytes()
    series = _series(tmp_path)
    for held in series.records:
        entry = SealedEntry(SUBTASK, 1, held.session_id, held.record)
        path, sealed = entry.path(tmp_path), entry.seal()
        data = read_sealed_bytes(path, sealed)
        assert data == path.read_bytes()
        assert (hashlib.sha256(data).hexdigest(), len(data)) == (sealed.sha256, sealed.length)
        assert parse_record(data) == read_record(path, sealed)
    assert len(series.records) == len(_records())


def _one(run_dir: Path, data: bytes) -> tuple[Path, Seal]:
    """``data`` written where a session's end would seal it, with its seal."""
    sealed = SealedRecord(
        record_id="step_nominal",
        sha256=hashlib.sha256(data).hexdigest(),
        length=len(data),
        script="modules/control/sim.py",
        script_sha256=DIGEST,
        script_blob="0" * 40,
    )
    entry = SealedEntry(SUBTASK, 1, SESSION, sealed)
    path = entry.path(run_dir)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(data)
    return path, entry.seal()


def _counting(reads: list[int]) -> Callable[[int, int], bytes]:
    """``os.read``, recording how many bytes each call asked for."""
    real = os.read

    def read(fd: int, size: int) -> bytes:
        reads.append(size)
        return real(fd, size)

    return read


HOW = (
    "a byte changed",
    "its length changed",
    "gone",
    "a link",
    "a second name",
    "a fifo in its place",
    "a directory in its place",
    "over the byte bound",
    "a relative path",
)


@pytest.mark.parametrize("how", HOW)
def test_the_checked_bytes_refuse_exactly_what_reading_the_record_refuses(
    tmp_path: Path, how: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    read_sealed_bytes = _sealed_bytes()
    data = encode(record_dict())
    path, sealed = _one(
        tmp_path, b" " * (MAX_FILE_BYTES + 1) if how == "over the byte bound" else data
    )
    if how == "a byte changed":
        at = data.index(b"0.05")
        path.write_bytes(data[:at] + b"9" + data[at + 1 :])
    elif how == "its length changed":
        path.write_bytes(data + b" ")
    elif how == "gone":
        path.unlink()
    elif how == "a link":
        elsewhere = path.with_name("elsewhere.json")
        path.rename(elsewhere)
        path.symlink_to(elsewhere)
    elif how == "a second name":
        os.link(path, path.with_name("second_name.json"))
    elif how == "a fifo in its place":
        path.unlink()
        os.mkfifo(path)
    elif how == "a directory in its place":
        path.unlink()
        path.mkdir()
    elif how == "a relative path":
        path = Path(os.path.relpath(path))
    refusals: list[SeriesError] = []
    reads: list[int] = []
    monkeypatch.setattr(os, "read", _counting(reads))
    for read in (read_sealed_bytes, read_record):
        with pytest.raises((RecordTamperedError, RecordRefusedError)) as caught:
            read(path, sealed)
        refusals.append(caught.value)
    checked, whole = refusals
    assert (type(checked), str(checked), checked.context) == (
        type(whole),
        str(whole),
        whole.context,
    )
    if how in ("its length changed", "over the byte bound", "a relative path"):
        assert reads == [], "refused before a byte is read"
    assert all(size <= MAX_FILE_BYTES + 1 for size in reads)


def test_sealed_bytes_that_are_not_a_record_are_returned_as_sealed_and_refused_by_the_parser(
    tmp_path: Path,
) -> None:
    read_sealed_bytes = _sealed_bytes()
    data = b'{"format": "series.v1"}'
    path, sealed = _one(tmp_path, data)
    assert read_sealed_bytes(path, sealed) == data
    with pytest.raises(RecordRefusedError, match="does not validate"):
        read_record(path, sealed)
