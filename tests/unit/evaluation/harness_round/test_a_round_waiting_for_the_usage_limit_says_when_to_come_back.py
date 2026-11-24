"""A round waiting for the account's usage limit says when to come back, and holds the word to it.

Exit 75 is a state, not a wait: the command returns at once. So the round says, in its printed
line and its output directory, which trial waits, the instant after which it goes on, and whether a
person's word (``--limit-reset``) would let it on sooner. The instant is the core's: the reset as
the client's limit message gave it, where the core read one, and otherwise the core's stated wait
after the halt. The round holds the word to the core's own rule for a run: a reset that was read is
waited for whatever the word says; one that was not is waited for until the stated wait has passed,
or until the word, which is used once and named on the line of the directory it let the round make.
After the instant the round goes on with no word. A restart before it makes nothing.
"""

from __future__ import annotations

import inspect
import json
from collections.abc import Callable
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

from round_rig import SCORED, Rig, StandInDriver, make_rig

from physgate.evaluation.harness_round import HARNESS_ROUNDS, LEDGER, ROUND_RECORD, run_round
from physgate.evaluation.tiers.store import withheld_root
from physgate.orchestrator.common import utc_stamp
from physgate.orchestrator.events import Halted, read_events
from physgate.orchestrator.usage_limit import UNREAD_RESET_WAIT, stamped


def _score(_task: Any, _answer: Path) -> dict[str, Any]:  # noqa: ANN401
    return dict(SCORED)


def _round(
    rig: Rig,
    driver: StandInDriver,
    now: Callable[[], datetime],
    *,
    resume: bool = False,
    limit_reset: bool = False,
) -> tuple[str, dict[str, Any]]:
    assert "now" in inspect.signature(run_round).parameters, "the round reads no clock"
    driver.clock = now
    status, summary = run_round(
        rig.inputs(trials=1),
        driver=driver,
        scorer=_score,
        resume=resume,
        limit_reset=limit_reset,
        sleep=lambda _: None,
        now=now,
    )
    return status, summary


def _place(rig: Rig) -> Path:
    summary = json.loads((rig.root / "out" / ROUND_RECORD).read_bytes())
    return withheld_root(rig.made.store, "control") / HARNESS_ROUNDS / str(summary["round"])


def _ledger(rig: Rig, kind: str) -> list[dict[str, Any]]:
    lines = [json.loads(x) for x in (_place(rig) / LEDGER).read_bytes().splitlines()]
    return [x for x in lines if x["kind"] == kind]


def _halted_at(rig: Rig, name: str) -> datetime:
    events = read_events(rig.run_root / _place(rig).name / name / "events.jsonl")
    return stamped([e for e in events if isinstance(e, Halted)][-1].ts)


def _at(instant: datetime) -> Callable[[], datetime]:
    return lambda: instant


def _real() -> datetime:
    return datetime.now(UTC)


def test_a_decomposition_on_the_limit_says_which_trial_waits_and_until_when(tmp_path: Path) -> None:
    rig = make_rig(tmp_path)
    status, summary = _round(rig, rig.driver(fails={1: "usage_limit"}), _real)
    assert status == "waiting_for_limit"
    after = utc_stamp(_halted_at(rig, "0000-1") + UNREAD_RESET_WAIT)
    waiting = summary.get("waiting")
    assert waiting == {
        "index": 0,
        "why": "usage_limit",
        "resume_after": after,
        "word_helps": True,
    }
    written = json.loads((rig.root / "out" / ROUND_RECORD).read_bytes())
    assert written.get("waiting") == waiting
    (line,) = _ledger(rig, "limit")
    assert line.get("resume_after") == after


def test_a_restart_before_the_instant_makes_nothing_and_after_it_goes_on_with_no_word(
    tmp_path: Path,
) -> None:
    rig = make_rig(tmp_path)
    _round(rig, rig.driver(fails={1: "usage_limit"}), _real)
    halted = _halted_at(rig, "0000-1")
    held = (_place(rig) / LEDGER).read_bytes()
    early = rig.driver()
    status, _ = _round(rig, early, _at(halted + timedelta(hours=1)), resume=True)
    assert status == "waiting_for_limit" and early.decomposed == []
    assert (_place(rig) / LEDGER).read_bytes() == held
    late = rig.driver()
    later = _at(halted + UNREAD_RESET_WAIT + timedelta(seconds=1))
    status, _ = _round(rig, late, later, resume=True)
    assert status == "done"
    assert [c.run_dir.name for c in late.decomposed] == ["0000-2"]
    placed = [x for x in _ledger(rig, "placed") if x["attempt"] == 2]
    assert [x.get("limit_reset") for x in placed] == ["waited"]


def test_the_word_before_the_instant_makes_one_directory_named_as_the_person_s(
    tmp_path: Path,
) -> None:
    rig = make_rig(tmp_path)
    _round(rig, rig.driver(fails={1: "usage_limit"}), _real)
    soon = _at(_halted_at(rig, "0000-1") + timedelta(minutes=10))
    worded = rig.driver(fails={1: "usage_limit"})
    status, _ = _round(rig, worded, soon, resume=True, limit_reset=True)
    assert status == "waiting_for_limit"
    assert [c.run_dir.name for c in worded.decomposed] == ["0000-2"]
    placed = [x for x in _ledger(rig, "placed") if x["attempt"] == 2]
    assert [x.get("limit_reset") for x in placed] == ["operator"]
    # The word was used: started again without it, the round makes nothing.
    held = (_place(rig) / LEDGER).read_bytes()
    plain = rig.driver()
    status, _ = _round(rig, plain, _at(_halted_at(rig, "0000-2")), resume=True)
    assert status == "waiting_for_limit" and plain.decomposed == []
    assert (_place(rig) / LEDGER).read_bytes() == held


def test_a_session_whose_reset_was_read_is_waited_for_whatever_the_word_says(
    tmp_path: Path,
) -> None:
    rig = make_rig(tmp_path)
    start = _real()
    resets = start + timedelta(hours=2)
    first = rig.driver(limited={1}, limit_resets_at=utc_stamp(resets))
    status, summary = _round(rig, first, _at(start))
    assert status == "waiting_for_limit"
    assert summary.get("waiting") == {
        "index": 0,
        "why": "usage_limit",
        "resume_after": utc_stamp(resets),
        "word_helps": False,
    }
    early = rig.driver()
    status, _ = _round(
        rig, early, _at(resets - timedelta(minutes=1)), resume=True, limit_reset=True
    )
    assert status == "waiting_for_limit" and early.drives == []
    late = rig.driver()
    status, _ = _round(rig, late, _at(resets + timedelta(seconds=1)), resume=True)
    assert status == "done" and [(d.resume, d.limit_reset) for d in late.drives] == [(True, False)]


def test_a_session_whose_reset_was_not_read_says_the_stated_wait_and_that_the_word_helps(
    tmp_path: Path,
) -> None:
    rig = make_rig(tmp_path)
    status, summary = _round(rig, rig.driver(limited={1}), _real)
    assert status == "waiting_for_limit"
    halted = _halted_at(rig, "0000-1")
    assert summary.get("waiting") == {
        "index": 0,
        "why": "usage_limit",
        "resume_after": utc_stamp(halted + UNREAD_RESET_WAIT),
        "word_helps": True,
    }
