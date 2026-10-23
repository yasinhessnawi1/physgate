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
    names = subprocess.run(
        ["bash", str(HERE / "law_sessions.sh"), "envnames"],
        capture_output=True,
        text=True,
        env=launched["env"],
        check=True,
    ).stdout.strip()
    assert {"HOME", "USER", "LOGNAME", "PATH", "LANG", "DISABLE_AUTOUPDATER"} <= set(names.split())
    assert f"(names): {names}" in log
    assert SENTINEL_USER not in log


# ---------------------------------------------------------------- a dry run is a dry run only


def _bare_env(**kw: str) -> dict[str, str]:
    drop = (
        "RLAW_CLAUDE_BIN",
        "RLAW_RESUME",
        "RLAW_PRIOR",
        "RLAW_PY",
        "RLAW_STANDIN",
        "RLAW_DRY_PINS",
    )
    return {**{k: v for k, v in os.environ.items() if k not in drop}, **kw}


def test_dry_pins_without_a_stand_in_are_refused_by_the_scripts(tmp_path: Path) -> None:
    done = subprocess.run(
        [
            sys.executable,
            "-I",
            "-c",
            f"import sys; sys.path.insert(0, {str(HERE)!r}); import law_extract",
        ],
        capture_output=True,
        text=True,
        env=_bare_env(RLAW_DRY_PINS=str(tmp_path / "pins.json")),
        check=False,
    )
    assert done.returncode != 0 and "Refused" in done.stderr


def test_dry_pins_without_a_stand_in_are_refused_by_the_launcher(tmp_path: Path) -> None:
    work = tmp_path / "work"
    work.mkdir()
    done = launch("preflight", work, _bare_env(RLAW_DRY_PINS=str(tmp_path / "pins.json")))
    assert done.returncode == 1 and "RLAW_DRY_PINS is for a dry run" in done.stdout


def test_a_stand_in_without_the_fixture_s_pins_is_refused(tmp_path: Path) -> None:
    # a stray RLAW_STANDIN must never make a real launch a dry run on the real work dir
    work = tmp_path / "work"
    work.mkdir()
    done = launch("preflight", work, _bare_env(RLAW_STANDIN=str(tmp_path / "standin")))
    assert done.returncode == 1 and "RLAW_STANDIN is for a dry run" in done.stdout


@pytest.mark.parametrize("where", ["ledger", "codes", "reality", "session"])
def test_a_real_preflight_refuses_a_work_dir_with_a_stand_in_s_outputs(
    tmp_path: Path, where: str
) -> None:
    work = tmp_path / "work"
    (work / "ledger").mkdir(parents=True)
    if where == "ledger":
        row = {"step": "s", "packet": "P0001", "try": 1, "tokens": 5, "standin": True}
        (work / "ledger" / "ledger.jsonl").write_text(json.dumps(row) + "\n")
    elif where == "codes":
        row = {"step": "measured", "who": "c1", "line_id": "L0001", "standin": True}
        (work / "codes.jsonl").write_text(json.dumps(row) + "\n")
    elif where == "reality":
        row = {"line_id": "L0001", "verdict": "true_flaw", "standin": True}
        (work / "reality.jsonl").write_text(json.dumps(row) + "\n")
    else:
        (work / "sessions" / "measured" / "c1").mkdir(parents=True)
        (work / "sessions" / "measured" / "c1" / "P0001.try1.standin").write_text("")
    done = launch("preflight", work, _bare_env())
    assert done.returncode == 1 and "a stand-in's outputs" in done.stdout, done.stdout


# ---------------------------------------------------------------- one launcher per work dir

#: A process that holds the work dir's lock as a launcher does (an flock through an open file),
#: with the record a launcher writes before its phase's group exists.
HOLDER = """
import fcntl, os, sys, time
fd = os.open(sys.argv[1], os.O_WRONLY | os.O_APPEND | os.O_CREAT, 0o644)
fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
with open(sys.argv[1], "w") as fh:
    fh.write(f"launcher {os.getpid()}\\n")
print("held", flush=True)
time.sleep(120)
"""


def _ledger_dir(tmp_path: Path, name: str = "work") -> Path:
    work = tmp_path / name
    (work / "ledger").mkdir(parents=True)
    # a recorded deviation ends a phase at its preflight, after the lock is taken
    (work / "deviations.json").write_text('["recorded"]')
    return work


def _events(work: Path) -> list[dict[str, Any]]:
    p = work / "ledger" / "interruptions.jsonl"
    return [json.loads(x) for x in p.read_text().splitlines()] if p.exists() else []


def test_a_second_launcher_is_refused_while_the_lock_is_held(tmp_path: Path) -> None:
    work = _ledger_dir(tmp_path)
    lock = work / "ledger" / "launch.lock"
    # held by a launcher whose phase's group is not yet recorded
    holder = subprocess.Popen(
        [sys.executable, "-I", "-c", HOLDER, str(lock)], stdout=subprocess.PIPE, text=True
    )
    try:
        assert holder.stdout is not None and holder.stdout.readline().strip() == "held"
        done = launch("calibrate", work, dry_env(tmp_path))
        assert done.returncode != 0
        assert "running" in done.stdout + done.stderr
        assert lock.read_text() == f"launcher {holder.pid}\n"  # left as it was
        assert not (work / "ledger" / "phase-start").exists()  # nothing of the phase began
        assert _events(work) == []
    finally:
        holder.kill()
        holder.wait()


