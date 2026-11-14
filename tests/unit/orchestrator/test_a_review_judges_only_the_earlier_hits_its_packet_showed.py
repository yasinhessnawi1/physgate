"""A review judges only the earlier hits its packet showed it.

The packet shows earlier hits only where the attempt under review is a session's own stream,
which the marker scan reads. Where the attempt is a written account, the scan is never run on
it and the packet carries no earlier part and no earlier hit. A review given none cannot have
judged one: an answer of it that names an earlier attempt judges nothing, and the review line
records no earlier hit shown and no attempt judged, so the hit stays for an approve to record
only.
"""

from __future__ import annotations

from pathlib import Path

import pytest
from loop_fakes import FakeReviewer
from test_an_earlier_hit_is_judged_only_by_a_confirmed_or_dismissed_answer_naming_its_attempt import (  # noqa: E501
    answer,
)
from test_an_unreviewed_attempt_s_scan_hits_go_to_the_next_review import (
    _item,
    _marked,
    _review_judged,
    _rig,
    _run,
    hit,
    result,
)

from physgate.orchestrator.events import ReviewRan, read_events
from physgate.reviewers.scan import judged_attempts


def test_an_answer_naming_an_attempt_judges_nothing_when_no_earlier_hit_was_shown() -> None:
    named = answer(hit("sess-1"), 1)
    assert judged_attempts((), [named]) == ()


def test_a_review_of_a_written_account_judges_no_earlier_hit_and_records_none_shown(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    # The packet's scan did not run on this attempt, so it carried none of attempt 1's hits.
    monkeypatch.setattr(
        "physgate.orchestrator.loop.indicator_scan_runs", lambda artefact: False, raising=False
    )
    run_dir = tmp_path / "run"
    reviewer = FakeReviewer(
        results={1: result("blocked", 1, answer(hit("sess-1"), 1), answer(hit("sess-2")))}
    )
    _run(_rig(run_dir, reviewer=reviewer), "s1")
    assert _review_judged(run_dir) == [(2, ())]
    ran = [e for e in read_events(run_dir / "events.jsonl") if isinstance(e, ReviewRan)]
    assert [e.earlier_hits for e in ran] == [()]
    item = _item(run_dir)
    assert item.consequence is not None and item.consequence.why_record_only == "scan_hit"
    assert _marked(item) == [(hit("sess-1"), 1)]
