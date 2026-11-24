"""What a session leaves in its scratch folder, or as bytecode, is never part of its attempt.

A session's file tools write only in its worktree, and the orchestrator commits whatever the
session left there. So a throwaway helper script was committed with the attempt and shown to its
reviewer; one left outside the module put the attempt out of scope; and a script that imported
another module's code left that module's bytecode cache beside it, outside the module, which a
real run lost an attempt to. Each lost attempt counts against the harness arm.

Now one folder, ``.physgate/scratch``, is never part of an attempt, nor is bytecode anywhere:
the commit leaves both out, and both are removed from the worktree, so neither reaches the
change check, the review, the merged work or the next attempt. What a session changes anywhere
else is judged exactly as before, and a curve computed by code in the folder is refused as code
from outside the module always was. Every row runs real git on a real run's worktree.
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path, PurePosixPath

import pytest

from physgate.orchestrator.apply import GitChangeChecker
from physgate.orchestrator.decompose import Plan, plan_problems
from physgate.orchestrator.dispatch import role_prompt
from physgate.orchestrator.git import diff_text, merge_base
from physgate.orchestrator.merge import RunGit, commit_attempt, write_scope_violations
from physgate.orchestrator.ports import SessionRequest
from physgate.orchestrator.run_config import RunBounds
from physgate.series.collect import WRITER_PATH, collect, writer_source

try:
    from physgate.orchestrator import left_out
except ImportError:  # the code before the folder existed: each row fails on what it asserts
    left_out = None  # type: ignore[assignment]

SCRATCH = str(getattr(left_out, "SCRATCH_DIR", PurePosixPath(".physgate/scratch")))
MODULE = "modules/power"
SUBTASK = "power-1"
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
#: A program that ignores the variable every session is spawned with: bytecode is written.
_WRITES_BYTECODE = {"PATH": "/usr/bin:/bin", "HOME": os.devnull}


def _git(cwd: Path, *args: str) -> str:
    return subprocess.run(
        ["git", "-c", "commit.gpgsign=false", *args],
        cwd=cwd,
        env=_ENV,
        capture_output=True,
        text=True,
        check=True,
    ).stdout.strip()


def _run(tmp_path: Path, tracked: dict[str, bytes] | None = None) -> tuple[RunGit, Path]:
    """A run whose target has two modules and the series writer, and one subtask's worktree."""
    root = Path(os.path.realpath(tmp_path))
    repo = root / "repo"
    files = {
        "README.md": b"a target\n",
        f"{MODULE}/base.py": b"x = 1\n",
        "modules/control/law.py": b"def gain():\n    return 2\n",
        str(WRITER_PATH): writer_source(),
        **(tracked or {}),
    }
    for rel, data in files.items():
        (repo / rel).parent.mkdir(parents=True, exist_ok=True)
        (repo / rel).write_bytes(data)
    _git(repo, "init", "-q", "-b", "main")
    _git(repo, "add", "-A")
    _git(repo, "commit", "-q", "-m", "start")
    run = RunGit(repo=repo, run_dir=root / "run", run_id="r1")
    run.open_run_branch(_git(repo, "rev-parse", "HEAD"))
    return run, run.open_subtask(SUBTASK)


def _write(worktree: Path, files: dict[str, str]) -> None:
    for rel, text in files.items():
        (worktree / rel).parent.mkdir(parents=True, exist_ok=True)
        (worktree / rel).write_text(text)


def _commit(run: RunGit, worktree: Path, attempt: int = 1) -> str:
    return commit_attempt(worktree, SUBTASK, attempt, f"session-{attempt}", repo=run.repo)


def _base(run: RunGit, commit: str) -> str:
    return merge_base(run.repo, run.run_branch, commit)


def _changed(run: RunGit, commit: str) -> list[str]:
    """Every path the attempt changed against where it left the run branch, as git lists them."""
    return _git(run.repo, "diff", "--name-only", _base(run, commit), commit).splitlines()


def _scope(run: RunGit, commit: str) -> list[str]:
    return write_scope_violations(run.repo, _base(run, commit), commit, MODULE)


def _left(worktree: Path) -> list[str]:
    """What of the scratch folder and of bytecode is still on disk in the worktree."""
    found = []
    for directory, dirs, files in os.walk(worktree):
        dirs[:] = [d for d in dirs if d != ".git"]
        for name in files + [d for d in dirs if d.casefold() == "__pycache__"]:
            rel = os.path.relpath(os.path.join(directory, name), worktree)
            if rel.startswith(SCRATCH) or "__pycache__" in rel.casefold() or rel.endswith(".pyc"):
                found.append(rel)
    if os.path.lexists(worktree / SCRATCH):
        found.append(SCRATCH)
    return sorted(set(found))


