"""A sealed record claims only what the session's end can hold, and the review is told so.

A record names the files its session's own process reported: the script it ran and the code it
had loaded. That process is the session's, so the writer's check that no compiled file lies
beside a module it loaded runs where the session can leave it out, and a record can be sealed
while other code ran. Nothing here closes that; the harness does not run the script again.

What the orchestrator holds, it now acts on. When the session has ended, a compiled file found
where the interpreter reads one in place of the source of a file a sealed record names (as the
sealed record lists it), or a cache of the series writer, in the worktree or beneath a cache
prefix in the session's own home or temporary directory, marks that record not vouched for in
the review's listing, with the file's path and digest; the attempt is not refused for it. The
writer's own cache is recorded by its digest like any other bytecode, never discarded as litter.
What the scratch folder held is recorded before it is emptied. Bytecode a session staged or
committed itself inside its module is out of scope. And the refusals and the review's sight of
bytecode each rest on a row.

Every row that runs a session's script runs it as a session runs (``PYTHONDONTWRITEBYTECODE``
set, an empty home), on real git, then takes the dispatcher's end steps in its order.
"""

from __future__ import annotations

import hashlib
import importlib._bootstrap_external as bootstrap
import json
import os
import stat
import subprocess
import sys
from pathlib import Path

import pytest
from loop_fakes import FakeDispatcher, Rig, plan
from test_a_session_s_scratch_folder_and_bytecode_are_never_part_of_its_attempt import (
    MODULE,
    SUBTASK,
    _changed,
    _git,
    _run,
    _scope,
    _write,
)

from physgate.orchestrator import apply as apply_module
from physgate.orchestrator import left_out
from physgate.orchestrator.apply import GitChangeChecker
from physgate.orchestrator.events import SessionEnded, read_events
from physgate.orchestrator.merge import RunGit, commit_attempt
from physgate.series import summary
from physgate.series.collect import collect, temporary_roots
from physgate.series.seal import (
    AttemptBytecode,
    AttemptRecord,
    AttemptSeries,
    Bytecode,
    SessionSeries,
)

TAG = sys.implementation.cache_tag
HONEST = "GAIN = 2.0\n"
PLANTED = "GAIN = 9.0\n"
#: A script under the module that records the helper's gain, as a session's script would.
SIM = """import os, sys
here = os.path.dirname(os.path.abspath(__file__))
while not os.path.isfile(os.path.join(here, ".physgate", "lib", "series_writer.py")):
    here = os.path.dirname(here)
sys.path.insert(0, os.path.join(here, ".physgate", "lib"))
import series_writer
{before}
import helper
series_writer.record("step", title="Fixture, not a simulation", axis="time",
    x=("time", "s", [0.0, 0.01, 0.02]),
    traces=[("position", "m", [0.0, helper.GAIN * 0.01, 0.05])],
    inputs={{"seed": (7, "dimensionless")}})
"""
#: One visible line that leaves the writer's check out: the session's process is the session's.
SWITCHED_OFF = "series_writer._compiled_in_place = lambda base: None"


def _setup(tmp_path: Path, before: str = "") -> tuple[RunGit, Path, Path]:
    run, worktree = _run(tmp_path)
    _write(worktree, {f"{MODULE}/helper.py": HONEST, f"{MODULE}/sim.py": SIM.format(before=before)})
    home = Path(os.path.realpath(tmp_path)) / "home"
    home.mkdir()
    return run, worktree, home


def _session_run(
    worktree: Path, home: Path, *argv: str, env: dict[str, str] | None = None
) -> subprocess.CompletedProcess[str]:
    """A command of the session's: its interpreter told to write no bytecode, its own home."""
    full = {"PATH": "/usr/bin:/bin", "HOME": str(home), "PYTHONDONTWRITEBYTECODE": "1"}
    return subprocess.run(
        [sys.executable, *argv],
        cwd=worktree,
        env={**full, **(env or {})},
        capture_output=True,
        text=True,
        check=False,
    )


def _timestamp_pyc(source: Path, text: str) -> bytes:
    """Compiled code of ``text`` whose header names ``source``'s time and size."""
    held = source.stat()
    code = compile(text, str(source), "exec")
    return bytes(bootstrap._code_to_timestamp_pyc(code, held.st_mtime, held.st_size))  # type: ignore[attr-defined]


