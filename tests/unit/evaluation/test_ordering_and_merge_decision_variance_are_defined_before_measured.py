"""The two variance numbers, on hand-made sequences whose values are worked out by hand.

The definitions are fixed before any run is measured with them, so these tests
use no run at all: dispatch sequences and attempt ends written out, and the
expected fractions derived in the comments.
"""

from __future__ import annotations

from fractions import Fraction
from typing import Any

import pytest

from physgate.evaluation.observe.variance import (
    Attempt,
    End,
    attempt_ends,
    decision_distance,
    dispatch_order,
    edit_distance,
    merge_decision_variance,
    ordering_distance,
    ordering_variance,
)

A: tuple[Attempt, ...] = (("s1", 1), ("s2", 1))
SWAPPED: tuple[Attempt, ...] = (("s2", 1), ("s1", 1))


@pytest.mark.parametrize(
    ("a", "b", "distance"),
    [
        ("", "", 0),
        ("abc", "abc", 0),
        ("abc", "", 3),
        ("abc", "abd", 1),  # one substitution
        ("abc", "ac", 1),  # one deletion
        ("ab", "ba", 2),  # a swap is two substitutions
        ("kitten", "sitting", 3),
    ],
)
def test_the_edit_distance_counts_each_insertion_deletion_and_substitution_once(
    a: str, b: str, distance: int
) -> None:
    assert edit_distance(a, b) == distance == edit_distance(b, a)


def test_repeats_of_one_ordering_have_no_variance_and_one_run_has_none_at_all() -> None:
    assert ordering_variance([A] * 5) == 0
    assert ordering_variance([A]) is None and ordering_variance([]) is None
    assert ordering_distance((), ()) == 0


def test_one_reordered_run_of_three_gives_two_thirds() -> None:
    # Pairs: (A, A) = 0; (A, swapped) = 2 edits over 2 = 1, twice. Mean: 2/3.
    assert ordering_distance(A, SWAPPED) == 1
    assert ordering_variance([A, A, SWAPPED]) == Fraction(2, 3)


def test_a_run_with_one_attempt_more_is_a_third_of_the_way_from_the_others() -> None:
    longer = (*A, ("s1", 2))
    # One insertion over the longer length 3.
    assert ordering_distance(A, longer) == Fraction(1, 3)
    # Pairs: 0, 1/3, 1/3. Mean: 2/9.
    assert ordering_variance([A, A, longer]) == Fraction(2, 9)


MERGED: dict[Attempt, End] = {("s1", 1): "merged", ("s2", 1): "merged"}


def test_repeats_of_one_set_of_decisions_have_no_variance() -> None:
    assert merge_decision_variance([MERGED] * 5) == 0
    assert merge_decision_variance([MERGED]) is None
    assert decision_distance({}, {}) == 0


def test_one_changed_decision_gives_the_share_of_attempts_that_differ() -> None:
    # s1's first attempt rejected, then merged at its second: of the three attempts
    # either run dispatched, two differ (s1/1 ended otherwise, s1/2 only one ran).
    changed: dict[Attempt, End] = {
        ("s1", 1): "rejected",
        ("s1", 2): "merged",
        ("s2", 1): "merged",
    }
    assert decision_distance(MERGED, changed) == Fraction(2, 3)
    # Pairs: 0, 2/3, 2/3. Mean: 4/9.
    assert merge_decision_variance([MERGED, MERGED, changed]) == Fraction(4, 9)


def spawn(subtask: str, attempt: int) -> dict[str, Any]:
    return {"kind": "stage_entered", "stage": "spawn", "subtask_id": subtask, "attempt": attempt}


def test_the_ordering_is_every_spawn_in_log_order() -> None:
    events: list[dict[str, Any]] = [
        {"kind": "subtask_planned", "subtask_id": "s1"},
        {"kind": "stage_entered", "stage": "resolve", "subtask_id": "s1", "attempt": 1},
        spawn("s1", 1),
        spawn("s2", 1),
        spawn("s1", 2),
    ]
    assert dispatch_order(events) == (("s1", 1), ("s2", 1), ("s1", 2))


def test_each_attempt_ends_merged_rejected_infrastructure_or_open() -> None:
    events: list[dict[str, Any]] = [
        spawn("s1", 1),
        {"kind": "attempt_rejected", "subtask_id": "s1", "attempt": 1},
        spawn("s1", 2),
        {"kind": "merged", "subtask_id": "s1", "attempt": 2},
        spawn("s2", 1),
        {"kind": "session_ended", "outcome": "infrastructure", "subtask_id": "s2", "attempt": 1},
        spawn("s3", 1),
        {"kind": "session_ended", "outcome": "infrastructure", "subtask_id": "s3", "attempt": 1},
        # A fresh session for the same attempt starts it over.
        spawn("s3", 1),
        {"kind": "merged", "subtask_id": "s3", "attempt": 1},
        spawn("s4", 1),
        # A decision on an attempt never dispatched is not an end of any attempt.
        {"kind": "merged", "subtask_id": "s9", "attempt": 1},
    ]
    assert attempt_ends(events) == {
        ("s1", 1): "rejected",
        ("s1", 2): "merged",
        ("s2", 1): "infrastructure",
        ("s3", 1): "merged",
        ("s4", 1): "open",
    }