# ── the three cases that cost an attempt ─────────────────────────────────────


def test_a_helper_left_in_the_scratch_folder_is_in_no_commit_no_diff_and_costs_nothing(
    tmp_path: Path,
) -> None:
    run, worktree = _run(tmp_path)
    _write(
        worktree,
        {
            f"{MODULE}/a.py": "x = 2\n",
            f"{SCRATCH}/helper.py": "print('a throwaway helper')\n",
            f"{SCRATCH}/plots/step.txt": "a note\n",
            # Shaped as a node proposal and as a record: the proposals and records are read from
            # the commit, which holds neither.
            f"{SCRATCH}/proposals/power.supply.json": json.dumps({"id": "power.supply"}),
        },
    )
    commit = _commit(run, worktree)
    assert _changed(run, commit) == [f"{MODULE}/a.py"]
    assert _scope(run, commit) == []
    tree = _git(run.repo, "ls-tree", "-r", "--name-only", commit).splitlines()
    assert not [f for f in tree if f.startswith(".physgate/scratch")]
    # The review's diff and its exported tree are both read from the commit.
    assert "scratch" not in diff_text(run.repo, _base(run, commit), commit)
    assert _left(worktree) == []


def test_a_helper_left_anywhere_else_in_the_worktree_still_puts_the_attempt_out_of_scope(
    tmp_path: Path,
) -> None:
    run, worktree = _run(tmp_path)
    _write(
        worktree,
        {
            f"{MODULE}/a.py": "x = 2\n",
            "helper.py": "print('top')\n",
            "scratch/helper.py": "print('a folder of the same name at the top')\n",
            # Another spelling is another folder, on every volume: it is judged as any other.
            ".physgate/Scratch/helper.py": "print('another spelling')\n",
        },
    )
    commit = _commit(run, worktree)
    assert _scope(run, commit) == [
        ".physgate/Scratch/helper.py (outside modules/power)",
        "helper.py (outside modules/power)",
        "scratch/helper.py (outside modules/power)",
    ]


def test_a_script_that_imports_another_module_leaves_no_bytecode_in_the_attempt(
    tmp_path: Path,
) -> None:
    run, worktree = _run(tmp_path)
    script = worktree / MODULE / "run.py"
    script.write_text(
        "import sys\nsys.path.insert(0, 'modules/control')\nimport law\nprint(law.gain())\n"
    )
    done = subprocess.run(
        [sys.executable, "-E", "-s", str(script)],
        cwd=worktree,
        env=_WRITES_BYTECODE,
        capture_output=True,
        text=True,
        check=True,
    )
    assert done.stdout.strip() == "2"
    cached = list((worktree / "modules" / "control" / "__pycache__").glob("law.*.pyc"))
    assert cached, "the interpreter wrote no cache, so the row proves nothing"
    commit = _commit(run, worktree)
    assert _changed(run, commit) == [f"{MODULE}/run.py"]
    assert _scope(run, commit) == []
    assert _left(worktree) == []


@pytest.mark.parametrize(
    "path",
    [
        "__pycache__/top.cpython-312.pyc",
        "modules/control/__PYCACHE__/law.cpython-312.pyc",
        "modules/control/law.PYC",
        "modules/control/law.pyc",
        ".physgate/lib/__pycache__/helper.cpython-312.pyc",
        "modules/control/__pycache__/anything-at-all.txt",
        f"{MODULE}/__pycache__/base.cpython-312.pyc",
    ],
)
def test_bytecode_in_any_spelling_anywhere_is_left_out_and_removed(
    tmp_path: Path, path: str
) -> None:
    run, worktree = _run(tmp_path)
    _write(worktree, {f"{MODULE}/a.py": "x = 2\n"})
    (worktree / path).parent.mkdir(parents=True, exist_ok=True)
    (worktree / path).write_bytes(b"\x00bytecode")
    commit = _commit(run, worktree)
    assert _changed(run, commit) == [f"{MODULE}/a.py"]
    assert _scope(run, commit) == []
    assert _left(worktree) == []


def test_a_real_source_file_beside_bytecode_is_still_counted(tmp_path: Path) -> None:
    run, worktree = _run(tmp_path)
    _write(
        worktree,
        {
            "modules/control/__pycache__/law.cpython-312.pyc": "cached\n",
            "modules/control/helper.py": "print('beside the cache, outside the module')\n",
            f"{MODULE}/__pycache__/base.cpython-312.pyc": "cached\n",
            f"{MODULE}/helper.py": "print('beside the cache, in the module')\n",
        },
    )
    commit = _commit(run, worktree)
    assert _changed(run, commit) == ["modules/control/helper.py", f"{MODULE}/helper.py"]
    assert _scope(run, commit) == ["modules/control/helper.py (outside modules/power)"]


