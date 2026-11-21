"""A reader held for its producer, and its producer's earlier attempt's unjudged hits, apart.

The producer's attempt 1 is refused before review and its stream carries a marker; its attempts
2 and 3 fail review and it goes to a person. While it waits, the subtask that reads from it stays
held (the dependent wait), and an independent subtask still runs. Neither rule touches the other:
the reader is never dispatched, and each review of the producer is given attempt 1's hit again,
as no review judged it.
"""

from __future__ import annotations

from pathlib import Path

import pytest
from test_a_choice_on_a_failed_contract_reopens_the_other_module import of, requests_of
from test_a_failed_contract_is_ruled_by_clause_and_goes_to_a_person_as_one_item import lines
from test_a_pairs_contract_is_tested_once_both_its_modules_merged_and_blocks_nothing import (
    BUDGET,
    DRIVE,
    FW,
)
from test_a_subtask_waits_while_a_subtask_it_reads_from_waits_on_a_person import (
    _sizing_registered,  # noqa: F401 - the autouse fixture
    first_run,
    rigged,
)
from test_an_unreviewed_attempt_s_scan_hits_go_to_the_next_review import (
    LONG_LINE,
    SkippingDispatcher,
)


def test_a_held_reader_stays_held_and_the_producer_s_earlier_hits_are_shown_at_each_review(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    rig = rigged(tmp_path)
    rig.dispatcher = SkippingDispatcher(trajectories=tmp_path / "run" / "sessions")
    rig.changes.refuse.update({1: LONG_LINE})
    rig.reviewer.verdicts[:] = ["fail", "fail"]
    assert first_run(rig, monkeypatch, budget=True) == "wait"
    rows = lines(rig)
    # The reader is held for its producer and never dispatched; the independent one ran.
    (held,) = of(rows, "dispatch_held")
    assert (held["subtask_id"], held["producer"]) == (FW, DRIVE)
    assert requests_of(rig, FW) == []
    assert [r.attempt for r in requests_of(rig, BUDGET)] == [1]
    # The producer's reviews were each given attempt 1's streams, which no review judged.
    drive = [a for a in rig.reviewer.seen if a.subtask_id == DRIVE]
    assert [[u.attempt for u in a.unjudged] for a in drive] == [[1], [1]]
