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
import stat
import subprocess
import sys
from pathlib import Path

import pytest
import test_a_session_s_hooks_never_fork_the_run_s_own_records as base
from orch_helpers import make_config
from test_a_session_s_hooks_never_fork_the_run_s_own_records import MODEL, SESSION, Run, leftovers

from physgate.evaluation.per_role.arms import raw
from physgate.orchestrator import decompose, dispatch, invocation
from physgate.orchestrator.dispatch import ClaudeDispatcher
from physgate.orchestrator.git import merge_base
from physgate.orchestrator.invocation import isolated_env
from physgate.orchestrator.run_config import RunConfig, load_run_config
from physgate.reviewers import claude as reviewers

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
    spawners = {
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
    assert config.python_bytecode == "not_written"  # type: ignore[attr-defined]
    assert b'"python_bytecode":"not_written"' in config.canonical_bytes()


def test_a_run_recorded_before_the_field_reads_as_writing_bytecode_and_keeps_its_digest(
    tmp_path: Path,
) -> None:
    before = make_config(python_bytecode="written")
    assert b"python_bytecode" not in before.canonical_bytes()
    path = tmp_path / "run.json"
    path.write_bytes(before.canonical_bytes())
    read = load_run_config(path)
    assert read.python_bytecode == "written"  # type: ignore[attr-defined]
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