def test_bytecode_that_reaches_a_commit_by_another_route_is_still_refused(tmp_path: Path) -> None:
    # The commit is the one place bytecode is left out; the scope check counts whatever a commit
    # holds, so a cache that runs in place of its source never reaches the run branch unjudged.
    run, worktree = _run(tmp_path)
    _write(worktree, {"modules/control/__pycache__/law.cpython-312.pyc": "planted\n"})
    _git(worktree, "add", "-A")
    _git(worktree, "commit", "-q", "-m", "not the orchestrator's commit")
    commit = _git(worktree, "rev-parse", "HEAD")
    assert _scope(run, commit) == [
        "modules/control/__pycache__/law.cpython-312.pyc (outside modules/power)"
    ]


# ── nothing is carried, nothing is hidden ────────────────────────────────────


def test_nothing_left_out_survives_into_the_next_attempt_s_worktree(tmp_path: Path) -> None:
    run, worktree = _run(tmp_path)
    _write(
        worktree,
        {
            f"{MODULE}/a.py": "x = 2\n",
            # The module's own ignore rule, which the attempt commits: bytecode it ignores is
            # removed too, so none is carried to the next attempt in this worktree.
            f"{MODULE}/.gitignore": "__pycache__/\n",
            f"{MODULE}/__pycache__/base.cpython-312.pyc": "cached\n",
            "modules/control/__pycache__/law.cpython-312.pyc": "cached\n",
            f"{SCRATCH}/for-the-next-attempt.txt": "a note to the next attempt\n",
        },
    )
    first = _commit(run, worktree)
    assert _left(worktree) == []
    _write(worktree, {f"{MODULE}/b.py": "y = 3\n"})
    second = _commit(run, worktree, attempt=2)
    assert _changed(run, first) == [f"{MODULE}/.gitignore", f"{MODULE}/a.py"]
    assert _changed(run, second) == [f"{MODULE}/.gitignore", f"{MODULE}/a.py", f"{MODULE}/b.py"]
    assert _scope(run, second) == []


def test_a_link_in_the_scratch_folder_s_place_is_removed_as_a_link_and_its_target_kept(
    tmp_path: Path,
) -> None:
    run, worktree = _run(tmp_path)
    kept = Path(os.path.realpath(tmp_path)) / "elsewhere"
    kept.mkdir()
    (kept / "precious.txt").write_text("not the session's\n")
    (worktree / ".physgate").mkdir(exist_ok=True)
    (worktree / SCRATCH).symlink_to(kept)
    _write(worktree, {f"{MODULE}/a.py": "x = 2\n"})
    commit = _commit(run, worktree)
    assert _changed(run, commit) == [f"{MODULE}/a.py"]
    assert not os.path.lexists(worktree / SCRATCH)
    assert (kept / "precious.txt").read_text() == "not the session's\n"


def test_what_a_session_made_unwritable_in_the_scratch_folder_is_removed_too(
    tmp_path: Path,
) -> None:
    run, worktree = _run(tmp_path)
    _write(worktree, {f"{SCRATCH}/locked/deep/file.txt": "x\n", f"{SCRATCH}/shut/f.txt": "y\n"})
    (worktree / SCRATCH / "locked" / "deep").chmod(0o500)
    (worktree / SCRATCH / "locked").chmod(0o500)
    (worktree / SCRATCH / "shut").chmod(0o000)
    commit = _commit(run, worktree)
    assert _changed(run, commit) == []
    assert _left(worktree) == []


def test_bytecode_the_run_branch_tracks_is_kept_and_a_change_to_it_left_out(
    tmp_path: Path,
) -> None:
    tracked = "tools/__pycache__/t.cpython-312.pyc"
    run, worktree = _run(tmp_path, tracked={tracked: b"as the target has it\n"})
    (worktree / tracked).write_bytes(b"rewritten by a program that ignores the variable\n")
    _write(worktree, {f"{MODULE}/a.py": "x = 2\n"})
    commit = _commit(run, worktree)
    assert _changed(run, commit) == [f"{MODULE}/a.py"]
    assert _scope(run, commit) == []
    assert (worktree / tracked).exists()


def test_a_module_directory_with_a_bytecode_part_is_refused_at_the_plan_check() -> None:
    node = {
        "id": "drivetrain.motor",
        "kind": "interface",
        "domain": "electrical",
        "owner_role": "electrical",
        "quantities": {},
        "requirements": [],
        "constrains": [],
        "model": None,
        "geometry_hash": "sha256:0",
        "updated": "2026-11-02T00:00:00Z",
    }

    def problems(module_dir: str) -> list[str]:
        module = {"name": "drive", "role": "electrical", "module_dir": module_dir, "spec": "s"}
        plan = Plan.model_validate_json(
            json.dumps({"modules": [module], "interface_nodes": [node]})
        )
        return plan_problems(plan, ["electrical"], "A brief.")

    assert problems("modules/__PyCache__/drive") == [
        "module 'drive' has a directory with a __pycache__ component, beneath which no attempt "
        "commits anything"
    ]
    assert problems("modules/drive") == []