def test_a_lock_no_process_holds_is_taken_over_and_logged(tmp_path: Path) -> None:
    work = _ledger_dir(tmp_path)
    lock = work / "ledger" / "launch.lock"
    gone = subprocess.Popen(["true"], start_new_session=True)
    gone.wait()
    lock.write_text(f"launcher {gone.pid} group {gone.pid}\n")  # its launcher died mid-phase
    done = launch("calibrate", work, dry_env(tmp_path))
    assert done.returncode == 1
    ev = _events(work)
    assert [e["event"] for e in ev] == ["takeover"] and str(gone.pid) in ev[0]["reason"]
    assert lock.read_text() == ""  # the record is cleared when the phase ends


def test_contenders_for_a_stale_lock_let_exactly_one_launcher_through(tmp_path: Path) -> None:
    for trial in range(8):
        work = _ledger_dir(tmp_path, f"w{trial}")
        (work / "ledger" / "launch.lock").write_text("launcher 1 group 1\n")
        # the winner holds the lock a while, so that every contender meets it
        env = dry_env(tmp_path, RLAW_LOCK_HOLD_SECONDS="2")
        runs = [
            subprocess.Popen(
                ["bash", str(LAUNCH), "calibrate", str(work)],
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                text=True,
                env=env,
            )
            for _ in range(4)
        ]
        outs = [r.communicate(timeout=120)[0] for r in runs]
        through = [o for o in outs if "the binary runs with only this environment" in o]
        assert len(through) == 1, (trial, outs)
        assert [e["event"] for e in _events(work)] == ["takeover"], trial


def test_a_clean_record_is_no_takeover(tmp_path: Path) -> None:
    for name, record in (("empty", ""), ("absent", None)):
        work = _ledger_dir(tmp_path, name)
        if record is not None:
            (work / "ledger" / "launch.lock").write_text(record)  # the last phase ended cleanly
        assert launch("calibrate", work, dry_env(tmp_path)).returncode == 1
        assert _events(work) == [], name


def launch_to_file(phase: str, work: Path, env: dict[str, str]) -> tuple[int, float]:
    """The launcher, its output to a file (not a pipe a lingering child could hold open): its exit
    code, and the seconds it took to exit."""
    start = time.monotonic()
    with (work / f"{phase}.out").open("w") as fh:
        p = subprocess.Popen(["bash", str(LAUNCH), phase, str(work)], stdout=fh, stderr=fh, env=env)
        code = p.wait(timeout=120)
    return code, time.monotonic() - start


def test_the_lock_is_free_as_soon_as_its_launcher_ends(tmp_path: Path) -> None:
    work = tmp_path / "work"
    (work / "ledger").mkdir(parents=True)
    standin = tmp_path / "standin"
    standin.write_text("#!/usr/bin/env bash\nexit 0\n")
    standin.chmod(0o755)
    pins = {"sets": {}, "parts_sheet": "0" * 64, "repo": str(tmp_path), "prior_adjudication": "0"}
    (tmp_path / "pins.json").write_text(json.dumps(pins))
    # the prior is a FIFO: the phase waits at its preflight's prior check until it is written,
    # so the watcher (looking every 20 s) is asleep, with its tee, when the phase ends
    prior = tmp_path / "prior.fifo"
    os.mkfifo(prior)
    env = dry_env(tmp_path, RLAW_WATCH_SECONDS="20", RLAW_PRIOR=str(prior))
    with (work / "calibrate.out").open("w") as fh:
        p = subprocess.Popen(
            ["bash", str(LAUNCH), "calibrate", str(work)], stdout=fh, stderr=fh, env=env
        )
        time.sleep(2)
        with prior.open("w") as w:
            w.write("not the prior\n")
        assert p.wait(timeout=60) == 1
    free = subprocess.run(
        [
            sys.executable,
            "-I",
            "-c",
            HOLDER.replace("time.sleep(120)", "sys.exit(0)"),
            str(work / "ledger" / "launch.lock"),
        ],
        capture_output=True,
        text=True,
        check=False,
    )
    assert free.returncode == 0, free.stderr
    assert "RLAW_PRIOR is not the prior adjudication" in (work / "calibrate.out").read_text()


def test_the_lock_hold_is_a_dry_run_s_only(tmp_path: Path) -> None:
    work = _ledger_dir(tmp_path)
    env = _bare_env(RLAW_LOCK_HOLD_SECONDS="30", RLAW_WATCH_SECONDS="1")
    code, took = launch_to_file("calibrate", work, env)
    assert code == 1 and took < 20


def test_a_dry_run_is_refused_on_a_work_dir_holding_the_committed_slice(tmp_path: Path) -> None:
    # both variables stray on the real work dir: its slice is the committed one
    work = tmp_path / "work"
    (work / "ledger").mkdir(parents=True)
    shutil.copy(HERE / "slice.json", work / "slice.json")
    (tmp_path / "standin").write_text("#!/usr/bin/env bash\nexit 0\n")
    (tmp_path / "standin").chmod(0o755)
    done = launch("preflight", work, dry_env(tmp_path))
    assert done.returncode == 1 and "committed slice" in done.stdout, done.stdout
