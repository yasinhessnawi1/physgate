"""R-LAW-01 §7, §8, §10 and §12: the session driver's guards, and the tally's statistics.

Run explicitly, from the repository root: uv run pytest -q experiments/R-LAW-01
"""

from __future__ import annotations

import json
import os
import re
import shlex
import subprocess
import sys
import time
from pathlib import Path
from typing import Any

import law_fixture as F
import law_tally as TL
import law_verify as V
import pytest

HERE = Path(__file__).resolve().parent
SH = HERE / "law_sessions.sh"
LIMIT = '[{"type":"result","is_error":true,"result":"usage_limit_reached"}]'
GOOD = {"id": "F1", "verdict": "true_flaw", "origin": "introduced", "reason": "r"}
#: Real outputs of the pinned 2.1.301 binary on the development account, copied byte for byte
#: (sha256 c8001a37…, 90f8d1ea… and 6812d707…): ``smoke_out.json`` is the smoke session;
#: ``schema_fail_probe_out.json`` a session whose schema no value can meet, where the model gave up
#: after two StructuredOutput calls (a success result without a structured output); and
#: ``retry_exhausted_probe_out.json`` the same schema with MAX_STRUCTURED_OUTPUT_RETRIES=1, where
#: the binary gave up itself: exit 1, ``is_error`` true, subtype
#: ``error_max_structured_output_retries``, terminal reason ``structured_output_retry_exhausted``,
#: two turns, and no usage reported (``modelUsage`` empty, every count 0).
DATA = HERE / "testdata"
EXHAUSTED = DATA / "retry_exhausted_probe_out.json"


def fake(tmp_path: Path, name: str, stdout: str, stderr: str = "", code: int = 0) -> Path:
    """An executable that answers every call with this output, stderr and exit code."""
    exe = tmp_path / name
    exe.write_text(
        "#!/usr/bin/env bash\ncat > /dev/null\n"
        f"printf '%s' {shlex.quote(stdout)}\nprintf '%s' {shlex.quote(stderr)} >&2\nexit {code}\n"
    )
    exe.chmod(0o755)
    return exe


def rows_of(path: Path) -> list[dict[str, Any]]:
    return [json.loads(x) for x in path.read_text().splitlines() if x.strip()]


def run(*args: str, env: dict[str, str] | None = None) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        ["bash", str(SH), *args],
        capture_output=True,
        text=True,
        env={**os.environ, **(env or {})},
        check=False,
    )


def ledger(path: Path, rows: list[dict[str, Any]]) -> Path:
    path.write_text("".join(json.dumps(r) + "\n" for r in rows))
    return path


def new_phase(led: Path) -> None:
    """What the launcher does as a phase starts: a stop from before it is old (an hour, here), and
    ``ledger/phase-start`` is touched now."""
    past = time.time() - 3600
    if (led / "STOPPED").exists():
        os.utime(led / "STOPPED", (past, past))
    (led / "phase-start").touch()


@pytest.fixture
def packets(tmp_path: Path) -> Path:
    pk = tmp_path / "pk"
    pk.mkdir()
    (pk / "P0001.md").write_text(
        "# Packet P0001\n\n## Findings\n\n### F1\nx\n\n"
        "## The design, all nodes\n\n[]\n\n## The parts sheet\n\n" + F.SHEET
    )
    (pk / "key.json").write_text(
        json.dumps(
            {"P0001": {"set": "fresh", "pair": "m1", "side": "twin", "findings": {"F1": "L0001"}}}
        )
    )
    prompts = tmp_path / "prompts"
    prompts.mkdir()
    for n in (
        "coder_prompt.txt",
        "coder_schema.json",
        "reality_prompt.txt",
        "reality_schema.json",
        "adjudicator_prompt.txt",
        "adjudicator_schema.json",
    ):
        (prompts / n).write_text('{"verdict": 1}' if n == "reality_schema.json" else "{}")
    return pk


def env_for(tmp_path: Path, **kw: str) -> dict[str, str]:
    (tmp_path / "led").mkdir(exist_ok=True)
    return {
        "RLAW_STANDIN": str(F.write_standin(tmp_path)),
        "RLAW_PROMPTS": str(tmp_path / "prompts"),
        "RLAW_LEDGER": str(tmp_path / "led" / "ledger.jsonl"),
        "RLAW_SHEET_SHA256": __import__("law_extract").sha256_bytes(F.SHEET.encode()),
        **kw,
    }


def test_the_guard_voids_and_stops_at_60_million(tmp_path: Path, packets: Path) -> None:
    env = env_for(tmp_path)
    ledger(Path(env["RLAW_LEDGER"]), [{"step": "x", "packet": "P", "tokens": 60_000_000}])
    done = run(
        "run", "s", "reality", str(packets), str(tmp_path / "out"), "claude-opus-5-5", "1", env=env
    )
    assert done.returncode == 3
    assert (tmp_path / "led" / "VOID").exists()
    assert not list((tmp_path / "out").glob("*.json"))
    again = run(
        "run",
        "s2",
        "reality",
        str(packets),
        str(tmp_path / "out2"),
        "claude-opus-5-5",
        "1",
        env=env,
    )
    assert again.returncode == 3