def _in_place(worktree: Path) -> Path:
    cache = worktree / MODULE / "__pycache__" / f"helper.{TAG}.pyc"
    cache.parent.mkdir(exist_ok=True)
    return cache


def _collected(run: RunGit, worktree: Path, home: Path) -> SessionSeries:
    return collect(
        worktree,
        module_dir=MODULE,
        run_dir=run.run_dir,
        subtask_id=SUBTASK,
        attempt=1,
        session_id="session-1",
        object_format="sha1",
        writable_roots=(home, *temporary_roots()),
    )


def _end(
    run: RunGit, worktree: Path, series: SessionSeries, own: tuple[Path, ...] = ()
) -> SessionSeries:
    """The dispatcher's end after its collection: the clearing, then the end line's series.

    On the code before there was no mark: the clearing's findings went on the end line as they
    were, so each row below fails there on what it asserts.
    """
    beside_of = getattr(left_out, "Beside", None)
    end = getattr(left_out, "end_series", None)
    if beside_of is None or end is None:
        cleared = left_out.clear_left_out(worktree, repo=run.repo)
        if cleared.bytecode_found or not cleared.complete:
            series = series.model_copy(
                update={
                    "bytecode": cleared.bytecode,
                    "bytecode_found": cleared.bytecode_found,
                    "left_out_incomplete": not cleared.complete,
                }
            )
        return series
    beside = beside_of(series.records)
    cleared = left_out.clear_left_out(worktree, repo=run.repo, concerns=beside)
    ended: SessionSeries = end(series, cleared, beside, own=own)
    return ended


def _attempt(run: RunGit, series: SessionSeries) -> AttemptSeries:
    """What the review is given for an attempt of this one session, as the loop builds it."""
    held = {
        "session_id": "session-1",
        "found": max(series.bytecode_found, len(series.bytecode)),
        "files": series.bytecode,
    }
    if "not_vouched" in AttemptBytecode.model_fields:
        held["not_vouched"] = getattr(series, "not_vouched", None)
    has_bytecode = series.bytecode or getattr(series, "not_vouched", None) is not None
    return AttemptSeries(
        run_dir=str(run.run_dir),
        subtask_id=SUBTASK,
        attempt=1,
        records=tuple(AttemptRecord(session_id="session-1", record=r) for r in series.records),
        bytecode=(AttemptBytecode.model_validate(held),) if has_bytecode else (),
    )


def _marked(series: SessionSeries, record_id: str) -> list[Bytecode]:
    return [b for b in series.bytecode if record_id in getattr(b, "records", ())]


def _section(listing: str, record_id: str) -> str:
    start = listing.index(f"## {record_id}\n")
    end = listing.find("\n#", start + 1)
    return listing[start : end if end >= 0 else None]


def _checked(run: RunGit, worktree: Path, series: SessionSeries) -> tuple[str | None, str]:
    commit = commit_attempt(
        worktree, SUBTASK, 1, "session-1", repo=run.repo, stage=not series.left_out_incomplete
    )
    graph = run.run_dir / "graph"
    graph.mkdir(parents=True, exist_ok=True)
    check = GitChangeChecker(run, graph, {SUBTASK: MODULE}).check(
        SUBTASK, commit, "electrical", series=series
    )
    return check.refused_by, commit


# ── the mark ─────────────────────────────────────────────────────────────────


