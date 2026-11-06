"""Runs whose control sessions record simulations, for the operator UI's simulation tests.

Every run here is made by the real loop, with real git, a real store, the real collection of a
session's records and the real ``PhysicsGate``. Two things are stand-ins, labelled as such: the
session, which runs the control stand-in's recording script (``stand_in_control``) under its
module, and the reviewer, which passes. No model is called.

The gate judges the stand-in's two linked quantities by the catalogue's own names. The control
domain has no bounds table in the knowledge layer, so the phase margin is always recorded as
having no sourced range: an unchecked record that names it, the case the real runs show. The
step's peak is given a range by a table made here for the tests alone, never a source: one that
holds the stand-in's peak (about 1.39 m), so the magnitude check passes it and names nothing,
or one that does not, so the check fails it and names it.

What the runs hold, each asserted where it is built so a run that stops showing it fails here
rather than leaving a test with nothing to look at:

- ``run-series``: gate on, the peak in range; both subtasks merge at their first attempt;
- ``run-series-refused``: gate on, the peak out of range. The first subtask's first attempt
  fails the gate on the peak; its second attempt names a record only the first attempt sealed,
  so its check cannot read it and the attempt is refused before the gate; its third reports
  the phase margin alone and merges. The second subtask fails the gate at every attempt;
- ``run-series-observe``: gate observe, the peak out of range; the gate would fail, nothing is
  refused, both merge;
- ``run-series-off``: gate off; the gate is skipped and says so;
- ``run-series-retried``: the first session of the first attempt records, leaves a stray file
  and a writer's temporary file in its outbox, and ends for infrastructure; the attempt runs
  again in a fresh session, which records every id again. So six records are superseded, one
  file is refused and the temporary file discarded, beside the interpreter's cache of the writer
  that the collector discards from every session;
- ``run-series-large``: one record at the format's sample bound;
- ``run-series-tampered``: a copy of ``run-series`` with one byte of one sealed record changed.

``bound_run`` makes one more, ``run-series-bound``, whose sessions each leave as many records as
one session may; its first record takes a seed larger than a browser's number holds exactly.
"""

from __future__ import annotations

import json
import shutil
from pathlib import Path
from typing import Any

from stand_in_control import CONTROL_SCRIPT, RECORD_IDS
from ui_rig import evaluation_rig

from physgate.gate.bounds_table import KNOWLEDGE_DIR, Bounds, load_table
from physgate.gate.runner import PhysicsGate
from physgate.orchestrator.events import (
    AttemptRejected,
    GateRan,
    GateSkipped,
    Merged,
    ProposalsChecked,
    SessionEnded,
    read_events,
)
from physgate.orchestrator.run_config import RunBounds
from physgate.series.record import MAX_FILE_BYTES, MAX_RECORDS_PER_SESSION, MAX_SAMPLES

#: The seed the stand-in sessions pass to their scripts.
SEED = 7
#: The ranges the tests' own control table gives the step's peak: one holding the stand-in's
#: peak, one not. Made up for the tests, never a source.
PEAK_IN_RANGE = (0.1, 10.0)
PEAK_OUT_OF_RANGE = (0.1, 1.0)

#: A seed larger than a browser's number holds exactly, and within a record's integer bound.
BIG_SEED = 2**63 - 1

#: The script a repair attempt runs that records nothing, yet reports a phase margin it says
#: it read off a record of the earlier attempt: the real runs' unreadable case.
NAMES_AN_EARLIER_RECORD = """import json
print(json.dumps({"phase_margin": {"value": 0.5534885189031078, "unit": "rad",
    "series": {"record": "loop_nominal", "extract": "phase_margin"}}}))
"""

#: The stand-in's script, reporting the phase margin alone, so the gate has no peak to fail.
WITHOUT_THE_PEAK = CONTROL_SCRIPT.replace(
    "if len(sys.argv) > 1:", 'reported.pop("step_peak")\nif len(sys.argv) > 1:', 1
)

#: The stand-in's script, leaving in its outbox a file that is not a record and a writer's
#: temporary file after it has recorded: the collector refuses the one and discards the other.
LEAVES_STRAYS = (
    CONTROL_SCRIPT
    + """
outbox = os.path.join(here, ".physgate", "series")
with open(os.path.join(outbox, "stray_notes.json"), "w") as handle:
    handle.write("not a record")
with open(os.path.join(outbox, ".half_written.tmp"), "w") as handle:
    handle.write("{")
"""
)

