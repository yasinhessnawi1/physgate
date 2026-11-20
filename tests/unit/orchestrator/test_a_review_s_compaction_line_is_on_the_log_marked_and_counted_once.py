"""A review's compaction line reaches the run's log as its own usage line, marked, counted once.

The reviewer adds the usage of its session's compaction calls to its account as one line marked
as a compaction (the binary counts that call in its totals and in no message). The loop records
every line of a review's account as a token line attributed to the reviewer, so the compaction
line is on the log with its mark, beside the session's messages without one, and the run's
account counts it once: on a verdict, on a review that is no verdict, on a review that showed
held-out material, and on a verdict held because the review ran under other conditions than its
run began with.
"""

from __future__ import annotations

from pathlib import Path

from loop_fakes import FakeDispatcher, FakeReviewer, Rig, plan

from physgate.orchestrator.accounting import TokenAccount
from physgate.orchestrator.events import Incident, TokensUsed, read_events
from physgate.orchestrator.exceptions import HeldOutExposedError, ReviewUnavailableError
from physgate.orchestrator.managed import ObservedTraffic, SessionManaged
from physgate.orchestrator.protocols import MessageUsage, ReviewResult, Usage
from physgate.orchestrator.record import DecompositionSummary


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


def test_a_review_that_showed_held_out_material_keeps_its_compaction_line_marked(
    tmp_path: Path,
) -> None:
    exposure = HeldOutExposedError(
        "held-out material in the stream of review session rev-1",
        session_id="rev-1",
        reviewer_model="claude-opus-5-5",
        usage=SPENT,
    )
    _run(tmp_path, FakeReviewer(unavailable={1: exposure}))  # type: ignore[dict-item]
    (incident,) = [e for e in read_events(tmp_path / "events.jsonl") if isinstance(e, Incident)]
    assert incident.cause == "held_out_read"
    _held(tmp_path)


#: What the run began with, and a review that saw a served catalog under it.
SEEN = ObservedTraffic(
    served_catalog="off", served_catalog_reason="not_first_party", feature_flags="not reported off"
)
SAME = SessionManaged(observed_traffic=SEEN, managed_drift=None, policy_limits_sha256=None)
SERVED = SAME.model_copy(
    update={
        "observed_traffic": SEEN.model_copy(
            update={"served_catalog": "not reported off", "served_catalog_reason": None}
        )
    }
)


def test_a_verdict_held_for_other_conditions_keeps_its_compaction_line_marked(
    tmp_path: Path,
) -> None:
    result = ReviewResult(
        verdict="pass",
        finding="the change is sound",
        reviewer_model="claude-opus-5-5",
        session_id="rev-1",
        usage=SPENT,
        compactions=1,
        managed=(SERVED,),
    )
    rig = Rig(
        tmp_path,
        reviewer=FakeReviewer(results={1: result}),
        dispatcher=FakeDispatcher(traffic={1: SEEN}),
    )
    loop = rig.open()
    loop.record.start(
        plan("s1"),
        decomposed=DecompositionSummary(
            session_id="d1",
            model="claude-sonnet-5",
            num_turns=1,
            subtasks=1,
            interface_nodes=("iface.bus",),
            spec_commit="a" * 40,
            head_revision=1,
            observed_traffic=SEEN,
        ),
    )
    loop.close()
    loop = rig.open()
    assert loop.run().kind == "halted"
    loop.close()
    (incident,) = [e for e in read_events(tmp_path / "events.jsonl") if isinstance(e, Incident)]
    assert incident.cause == "managed_settings_changed"
    _held(tmp_path)
