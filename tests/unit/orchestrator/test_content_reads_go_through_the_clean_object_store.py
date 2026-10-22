"""The harness's remaining content reads run in the clean object store, not in the repository.

A role session works in the run's repository and can leave files in its git directory. A read
run inside that repository honours them; a read through the clean object store (a bare
directory that reaches the repository's objects and nothing else) cannot. These reads moved
there: a proposal's bytes (``show``), the target's tree at the run's start (``ls-tree``) and its
object format, a merge's parents (``rev-list``), a recorded commit's tree, every history the
rerun comparison walks (``log``), and an attempt's changed paths and its patch (``diff``). Ref
names are still resolved in the repository, the only place refs are; only the objects behind
them are read in the store.

Inert markers only. A ``shallow`` file in the git directory lists commits whose parents git then
treats as absent: it runs nothing, and its only effect is what git's history reads report. For
the history reads the test asserts the harness reads the same with and without it. The point
reads (a blob, a tree listing, a tree id, the object format) have no inert setting that changes
their output (abbreviation, colour, diff prefixes and a committed ``.gitattributes`` naming an
unconfigured diff driver were each tried); for those the test checks that git ran in the store.
"""

from __future__ import annotations

import json
import os
import subprocess
from pathlib import Path
from typing import Any

import pytest

from physgate.evaluation.observe.manifest import _tree
from physgate.evaluation.observe.sequence import RunView
from physgate.orchestrator.apply import ProposalRefusedError, read_proposals
from physgate.orchestrator.decompose import _require_library_fits
from physgate.orchestrator.git import changes_between, diff_text, head_of
from physgate.orchestrator.merge import GitMerger, RunGit, commit_attempt

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
_STORE_PREFIX = "physgate-git-store-"


def _git(cwd: Path, *args: str) -> str:
    return subprocess.run(
        ["git", "-c", "commit.gpgsign=false", *args],
        cwd=cwd,
        env=_ENV,
        capture_output=True,
        text=True,
        check=True,
    ).stdout.strip()


def _commit(repo: Path, files: dict[str, str], message: str) -> str:
    for name, content in files.items():
        (repo / name).parent.mkdir(parents=True, exist_ok=True)
        (repo / name).write_text(content)
    _git(repo, "add", "-A")
    _git(repo, "commit", "-q", "-m", message)
    return _git(repo, "rev-parse", "HEAD")


def _repo(root: Path) -> tuple[Path, str, str]:
    """A repository with two commits; the repository, the first and the second."""
    repo = root / "repo"
    repo.mkdir(parents=True)
    _git(repo, "init", "-q", "-b", "main")
    first = _commit(repo, {"m.txt": "one\n"}, "one")
    second = _commit(repo, {"m.txt": "two\n"}, "two")
    return repo, first, second


def _mark_shallow(git_dir: Path, *commits: str) -> None:
    """The inert marker: git now treats these commits as having no parents."""
    (git_dir / "shallow").write_text("".join(f"{c}\n" for c in commits))


def _recording(monkeypatch: pytest.MonkeyPatch) -> list[tuple[list[str], str]]:
    """Every subprocess the harness starts, as (argv, working directory)."""
    calls: list[tuple[list[str], str]] = []
    real_run = subprocess.run

    def recording_run(argv: list[str], **kwargs: Any) -> Any:  # noqa: ANN401
        calls.append((list(argv), str(kwargs.get("cwd"))))
        return real_run(argv, **kwargs)

    monkeypatch.setattr(subprocess, "run", recording_run)
    return calls


def _ran_in_store(calls: list[tuple[list[str], str]], *command: str) -> None:
    """Every recorded git call whose arguments end with ``command`` ran in a clean store."""
    found = [
        (argv, cwd)
        for argv, cwd in calls
        if len(argv) >= len(command) and argv[-len(command) :] == list(command)
    ]
    assert found, (command, calls)
    for argv, cwd in found:
        assert "--git-dir" in argv, argv
        store = argv[argv.index("--git-dir") + 1]
        assert Path(store).name.startswith(_STORE_PREFIX), argv
        assert cwd == store, (cwd, argv)


# ── a proposal's bytes ─────────────────────────────────────────────────────────


