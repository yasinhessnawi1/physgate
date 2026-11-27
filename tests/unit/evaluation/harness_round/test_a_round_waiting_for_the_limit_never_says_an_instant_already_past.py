"""A round waiting for the usage limit always says when to come back, never an instant past.

The reset the client's message gave can have passed by the time the halt is read: the core would
then resume the run at once, and the drive's exit said only that it waits. The command still says
a wait (exit 75 with ``waiting``): the trial, and an instant still to come, the floor from now,
marked as the floor, so a wrapper that sleeps until it never starts again at once. A wait whose
instant is still to come is said as read, with no floor.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

from round_rig import SCORED, make_rig

from physgate.evaluation.harness_round import LIMIT_WAIT_FLOOR, run_round
from physgate.orchestrator.common import utc_stamp
from physgate.orchestrator.usage_limit import stamped


def _scorer(_task: Any, _answer: Path) -> dict[str, Any]:  # noqa: ANN401
    return dict(SCORED)


def test_a_reset_already_past_is_said_as_the_floor_from_now(tmp_path: Path) -> None:
    rig = make_rig(tmp_path)
    now = datetime.now(UTC)
    driver = rig.driver(limited={1}, limit_resets_at=utc_stamp(now - timedelta(minutes=5)))
    status, summary = run_round(
        rig.inputs(trials=1), driver=driver, scorer=_scorer, sleep=lambda _s: None, now=lambda: now
    )
    assert status == "waiting_for_limit"
    assert "waiting" in summary, "the round waits for the limit and says no wait"
    waiting = summary["waiting"]
    assert waiting["index"] == 0 and waiting["why"] == "usage_limit"
    assert stamped(waiting["resume_after"]) == now + LIMIT_WAIT_FLOOR
    assert waiting["floor"] is True


def test_a_reset_still_to_come_is_said_as_read_with_no_floor(tmp_path: Path) -> None:
    rig = make_rig(tmp_path)
    now = datetime.now(UTC)
    later = utc_stamp(now + timedelta(hours=2))
    driver = rig.driver(limited={1}, limit_resets_at=later)
    status, summary = run_round(
        rig.inputs(trials=1), driver=driver, scorer=_scorer, sleep=lambda _s: None, now=lambda: now
    )
    assert status == "waiting_for_limit"
    assert summary["waiting"]["resume_after"] == later
    assert "floor" not in summary["waiting"]