def test_a_record_sealed_beside_a_compiled_file_of_its_code_is_not_vouched_for_and_costs_nothing(
    tmp_path: Path,
) -> None:
    # The review's attack: the check left out by one line, the planted cache left in place.
    run, worktree, home = _setup(tmp_path, before=SWITCHED_OFF)
    planted = _timestamp_pyc(worktree / MODULE / "helper.py", PLANTED)
    _in_place(worktree).write_bytes(planted)
    done = _session_run(worktree, home, f"{MODULE}/sim.py")
    assert done.returncode == 0, done.stderr
    series = _end(run, worktree, _collected(run, worktree, home), own=(home,))
    (record,) = series.records
    assert record.record_id == "step"
    marked = _marked(series, "step")
    assert [b.path for b in marked] == [f"{MODULE}/__pycache__/helper.{TAG}.pyc"]
    assert marked[0].sha256 == hashlib.sha256(planted).hexdigest()
    # The attempt is not refused for it: an honest session that ran -E after sealing loses
    # nothing, and the mark is what the reviewer reads.
    refused_by, commit = _checked(run, worktree, series)
    assert refused_by is None
    assert _changed(run, commit) == [f"{MODULE}/helper.py", f"{MODULE}/sim.py"]
    shown = summary.listing(_attempt(run, series)).decode()
    section = _section(shown, "step")
    assert "NOT VOUCHED FOR" in section
    assert f"sha256 {hashlib.sha256(planted).hexdigest()}" in section
    assert "is refused when it is written" not in shown


def test_a_planted_cache_of_the_writer_is_recorded_by_its_digest_and_marks_every_record(
    tmp_path: Path,
) -> None:
    run, worktree, home = _setup(tmp_path)
    writer = worktree / ".physgate" / "lib" / "series_writer.py"
    text = writer.read_text().replace(
        "    compiled = _compiled_in_place(base)\n", "    compiled = None\n"
    )
    cache = writer.parent / "__pycache__" / f"series_writer.{TAG}.pyc"
    cache.parent.mkdir()
    planted = _timestamp_pyc(writer, text)
    cache.write_bytes(planted)
    _in_place(worktree).write_bytes(_timestamp_pyc(worktree / MODULE / "helper.py", PLANTED))
    done = _session_run(worktree, home, f"{MODULE}/sim.py")
    assert done.returncode == 0, done.stderr
    collected = _collected(run, worktree, home)
    # Never discarded as the interpreter's own cache, with no digest.
    assert [e.name for e in collected.discarded] == []
    series = _end(run, worktree, collected, own=(home,))
    writer_cache = [b for b in series.bytecode if b.path.startswith(".physgate/lib/__pycache__/")]
    assert [b.path for b in writer_cache] == [f".physgate/lib/__pycache__/series_writer.{TAG}.pyc"]
    assert writer_cache[0].sha256 == hashlib.sha256(planted).hexdigest()
    assert getattr(writer_cache[0], "records", ()) == ("step",)
    assert not cache.exists()


def test_a_cache_beneath_a_prefix_in_the_session_s_home_marks_the_record_with_its_path(
    tmp_path: Path,
) -> None:
    run, worktree, home = _setup(tmp_path, before=SWITCHED_OFF)
    prefix = home / "pc"
    source = worktree / MODULE / "helper.py"
    mirrored = prefix / str(source.parent).lstrip("/") / f"helper.{TAG}.pyc"
    mirrored.parent.mkdir(parents=True)
    planted = _timestamp_pyc(source, PLANTED)
    mirrored.write_bytes(planted)
    done = _session_run(
        worktree, home, f"{MODULE}/sim.py", env={"PYTHONPYCACHEPREFIX": str(prefix)}
    )
    assert done.returncode == 0, done.stderr
    series = _end(run, worktree, _collected(run, worktree, home), own=(home,))
    marked = _marked(series, "step")
    assert [b.path for b in marked] == [str(mirrored)]
    assert marked[0].sha256 == hashlib.sha256(planted).hexdigest()
    # Outside the worktree it is evidence, left where it lies.
    assert mirrored.read_bytes() == planted


def test_bytecode_beside_code_no_record_names_marks_no_record(tmp_path: Path) -> None:
    run, worktree, home = _setup(tmp_path)
    done = _session_run(worktree, home, f"{MODULE}/sim.py")
    assert done.returncode == 0, done.stderr
    # Written after the record, beside a module the record does not name.
    other = worktree / "modules" / "control" / "__pycache__" / f"law.{TAG}.pyc"
    other.parent.mkdir()
    other.write_bytes(b"compiled")
    series = _end(run, worktree, _collected(run, worktree, home), own=(home,))
    assert [b.path for b in series.bytecode] == [f"modules/control/__pycache__/law.{TAG}.pyc"]
    assert _marked(series, "step") == []
    assert getattr(series, "not_vouched", None) is None
    shown = summary.listing(_attempt(run, series)).decode()
    assert "NOT VOUCHED FOR" not in _section(shown, "step")


