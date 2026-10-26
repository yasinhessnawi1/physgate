"""Tests of ledger.py (§10): R-PG-01b's lines, each kind of line, the 5-hour projection.

Run explicitly, from the repository root: ``uv run pytest -q experiments/R-PG-03``.
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
import common  # noqa: E402
import fixture as fx  # noqa: E402
import ledger as lg  # noqa: E402

NOW = lg.seconds("2026-11-05T12:00:00Z")


def line(start: str, end: str | None, tokens: int | None, kind: str = "block") -> dict[str, object]:
    return {
        "kind": kind,
        "label": f"{kind} {start}",
        "started_utc": start,
        "ended_utc": end,
        "tokens_every_try": tokens,
    }


def test_r_pg_01b_s_lines_are_copied_as_counts_and_a_missing_total_says_so(tmp_path: Path) -> None:
    r1 = tmp_path / "ledger-round-1.json"
    r1.write_text(
        json.dumps(
            {
                "round": 1,
                "review_tokens": 100,
                "smoke_tokens": 5,
                "attempts": 1,
                "started_utc": "2026-10-29T08:00:00Z",
                "ended_utc": "2026-10-29T15:00:00Z",
            }
        )
    )
    r2 = tmp_path / "ledger-round-2.json"
    r2.write_text(
        json.dumps({"round": 2, "started_utc": "2026-10-30T08:00:00Z", "ended_utc": None})
    )
    reality = tmp_path / "reasons.jsonl"
    reality.write_text(
        '{"tokens": 7, "utc": "2026-10-31T08:00:00Z"}\n'
        '{"tokens": 3, "utc": "2026-10-31T09:00:00Z"}\n'
    )
    got = lg.rpg01b_lines([r1, r2], reality)
    assert [x["tokens_every_try"] for x in got] == [105, None, 10]
    assert got[1]["no_total"] is True and got[2]["started_utc"] == "2026-10-31T08:00:00Z"


def test_a_line_whose_span_overlaps_the_trailing_5_hours_counts_in_full() -> None:
    lines = [
        line("2026-11-05T05:00:00Z", "2026-11-05T07:30:00Z", 10),  # ends inside the window
        line("2026-11-05T01:00:00Z", "2026-11-05T06:59:00Z", 20),  # ends just before it
        line("2026-11-05T11:00:00Z", "2026-11-05T11:30:00Z", 30),
    ]
    got = lg.trailing(lines, NOW)
    assert got["tokens"] == 40 and got["lines_in_window"] == 2


def test_the_projection_is_each_arm_s_reviews_at_its_upper_rate() -> None:
    assert lg.projection("x1")["total"] == 40 * 700_000 * 2 + 40 * 350_000
    assert lg.projection("s")["total"] == 20 * 700_000 * 2 + 20 * 350_000
    assert lg.projection("p2")["reviews_per_arm"] == 40


RPB = line("2026-10-29T08:00:00Z", "2026-10-29T15:00:00Z", 1, kind="rpg01b-round")


def test_the_block_waits_past_w5_and_the_owner_may_raise_it() -> None:
    lines = [RPB, line("2026-11-05T10:00:00Z", "2026-11-05T11:00:00Z", 15_000_000)]
    assert not lg.project(lines, "x1", NOW, common.W5)["may_start"]  # 15 M + 70 M > 80 M
    raised = lg.project(lines, "x1", NOW, 90_000_000)
    assert raised["may_start"] and raised["w5_raised"]
    assert lg.project([RPB], "x1", NOW, common.W5)["may_start"]


def test_the_projection_refuses_a_ledger_that_does_not_open_with_r_pg_01b_s_lines() -> None:
    got = lg.project([], "x1", NOW, common.W5)
    assert not got["may_start"] and not got["opens_with_r_pg_01b_s_lines"]


def test_a_line_in_the_window_with_no_total_refuses_the_projection() -> None:
    lines = [line("2026-11-05T10:00:00Z", "2026-11-05T11:00:00Z", None, kind="rpg01b-round")]
    got = lg.project(lines, "s", NOW, common.W5)
    assert not got["may_start"] and got["trailing_5h"]["lines_without_a_total"]


def test_an_unreadable_ledger_or_an_unknown_kind_is_refused(tmp_path: Path) -> None:
    path = tmp_path / "ledger.jsonl"
    with pytest.raises(common.RefusedError):
        lg.append(path, {"kind": "something else"})
    path.write_text("not json\n")
    with pytest.raises(common.RefusedError):
        lg.read(path)


def test_a_root_s_sessions_are_counted_from_their_result_lines_through_no_symlink(
    tmp_path: Path,
) -> None:
    root = tmp_path / "root"
    for n, text in ((1, fx.stream()), (2, fx.stream(result={}))):
        d = root / "lane-0" / fx.session_of(n) / "session"
        d.mkdir(parents=True)
        (d / "stdout.jsonl").write_text(text)
    other = tmp_path / "other" / fx.session_of(3) / "session"
    other.mkdir(parents=True)
    (other / "stdout.jsonl").write_text(fx.stream())
    os.symlink(tmp_path / "other" / fx.session_of(3), root / fx.session_of(3))
    assert lg.root_tokens(root) == {"sessions": 2, "tokens": 10, "without_result": 1}


def test_the_cli_writes_a_block_line_and_never_rewrites_the_ledger(tmp_path: Path) -> None:
    env = {**os.environ, "RP3_RUNS": str(tmp_path / "runs")}
    root = tmp_path / "scratch"
    d = root / fx.session_of(1) / "session"
    d.mkdir(parents=True)
    (d / "stdout.jsonl").write_text(fx.stream())
    done = subprocess.run(
        [
            sys.executable,
            "-I",
            str(HERE / "ledger.py"),
            "block",
            "--block",
            "x1",
            "--attempt",
            "1",
            "--scratch",
            str(root),
            "--account",
            "the run account",
            "--window",
            "2026-11-05T07:00:00Z",
            "--started",
            "2026-11-05T08:00:00Z",
            "--ended",
            "2026-11-05T10:00:00Z",
            "--void",
            "a cut read",
        ],
        capture_output=True,
        text=True,
        check=False,
        env=env,
        cwd=common.REPO,
    )
    assert done.returncode == 0, done.stdout
    rows = [json.loads(x) for x in (tmp_path / "runs" / "ledger.jsonl").read_text().splitlines()]
    assert rows[0]["tokens_every_try"] == 10 and rows[0]["void"] == "a cut read"
    assert "the run account" not in done.stdout  # the account's label is never printed
