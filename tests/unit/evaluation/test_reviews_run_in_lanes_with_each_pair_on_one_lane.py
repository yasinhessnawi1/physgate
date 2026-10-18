"""Reviews run in lanes drawn before the run: an artefact and its twin always share one.

Each lane works under a review root of its own, takes its own items in id order, and
writes each finished review on its own with its lane and wall-clock times. The lanes are
dealt by class so they hold the classes evenly; the draw is the seed's alone. The
progress line gives counts only. After a run of infrastructure failures across the
lanes, no lane starts a session for the pause. The reviewers are stand-ins; nothing is
called, and the waits are recorded fakes.
"""

from __future__ import annotations

import json
import threading
from collections import Counter
from dataclasses import dataclass, field
from pathlib import Path

from instrument_corpus import REVIEWER, SeededFakeReviewer, write_corpus
from test_every_artefact_gets_its_row_whatever_its_review_came_to import ScriptedReviewer

from physgate.evaluation.inject.corpus import load_corpus
from physgate.evaluation.inject.runner import (
    LANES_NAME,
    PAUSES_NAME,
    RESULTS_NAME,
    REVIEWS_DIRNAME,
    assign_lanes,
    control_id,
    review_id,
    run_instrument,
)
from physgate.orchestrator.protocols import Artefact, ReviewResult


@dataclass
class _Fake:
    """Any artefact, any class: only ``id`` and ``error_class`` are read by the draw."""

    id: str
    error_class: str


def test_the_lane_draw_balances_the_classes_and_depends_on_the_seed_alone() -> None:
    fakes = [
        _Fake(f"a{i:02d}", c)
        for i, c in enumerate(["unit", "magnitude", "equilibrium", "propagation"] * 5)
    ]
    drawn = assign_lanes(11, fakes, 4)  # type: ignore[arg-type]
    assert drawn == assign_lanes(11, fakes, 4)  # type: ignore[arg-type]
    per_lane = Counter(drawn.values())
    assert sorted(per_lane.values()) == [5, 5, 5, 5]
    for error_class in ("unit", "magnitude", "equilibrium", "propagation"):
        lanes = Counter(drawn[f.id] for f in fakes if f.error_class == error_class)
        assert max(lanes.values()) - min(lanes.values(), default=0) <= 1
    assert any(assign_lanes(s, fakes, 4) != drawn for s in range(1, 6))  # type: ignore[arg-type]


@dataclass
class _Recording:
    """A fake that notes which review root each review was given, then passes it."""

    model: str = REVIEWER
    roots: dict[str, str] = field(default_factory=dict)
    lock: threading.Lock = field(default_factory=threading.Lock)

    def review(self, artefact: Artefact) -> ReviewResult:
        with self.lock:
            self.roots[artefact.subtask_id] = artefact.worktree
        return SeededFakeReviewer(seed=3).review(artefact)


def test_a_run_in_two_lanes_reviews_each_pair_on_its_one_lane_under_that_lane_s_root(
    tmp_path: Path,
) -> None:
    corpus = load_corpus(write_corpus(tmp_path / "corpus"))
    lanes = [{"electrical": _Recording()}, {"electrical": _Recording()}]
    lines: list[str] = []
    run_instrument(
        corpus,
        lanes[0],
        run_dir=tmp_path / "run",
        scratch=tmp_path / "scratch",
        run_id="lanes-1",
        seed=11,
        review_clean_twins=True,
        lanes=2,
        lane_reviewers=lanes,
        progress=lines.append,
    )
    drawn = json.loads((tmp_path / "run" / LANES_NAME).read_text())
    assert drawn == assign_lanes(11, corpus.artefacts, 2)
    for artefact in corpus.artefacts:
        lane = drawn[artefact.id]
        for subtask in (review_id(11, artefact.id), control_id(11, artefact.id)):
            record = json.loads(
                (tmp_path / "run" / REVIEWS_DIRNAME / f"{subtask}.json").read_text()
            )
            assert record["lane"] == lane
            assert record["tries"][0]["started_at"] and record["tries"][0]["ended_at"]
            assert f"lane-{lane}" in lanes[lane]["electrical"].roots[subtask]
    assert lines[-1] == "progress: 4/4 reviews done, 0 without a verdict"
    assert all(word not in " ".join(lines) for word in ("pass", "fail", "blocked"))
    rows = [json.loads(x) for x in (tmp_path / "run" / RESULTS_NAME).read_text().splitlines()]
    assert all(r["gate_evaluated"] and r["control_evaluated"] for r in rows)


def test_three_infrastructure_failures_in_a_row_pause_every_lane_for_the_pause(
    tmp_path: Path,
) -> None:
    now = [0.0]
    slept: list[float] = []

    def sleep(seconds: float) -> None:
        slept.append(seconds)
        now[0] += seconds

    reviewer = ScriptedReviewer(["infrastructure", "infrastructure", "infrastructure", None, None])
    run_instrument(
        load_corpus(write_corpus(tmp_path / "corpus")),
        {"electrical": reviewer},
        run_dir=tmp_path / "run",
        scratch=tmp_path / "scratch",
        run_id="pause-1",
        seed=11,
        retry_delays_s=(60.0, 900.0, 2700.0),
        pause_after_failures=3,
        pause_s=900.0,
        sleep=sleep,
        clock=lambda: now[0],
        progress=lambda line: None,
    )
    # 60 and 900 between the first three tries; then the third retry's own 2700 s,
    # which outlasts the 900 s pause the third failure started, so no further wait.
    assert slept == [60.0, 900.0, 2700.0]
    pauses = (tmp_path / "run" / PAUSES_NAME).read_text().splitlines()
    assert len(pauses) == 1 and json.loads(pauses[0])["pause_s"] == 900.0


def test_the_pause_holds_back_the_next_review_until_it_has_run_out(tmp_path: Path) -> None:
    now = [0.0]
    slept: list[float] = []

    def sleep(seconds: float) -> None:
        slept.append(seconds)
        now[0] += seconds

    # No retries: three failures end three reviews, the third starting the pause; the
    # next review waits it out first.
    reviewer = ScriptedReviewer(["infrastructure", "infrastructure", "infrastructure", None])
    run_instrument(
        load_corpus(write_corpus(tmp_path / "corpus")),
        {"electrical": reviewer},
        run_dir=tmp_path / "run",
        scratch=tmp_path / "scratch",
        run_id="pause-2",
        seed=11,
        review_clean_twins=True,
        retry_delays_s=(),
        pause_after_failures=3,
        pause_s=900.0,
        sleep=sleep,
        clock=lambda: now[0],
        progress=lambda line: None,
    )
    assert slept == [900.0]


def test_a_cause_other_than_infrastructure_breaks_the_run_of_failures(tmp_path: Path) -> None:
    slept: list[float] = []
    reviewer = ScriptedReviewer(
        ["infrastructure", "infrastructure", "no_verdict", "infrastructure"]
    )
    run_instrument(
        load_corpus(write_corpus(tmp_path / "corpus")),
        {"electrical": reviewer},
        run_dir=tmp_path / "run",
        scratch=tmp_path / "scratch",
        run_id="pause-3",
        seed=11,
        review_clean_twins=True,
        retry_delays_s=(),
        pause_after_failures=3,
        pause_s=900.0,
        sleep=slept.append,
        clock=lambda: 0.0,
        progress=lambda line: None,
    )
    assert slept == [] and not (tmp_path / "run" / PAUSES_NAME).exists()
