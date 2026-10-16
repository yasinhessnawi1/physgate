"""``physgate catches`` reads an injected-error instrument run as it reads any run.

The instrument records ``instrument.json`` where a driven run records ``run.json``,
and its log's first line carries that file's digest as the run's manifest id. The
command takes the id from there, held to the log, and prints exactly the rows the
library query prints over the same log: ``catches()`` over ``gate_events()``
stamped with the id on the log's first line. The controls log, in the run's
``controls`` directory, is read the same way, under the same file. All of it runs
on the instrument's own test-fixture corpus with a fake reviewer, never the
measurement's corpus.
"""

from __future__ import annotations

import json
import shutil
from pathlib import Path

import pytest
from instrument_corpus import SeededFakeReviewer, write_corpus

from physgate.evaluation.inject.corpus import digest, load_corpus
from physgate.evaluation.inject.runner import CONFIG_NAME, CONTROLS_DIRNAME, run_instrument
from physgate.orchestrator.catches import catches
from physgate.orchestrator.events import RunStarted, read_events
from physgate.orchestrator.gate_events import gate_events

#: A seed for the fake's coin that passes one of the two artefacts and fails the other.
FAKE_SEED = 1


@pytest.fixture
def run_dir(tmp_path: Path) -> Path:
    """One instrument run over the fixture corpus, with the clean twins reviewed too."""
    corpus = load_corpus(write_corpus(tmp_path / "corpus"))
    run_instrument(
        corpus,
        {"electrical": SeededFakeReviewer(seed=FAKE_SEED)},
        run_dir=tmp_path / "out" / "run",
        scratch=tmp_path / "out" / "scratch",
        run_id="dry-1",
        seed=11,
        review_clean_twins=True,
    )
    return tmp_path / "out" / "run"


def library_query(log_path: Path) -> list[dict[str, object]]:
    """The query the command must agree with: the id on the log's first line, then the count."""
    log = read_events(log_path)
    (started,) = [e for e in log if isinstance(e, RunStarted)]
    rows = catches(gate_events(log, started.config_sha256))
    return [json.loads(r.model_dump_json()) for r in rows]


def command(directory: Path, capsys: pytest.CaptureFixture[str]) -> tuple[int, list[str], str]:
    from physgate.cli import main

    capsys.readouterr()
    code = main(["catches", "--run-dir", str(directory)])
    out, err = capsys.readouterr()
    return code, out.splitlines(), err


def test_the_command_prints_the_library_query_s_rows_for_an_instrument_run(
    run_dir: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    expected = library_query(run_dir / "events.jsonl")
    caught = [r for r in expected if r["name"] == "all"]
    # Both fixture artefacts are caught, one after a passing review: the rows say something.
    assert caught and caught[0]["artefacts_caught"] == 2
    assert caught[0]["caught_after_reviewer_passed"] == 1
    code, lines, err = command(run_dir, capsys)
    assert code == 0, err
    assert [json.loads(line) for line in lines] == expected


def test_the_controls_log_is_read_under_the_run_s_own_configuration(
    run_dir: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    expected = library_query(run_dir / CONTROLS_DIRNAME / "events.jsonl")
    assert expected, "the controls log ran the gate on every clean twin"
    assert [r["artefacts_caught"] for r in expected if r["name"] == "all"] == [0]
    code, lines, err = command(run_dir / CONTROLS_DIRNAME, capsys)
    assert code == 0, err
    assert [json.loads(line) for line in lines] == expected


def test_an_instrument_configuration_that_is_not_the_one_the_log_names_is_refused(
    run_dir: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    config = run_dir / CONFIG_NAME
    named = digest(config)
    # Still a valid configuration, but not the bytes the run started under.
    config.write_text(json.dumps(json.loads(config.read_text()), indent=2, sort_keys=True) + "\n")
    assert digest(config) != named
    for directory in (run_dir, run_dir / CONTROLS_DIRNAME):
        code, lines, err = command(directory, capsys)
        assert (code, lines) == (2, [])
        assert json.loads(err)["manifest_id"] == digest(config)


def test_a_file_that_is_not_an_instrument_configuration_is_refused(
    run_dir: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    (run_dir / CONFIG_NAME).write_text('{"run_id": "dry-1"}\n')
    code, lines, err = command(run_dir, capsys)
    assert (code, lines) == (2, [])
    assert "instrument" in json.loads(err)["error"]


def test_a_directory_holding_both_configurations_is_refused(
    run_dir: Path, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    (run_dir / "run.json").write_text("{}\n")
    code, lines, err = command(run_dir, capsys)
    assert (code, lines) == (2, [])
    assert "both" in json.loads(err)["error"]


def test_a_controls_directory_outside_an_instrument_run_is_not_read_as_one(
    run_dir: Path, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    elsewhere = tmp_path / "elsewhere" / CONTROLS_DIRNAME
    shutil.copytree(run_dir / CONTROLS_DIRNAME, elsewhere)
    code, lines, err = command(elsewhere, capsys)
    assert (code, lines) == (2, [])
    assert "no run configuration" in json.loads(err)["error"]
