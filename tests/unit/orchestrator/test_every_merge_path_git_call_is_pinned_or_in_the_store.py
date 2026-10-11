"""Every git call on the merge path holds to the commit's rule, or reads the clean object store.

The commit of a role's work verifies the worktree's ``.git`` pointer once, then runs each git
command pinned to the admin directory that check returned (``--git-dir``), so a pointer swapped
after the check cannot redirect a command. The merge path (opening worktrees, the write-scope
check, the proposals, the merge and its idempotency check, the run branch's check, the review's
base and patch, the worktree's removal) holds to the same rule: each command either runs pinned
to the verified git directory of the repository or worktree it runs in, or runs in the clean
store. The repository is either an ordinary one, whose own ``.git`` directory is the one pinned,
or itself a linked worktree, whose pointer is checked like any worktree's.

Inert markers only: a decoy admin directory holds a ``HEAD``, a ``commondir`` and a ``gitdir``
and nothing git runs; the decoy common directory is an empty repository git created.
"""

from __future__ import annotations

import os
import subprocess
from pathlib import Path
from typing import Any

import pytest

import physgate.orchestrator.apply as apply_module
import physgate.orchestrator.merge as merge_module
from physgate.orchestrator.apply import GitChangeChecker, StoreKeeper
from physgate.orchestrator.git import git as real_git
from physgate.orchestrator.git import harness_git
from physgate.orchestrator.git import merge_base as real_merge_base
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


def _target(tmp_path: Path, layout: str = "linked") -> tuple[Path, str]:
    """A repository, ordinary or a linked worktree of another; it and its first commit."""
    origin = tmp_path / ("target" if layout == "plain" else "origin")
    (origin / "m1").mkdir(parents=True)
    (origin / "m1" / "a.txt").write_text("0\n")
    _git(origin, "init", "-q", "-b", "main")
    _git(origin, "add", "-A")
    _git(origin, "commit", "-q", "-m", "start")
    if layout == "plain":
        return origin, _git(origin, "rev-parse", "HEAD")
    target = tmp_path / "target"
    _git(origin, "worktree", "add", "-q", "-b", "target", str(target))
    return target, _git(target, "rev-parse", "HEAD")


def _admin(worktree: Path) -> Path:
    """The admin directory a linked worktree's ``.git`` pointer names, read from the file."""
    if (worktree / ".git").is_dir():
        return (worktree / ".git").resolve()  # an ordinary repository's own git directory
    pointer = (worktree / ".git").read_text().strip().removeprefix("gitdir:").strip()
    return Path(pointer).resolve()


def _recording(monkeypatch: pytest.MonkeyPatch) -> list[tuple[list[str], str]]:
    calls: list[tuple[list[str], str]] = []
    real_run = subprocess.run

    def recording_run(argv: list[str], **kwargs: Any) -> Any:  # noqa: ANN401
        calls.append((list(argv), str(kwargs.get("cwd"))))
        return real_run(argv, **kwargs)

    monkeypatch.setattr(subprocess, "run", recording_run)
    return calls


def _unpinned(calls: list[tuple[list[str], str]], admins: dict[str, Path]) -> list[str]:
    """Every harness git call that is neither pinned to its directory's admin nor in a store."""
    exe = harness_git().path
    found: list[str] = []
    for argv, cwd in calls:
        if not argv or argv[0] != exe:
            continue
        if argv[1:] == ["--version"]:
            continue  # resolving the harness's git, run from the filesystem root
        if "--file" in argv and "--no-includes" in argv and cwd == "/":
            continue  # the object format, read as data from a config file
        if "init" in argv and "--bare" in argv and Path(argv[-1]).name.startswith(_STORE_PREFIX):
            continue  # making a clean store
        if "--git-dir" in argv:
            named = argv[argv.index("--git-dir") + 1]
            if Path(named).name.startswith(_STORE_PREFIX) and cwd == named:
                continue  # read in a clean store
            tree = argv[argv.index("--work-tree") + 1] if "--work-tree" in argv else None
            admin = admins.get(str(Path(cwd).resolve()))
            if admin is not None and Path(named) == admin and tree == cwd:
                continue  # pinned to the verified admin directory
        found.append(f"{cwd}: {' '.join(argv[1:])}")
    return found


def _flow(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, layout: str = "linked"
) -> tuple[list[tuple[list[str], str]], dict[str, Path], list[Path]]:
    """Every merge-path step once: (the git calls made, each directory's admin, the dirs)."""
    repo, start = _target(tmp_path, layout)
    run = RunGit(repo=repo, run_dir=tmp_path / "run", run_id="r1")
    graph = tmp_path / "graph"
    graph.mkdir()
    calls = _recording(monkeypatch)
    run.open_run_branch(start)
    worktree = run.open_subtask("m1")
    admins = {str(path.resolve()): _admin(path) for path in (repo, run.integration, worktree)}
    (worktree / "m1" / "a.txt").write_text("1\n")
    attempt = commit_attempt(worktree, "m1", 1, "sess-1")
    assert run.open_subtask("m1") == worktree  # a repair attempt's worktree, already there
    assert (
        GitChangeChecker(run, graph, {"m1": "m1"}).check("m1", attempt, "role").refused_by is None
    )
    assert StoreKeeper(run, graph).proposals("m1", attempt) == []
    merger = GitMerger(run, removal_timeout_s=60)
    before = merger.review_base(attempt)
    assert "+1" in merger.artefact_diff(attempt)
    merged = merger.merge("m1", 1, attempt, "merge m1")
    assert merger.merge("m1", 1, attempt, "merge m1") == merged  # found, not made again
    assert merger.run_branch_moved(before, attempt) is None
    assert merger.remove_worktree("m1").outcome == "removed"
    return calls, admins, [repo, run.integration, worktree]


