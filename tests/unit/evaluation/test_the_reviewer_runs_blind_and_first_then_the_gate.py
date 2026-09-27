"""The instrument reviews every artefact blind and first, then gates each, and writes one row each.

If a reviewer could see a gate result, whether a reviewer had passed an
artefact would measure the gate telling the reviewer the answer. So a stub
reviewer asserts, at the moment it judges, that nothing it was handed carries a
gate field or a corpus answer, that its worktree lies outside the corpus and the
run, and that the run holds no gate line yet. Afterwards every gate event on the
artefact carries that stub's verdict as ``reviewer_had_passed``, and the catch
count over the run's log is what the results file's rows add up to.

The instrument also refuses to start without a reviewer for every artefact, or
with one on the corpus author's model, and runs the same way twice.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from instrument_corpus import (
    AUTHOR,
    MAGNITUDE_ARTEFACT,
    SOURCE,
    SeededFakeReviewer,
    coin,
    write_corpus,
)

from physgate.evaluation.inject.corpus import Corpus, load_corpus, strings_of, telltales
from physgate.evaluation.inject.exceptions import (
    BlindnessError,
    ReviewerRefusedError,
    RunDirectoryError,
)
from physgate.evaluation.inject.materialise import ANSWER_FIELDS
from physgate.evaluation.inject.runner import (
    CONFIG_NAME,
    RESULTS_NAME,
    ResultRow,
    check_base,
    review_id,
    run_instrument,
)
from physgate.orchestrator.catches import catches
from physgate.orchestrator.events import GateRan, ReviewRan, SubtaskPlanned, read_events
from physgate.orchestrator.exceptions import ModelSeparationError
from physgate.orchestrator.gate_events import gate_events
from physgate.orchestrator.protocols import Artefact

SEED = 11
#: A seed for the fake's coin that passes one of the two artefacts and fails the other.
FAKE_SEED = 1


@pytest.fixture
def corpus(tmp_path: Path) -> Corpus:
    return load_corpus(write_corpus(tmp_path / "corpus"))


def _run(corpus: Corpus, root: Path, reviewer: SeededFakeReviewer) -> tuple[ResultRow, ...]:
    return run_instrument(
        corpus,
        {"electrical": reviewer},
        run_dir=root / "run",
        scratch=root / "scratch",
        run_id="dry-1",
        seed=SEED,
    )


def test_what_is_shown_holds_no_gate_result_nor_anything_telling_and_is_judged_first(
    corpus: Corpus, tmp_path: Path
) -> None:
    run_dir = tmp_path / "out" / "run"
    checked: list[str] = []

    def blind(artefact: Artefact) -> None:
        worktree = Path(artefact.worktree)
        for place in (corpus.root, run_dir):
            assert place.resolve() not in worktree.resolve().parents
        shown = [Path(artefact.trajectory), *(p for p in worktree.rglob("*") if p.is_file())]
        shown = [p for p in shown if ".git" not in p.parts]
        for path in shown:
            text = path.read_text()
            assert not telltales(text), path
            assert not [f for f in ANSWER_FIELDS if f'"{f}"' in text], path
            for artefact_of_corpus in corpus.artefacts:
                assert artefact_of_corpus.description not in text
                assert f'"{artefact_of_corpus.id}"' not in text
                assert artefact_of_corpus.error_class + " error" not in text
        assert not set(json.loads(artefact.model_dump_json())) & {"gate", "result", "verdict"}
        assert not [s for s in strings_of(json.loads(artefact.model_dump_json())) if telltales(s)]
        for path in (run_dir / "events.jsonl", run_dir / "controls" / "events.jsonl"):
            log = [json.loads(line) for line in path.read_text().splitlines()]
            assert not [e for e in log if e["kind"] in ("gate_ran", "integration_gate_ran")]
        assert not (run_dir / RESULTS_NAME).exists()
        assert [p.name for p in (worktree.parent.parent).iterdir()] == [artefact.subtask_id]
        checked.append(artefact.subtask_id)

    reviewer = SeededFakeReviewer(seed=FAKE_SEED, before_verdict=blind)
    rows = _run(corpus, tmp_path / "out", reviewer)
    assert sorted(checked) == sorted(r.review_id for r in rows) and len(checked) == 2
    assert list((tmp_path / "out" / "scratch" / "review").iterdir()) == []

    log = read_events(run_dir / "events.jsonl")
    reviews = [e for e in log if isinstance(e, ReviewRan)]
    gates = [e for e in log if isinstance(e, GateRan)]
    assert max(r.seq for r in reviews) < min(g.seq for g in gates)
    events = gate_events(log)
    assert events
    for event in events:
        assert event.reviewer_basis == "same_attempt"
        assert event.reviewer_had_passed is coin(FAKE_SEED, event.subtask_id)


def test_each_row_is_one_artefact_and_the_catch_count_is_what_the_rows_add_up_to(
    corpus: Corpus, tmp_path: Path
) -> None:
    rows = _run(corpus, tmp_path / "out", SeededFakeReviewer(seed=FAKE_SEED))
    assert [(r.artefact, r.error_class, r.expected_check) for r in rows] == [
        ("m1", "magnitude", "magnitude"),
        ("p1", "propagation", "propagation"),
    ]
    assert [(r.gate_verdict, r.gate_blocking) for r in rows] == [
        ("fail", ("magnitude",)),
        ("fail", ("propagation",)),
    ]
    assert [(r.control_verdict, r.control_blocking) for r in rows] == [("pass", ()), ("pass", ())]
    assert {r.reviewer_verdict for r in rows} == {"pass", "fail"}  # both stamping paths ran
    assert all(r.reviewer_model == "claude-opus-5-5" and r.reviewer_tokens == 0 for r in rows)
    on_disk = [
        ResultRow.model_validate_json(line)
        for line in (tmp_path / "out" / "run" / RESULTS_NAME).read_text().splitlines()
    ]
    assert tuple(on_disk) == rows

    counted = {
        row.name: row
        for row in catches(gate_events(read_events(tmp_path / "out" / "run" / "events.jsonl")))
    }
    for name in ("magnitude", "propagation", "all"):
        caught = [r for r in rows if name == "all" or name in r.gate_blocking]
        assert counted[name].artefacts_caught == len(caught)
        assert counted[name].caught_after_reviewer_passed == sum(
            r.reviewer_verdict == "pass" for r in caught
        )
    controls = catches(
        gate_events(read_events(tmp_path / "out" / "run" / "controls" / "events.jsonl"))
    )
    assert [c.artefacts_caught for c in controls if c.name == "all"] == [0]


def test_the_clean_twins_are_reviewed_only_when_asked_and_blind_and_first(
    corpus: Corpus, tmp_path: Path
) -> None:
    off = SeededFakeReviewer(seed=FAKE_SEED)
    rows = _run(corpus, tmp_path / "off", off)
    assert [r.control_reviewer_verdict for r in rows] == [None, None]
    assert sorted(a.subtask_id for a in off.seen) == sorted(r.review_id for r in rows)
    config = json.loads((tmp_path / "off" / "run" / CONFIG_NAME).read_text())
    assert config["review_clean_twins"] is False

    seen: list[str] = []
    reviewer = SeededFakeReviewer(
        seed=FAKE_SEED, before_verdict=lambda a: seen.append(a.subtask_id)
    )
    rows = run_instrument(
        corpus,
        {"electrical": reviewer},
        run_dir=tmp_path / "on" / "run",
        scratch=tmp_path / "on" / "scratch",
        run_id="dry-1",
        seed=SEED,
        review_clean_twins=True,
    )
    twins = {r.control_id for r in rows}
    assert sorted(seen) == seen and set(seen) == twins | {r.review_id for r in rows}
    assert not twins & {r.review_id for r in rows}
    for row in rows:
        assert row.control_reviewer_verdict == (
            "pass" if coin(FAKE_SEED, row.control_id) else "fail"
        )
    controls = read_events(tmp_path / "on" / "run" / "controls" / "events.jsonl")
    reviews = [e for e in controls if isinstance(e, ReviewRan)]
    gates = [e for e in controls if isinstance(e, GateRan)]
    assert {e.subtask_id for e in reviews} == twins
    assert max(r.seq for r in reviews) < min(g.seq for g in gates)
    main = read_events(tmp_path / "on" / "run" / "events.jsonl")
    assert not twins & {e.subtask_id for e in main if isinstance(e, ReviewRan)}
    for event in gate_events(controls):
        assert event.reviewer_had_passed is coin(FAKE_SEED, event.subtask_id)
    assert json.loads((tmp_path / "on" / "run" / CONFIG_NAME).read_text())["review_clean_twins"]


def test_the_log_names_no_artefact_id_and_no_class_order(corpus: Corpus, tmp_path: Path) -> None:
    seed = 3  # a seed under which the run's order is not the corpus's
    assert review_id(seed, "m1") > review_id(seed, "p1")
    run_instrument(
        corpus,
        {"electrical": SeededFakeReviewer()},
        run_dir=tmp_path / "run",
        scratch=tmp_path / "s",
        run_id="x",
        seed=seed,
    )
    log = read_events(tmp_path / "run" / "events.jsonl")
    for kind in (SubtaskPlanned, ReviewRan, GateRan):
        subtasks = [e.subtask_id for e in log if isinstance(e, kind)]
        assert subtasks == [review_id(seed, "p1"), review_id(seed, "m1")]


def test_the_same_input_and_seed_give_the_same_results_file(corpus: Corpus, tmp_path: Path) -> None:
    _run(corpus, tmp_path / "one", SeededFakeReviewer())
    _run(corpus, tmp_path / "two", SeededFakeReviewer())
    one, two = (tmp_path / d / "run" / RESULTS_NAME for d in ("one", "two"))
    assert one.read_bytes() == two.read_bytes()
    config = json.loads((tmp_path / "one" / "run" / CONFIG_NAME).read_text())
    assert config["corpus_manifest_sha256"] == corpus.manifest_sha256
    assert config["author_model"] == AUTHOR and config["seed"] == SEED
    assert config["reviewer_models"] == {"electrical": "claude-opus-5-5"}


def test_no_reviewer_for_a_role_and_nothing_is_written(corpus: Corpus, tmp_path: Path) -> None:
    with pytest.raises(ReviewerRefusedError) as caught:
        run_instrument(
            corpus, {}, run_dir=tmp_path / "run", scratch=tmp_path / "s", run_id="x", seed=1
        )
    assert caught.value.context == {"role": "electrical"}
    assert not (tmp_path / "run").exists() and not (tmp_path / "s").exists()


def test_a_reviewer_on_the_author_s_model_is_refused_before_anything(
    corpus: Corpus, tmp_path: Path
) -> None:
    with pytest.raises(ModelSeparationError):
        _run(corpus, tmp_path / "out", SeededFakeReviewer(model=AUTHOR))
    assert not (tmp_path / "out").exists()


def test_a_review_that_reports_the_author_s_model_stops_the_run(
    corpus: Corpus, tmp_path: Path
) -> None:
    with pytest.raises(ModelSeparationError):
        _run(corpus, tmp_path / "out", SeededFakeReviewer(reports_model=AUTHOR))
    assert not (tmp_path / "out" / "run" / RESULTS_NAME).exists()


@pytest.mark.parametrize(
    ("run_dir", "scratch", "reason"),
    [
        ("run", "run/scratch", "scratch in run"),
        ("scratch/run", "scratch", "run in scratch"),
        ("corpus/run", "s", "run in corpus"),
        ("run", "corpus/s", "scratch in corpus"),
        ("@outside", ".", "corpus in scratch"),
    ],
)
def test_the_run_the_scratch_and_the_corpus_are_kept_apart(
    corpus: Corpus, tmp_path: Path, run_dir: str, scratch: str, reason: str
) -> None:
    outside = tmp_path.parent / f"{tmp_path.name}-run"
    with pytest.raises(RunDirectoryError) as caught:
        run_instrument(
            corpus,
            {"electrical": SeededFakeReviewer()},
            run_dir=outside if run_dir == "@outside" else tmp_path / run_dir,
            scratch=tmp_path / scratch,
            run_id="x",
            seed=1,
        )
    assert caught.value.context.get("inside") == reason


def test_a_used_run_directory_is_refused(corpus: Corpus, tmp_path: Path) -> None:
    (tmp_path / "run").mkdir()
    (tmp_path / "run" / "events.jsonl").write_text("")
    with pytest.raises(RunDirectoryError, match="new or empty"):
        run_instrument(
            corpus,
            {"electrical": SeededFakeReviewer()},
            run_dir=tmp_path / "run",
            scratch=tmp_path / "s",
            run_id="x",
            seed=1,
        )


def test_an_artefact_whose_description_the_design_spells_out_is_never_shown(tmp_path: Path) -> None:
    telling = {**MAGNITUDE_ARTEFACT, "description": SOURCE}  # every node's source says it
    corpus = load_corpus(write_corpus(tmp_path / "corpus", artefacts=(telling,)))
    reviewer = SeededFakeReviewer()
    with pytest.raises(BlindnessError):
        _run(corpus, tmp_path / "out", reviewer)
    assert reviewer.seen == []


def test_a_scratch_path_that_names_an_answer_is_never_shown(corpus: Corpus, tmp_path: Path) -> None:
    reviewer = SeededFakeReviewer()
    with pytest.raises(BlindnessError, match="paths"):
        run_instrument(
            corpus,
            {"electrical": reviewer},
            run_dir=tmp_path / "run",
            scratch=tmp_path / "injected-errors",
            run_id="x",
            seed=1,
        )
    assert reviewer.seen == []


def test_the_base_alone_is_gated_as_one_change_over_nothing(corpus: Corpus, tmp_path: Path) -> None:
    result = check_base(corpus.base, tmp_path / "base")
    assert result.verdict == "pass"
    assert {r.scope for r in result.checks} == {"subtask", "module", "system"}
