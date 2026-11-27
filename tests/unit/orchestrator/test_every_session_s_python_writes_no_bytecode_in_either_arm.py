"""Every session's Python writes no bytecode, in both arms, and a run records that it did not.

An interpreter caches each module it imports beside that module's source, so a session's script
that imported another module's code left that module's cache in the worktree, outside its own
module, and its attempt out of scope. Every session is now spawned with ``PYTHONDONTWRITEBYTECODE``
set: role sessions, reviewers, the decomposition call and the raw arm's sessions all take their
environment from the one function that builds it. That changes what a session ran under, so a
run records it as a field of its own, compared like every pin the two arms must share: a run
whose sessions wrote bytecode is no pair for one whose sessions wrote none. A run recorded before
the field existed reads as having written it, and its recorded digest does not move.

Through the dispatcher, a stand-in role session running the real hook chain finds the variable
in its environment, and what it leaves in the scratch folder or as bytecode reaches no commit.
"""

from __future__ import annotations

import inspect
import json
import os
import stat
import subprocess
import sys
from collections.abc import Callable
from pathlib import Path
from types import ModuleType
from typing import Any

import pytest
import test_a_session_s_hooks_never_fork_the_run_s_own_records as base
from orch_helpers import make_config
from test_a_session_s_hooks_never_fork_the_run_s_own_records import MODEL, SESSION, Run, leftovers

from physgate.evaluation.per_role.arms import raw
from physgate.orchestrator import decompose, dispatch, invocation
from physgate.orchestrator.apply import LEFT_OUT_INCOMPLETE, GitChangeChecker
from physgate.orchestrator.dispatch import ClaudeDispatcher
from physgate.orchestrator.exceptions import GitError
from physgate.orchestrator.git import merge_base
from physgate.orchestrator.invocation import isolated_env
from physgate.orchestrator.ports import SessionReport
from physgate.orchestrator.run_config import RunConfig, load_run_config
from physgate.reviewers import claude as reviewers
from physgate.series.collect import writer_source
from physgate.series.seal import AttemptBytecode, AttemptSeries, Bytecode
from physgate.series.summary import listing

__all__ = ["leftovers"]

PINS = ("2.1.272", "2.1.283", "2.1.301", "2.1.322")


def _env(version: str) -> dict[str, str]:
    return isolated_env(
        home=Path("/h"),
        config_dir=Path("/c"),
        binary="/opt/bin/claude",
        claude_version=version,
        max_retries=0,
        max_output_tokens=64000,
        base_url=None,
        api_key=None,
    )


@pytest.mark.parametrize("version", PINS)
def test_every_session_s_environment_tells_its_python_to_write_no_bytecode(version: str) -> None:
    assert _env(version).get("PYTHONDONTWRITEBYTECODE") == "1"


def test_each_kind_of_session_takes_its_environment_from_that_one_function() -> None:
    """Role sessions, the raw arm's sessions, reviewers and the decomposition call alike."""
    spawners: dict[ModuleType, Callable[..., Any]] = {
        dispatch: dispatch.ClaudeDispatcher._run_session,
        raw: raw._session,
        reviewers: reviewers.ClaudeReviewer._spawn,
        decompose: decompose.call,
    }
    for module, spawner in spawners.items():
        assert vars(module)["isolated_env"] is isolated_env, module.__name__
        assert "env = isolated_env(" in inspect.getsource(spawner), spawner.__qualname__


def test_a_run_records_that_its_sessions_python_writes_no_bytecode() -> None:
    recorded = getattr(invocation, "session_python_bytecode", lambda: None)()
    assert recorded == "not_written"
    field = RunConfig.model_fields.get("python_bytecode")
    assert field is not None and field.is_required()
    config = make_config()
    assert config.python_bytecode == "not_written"
    assert b'"python_bytecode":"not_written"' in config.canonical_bytes()


def test_a_run_recorded_before_the_field_reads_as_writing_bytecode_and_keeps_its_digest(
    tmp_path: Path,
) -> None:
    before = make_config(python_bytecode="written")
    assert b"python_bytecode" not in before.canonical_bytes()
    path = tmp_path / "run.json"
    path.write_bytes(before.canonical_bytes())
    read = load_run_config(path)
    assert read.python_bytecode == "written"
    assert read.sha256() == before.sha256()