def test_a_proposal_is_read_from_the_store(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    repo, base, _ = _repo(tmp_path)
    path = ".physgate/proposals/motor.torque.json"
    commit = _commit(repo, {path: "not json\n"}, "proposal")
    (tmp_path / "graph").mkdir()
    calls = _recording(monkeypatch)
    with pytest.raises(ProposalRefusedError, match="is not JSON"):
        read_proposals(repo, base, commit, tmp_path / "graph", role="mechanical")
    _ran_in_store(calls, "show", f"{commit}:{path}")


# ── the target's tree and object format at the run's start ─────────────────────


def test_the_library_check_reads_the_target_tree_and_format_from_the_store(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    repo, _, commit = _repo(tmp_path)
    calls = _recording(monkeypatch)
    # The same bytes where the library goes: the check passes, having read both from the store.
    _require_library_fits(repo, commit, {Path("m.txt"): b"two\n"})
    _ran_in_store(calls, "ls-tree", "-r", "-z", "--full-tree", commit)
    _ran_in_store(calls, "rev-parse", "--show-object-format")


# ── a recorded commit's tree ───────────────────────────────────────────────────


def test_a_recorded_commit_s_tree_is_read_from_the_store(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    repo, _, commit = _repo(tmp_path)
    expected = _git(repo, "rev-parse", f"{commit}^{{tree}}")
    calls = _recording(monkeypatch)
    assert _tree(repo, commit) == expected
    _ran_in_store(calls, "rev-parse", "--verify", f"{commit}^{{tree}}")


# ── a merge's parents ──────────────────────────────────────────────────────────


def _merged_run(tmp_path: Path) -> tuple[RunGit, str, str, str]:
    """A run branch holding one merge: the run, the branch before it, the attempt, the merge."""
    repo, _, start = _repo(tmp_path)
    run = RunGit(repo=repo, run_dir=tmp_path / "run", run_id="r1")
    run.open_run_branch(start)
    worktree = run.open_subtask("m1")
    (worktree / "m1.txt").write_text("attempt\n")
    attempt = commit_attempt(worktree, "m1", 1, "sess-1", repo=run.repo)
    before = head_of(repo, run.run_branch)
    merger = GitMerger(run, removal_timeout_s=60)
    merged = merger.merge("m1", 1, attempt, "merge m1")
    return run, before, attempt, merged


def test_a_merge_s_parents_are_its_own_whatever_the_repository_s_shallow_file_says(
    tmp_path: Path,
) -> None:
    run, before, attempt, merged = _merged_run(tmp_path)
    merger = GitMerger(run, removal_timeout_s=60)
    # The branch moved by exactly the merge of the pending attempt: not a move to report.
    assert merger.run_branch_moved(before, attempt) is None
    _mark_shallow(run.repo / ".git", merged)
    assert merger.run_branch_moved(before, attempt) is None


def test_a_merge_s_parents_are_read_from_the_store(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    run, before, attempt, merged = _merged_run(tmp_path)
    calls = _recording(monkeypatch)
    GitMerger(run, removal_timeout_s=60).run_branch_moved(before, attempt)
    _ran_in_store(calls, "rev-list", "--parents", "-n", "1", merged)


# ── the histories the rerun comparison walks ───────────────────────────────────


def _observed_run(tmp_path: Path) -> tuple[Path, Path, Path, str, str]:
    """A run directory: (run dir, target repo, store repo, run branch tip, store head)."""
    repo, _, start = _repo(tmp_path)
    run_dir = tmp_path / "run"
    run_dir.mkdir()
    (run_dir / "run.json").write_text(json.dumps({"run_id": "r1"}))
    integration = run_dir / "worktrees" / "_integration"
    _git(repo, "worktree", "add", "-q", "-b", "physgate/r1/run", str(integration), start)
    _commit(integration, {"a.txt": "a\n"}, "run one")
    tip = _commit(integration, {"a.txt": "b\n"}, "run two")
    _git(repo, "branch", "physgate/r1/m1", start)
    store = run_dir / "store"
    store.mkdir()
    _git(store, "init", "-q", "-b", "main")
    _commit(store, {"journal.jsonl": "1\n"}, "store one")
    head = _commit(store, {"journal.jsonl": "2\n"}, "store two")
    return run_dir, repo, store, tip, head


def test_the_rerun_comparison_walks_the_same_history_whatever_shallow_files_say(
    tmp_path: Path,
) -> None:
    run_dir, repo, store, tip, head = _observed_run(tmp_path)
    clean = RunView(run_dir)
    clean_trees, clean_branches = dict(clean.trees), clean.git_trees()
    # Every branch and the store keep their whole history: four commits on the run branch's
    # line (two from main, two on the run), the subtask branch's two, and the store's two.
    assert [len(entry["trees"]) for entry in clean_branches] == [2, 4, 2]
    _mark_shallow(repo / ".git", tip)
    _mark_shallow(store / ".git", head)
    marked = RunView(run_dir)
    assert marked.trees == clean_trees
    assert marked.git_trees() == clean_branches


def test_the_rerun_comparison_walks_history_in_the_store(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    run_dir, _, _, tip, head = _observed_run(tmp_path)
    calls = _recording(monkeypatch)
    RunView(run_dir).git_trees()
    _ran_in_store(calls, "log", "--format=%H %T", "--stdin")
    _ran_in_store(calls, "log", "--topo-order", "--format=%T", tip)
    _ran_in_store(calls, "log", "--topo-order", "--format=%T", head)


# ── an attempt's changed paths and its patch ───────────────────────────────────


def test_an_attempt_s_changes_and_patch_are_read_from_the_store(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    repo, first, second = _repo(tmp_path)
    calls = _recording(monkeypatch)
    assert [change.path for change in changes_between(repo, first, second)] == ["m.txt"]
    assert "+two" in diff_text(repo, first, second)
    _ran_in_store(calls, "diff", "--raw", "-z", "--no-renames", "--no-abbrev", first, second)
    _ran_in_store(calls, "diff", "--no-ext-diff", "--no-textconv", "--no-color",
                  "--submodule=short", first, second)  # fmt: skip
