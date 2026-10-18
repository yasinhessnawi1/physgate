"""An infrastructure failure is retried after each delay of the run's schedule, waited out.

One outage used to cost a review its only retry, taken at once while the outage still
held. The retry now waits each delay of ``infra_retry_delays_s`` first, one retry per
delay, and every try is written with the delay before it, in the review's own record.
The reviewer is a stand-in that answers from a script; nothing is called, and the wait
is a recorded fake.
"""

from __future__ import annotations

import json
from pathlib import Path

from instrument_corpus import write_corpus
from test_every_artefact_gets_its_row_whatever_its_review_came_to import ScriptedReviewer

from physgate.evaluation.inject.corpus import load_corpus
from physgate.evaluation.inject.runner import (
    CONFIG_NAME,
    RESULTS_NAME,
    REVIEWS_DIRNAME,
    run_instrument,
)
from physgate.orchestrator.events import ReviewUnavailable, read_events


def _run(tmp_path: Path, script: list[str | None], delays: tuple[float, ...]) -> list[float]:
    waited: list[float] = []
    run_instrument(
        load_corpus(write_corpus(tmp_path / "corpus")),
        {"electrical": ScriptedReviewer(script)},  # type: ignore[dict-item]
        run_dir=tmp_path / "run",
        scratch=tmp_path / "scratch",
        run_id="retry-1",
        seed=11,
        retry_delays_s=delays,
        sleep=waited.append,
        progress=lambda line: None,
    )
    return waited


def _rows(tmp_path: Path) -> list[dict[str, object]]:
    text = (tmp_path / "run" / RESULTS_NAME).read_text()
    return sorted((json.loads(x) for x in text.splitlines()), key=lambda r: int(r["review_seq"]))


def test_each_retry_waits_its_own_delay_and_a_verdict_after_the_third_counts(
    tmp_path: Path,
) -> None:
    script = ["infrastructure", "infrastructure", "infrastructure", None, None]
    waited = _run(tmp_path, script, (60.0, 900.0, 2700.0))
    assert waited == [60.0, 900.0, 2700.0]
    first, second = _rows(tmp_path)
    assert first["reviewer_verdict"] == "pass" and second["reviewer_verdict"] == "pass"
    record = json.loads(
        (tmp_path / "run" / REVIEWS_DIRNAME / f"{first['review_id']}.json").read_text()
    )
    assert record["tries"] == [
        {"cause": "infrastructure", "delay_before_s": 0.0},
        {"cause": "infrastructure", "delay_before_s": 60.0},
        {"cause": "infrastructure", "delay_before_s": 900.0},
        {"cause": None, "delay_before_s": 2700.0},
    ]


def test_the_schedule_spent_leaves_the_review_unavailable_and_the_run_goes_on(
    tmp_path: Path,
) -> None:
    script = ["infrastructure", "infrastructure", "infrastructure", None]
    waited = _run(tmp_path, script, (60.0, 900.0))
    assert waited == [60.0, 900.0]
    first, second = _rows(tmp_path)
    assert (first["reviewer_verdict"], first["review_cause"]) == (
        "review_unavailable",
        "infrastructure",
    )
    assert second["reviewer_verdict"] == "pass"
    lines = [
        e
        for e in read_events(tmp_path / "run" / "events.jsonl")
        if isinstance(e, ReviewUnavailable)
    ]
    assert [e.retry for e in lines] == [True, True, False]


def test_a_cause_other_than_infrastructure_is_never_retried_or_waited_for(tmp_path: Path) -> None:
    waited = _run(tmp_path, ["no_verdict", None], (60.0, 900.0, 2700.0))
    assert waited == []


def test_the_schedule_is_recorded_with_the_run(tmp_path: Path) -> None:
    _run(tmp_path, [None, None], (60.0, 900.0, 2700.0))
    config = json.loads((tmp_path / "run" / CONFIG_NAME).read_text())
    assert config["retry_delays_s"] == [60.0, 900.0, 2700.0]
    assert config["lanes"] == 1 and config["per_class"] == 10