def test_a_stand_in_session_is_logged_and_marked(tmp_path: Path, packets: Path) -> None:
    env = env_for(tmp_path)
    done = run(
        "run", "s", "reality", str(packets), str(tmp_path / "out"), "claude-opus-5-5", "1", env=env
    )
    assert done.returncode == 0, done.stderr
    rows = [json.loads(x) for x in Path(env["RLAW_LEDGER"]).read_text().splitlines()]
    assert len(rows) == 1 and rows[0]["valid"] and rows[0]["standin"] and rows[0]["tokens"] > 0
    assert (tmp_path / "out" / "P0001.try1.standin").exists()
    # a second run into the same out dir is refused unless told to resume
    again = run(
        "run", "s", "reality", str(packets), str(tmp_path / "out"), "claude-opus-5-5", "1", env=env
    )
    assert again.returncode == 2


def test_a_usage_limit_stops_every_session(tmp_path: Path, packets: Path) -> None:
    exe = tmp_path / "limited"
    exe.write_text(
        '#!/usr/bin/env bash\necho \'[{"type":"result","is_error":true,'
        '"result":"usage_limit_reached"}]\'\n'
    )
    exe.chmod(0o755)
    env = env_for(tmp_path, RLAW_STANDIN=str(exe))
    done = run(
        "run", "s", "reality", str(packets), str(tmp_path / "out"), "claude-opus-5-5", "1", env=env
    )
    assert done.returncode == 4
    assert (tmp_path / "led" / "STOPPED").exists()


def test_an_unpinned_binary_or_model_is_refused(tmp_path: Path, packets: Path) -> None:
    env = env_for(tmp_path)
    del env["RLAW_STANDIN"]
    fake = tmp_path / "claude"
    fake.write_text("#!/usr/bin/env bash\necho 2.1.301 '(Claude Code)'\n")
    fake.chmod(0o755)
    env["RLAW_CLAUDE_BIN"] = str(fake)
    env["RLAW_STANDIN"] = ""
    done = run(
        "run", "s", "reality", str(packets), str(tmp_path / "o"), "claude-opus-5-5", "1", env=env
    )
    assert done.returncode == 2 and "not the pinned one" in done.stderr
    env2 = env_for(tmp_path)
    done = run(
        "run", "s", "reality", str(packets), str(tmp_path / "o2"), "claude-sonnet-5", "1", env=env2
    )
    assert done.returncode == 2


def test_the_projection_check(tmp_path: Path) -> None:
    rows = [{"step": "slice-r1-c1", "packet": f"P{i}", "tokens": 50_000} for i in range(30)]
    led = ledger(tmp_path / "l.jsonl", rows)
    done = run("projection", str(led), "slice-r1-c1")
    out = json.loads(done.stdout)
    assert done.returncode == 0 and out["sessions_remaining"] == 560
    assert out["projected"] == 30 * 50_000 + 50_000 * 560
    heavy = [{"step": "slice-r1-c1", "packet": f"P{i}", "tokens": 120_000} for i in range(30)]
    done = run("projection", str(ledger(tmp_path / "h.jsonl", heavy)), "slice-r1-c1")
    assert done.returncode == 1 and not json.loads(done.stdout)["holds"]
    assert run("spent", str(led)).stdout.strip() == str(30 * 50_000)


#: Ledger lines no total can be read past: a driver killed mid-append, and rows that are not one
#: call's whole line with a token count that is a non-negative integer.
UNREADABLE = {
    "a line cut short by a killed append": '{"step": "x", "packet": "P0009", "tok',
    "a negative token count": json.dumps({"step": "x", "packet": "P", "try": 1, "tokens": -5}),
    "a token count that is not an integer": json.dumps(
        {"step": "x", "packet": "P", "try": 1, "tokens": "12"}
    ),
    "a row without a token count": json.dumps({"step": "x", "packet": "P", "try": 1}),
    "a row that is not an object": "[1, 2]",
}


@pytest.mark.parametrize("case", sorted(UNREADABLE))
def test_the_guard_fails_closed_on_a_ledger_it_cannot_read(
    tmp_path: Path, packets: Path, case: str
) -> None:
    env = env_for(tmp_path)
    led = Path(env["RLAW_LEDGER"])
    before = json.dumps({"step": "x", "packet": "P", "try": 1, "tokens": 10}) + "\n"
    led.write_text(before + UNREADABLE[case] + "\n")
    out = tmp_path / "out"
    done = run("run", "s", "reality", str(packets), str(out), "claude-opus-5-5", "1", env=env)
    assert done.returncode == 4, done.stderr
    # a stop, not the §12 result: VOID is never written on a read error
    assert (tmp_path / "led" / "STOPPED").exists()
    assert not (tmp_path / "led" / "VOID").exists()
    # no session started
    assert led.read_text() == before + UNREADABLE[case] + "\n"
    assert not out.exists() or not list(out.iterdir())
    ev = rows_of(tmp_path / "led" / "interruptions.jsonl")
    assert [e["event"] for e in ev] == ["stop"] and "ledger" in ev[0]["reason"]
    assert run("spent", str(led)).returncode != 0


