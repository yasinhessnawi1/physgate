"""Reading the approval queue writes nothing, and reads exactly what the writer would accept.

The writer, ``ApprovalQueue``, creates its files and cuts a torn final line when it opens:
right for the one writer, wrong for anything that only reads, which might cut a line a
person's decision is still completing. ``read_queue`` and ``queue_listing`` read through the
writer's own parser and change nothing, and ``physgate queue list`` prints from them.

Two detectors stand apart from the code under test: a snapshot of every byte and name in the
run directory, and an audit-hook recorder of every write-capable open and filesystem change.
"""

from __future__ import annotations

import json
import os
import shutil
import sys
from collections.abc import Iterator
from pathlib import Path

import pytest
from loop_fakes import FakeDispatcher, FakeGate, Rig, plan

from physgate.cli import main
from physgate.orchestrator.exceptions import QueueError
from physgate.orchestrator.queue import (
    DECISIONS_NAME,
    QUEUE_NAME,
    ApprovalQueue,
    queue_listing,
    read_queue,
)

# -- the detectors ----------------------------------------------------------------------

_WRITE_FLAGS = os.O_WRONLY | os.O_RDWR | os.O_CREAT | os.O_APPEND | os.O_TRUNC
_CHANGES = {"os.mkdir", "os.remove", "os.rename", "os.truncate", "os.rmdir", "os.utime"}
_recorded: list[tuple[str, str]] = []
_recording = {"on": False}


def _recorder(event: str, args: tuple[object, ...]) -> None:
    if not _recording["on"]:
        return
    if event == "open":
        mode = args[1] if len(args) > 1 else None
        flags = args[2] if len(args) > 2 else 0
        writes = (isinstance(mode, str) and bool(set(mode) & set("wax+"))) or (
            isinstance(flags, int) and bool(flags & _WRITE_FLAGS)
        )
        if writes:
            _recorded.append((event, str(args[0])))
    elif event in _CHANGES:
        _recorded.append((event, str(args[0]) if args else ""))


sys.addaudithook(_recorder)


@pytest.fixture
def recorded() -> Iterator[list[tuple[str, str]]]:
    """Every write-capable open or filesystem change made inside the test's block."""
    _recorded.clear()
    _recording["on"] = True
    try:
        yield _recorded
    finally:
        _recording["on"] = False


def _snapshot(root: Path) -> dict[str, bytes | None]:
    if not root.exists():
        return {"<absent>": None}
    return {
        str(p.relative_to(root)): (p.read_bytes() if p.is_file() else None)
        for p in sorted(root.rglob("*"))
    }


# -- the runs ---------------------------------------------------------------------------


def _decide(run_dir: Path, item: str) -> None:
    ApprovalQueue(run_dir / QUEUE_NAME).resolve(item, decision="split", resolved_by="yasin")


@pytest.fixture
def decided(tmp_path: Path) -> Path:
    """Two escalations, one decided while a session ran and one after every session."""
    run_dir = tmp_path / "run"
    run_dir.mkdir()
    rig = Rig(run_dir, dispatcher=FakeDispatcher(during={7: lambda: _decide(run_dir, "run-1-s1")}))
    rig.gate = FakeGate(verdicts=["fail"] * 6 + ["pass"])
    loop = rig.open()
    loop.start(plan("s1", "s2", "s3"))
    assert loop.run().kind == "done"
    loop.close()
    _decide(run_dir, "run-1-s2")
    return run_dir


def _decided(run_dir: Path) -> list[dict[str, object]]:
    decided = queue_listing(run_dir)["decided"]
    assert isinstance(decided, list)
    return decided


def _copy(run_dir: Path, name: str) -> Path:
    target = run_dir.with_name(name)
    shutil.copytree(run_dir, target)
    return target


# -- nothing is written ------------------------------------------------------------------


def test_reading_a_run_with_no_queue_creates_nothing(
    tmp_path: Path, recorded: list[tuple[str, str]]
) -> None:
    absent = tmp_path / "absent"
    empty = tmp_path / "empty"
    empty.mkdir()
    recorded.clear()  # the setup above is the test's own
    for run_dir in (absent, empty):
        view = read_queue(run_dir)
        assert view.items == () and view.decisions == ()
        assert queue_listing(run_dir) == {"open": [], "decided": []}
    assert not absent.exists()
    assert list(empty.iterdir()) == []
    assert recorded == []


