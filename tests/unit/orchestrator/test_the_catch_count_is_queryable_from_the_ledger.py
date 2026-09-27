"""The catch count is queryable from the run logs, per check, and matches a count by hand.

ARCH-083: the headline quantity is the number of physical errors the gate caught
where the paired reviewer had already passed the work, queryable from the first
run and aggregated weekly. Two synthetic runs with every verdict known in
advance; the table the query must return is written out below, computed by hand
from the lines, before the query ran.

Run ``run-1``, gate mode observe:

    seq  line
     0   s1/1 gate: magnitude FAILS on motor.left (subtask)
     1   s1/1 review: pass
     2   s1/1 wrote motor.left, revision 2
     3   s2/1 gate: magnitude FAILS on electrical.driver (subtask)
     4   s2/1 review: fail
     5   s3/1 gate: magnitude passes (subtask)
     6   s3/1 review: pass
     7   s3/1 wrote motor.right, revision 3
     8   integration: magnitude FAILS on motor.left (system);
                      propagation FAILS on motor.right (system)

Run ``run-2``, gate mode on, a week later:

     0   s1/1 gate: magnitude FAILS on motor.left (subtask); refused, never reviewed
     1   s1/2 gate: magnitude passes (subtask)
     2   s1/2 review: pass

By hand, observe (``run-1`` only in its week):

    check        checks run  blocking  passed  failed  none  artefacts  after passed
    magnitude    4           3         2       1       0     2          1
    propagation  1           1         1       0       0     1          1
    all          5           4         3       1       0     3          2

- magnitude checks run: seq 0, 3, 5 at subtask, seq 8 at system = 4.
- magnitude blocking: seq 0 (s1, reviewer passed), seq 3 (s2, failed), seq 8 on
  motor.left, stamped from s1's review because s1 last wrote it (passed) = 3;
  passed 2, failed 1.
- magnitude artefacts: s1 and s2; seq 8 is s1 again, so 2. After passed: s1 only.
- propagation: seq 8 on motor.right, last written by s3, whose review passed: 1, 1.
- all: 4 + 1 checks run; 3 + 1 blocking; artefacts s1, s2, s3 = 3; after passed
  s1, s3 = 2.

By hand, on (``run-2``): magnitude 2 checks run, 1 blocking, 0 passed, 0 failed,
1 with no review, 1 artefact, 0 after passed; ``all`` the same.
"""

from __future__ import annotations

from datetime import datetime

import pytest
from synthetic_ledger import Log, record

from physgate.orchestrator.catches import CatchRow, catches, parse_time
from physgate.orchestrator.events import Event
from physgate.orchestrator.gate_events import gate_events

WEEK_1 = "2026-09-24T10:00:00.000000Z"
WEEK_2 = "2026-10-01T10:00:00.000000Z"

COLUMNS = (
    "checks_run",
    "blocking_failures",
    "reviewer_had_passed",
    "reviewer_had_failed",
    "no_review",
    "artefacts_caught",
    "caught_after_reviewer_passed",
)
#: The table above, as the query must return it: (mode, name) → the seven columns.
BY_HAND = {
    ("observe", "magnitude"): (4, 3, 2, 1, 0, 2, 1),
    ("observe", "propagation"): (1, 1, 1, 0, 0, 1, 1),
    ("observe", "all"): (5, 4, 3, 1, 0, 3, 2),
    ("on", "magnitude"): (2, 1, 0, 0, 1, 1, 0),
    ("on", "all"): (2, 1, 0, 0, 1, 1, 0),
}


def observe_run() -> Log:
    """``run-1`` in the table above."""
    log = Log("run-1", "observe", WEEK_1)
    log.gate("s1", 1, node="motor.left")
    log.review("s1", 1, "pass")
    log.wrote("s1", 1, "motor.left", 2)
    log.gate("s2", 1, node="electrical.driver")
    log.review("s2", 1, "fail")
    log.gate("s3", 1, fails=False)
    log.review("s3", 1, "pass")
    log.wrote("s3", 1, "motor.right", 3)
    log.integration(
        record("fail", "motor.left", scope="system"),
        record("fail", "motor.right", "propagation"),
    )
    return log


def on_run() -> Log:
    """``run-2`` in the table above."""
    log = Log("run-2", "on", WEEK_2)
    log.gate("s1", 1, node="motor.left")
    log.gate("s1", 2, fails=False)
    log.review("s1", 2, "pass")
    return log


def table(rows: list[CatchRow]) -> dict[tuple[str, str], tuple[int, ...]]:
    return {(r.gate_mode, r.name): tuple(getattr(r, c) for c in COLUMNS) for r in rows}


def test_the_query_over_both_runs_equals_the_table_computed_by_hand() -> None:
    events = gate_events(observe_run().lines) + gate_events(on_run().lines)
    rows = catches(events)
    assert table(rows) == BY_HAND
    assert [(r.gate_mode, r.check) for r in rows] == [
        ("observe", 2),
        ("observe", 7),
        ("observe", None),
        ("on", 2),
        ("on", None),
    ]


def test_a_week_is_a_window_on_the_gate_lines_time() -> None:
    events = gate_events(observe_run().lines) + gate_events(on_run().lines)
    first = catches(events, since=parse_time("2026-09-21"), until=parse_time("2026-09-28"))
    assert table(first) == {k: v for k, v in BY_HAND.items() if k[0] == "observe"}
    second = catches(events, since=parse_time("2026-09-28"), until=parse_time("2026-10-05"))
    assert table(second) == {k: v for k, v in BY_HAND.items() if k[0] == "on"}


def test_the_window_includes_its_start_and_excludes_its_end() -> None:
    events = gate_events(on_run().lines)
    assert catches(events, since=parse_time(WEEK_2)) != []
    assert catches(events, until=parse_time(WEEK_2)) == []


def test_a_run_with_no_gate_events_gives_no_rows_not_an_error() -> None:
    log = Log()
    log.review("s1", 1, "pass")
    assert catches(gate_events(log.lines)) == []
    assert catches([]) == []


@pytest.mark.parametrize("text", ["2026-13-01", "yesterday", "2026-09-21T10:00:00+02:00"])
def test_a_window_that_is_not_a_utc_date_or_time_is_refused(text: str) -> None:
    with pytest.raises(ValueError):
        parse_time(text)


def test_a_bare_date_is_its_midnight() -> None:
    assert parse_time("2026-09-21") == datetime(2026, 9, 21)  # noqa: DTZ001 - UTC by contract
    assert parse_time("2026-09-21T10:30:00.000000Z") == datetime(2026, 9, 21, 10, 30)  # noqa: DTZ001


def test_the_events_the_query_reads_are_the_derived_ones() -> None:
    lines: list[Event] = observe_run().lines
    assert catches(gate_events(lines)) == catches(gate_events(list(lines)))
