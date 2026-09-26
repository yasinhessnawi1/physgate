"""SIGKILL mid-append loses no acknowledged event and leaves a log that opens.

Every emit is synced before it returns, so any line the parent has seen on disk
before the kill was acknowledged. The kill is anchored to a seeded count of those
lines, not to a clock, and the child being alive when the signal is sent is
asserted per seed: a kill that lands after the child finished proves nothing.

This proves process-crash durability only. That the sync happens is asserted by
a separate unit test, because a kill cannot tell a synced write from a flushed
one.
"""

from __future__ import annotations

import random
import signal
import subprocess
import sys
import time
from pathlib import Path

import pytest

from physgate.orchestrator.events import EventLog, StageEntered, read_events

pytestmark = pytest.mark.integration

HERE = Path(__file__).resolve().parent
SEEDS = (1, 2, 3, 4, 5)


def complete_lines(path: Path) -> int:
    return path.read_bytes().count(b"\n") if path.exists() else 0


@pytest.mark.parametrize("seed", SEEDS)
def test_a_kill_mid_append_keeps_every_acknowledged_line(seed: int, tmp_path: Path) -> None:
    path = tmp_path / "events.jsonl"
    target = random.Random(20_000 + seed).randint(200, 800)
    child = subprocess.Popen([sys.executable, str(HERE / "event_crash_child.py"), str(path)])
    deadline = time.monotonic() + 60
    while complete_lines(path) < target and time.monotonic() < deadline:
        time.sleep(0.001)
    acknowledged = complete_lines(path)
    alive = child.poll() is None
    child.send_signal(signal.SIGKILL)
    child.wait()
    assert alive, "the child was not running when the kill was sent: this seed proved nothing"
    assert acknowledged >= target

    size_after_kill = path.stat().st_size
    log = EventLog(path, run_id="crash", gate_mode="on")
    torn = log.torn_tail_bytes
    assert len(log.events) >= acknowledged
    assert [e.seq for e in log.events] == list(range(len(log.events)))
    log.emit(StageEntered, subtask_id="s1", attempt=1, stage="resolve")
    log.close()
    reread = read_events(path)
    assert len(reread) == len(log.events)
    assert reread[-1].seq == len(reread) - 1
    # Report what the kill reached rather than pretend: a torn tail needs the kill
    # to land inside one write call, which a single short write makes rare.
    print(
        f"seed {seed}: target {target}, acknowledged {acknowledged}, "
        f"torn tail {torn} bytes of {size_after_kill}"
    )