def test_a_ledger_past_the_guard_but_unreadable_is_stopped_not_voided(
    tmp_path: Path, packets: Path
) -> None:
    env = env_for(tmp_path)
    led = Path(env["RLAW_LEDGER"])
    led.write_text(json.dumps({"step": "x", "packet": "P", "try": 1, "tokens": 70_000_000}) + "\n{")
    done = run(
        "run", "s", "reality", str(packets), str(tmp_path / "out"), "claude-opus-5-5", "1", env=env
    )
    assert done.returncode == 4
    assert (tmp_path / "led" / "STOPPED").exists() and not (tmp_path / "led" / "VOID").exists()


def test_the_guard_is_read_again_once_the_last_session_settles(
    tmp_path: Path, packets: Path
) -> None:
    answer = json.dumps(
        {
            "type": "result",
            "is_error": False,
            "terminal_reason": "completed",
            "structured_output": {"findings": [GOOD]},
            "usage": {"input_tokens": 100},
            "modelUsage": {"claude-opus-5-5": {"inputTokens": 100}},
        }
    )
    env = env_for(tmp_path, RLAW_STANDIN=str(fake(tmp_path, "last", answer)))
    led = ledger(
        Path(env["RLAW_LEDGER"]), [{"step": "x", "packet": "P", "try": 1, "tokens": 59_999_950}]
    )
    done = run(
        "run", "s", "reality", str(packets), str(tmp_path / "out"), "claude-opus-5-5", "1", env=env
    )
    # the guard let the session start below 60 M; the session ended past it: the result is void
    assert [r["tokens"] for r in rows_of(led)] == [59_999_950, 100]
    assert done.returncode == 3, done.stderr
    assert "60000050" in (tmp_path / "led" / "VOID").read_text()


def test_the_ledger_line_is_law_verify_s_own(tmp_path: Path, packets: Path) -> None:
    calls = tmp_path / "py.calls"
    py = tmp_path / "py"
    py.write_text(
        "#!/usr/bin/env bash\n"
        f'printf "%s\\n" "$*" >> {shlex.quote(str(calls))}\n'
        f'exec {shlex.quote(sys.executable)} "$@"\n'
    )
    py.chmod(0o755)
    real = DATA / "smoke_out.json"
    env = env_for(
        tmp_path,
        RLAW_STANDIN=str(fake(tmp_path, "real", real.read_text())),
        RLAW_PY=str(py),
    )
    done = run(
        "run", "s", "reality", str(packets), str(tmp_path / "out"), "claude-opus-5-5", "1", env=env
    )
    assert done.returncode == 0, done.stderr
    rows = rows_of(Path(env["RLAW_LEDGER"]))
    # the smoke session's form is no reality form: a try and the retry, each counted by law_verify
    assert [r["try"] for r in rows] == [1, 2]
    assert V.tokens_of(real) == 1572 and V.model_of(real) == ["claude-opus-5-5"]
    assert {r["tokens"] for r in rows} == {1572}
    assert all(r["models_used"] == ["claude-opus-5-5"] for r in rows)
    assert all(
        set(r)
        == {
            "step",
            "packet",
            "try",
            "model_asked",
            "models_used",
            "tokens",
            "exit",
            "valid",
            "standin",
            "infrastructure",
            "utc",
        }
        for r in rows
    )
    ledger_calls = [c for c in calls.read_text().splitlines() if "law_verify.py ledger " in c]
    assert len(ledger_calls) == 2


#: Failed calls whose output reports no usage. A call refused before any model work (a usage limit,
#: a rate limit, a refused credential) is charged nothing; any other is charged as a try.
NO_USAGE = {
    "a server error": (
        '{"type":"result","is_error":true,"terminal_reason":"api_error","api_error_status":500}',
        1,
        30_000,
    ),
    "a network failure": ("", 1, 30_000),
    "a usage limit": (LIMIT, 0, 0),
    "a rate limit": (
        '{"type":"result","is_error":true,"terminal_reason":"api_error","api_error_status":429}',
        1,
        0,
    ),
    "a refused credential": (
        '{"type":"result","is_error":true,"terminal_reason":"api_error","api_error_status":401}',
        1,
        0,
    ),
}


@pytest.mark.parametrize("case", sorted(NO_USAGE))
def test_a_call_that_reports_no_usage_is_charged_unless_refused_before_any_work(
    tmp_path: Path, packets: Path, case: str
) -> None:
    stdout, code, charge = NO_USAGE[case]
    env = env_for(tmp_path, RLAW_STANDIN=str(fake(tmp_path, "nousage", stdout, "", code)))
    before = [
        {"step": "s0", "packet": "P0101", "try": 1, "tokens": 30_000, "infrastructure": None},
        {"step": "s0", "packet": "P0102", "try": 1, "tokens": 20_000},
        # neither an estimate nor a failed call is a completed try's count
        {"step": "s0", "packet": "P0103", "try": 1, "tokens": 900_000, "tokens_estimated": True},
        {"step": "s0", "packet": "P0104", "try": 1, "tokens": 2_000_000, "infrastructure": "x"},
    ]
    led = ledger(Path(env["RLAW_LEDGER"]), before)
    done = run(
        "run", "s", "reality", str(packets), str(tmp_path / "out"), "claude-opus-5-5", "1", env=env
    )
    assert done.returncode == 4, done.stderr  # a failed call: the run stops
    (row,) = rows_of(led)[len(before) :]
    assert row["infrastructure"] and row["models_used"] == []
    assert row["tokens"] == charge
    assert row.get("tokens_estimated", False) is (charge > 0)


