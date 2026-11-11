"""On 2.1.322 a review is held to the catalog, flags, managed tier and policy limits of its run.

A review session on 2.1.322 carries the same traffic a role session does, so it is held to the
same conditions: the catalog and flags the run first saw, the policy limits the decomposition
call received, and no managed settings delivered or changed under it. Every invocation of the
review's session counts, a resume to repair a verdict included. A review that saw another
state is not taken: what it spent is recorded, then the incident, then one halt, as a role
session's change is. A review that saw the same is recorded with what each invocation saw.

Reviews on the earlier pins carry nothing of this, and nothing about them changes.
"""

from __future__ import annotations

from pathlib import Path

import pytest
from loop_fakes import FakeDispatcher, Rig, plan, usage

from physgate.orchestrator.events import (
    Halted,
    Incident,
    Merged,
    ReviewRan,
    ReviewUnavailable,
    TokensUsed,
    read_events,
)
from physgate.orchestrator.exceptions import ReviewUnavailableError
from physgate.orchestrator.managed import ObservedTraffic, SessionManaged
from physgate.orchestrator.protocols import MessageUsage, ReviewResult
from physgate.orchestrator.record import DecompositionSummary

SEEN = ObservedTraffic(
    served_catalog="off", served_catalog_reason="not_first_party", feature_flags="not reported off"
)
SERVED = SEEN.model_copy(
    update={"served_catalog": "not reported off", "served_catalog_reason": None}
)
SAME = SessionManaged(observed_traffic=SEEN, managed_drift=None, policy_limits_sha256=None)
CATALOG = SAME.model_copy(update={"observed_traffic": SERVED})
FLAGS = SAME.model_copy(
    update={"observed_traffic": SEEN.model_copy(update={"feature_flags": "off"})}
)
POLICY = SAME.model_copy(update={"policy_limits_sha256": "b" * 64})
DRIFT = SAME.model_copy(
    update={"managed_drift": "remote managed settings were delivered into the session"}
)


def _start(rig: Rig) -> None:
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


def _result(rig: Rig, *managed: SessionManaged) -> ReviewResult:
    return ReviewResult(
        verdict="pass",
        finding="the change is sound",
        reviewer_model=rig.reviewer.model,
        session_id="rev-1",
        usage=(MessageUsage(message_id="r1", usage=usage(7)),),
        managed=managed,
    )


def _run(rig: Rig) -> str:
    _start(rig)
    loop = rig.open()
    kind = loop.run().kind
    loop.close()
    return kind


def test_a_review_that_saw_what_the_run_began_with_is_taken_and_records_it(
    tmp_path: Path,
) -> None:
    rig = Rig(tmp_path, dispatcher=FakeDispatcher(traffic={1: SEEN}))
    rig.reviewer.results[1] = _result(rig, SAME, SAME)
    assert _run(rig) == "done"
    events = read_events(tmp_path / "events.jsonl")
    (ran,) = [e for e in events if isinstance(e, ReviewRan)]
    assert ran.result.managed == (SAME, SAME)
    assert not any(isinstance(e, Incident) for e in events)
    assert any(isinstance(e, Merged) for e in events)


@pytest.mark.parametrize(
    ("seen", "named"),
    [
        ((CATALOG,), "catalog"),
        ((FLAGS,), "flags"),
        ((POLICY,), "policy limits"),
        ((DRIFT,), "remote managed settings"),
        ((SAME, CATALOG), "catalog"),  # the resume to repair the verdict saw another state
    ],
    ids=["catalog", "flags", "policy", "managed", "at-the-repair-resume"],
)
def test_a_review_that_saw_another_state_halts_the_run_and_its_verdict_is_not_taken(
    tmp_path: Path, seen: tuple[SessionManaged, ...], named: str
) -> None:
    rig = Rig(tmp_path, dispatcher=FakeDispatcher(traffic={1: SEEN}))
    rig.reviewer.results[1] = _result(rig, *seen)
    assert _run(rig) == "halted"
    events = read_events(tmp_path / "events.jsonl")
    (incident,) = [e for e in events if isinstance(e, Incident)]
    assert incident.cause == "managed_settings_changed" and incident.subtask_id == "s1"
    assert named in incident.detail and "rev-1" in incident.detail
    assert any(isinstance(e, Halted) for e in events)
    assert not any(isinstance(e, (ReviewRan, Merged)) for e in events)
    # What the review spent is still the reviewer's.
    assert [e.attribution for e in events if isinstance(e, TokensUsed)][-1] == "reviewer:rev-1"


def test_a_review_with_no_verdict_that_saw_another_state_halts_and_is_never_retried(
    tmp_path: Path,
) -> None:
    rig = Rig(tmp_path, dispatcher=FakeDispatcher(traffic={1: SEEN}))
    rig.reviewer.unavailable[1] = ReviewUnavailableError(
        "the session ended with api_error",
        cause="infrastructure",
        session_id="rev-1",
        reviewer_model=rig.reviewer.model,
        managed=(CATALOG,),
    )
    assert _run(rig) == "halted"
    events = read_events(tmp_path / "events.jsonl")
    (incident,) = [e for e in events if isinstance(e, Incident)]
    assert incident.cause == "managed_settings_changed" and "rev-1" in incident.detail
    assert len(rig.reviewer.seen) == 1  # the infrastructure retry never ran
    assert not any(isinstance(e, ReviewUnavailable) and e.retry for e in events)


def test_a_review_with_no_verdict_that_saw_the_same_records_what_it_saw(
    tmp_path: Path,
) -> None:
    rig = Rig(tmp_path, dispatcher=FakeDispatcher(traffic={1: SEEN}))
    rig.reviewer.unavailable[1] = ReviewUnavailableError(
        "a required file was not read in full",
        cause="reading_incomplete",
        session_id="rev-1",
        reviewer_model=rig.reviewer.model,
        managed=(SAME,),
    )
    _run(rig)
    events = read_events(tmp_path / "events.jsonl")
    (unavailable,) = [e for e in events if isinstance(e, ReviewUnavailable)]
    assert unavailable.managed == (SAME,)
    assert not any(isinstance(e, Incident) for e in events)


def test_a_review_on_an_earlier_pin_is_recorded_as_it_was(tmp_path: Path) -> None:
    rig = Rig(tmp_path)
    rig.reviewer.results[1] = _result(rig)
    assert _run(rig) == "done"
    text = (tmp_path / "events.jsonl").read_text()
    assert '"review_ran"' in text and '"managed"' not in text


#: An invocation whose stop was not confirmed: its log was never read.
UNREAD = SAME.model_copy(update={"observed_traffic": None})


def test_on_the_new_pin_a_review_whose_catalog_and_flags_went_unread_halts_the_run(
    tmp_path: Path,
) -> None:
    rig = Rig(
        tmp_path,
        dispatcher=FakeDispatcher(traffic={1: SEEN}),
        config_overrides={"claude_version": "2.1.322"},
    )
    rig.reviewer.results[1] = _result(rig, UNREAD)
    assert _run(rig) == "halted"
    events = read_events(tmp_path / "events.jsonl")
    (incident,) = [e for e in events if isinstance(e, Incident)]
    assert incident.cause == "managed_settings_changed" and "not read" in incident.detail
    assert not any(isinstance(e, (ReviewRan, Merged)) for e in events)
