"""A review is read from beneath a root whose path names nothing about what is measured.

The injected-error instrument refuses to show a reviewer any path holding a word
that gives the evaluation away, the harness's own name among them. The standing
root is therefore checked when it is given, and a review's directory beneath it
is named by a generated id alone.
"""

from __future__ import annotations

import subprocess
from pathlib import Path

import pytest

from physgate.evaluation.inject.corpus import telltales
from physgate.reviewers.exceptions import ReviewRootError
from physgate.reviewers.places import (
    STANDING_ROOT_NAME,
    require_review_root,
    review_dir,
    standing_root,
)

INSTRUMENT_ID = "r0123456789ab"
SESSION_ID = "5f0c1d2e-3a4b-4c5d-8e9f-0a1b2c3d4e5f"


# A macOS and a Linux home, and the home of whichever machine runs the test.
@pytest.mark.parametrize("home", ["/Users/someone", "/home/coder", str(Path.home())])
@pytest.mark.parametrize("review", [INSTRUMENT_ID, SESSION_ID])
@pytest.mark.parametrize("leaf", ["read/worktree", "read/transcript.md", "session/stdout.jsonl"])
def test_the_standing_root_names_nothing_on_either_machine(
    home: str, review: str, leaf: str
) -> None:
    path = review_dir(standing_root(Path(home)), review) / leaf
    assert telltales(str(path)) == []


def test_the_old_scratch_root_would_name_the_harness() -> None:
    # The collision the standing root exists to avoid, kept as a control.
    assert telltales("/home/coder/physgate-scratch/r/review/r0123456789ab/worktree") == ["physgate"]
    assert STANDING_ROOT_NAME == "review-scratch"


@pytest.mark.parametrize("name", ["physgate-scratch", "reviewer-scratch", "corpus-runs"])
def test_a_root_that_names_what_is_measured_is_refused(tmp_path: Path, name: str) -> None:
    with pytest.raises(ReviewRootError, match="holds a word"):
        require_review_root(tmp_path / name)


def test_a_root_inside_a_git_checkout_is_refused(tmp_path: Path) -> None:
    repo = tmp_path / "repo"
    repo.mkdir()
    subprocess.run(["git", "init", "-q", str(repo)], check=True)
    with pytest.raises(ReviewRootError, match="inside a git checkout"):
        require_review_root(repo / "deep" / STANDING_ROOT_NAME)


def test_a_clean_root_outside_any_checkout_is_returned_resolved(tmp_path: Path) -> None:
    root = tmp_path / "x" / ".." / STANDING_ROOT_NAME
    assert require_review_root(root) == (tmp_path / STANDING_ROOT_NAME).resolve()


@pytest.mark.parametrize("review", [INSTRUMENT_ID, SESSION_ID])
def test_a_review_is_named_by_a_generated_id(tmp_path: Path, review: str) -> None:
    assert review_dir(tmp_path, review) == tmp_path / review


@pytest.mark.parametrize("review", ["run-1", "control-8f3ac4", "../r0123456789ab", "R0123456789AB"])
def test_a_chosen_name_is_refused(tmp_path: Path, review: str) -> None:
    with pytest.raises(ReviewRootError, match="generated id"):
        review_dir(tmp_path, review)
