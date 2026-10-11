"""The merge path reads each commit's own parents, whatever the repository's git directory says.

Three files in a repository's git directory make git see a commit with other parents than the
commit holds: ``shallow`` (the listed commits have none), ``info/grafts`` (the listed commit has
the parents the line names) and the commit graph under ``objects/info/`` (a cache of every
commit's parents that git trusts in place of the commits). A role session can write the first
and the third. Through any of them the write-scope check could diff from another base than the
merge merges from, a merge already made could look like none, and the merge itself could merge
from another base and keep or drop a file neither check saw.

Inert markers only: each is a data file git reads and nothing it runs. The commit graph is
written by git's own ``commit-graph write`` and then one commit's parent entries are rewritten,
as a role could; a control shows plain git reading every marker. Each test asserts the harness
reads the same as without the marker.

The scenario: the run branch starts at S; subtask m2's branch starts there too, and its first
attempt C1 left a file outside its module, which its second attempt C2 keeps. Subtask m1 is
merged meanwhile, so the run branch is at R (S and A1). The honest base of R and C2 is S, so the
scope check sees the stray file. A marker that makes R a child of C1 moves the base to C1, where
the file already is, so the check would pass and the merge would drop it.
"""

from __future__ import annotations

import os
import struct
import subprocess
from dataclasses import dataclass
from pathlib import Path

import pytest

from physgate.orchestrator.apply import GitChangeChecker
from physgate.orchestrator.git import head_of, merge_base, merges_of
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
MARKERS = ("shallow", "grafts", "commit_graph")
#: A commit-graph parent slot that names no parent.
_NO_PARENT = 0x70000000


def _plain(cwd: Path, *args: str, check: bool = True) -> subprocess.CompletedProcess[str]:
    """Plain git, with none of the harness's settings: the control that a marker is live."""
    return subprocess.run(
        ["git", "-c", "commit.gpgsign=false", *args],
        cwd=cwd,
        env=_ENV,
        capture_output=True,
        text=True,
        check=check,
    )


def _git(cwd: Path, *args: str) -> str:
    return _plain(cwd, *args).stdout.strip()


@dataclass(frozen=True)
class Scenario:
    run: RunGit
    common: Path
    start: str
    first: str
    second: str
    other: str
    run_head: str

    @property
    def merger(self) -> GitMerger:
        return GitMerger(self.run, removal_timeout_s=60)

    @property
    def checker(self) -> GitChangeChecker:
        graph = self.run.run_dir / "graph"
        graph.mkdir(exist_ok=True)
        return GitChangeChecker(self.run, graph, {"m1": "m1", "m2": "m2"})


def _scenario(tmp_path: Path) -> Scenario:
    repo = tmp_path / "repo"
    (repo / "m1").mkdir(parents=True)
    (repo / "m2").mkdir()
    (repo / "m1" / "a.txt").write_text("0\n")
    (repo / "m2" / "b.txt").write_text("0\n")
    _git(repo, "init", "-q", "-b", "main")
    _git(repo, "add", "-A")
    _git(repo, "commit", "-q", "-m", "start")
    start = _git(repo, "rev-parse", "HEAD")
    run = RunGit(repo=repo, run_dir=tmp_path / "run", run_id="r1")
    run.open_run_branch(start)
    m2 = run.open_subtask("m2")
    (m2 / "out.txt").write_text("outside the module\n")
    (m2 / "m2" / "b.txt").write_text("1\n")
    first = commit_attempt(m2, "m2", 1, "sess-1")
    (m2 / "m2" / "b.txt").write_text("2\n")
    second = commit_attempt(m2, "m2", 2, "sess-2")
    m1 = run.open_subtask("m1")
    (m1 / "m1" / "a.txt").write_text("1\n")
    other = commit_attempt(m1, "m1", 1, "sess-3")
    run_head = GitMerger(run, removal_timeout_s=60).merge("m1", 1, other, "merge m1")
    return Scenario(run, repo / ".git", start, first, second, other, run_head)


# ── the markers ────────────────────────────────────────────────────────────────


def _forge_graph(repo: Path, common: Path, parents: dict[str, list[str]]) -> None:
    """Write the commit graph with git, then give each listed commit the listed parents.

    Version 1 generations (topological levels) so the one number per commit stays consistent
    when a parent changes. Only the file's parent and level fields are rewritten; its checksum
    is left, as git does not check it when it reads the graph.
    """
    _git(repo, "-c", "commitGraph.generationVersion=1", "commit-graph", "write", "--reachable")
    path = common / "objects" / "info" / "commit-graph"
    data = bytearray(path.read_bytes())
    assert data[:4] == b"CGPH"
    hash_len = 20
    chunks: dict[bytes, int] = {}
    for i in range(data[6] + 1):
        entry = 8 + 12 * i
        chunks[bytes(data[entry : entry + 4])] = struct.unpack(">Q", data[entry + 4 : entry + 12])[
            0
        ]
    oids, cdat = chunks[b"OIDL"], chunks[b"CDAT"]
    count = (cdat - oids) // hash_len
    order = [
        bytes(data[oids + i * hash_len : oids + (i + 1) * hash_len]).hex() for i in range(count)
    ]
    width = hash_len + 16

    def level(position: int) -> int:
        at = cdat + position * width + hash_len + 8
        return int(struct.unpack(">Q", data[at : at + 8])[0] >> 34)

    for commit, new in parents.items():
        assert len(new) <= 2
        at = cdat + order.index(commit) * width + hash_len
        slots = [order.index(p) for p in new] + [_NO_PARENT] * (2 - len(new))
        data[at : at + 8] = struct.pack(">II", *slots)
        old = struct.unpack(">Q", data[at + 8 : at + 16])[0]
        top = max((level(order.index(p)) for p in new), default=0) + 1
        data[at + 8 : at + 16] = struct.pack(">Q", (top << 34) | (old & ((1 << 34) - 1)))
    path.chmod(0o644)
    path.write_bytes(bytes(data))