# ── through the dispatcher ───────────────────────────────────────────────────

#: Inserted into the stand-in before it writes its module file: it records what its environment
#: says of bytecode, leaves a helper in the scratch folder and runs it (the helper imports the
#: module's code, as a session's script does), then writes bytecode outside its module as a
#: program that ignores the variable would.
STEPS = r"""
if MODE == "scratch":
    with open(os.path.join(FLAGS, "variable"), "w") as out:
        out.write(os.environ.get("PYTHONDONTWRITEBYTECODE", "unset"))
    os.makedirs(".physgate/scratch", exist_ok=True)
    with open(".physgate/scratch/helper.py", "w") as out:
        out.write("import sys\nsys.path.insert(0, 'modules/power')\nimport base\n")
    subprocess.run([sys.executable, ".physgate/scratch/helper.py"], check=True)
    with open(os.path.join(FLAGS, "cached"), "w") as out:
        out.write(str(os.path.isdir("modules/power/__pycache__")))
    import py_compile
    py_compile.compile(
        "modules/power/base.py",
        cfile="elsewhere/__pycache__/base.cpython-312.pyc",
        doraise=True,
    )
"""


class ScratchRun(Run):
    """The rig's run, its stand-in leaving a helper and bytecode behind."""

    def __init__(self, tmp_path: Path) -> None:
        super().__init__(tmp_path, "scratch")
        marker = 'os.makedirs("modules/power", exist_ok=True)'
        assert marker in SESSION
        prelude = f"FLAGS = {str(self.flags)!r}\nMODE = 'scratch'\nMODEL_NAME = {MODEL!r}\n"
        self.binary.write_text(
            f"#!{sys.executable}\n{prelude}{SESSION.replace(marker, STEPS + marker, 1)}"
        )
        self.binary.chmod(self.binary.stat().st_mode | stat.S_IXUSR)


def test_a_role_session_finds_the_variable_and_leaves_nothing_of_scratch_or_bytecode_committed(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, leftovers: list[int]
) -> None:
    run = ScratchRun(tmp_path)
    dispatcher: ClaudeDispatcher = run.dispatcher(monkeypatch)
    report = dispatcher.run(run.request(), run.spawned)
    assert (run.flags / "variable").read_text() == "1"
    assert (run.flags / "cached").read_text() == "False"
    commit = report.attempt_commit
    assert commit is not None, report.end
    repo = run.run.repo
    since = merge_base(repo, run.run.run_branch, commit)
    changed = subprocess.run(
        ["git", "diff", "--name-only", since, commit],
        cwd=repo,
        env=base.GITENV,
        capture_output=True,
        text=True,
        check=True,
    ).stdout.split()
    assert changed == ["modules/power/a.py"]
    worktree = Path(report.worktree or "")
    assert not (worktree / ".physgate" / "scratch").exists()
    assert not (worktree / "elsewhere" / "__pycache__").exists()
    sdir = run.session_dir()
    assert (sdir / "left_out_before.json").is_file(), "the session's start cleared nothing"
    ended = json.loads((sdir / "left_out.json").read_text())
    assert ".physgate/scratch" in ended["removed"]
    assert "elsewhere/__pycache__/base.cpython-312.pyc" in ended["removed"]
    assert ended["refused"] == []
    started = json.loads((sdir / "left_out_before.json").read_text())
    assert started["removed_count"] == 0
    # The bytecode is evidence of what may have run: on the session's end line, by its digest.
    planted = [b for b in report.series.bytecode if b.path.startswith("elsewhere/")]
    assert [b.path for b in planted] == ["elsewhere/__pycache__/base.cpython-312.pyc"]
    assert planted[0].sha256 is not None and planted[0].length
    assert report.series.bytecode_found == len(report.series.bytecode)


#: Inserted the same way: the stand-in leaves a directory outside its module that no one can list.
LOCKS = r"""
if MODE == "locked":
    os.makedirs("elsewhere/locked", exist_ok=True)
    os.chmod("elsewhere/locked", 0)
"""


