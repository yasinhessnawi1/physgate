"""Tests of streams.py (§2.4, §2.5, §10) and watch_limit.sh: invented streams and roots.

Run explicitly, from the repository root: ``uv run pytest -q experiments/R-PG-03``.
"""

from __future__ import annotations

import json
import os
import platform
import subprocess
import sys
import threading
import time
from pathlib import Path

import pytest

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
import common  # noqa: E402
import fixture as fx  # noqa: E402
import streams as st  # noqa: E402

SHEET = (
    json.dumps(
        {"label": "x", "rows": {"R1.01": {"quantity": "a"}, "R11.04": {"quantity": "b"}}}, indent=1
    )
    + "\n"
).encode()
TOTAL, LAST = st.sheet_shape(SHEET)
PATH = "/w/worktree/parts_sheet.json"


def classes(*events: dict[str, object]) -> list[str]:
    got = st.session_reads_text(fx.stream(*events), TOTAL, LAST)
    return [c for c in st.CLASSES for _ in range(got[c])]


def test_the_sheet_s_numbered_lines_count_the_empty_line_after_the_last_newline() -> None:
    assert (SHEET.count(b"\n") + 1, "R11.04") == (TOTAL, LAST)


def test_a_whole_read_and_a_part_read() -> None:
    assert classes(fx.read_call("t1", PATH), fx.tool_result("t1", fx.numbered(SHEET))) == ["whole"]
    assert classes(
        fx.read_call("t1", PATH, offset=1, limit=3), fx.tool_result("t1", fx.numbered(SHEET, 1, 3))
    ) == ["part"]


@pytest.mark.parametrize(
    "text",
    [
        "fewer",
        "no-last-row",
        "token-limit",
    ],
)
def test_a_cut_read(text: str) -> None:
    if text == "fewer":
        body = fx.numbered(SHEET, 1, TOTAL - 3)
    elif text == "no-last-row":
        body = fx.numbered(SHEET).replace('"R11.04"', '"R11.05"')
    else:
        body = "File content (25,001 tokens) exceeds maximum allowed tokens (25000)."
    assert classes(fx.read_call("t1", PATH), fx.tool_result("t1", body)) == ["cut"]


def test_an_unchanged_stub_is_unchanged_only_after_a_read_of_its_range() -> None:
    stub = st.UNCHANGED[0]
    after = classes(
        fx.read_call("t1", PATH),
        fx.tool_result("t1", fx.numbered(SHEET)),
        fx.read_call("t2", PATH),
        fx.tool_result("t2", stub),
    )
    assert after == ["whole", "unchanged"]
    assert classes(fx.read_call("t2", PATH), fx.tool_result("t2", stub)) == ["cut"]


def test_an_error_and_a_read_with_no_result() -> None:
    assert classes(fx.read_call("t1", PATH), fx.tool_result("t1", "no such file", True)) == [
        "error"
    ]
    assert classes(fx.read_call("t1", PATH)) == ["no_result"]


def test_a_read_of_another_file_is_not_a_read_of_the_sheet() -> None:
    assert classes(fx.read_call("t1", "/w/worktree/notes.md"), fx.tool_result("t1", "x")) == []


def _session(root: Path, sid: str, text: str) -> None:
    d = root / sid / "session"
    d.mkdir(parents=True)
    (d / "stdout.jsonl").write_text(text)


def _run(tmp: Path, sids: list[str]) -> Path:
    run = tmp / "run"
    (run / "controls").mkdir(parents=True)
    lines = [{"kind": "review_ran", "subtask_id": "r1", "result": {"session_id": s}} for s in sids]
    (run / "events.jsonl").write_text("".join(json.dumps(x) + "\n" for x in lines))
    (run / "controls" / "events.jsonl").write_text("")
    return run


def test_the_block_check_reads_every_lane_s_sessions_and_counts_a_cut(tmp_path: Path) -> None:
    a, b, c = fx.session_of(1), fx.session_of(2), fx.session_of(3)
    scratch = tmp_path / "scratch"
    whole = fx.stream(fx.read_call("t1", PATH), fx.tool_result("t1", fx.numbered(SHEET)))
    cut = fx.stream(fx.read_call("t1", PATH), fx.tool_result("t1", fx.numbered(SHEET, 1, 2)))
    _session(scratch / "lane-0", a, whole)
    _session(scratch / "lane-1", b, cut)
    _session(scratch / "lane-1", c, whole)  # under a root, named by no log
    got = st.block_counts(_run(tmp_path, [a, b]), scratch, "A2", SHEET)
    assert got["lane_roots"] == 2 and got["cut"] == 1
    assert got["sides"]["injected"]["whole"] == 1 and got["sides"]["not_in_a_log"]["reviews"] == 1