def test_the_driver_and_the_tally_hold_one_guard() -> None:
    m = re.search(r"^GUARD=(\d+)$", SH.read_text(), re.M)
    assert m is not None and int(m.group(1)) == TL.GUARD == 60_000_000


# ---------------------------------------------------------------- statistics


def test_wilson_matches_its_textbook_value() -> None:
    lo, hi = TL.wilson(15, 100) or [0, 0]
    assert abs(lo - 0.0930) < 1e-3 and abs(hi - 0.2321) < 1e-3
    assert TL.wilson(0, 0) is None


def test_the_cluster_bootstrap_is_seeded_and_brackets_the_share() -> None:
    per = [(1, 4), (0, 3), (2, 5), (1, 2), (0, 6)] * 4
    a = TL.cluster_share(per, draws=2000)
    b = TL.cluster_share(per, draws=2000)
    assert a == b and a is not None
    assert a[0] < 4 / 20 < a[1]


def test_weighted_kappa_weighs_each_flaw_once() -> None:
    rows = [
        ("L", "L", 1.0, "c1"),
        ("N", "N", 1.0, "c2"),
        ("L", "N", 1.0, "c3"),
        ("N", "N", 0.25, "c4"),
        ("N", "N", 0.25, "c4"),
        ("N", "N", 0.25, "c4"),
        ("N", "N", 0.25, "c4"),
    ]
    out = TL.kappa_stats(rows, 6, draws=500)
    # weighted: four units of weight one, three agreeing
    assert abs(out["raw_agreement_weighted"] - 0.75) < 1e-9
    assert abs(out["raw_agreement_unweighted"] - 6 / 7) < 1e-9
    assert out["pabak_weighted"] == pytest.approx((6 * 0.75 - 1) / 5)
    po, pe = 0.75, (0.5 * 0.25 + 0.5 * 0.75)
    assert out["weighted"] == pytest.approx((po - pe) / (1 - pe))
    assert out["interval"] is not None


def test_rule_1_rule_2_and_the_majority_reading() -> None:
    def w(a: str | None, b: str | None, adj: str | None = None) -> dict[str, Any]:
        out = {}
        for who, c in (("c1", a), ("c2", b), ("adj", adj)):
            if c is not None or who != "adj":
                out[who] = {"code": c, "form": None if c is None else {}}
        return out

    assert TL.rule1(w("L", "L")) == "L"
    assert TL.rule1(w("L", "N", "D")) == "D"
    assert TL.rule1(w("L", "N")) == "uncoded"
    assert TL.rule1(w("L", None)) == "uncoded"
    assert TL.aggregate(["N", "D", "L", "G"]) == "G"
    assert TL.aggregate(["N", "L-if-data", "D"]) == "L-if-data"
    assert TL.aggregate(["uncoded"]) == "uncoded"
    assert TL.majority(["L", "N"]) == "N"
    assert TL.majority(["L", "L", "N"]) == "L"
    assert TL.majority(["G", "L"]) == "G"
    assert TL.majority(["uncoded", "uncoded"]) == "uncoded"


# ---------------------------------------------------------------- stops and resumes


def test_a_cut_off_first_try_counts_and_gets_the_retry(tmp_path: Path, packets: Path) -> None:
    env = env_for(tmp_path)
    out = tmp_path / "out"
    # the first try is cut off and the process is gone before its ledger line: simulate by
    # writing only the cut output, as a killed session leaves it
    out.mkdir()
    (out / "P0001.try1.json").write_text("{")
    (tmp_path / "led" / "STOPPED").write_text("usage limit at P0001 try1\n")
    new_phase(tmp_path / "led")
    done = run(
        "run",
        "s",
        "reality",
        str(packets),
        str(out),
        "claude-opus-5-5",
        "1",
        env={**env, "RLAW_RESUME": "1"},
    )
    assert done.returncode == 0, done.stderr
    rows = [json.loads(x) for x in Path(env["RLAW_LEDGER"]).read_text().splitlines()]
    assert [(r["try"], r["exit"], r["valid"]) for r in rows] == [(1, -1, False), (2, 0, True)]
    assert (out / "P0001.try1.json").read_text() == "{"  # never overwritten
    ev = [
        json.loads(x) for x in (tmp_path / "led" / "interruptions.jsonl").read_text().splitlines()
    ]
    assert [e["event"] for e in ev] == ["resume"] and "usage limit" in ev[0]["reason"]
    assert not (tmp_path / "led" / "STOPPED").exists()
    assert list((tmp_path / "led").glob("STOPPED.*"))


def test_a_finished_packet_is_never_run_again(tmp_path: Path, packets: Path) -> None:
    env = env_for(tmp_path)
    out = tmp_path / "out"
    assert (
        run(
            "run", "s", "reality", str(packets), str(out), "claude-opus-5-5", "1", env=env
        ).returncode
        == 0
    )
    before = (out / "P0001.try1.json").read_bytes()
    again = run(
        "run",
        "s",
        "reality",
        str(packets),
        str(out),
        "claude-opus-5-5",
        "1",
        env={**env, "RLAW_RESUME": "1"},
    )
    assert again.returncode == 0
    assert (out / "P0001.try1.json").read_bytes() == before
    rows = Path(env["RLAW_LEDGER"]).read_text().splitlines()
    assert len(rows) == 1
    # no STOPPED marker was there, so the driver logged no resume of its own
    assert not (tmp_path / "led" / "interruptions.jsonl").exists()


