"""A review that ends on the account's usage limit judges nothing, and is given the same hits again.

The earlier attempt's hits are judged only by a review that ran and answered them. A review cut
by the usage limit emits no review line, so the earlier attempt stays unjudged: the run waits for
the reset, and the review that follows the resume is shown the earlier attempt's streams and hits
once more, and judges them.
"""

from __future__ import annotations

from datetime import datetime, timedelta
from pathlib import Path

from loop_fakes import FakeReviewer, plan
from test_a_usage_limit_is_its_own_cause_and_the_run_waits_for_its_reset import (
    NOON,
    _limited_review,
    clock,  # noqa: F401 - the fixture that sets the rig's clock
)
from test_an_earlier_hit_is_judged_only_by_a_confirmed_or_dismissed_answer_naming_its_attempt import (  # noqa: E501
    answer,
)
from test_an_unreviewed_attempt_s_scan_hits_go_to_the_next_review import (
    _layer,
    _review_judged,
    _rig,
    hit,
    result,
)

from physgate.orchestrator.events import Halted, ReviewRan, read_events


def test_a_review_cut_by_the_usage_limit_judges_no_earlier_hit_and_is_shown_them_again(
    tmp_path: Path,
    clock: list[datetime],  # noqa: F811
) -> None:
    reviewer = FakeReviewer(
        unavailable={1: _limited_review()},
        results={2: result("pass", 2, answer(hit("sess-1"), 1), answer(hit("sess-2")))},
    )
    rig = _rig(tmp_path, reviewer=reviewer, delays=(60.0,))
    loop = rig.open()
    loop.start(plan("s1"))
    _layer(loop)
    assert loop.run().kind == "halted"
    loop.close()
    events = list(read_events(tmp_path / "events.jsonl"))
    assert [e.reason for e in events if isinstance(e, Halted)] == ["usage_limit"]
    assert [e for e in events if isinstance(e, ReviewRan)] == [], "the cut review judged nothing"
    assert [u.attempt for u in reviewer.seen[0].unjudged] == [1]

    clock[0] = NOON + timedelta(hours=8)
    loop = rig.open()
    _layer(loop)
    loop.resume()
    loop.close()
    assert len(reviewer.seen) == 2
    assert [u.attempt for u in reviewer.seen[1].unjudged] == [1], "shown again at the next review"
    assert _review_judged(tmp_path) == [(2, (1,))]
