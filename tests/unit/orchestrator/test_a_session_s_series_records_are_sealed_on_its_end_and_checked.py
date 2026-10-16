"""A session's series records are sealed on its end line, and the change check holds them.

Two halves. Through the loop with stand-in parts: the series a session left goes on its end
line, is handed to the change check, and an attempt the check refuses for it is rejected with
a finding the repair names; the records an attempt sealed are read back from the log alone,
a later session's superseding an earlier one's. Through real git and a real collection: the
attempt commit never holds a record; a script changed between collection and commit, or a
record a straggling process writes after collection, is refused before the gate.
"""

from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

import pytest
from loop_fakes import FakeChanges, FakeDispatcher, Rig, plan

from physgate.orchestrator import apply as apply_module
from physgate.orchestrator.apply import GitChangeChecker
from physgate.orchestrator.events import AttemptRejected, SessionEnded, read_events
from physgate.orchestrator.git import verified_git_dir
from physgate.orchestrator.merge import RunGit, commit_attempt
from physgate.orchestrator.repair import repair_instruction
from physgate.series.collect import WRITER_PATH, blob_id, collect, writer_source
from physgate.series.reader import attempt_records, read_record
from physgate.series.seal import SealedRecord, SessionSeries, SetAside

DIGEST = "a" * 64
BLOB = "b" * 40


def _sealed(record_id: str, digest: str = DIGEST) -> SealedRecord:
    return SealedRecord(
        record_id=record_id,
        sha256=digest,
        length=10,
        script="modules/control/sim.py",
        script_sha256=DIGEST,
        script_blob=BLOB,
    )


# ── through the loop ─────────────────────────────────────────────────────────


def test_the_series_a_session_left_is_on_its_end_line_and_reaches_the_change_check(
    tmp_path: Path,
) -> None:
    series = SessionSeries(
        records=(_sealed("step"),),
        discarded=(SetAside(name="x.tmp", reason="a writer's temporary file"),),
    )
    changes = FakeChanges()
    rig = Rig(tmp_path, dispatcher=FakeDispatcher(series={1: series}), changes=changes)
    loop = rig.open()
    loop.start(plan("s1"))
    loop.run()
    loop.close()
    ended = [e for e in read_events(tmp_path / "events.jsonl") if isinstance(e, SessionEnded)]
    assert [e.series for e in ended] == [series]
    assert changes.seen == [series]


def test_an_attempt_refused_for_its_series_is_rejected_and_the_repair_names_the_check(
    tmp_path: Path,
) -> None:
    changes = FakeChanges(
        refuse={1: ("series", "the session left series records that were refused")}
    )
    rig = Rig(tmp_path, changes=changes)
    loop = rig.open()
    loop.start(plan("s1"))
    loop.run()
    loop.close()
    rejected = [e for e in read_events(tmp_path / "events.jsonl") if isinstance(e, AttemptRejected)]
    assert rejected[0].finding.source == "series"
    assert "the series check" in repair_instruction(1, rejected[0].finding)


def test_an_attempt_s_records_are_read_from_its_end_lines_a_later_session_superseding(
    tmp_path: Path,
) -> None:
    first = SessionSeries(records=(_sealed("step", "1" * 64), _sealed("bode", "2" * 64)))
    second = SessionSeries(records=(_sealed("step", "3" * 64),))
    rig = Rig(
        tmp_path,
        dispatcher=FakeDispatcher(infra={1: "api_error"}, series={1: first, 2: second}),
        delays=(0.0,),
    )
    loop = rig.open()
    loop.start(plan("s1"))
    loop.run()
    loop.close()
    events = read_events(tmp_path / "events.jsonl")
    entries = attempt_records(events, "s1", 1)
    assert [(e.record.record_id, e.record.sha256, e.session_id) for e in entries] == [
        ("bode", "2" * 64, "sess-1"),
        ("step", "3" * 64, "sess-2"),
    ]
    assert attempt_records(events, "s1", 2) == ()
    assert attempt_records(events, "other", 1) == ()


# ── through real git and a real collection ───────────────────────────────────

_ENV = {
    "PATH": "/usr/bin:/bin",
    "HOME": os.devnull,
    "GIT_CONFIG_GLOBAL": os.devnull,
    "GIT_CONFIG_NOSYSTEM": "1",
    "GIT_AUTHOR_NAME": "t",
    "GIT_AUTHOR_EMAIL": "t@example.invalid",
    "GIT_COMMITTER_NAME": "t",
    "GIT_COMMITTER_EMAIL": "t@example.invalid",
}

SCRIPT = """import os, sys
here = os.path.dirname(os.path.abspath(__file__))
while not os.path.isfile(os.path.join(here, ".physgate", "lib", "series_writer.py")):
    here = os.path.dirname(here)
sys.path.insert(0, os.path.join(here, ".physgate", "lib"))
import series_writer
series_writer.record("step", title="Fixture, not a simulation", axis="time",
    x=("time", "s", [0.0, 0.01]), traces=[("position", "m", [0.0, 0.02])],
    inputs={"seed": (7, "dimensionless")})
"""


def _git(cwd: Path, *args: str) -> str:
    return subprocess.run(
        ["git", "-c", "commit.gpgsign=false", *args],
        cwd=cwd,
        env=_ENV,
        capture_output=True,
        text=True,
        check=True,
    ).stdout.strip()