def test_a_shared_out_dir_takes_only_new_packets(tmp_path: Path, packets: Path) -> None:
    env = env_for(tmp_path)
    out = tmp_path / "out"
    assert (
        run(
            "run", "s", "reality", str(packets), str(out), "claude-opus-5-5", "1", env=env
        ).returncode
        == 0
    )
    again = run(
        "run",
        "s2",
        "reality",
        str(packets),
        str(out),
        "claude-opus-5-5",
        "1",
        env={**env, "RLAW_SHARED_OUT": "1"},
    )
    assert again.returncode == 2 and "already holds" in again.stderr


def test_a_usage_stop_is_logged_with_its_time(tmp_path: Path, packets: Path) -> None:
    exe = tmp_path / "limited"
    exe.write_text(
        '#!/usr/bin/env bash\necho \'[{"type":"result","is_error":true,'
        '"result":"usage_limit_reached"}]\'\n'
    )
    exe.chmod(0o755)
    env = env_for(tmp_path, RLAW_STANDIN=str(exe))
    run("run", "s", "reality", str(packets), str(tmp_path / "out"), "claude-opus-5-5", "1", env=env)
    ev = [
        json.loads(x) for x in (tmp_path / "led" / "interruptions.jsonl").read_text().splitlines()
    ]
    stops = [e for e in ev if e["event"] == "stop"]
    assert stops and stops[0]["utc"].endswith("Z")


# ---------------------------------------------------------------- a failed call is not a try

FAILED_CALLS = {
    "usage limit": (LIMIT, "", 0, "usage_limit"),
    "refused credential 401": (
        '{"type":"result","is_error":true,"terminal_reason":"api_error","api_error_status":401}',
        "",
        1,
        "credential_refused",
    ),
    "refused credential 403": (
        '{"type":"result","is_error":true,"terminal_reason":"api_error","api_error_status":403}',
        "",
        1,
        "credential_refused",
    ),
    "server error after the binary's retries": (
        '{"type":"result","is_error":true,"terminal_reason":"api_error","api_error_status":500}',
        "",
        1,
        "api_error",
    ),
    "overloaded, ended as a success subtype": (
        '{"type":"result","subtype":"success","is_error":true,"api_error_status":529}',
        "",
        1,
        "api_error",
    ),
    "rate limit": (
        '{"type":"result","is_error":true,"terminal_reason":"api_error","api_error_status":429}',
        "",
        1,
        "rate_limit",
    ),
    "api error without a status": (
        '{"type":"result","is_error":true,"terminal_reason":"api_error"}',
        "",
        1,
        "api_error",
    ),
    "network failure": ("", "TypeError: fetch failed (ECONNRESET)", 1, "no_result"),
    "not json": ("Error: something broke", "", 0, "no_result"),
    "an error result of another kind": ('{"type":"result","is_error":true}', "", 0, "error"),
    "the binary's own error of another kind than the schema's": (
        '{"type":"result","subtype":"error_max_turns","is_error":true,'
        '"terminal_reason":"max_turns","errors":["Reached maximum number of turns (1)"]}',
        "",
        1,
        "error",
    ),
    "a form, but a non-zero exit": (
        json.dumps(
            {"type": "result", "is_error": False, "structured_output": {"findings": [GOOD]}}
        ),
        "",
        2,
        "exit",
    ),
    "a form, but another terminal reason": (
        json.dumps(
            {
                "type": "result",
                "is_error": False,
                "terminal_reason": "max_turns",
                "structured_output": {"findings": [GOOD]},
            }
        ),
        "",
        0,
        "terminal",
    ),
}


@pytest.mark.parametrize("case", sorted(FAILED_CALLS))
def test_a_failed_call_is_not_a_try_and_stops_the_run(
    tmp_path: Path, packets: Path, case: str
) -> None:
    stdout, stderr, code, cause = FAILED_CALLS[case]
    env = env_for(tmp_path, RLAW_STANDIN=str(fake(tmp_path, "failing", stdout, stderr, code)))
    out = tmp_path / "out"
    done = run("run", "s", "reality", str(packets), str(out), "claude-opus-5-5", "1", env=env)
    assert done.returncode == 4, done.stderr
    assert (tmp_path / "led" / "STOPPED").exists()
    rows = rows_of(Path(env["RLAW_LEDGER"]))
    assert len(rows) == 1 and rows[0]["try"] == 1 and not rows[0]["valid"]
    assert rows[0]["infrastructure"].startswith(cause), rows[0]
    assert not (out / "P0001.try1.json").exists()
    failed = list(out.glob("P0001.try1.failed-*.json"))
    assert len(failed) == 1 and failed[0].read_text() == stdout
    ev = rows_of(tmp_path / "led" / "interruptions.jsonl")
    assert [e["event"] for e in ev] == ["failed_call", "stop"]
    assert (
        ev[0]["packet"] == "P0001"
        and ev[0]["try"] == 1
        and ev[0]["cause"] == rows[0]["infrastructure"]
    )
    # resumed: the packet gets its first try, so the frozen retry is still there for a bad form
    new_phase(tmp_path / "led")
    good = env_for(tmp_path, RLAW_RESUME="1")
    again = run("run", "s", "reality", str(packets), str(out), "claude-opus-5-5", "1", env=good)
    assert again.returncode == 0, again.stderr
    rows = rows_of(Path(env["RLAW_LEDGER"]))
    assert [(r["try"], r["valid"], r["infrastructure"] is None) for r in rows[1:]] == [
        (1, True, True)
    ]
    assert (out / "P0001.try1.json").exists() and failed[0].exists()
    assert not (tmp_path / "led" / "STOPPED").exists()
    summary = json.loads(again.stdout.strip().splitlines()[-1])
    assert summary["tries"] == 1 and summary["failed_calls"] == 1


