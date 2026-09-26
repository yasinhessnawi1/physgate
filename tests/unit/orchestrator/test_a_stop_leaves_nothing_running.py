"""Stopping a session collects its whole process tree first, and leaves nothing running."""

from __future__ import annotations

import contextlib
import json
import subprocess
import sys
import time
from pathlib import Path

from loop_fakes import FakeDispatcher, KilledError, Rig, plan

from physgate.orchestrator.accounting import TokenAccount
from physgate.orchestrator.credentials import Credential
from physgate.orchestrator.dispatch import ClaudeDispatcher
from physgate.orchestrator.events import (
    LeftoverStopped,
    Resumed,
    StageEntered,
    TokensUsed,
    read_events,
)
from physgate.orchestrator.merge import RunGit
from physgate.orchestrator.ports import Leftover
from physgate.orchestrator.processes import started_at, stop_tree, tree
from physgate.orchestrator.protocols import MessageUsage, Usage

# A parent that starts a child in a process group of its own, as the Bash tool
# does, so a group kill of the parent would miss it. Both write their pid.
FAMILY = r"""
import os, signal, subprocess, sys, time
if sys.argv[2] == "stubborn":
    signal.signal(signal.SIGTERM, signal.SIG_IGN)
late = "import sys, time; time.sleep(60); open(sys.argv[1], 'w').write('late')"
child = subprocess.Popen([sys.executable, "-c", late, sys.argv[1] + ".late"],
    start_new_session=True)
open(sys.argv[1], "w").write(f"{os.getpid()} {child.pid}")
time.sleep(60)
"""


def family(
    tmp_path: Path, mode: str = "polite", session: str | None = None
) -> tuple[subprocess.Popen[bytes], int, int]:
    marker = tmp_path / "pids"
    # A session's own command line carries its session id, as the runtime's does.
    tag = ["--session-id", session] if session else []
    parent = subprocess.Popen([sys.executable, "-c", FAMILY, str(marker), mode, *tag])
    deadline = time.monotonic() + 10
    while not marker.exists() and time.monotonic() < deadline:
        time.sleep(0.05)
    pid, child = (int(x) for x in marker.read_text().split())
    return parent, pid, child


def test_the_tree_includes_a_child_in_its_own_process_group(tmp_path: Path) -> None:
    parent, pid, child = family(tmp_path)
    try:
        assert [p.pid for p in tree(pid)] == [pid, child]
    finally:
        stop_tree(pid)
        parent.wait()


def test_a_stop_leaves_neither_the_session_nor_its_child_running(tmp_path: Path) -> None:
    parent, pid, child = family(tmp_path)
    killed = stop_tree(pid, started_at(pid))
    parent.wait()
    assert started_at(pid) is None and started_at(child) is None
    assert killed == 1  # the child in its own group survived the SIGTERM and needed a kill


def test_a_session_that_ignores_sigterm_is_killed_after_the_grace(tmp_path: Path) -> None:
    parent, pid, child = family(tmp_path, "stubborn")
    killed = stop_tree(pid, started_at(pid))
    parent.wait()
    assert killed == 2 and started_at(pid) is None and started_at(child) is None


def test_a_pid_now_held_by_another_process_is_never_signalled(tmp_path: Path) -> None:
    parent, pid, child = family(tmp_path)
    try:
        assert stop_tree(pid, "Mon Jan  1 00:00:00 2001") == 0
        time.sleep(0.2)
        assert started_at(pid) is not None and started_at(child) is not None
    finally:
        stop_tree(pid)
        parent.wait()


def _dispatcher(run_dir: Path) -> ClaudeDispatcher:
    from orch_helpers import make_config

    return ClaudeDispatcher(
        config=make_config(),
        run=RunGit(repo=run_dir, run_dir=run_dir, run_id="run-1"),
        store_root=run_dir / "store",
        install_bin=run_dir / "bin" / "physgate",
        binary="/nonexistent/claude",
        base_url=None,
        credential=Credential("api_key", "sk-ant-test-dummy-not-a-credential"),
    )