class LockedRun(Run):
    """The rig's run, its stand-in leaving a directory that cannot be listed."""

    def __init__(self, tmp_path: Path) -> None:
        super().__init__(tmp_path, "locked")
        marker = 'os.makedirs("modules/power", exist_ok=True)'
        prelude = f"FLAGS = {str(self.flags)!r}\nMODE = 'locked'\nMODEL_NAME = {MODEL!r}\n"
        self.binary.write_text(
            f"#!{sys.executable}\n{prelude}{SESSION.replace(marker, LOCKS + marker, 1)}"
        )
        self.binary.chmod(self.binary.stat().st_mode | stat.S_IXUSR)


def _unlock(root: Path) -> None:
    """Let the row's directory be removed again: what the stand-in locked, wherever it lies."""
    for directory, names, _files in os.walk(root):
        for name in names:
            if name == "locked":
                (Path(directory) / name).chmod(0o700)


def test_a_directory_left_that_cannot_be_listed_refuses_the_attempt_and_stops_nothing(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, leftovers: list[int]
) -> None:
    run = LockedRun(tmp_path)
    dispatcher: ClaudeDispatcher = run.dispatcher(monkeypatch)
    try:
        try:
            ran: object = dispatcher.run(run.request(), run.spawned)
        except GitError as exc:
            ran = exc
        # The session's end raises nothing: before, the commit's walk raised on the directory.
        assert isinstance(ran, SessionReport), ran
        report = ran
        # The session's end clearing could not look below it, so it says so.
        assert report.series.left_out_incomplete, report.series
        ended = json.loads((run.session_dir() / "left_out.json").read_text())
        assert [path for path, _ in ended["refused"]] == ["elsewhere/locked"]
        # The attempt still has its commit, which stages nothing the session left, and the change
        # check refuses it in closed words before its gate.
        commit = report.attempt_commit
        assert commit is not None, report.end
        repo = run.run.repo
        since = merge_base(repo, run.run.run_branch, commit)
        changed = subprocess.run(
            ["git", "diff", "--name-only", since, commit],
            cwd=repo,
            env=base.GITENV,
            capture_output=True,
            text=True,
            check=True,
        ).stdout.split()
        assert changed == []
        graph = run.run.run_dir / "graph"
        graph.mkdir(parents=True, exist_ok=True)
        check = GitChangeChecker(run.run, graph, {"s1": "modules/power"}).check(
            "s1", commit, "electrical", series=report.series
        )
        assert check.refused_by == "series"
        assert check.reason == LEFT_OUT_INCOMPLETE
    finally:
        _unlock(tmp_path)


def test_the_review_s_series_listing_names_each_bytecode_file_a_session_left(
    tmp_path: Path,
) -> None:
    left = AttemptBytecode(
        session_id="session-1",
        found=3,
        files=(
            Bytecode(path="elsewhere/__pycache__/base.cpython-312.pyc", sha256="a" * 64, length=9),
            Bytecode(path="modules/power/x.pyc"),
        ),
    )
    series = AttemptSeries(run_dir=str(tmp_path), subtask_id="s1", attempt=1, bytecode=(left,))
    shown = listing(series).decode()
    assert "# Bytecode left in the worktree" in shown
    assert "Files found: 3." in shown
    assert "elsewhere/__pycache__/base.cpython-312.pyc" in shown and "sha256 " + "a" * 64 in shown
    assert "modules/power/x.pyc" in shown and "and 1 more, not named" in shown
    assert "Bytecode" not in listing(series.model_copy(update={"bytecode": ()})).decode()


