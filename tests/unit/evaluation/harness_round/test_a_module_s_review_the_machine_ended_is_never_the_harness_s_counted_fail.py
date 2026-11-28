"""A module's review the machine ended is never a counted fail of the harness arm.

Through the round, on the real loop: a review session the machine ends every time takes its
retries and then halts the run ``infrastructure_exhausted``; the round gives the run its one
resume after the registered delay, the review is owed again and ended again, and the trial is
assembled ``unscored``, with no figure, not as a fail with a cap. A review session whose
credential is refused halts the run at once, and the round waits for a person, spending nothing.
A review with no verdict for the reviewer's own reasons is still the harness's own fail, with a
figure.
"""

from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any

import pytest
import round_rig
from observe_rig import SPAWN_STARTED
from round_rig import SCORED, make_rig

from physgate.evaluation.harness_round import run_round
from physgate.orchestrator.events import Halted, ReviewUnavailable, read_events
from physgate.orchestrator.exceptions import ReviewUnavailableError
from physgate.orchestrator.ports import SpawnHook


def _scorer(_task: Any, _answer: Path) -> dict[str, Any]:  # noqa: ANN401
    return dict(SCORED)


class _EndedReviewer:
    """A module's reviewer whose session ends the same way at every call.

    Each call's session is spawned on the run's log first, as the real reviewer's is.
    """

    def __init__(self, model: str, cause: str, session_cause: str | None) -> None:
        self.model, self.cause, self.session_cause = model, cause, session_cause
        self.calls = 0
        self.hook: SpawnHook | None = None

    def record_spawns(self, hook: SpawnHook) -> None:
        self.hook = hook

    def review(self, artefact: Any) -> Any:  # noqa: ANN401
        self.calls += 1
        if self.hook is not None:
            self.hook(f"rev-ended-{self.calls}", os.getpid(), SPAWN_STARTED)
        raise ReviewUnavailableError(
            f"the session ended with {self.session_cause or self.cause}",
            cause=self.cause,  # type: ignore[arg-type]
            session_id=f"rev-ended-{self.calls}",
            reviewer_model=self.model,
            session_cause=self.session_cause,
        )


def _round(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, cause: str, session_cause: str | None
) -> tuple[str, dict[str, Any], list[dict[str, Any]], list[_EndedReviewer], list[float]]:
    rig = make_rig(tmp_path)
    made: list[_EndedReviewer] = []

    def reviewer(model: str = "x", **_rig: Any) -> _EndedReviewer:  # noqa: ANN401
        made.append(_EndedReviewer(model, cause, session_cause))
        return made[-1]

    monkeypatch.setattr(round_rig, "Reviewer", reviewer)
    slept: list[float] = []
    status, summary = run_round(
        rig.inputs(trials=1), driver=rig.driver(), scorer=_scorer, sleep=slept.append
    )
    place = next((rig.made.store / "control" / "withheld" / "harness").iterdir())
    lines = [json.loads(x) for x in (place / "ledger.jsonl").read_text().splitlines()]
    return status, summary, lines, made, slept


def test_a_review_the_machine_ends_every_time_makes_the_trial_unscored_with_no_figure(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    status, _summary, lines, made, slept = _round(
        tmp_path, monkeypatch, "infrastructure", "api_error"
    )
    (assembled,) = [x for x in lines if x["kind"] == "assembled"]
    assert assembled["unscored"] is True
    assert assembled["outcome"] == "unscored"
    assert assembled["harness_total"] is None
    assert status == "done_without_caps"
    events = read_events(Path(assembled["run_dir"]) / "events.jsonl")
    halts = [e.reason for e in events if isinstance(e, Halted)]
    assert halts == ["infrastructure_exhausted", "infrastructure_exhausted"]
    # The rig's ladder is one delay: each drive is the first end, its immediate retry and the
    # ladder's one, so three review sessions a drive; the round's resume after its delay.
    assert [r.calls for r in made] == [3, 3]
    assert 7.0 in slept
    # Every try ends on a line of its own, the one each drive halts on too: owed again.
    unavailable = [(e.cause, e.retry) for e in events if isinstance(e, ReviewUnavailable)]
    assert unavailable == [("infrastructure", True)] * 6


def test_a_review_s_refused_credential_stops_the_round_for_a_person(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    status, summary, lines, made, _slept = _round(
        tmp_path, monkeypatch, "infrastructure", "credential_refused"
    )
    assert status == "waiting_for_a_person"
    assert summary["waiting"]["why"] == "credential_refused"
    assert [r.calls for r in made] == [1]
    assert not [x for x in lines if x["kind"] in ("assembled", "superseded")]


def test_a_review_with_no_verdict_for_its_own_reasons_is_the_harness_s_fail_with_a_figure(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    status, _summary, lines, made, _slept = _round(tmp_path, monkeypatch, "no_verdict", None)
    (assembled,) = [x for x in lines if x["kind"] == "assembled"]
    assert (assembled["outcome"], assembled["unscored"]) == ("fail", False)
    assert assembled["harness_total"] is not None
    assert status == "done"
    assert [r.calls for r in made] == [1]
