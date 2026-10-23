"""R-LAW-01 §12's run order through the launcher, end to end, on the synthetic fixture.

Run explicitly, from the repository root: uv run pytest -q experiments/R-LAW-01

A dry run: ``law_launch.sh`` preflight, calibrate and measure, then the tally, with the scripted
stand-in for every session (``RLAW_STANDIN``) and the fixture's sets in place of the frozen ones
(``RLAW_DRY_PINS``). Every output is marked a stand-in's and the tally refuses it outside
``--dry-run``. No set or run of the experiment is read, and no model is called.
"""

from __future__ import annotations

import dataclasses
import json
import os
import shutil
import subprocess
import sys
import time
from pathlib import Path
from typing import Any

import law_extract as X
import law_fixture as F
import law_group as GR
import law_regate as G
import pytest

HERE = Path(__file__).resolve().parent
LAUNCH = HERE / "law_launch.sh"
SLICE = {"practice": ["u1"], "fresh": ["e1"]}
#: Set in the launcher's environment; the binary must never see the user's name it carries.
SENTINEL_USER = "rlaw-sentinel-user"
PRIOR = {
    "packets": {
        "P01": {
            "artefact": "m1",
            "side": "injected",
            "findings": [
                {"arm": "paired", "item": "ES-3", "verdict": "true_flaw"},
                {"arm": "generalist", "item": "ES-3", "verdict": "not_a_flaw"},
            ],
        }
    }
}


def dry_env(root: Path, **kw: str) -> dict[str, str]:
    base = {
        k: v
        for k, v in os.environ.items()
        if k not in ("RLAW_CLAUDE_BIN", "RLAW_RESUME", "RLAW_PRIOR", "RLAW_PY")
    }
    return {
        **base,
        "RLAW_STANDIN": str(root / "standin"),
        "RLAW_DRY_PINS": str(root / "pins.json"),
        "RLAW_WATCH_SECONDS": "1",
        "USER": SENTINEL_USER,
        "LOGNAME": SENTINEL_USER,
        **kw,
    }


def launch(phase: str, work: Path, env: dict[str, str]) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        ["bash", str(LAUNCH), phase, str(work)],
        capture_output=True,
        text=True,
        env=env,
        check=False,
        timeout=600,
    )


def dry_work(root: Path) -> Path:
    """A work dir as extraction, grouping, the slice draw and the re-gate leave it, on the
    fixture; and the pins file that points the scripts at the fixture's sets."""
    fx = F.build(root / "fx")
    work = root / "work"
    (work / "ledger").mkdir(parents=True)
    lines, counts, sets = F.extract_fixture(fx)
    X.write_jsonl(work / "lines.jsonl", lines)
    (work / "extract_counts.json").write_text(json.dumps(counts))
    flaws, s1, s6, gc = GR.group(lines, sets)
    X.write_jsonl(work / "flaws.jsonl", flaws)
    X.write_jsonl(work / "units_s1.jsonl", s1)
    X.write_jsonl(work / "units_s6.jsonl", s6)
    (work / "group_counts.json").write_text(json.dumps(gc))
    (work / "slice.json").write_text(
        json.dumps({"pairs": SLICE, "base_flaws_spanning_slice_and_measured": 1})
    )
    regate = []
    for name, d in fx["sets"].items():
        regate += [{"set": name, **r} for r in G.gate_set(d, X.SETS[name].seed)]
    X.write_jsonl(work / "regate.jsonl", regate)
    (root / "prior.json").write_text(json.dumps(PRIOR))
    pins = {
        "sets": {n: dataclasses.asdict(p) for n, p in fx["pins"].sets.items()},
        "parts_sheet": fx["pins"].parts_sheet,
        "repo": str(fx["root"]),
        "prior_adjudication": X.sha256_file(root / "prior.json"),
    }
    (root / "pins.json").write_text(json.dumps(pins))
    (root / "state").mkdir()
    F.write_standin(root, state=root / "state")
    return work