def test_a_resume_stops_a_recorded_session_still_running_and_only_that(tmp_path: Path) -> None:
    parent, pid, child = family(tmp_path, session="live")
    sessions = tmp_path / "run" / "sessions"
    for sid, record in (
        ("live", {"pid": pid, "started": started_at(pid), "session_id": "live"}),
        ("reused", {"pid": pid, "started": "Mon Jan  1 00:00:00 2001", "session_id": "reused"}),
    ):
        (sessions / sid).mkdir(parents=True)
        (sessions / sid / "process.json").write_text(json.dumps(record))
    (sessions / "done").mkdir()
    (sessions / "done" / "process.json").write_text(json.dumps({"pid": 1, "session_id": "done"}))
    (sessions / "done" / "ended.json").write_text("{}")
    # What the live one spent before its orchestrator died: one message, final usage 9.
    start = {"input_tokens": 5, "output_tokens": 1}
    (sessions / "live" / "stdout.jsonl").write_text(
        "\n".join(
            json.dumps(e)
            for e in (
                {
                    "type": "stream_event",
                    "event": {"type": "message_start", "message": {"id": "m1", "usage": start}},
                },
                {
                    "type": "stream_event",
                    "event": {"type": "message_delta", "usage": {**start, "output_tokens": 9}},
                },
            )
        )
    )
    left = _dispatcher(tmp_path / "run").stop_leftovers()
    parent.wait()
    assert [(x.session_id, x.pid, x.killed, x.stopped) for x in left] == [
        ("live", pid, 1, True),
        ("reused", pid, 0, False),
    ]
    live = left[0]
    assert [(u.message_id, u.usage.output_tokens) for u in live.usage] == [("m1", 9)]
    assert live.complete is False and left[1].usage == ()
    assert started_at(pid) is None and started_at(child) is None
    assert json.loads((sessions / "reused" / "ended.json").read_text()) == {
        "not_running_at_resume": True
    }
    assert json.loads((sessions / "live" / "ended.json").read_text())["stopped_at_resume"]
    assert _dispatcher(tmp_path / "run").stop_leftovers() == []


SPENT = MessageUsage(
    message_id="m-old",
    usage=Usage(
        input_tokens=7, output_tokens=3, cache_read_input_tokens=11, cache_creation_input_tokens=13
    ),
)


class _LeftBehind(FakeDispatcher):
    def stop_leftovers(self) -> list[Leftover]:
        return [
            Leftover(
                session_id="sess-old",
                pid=4242,
                killed=1,
                stopped=True,
                usage=(SPENT,),
                complete=False,
            )
        ]


def test_a_resume_records_what_it_stopped_before_it_touches_the_attempt(tmp_path: Path) -> None:
    rig = Rig(tmp_path, dispatcher=_LeftBehind(kill_on=1))
    loop = rig.open()
    loop.start(plan("s1"))
    with contextlib.suppress(KilledError):
        loop.run()
    loop.close()
    rig.dispatcher.kill_on = None
    again = rig.open()
    again.resume()
    again.close()
    events = read_events(tmp_path / "events.jsonl")
    stops = [e for e in events if isinstance(e, LeftoverStopped)]
    (resumed,) = [e for e in events if isinstance(e, Resumed)]
    assert [(e.session_id, e.pid, e.killed) for e in stops] == [("sess-old", 4242, 1)] * 2
    later_stage = min(e.seq for e in events if isinstance(e, StageEntered) and e.seq > stops[1].seq)
    assert stops[1].seq < resumed.seq < later_stage
    # What the stopped session spent is in the account, marked partial.
    spent = [e for e in events if isinstance(e, TokensUsed) and e.attribution == "session:sess-old"]
    assert spent and all(e.partial and e.usage == SPENT.usage for e in spent)
    account = TokenAccount.from_events(events)
    assert account.by_attribution()["session:sess-old"] == SPENT.usage


def test_a_rewritten_process_record_never_points_the_stop_at_another_process(
    tmp_path: Path,
) -> None:
    # process.json is in the sessions directory, a file the session's own user can
    # write. A record rewritten to name another live process of that user, with
    # that process's true start time, must not get it signalled: it is not the
    # session, whose command line carries the session id.
    parent, pid, child = family(tmp_path)
    try:
        sessions = tmp_path / "run" / "sessions"
        (sessions / "forged").mkdir(parents=True)
        record = {"pid": pid, "started": started_at(pid), "session_id": "forged"}
        (sessions / "forged" / "process.json").write_text(json.dumps(record))
        (left,) = _dispatcher(tmp_path / "run").stop_leftovers()
        assert (left.session_id, left.stopped, left.killed) == ("forged", False, 0)
        time.sleep(0.5)
        assert started_at(pid) is not None and started_at(child) is not None
        assert json.loads((sessions / "forged" / "ended.json").read_text()) == {
            "not_running_at_resume": True
        }
    finally:
        stop_tree(pid)
        parent.wait()
