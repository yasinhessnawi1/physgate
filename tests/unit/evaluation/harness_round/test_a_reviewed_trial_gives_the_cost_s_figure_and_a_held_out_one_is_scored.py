"""A trial whose module was reviewed gives its figure, and a held-out one is scored, not excluded.

Through the round, on the real loop: each module review's session is spawned on the run's log as
the real reviewer's is, and nothing but the review's own lines ends it. The figure the raw arm is
capped at is every message once: each review's tries, the plan's review, the decomposition and the
role sessions, the same total the run's cost line prices.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from round_rig import SCORED, make_rig

from physgate.evaluation import harness_round
from physgate.evaluation.harness_round import run_round
from physgate.orchestrator.accounting import TokenAccount
from physgate.orchestrator.events import ReviewRan, ReviewUnavailable, SessionSpawned, read_events
from physgate.orchestrator.session_ends import open_sessions


def _scorer(_task: Any, _answer: Path) -> dict[str, Any]:  # noqa: ANN401
    return dict(SCORED)


def _assembled(store: Path) -> dict[str, Any]:
    place = next((store / "control" / "withheld" / "harness").iterdir())
    lines = [json.loads(x) for x in (place / "ledger.jsonl").read_text().splitlines()]
    (assembled,) = [x for x in lines if x["kind"] == "assembled"]
    found: dict[str, Any] = assembled
    return found


def test_a_trial_reviewed_twice_after_its_plan_s_review_gives_the_figure_its_cost_line_prices(
    tmp_path: Path,
) -> None:
    rig = make_rig(tmp_path, design_review="observe")
    status, _summary = run_round(
        rig.inputs(trials=1),
        driver=rig.driver(review_fails=1),
        scorer=_scorer,
        sleep=lambda _: None,
    )
    assert status == "done"
    assembled = _assembled(rig.made.store)
    run_dir = Path(assembled["run_dir"])
    events = read_events(run_dir / "events.jsonl")
    reviews = [e.result.session_id for e in events if isinstance(e, ReviewRan)]
    spawned = {e.session_id for e in events if isinstance(e, SessionSpawned)}
    assert len(reviews) == 2, "the attempt's review failed once, so two reviews ran"
    assert set(reviews) <= spawned, "a review's session is not on the log as the loop records it"
    assert open_sessions(events, run_dir) == ()
    account = TokenAccount.from_events(events)
    spenders = sorted(a.split(":", 1)[0] for a in account.by_attribution())
    # Two role sessions, two module reviews and the plan's review, and the decomposition's call.
    assert spenders == ["decomposition", "reviewer", "reviewer", "reviewer", "session", "session"]
    assert assembled["no_figure"] is None
    assert assembled["harness_total"] == account.total().total()
    # The figure is the cost line's: every row's tokens, as the run's cost prices them.
    assert assembled["record"]["cost"]["tokens"] == assembled["harness_total"]


def test_a_review_try_the_machine_ended_and_its_retry_are_each_counted_once_in_the_figure(
    tmp_path: Path,
) -> None:
    rig = make_rig(tmp_path)
    status, _summary = run_round(
        rig.inputs(trials=1),
        driver=rig.driver(reviews_machine_ended=1),
        scorer=_scorer,
        sleep=lambda _: None,
    )
    assert status == "done"
    assembled = _assembled(rig.made.store)
    run_dir = Path(assembled["run_dir"])
    events = read_events(run_dir / "events.jsonl")
    ended = [e.session_id for e in events if isinstance(e, ReviewUnavailable)]
    ran = [e.result.session_id for e in events if isinstance(e, ReviewRan)]
    assert len(ended) == 1 and len(ran) == 1 and ended != ran, "one try ended, its retry answered"
    assert open_sessions(events, run_dir) == ()
    account = TokenAccount.from_events(events)
    tries = {f"reviewer:{s}" for s in (*ended, *ran)}
    assert tries <= set(account.by_attribution()), "a try's spend is not on the record"
    assert assembled["harness_total"] == account.total().total()
    assert assembled["record"]["cost"]["tokens"] == assembled["harness_total"]


def test_a_held_out_trial_whose_module_was_reviewed_is_scored_with_its_figure(
    tmp_path: Path,
) -> None:
    rig = make_rig(tmp_path)
    status, summary = run_round(
        rig.inputs(tiers=("held_out",), trials=1, tasks=1),
        driver=rig.driver(),
        scorer=_scorer,
        sleep=lambda _: None,
    )
    assert status == "done" and summary["tiers"]["held_out"]["assembled"] == 1
    assembled = _assembled(rig.made.store)
    events = read_events(Path(assembled["run_dir"]) / "events.jsonl")
    assert [e for e in events if isinstance(e, ReviewRan)], "the trial's module was not reviewed"
    assert assembled["outcome"] == "pass", assembled["record"].get("reason")
    assert assembled["harness_total"] is not None and assembled["no_figure"] is None


def test_a_run_waiting_for_the_limit_after_its_review_ended_is_stuck_not_a_leftover_unread(
    tmp_path: Path,
) -> None:
    # The attempt's review failed it and ended; the next attempt's session met the usage limit,
    # so the run stands where a resume continues it: no figure, and the review is no leftover.
    rig = make_rig(tmp_path)
    driver = rig.driver(review_fails=1, limited={2})
    status, _summary = run_round(
        rig.inputs(trials=1), driver=driver, scorer=_scorer, sleep=lambda _: None
    )
    assert status == "waiting_for_limit", status
    run_dir = driver.drives[-1].run_dir
    events = read_events(run_dir / "events.jsonl")
    assert [e for e in events if isinstance(e, ReviewRan)], "the first attempt was not reviewed"
    assert open_sessions(events, run_dir) == ()
    assert harness_round._no_figure_because(run_dir, unscored=False) == "stuck"