@pytest.fixture(scope="module")
def launched(tmp_path_factory: pytest.TempPathFactory) -> dict[str, Any]:
    root = tmp_path_factory.mktemp("launch")
    work = dry_work(root)
    env = dry_env(root)
    out: dict[str, Any] = {"root": root, "work": work, "env": env}
    out["preflight"] = launch("preflight", work, env)
    out["calibrate"] = launch("calibrate", work, env)
    # the "Prompt filled" commit, for a fixture: the last version run on the slice is final
    bank = json.loads((work / "bank.json").read_text())
    shutil.copytree(work / "prompts" / ("v1" if bank["round_2"] else "v0"), work / "prompts/final")
    out["measure"] = launch("measure", work, {**env, "RLAW_PRIOR": str(root / "prior.json")})
    tally = [sys.executable, "-I", str(HERE / "law_tally.py"), str(work)]
    out["tally_dry"] = subprocess.run(
        [*tally, "--dry-run"], capture_output=True, text=True, env=env, check=False
    )
    out["tally_real"] = subprocess.run(tally, capture_output=True, text=True, env=env, check=False)
    return out


def test_every_phase_of_the_dry_run_holds(launched: dict[str, Any]) -> None:
    for phase in ("preflight", "calibrate", "measure"):
        done = launched[phase]
        assert done.returncode == 0, (phase, done.stdout[-3000:], done.stderr[-3000:])
    work = launched["work"]
    assert not (work / "ledger" / "STOPPED").exists() and not (work / "ledger" / "VOID").exists()
    assert not (work / "deviations.json").exists()
    assert json.loads((work / "ledger" / "projection.json").read_text())["exit"] == 0


def test_every_session_of_the_dry_run_is_marked(launched: dict[str, Any]) -> None:
    rows = X.read_jsonl(launched["work"] / "ledger" / "ledger.jsonl")
    steps = {r["step"] for r in rows}
    assert {"slice-r1-c1", "slice-r1-c2", "reality-injected", "measured-c1", "audit"} <= steps
    assert all(r["standin"] for r in rows)
    codes = X.read_jsonl(launched["work"] / "codes.jsonl")
    assert {(r["step"], r["who"]) for r in codes} >= {("measured", "c1"), ("audit", "audit")}
    assert all(r["standin"] for r in codes)


def test_the_tally_reads_the_dry_run_and_refuses_it_outside_one(launched: dict[str, Any]) -> None:
    dry, real = launched["tally_dry"], launched["tally_real"]
    assert dry.returncode == 0, dry.stderr[-3000:]
    t = json.loads((launched["work"] / "tally.json").read_text())
    assert t["dry_run"] is True and t["decision"]["branch"]
    assert real.returncode == 1 and "stand-in" in json.loads(real.stdout)["refused"]


def test_the_launch_log_names_the_binary_s_environment_never_its_values(
    launched: dict[str, Any],
) -> None:
    log = (launched["work"] / "launch.log").read_text()
    names = "HOME USER LOGNAME PATH TMPDIR LANG DISABLE_AUTOUPDATER"
    assert names in log
    assert SENTINEL_USER not in log


# ---------------------------------------------------------------- one launcher per work dir


def _lock(work: Path, group: int) -> Path:
    lock = work / "ledger" / "launch.lock"
    lock.mkdir(parents=True)
    (lock / "group").write_text(f"{group}\n")
    return lock


def test_a_second_launcher_is_refused_while_the_phase_s_group_lives(tmp_path: Path) -> None:
    work = tmp_path / "work"
    (work / "ledger").mkdir(parents=True)
    phase = subprocess.Popen(["sleep", "120"], start_new_session=True)
    try:
        lock = _lock(work, phase.pid)
        done = launch("calibrate", work, dry_env(tmp_path))
        assert done.returncode != 0
        assert "running" in done.stdout + done.stderr
        assert (lock / "group").read_text().strip() == str(phase.pid)  # left as it was
        assert not (work / "ledger" / "phase-start").exists()  # nothing of the phase began
        assert not (work / "ledger" / "interruptions.jsonl").exists()
    finally:
        phase.kill()
        phase.wait()


def test_a_lock_whose_processes_are_all_dead_is_taken_over_and_logged(tmp_path: Path) -> None:
    work = tmp_path / "work"
    (work / "ledger").mkdir(parents=True)
    gone = subprocess.Popen(["true"], start_new_session=True)
    gone.wait()
    time.sleep(0.2)
    _lock(work, gone.pid)
    # a recorded deviation ends the phase at its preflight, after the lock is taken
    (work / "deviations.json").write_text('["recorded"]')
    done = launch("calibrate", work, dry_env(tmp_path))
    assert done.returncode == 1
    ev = [json.loads(x) for x in (work / "ledger" / "interruptions.jsonl").read_text().splitlines()]
    assert [e["event"] for e in ev] == ["takeover"] and str(gone.pid) in ev[0]["reason"]
    assert not (work / "ledger" / "launch.lock").exists()  # released when the phase ended
