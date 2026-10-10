"""One function records every decision: locked, beneath the run directory, never creating.

``record_decision`` is what ``physgate queue resolve``, ``ApprovalQueue.resolve`` and the
operator UI all call. These tests hold it to what it promises:

- one line, the record's own JSON, appended and synced, and nothing else written;
- a refusal writes nothing and creates nothing;
- every file is opened beneath the run directory and never through a link, so a swapped
  file, or a run directory swapped after the walk reached it, cannot redirect the write;
- two deciders cannot both find an item open, and a decider killed while it holds the lock
  does not hold it any longer;
- a torn tail is cut only by a decider holding the lock; the loop's own reading leaves it;
- a decision sent with what was shown is refused when the item or its trajectories changed.
"""

from __future__ import annotations

import json
import os
import shutil
import signal
import subprocess
import sys
import threading
import time
from pathlib import Path

import pytest
from loop_fakes import FakeDispatcher, FakeGate, Rig, plan

from physgate.cli import main
from physgate.orchestrator import queue as queue_module
from physgate.orchestrator.events import read_events
from physgate.orchestrator.exceptions import QueueError, StaleViewError
from physgate.orchestrator.queue import (
    DECISIONS_NAME,
    QUEUE_NAME,
    ApprovalQueue,
    QueueResolution,
    ShownItem,
    decision_text,
    read_queue,
    record_decision,
    trajectory_statuses,
)
from physgate.ui.paths import Allowlist

ITEM = "run-1-s1"


@pytest.fixture
def run_dir(tmp_path: Path) -> Path:
    """Two escalated subtasks, both open, each attempt's stream real and sealed."""
    run = tmp_path / "runs" / "run"
    run.mkdir(parents=True)
    rig = Rig(run, dispatcher=FakeDispatcher(trajectories=run / "sessions"))
    rig.gate = FakeGate(verdicts=["fail"] * 6 + ["pass"])
    loop = rig.open()
    loop.start(plan("s1", "s2", "s3"))
    assert loop.run().kind == "done"
    loop.close()
    return run


def _snapshot(root: Path) -> dict[str, bytes | None]:
    if not root.exists():
        return {"<absent>": None}
    return {
        str(p.relative_to(root)): (p.read_bytes() if p.is_file() and not p.is_symlink() else None)
        for p in sorted(root.rglob("*"))
    }


def _decide(
    run: Path, item: str = ITEM, *, shown: ShownItem | None = None, dir_fd: int | None = None
) -> QueueResolution:
    return record_decision(
        run, item, decision="approve", resolved_by="yasin", shown=shown, dir_fd=dir_fd
    )


def _shown(run: Path, item: str = ITEM) -> ShownItem:
    view = read_queue(run)
    found = next(i for i in view.items if i.item_id == item)
    events = read_events(run / "events.jsonl")

    def read(session_id: str) -> bytes | None:
        path = run / "sessions" / session_id / "stdout.jsonl"
        return path.read_bytes() if path.exists() else None

    return ShownItem(
        item_sha256=view.digests[item], trajectories=trajectory_statuses(found, events, read)
    )


# -- the decision text ---------------------------------------------------------------------


def test_the_decision_text_is_the_verb_and_the_note_and_a_rejection_must_say_why() -> None:
    assert decision_text("approve", "") == "approve"
    assert decision_text("approve", "  ") == "approve"
    assert decision_text("approve", "fine as it is") == "approve: fine as it is"
    assert decision_text("reject", "split it") == "reject: split it"
    for note in ("", " \n"):
        with pytest.raises(QueueError, match="note is required"):
            decision_text("reject", note)
    with pytest.raises(QueueError, match="approve or to reject"):
        decision_text("defer", "x")  # type: ignore[arg-type]


# -- one line, and nothing else ---------------------------------------------------------------