#: Inserted the same way: the stand-in records a run through the series writer from a script
#: that leaves the writer's check out, with a compiled file of other code planted beside the
#: helper the script imports, and leaves a note in the scratch folder.
MARKS = r"""
if MODE == "marked":
    import importlib._bootstrap_external as bootstrap
    os.makedirs("modules/power/__pycache__", exist_ok=True)
    with open("modules/power/helper.py", "w") as out:
        out.write("GAIN = 2.0\n")
    with open("modules/power/sim.py", "w") as out:
        out.write(
            "import os, sys\n"
            "sys.path.insert(0, os.path.join(os.getcwd(), '.physgate', 'lib'))\n"
            "import series_writer\n"
            "series_writer._compiled_in_place = lambda base: None\n"
            "import helper\n"
            "series_writer.record('step', title='Fixture, not a simulation', axis='time',\n"
            "    x=('time', 's', [0.0, 0.01]), traces=[('position', 'm', [0.0, helper.GAIN])])\n"
        )
    held = os.stat("modules/power/helper.py")
    code = compile("GAIN = 9.0\n", os.path.abspath("modules/power/helper.py"), "exec")
    tag = sys.implementation.cache_tag
    with open(f"modules/power/__pycache__/helper.{tag}.pyc", "wb") as out:
        out.write(bootstrap._code_to_timestamp_pyc(code, held.st_mtime, held.st_size))
    os.makedirs(".physgate/scratch", exist_ok=True)
    with open(".physgate/scratch/note.txt", "w") as out:
        out.write("a note\n")
    done = subprocess.run([sys.executable, "modules/power/sim.py"], capture_output=True, text=True)
    with open(os.path.join(FLAGS, "sim"), "w") as out:
        out.write(f"{done.returncode} {done.stderr}")
"""


class MarkedRun(Run):
    """The rig's run, its stand-in sealing a record beside a planted compiled file.

    Its run branch holds the series writer, as a decomposed run's does: the session's end puts
    the harness's places back to the run branch, so a writer the session made would be gone.
    """

    def __init__(self, tmp_path: Path) -> None:
        super().__init__(tmp_path, "marked")
        branch = tmp_path / "branch"
        repo = self.run.repo
        git = ["git", "-c", "commit.gpgsign=false"]
        subprocess.run(
            [*git, "worktree", "add", "-q", "--detach", str(branch), self.run.run_branch],
            cwd=repo,
            env=base.GITENV,
            check=True,
        )
        (branch / ".physgate" / "lib").mkdir(parents=True)
        (branch / ".physgate" / "lib" / "series_writer.py").write_bytes(writer_source())
        subprocess.run([*git, "add", "-A"], cwd=branch, env=base.GITENV, check=True)
        subprocess.run(
            [*git, "commit", "-q", "-m", "the series writer"],
            cwd=branch,
            env=base.GITENV,
            check=True,
        )
        head = subprocess.run(
            ["git", "rev-parse", "HEAD"],
            cwd=branch,
            env=base.GITENV,
            capture_output=True,
            text=True,
            check=True,
        ).stdout.strip()
        for argv in (
            ["update-ref", f"refs/heads/{self.run.run_branch}", head],
            ["worktree", "remove", "--force", str(branch)],
        ):
            subprocess.run([*git, *argv], cwd=repo, env=base.GITENV, check=True)
        marker = 'os.makedirs("modules/power", exist_ok=True)'
        prelude = f"FLAGS = {str(self.flags)!r}\nMODE = 'marked'\nMODEL_NAME = {MODEL!r}\n"
        self.binary.write_text(
            f"#!{sys.executable}\n{prelude}{SESSION.replace(marker, MARKS + marker, 1)}"
        )
        self.binary.chmod(self.binary.stat().st_mode | stat.S_IXUSR)


def test_the_dispatcher_s_end_marks_a_record_sealed_beside_compiled_code_and_records_the_scratch(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, leftovers: list[int]
) -> None:
    run = MarkedRun(tmp_path)
    dispatcher: ClaudeDispatcher = run.dispatcher(monkeypatch)
    report = dispatcher.run(run.request(), run.spawned)
    assert (run.flags / "sim").read_text().startswith("0 "), (run.flags / "sim").read_text()
    assert [r.record_id for r in report.series.records] == ["step"], report.series.refused
    tag = sys.implementation.cache_tag
    marked = [b for b in report.series.bytecode if "step" in getattr(b, "records", ())]
    assert [b.path for b in marked] == [f"modules/power/__pycache__/helper.{tag}.pyc"]
    assert marked[0].sha256 is not None
    note = [(e.path, e.kind) for e in getattr(report.series, "scratch", ())]
    assert note == [(".physgate/scratch/note.txt", "file")]
    # On the session's end line as it is dumped, which a resume and the review read.
    dumped = json.loads(report.series.model_dump_json())
    assert dumped["bytecode"][0]["records"] == ["step"]