def test_an_invalid_form_is_a_try_and_gets_the_one_retry(tmp_path: Path, packets: Path) -> None:
    empty = json.dumps({"type": "result", "is_error": False, "structured_output": {"findings": []}})
    env = env_for(tmp_path, RLAW_STANDIN=str(fake(tmp_path, "empty", empty)))
    out = tmp_path / "out"
    done = run("run", "s", "reality", str(packets), str(out), "claude-opus-5-5", "1", env=env)
    assert done.returncode == 0, done.stderr
    rows = rows_of(Path(env["RLAW_LEDGER"]))
    assert [(r["try"], r["valid"], r["infrastructure"]) for r in rows] == [
        (1, False, None),
        (2, False, None),
    ]
    assert not (tmp_path / "led" / "STOPPED").exists()
    assert not (tmp_path / "led" / "interruptions.jsonl").exists()


def _exhausted(variant: str) -> str:
    """The binary's structured-output exhaustion result, or one of its two marks alone."""
    r = json.loads(EXHAUSTED.read_text())
    if variant == "the subtype alone":  # the retraction path keeps an aborted terminal reason
        r["terminal_reason"] = "aborted_tools"
    elif variant == "the terminal reason alone":
        del r["subtype"]
    return json.dumps(r)


@pytest.mark.parametrize(
    "variant", ["both marks", "the subtype alone", "the terminal reason alone"]
)
def test_the_binary_s_structured_output_exhaustion_is_a_try_with_no_form(
    tmp_path: Path, packets: Path, variant: str
) -> None:
    # the binary gave up fitting the model's output to --json-schema: is_error true, exit 1
    exe = fake(tmp_path, "exhausted", _exhausted(variant), "Error: Failed to provide valid", 1)
    env = env_for(tmp_path, RLAW_STANDIN=str(exe))
    out = tmp_path / "out"
    done = run("run", "s", "reality", str(packets), str(out), "claude-opus-5-5", "1", env=env)
    assert done.returncode == 0, done.stderr
    rows = rows_of(Path(env["RLAW_LEDGER"]))
    # §5.5: a try with no valid form, retried once; the second leaves the line without a form
    assert [(r["try"], r["valid"], r["infrastructure"]) for r in rows] == [
        (1, False, None),
        (2, False, None),
    ]
    # it reports no usage: each try is charged one session of the CRITERIA §12 unit, no try
    # having reported its usage yet
    assert [(r["tokens"], r.get("tokens_estimated")) for r in rows] == [(50_000, True)] * 2
    assert all(r["models_used"] == [] for r in rows)
    assert not (tmp_path / "led" / "STOPPED").exists()
    assert not (tmp_path / "led" / "interruptions.jsonl").exists()
    assert not list(out.glob("*.failed-*"))
    for t in (1, 2):
        assert V.valid_forms(out / f"P0001.try{t}.json", ["F1"], "reality") == {}


def test_a_session_whose_model_gave_up_on_the_schema_is_a_try(
    tmp_path: Path, packets: Path
) -> None:
    probe = (DATA / "schema_fail_probe_out.json").read_text()
    env = env_for(tmp_path, RLAW_STANDIN=str(fake(tmp_path, "probe", probe)))
    out = tmp_path / "out"
    done = run("run", "s", "reality", str(packets), str(out), "claude-opus-5-5", "1", env=env)
    assert done.returncode == 0, done.stderr
    rows = rows_of(Path(env["RLAW_LEDGER"]))
    assert [(r["try"], r["valid"], r["infrastructure"]) for r in rows] == [
        (1, False, None),
        (2, False, None),
    ]
    assert V.structured(out / "P0001.try1.json") is None


def test_a_session_cut_off_mid_call_counts_as_a_try(tmp_path: Path, packets: Path) -> None:
    env = env_for(tmp_path)
    out = tmp_path / "out"
    out.mkdir()
    # a killed session leaves its call's output half written under the in-flight name
    (out / "P0001.try1.part.json").write_text('[{"type":"system"')
    (out / "P0001.try1.part.err").write_text("")
    (tmp_path / "led" / "STOPPED").write_text("killed\n")
    new_phase(tmp_path / "led")
    done = run(
        "run",
        "s",
        "reality",
        str(packets),
        str(out),
        "claude-opus-5-5",
        "1",
        env={**env, "RLAW_RESUME": "1"},
    )
    assert done.returncode == 0, done.stderr
    rows = rows_of(Path(env["RLAW_LEDGER"]))
    assert [(r["try"], r["exit"], r["valid"]) for r in rows] == [(1, -1, False), (2, 0, True)]
    assert (out / "P0001.try1.json").read_text() == '[{"type":"system"'
    assert not list(out.glob("*.part.*"))


