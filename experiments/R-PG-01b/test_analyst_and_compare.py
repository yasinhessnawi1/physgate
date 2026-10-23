"""Tests of check_analyst.py and compare_r_pg_01.py (§8) on invented repositories and numbers.

Run explicitly, in the run checkout: ``uv run --frozen pytest -q experiments/R-PG-01b``.
No R-PG-01 result is read: R-PG-01's figures here are invented.
"""

from __future__ import annotations

import os
import subprocess
import sys
from collections.abc import Callable
from pathlib import Path

import pytest

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
import check_analyst as A  # noqa: E402
import common as C  # noqa: E402
import compare_r_pg_01 as M  # noqa: E402
import contrast as K  # noqa: E402

ENV = {
    **os.environ,
    "GIT_AUTHOR_NAME": "t",
    "GIT_AUTHOR_EMAIL": "t@e.invalid",
    "GIT_COMMITTER_NAME": "t",
    "GIT_COMMITTER_EMAIL": "t@e.invalid",
}


def git(repo: Path, *args: str) -> str:
    return subprocess.run(
        ["git", "-C", str(repo), *args], capture_output=True, text=True, check=True, env=ENV
    ).stdout.strip()


def origin(tmp: Path, files: dict[str, str]) -> Path:
    repo = tmp / "origin"
    repo.mkdir()
    git(repo, "init", "-q", "-b", "main")
    for rel, body in files.items():
        (repo / rel).parent.mkdir(parents=True, exist_ok=True)
        (repo / rel).write_text(body)
    git(repo, "add", "-A")
    git(repo, "commit", "-q", "-m", "run")
    git(repo, "tag", C.RUN_TAG)
    git(repo, "branch", "other")
    return repo


def clone(tmp: Path, repo: Path) -> Path:
    out = tmp / "analysis"
    subprocess.run(
        [
            "git",
            "clone",
            "-q",
            "--single-branch",
            "--no-tags",
            "--branch",
            C.RUN_TAG,
            str(repo),
            str(out),
        ],
        check=True,
        capture_output=True,
        env=ENV,
    )
    return out


FILES = {"experiments/R-PG-01b/CRITERIA.md": "c\n", ".docs/02-architecture-specification.md": "a\n"}


def test_the_frozen_clone_command_gives_a_clone_that_passes(tmp_path: Path) -> None:
    out = clone(tmp_path, origin(tmp_path, FILES))
    found = A.check(out, out)
    assert found["holds"], found
    assert A.check(out, tmp_path)["working_directory_is_the_clone"] is False


@pytest.mark.parametrize(
    "extra",
    ["experiments/R-PG-01/RESULT.md", "experiments/R-PG-02/CRITERIA.md", "RESULTS.md"],
)
def test_an_excluded_path_in_the_commit_fails(tmp_path: Path, extra: str) -> None:
    out = clone(tmp_path, origin(tmp_path, {**FILES, extra: "x\n"}))
    found = A.check(out, out)
    assert found["excluded_in_the_commit"] == 1 and not found["holds"]


@pytest.mark.parametrize(
    "extra", ["experiments/R-PG-02/notes.md", "RESULTS_TECHNICAL.md", "private/notes.md"]
)
def test_any_file_the_commit_does_not_track_fails(tmp_path: Path, extra: str) -> None:
    out = clone(tmp_path, origin(tmp_path, FILES))
    (out / extra).parent.mkdir(parents=True, exist_ok=True)
    (out / extra).write_text("x\n")
    found = A.check(out, out)
    assert found["untracked_files_on_disk"] == 1 and not found["holds"]
    (out / extra).unlink()
    (out / ".venv" / "lib").mkdir(parents=True)
    (out / ".venv" / "lib" / "x.py").write_text("x\n")
    assert A.check(out, out)["holds"]


def test_another_branch_or_tag_fails(tmp_path: Path) -> None:
    out = clone(tmp_path, origin(tmp_path, FILES))
    git(out, "branch", "exp/elsewhere")
    assert A.check(out, out)["other_branches_or_tags"] == 1