def test_a_place_the_look_cannot_list_marks_every_record_of_the_session(tmp_path: Path) -> None:
    run, worktree, home = _setup(tmp_path)
    done = _session_run(worktree, home, f"{MODULE}/sim.py")
    assert done.returncode == 0, done.stderr
    hidden = home / "hidden"
    hidden.mkdir()
    hidden.chmod(0)
    try:
        series = _end(run, worktree, _collected(run, worktree, home), own=(home,))
    finally:
        hidden.chmod(0o700)
    why = getattr(series, "not_vouched", None)
    assert why is not None and "could not be listed" in why, series
    shown = summary.listing(_attempt(run, series)).decode()
    assert "NOT VOUCHED FOR" in _section(shown, "step")


def test_a_file_beside_a_record_is_named_past_the_first_bound(tmp_path: Path) -> None:
    run, worktree, home = _setup(tmp_path, before=SWITCHED_OFF)
    _in_place(worktree).write_bytes(_timestamp_pyc(worktree / MODULE / "helper.py", PLANTED))
    done = _session_run(worktree, home, f"{MODULE}/sim.py")
    assert done.returncode == 0, done.stderr
    # Sixty files named before it, in the order the clearing takes them.
    first = worktree / "a" / "__pycache__"
    first.mkdir(parents=True)
    for n in range(60):
        (first / f"m{n:02d}.{TAG}.pyc").write_bytes(b"x")
    series = _end(run, worktree, _collected(run, worktree, home))
    assert series.bytecode_found == 61
    assert [b.path for b in _marked(series, "step")] == [f"{MODULE}/__pycache__/helper.{TAG}.pyc"]


@pytest.mark.parametrize(
    ("path", "marks"),
    [
        (f"{MODULE}/__pycache__/helper.{TAG}.pyc", True),
        (f"{MODULE}/__pycache__/helper.{TAG}.opt-1.pyc", True),
        (f"{MODULE}/__PYCACHE__/HELPER.cpython-399.PYC", True),
        (f"{MODULE}/helper.pyc", True),
        (f"pc/Users/x/wt/{MODULE}/helper.{TAG}.pyc", True),
        (f"/home/s/pc/w/t/{MODULE}/sim.{TAG}.pyc", True),
        (f"{MODULE}/helper.{TAG}.pyc", True),  # beneath a prefix of /
        (f".physgate/lib/__pycache__/series_writer.{TAG}.pyc", True),
        (f"{MODULE}/__pycache__/base.{TAG}.pyc", False),
        (f"{MODULE}/__pycache__/helper.py", False),
        (f"{MODULE}/__pycache__/x/helper.{TAG}.pyc", False),
        (f"{MODULE}/helperx.pyc", False),
        (f"modules/control/__pycache__/helper.{TAG}.pyc", False),
    ],
)
def test_a_file_lies_beside_a_record_exactly_where_the_interpreter_reads_compiled_code(
    path: str, marks: bool
) -> None:
    from physgate.series.seal import CodeBlob, SealedRecord

    record = SealedRecord(
        record_id="step",
        sha256="a" * 64,
        length=1,
        script=f"{MODULE}/sim.py",
        script_sha256="a" * 64,
        script_blob="b" * 40,
        loaded=(CodeBlob(path=f"{MODULE}/helper.py", blob="c" * 40),),
    )
    beside = left_out.Beside((record,))
    assert beside(path) == (("step",) if marks else ())


# ── the scratch folder ───────────────────────────────────────────────────────


def test_what_the_scratch_folder_held_is_recorded_by_path_length_and_digest_before_it_goes(
    tmp_path: Path,
) -> None:
    run, worktree, _ = _setup(tmp_path)
    scratch = worktree / ".physgate" / "scratch"
    _write(
        worktree, {".physgate/scratch/run_it.py": "print(1)\n", ".physgate/scratch/d/n.txt": "n\n"}
    )
    (scratch / "shut.txt").write_text("hidden\n")
    (scratch / "shut.txt").chmod(0)
    (scratch / "link").symlink_to("/etc/hosts")
    cleared = left_out.clear_left_out(worktree, repo=run.repo)
    held = [(e.path, e.kind, e.length, e.sha256) for e in getattr(cleared, "scratch", ())]

    def digest(text: str) -> str:
        return hashlib.sha256(text.encode()).hexdigest()

    assert held == [
        (".physgate/scratch/d/n.txt", "file", 2, digest("n\n")),
        (".physgate/scratch/link", "link", None, None),
        (".physgate/scratch/run_it.py", "file", 9, digest("print(1)\n")),
        (".physgate/scratch/shut.txt", "file", 7, digest("hidden\n")),
    ]
    assert cleared.scratch_found == 4 and cleared.scratch_cut is None
    assert not scratch.exists()