def test_a_session_behind_a_symlink_is_never_read(tmp_path: Path) -> None:
    a = fx.session_of(1)
    scratch, elsewhere = tmp_path / "scratch", tmp_path / "elsewhere"
    _session(elsewhere, a, fx.stream(fx.read_call("t1", PATH), fx.tool_result("t1", "x")))
    scratch.mkdir()
    os.symlink(elsewhere / a, scratch / a)
    got = st.block_counts(_run(tmp_path, [a]), scratch, "A2", SHEET)
    assert got["symlinks_refused"] == 1 and got["sides"]["injected"]["stream_missing_unknown"] == 1


def test_the_cli_exits_3_on_a_cut(tmp_path: Path) -> None:
    a = fx.session_of(1)
    scratch = tmp_path / "scratch"
    _session(
        scratch,
        a,
        fx.stream(fx.read_call("t1", PATH), fx.tool_result("t1", fx.numbered(SHEET, 1, 2))),
    )
    (tmp_path / "sheet.json").write_bytes(SHEET)
    done = subprocess.run(
        [
            sys.executable,
            "-I",
            str(HERE / "streams.py"),
            "block",
            "--sheet",
            str(tmp_path / "sheet.json"),
            "--arm",
            "B",
            "--run",
            str(_run(tmp_path, [a])),
            "--scratch",
            str(scratch),
        ],
        capture_output=True,
        text=True,
        check=False,
        cwd=common.REPO,
    )
    assert done.returncode == 3 and json.loads(done.stdout)["cut"] == 1


@pytest.mark.parametrize(
    ("result", "stderr", "ended"),
    [
        (None, "", "completed"),
        ({"type": "result", "subtype": "error_max_turns", "is_error": True}, "", "completed"),
        ({}, "", "infrastructure"),
        (
            {"type": "result", "subtype": "success", "is_error": True, "api_error_status": 529},
            "",
            "infrastructure",
        ),
        (
            {"type": "result", "subtype": "error_during_execution", "is_error": True},
            "",
            "infrastructure",
        ),
        (None, "API Error: usage_limit_reached", "usage_limit"),
    ],
    ids=[
        "a-turn-that-ended",
        "the-turn-bound",
        "no-result",
        "an-api-error",
        "a-binary-error",
        "a-usage-limit",
    ],
)
def test_how_an_authoring_turn_ended(
    result: dict[str, object] | None, stderr: str, ended: str
) -> None:
    text = fx.stream(result=result) if result != {} else fx.stream(result={})
    assert st.author_end(text, stderr, 0)["ended"] == ended


def test_usage_limit_facts_count_files_and_429s_and_follow_no_symlink(tmp_path: Path) -> None:
    d = tmp_path / "d"
    d.mkdir()
    (d / "a.jsonl").write_text('{"x": "usage_limit_reached"}\n{"api_error_status": 429}\n')
    (d / "b.txt").write_text("nothing\n")
    outside = tmp_path / "outside.json"
    outside.write_text("usage_limit_reached")
    os.symlink(outside, d / "c.json")
    assert st.limit_counts([d]) == {"usage_limit_files": 1, "status_429s": 1}


# ---- watch_limit.sh ----------------------------------------------------------------------------


def watch(tmp: Path, kind: str, write_limit: bool) -> str:
    d = tmp / "watched"
    d.mkdir()
    sleeper = subprocess.Popen(["sleep", "5"], start_new_session=True)
    # Reaped as soon as it ends, as the launcher reaps its arms, so no zombie looks alive.
    reaper = threading.Thread(target=sleeper.wait, daemon=True)
    reaper.start()
    env = {**os.environ, "RP3_WATCH_SECONDS": "1"}
    log = tmp / "watcher.log"
    w = subprocess.Popen(
        ["bash", str(HERE / "watch_limit.sh"), str(log), kind, str(sleeper.pid), str(d)], env=env
    )
    if write_limit:
        time.sleep(1.5)
        (d / "s.jsonl").write_text('{"error": "usage_limit_reached"}\n')
    w.wait(timeout=30)
    reaper.join(timeout=30)
    return log.read_text() if log.exists() else ""


def test_the_watcher_notes_an_end_with_no_limit(tmp_path: Path) -> None:
    assert "WATCHER" in watch(tmp_path, "reality", write_limit=False)


@pytest.mark.skipif(platform.system() == "Linux", reason="off the run machine it signals nothing")
def test_a_block_s_watcher_aborts_at_a_limit_and_signals_nothing_off_the_run_machine(
    tmp_path: Path,
) -> None:
    log = watch(tmp_path, "block", write_limit=True)
    assert "ABORT" in log and "nothing signalled off the run machine" in log


