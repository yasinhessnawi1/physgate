"""Every artefact gets its row, whatever its review came to; no non-verdict counts as one.

A review that fails for infrastructure is retried once. One that still gives no
verdict, or gives none for another reason, is recorded in the log as unavailable
and in its row as ``review_unavailable`` with its cause; a blocking defect of the
issued specification is recorded as ``blocked``. The run goes on to the next
artefact and to the gate, and the command's exit status and summary give the
counts. The reviewer here is a stand-in that answers from a script; nothing is
called.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path

import pytest
from instrument_corpus import REVIEWER, SeededFakeReviewer, write_corpus

from physgate.evaluation.inject.corpus import load_corpus
from physgate.evaluation.inject.runner import RESULTS_NAME, run_instrument
from physgate.orchestrator.events import (
    GateRan,
    ReviewRan,
    ReviewUnavailable,
    RunStarted,
    read_events,
)
from physgate.orchestrator.exceptions import ReviewUnavailableError
from physgate.orchestrator.gate_events import gate_events
from physgate.orchestrator.protocols import Artefact, MessageUsage, ReviewResult, Usage

SEED = 11


def _usage(n: int) -> tuple[MessageUsage, ...]:
    usage = Usage(
        input_tokens=n, output_tokens=0, cache_read_input_tokens=0, cache_creation_input_tokens=0
    )
    return (MessageUsage(message_id=f"m{n}", usage=usage),)


@dataclass
class ScriptedReviewer:
    """Answers each review from a script of causes, in order; ``None`` is a pass."""

    script: list[str | None]
    model: str = REVIEWER
    seen: list[Artefact] = field(default_factory=list)

    def review(self, artefact: Artefact) -> ReviewResult:
        self.seen.append(artefact)
        cause = self.script.pop(0)
        if cause is not None:
            raise ReviewUnavailableError(
                f"scripted {cause}",
                cause=cause,  # type: ignore[arg-type]
                session_id=f"s{len(self.seen)}",
                reviewer_model=self.model,
                usage=_usage(10),
            )
        return ReviewResult(
            verdict="pass",
            finding="every item is met",
            reviewer_model=self.model,
            session_id=f"s{len(self.seen)}",
            usage=_usage(5),
        )


def _run(tmp_path: Path, reviewer: object) -> tuple[list[dict[str, object]], list[object]]:
    corpus = load_corpus(write_corpus(tmp_path / "corpus"))
    run_instrument(
        corpus,
        {"electrical": reviewer},  # type: ignore[dict-item]
        run_dir=tmp_path / "run",
        scratch=tmp_path / "scratch",
        run_id="rows-1",
        seed=SEED,
    )
    rows = [json.loads(x) for x in (tmp_path / "run" / RESULTS_NAME).read_text().splitlines()]
    return rows, list(read_events(tmp_path / "run" / "events.jsonl"))


def _by_seq(rows: list[dict[str, object]]) -> list[dict[str, object]]:
    return sorted(rows, key=lambda r: int(str(r["review_seq"])))


def test_an_infrastructure_failure_is_retried_once_and_its_tokens_are_counted(
    tmp_path: Path,
) -> None:
    reviewer = ScriptedReviewer(["infrastructure", None, None])
    rows, events = _run(tmp_path, reviewer)
    first, second = _by_seq(rows)
    assert (first["reviewer_verdict"], first["review_cause"]) == ("pass", None)
    assert first["reviewer_tokens"] == 15  # the failed try's 10 and the verdict's 5
    retried = [e for e in events if isinstance(e, ReviewUnavailable)]
    assert len(retried) == 1 and retried[0].retry
    assert second["reviewer_verdict"] == "pass"


@pytest.mark.parametrize(
    ("script", "outcome", "cause"),
    [
        (["infrastructure", "infrastructure", None], "review_unavailable", "infrastructure"),
        (["no_verdict", None], "review_unavailable", "no_verdict"),
        (["compacted", None], "review_unavailable", "compacted"),
        (["blocking_spec_defect", None], "blocked", "blocking_spec_defect"),
    ],
    ids=["infrastructure-twice", "no-verdict", "compacted", "blocked"],
)
def test_a_review_with_no_verdict_is_a_row_of_its_own_and_the_run_goes_on(
    tmp_path: Path, script: list[str | None], outcome: str, cause: str
) -> None:
    rows, events = _run(tmp_path, ScriptedReviewer(script))
    assert len(rows) == 2  # every artefact has its row
    first, second = _by_seq(rows)
    assert (first["reviewer_verdict"], first["review_cause"]) == (outcome, cause)
    assert first["reviewer_model"] == REVIEWER
    assert second["reviewer_verdict"] == "pass"
    # The gate still judged both, after every review.
    gates = [e for e in events if isinstance(e, GateRan)]
    assert len(gates) == 2
    reviews = [e for e in events if isinstance(e, ReviewRan | ReviewUnavailable)]
    assert max(e.seq for e in reviews) < min(g.seq for g in gates)
    final = [e for e in events if isinstance(e, ReviewUnavailable) and not e.retry]
    assert len(final) == 1 and final[0].cause == cause


def test_a_review_with_no_verdict_stamps_no_reviewer_verdict_on_its_gate_events(
    tmp_path: Path,
) -> None:
    """The catch count reads a non-verdict as neither a pass nor a fail: no stamp at all."""
    rows, events = _run(tmp_path, ScriptedReviewer(["no_verdict", None]))
    (started,) = [e for e in events if isinstance(e, RunStarted)]
    stamped = gate_events(events, started.config_sha256)  # type: ignore[arg-type]
    unavailable = next(r for r in rows if r["reviewer_verdict"] == "review_unavailable")
    reviewed = next(r for r in rows if r["reviewer_verdict"] == "pass")
    unseen = {e.reviewer_had_passed for e in stamped if e.subtask_id == unavailable["review_id"]}
    seen = {e.reviewer_had_passed for e in stamped if e.subtask_id == reviewed["review_id"]}
    assert unseen == {None} and seen == {True}


def test_the_command_says_how_many_came_to_each_and_exits_1_if_any_came_to_neither(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    import physgate.evaluation.inject.cli as inject_cli
    from physgate.cli import main
    from physgate.orchestrator.cli import Registrations

    monkeypatch.setattr(inject_cli, "require_complete", lambda corpus: None)
    corpus = write_corpus(tmp_path / "corpus")
    argv = [
        "inject",
        *("--corpus", str(corpus), "--run-dir", str(tmp_path / "run")),
        *("--scratch", str(tmp_path / "scratch"), "--run-id", "rows-2", "--seed", str(SEED)),
    ]
    reviewer = ScriptedReviewer(["no_verdict", None])
    assert main(argv, Registrations(reviewers={"electrical": reviewer})) == 1
    printed = json.loads(capsys.readouterr().out)
    assert printed["reviews"] == {"pass": 1, "fail": 0, "blocked": 0, "review_unavailable": 1}
    argv[argv.index("rows-2")] = "rows-3"
    argv[argv.index(str(tmp_path / "run"))] = str(tmp_path / "run2")
    argv[argv.index(str(tmp_path / "scratch"))] = str(tmp_path / "scratch2")
    assert main(argv, Registrations(reviewers={"electrical": SeededFakeReviewer()})) == 0
