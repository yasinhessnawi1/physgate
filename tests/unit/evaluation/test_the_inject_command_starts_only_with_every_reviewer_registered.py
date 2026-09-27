"""``physgate inject`` starts only with a reviewer for every role, on a complete corpus.

No reviewer is registered with the command yet, so it refuses to start and
names the role, and nothing is written. With a reviewer, a corpus that is not
the measurement's (fewer than ten of each class) is refused too.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from instrument_corpus import SeededFakeReviewer, write_corpus

from physgate.cli import main
from physgate.orchestrator.cli import Registrations


def _argv(tmp_path: Path) -> list[str]:
    corpus = write_corpus(tmp_path / "c")
    return [
        "inject",
        "--corpus",
        str(corpus),
        "--run-dir",
        str(tmp_path / "run"),
        "--scratch",
        str(tmp_path / "s"),
        "--run-id",
        "x",
        "--seed",
        "1",
    ]


@pytest.mark.parametrize("registrations", [None, Registrations()], ids=["as shipped", "none"])
def test_with_no_reviewer_registered_the_command_refuses_to_start(
    tmp_path: Path, capsys: pytest.CaptureFixture[str], registrations: Registrations | None
) -> None:
    assert main(_argv(tmp_path), registrations) == 2
    error = json.loads(capsys.readouterr().err)
    assert error["role"] == "electrical" and "no reviewer" in error["error"]
    assert not (tmp_path / "run").exists() and not (tmp_path / "s").exists()


def test_with_a_reviewer_an_incomplete_corpus_is_refused(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    registered = Registrations(reviewers={"electrical": SeededFakeReviewer()})
    assert main(_argv(tmp_path), registered) == 2
    error = json.loads(capsys.readouterr().err)
    assert "10 artefacts of each class" in error["error"]
    assert (error["magnitude"], error["propagation"]) == ("1", "1")
    assert not (tmp_path / "run").exists()