def test_a_failed_call_found_on_resume_is_logged_and_not_a_try(
    tmp_path: Path, packets: Path
) -> None:
    env = env_for(tmp_path)
    out = tmp_path / "out"
    out.mkdir()
    # the driver was stopped after the call ended and before it was settled
    (out / "P0001.try1.part.json").write_text(LIMIT)
    (out / "P0001.try1.part.err").write_text("")
    (tmp_path / "led" / "STOPPED").write_text("killed\n")
    new_phase(tmp_path / "led")
    done = run(
        "run",
        "s",
        "reality",
        str(packets),
        str(out),
        "claude-opus-5-5",
        "1",
        env={**env, "RLAW_RESUME": "1"},
    )
    assert done.returncode == 0, done.stderr
    rows = rows_of(Path(env["RLAW_LEDGER"]))
    assert [(r["try"], r["infrastructure"]) for r in rows] == [(1, "usage_limit"), (1, None)]
    assert rows[1]["valid"]
    assert [e["event"] for e in rows_of(tmp_path / "led" / "interruptions.jsonl")] == [
        "resume",
        "failed_call",
    ]


# ---------------------------------------------------------------- a resume after a limit


def test_a_resume_is_not_stopped_by_the_evidence_of_the_stop_it_resumes(
    tmp_path: Path, packets: Path
) -> None:
    env = env_for(tmp_path)
    out = tmp_path / "out"
    out.mkdir()
    # the stop being resumed left a usage-limit file and three rate-limit errors behind
    (out / "P0009.try1.failed-20261022T100000Z.json").write_text(LIMIT)
    for i in range(3):
        (out / f"P000{i + 5}.try1.failed-20261022T10000{i}Z.json").write_text(
            '{"type": "result", "is_error": true, "api_error_status": 429}'
        )
    (tmp_path / "led" / "STOPPED").write_text("usage limit\n")
    new_phase(tmp_path / "led")
    done = run(
        "run",
        "s",
        "reality",
        str(packets),
        str(out),
        "claude-opus-5-5",
        "1",
        env={**env, "RLAW_RESUME": "1"},
    )
    assert done.returncode == 0, done.stderr
    assert not (tmp_path / "led" / "STOPPED").exists()
    rows = rows_of(Path(env["RLAW_LEDGER"]))
    assert [(r["packet"], r["try"], r["valid"]) for r in rows] == [("P0001", 1, True)]


def test_a_stop_written_in_the_resumed_phase_is_a_stop(tmp_path: Path, packets: Path) -> None:
    env = env_for(tmp_path, RLAW_RESUME="1")
    led = tmp_path / "led"
    # the launcher consumed the old stop as the phase began; then another driver of this phase
    # hit a failed call, before this driver started
    (led / "phase-start").touch()
    past = time.time() - 60
    os.utime(led / "phase-start", (past, past))
    (led / "STOPPED").write_text("a failed call at P0042 try1: usage_limit\n")
    out = tmp_path / "out"
    done = run("run", "s", "reality", str(packets), str(out), "claude-opus-5-5", "1", env=env)
    assert done.returncode == 4
    assert (led / "STOPPED").read_text() == "a failed call at P0042 try1: usage_limit\n"
    assert not list(led.glob("STOPPED.*"))
    assert not (led / "interruptions.jsonl").exists()  # no resume logged
    assert not Path(env["RLAW_LEDGER"]).exists()  # nothing started


def test_a_stop_with_no_phase_start_is_a_stop(tmp_path: Path, packets: Path) -> None:
    env = env_for(tmp_path, RLAW_RESUME="1")
    (tmp_path / "led" / "STOPPED").write_text("usage limit\n")
    done = run(
        "run", "s", "reality", str(packets), str(tmp_path / "out"), "claude-opus-5-5", "1", env=env
    )
    assert done.returncode == 4
    assert (tmp_path / "led" / "STOPPED").exists()
    assert not Path(env["RLAW_LEDGER"]).exists()


def _watch(work: Path, group: int, since: Path) -> subprocess.Popen[str]:
    return subprocess.Popen(
        ["bash", str(SH), "watch", str(work), str(group), str(since), "measure"],
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        env={**os.environ, "RLAW_WATCH_SECONDS": "1"},
    )


def _until(cond: Any, seconds: float = 20.0) -> bool:  # noqa: ANN401
    end = time.time() + seconds
    while time.time() < end:
        if cond():
            return True
        time.sleep(0.2)
    return False