# ── a curve stands only on committed module code ─────────────────────────────

SCRIPT = """import os, sys
here = os.path.dirname(os.path.abspath(__file__))
while not os.path.isfile(os.path.join(here, ".physgate", "lib", "series_writer.py")):
    here = os.path.dirname(here)
sys.path.insert(0, os.path.join(here, ".physgate", "lib"))
{prelude}
import series_writer
series_writer.record("step", title="Fixture, not a simulation", axis="time",
    x=("time", "s", [0.0, 0.01]), traces=[("position", "m", [0.0, 0.02])],
    inputs={{"seed": (7, "dimensionless")}})
"""


def _recorded(run: RunGit, worktree: Path, script: str, prelude: str = "") -> Path:
    path = worktree / script
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(SCRIPT.format(prelude=prelude))
    done = subprocess.run(
        [sys.executable, "-E", "-s", str(path)],
        cwd=worktree,
        capture_output=True,
        text=True,
        check=False,
        env={"PATH": "/usr/bin:/bin", "HOME": str(run.run_dir)},
    )
    assert done.returncode == 0, done.stderr
    return path


def _collected(run: RunGit, worktree: Path) -> object:
    return collect(
        worktree,
        module_dir=MODULE,
        run_dir=run.run_dir,
        subtask_id=SUBTASK,
        attempt=1,
        session_id="session-1",
        object_format="sha1",
    )


def test_a_record_written_by_a_script_in_the_scratch_folder_is_refused(tmp_path: Path) -> None:
    run, worktree = _run(tmp_path)
    _recorded(run, worktree, f"{SCRATCH}/sim.py")
    series = _collected(run, worktree)
    assert [(e.name, e.reason) for e in series.refused] == [  # type: ignore[attr-defined]
        ("step.json", f"code from outside the module ran: {SCRATCH}/sim.py")
    ]
    assert series.records == ()  # type: ignore[attr-defined]


def test_a_record_whose_script_loaded_a_helper_from_the_scratch_folder_is_refused(
    tmp_path: Path,
) -> None:
    run, worktree = _run(tmp_path)
    _write(worktree, {f"{SCRATCH}/helper.py": "GAIN = 2\n"})
    prelude = f"sys.path.insert(0, os.path.join(here, {SCRATCH!r}))\nimport helper"
    _recorded(run, worktree, f"{MODULE}/sim.py", prelude)
    series = _collected(run, worktree)
    assert [(e.name, e.reason) for e in series.refused] == [  # type: ignore[attr-defined]
        ("step.json", f"code from outside the module ran: {SCRATCH}/helper.py")
    ]


def test_a_record_whose_script_lies_in_a_bytecode_folder_is_refused_at_the_change_check(
    tmp_path: Path,
) -> None:
    # Inside the module, so the collector seals it; the commit leaves the folder out, so the
    # change check finds the script uncommitted, as for any script the attempt did not commit.
    run, worktree = _run(tmp_path)
    _recorded(run, worktree, f"{MODULE}/__pycache__/sim.py")
    series = _collected(run, worktree)
    assert [r.record_id for r in series.records] == ["step"]  # type: ignore[attr-defined]
    commit = _commit(run, worktree)
    graph = run.run_dir / "graph"
    graph.mkdir(parents=True, exist_ok=True)
    check = GitChangeChecker(run, graph, {SUBTASK: MODULE}).check(
        SUBTASK,
        commit,
        "electrical",
        series=series,  # type: ignore[arg-type]
    )
    assert check.refused_by == "series"
    assert check.reason is not None and "did not commit that script" in check.reason


# ── what a session is told ───────────────────────────────────────────────────


def test_a_role_session_is_told_where_a_throwaway_helper_goes() -> None:
    request = SessionRequest(
        subtask_id=SUBTASK,
        attempt=1,
        assigned_role="electrical",
        spec_path=".physgate/specs/power-1.md",
        module_dir=MODULE,
        model="claude-opus-5-5",
        repair_instruction=None,
        bounds=RunBounds(
            binary_max_retries=0,
            session_wall_clock_s=60.0,
            session_max_turns=20,
            infra_retry_delays_s=(),
        ),
    )
    told = role_prompt(request)
    assert f"A throwaway helper script or note goes in {SCRATCH}/" in told
    assert "never part of your attempt" in told
    assert "nothing it computes is accepted as a record" in told
