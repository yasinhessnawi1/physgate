"""A sealed series record is read only as the bytes its seal names, bounded, and writing nothing.

The reader is the one the operator UI will call, so the last two tests run it inside the
UI's own read guard: once with the run directory readable, where it must succeed, and
once with it unreadable, where the guard must refuse its open. The second proves the
guard actually sees the reader's open, so the first is not a pass over nothing.
"""

from __future__ import annotations

import os
from collections.abc import Callable
from pathlib import Path

import pytest
from series_fixture import encode, record_dict

from physgate.orchestrator.trajectory import Seal, seal
from physgate.series.exceptions import RecordRefusedError, RecordTamperedError
from physgate.series.reader import read_record, record_path
from physgate.series.record import MAX_FILE_BYTES
from physgate.ui import guard
from physgate.ui.exceptions import GuardRefusedError


def _sealed(
    run_dir: Path, data: bytes | None = None, record_id: str = "step_nominal"
) -> tuple[Path, Seal]:
    body = encode(record_dict(id=record_id)) if data is None else data
    path = record_path(run_dir, "control-8f3ac4", 1, "session-1", record_id)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(body)
    return path, seal(body)


def _counting(reads: list[int]) -> Callable[[int, int], bytes]:
    """``os.read``, recording how many bytes each call asked for."""
    real = os.read

    def read(fd: int, size: int) -> bytes:
        reads.append(size)
        return real(fd, size)

    return read


@pytest.fixture
def run_dir(tmp_path: Path) -> Path:
    return Path(os.path.realpath(tmp_path)) / "run"


def test_a_sealed_record_reads_back_as_it_was_written(run_dir: Path) -> None:
    path, sealed = _sealed(run_dir)
    assert path == run_dir / "series" / "control-8f3ac4" / "1" / "session-1" / "step_nominal.json"
    record = read_record(path, sealed)
    assert record.id == "step_nominal"
    assert record.traces[0].unit == "m"


def test_a_byte_changed_in_place_is_refused(run_dir: Path) -> None:
    path, sealed = _sealed(run_dir)
    data = bytearray(path.read_bytes())
    data[data.index(b"0.05")] = ord("9")
    path.write_bytes(bytes(data))
    assert path.stat().st_size == sealed.length
    with pytest.raises(RecordTamperedError, match="not what it was"):
        read_record(path, sealed)


