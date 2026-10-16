"""The diff a reviewer reads is the one the commits hold, read through one verified directory.

A commit graph (``objects/info/commit-graph``) stores each commit's root tree as well as its
parents, and git takes the tree from it, in every object directory it reaches through
alternates, the packet's clean store included. A graph that names another tree would show the
reviewer a different change from the one the scope check saw and the merge merges. The packet
reads with the commit graph off, as every harness git does.

The packet verifies the attempt's repository once per sequence of reads, and every read takes
the common directory that check confirmed, never ``commondir`` again.

Inert markers only: the graph is written by git and one tree id in it is replaced by another
commit's tree id, which changes nothing but what git shows; the decoy is an empty repository.
"""

from __future__ import annotations

import os
import struct
import subprocess
from pathlib import Path

import pytest

from physgate.orchestrator.git import GitDir, verified_git_dir
from physgate.reviewers import packet

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


def _git(cwd: Path, *args: str) -> str:
    return subprocess.run(
        ["git", "-c", "commit.gpgsign=false", *args],
        cwd=cwd,
        env=_ENV,
        capture_output=True,
        text=True,
        check=True,
    ).stdout


def _two_commits(tmp_path: Path) -> tuple[Path, str, str]:
    repo = tmp_path / "repo"
    repo.mkdir()
    _git(repo, "init", "-q", "-b", "main")
    (repo / "a.txt").write_text("one\n")
    _git(repo, "add", "-A")
    _git(repo, "commit", "-q", "-m", "one")
    first = _git(repo, "rev-parse", "HEAD").strip()
    (repo / "a.txt").write_text("two\n")
    _git(repo, "commit", "-q", "-am", "two")
    return repo, first, _git(repo, "rev-parse", "HEAD").strip()


def _forge_tree(repo: Path, commit: str, tree_of: str) -> None:
    """Write the commit graph, then give ``commit`` the root tree of ``tree_of`` in it.

    Only the tree id in the commit's data row is rewritten; the file's checksum is left, as git
    does not check it when it reads the graph.
    """
    _git(repo, "commit-graph", "write", "--reachable")
    path = repo / ".git" / "objects" / "info" / "commit-graph"
    data = bytearray(path.read_bytes())
    assert data[:4] == b"CGPH"
    chunks = {
        bytes(data[8 + 12 * i : 12 + 12 * i]): struct.unpack(">Q", data[12 + 12 * i : 20 + 12 * i])[
            0
        ]
        for i in range(data[6] + 1)
    }
    oids, cdat, width = chunks[b"OIDL"], chunks[b"CDAT"], 20 + 16
    count = (cdat - oids) // 20
    order = [bytes(data[oids + i * 20 : oids + (i + 1) * 20]).hex() for i in range(count)]
    tree = bytes.fromhex(_git(repo, "rev-parse", f"{tree_of}^{{tree}}").strip())
    at = cdat + order.index(commit) * width
    data[at : at + 20] = tree
    path.chmod(0o644)
    path.write_bytes(bytes(data))


def test_a_forged_commit_graph_does_not_change_the_reviewer_s_diff(tmp_path: Path) -> None:
    repo, first, second = _two_commits(tmp_path)
    honest = packet._diff(repo, first, second)
    assert b"-one\n+two\n" in honest
    _forge_tree(repo, second, first)
    # The control: git that reads the graph now sees no change at all.
    assert _git(repo, "diff", first, second) == ""
    assert packet._diff(repo, first, second) == honest


def test_the_packet_verifies_once_per_sequence_of_reads(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    repo, first, second = _two_commits(tmp_path)
    linked = tmp_path / "linked"
    _git(repo, "worktree", "add", "-q", "--detach", str(linked))
    checks: list[Path] = []

    def counting(cwd: Path, *, linked: bool, common: Path | None = None) -> GitDir:
        checks.append(Path(cwd))
        return verified_git_dir(cwd, linked=linked, common=common)

    monkeypatch.setattr(packet, "verified_git_dir", counting)
    where = packet._git_dir(linked)
    assert checks == [linked]
    # ``commondir`` rewritten after the check: the reads take the directory the check confirmed.
    decoy = tmp_path / "decoy"
    _git(tmp_path, "init", "-q", "--bare", "--object-format=sha256", str(decoy))
    admin = Path((linked / ".git").read_text().removeprefix("gitdir:").strip())
    (admin / "commondir").write_text(f"{decoy}\n")
    assert b"+two\n" in packet._diff(where, first, second)
    out = tmp_path / "export"
    packet._export(where, second, out)
    assert (out / "a.txt").read_text() == "two\n"
    assert checks == [linked]