def _attempt(tmp_path: Path) -> tuple[RunGit, Path, SessionSeries]:
    """A run whose subtask worktree ran a script that wrote one record, collected."""
    repo = Path(os.path.realpath(tmp_path)) / "repo"
    (repo / "modules" / "control").mkdir(parents=True)
    (repo / "modules" / "control" / "base.py").write_text("y = 1\n")
    (repo / WRITER_PATH).parent.mkdir(parents=True)
    (repo / WRITER_PATH).write_bytes(writer_source())
    _git(repo, "init", "-q", "-b", "main")
    _git(repo, "add", "-A")
    _git(repo, "commit", "-q", "-m", "start")
    run = RunGit(repo=repo, run_dir=Path(os.path.realpath(tmp_path)) / "run", run_id="r1")
    run.open_run_branch(_git(repo, "rev-parse", "HEAD"))
    worktree = run.open_subtask("control-1")
    script = worktree / "modules" / "control" / "sim.py"
    script.write_text(SCRIPT)
    done = subprocess.run(
        [sys.executable, "-E", "-s", str(script)],
        cwd=worktree,
        capture_output=True,
        text=True,
        check=False,
        env={"PATH": "/usr/bin:/bin", "HOME": str(tmp_path / "home")},
    )
    assert done.returncode == 0, done.stderr
    series = collect(
        worktree,
        module_dir="modules/control",
        run_dir=run.run_dir,
        subtask_id="control-1",
        attempt=1,
        session_id="session-1",
        object_format="sha1",
    )
    assert [r.record_id for r in series.records] == ["step"]
    return run, worktree, series


def _checker(run: RunGit) -> GitChangeChecker:
    graph = run.run_dir / "graph"
    graph.mkdir(parents=True, exist_ok=True)
    return GitChangeChecker(run, graph, {"control-1": "modules/control"})


def test_a_collected_record_is_never_in_the_attempt_commit_and_the_check_admits_it(
    tmp_path: Path,
) -> None:
    run, worktree, series = _attempt(tmp_path)
    commit = commit_attempt(worktree, "control-1", 1, "session-1", repo=run.repo)
    files = _git(run.repo, "ls-tree", "-r", "--name-only", commit).splitlines()
    assert "modules/control/sim.py" in files
    assert not [f for f in files if f.startswith(".physgate/series")]
    check = _checker(run).check("control-1", commit, "control", series=series)
    assert check.refused_by is None, check.reason
    (entry,) = attempt_records([_ended(series)], "control-1", 1)
    assert read_record(entry.path(run.run_dir), entry.seal()).id == "step"


def _ended(series: SessionSeries) -> SessionEnded:
    return SessionEnded(
        seq=1,
        ts="2026-10-16T00:00:00.000000Z",
        run_id="r1",
        gate_mode="on",
        subtask_id="control-1",
        attempt=1,
        session_id="session-1",
        outcome="completed",
        cause=None,
        attempt_commit="c" * 40,
        trajectory="t",
        worktree="w",
        reading_verified=True,
        series=series,
    )


def test_a_script_changed_between_collection_and_commit_is_refused(tmp_path: Path) -> None:
    run, worktree, series = _attempt(tmp_path)
    with (worktree / "modules" / "control" / "sim.py").open("a") as script:
        script.write("# changed by a process the session left running\n")
    commit = commit_attempt(worktree, "control-1", 1, "session-1", repo=run.repo)
    check = _checker(run).check("control-1", commit, "control", series=series)
    assert check.refused_by == "series"
    assert check.reason is not None and "did not commit that script" in check.reason
    assert check.subject == "step"


def test_a_record_written_after_collection_is_refused_by_the_write_scope(tmp_path: Path) -> None:
    run, worktree, series = _attempt(tmp_path)
    late = worktree / ".physgate" / "series" / "late.json"
    late.write_text("{}")
    commit = commit_attempt(worktree, "control-1", 1, "session-1", repo=run.repo)
    check = _checker(run).check("control-1", commit, "control", series=series)
    assert check.refused_by == "write_scope"
    assert check.reason is not None and ".physgate/series/late.json" in check.reason


def test_a_refused_record_refuses_the_attempt_and_names_it(tmp_path: Path) -> None:
    run, worktree, _ = _attempt(tmp_path)
    commit = commit_attempt(worktree, "control-1", 1, "session-1", repo=run.repo)
    refused = SessionSeries(refused=(SetAside(name="bad.json", reason="does not validate"),))
    check = _checker(run).check("control-1", commit, "control", series=refused)
    assert check.refused_by == "series"
    assert (
        check.reason
        == "the session left series records that were refused: bad.json: does not validate"
    )
    assert check.subject == "bad.json"


@pytest.mark.parametrize("series", [None, SessionSeries()])
def test_an_attempt_with_no_series_is_checked_as_before(
    tmp_path: Path, series: SessionSeries | None
) -> None:
    run, worktree, _ = _attempt(tmp_path)
    commit = commit_attempt(worktree, "control-1", 1, "session-1", repo=run.repo)
    assert _checker(run).check("control-1", commit, "control", series=series).refused_by is None


def test_the_script_binding_holds_without_the_write_scope_a_link_is_not_a_script(
    tmp_path: Path,
) -> None:
    # The write scope refuses a link first in the change check; this holds the binding to
    # the same on its own, since git lists a link as a blob whose bytes are its target.
    run, worktree, _ = _attempt(tmp_path)
    target = "x = 1\n"
    (worktree / "modules" / "control" / "linked.py").symlink_to(target)
    commit = commit_attempt(worktree, "control-1", 1, "session-1", repo=run.repo)
    claimed = SealedRecord(
        record_id="step",
        sha256=DIGEST,
        length=10,
        script="modules/control/linked.py",
        script_sha256=DIGEST,
        script_blob=blob_id(target.encode(), "sha1"),
    )
    pinned = verified_git_dir(run.repo, linked=False)
    refusal = apply_module._series_refusal(
        run.repo, commit, SessionSeries(records=(claimed,)), pinned
    )
    assert refusal is not None and refusal[1] == "step"