def test_a_decision_is_one_synced_line_of_its_own_json_and_nothing_else_changes(
    run_dir: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    before = _snapshot(run_dir)
    synced: list[int] = []
    real_fsync = os.fsync

    def recording_fsync(fd: int) -> None:
        synced.append(os.fstat(fd).st_ino)
        real_fsync(fd)

    monkeypatch.setattr(os, "fsync", recording_fsync)
    record = _decide(run_dir)
    after = _snapshot(run_dir)
    assert {k for k in after if after[k] != before.get(k)} == {DECISIONS_NAME}
    written, earlier = after[DECISIONS_NAME], before[DECISIONS_NAME]
    assert written is not None and earlier is not None
    assert written[len(earlier) :] == record.model_dump_json().encode() + b"\n"
    assert synced == [os.stat(run_dir / DECISIONS_NAME).st_ino]


@pytest.mark.parametrize(
    ("item", "kw", "reason"),
    [
        ("nope", {}, "not an open item"),
        (ITEM, {"decision": ""}, "not one the queue can record"),
        (ITEM, {"resolved_by": ""}, "not one the queue can record"),
    ],
)
def test_a_refused_decision_writes_nothing(
    run_dir: Path, item: str, kw: dict[str, str], reason: str
) -> None:
    before = _snapshot(run_dir)
    args = {"decision": "approve", "resolved_by": "yasin", **kw}
    with pytest.raises(QueueError, match=reason):
        record_decision(run_dir, item, **args)  # type: ignore[arg-type]
    assert _snapshot(run_dir) == before


def test_a_second_decision_on_an_item_is_refused(run_dir: Path) -> None:
    _decide(run_dir)
    before = _snapshot(run_dir)
    with pytest.raises(QueueError, match="not an open item"):
        _decide(run_dir)
    assert _snapshot(run_dir) == before


def test_a_run_with_no_queue_or_no_directory_is_refused_and_nothing_is_created(
    tmp_path: Path,
) -> None:
    empty = tmp_path / "empty"
    empty.mkdir()
    for run in (empty, tmp_path / "absent"):
        with pytest.raises(QueueError, match="not an open item"):
            _decide(run)
    assert list(empty.iterdir()) == []
    assert not (tmp_path / "absent").exists()


# -- swaps beneath the run directory ----------------------------------------------------------


@pytest.fixture
def outside(tmp_path: Path, run_dir: Path) -> Path:
    """A copy of the run outside its directory, the target every swap below aims at."""
    target = tmp_path / "outside"
    shutil.copytree(run_dir, target)
    return target


def _link(at: Path, to: Path) -> None:
    at.rename(at.with_name(at.name + ".moved"))
    at.symlink_to(to)


def test_a_decisions_file_swapped_for_a_link_is_refused_before_its_target_is_locked(
    run_dir: Path, outside: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Refused at the first open, before any lock is taken.

    The later checks would still refuse the decision (the read is never through a link, and
    the locked and the read file are compared), but by then a following open would have
    opened the link's target for writing and locked it, and a lock on another run's decisions
    file stalls everyone deciding there.
    """
    _link(run_dir / DECISIONS_NAME, outside / DECISIONS_NAME)
    locked: list[str] = []
    monkeypatch.setattr(queue_module, "_checked", locked.append)
    before = _snapshot(outside)
    with pytest.raises(QueueError, match="not a plain file"):
        _decide(run_dir)
    assert locked == [], "the link's target was opened for writing and locked"
    assert _snapshot(outside) == before


def test_an_items_file_swapped_for_a_link_is_refused(run_dir: Path, outside: Path) -> None:
    _link(run_dir / QUEUE_NAME, outside / QUEUE_NAME)
    before = _snapshot(run_dir)
    with pytest.raises(QueueError, match="not a plain file"):
        _decide(run_dir)
    assert _snapshot(run_dir) == before


def test_a_decisions_file_with_a_second_name_or_that_is_a_directory_is_refused(
    run_dir: Path, tmp_path: Path
) -> None:
    os.link(run_dir / DECISIONS_NAME, tmp_path / "second-name")
    with pytest.raises(QueueError, match="not a plain file"):
        _decide(run_dir)
    (tmp_path / "second-name").unlink()
    (run_dir / DECISIONS_NAME).unlink()
    (run_dir / DECISIONS_NAME).mkdir()
    with pytest.raises(QueueError, match="not a plain file"):
        _decide(run_dir)


def test_a_decisions_file_replaced_between_its_lock_and_its_read_is_refused(
    run_dir: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    opened = queue_module._open_in

    def replace_before_reading(dir_fd: int, name: str, flags: int) -> int:
        if name == DECISIONS_NAME and not flags & os.O_WRONLY:
            path = run_dir / DECISIONS_NAME
            data = path.read_bytes()
            path.rename(path.with_name("locked-one"))
            path.write_bytes(data)
        return opened(dir_fd, name, flags)

    monkeypatch.setattr(queue_module, "_open_in", replace_before_reading)
    with pytest.raises(QueueError, match="replaced while the decision was being made"):
        _decide(run_dir)
    assert (run_dir / DECISIONS_NAME).read_bytes() == (run_dir / "locked-one").read_bytes()


def test_a_run_directory_swapped_after_the_walk_still_takes_the_decision_where_it_was_walked(
    run_dir: Path, outside: Path
) -> None:
    """A run directory swapped after the walk cannot move the decision.

    This is the operator UI's path: the walk reaches the run, then its name is swapped for a
    link to another copy. The decision lands in the directory the walk reached, and the copy
    is untouched.
    """
    allow = Allowlist.build([str(run_dir.parent)], held_out=[], answer_keys=[], harness=None)
    before = _snapshot(outside)
    with allow.opened_directory(run_dir) as fd:
        _link(run_dir, outside)
        record_decision(run_dir, ITEM, decision="approve", resolved_by="yasin", dir_fd=fd)
    assert _snapshot(outside) == before
    walked = run_dir.with_name("run.moved")
    assert [d.item_id for _, d in read_queue(walked).decisions] == [ITEM]


# -- the lock ---------------------------------------------------------------------------------


def test_two_deciders_cannot_both_find_an_item_open(
    run_dir: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The first decider, holding the lock, waits for the second to reach the same point.

    With the lock the second cannot reach it until the first has written, so the wait times
    out and the second then finds the item decided. Without the lock both find it open and
    both append, and the second line makes the file unreadable.
    """
    first_holds = threading.Event()
    second_checked = threading.Event()
    calls: list[str] = []

    def checked(item_id: str) -> None:
        name = threading.current_thread().name
        calls.append(name)
        if name == "first":
            first_holds.set()
            second_checked.wait(timeout=0.5)
        else:
            second_checked.set()

    monkeypatch.setattr(queue_module, "_checked", checked)
    outcomes: dict[str, str] = {}

    def decide(name: str) -> None:
        try:
            _decide(run_dir)
            outcomes[name] = "decided"
        except QueueError as exc:
            outcomes[name] = str(exc)

    first = threading.Thread(target=decide, args=("first",), name="first")
    first.start()
    assert first_holds.wait(timeout=5)
    second = threading.Thread(target=decide, args=("second",), name="second")
    second.start()
    first.join(timeout=10)
    second.join(timeout=10)
    assert calls == ["first", "second"]
    assert outcomes == {
        "first": "decided",
        "second": f"a decision on {ITEM!r}, which is not an open item",
    }
    assert [d.item_id for _, d in read_queue(run_dir).decisions] == [ITEM]


def test_six_commands_deciding_one_item_at_once_record_exactly_one_decision(
    run_dir: Path,
) -> None:
    entry = "import sys; from physgate.cli import main; sys.exit(main(sys.argv[1:]))"
    command = [sys.executable, "-c", entry, "queue", "resolve", ITEM, "--run-dir", str(run_dir)]
    command += ["--decision", "approve", "--by", "yasin"]
    started = [
        subprocess.Popen(command, stdout=subprocess.PIPE, stderr=subprocess.PIPE) for _ in range(6)
    ]
    codes = sorted(p.wait(timeout=60) for p in started)
    assert codes == [0, 2, 2, 2, 2, 2]
    assert [d.item_id for _, d in read_queue(run_dir).decisions] == [ITEM]


_HOLD = """
import sys, time
from pathlib import Path
from physgate.orchestrator import queue
def held(item_id):
    Path(sys.argv[2]).write_text("holding")
    time.sleep(60)
queue._checked = held
queue.record_decision(Path(sys.argv[1]), "run-1-s1", decision="approve", resolved_by="killed")
"""


def test_a_decider_killed_while_it_holds_the_lock_leaves_no_lock_and_no_line(
    run_dir: Path, tmp_path: Path
) -> None:
    marker = tmp_path / "holding"
    child = subprocess.Popen([sys.executable, "-c", _HOLD, str(run_dir), str(marker)])
    try:
        deadline = time.monotonic() + 30
        while not marker.exists():
            assert time.monotonic() < deadline, "the child never took the lock"
            time.sleep(0.02)
        child.send_signal(signal.SIGKILL)
        child.wait(timeout=10)
    finally:
        if child.poll() is None:
            child.kill()
    before = (run_dir / DECISIONS_NAME).read_bytes()
    result: list[object] = []
    decider = threading.Thread(target=lambda: result.append(_decide(run_dir)))
    decider.start()
    decider.join(timeout=10)
    assert result, "the lock outlived the process that held it"
    assert (run_dir / DECISIONS_NAME).read_bytes().startswith(before)
    assert [d.resolved_by for _, d in read_queue(run_dir).decisions] == ["yasin"]


# -- a torn tail -------------------------------------------------------------------------------

TORN = b'{"kind":"resolution","item_id":"run-1-s2","ts":"2026-10-10T00:00'


def test_a_torn_tail_is_left_by_the_loop_s_reading_and_cut_only_by_a_decider(
    run_dir: Path,
) -> None:
    with (run_dir / DECISIONS_NAME).open("ab") as handle:
        handle.write(TORN)
    torn = (run_dir / DECISIONS_NAME).read_bytes()
    queue = ApprovalQueue(run_dir / QUEUE_NAME)
    queue.refresh()
    assert (run_dir / DECISIONS_NAME).read_bytes() == torn, "the loop's reading cut a tail"
    assert [i.item_id for i in queue.open_items()] == [ITEM, "run-1-s2"]
    record = _decide(run_dir)
    assert (run_dir / DECISIONS_NAME).read_bytes() == (
        torn[: -len(TORN)] + record.model_dump_json().encode() + b"\n"
    )
    assert [d.item_id for _, d in read_queue(run_dir).decisions] == [ITEM]


def test_the_items_file_s_torn_tail_is_still_cut_by_its_one_writer(run_dir: Path) -> None:
    whole = (run_dir / QUEUE_NAME).read_bytes()
    with (run_dir / QUEUE_NAME).open("ab") as handle:
        handle.write(b'{"kind":"item","item_id":"x')
    ApprovalQueue(run_dir / QUEUE_NAME)
    assert (run_dir / QUEUE_NAME).read_bytes() == whole


# -- what was shown ---------------------------------------------------------------------------


def test_every_trajectory_status_is_told_apart(run_dir: Path) -> None:
    item = next(i for i in read_queue(run_dir).items if i.item_id == ITEM)
    events = read_events(run_dir / "events.jsonl")
    streams = {Path(link).parent.name: Path(link).read_bytes() for link in item.trajectories}
    first, second, third = (Path(link).parent.name for link in item.trajectories)

    def read(session_id: str) -> bytes | None:
        if session_id == second:
            return streams[session_id] + b"tampered"
        if session_id == third:
            return None
        return streams[session_id]

    assert trajectory_statuses(item, events, read) == ("holds", "tampered", "missing")
    foreign = item.model_copy(
        update={"trajectories": ("/elsewhere/stdout.jsonl", "sessions/x y/stdout.jsonl")}
    )
    assert trajectory_statuses(foreign, events, read) == ("not_in_this_run", "not_in_this_run")
    unsealed = item.model_copy(update={"trajectories": ("sessions/never-ended/stdout.jsonl",)})
    assert trajectory_statuses(unsealed, events, read) == ("no_seal",)

    def refused(session_id: str) -> bytes | None:
        raise OSError("a link")

    assert set(trajectory_statuses(item, events, refused)) == {"tampered"}


def test_a_decision_on_the_view_as_shown_is_recorded(run_dir: Path) -> None:
    shown = _shown(run_dir)
    assert shown.trajectories == ("holds", "holds", "holds")
    _decide(run_dir, shown=shown)
    assert [d.item_id for _, d in read_queue(run_dir).decisions] == [ITEM]


def test_a_decision_on_a_view_of_a_different_item_line_is_refused(run_dir: Path) -> None:
    shown = _shown(run_dir).model_copy(update={"item_sha256": "0" * 64})
    before = _snapshot(run_dir)
    with pytest.raises(StaleViewError, match="no longer the one that was shown"):
        _decide(run_dir, shown=shown)
    assert _snapshot(run_dir) == before


def test_a_decision_on_a_view_whose_trajectory_was_tampered_since_is_refused(
    run_dir: Path,
) -> None:
    shown = _shown(run_dir)
    item = next(i for i in read_queue(run_dir).items if i.item_id == ITEM)
    with Path(item.trajectories[1]).open("ab") as handle:
        handle.write(b"{}\n")
    before = _snapshot(run_dir)
    with pytest.raises(StaleViewError, match="trajectory of the item is no longer"):
        _decide(run_dir, shown=shown)
    assert _snapshot(run_dir) == before


def test_a_trajectory_swapped_for_a_link_reads_as_tampered_under_the_lock(
    run_dir: Path, tmp_path: Path
) -> None:
    shown = _shown(run_dir)
    item = next(i for i in read_queue(run_dir).items if i.item_id == ITEM)
    stream = Path(item.trajectories[0])
    copy = tmp_path / "copy.jsonl"
    copy.write_bytes(stream.read_bytes())
    _link(stream, copy)
    with pytest.raises(StaleViewError) as refused:
        _decide(run_dir, shown=shown)
    assert refused.value.context["now"] == "tampered,holds,holds"


# -- every caller goes through it -------------------------------------------------------------


def test_the_writer_class_and_the_command_decide_through_the_one_function(
    run_dir: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    calls: list[str] = []
    real = queue_module.record_decision

    def counted(*args: object, **kw: object) -> object:
        calls.append(str(args[1]))
        return real(*args, **kw)  # type: ignore[arg-type]

    monkeypatch.setattr(queue_module, "record_decision", counted)
    ApprovalQueue(run_dir / QUEUE_NAME).resolve(ITEM, decision="approve", resolved_by="yasin")
    from physgate.orchestrator import cli as cli_module

    monkeypatch.setattr(cli_module, "record_decision", counted)
    code = main(["queue", "resolve", "run-1-s2", "--run-dir", str(run_dir),
                 "--decision", "reject: split it", "--by", "yasin"])  # fmt: skip
    assert code == 0
    assert json.loads(capsys.readouterr().out)["resolved"]["decision"] == "reject: split it"
    assert calls == [ITEM, "run-1-s2"]


def test_the_writer_class_refuses_an_items_file_of_another_name(tmp_path: Path) -> None:
    with pytest.raises(QueueError, match="always named the same"):
        ApprovalQueue(tmp_path / "items.jsonl")
    assert list(tmp_path.iterdir()) == []
