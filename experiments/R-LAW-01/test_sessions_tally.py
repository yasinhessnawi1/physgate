"""R-LAW-01 §7, §8, §10 and §12: the session driver's guards, and the tally's statistics.

Run explicitly, from the repository root: uv run pytest -q experiments/R-LAW-01
"""

from __future__ import annotations

import json
import os
import subprocess
from pathlib import Path
from typing import Any

import pytest

import law_fixture as F
import law_tally as TL

HERE = Path(__file__).resolve().parent
SH = HERE / "law_sessions.sh"


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