def test_a_torn_final_line_is_not_read_and_not_cut(
    decided: Path, recorded: list[tuple[str, str]]
) -> None:
    whole = read_queue(decided)
    for name in (QUEUE_NAME, DECISIONS_NAME):
        with (decided / name).open("ab") as handle:
            handle.write(b'{"kind":"resol')
    before = _snapshot(decided)
    recorded.clear()
    torn = read_queue(decided)
    listing = _decided(decided)
    assert recorded == []
    assert _snapshot(decided) == before
    assert torn == whole
    assert [d["item_id"] for d in listing] == ["run-1-s1", "run-1-s2"]


@pytest.mark.parametrize(
    ("name", "line", "reason"),
    [
        (QUEUE_NAME, b"not a record\n", "Invalid JSON"),
        (DECISIONS_NAME, b"not a record\n", "Invalid JSON"),
        (
            DECISIONS_NAME,
            b'{"kind":"resolution","item_id":"nope","ts":"2026-10-10T00:00:00.000000Z",'
            b'"decision":"x","resolved_by":"y"}\n',
            "which is not an open item",
        ),
        (
            DECISIONS_NAME,
            b'{"kind":"resolution","item_id":"run-1-s1","ts":"2026-10-10T00:00:00.000000Z",'
            b'"decision":"x","resolved_by":"y"}\n',
            "which is not an open item",
        ),
    ],
)
def test_a_line_the_writer_would_refuse_is_refused_by_the_reader_and_left_in_place(
    decided: Path, recorded: list[tuple[str, str]], name: str, line: bytes, reason: str
) -> None:
    with (decided / name).open("ab") as handle:
        handle.write(line)
    before = _snapshot(decided)
    recorded.clear()
    with pytest.raises(QueueError) as reader:
        read_queue(decided)
    assert reason in reader.value.context["reason"]
    assert recorded == []
    assert _snapshot(decided) == before
    with pytest.raises(QueueError) as writer:
        ApprovalQueue(_copy(decided, "writer") / QUEUE_NAME)
    assert writer.value.context["reason"] == reader.value.context["reason"]


# -- what is read is what the writer reads -------------------------------------------------


def test_the_reader_and_the_writer_agree_on_every_item_and_decision(decided: Path) -> None:
    view = read_queue(decided)
    writer = ApprovalQueue(_copy(decided, "writer") / QUEUE_NAME)
    assert list(view.items) == writer.items()
    assert view.open_items() == writer.open_items()
    assert [d.item_id for _, d in view.decisions] == ["run-1-s1", "run-1-s2"]
    raw = (decided / DECISIONS_NAME).read_bytes()
    for offset, decision in view.decisions:
        line = raw[offset:].split(b"\n", 1)[0]
        assert line == decision.model_dump_json().encode()


def test_a_window_still_open_marks_every_decision_after_it(decided: Path) -> None:
    """The log cut right after the session the first decision was written in started."""
    cut = _copy(decided, "cut")
    lines = (cut / "events.jsonl").read_bytes().splitlines(keepends=True)
    ended = next(
        i
        for i, raw in enumerate(lines)
        if json.loads(raw).get("kind") == "session_ended"
        and (json.loads(raw).get("decisions_bytes") or 0) > 0
    )
    (cut / "events.jsonl").write_bytes(b"".join(lines[:ended]))
    flags = [d["flag"] for d in _decided(cut)]
    assert flags == ["made while session still running or not yet resumed ran; confirm"] * 2
    closed = [d["flag"] for d in _decided(decided)]
    assert closed == ["made while session sess-7 ran; confirm", None]


# -- the command prints from the reader ----------------------------------------------------


def test_queue_list_prints_the_listing_and_writes_nothing(
    decided: Path, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    before = _snapshot(decided)
    assert main(["queue", "list", "--run-dir", str(decided)]) == 0
    printed = capsys.readouterr().out
    assert printed == json.dumps(queue_listing(decided), indent=1, sort_keys=True) + "\n"
    assert _snapshot(decided) == before
    absent = tmp_path / "absent"
    assert main(["queue", "list", "--run-dir", str(absent)]) == 0
    assert json.loads(capsys.readouterr().out) == {"decided": [], "open": []}
    assert not absent.exists()


def test_queue_list_refuses_a_corrupt_queue_with_its_reason_and_no_traceback(
    decided: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    with (decided / DECISIONS_NAME).open("ab") as handle:
        handle.write(b"not a record\n")
    assert main(["queue", "list", "--run-dir", str(decided)]) == 2
    captured = capsys.readouterr()
    assert captured.out == ""
    refusal = json.loads(captured.err)
    assert refusal["error"] == "the approval queue holds a line this package could not have written"
    assert refusal["queue"].endswith(DECISIONS_NAME)