def test_a_scratch_folder_past_its_bound_is_recorded_and_says_where_it_stopped(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    run, worktree, _ = _setup(tmp_path)
    many = {f".physgate/scratch/f{n:03d}.txt": "x" * 10 for n in range(205)}
    _write(worktree, many)
    monkeypatch.setattr(left_out, "MAX_SCRATCH_BYTES", 25)
    cleared = left_out.clear_left_out(worktree, repo=run.repo)
    named = getattr(cleared, "scratch", ())
    assert len(named) == 200 and cleared.scratch_found == 205
    assert [e.sha256 is not None for e in named[:3]] == [True, True, False]
    cut = cleared.scratch_cut
    assert cut is not None
    assert "named the first 200 of 205 entries" in cut
    assert "198 files named by length alone" in cut


def test_a_data_file_the_committed_script_read_from_the_scratch_folder_is_on_the_end_line(
    tmp_path: Path,
) -> None:
    # The review's route: a committed script runs text from a scratch file, which is gone when
    # the review reads the attempt. Its digest is on the end line and in the listing.
    run, worktree, home = _setup(tmp_path, before="exec(open('.physgate/scratch/gain.txt').read())")
    _write(worktree, {".physgate/scratch/gain.txt": "import helper\nhelper.GAIN = 9.0\n"})
    done = _session_run(worktree, home, f"{MODULE}/sim.py")
    assert done.returncode == 0, done.stderr
    series = _end(run, worktree, _collected(run, worktree, home), own=(home,))
    assert [r.record_id for r in series.records] == ["step"]
    data = hashlib.sha256(b"import helper\nhelper.GAIN = 9.0\n").hexdigest()
    held = [(e.path, e.sha256) for e in getattr(series, "scratch", ())]
    assert held == [(".physgate/scratch/gain.txt", data)]


# ── bytecode a session committed itself ──────────────────────────────────────


def test_a_session_s_own_commit_of_bytecode_inside_its_module_is_out_of_scope(
    tmp_path: Path,
) -> None:
    run, worktree = _run(tmp_path)
    _write(
        worktree,
        {
            f"{MODULE}/__pycache__/base.{TAG}.pyc": "planted\n",
            f"{MODULE}/old.PYC": "planted\n",
            f"{MODULE}/a.py": "x = 2\n",
        },
    )
    _git(worktree, "add", "-A")
    _git(worktree, "commit", "-q", "-m", "not the orchestrator's commit")
    commit = _git(worktree, "rev-parse", "HEAD")
    assert sorted(_scope(run, commit)) == [
        f"{MODULE}/__pycache__/base.{TAG}.pyc (compiled Python inside the module, which the "
        "interpreter runs in place of its source: never stage or commit it, and remove this)",
        f"{MODULE}/old.PYC (compiled Python inside the module, which the interpreter runs in "
        "place of its source: never stage or commit it, and remove this)",
    ]


def test_bytecode_a_session_staged_itself_reaches_the_commit_and_is_out_of_scope(
    tmp_path: Path,
) -> None:
    run, worktree = _run(tmp_path)
    _write(worktree, {f"{MODULE}/a.py": "x = 2\n", f"{MODULE}/__pycache__/a.{TAG}.pyc": "c\n"})
    _git(worktree, "add", "-f", f"{MODULE}/__pycache__/a.{TAG}.pyc")
    commit = commit_attempt(worktree, SUBTASK, 1, "session-1", repo=run.repo)
    assert f"{MODULE}/__pycache__/a.{TAG}.pyc" in _changed(run, commit)
    assert [v.split(" (")[0] for v in _scope(run, commit)] == [f"{MODULE}/__pycache__/a.{TAG}.pyc"]


# ── the refusals, each on a row ──────────────────────────────────────────────


def test_a_worktree_whose_pointer_does_not_verify_leaves_the_clearing_incomplete(
    tmp_path: Path,
) -> None:
    run, worktree = _run(tmp_path)
    pointer = worktree / ".git"
    held = pointer.read_bytes()
    pointer.write_text(f"gitdir: {tmp_path / 'not-the-run-s'}\n")
    try:
        cleared = left_out.clear_left_out(worktree, repo=run.repo)
    finally:
        pointer.write_bytes(held)
    assert not cleared.complete
    assert [p for p, _ in cleared.refused] == ["."]


def test_an_entry_that_cannot_be_recorded_leaves_the_clearing_incomplete(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    run, worktree = _run(tmp_path)
    _write(worktree, {f"modules/control/__pycache__/law.{TAG}.pyc": "c\n"})

    def unreadable(_parent: int, _name: str) -> bytes | None:
        msg = "a fault while it was recorded"
        raise RuntimeError(msg)

    monkeypatch.setattr(left_out, "_read_compiled", unreadable)
    cleared = left_out.clear_left_out(worktree, repo=run.repo)
    assert not cleared.complete
    assert cleared.refused == (
        (
            f"modules/control/__pycache__/law.{TAG}.pyc",
            "it could not be recorded or removed (RuntimeError)",
        ),
    )


@pytest.mark.skipif(os.geteuid() == 0, reason="the superuser removes any file")
def test_a_compiled_file_that_cannot_be_removed_refuses_the_attempt(tmp_path: Path) -> None:
    run, worktree = _run(tmp_path)
    _write(worktree, {f"{MODULE}/a.py": "x = 2\n", "modules/control/law.pyc": "c\n"})
    folder = worktree / "modules" / "control"
    folder.chmod(0o500)
    try:
        cleared = left_out.clear_left_out(worktree, repo=run.repo)
        # Only a bytecode folder's own mode is changed: this one is the module's, left as it was.
        assert stat.S_IMODE(folder.stat().st_mode) == 0o500
        series = SessionSeries(left_out_incomplete=not cleared.complete)
        refused_by, _ = _checked(run, worktree, series)
    finally:
        folder.chmod(0o700)
    assert not cleared.complete
    assert [p for p, _ in cleared.refused] == ["modules/control/law.pyc"]
    assert refused_by == "series"


def test_an_end_line_that_says_incomplete_still_refuses_when_read_back_from_the_log(
    tmp_path: Path,
) -> None:
    # A run resumed between the session's end and its judging reads the end line from the log.
    left = SessionSeries(left_out_incomplete=True)
    rig = Rig(tmp_path / "loop", dispatcher=FakeDispatcher(series={1: left}))
    loop = rig.open()
    loop.start(plan("s1"))
    loop.run()
    loop.close()
    ended = [
        e for e in read_events(tmp_path / "loop" / "events.jsonl") if isinstance(e, SessionEnded)
    ]
    assert ended and ended[0].series.left_out_incomplete
    run, worktree = _run(tmp_path / "git")
    refused_by, _ = _checked(run, worktree, ended[0].series)
    assert refused_by == "series"
    reason = apply_module.LEFT_OUT_INCOMPLETE
    assert "could not all be recorded and removed" in reason


def test_the_loop_hands_the_review_an_attempt_whose_session_left_bytecode_alone(
    tmp_path: Path,
) -> None:
    left = SessionSeries(
        bytecode=(
            Bytecode(path=f"modules/control/__pycache__/law.{TAG}.pyc", sha256="a" * 64, length=1),
        ),
        bytecode_found=1,
    )
    rig = Rig(tmp_path, dispatcher=FakeDispatcher(series={1: left}))
    loop = rig.open()
    loop.start(plan("s1"))
    loop.run()
    loop.close()
    (reviewed,) = rig.reviewer.seen
    assert reviewed.series is not None
    shown = json.loads(reviewed.series.model_dump_json())
    assert shown["bytecode"][0]["files"][0]["path"] == f"modules/control/__pycache__/law.{TAG}.pyc"