#: A script that records one run at the format's sample bound, with made-up numbers.
LARGE_SCRIPT = f"""import math, os, sys
here = os.path.dirname(os.path.abspath(__file__))
while not os.path.isfile(os.path.join(here, ".physgate", "lib", "series_writer.py")):
    here = os.path.dirname(here)
sys.path.insert(0, os.path.join(here, ".physgate", "lib"))
import series_writer
n = {MAX_SAMPLES}
series_writer.record(
    "long_run",
    title="Stand-in long run at the sample bound, made-up numbers, not a simulation",
    axis="time",
    x=("time", "s", [round(i * 1e-4, 4) for i in range(n)]),
    traces=[
        ("position", "m", [round(math.sin(i * 1e-3), 6) for i in range(n)]),
        ("tilt", "rad", [round(math.cos(i * 1e-3) * 0.1, 6) for i in range(n)]),
    ],
    inputs={{"seed": (int(os.environ.get("STAND_IN_SEED", "7")), "dimensionless")}},
    group="long_runs",
)
"""

#: A script that records as many runs as one session may leave, each small, with made-up numbers;
#: the first takes a seed larger than a browser's number holds exactly.
BOUND_SCRIPT = f"""import os, sys
here = os.path.dirname(os.path.abspath(__file__))
while not os.path.isfile(os.path.join(here, ".physgate", "lib", "series_writer.py")):
    here = os.path.dirname(here)
sys.path.insert(0, os.path.join(here, ".physgate", "lib"))
import series_writer
for k in range({MAX_RECORDS_PER_SESSION}):
    series_writer.record(
        f"run_{{k:03d}}",
        title=f"Stand-in short run {{k}}, made-up numbers, not a simulation",
        axis="time",
        x=("time", "s", [i / 100 for i in range(200)]),
        traces=[("position", "m", [(i * k) / 1000 for i in range(200)])],
        inputs={{"seed": ({BIG_SEED} if k == 0 else k, "dimensionless")}},
        group="short_runs",
    )
"""

_TABLE = """[meta]
domain = "control"
curated_by = "the operator UI's tests, made up for them; not a source"

[[range]]
quantity = "step_peak"
low = {low}
high = {high}
unit = "m"
class = "the control stand-in's step response, a test fixture"
source = "made up for the operator UI's tests, not a source"
retrieved = 2026-11-06
confirmed = 2026-11-06
note = "a test fixture: it says nothing about any real step response"
"""


def control_gate(root: Path, peak: tuple[float, float]) -> PhysicsGate:
    """The real gate over the shipped tables and a test-only control table for the peak."""
    low, high = peak
    table = root / f"control-bounds-{low}-{high}" / "control" / "bounds.toml"
    table.parent.mkdir(parents=True, exist_ok=True)
    table.write_text(_TABLE.format(low=low, high=high))
    tables = [load_table(path) for path in sorted(KNOWLEDGE_DIR.glob("*/bounds.toml"))]
    tables.append(load_table(table))
    return PhysicsGate(bounds=Bounds({t.domain: t for t in tables}))


def series_run(
    root: Path,
    runs: Path,
    repo: Path,
    name: str,
    *,
    mode: str = "on",
    peak: tuple[float, float] = PEAK_IN_RANGE,
    script: str = CONTROL_SCRIPT,
    session: dict[str, Any] | None = None,
    overrides: dict[str, Any] | None = None,
) -> Path:
    """One run of two control subtasks, each session running the stand-in's script."""
    observe_rig = evaluation_rig()
    return observe_rig.fake_run(  # type: ignore[no-any-return]
        runs,
        name,
        repo,
        gate=control_gate(root, peak),
        records=SEED,
        role="control",
        script=script,
        reviewers={"control": observe_rig.Reviewer()},
        session=session or {},
        overrides={"gate_mode": mode, **(overrides or {})},
    )


def _events(run: Path) -> list[Any]:
    return read_events(run / "events.jsonl")


def _kinds(run: Path, kind: type) -> list[Any]:
    return [e for e in _events(run) if isinstance(e, kind)]


def tamper(source: Path, target: Path) -> Path:
    """A copy of ``source`` with one digit of its first sealed record changed, length kept."""
    shutil.copytree(source, target, symlinks=True, ignore=shutil.ignore_patterns("worktrees"))
    ended = next(e for e in _kinds(target, SessionEnded) if e.series.records)
    record = ended.series.records[0]
    path = (
        target
        / "series"
        / ended.subtask_id
        / str(ended.attempt)
        / ended.session_id
        / f"{record.record_id}.json"
    )
    data = bytearray(path.read_bytes())
    at = data.index(b'"values": [') + len(b'"values": [')
    while not chr(data[at]).isdigit():
        at += 1
    data[at] = ord("1") if data[at] != ord("1") else ord("2")
    path.write_bytes(bytes(data))
    assert path.stat().st_size == record.length
    return target