def _mark(s: Scenario, marker: str, commit: str, parents: list[str]) -> None:
    """Make git see ``commit`` with ``parents`` (shallow: with none, whatever is asked)."""
    if marker == "shallow":
        (s.common / "shallow").write_text(f"{commit}\n")
    elif marker == "grafts":
        (s.common / "info").mkdir(exist_ok=True)
        (s.common / "info" / "grafts").write_text(" ".join([commit, *parents]) + "\n")
    else:
        _forge_graph(s.run.repo, s.common, {commit: parents})


def _seen_parents(s: Scenario, commit: str) -> list[str]:
    """The parents plain git sees for ``commit``: the control that the marker is live."""
    return _git(s.run.repo, "rev-list", "--parents", "-n", "1", commit).split()[1:]


def _cut(s: Scenario, marker: str) -> str:
    """Mark the run's history: shallow cuts C1 from S, the others make R a child of C1."""
    if marker == "shallow":
        _mark(s, marker, s.first, [])
        assert _seen_parents(s, s.first) == []
        return s.first
    _mark(s, marker, s.run_head, [s.first, s.other])
    assert _seen_parents(s, s.run_head) == [s.first, s.other]
    return s.run_head


# ── the base: merge_base, the review's base and the write-scope check ─────────


@pytest.mark.parametrize("marker", MARKERS)
def test_the_merge_base_is_the_one_the_commits_own_parents_give(
    tmp_path: Path, marker: str
) -> None:
    s = _scenario(tmp_path)
    assert merge_base(s.run.repo, s.run.run_branch, s.second) == s.start
    # Shallow: C1 has no parent, so R and C2 share none. Otherwise R is a child of C1.
    _cut(s, marker)
    assert merge_base(s.run.repo, s.run.run_branch, s.second) == s.start
    assert s.merger.review_base(s.second) == s.start
    assert "out.txt" in s.merger.artefact_diff(s.second)


@pytest.mark.parametrize("marker", MARKERS)
def test_the_write_scope_check_sees_what_the_attempt_left_outside_its_module(
    tmp_path: Path, marker: str
) -> None:
    s = _scenario(tmp_path)
    before = s.checker.check("m2", s.second, "role")
    assert before.refused_by == "write_scope"
    assert before.subject == "out.txt"
    _cut(s, marker)
    after = s.checker.check("m2", s.second, "role")
    assert (after.refused_by, after.reason, after.subject) == (
        before.refused_by,
        before.reason,
        before.subject,
    )


# ── the merge ──────────────────────────────────────────────────────────────────


@pytest.mark.parametrize("marker", MARKERS)
def test_the_merge_merges_from_the_base_the_commits_own_parents_give(
    tmp_path: Path, marker: str
) -> None:
    s = _scenario(tmp_path)
    _cut(s, marker)
    merged = s.merger.merge("m2", 2, s.second, "merge m2")
    repo = s.run.repo
    # The commit's own parents, read by plain git with no marker in the way.
    _mark_none(s)
    assert _git(repo, "rev-list", "--parents", "-n", "1", merged).split()[1:] == [
        s.run_head,
        s.second,
    ]
    # Merged from S: m1's change, m2's last change, and the file m2 left outside its module.
    assert _git(repo, "show", f"{merged}:out.txt") == "outside the module"
    assert _git(repo, "show", f"{merged}:m2/b.txt") == "2"
    assert _git(repo, "show", f"{merged}:m1/a.txt") == "1"


def _mark_none(s: Scenario) -> None:
    for marker in (s.common / "shallow", s.common / "info" / "grafts"):
        marker.unlink(missing_ok=True)
    (s.common / "objects" / "info" / "commit-graph").unlink(missing_ok=True)


# ── a merge already made ───────────────────────────────────────────────────────


@pytest.mark.parametrize("marker", MARKERS)
def test_a_merge_already_made_is_found_and_not_made_again(tmp_path: Path, marker: str) -> None:
    s = _scenario(tmp_path)
    merged = s.merger.merge("m2", 2, s.second, "merge m2")
    # The merge seen with one parent only (shallow: none), so it no longer looks like a merge.
    _mark(s, marker, merged, [s.run_head])
    assert _seen_parents(s, merged) == ([] if marker == "shallow" else [s.run_head])
    assert merges_of(s.run.repo, s.run.run_branch, s.start).get(s.second) == merged
    assert s.merger.merge("m2", 2, s.second, "merge m2") == merged
    assert head_of(s.run.repo, s.run.run_branch) == merged
    assert s.merger.run_branch_moved(s.run_head, s.second) is None