@pytest.mark.parametrize("change", ["append", "truncate"])
def test_a_record_that_changed_length_is_refused_before_it_is_read(
    run_dir: Path, change: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    path, sealed = _sealed(run_dir)
    data = path.read_bytes()
    path.write_bytes(data + b" " if change == "append" else data[:-1])
    reads: list[int] = []
    monkeypatch.setattr(os, "read", _counting(reads))
    with pytest.raises(RecordTamperedError, match="not the length"):
        read_record(path, sealed)
    assert reads == []


def test_a_record_replaced_by_another_of_the_same_length_is_refused(run_dir: Path) -> None:
    path, sealed = _sealed(run_dir)
    other = path.read_bytes().replace(b'"step"', b'"stap"')
    assert len(other) == sealed.length
    path.unlink()
    path.write_bytes(other)
    with pytest.raises(RecordTamperedError, match="not what it was"):
        read_record(path, sealed)


def test_a_sealed_record_that_is_gone_is_refused(run_dir: Path) -> None:
    path, sealed = _sealed(run_dir)
    path.unlink()
    with pytest.raises(RecordTamperedError, match="gone"):
        read_record(path, sealed)


def test_a_record_that_is_a_link_is_refused(run_dir: Path) -> None:
    path, sealed = _sealed(run_dir)
    elsewhere = run_dir / "elsewhere.json"
    path.rename(elsewhere)
    path.symlink_to(elsewhere)
    with pytest.raises(RecordTamperedError, match="link"):
        read_record(path, sealed)


def test_a_link_that_appears_after_the_path_check_is_still_not_followed(
    run_dir: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    # The path check and the open are two steps. Here the check is made to see no link, as it
    # would if a link were swapped in just after it; the open itself must still refuse one.
    path, sealed = _sealed(run_dir)
    elsewhere = run_dir / "elsewhere.json"
    path.rename(elsewhere)
    path.symlink_to(elsewhere)
    monkeypatch.setattr(os.path, "realpath", os.path.normpath)
    with pytest.raises(RecordTamperedError, match="is a link"):
        read_record(path, sealed)


def test_a_record_reached_through_a_linked_directory_is_refused(run_dir: Path) -> None:
    path, sealed = _sealed(run_dir)
    session_dir = path.parent
    moved = run_dir / "moved-session"
    session_dir.rename(moved)
    session_dir.symlink_to(moved, target_is_directory=True)
    assert path.exists()
    with pytest.raises(RecordTamperedError, match="through a link"):
        read_record(path, sealed)


def test_a_record_with_a_second_name_is_refused(run_dir: Path) -> None:
    path, sealed = _sealed(run_dir)
    os.link(path, run_dir / "second-name.json")
    with pytest.raises(RecordTamperedError, match="another name"):
        read_record(path, sealed)


def test_a_pipe_or_a_directory_in_a_record_s_place_is_refused(run_dir: Path) -> None:
    path, sealed = _sealed(run_dir)
    path.unlink()
    os.mkfifo(path)
    with pytest.raises(RecordTamperedError, match="not a regular file"):
        read_record(path, sealed)
    path.unlink()
    path.mkdir()
    with pytest.raises(RecordTamperedError, match="not a regular file"):
        read_record(path, sealed)


def test_a_file_over_the_byte_bound_is_refused_before_a_byte_is_read(
    run_dir: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    oversized = b" " * (MAX_FILE_BYTES + 1)
    path, sealed = _sealed(run_dir, oversized)
    reads: list[int] = []
    monkeypatch.setattr(os, "read", _counting(reads))
    with pytest.raises(RecordRefusedError, match="at most"):
        read_record(path, sealed)
    assert reads == []


def test_sealed_bytes_that_are_not_a_record_are_refused(run_dir: Path) -> None:
    path, sealed = _sealed(run_dir, b'{"format": "series.v1"}')
    with pytest.raises(RecordRefusedError, match="does not validate"):
        read_record(path, sealed)


def test_the_fix_a_person_ordered_has_a_record_path_of_its_own() -> None:
    path = record_path(Path("/run"), "sub", 4, "s", "r")
    assert path.parts[-4:] == ("sub", "4", "s", "r.json")


@pytest.mark.parametrize(
    ("subtask", "attempt", "session", "record"),
    [
        ("../escape", 1, "s", "r"),
        ("a/b", 1, "s", "r"),
        ("sub", 0, "s", "r"),
        # Past the last attempt a subtask can reach: the budget's three and the one fix.
        ("sub", 5, "s", "r"),
        ("sub", True, "s", "r"),
        ("sub", 1, "s/../t", "r"),
        ("sub", 1, "s", "R"),
        ("sub", 1, "s", "../r"),
    ],
)
def test_a_record_s_path_is_built_only_from_plain_identifiers(
    subtask: str, attempt: int, session: str, record: str
) -> None:
    with pytest.raises(RecordRefusedError):
        record_path(Path("/run"), subtask, attempt, session, record)


def test_a_relative_path_is_refused() -> None:
    with pytest.raises(RecordRefusedError, match="absolute"):
        read_record(Path("series/x.json"), seal(b""))


def _snapshot(root: Path) -> dict[str, tuple[int, int, int]]:
    found = {}
    for directory, names, files in os.walk(root):
        for name in [*names, *files]:
            info = os.lstat(os.path.join(directory, name))
            found[os.path.join(directory, name)] = (info.st_ino, info.st_size, info.st_mtime_ns)
    return found


def test_reading_writes_nothing_whether_it_succeeds_or_is_refused(run_dir: Path) -> None:
    path, sealed = _sealed(run_dir)
    bad_path, bad_seal = _sealed(run_dir, b"not json", record_id="broken")
    before = _snapshot(run_dir)
    read_record(path, sealed)
    with pytest.raises(RecordRefusedError):
        read_record(bad_path, bad_seal)
    with pytest.raises(RecordTamperedError):
        read_record(path, Seal(sha256="0" * 64, length=sealed.length))
    assert _snapshot(run_dir) == before


def test_the_reader_runs_inside_the_ui_s_read_guard(run_dir: Path) -> None:
    path, sealed = _sealed(run_dir)
    root = str(run_dir)
    guard.install()
    with guard.scope("read", readable=lambda p: os.path.realpath(p).startswith(root + os.sep)):
        record = read_record(path, sealed)
    assert record.id == "step_nominal"


def test_the_ui_s_read_guard_sees_the_reader_s_open(run_dir: Path) -> None:
    path, sealed = _sealed(run_dir)
    guard.install()
    with (
        pytest.raises(GuardRefusedError, match="outside the roots"),
        guard.scope("read", readable=lambda p: False),
    ):
        read_record(path, sealed)