def series_runs(root: Path, runs: Path) -> dict[str, Path]:
    """Build every run named in the module docstring under ``runs``; return them by name."""
    repo = evaluation_rig().target_repo(root / "series-repo")
    made: dict[str, Path] = {}

    made["run-series"] = series_run(root, runs, repo, "run-series")
    assert len(_kinds(made["run-series"], Merged)) == 2
    assert all(
        len(e.series.records) == len(RECORD_IDS) for e in _kinds(made["run-series"], SessionEnded)
    )

    made["run-series-refused"] = series_run(
        root,
        runs,
        repo,
        "run-series-refused",
        peak=PEAK_OUT_OF_RANGE,
        session={"scripts": {2: NAMES_AN_EARLIER_RECORD, 3: WITHOUT_THE_PEAK}},
    )
    refused = [
        e for e in _kinds(made["run-series-refused"], ProposalsChecked) if e.refused_by == "series"
    ]
    assert len(refused) == 1 and refused[0].attempt == 2
    assert [c.outcome for c in refused[0].series_checks] == ["unreadable"]
    first = refused[0].subtask_id
    assert [e.attempt for e in _kinds(made["run-series-refused"], Merged)] == [3]
    failed = [e for e in _kinds(made["run-series-refused"], GateRan) if e.result.verdict == "fail"]
    assert any(e.subtask_id == first and e.attempt == 1 and e.result.quantities for e in failed)

    made["run-series-observe"] = series_run(
        root, runs, repo, "run-series-observe", mode="observe", peak=PEAK_OUT_OF_RANGE
    )
    observed = _kinds(made["run-series-observe"], GateRan)
    assert observed and all(
        e.result.mode == "observe" and e.result.verdict == "fail" for e in observed
    )
    assert len(_kinds(made["run-series-observe"], Merged)) == 2

    made["run-series-off"] = series_run(root, runs, repo, "run-series-off", mode="off")
    assert len(_kinds(made["run-series-off"], GateSkipped)) == 2
    assert not _kinds(made["run-series-off"], GateRan)

    made["run-series-retried"] = series_run(
        root,
        runs,
        repo,
        "run-series-retried",
        session={"infra": {1}, "scripts": {1: LEAVES_STRAYS}},
        overrides={
            "bounds": RunBounds(
                binary_max_retries=0,
                session_wall_clock_s=120.0,
                session_max_turns=20,
                infra_retry_delays_s=(0.0,),
            )
        },
    )
    retried = [e for e in _kinds(made["run-series-retried"], SessionEnded) if e.attempt == 1]
    first_ended = retried[0]
    assert first_ended.outcome == "infrastructure" and len(first_ended.series.records) == 6
    assert [s.name for s in first_ended.series.refused] == ["stray_notes.json"]
    assert ".half_written.tmp" in [s.name for s in first_ended.series.discarded]
    assert retried[1].subtask_id == first_ended.subtask_id and len(retried[1].series.records) == 6

    made["run-series-large"] = series_run(root, runs, repo, "run-series-large", script=LARGE_SCRIPT)
    large = _kinds(made["run-series-large"], SessionEnded)[0].series.records
    assert [r.record_id for r in large] == ["long_run"]
    assert large[0].length <= MAX_FILE_BYTES

    made["run-series-tampered"] = tamper(made["run-series"], runs / "run-series-tampered")
    return made


def bound_run(root: Path, runs: Path) -> Path:
    """``run-series-bound``: each session leaves as many records as one session may."""
    repo = evaluation_rig().target_repo(root / "bound-repo")
    run = series_run(root, runs, repo, "run-series-bound", script=BOUND_SCRIPT)
    for ended in _kinds(run, SessionEnded):
        assert len(ended.series.records) == MAX_RECORDS_PER_SESSION
    return run


def cut_after_first_check(source: Path, target: Path) -> Path:
    """A copy of ``source`` whose log ends just after its first change check: not gated yet."""
    shutil.copytree(source, target, symlinks=True, ignore=shutil.ignore_patterns("worktrees"))
    log = target / "events.jsonl"
    lines = log.read_bytes().splitlines(keepends=True)
    cut = next(i for i, raw in enumerate(lines) if json.loads(raw)["kind"] == "proposals_checked")
    log.write_bytes(b"".join(lines[: cut + 1]))
    return target


def rejected(run: Path) -> set[tuple[str, int]]:
    """The attempts the run's log records as rejected."""
    return {(e.subtask_id, e.attempt) for e in _kinds(run, AttemptRejected)}
