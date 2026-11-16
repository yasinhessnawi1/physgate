"""A review's compaction line reaches the run's log as its own usage line, marked, counted once.

The reviewer adds the usage of its session's compaction calls to its account as one line marked
as a compaction (the binary counts that call in its totals and in no message). The loop records
every line of a review's account as a token line attributed to the reviewer, so the compaction
line is on the log with its mark, beside the session's messages without one, and the run's
account counts it once: on a verdict, and on a review that is no verdict.
"""

from __future__ import annotations

from pathlib import Path

from loop_fakes import FakeReviewer, Rig, plan

from physgate.orchestrator.accounting import TokenAccount
from physgate.orchestrator.events import TokensUsed, read_events
from physgate.orchestrator.exceptions import ReviewUnavailableError
from physgate.orchestrator.protocols import MessageUsage, ReviewResult, Usage


def _usage(i: int, o: int) -> Usage:
    return Usage(
        input_tokens=i, output_tokens=o, cache_read_input_tokens=0, cache_creation_input_tokens=0
    )


SPENT = (
    MessageUsage(message_id="m-1", usage=_usage(5, 9)),
    MessageUsage(message_id="compaction-1", usage=_usage(70_001, 301), compaction=True),
)


def _lines(tmp_path: Path) -> list[TokensUsed]:
    events = read_events(tmp_path / "events.jsonl")
    return [e for e in events if isinstance(e, TokensUsed) and e.attribution == "reviewer:rev-1"]


def _run(tmp_path: Path, reviewer: FakeReviewer) -> None:
    rig = Rig(tmp_path, reviewer=reviewer)
    loop = rig.open()
    loop.start(plan("s1"))
    loop.run()
    loop.close()


def _held(tmp_path: Path) -> None:
    lines = _lines(tmp_path)
    assert [(e.message_id, e.compaction) for e in lines] == [
        ("m-1", False),
        ("compaction-1", True),
    ]
    reviewer = TokenAccount.from_events(lines).by_attribution()["reviewer:rev-1"]
    assert (reviewer.input_tokens, reviewer.output_tokens) == (70_006, 310)
    # The mark is written only on the compaction's line (and on the review's own copy of it).
    text = (tmp_path / "events.jsonl").read_text()
    marked = [line for line in text.splitlines() if '"compaction":true' in line]
    assert sum('"kind":"tokens_used"' in line for line in marked) == 1
    assert '"compaction":false' not in text


def test_a_verdict_s_compaction_line_is_on_the_log_marked(tmp_path: Path) -> None:
    result = ReviewResult(
        verdict="pass",
        finding="the change is sound",
        reviewer_model="claude-opus-5-5",
        session_id="rev-1",
        usage=SPENT,
        compactions=1,
    )
    _run(tmp_path, FakeReviewer(results={1: result}))
    _held(tmp_path)


def test_a_review_that_is_no_verdict_keeps_its_compaction_line_marked(tmp_path: Path) -> None:
    unavailable = ReviewUnavailableError(
        "the review outgrew the model's context window (after 1 compaction)",
        cause="context_exceeded",
        session_id="rev-1",
        reviewer_model="claude-opus-5-5",
        usage=SPENT,
        compactions=1,
    )
    _run(tmp_path, FakeReviewer(unavailable={1: unavailable}))
    _held(tmp_path)