def test_the_watcher_reads_only_evidence_from_the_phase_now_running(tmp_path: Path) -> None:
    work = tmp_path / "work"
    s = work / "sessions" / "measured" / "c1"
    s.mkdir(parents=True)
    (work / "ledger").mkdir()
    (s / "P0001.try1.failed-old.json").write_text(LIMIT)
    (s / "P0001.try1.failed-old.err").write_text("usage_limit_reached")
    for i in range(3):
        (s / f"P000{i + 2}.try1.failed-old.json").write_text('{"api_error_status": 429}')
    past = time.time() - 3600
    for f in s.iterdir():
        os.utime(f, (past, past))
    since = work / "ledger" / "phase-start"
    since.touch()
    phase = subprocess.Popen(["sleep", "120"], start_new_session=True)
    w = _watch(work, phase.pid, since)
    try:
        # the resumed phase keeps running past the old evidence
        time.sleep(3)
        assert w.poll() is None and phase.poll() is None
        assert not (work / "ledger" / "STOPPED").exists()
        # a usage limit of this phase stops new sessions and leaves those in flight to end
        (s / "P0007.try1.failed-new.json").write_text(LIMIT)
        assert _until(lambda: w.poll() is not None)
        assert (work / "ledger" / "STOPPED").exists()
        ev = rows_of(work / "ledger" / "interruptions.jsonl")
        assert [e["event"] for e in ev] == ["stop"] and "watcher" in ev[0]["reason"]
        assert phase.poll() is None
    finally:
        phase.kill()
        w.kill()


def test_the_watcher_kills_the_phase_at_the_token_guard(tmp_path: Path) -> None:
    work = tmp_path / "work"
    (work / "sessions").mkdir(parents=True)
    (work / "ledger").mkdir()
    since = work / "ledger" / "phase-start"
    since.touch()
    phase = subprocess.Popen(["sleep", "120"], start_new_session=True)
    w = _watch(work, phase.pid, since)
    try:
        time.sleep(2)
        assert phase.poll() is None
        (work / "ledger" / "VOID").write_text("token guard\n")
        assert _until(lambda: phase.poll() is not None)
        assert _until(lambda: w.poll() is not None)
    finally:
        phase.kill()
        w.kill()


# ---------------------------------------------------------------- the smoke test (not run here)


def _smoke(tmp_path: Path, result: dict[str, Any], name: str) -> tuple[int, dict[str, Any]]:
    exe = fake(tmp_path, f"standin-{name}", json.dumps(result))
    done = subprocess.run(
        ["bash", str(SH), "smoke", str(tmp_path / name)],
        capture_output=True,
        text=True,
        env={**os.environ, "RLAW_STANDIN": str(exe)},
        check=False,
    )
    return done.returncode, json.loads(done.stdout.strip().splitlines()[-1])


def test_the_smoke_check_reads_one_session_s_output(tmp_path: Path) -> None:
    usage = {
        "input_tokens": 10,
        "output_tokens": 20,
        "cache_read_input_tokens": 30,
        "cache_creation_input_tokens": 40,
    }
    good = {
        "type": "result",
        "is_error": False,
        "terminal_reason": "completed",
        "structured_output": {"sum": 5, "tools": [], "earlier_files": []},
        "usage": usage,
        "modelUsage": {
            "claude-opus-5-5": {
                "inputTokens": 10,
                "outputTokens": 20,
                "cacheReadInputTokens": 30,
                "cacheCreationInputTokens": 40,
            }
        },
    }
    code, out = _smoke(tmp_path, good, "good")
    assert code == 0 and out["holds"] and out["standin"]
    assert all(out["checks"].values())
    bad = dict(
        good,
        structured_output={"sum": 5, "tools": [], "earlier_files": ["# graphify"]},
        usage=dict(usage, output_tokens=21),
    )
    code, out = _smoke(tmp_path, bad, "bad")
    assert code == 1 and not out["holds"]
    assert not out["checks"]["no_claude_md"]
    assert not out["checks"]["usage_is_the_model_usage_sum"]
    assert out["checks"]["json_schema_with_no_tools"]


def test_the_smoke_check_holds_on_the_real_smoke_session(tmp_path: Path) -> None:
    code, out = _smoke(tmp_path, json.loads((DATA / "smoke_out.json").read_text()), "real")
    assert code == 0 and out["holds"] and out["failed_call"] is None
    assert out["usage"] == out["model_usage_sum"] and out["models_used"] == ["claude-opus-5-5"]
    # the binary's exhaustion is no failed call, and no form either
    code, out = _smoke(tmp_path, json.loads(_exhausted("both marks")), "exhausted")
    assert code == 1 and out["failed_call"] is None
    assert not out["checks"]["json_schema_with_no_tools"]


# ---------------------------------------------------------------- the launcher's preflight

LAUNCH = HERE / "law_launch.sh"


def preflight(work: Path, **env: str) -> subprocess.CompletedProcess[str]:
    base = {k: v for k, v in os.environ.items() if k not in ("RLAW_PRIOR", "RLAW_RESUME")}
    return subprocess.run(
        ["bash", str(LAUNCH), "preflight", str(work)],
        capture_output=True,
        text=True,
        env={**base, **env},
        check=False,
    )


def test_the_preflight_refuses_a_work_dir_with_a_recorded_deviation(tmp_path: Path) -> None:
    (tmp_path / "deviations.json").write_text('["the projection check failed"]')
    done = preflight(tmp_path)
    assert done.returncode == 1
    assert "deviation" in done.stdout and "nothing runs" in done.stdout


def test_the_preflight_holds_the_prior_adjudication_to_its_digest(tmp_path: Path) -> None:
    other = tmp_path / "prior.json"
    other.write_text("{}")
    done = preflight(tmp_path, RLAW_PRIOR=str(other))
    assert done.returncode == 1 and "prior adjudication" in done.stdout
    gone = preflight(tmp_path, RLAW_PRIOR=str(tmp_path / "missing.json"))
    assert gone.returncode == 1 and "prior adjudication" in gone.stdout
