"""``physgate inject`` starts only with a reviewer for every role, on a complete corpus.

As shipped, the reviewer is the real one, built from a parameters file and an
installation: without them the command refuses to start and nothing is written,
and so it does with an incomplete parameters file. With no reviewer at all it
names the role. With a reviewer, a corpus that is not the measurement's (fewer
than ten of each class) is refused too.
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


def test_with_no_reviewer_registered_the_command_refuses_to_start(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    assert main(_argv(tmp_path), Registrations()) == 2
    error = json.loads(capsys.readouterr().err)
    assert error["role"] == "electrical" and "no reviewer" in error["error"]
    assert not (tmp_path / "run").exists() and not (tmp_path / "s").exists()


def test_as_shipped_the_real_reviewer_needs_its_parameters_and_installation(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    assert main(_argv(tmp_path)) == 2
    error = json.loads(capsys.readouterr().err)
    assert error["needs"] == "--params and --install"
    assert not (tmp_path / "run").exists() and not (tmp_path / "s").exists()


def test_an_incomplete_parameters_file_is_refused_before_anything_is_built(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    params = tmp_path / "params.json"
    params.write_text(json.dumps({"auth": "api_key", "reviewers": {"electrical": "m"}}))
    argv = [*_argv(tmp_path), "--params", str(params), "--install", str(tmp_path / "i")]
    assert main(argv) == 2
    error = json.loads(capsys.readouterr().err)
    assert "complete set of reviewer parameters" in error["error"]
    assert not (tmp_path / "i").exists() and not (tmp_path / "run").exists()


def test_with_a_reviewer_an_incomplete_corpus_is_refused(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    registered = Registrations(reviewers={"electrical": SeededFakeReviewer()})
    assert main(_argv(tmp_path), registered) == 2
    error = json.loads(capsys.readouterr().err)
    assert "10 artefacts of each class" in error["error"]
    assert (error["magnitude"], error["propagation"]) == ("1", "1")
    assert not (tmp_path / "run").exists()


@pytest.mark.parametrize(("flag", "expected"), [([], False), (["--review-clean-twins"], True)])
def test_the_clean_twin_switch_reaches_the_run_and_is_off_unless_given(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, flag: list[str], expected: bool
) -> None:
    import physgate.evaluation.inject.cli as inject_cli

    asked: list[bool] = []
    monkeypatch.setattr(inject_cli, "require_complete", lambda corpus: None)

    def stand_in(*_: object, **given: object) -> tuple[()]:
        asked.append(bool(given["review_clean_twins"]))
        return ()

    monkeypatch.setattr(inject_cli, "run_instrument", stand_in)
    registered = Registrations(reviewers={"electrical": SeededFakeReviewer()})
    assert main([*_argv(tmp_path), *flag], registered) == 0
    assert asked == [expected]