# ---- compare_r_pg_01.py ----


def pushed(tmp: Path, output: str, cite: bool) -> tuple[Path, str]:
    remote = tmp / "remote.git"
    subprocess.run(["git", "init", "-q", "--bare", str(remote)], check=True, env=ENV)
    work = tmp / "work"
    work.mkdir()
    git(work, "init", "-q", "-b", "main")
    git(work, "remote", "add", "origin", str(remote))
    out = work / "experiments/R-PG-01b/tally.json"
    out.parent.mkdir(parents=True)
    out.write_text(output)
    digest = C.sha256_bytes(output.encode())
    (work / M.RESULT).write_text(f"tally sha256 {digest if cite else '0' * 64}\n")
    git(work, "add", "-A")
    git(work, "commit", "-q", "-m", "numbers final")
    return work, digest


def test_compare_refuses_before_the_numbers_are_pushed(tmp_path: Path) -> None:
    work, _ = pushed(tmp_path, "{}\n", cite=True)
    with pytest.raises(M.Refused, match="not pushed"):
        M.numbers_final(work, "origin/exp/r-pg-01b-numbers", "experiments/R-PG-01b/tally.json")


def test_compare_reads_the_pushed_output_held_to_result_s_digest(tmp_path: Path) -> None:
    work, digest = pushed(tmp_path, '{"R": 2}\n', cite=True)
    git(work, "push", "-q", "origin", "HEAD:refs/heads/exp/r-pg-01b-numbers")
    found = M.numbers_final(work, "origin/exp/r-pg-01b-numbers", "experiments/R-PG-01b/tally.json")
    assert found["sha256"] == digest and found["output"] == {"R": 2}


def test_compare_refuses_an_output_result_does_not_cite(tmp_path: Path) -> None:
    work, _ = pushed(tmp_path, '{"R": 2}\n', cite=False)
    git(work, "push", "-q", "origin", "HEAD:refs/heads/exp/r-pg-01b-numbers")
    with pytest.raises(M.Refused, match="digest"):
        M.numbers_final(work, "origin/exp/r-pg-01b-numbers", "experiments/R-PG-01b/tally.json")


def test_replication_needs_the_interval_at_or_below_zero_and_no_systematic_shift() -> None:
    arts = [f"a{n}" for n in range(20)]
    prior = {a: int(n < 10) for n, a in enumerate(arts)}
    same = [dict(prior), dict(prior)]
    found = M.replication(prior, same, K.draws(20, 200))
    assert found["replicated"] and found["D_cross"] == 0 and found["D_same"] == 0
    shifted = [{a: 0 for a in arts}, {a: 0 for a in arts}]
    found = M.replication(prior, shifted, K.draws(20, 200))
    assert not found["replicated"] and found["named"] == "drift or protocol differences"
    one = M.replication(prior, [dict(prior)], K.draws(20, 200))
    assert one["replicated"] and one["label"] == "without a noise floor"


S: Callable[..., tuple[int, str]] = M.d1_sentence
D = {"A": "-2 (-4, 0)", "C": "-1 (-3, 1)"}


@pytest.mark.parametrize(
    ("prior", "i", "f", "agree", "row"),
    [
        (True, True, True, False, 1),
        (True, True, True, True, 2),
        (True, False, True, True, 3),
        (True, True, False, True, 4),
        (True, False, False, True, 5),
    ],
)
def test_d1_s_sentence_is_the_first_row_that_holds(
    prior: bool, i: bool, f: bool, agree: bool, row: int
) -> None:
    assert S(prior, i, f, agree, D, "the C leg")[0] == row


def test_the_legs_are_read_on_each_threshold() -> None:
    assert M.legs(5, 3, 12, 12) == "the A leg"
    assert M.legs(5, 5, 12, 8) == "the C leg"
    assert M.legs(5, 3, 12, 8) == "both"