def as_the_run_machine(tmp: Path) -> dict[str, str]:
    """An environment whose ``uname -s`` says Linux, so the watcher acts as on the run machine."""
    shims = tmp / "linux-shims"
    shims.mkdir(exist_ok=True)
    (shims / "uname").write_text(
        '#!/bin/sh\n[ "${1:-}" = -s ] && { echo Linux; exit 0; }\nexec /usr/bin/uname "$@"\n'
    )
    (shims / "uname").chmod(0o755)
    return {**os.environ, "PATH": f"{shims}:{os.environ['PATH']}", "RP3_WATCH_SECONDS": "1"}


def step_under_watch(
    tmp: Path, kind: str, step: str, env: dict[str, str], dirs: int = 1
) -> tuple[subprocess.CompletedProcess[str], str]:
    """One step (``sh -c step <dir>``) in a session of its own, under the watcher of ``kind``."""
    d = tmp / "watched"
    d.mkdir(exist_ok=True)
    extra = [str(tmp / "scratch")] if dirs == 2 else []
    if extra:
        Path(extra[0]).mkdir(exist_ok=True)
    proc = subprocess.Popen(["sh", "-c", step, "x", str(d)], start_new_session=True)
    reaper = threading.Thread(target=proc.wait, daemon=True)
    reaper.start()
    log = tmp / f"watcher-{kind}.log"
    done = subprocess.run(
        ["bash", str(HERE / "watch_limit.sh"), str(log), kind, str(proc.pid), str(d), *extra],
        capture_output=True,
        text=True,
        env=env,
        check=False,
        timeout=120,
    )
    reaper.join(timeout=30)
    return done, log.read_text() if log.exists() else ""


@pytest.mark.parametrize("kind", ["authoring", "reality"])
def test_a_limit_an_earlier_step_left_is_never_counted_again(tmp_path: Path, kind: str) -> None:
    # The cut turn's stream (or a failed reading call's file) is kept for good in the directory the
    # next step is watched over: only what is written after the watcher starts counts.
    (tmp_path / "watched").mkdir()
    (tmp_path / "watched" / "03-continue.stream.jsonl").write_text(
        '{"error": "usage_limit_reached"}\n'
    )
    old = time.time() - 600
    os.utime(tmp_path / "watched" / "03-continue.stream.jsonl", (old, old))
    done, log = step_under_watch(
        tmp_path, kind, 'sleep 3; echo ended > "$1/after.txt"', as_the_run_machine(tmp_path)
    )
    assert "ABORT" not in log and "LIMIT" not in log, log
    assert (tmp_path / "watched" / "after.txt").read_text() == "ended\n"
    assert "WATCHER" in log and "usage_limit_reached files 0" in log


@pytest.mark.parametrize("kind", ["authoring", "reality"])
def test_a_step_whose_session_ends_on_a_limit_is_left_to_finish_its_bookkeeping(
    tmp_path: Path, kind: str
) -> None:
    # The session has already ended on the limit; the step's own records (outcome, audit, state,
    # or the failed call's file and STOPPED) are still to be written: a kill there loses them.
    # The session runs a while, then its stream ends on the limit.
    step = (
        'sleep 1.5; echo \'{"error": "usage_limit_reached"}\' > "$1/01-launch.stream.jsonl"; '
        'sleep 3; echo written > "$1/01-launch.outcome.json"'
    )
    done, log = step_under_watch(tmp_path, kind, step, as_the_run_machine(tmp_path))
    assert (tmp_path / "watched" / "01-launch.outcome.json").read_text() == "written\n", log
    assert "LIMIT" in log and "usage_limit_reached files 1" in log and "ABORT" not in log


def test_a_block_s_watcher_still_stops_every_arm_at_the_first_limit(tmp_path: Path) -> None:
    step = (
        'echo \'{"error": "usage_limit_reached"}\' > "$1/s.jsonl"; '
        'sleep 6; echo written > "$1/after.txt"'
    )
    done, log = step_under_watch(tmp_path, "block", step, as_the_run_machine(tmp_path), dirs=2)
    assert "ABORT" in log and "everything watched stopped" in log
    assert not (tmp_path / "watched" / "after.txt").exists()


def test_the_watcher_refuses_an_unknown_kind(tmp_path: Path) -> None:
    done = subprocess.run(
        ["bash", str(HERE / "watch_limit.sh"), str(tmp_path / "l"), "other", "1", "/x"],
        capture_output=True,
        text=True,
        check=False,
    )
    assert done.returncode == 2
