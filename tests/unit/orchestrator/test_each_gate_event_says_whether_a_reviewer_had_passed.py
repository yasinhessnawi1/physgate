"""Every gate event says whether the paired reviewer had passed the artefact it judged.

The headline quantity is the count of physical errors the gate caught that a
reviewer had approved (ARCH-083). The gate cannot know, since it runs first, so
the field is filled when the events are derived from the log. These tests build
logs by hand with known verdicts and check, case by case, that each event names
the review of its own artefact: the loop's order, a resumed attempt that was
gated and reviewed twice, the injected-error instrument's blind order, and the
integration call, stamped from the review of the attempt that last wrote the
record's node.
"""

from __future__ import annotations

import pytest
from pydantic import ValidationError
from synthetic_ledger import Log, record

from physgate.orchestrator.gate_events import GateEvent, gate_events
from physgate.orchestrator.protocols import CheckRecord, Verdict


def stamps(log: Log) -> list[tuple[bool | None, str | None, int | None]]:
    return [(e.reviewer_had_passed, e.reviewer_basis, e.review_seq) for e in gate_events(log.lines)]


# --- one attempt, the loop's order: gate, then review -----------------------------------------


@pytest.mark.parametrize(("verdict", "stamped"), [("pass", True), ("fail", False)])
def test_a_gate_line_takes_the_verdict_of_the_review_that_follows_it(
    verdict: Verdict, stamped: bool
) -> None:
    log = Log()
    log.session("s1", 1)
    log.gate("s1", 1)
    review = log.review("s1", 1, verdict)
    assert stamps(log) == [(stamped, "same_attempt", review.seq)]


def test_an_attempt_the_gate_refused_and_no_reviewer_saw_is_none() -> None:
    log = Log()
    log.session("s1", 1)
    log.gate("s1", 1)
    log.session("s1", 2)
    log.gate("s1", 2, fails=False)
    review = log.review("s1", 2, "pass")
    assert stamps(log) == [(None, None, None), (True, "same_attempt", review.seq)]


def test_a_review_of_another_attempt_or_subtask_is_never_taken() -> None:
    log = Log()
    log.session("s1", 1)
    log.gate("s1", 1)
    log.review("s2", 1, "pass")
    log.review("s1", 2, "pass")
    assert stamps(log) == [(None, None, None)]


def test_a_resumed_attempt_gated_and_reviewed_twice_pairs_each_gate_with_its_own_review() -> None:
    """A resume re-gates and re-reviews the same artefact; the verdicts may differ."""
    log = Log()
    log.session("s1", 1)
    log.gate("s1", 1)
    first = log.review("s1", 1, "fail")
    log.resumed("s1", 1)
    log.gate("s1", 1)
    second = log.review("s1", 1, "pass")
    assert stamps(log) == [
        (False, "same_attempt", first.seq),
        (True, "same_attempt", second.seq),
    ]


def test_a_gate_line_left_unreviewed_by_a_kill_does_not_borrow_the_review_before_the_resume() -> (
    None
):
    log = Log()
    log.session("s1", 1)
    log.gate("s1", 1)
    first = log.review("s1", 1, "pass")
    log.resumed("s1", 1)
    log.gate("s1", 1)  # killed before its review
    log.resumed("s1", 1)
    log.gate("s1", 1)
    third = log.review("s1", 1, "fail")
    assert stamps(log) == [
        (True, "same_attempt", first.seq),
        (None, None, None),
        (False, "same_attempt", third.seq),
    ]


# --- the instrument's order: the reviewer first, blind, then the gate ---------------------------


def test_a_review_written_before_the_gate_line_is_its_artefact_s_review() -> None:
    log = Log()
    blind = log.review("artefact-01", 1, "pass")
    log.gate("artefact-01", 1)
    other = log.review("artefact-02", 1, "fail")
    log.gate("artefact-02", 1)
    assert stamps(log) == [(True, "same_attempt", blind.seq), (False, "same_attempt", other.seq)]


def test_a_review_after_a_new_session_is_not_the_earlier_artefact_s() -> None:
    log = Log()
    log.review("s1", 1, "pass")
    log.session("s1", 1)
    log.gate("s1", 1)
    assert stamps(log) == [(None, None, None)]


# --- the integration call: the review of the attempt that last wrote the node ---------------------


def test_an_integration_failure_is_stamped_from_the_review_that_approved_the_last_write() -> None:
    log = Log()
    log.session("s1", 1)
    log.gate("s1", 1, fails=False)
    approved = log.review("s1", 1, "pass")
    log.wrote("s1", 1, "motor.left", 3)
    log.session("s2", 1)
    log.gate("s2", 1, fails=False)
    log.review("s2", 1, "pass")
    log.wrote("s2", 1, "power.budget", 4)
    log.integration(record("fail", "motor.left", "propagation"))
    (event,) = [e for e in gate_events(log.lines) if e.subtask_id == "integration"]
    assert (event.reviewer_had_passed, event.reviewer_basis, event.review_seq) == (
        True,
        "last_writer_of_node",
        approved.seq,
    )
    assert (event.reviewed_subtask, event.reviewed_attempt) == ("s1", 1)


def test_a_node_written_twice_is_stamped_from_the_later_writer() -> None:
    log = Log()
    log.review("s1", 1, "pass")
    log.wrote("s1", 1, "motor.left", 3)
    later = log.review("s2", 1, "pass")
    log.wrote("s2", 1, "motor.left", 4)
    log.integration(record("fail", "motor.left", "propagation"))
    (event,) = gate_events(log.lines)
    assert (event.review_seq, event.reviewed_subtask) == (later.seq, "s2")


@pytest.mark.parametrize(
    "records",
    [(record("pass", None),), (record("fail", "iface.power_bus", "propagation"),)],
    ids=["a record that names no node", "a node only the given design wrote"],
)
def test_an_integration_record_with_no_writer_has_no_verdict(
    records: tuple[CheckRecord, ...],
) -> None:
    log = Log()
    log.review("s1", 1, "pass")
    log.wrote("s1", 1, "motor.left", 3)
    log.integration(*records)
    assert stamps(log) == [(None, None, None)]


# --- the event's shape ------------------------------------------------------------------


def test_a_verdict_without_its_review_or_a_review_without_its_verdict_is_refused() -> None:
    log = Log()
    log.gate("s1", 1)
    log.review("s1", 1, "pass")
    (event,) = gate_events(log.lines)
    fields = event.model_dump()
    for broken in (
        {"reviewer_had_passed": None},
        {"review_seq": None},
        {"reviewer_basis": None},
        {"reviewed_attempt": None},
    ):
        with pytest.raises(ValidationError, match="names its review"):
            GateEvent.model_validate({**fields, **broken})