@pytest.mark.parametrize("layout", ["plain", "linked"])
def test_every_merge_path_call_is_pinned_or_in_the_store(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, layout: str
) -> None:
    calls, admins, places = _flow(tmp_path, monkeypatch, layout)
    # The control: the flow ran git in the repository and in both worktrees.
    ran_in = {cwd for argv, cwd in calls if "--work-tree" in argv}
    assert {str(place) for place in places} <= ran_in, ran_in
    assert _unpinned(calls, admins) == []


def test_history_is_walked_in_the_store_never_in_the_repository(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    calls, _, _ = _flow(tmp_path, monkeypatch)
    walks = [(argv, cwd) for argv, cwd in calls if "merge-base" in argv or "--merges" in argv]
    # Both walks ran: merge bases (check, proposals, review, merge) and a branch's merges.
    assert {"merge-base" in argv for argv, _ in walks} == {True, False}, walks
    for argv, cwd in walks:
        named = argv[argv.index("--git-dir") + 1] if "--git-dir" in argv else ""
        assert Path(named).name.startswith(_STORE_PREFIX), argv
        assert cwd == named, (cwd, argv)


def _decoy_admin(tmp_path: Path, worktree: Path, head: str) -> Path:
    """An admin directory that would pass a pointer check, over an empty common directory."""
    common = tmp_path / "decoy-common"
    _git(tmp_path, "init", "-q", "--bare", str(common))
    admin = tmp_path / "decoy-admin"
    admin.mkdir()
    (admin / "HEAD").write_text(f"{head}\n")
    (admin / "commondir").write_text(f"{common}\n")
    (admin / "gitdir").write_text(f"{worktree / '.git'}\n")
    return admin


def test_the_merge_s_result_is_read_through_the_admin_directory_it_ran_in(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    repo, start = _target(tmp_path)
    run = RunGit(repo=repo, run_dir=tmp_path / "run", run_id="r1")
    run.open_run_branch(start)
    worktree = run.open_subtask("m1")
    (worktree / "m1" / "a.txt").write_text("1\n")
    attempt = commit_attempt(worktree, "m1", 1, "sess-1")
    decoy = _decoy_admin(tmp_path, run.integration, start)

    def swapping_git(cwd: Path, *args: str, **kwargs: Any) -> str:  # noqa: ANN401
        out = real_git(cwd, *args, **kwargs)
        if args[:2] == ("merge", "--no-ff"):
            # The integration worktree's pointer, swapped after the merge and before its result
            # is read: a read that followed the pointer would answer from the decoy.
            (run.integration / ".git").write_text(f"gitdir: {decoy}\n")
        return out

    monkeypatch.setattr(merge_module, "git", swapping_git)
    merged = GitMerger(run, removal_timeout_s=60).merge("m1", 1, attempt, "merge m1")
    assert merged != start
    assert _git(repo, "rev-parse", run.run_branch) == merged


def test_the_change_check_reads_through_the_pointer_it_verified(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    repo, start = _target(tmp_path)
    run = RunGit(repo=repo, run_dir=tmp_path / "run", run_id="r1")
    run.open_run_branch(start)
    worktree = run.open_subtask("m1")
    (worktree / "out.txt").write_text("outside the module\n")
    attempt = commit_attempt(worktree, "m1", 1, "sess-1")
    graph = tmp_path / "graph"
    graph.mkdir()
    real_admin = _admin(repo)
    decoy = _decoy_admin(tmp_path, repo, start)

    def swapping_merge_base(*args: Any, **kwargs: Any) -> str:  # noqa: ANN401
        base = real_merge_base(*args, **kwargs)
        # The repository's pointer, swapped after the base is found and before the scope check
        # reads the attempt's changes: a read that followed it would find none of the objects.
        (repo / ".git").write_text(f"gitdir: {decoy}\n")
        return base

    monkeypatch.setattr(apply_module, "merge_base", swapping_merge_base)
    found = GitChangeChecker(run, graph, {"m1": "m1"}).check("m1", attempt, "role")
    assert (found.refused_by, found.subject) == ("write_scope", "out.txt")
    (repo / ".git").write_text(f"gitdir: {real_admin}\n")
    proposals = StoreKeeper(run, graph).proposals("m1", attempt)
    assert proposals == []
