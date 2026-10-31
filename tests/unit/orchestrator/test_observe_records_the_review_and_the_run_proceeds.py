"""Under ``observe`` the plan's review is recorded in the run's opening, and the run goes on.

The review runs after the one call and before anything of the run is written, so its record is
part of the run's opening: the installation its session ran under, what it spent attributed to
its own session, and one line with what it came to (a verdict or why there is none), the plan's
digest it judged and the stream's seal it held. A verdict of any kind leaves the run's next step
the first dispatch. A review that showed held-out material records the exposure and halts the run
before anything is dispatched.

Replay holds the line to its place: only in a run that reviews its plan, once, after the plan it
names and before any dispatch, with the plan's own digest; and nothing is dispatched in such a run
before it. A run that does not review its plan writes its opening exactly as before.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest
from design_review_rig import (
    REVIEW_SESSION,
    REVIEWER,
    design_line_kind,
    digest,
    git,
    kinds,
    line,
    lines,
    outcome_of,
    plan,
    refusal,
    result,
    reviewed,
    started,
)

from physgate.orchestrator.accounting import TokenAccount
from physgate.orchestrator.events import read_events
from physgate.orchestrator.exceptions import RunConfigError
from physgate.orchestrator.replay import replay


def _started(tmp_path: Path, *args: Any, **kwargs: Any) -> Path:  # noqa: ANN401
    run_dir = outcome_of(lambda: started(tmp_path, *args, **kwargs))
    assert isinstance(run_dir, Path), run_dir
    return run_dir


def _design_line(run_dir: Path) -> dict[str, Any]:
    kind = design_line_kind()
    found = [one for one in lines(run_dir) if one["kind"] == kind]
    assert len(found) == 1, found
    return found[0]


def test_observe_records_the_review_and_the_run_proceeds(tmp_path: Path) -> None:
    run_dir = _started(tmp_path)
    log = lines(run_dir)
    assert log[0]["kind"] == "run_started"
    assert log[0].get("design_review") == "observe"
    kind = design_line_kind()
    # The opening: the call's tokens, the installation the review ran under, the plan, then the
    # review's tokens and its line, last, before anything is dispatched.
    assert kinds(run_dir) == [
        "run_started",
        "tokens_used",
        "install_checked",
        "decomposed",
        "subtask_planned",
        "subtask_planned",
        "tokens_used",
        kind,
    ]
    ran = _design_line(run_dir)
    assert ran["result"]["verdict"] == "fail"
    assert ran["result"]["session_id"] == REVIEW_SESSION
    assert ran["result"]["reviewer_model"] == REVIEWER
    assert ran["plan_sha256"] == digest(plan()) == log[3]["plan_sha256"]
    assert "unavailable" not in ran
    assert log[2]["path"] == "/install"
    assert log[6]["attribution"] == f"reviewer:{REVIEW_SESSION}"
    # The run goes on: its next step is the first subtask's first attempt.
    state = replay(read_events(run_dir / "events.jsonl"))
    step = state.next_step()
    assert (step.kind, step.attempt, step.point) == ("attempt", 1, "resolve")
    assert step.subtask_id == log[4]["subtask_id"]


@pytest.mark.parametrize("verdict", ["pass", "fail", "blocked"])
def test_whatever_the_verdict_an_observed_run_proceeds(tmp_path: Path, verdict: str) -> None:
    run_dir = _started(tmp_path, review=lambda d: reviewed(d, result=result(verdict)))
    assert _design_line(run_dir)["result"]["verdict"] == verdict
    assert replay(read_events(run_dir / "events.jsonl")).next_step().kind == "attempt"


def test_a_review_with_no_verdict_is_recorded_with_its_cause_and_the_run_proceeds(
    tmp_path: Path,
) -> None:
    unavailable = {
        "cause": "reading_incomplete",
        "detail": "a required file was not read in full",
        "session_id": REVIEW_SESSION,
        "reviewer_model": REVIEWER,
    }
    run_dir = _started(tmp_path, review=lambda d: reviewed(d, unavailable=unavailable))
    ran = _design_line(run_dir)
    assert ran["unavailable"] == unavailable
    assert "result" not in ran
    assert replay(read_events(run_dir / "events.jsonl")).next_step().kind == "attempt"


def test_a_review_that_showed_held_out_material_halts_the_run_before_any_dispatch(
    tmp_path: Path,
) -> None:
    run_dir = _started(tmp_path, review=lambda d: reviewed(d, exposed=True))
    log = lines(run_dir)
    assert design_line_kind() not in kinds(run_dir)
    incident, halted = log[-2], log[-1]
    assert (incident["kind"], incident["cause"], incident["subtask_id"]) == (
        "incident",
        "held_out_read",
        None,
    )
    assert REVIEW_SESSION in incident["detail"]
    assert (halted["kind"], halted["reason"]) == ("halted", "incident")
    # What the review spent is recorded all the same.
    assert log[-3]["attribution"] == f"reviewer:{REVIEW_SESSION}"
    assert replay(read_events(run_dir / "events.jsonl")).next_step().kind == "halted"


def test_no_second_decomposition_call_and_one_review_session_on_the_account(
    tmp_path: Path,
) -> None:
    run_dir = _started(tmp_path)
    account = TokenAccount.from_events(read_events(run_dir / "events.jsonl"))
    assert account.decomposition_invocations() == 1
    account.assert_no_routing()
    reviewers = [a for a in account.by_attribution() if a.startswith("reviewer:")]
    assert reviewers == [f"reviewer:{REVIEW_SESSION}"]


def test_a_run_that_does_not_review_its_plan_writes_its_opening_as_before(tmp_path: Path) -> None:
    run_dir = _started(tmp_path, "off", review=None)
    assert kinds(run_dir) == ["run_started", "tokens_used", "decomposed", *["subtask_planned"] * 2]
    # The first line's fields are the ones a run before the flag wrote, and no other.
    assert set(lines(run_dir)[0]) == {
        "seq",
        "ts",
        "run_id",
        "gate_mode",
        "kind",
        "config_sha256",
        "escalation_backend",
    }
    recorded = (run_dir / "run.json").read_bytes()
    assert b"design_review" not in recorded


def test_a_run_that_does_not_review_its_plan_records_no_review(tmp_path: Path) -> None:
    refused = outcome_of(lambda: started(tmp_path, "off"))
    assert isinstance(refused, RunConfigError), refused
    _nothing_written(tmp_path)


def test_a_run_that_reviews_its_plan_is_not_started_without_its_review(tmp_path: Path) -> None:
    refused = outcome_of(lambda: started(tmp_path, "observe", review=None))
    assert isinstance(refused, RunConfigError), refused
    _nothing_written(tmp_path)


def _nothing_written(root: Path) -> None:
    """No run record and no run branch: refused before the specifications were committed."""
    events = root / "run" / "events.jsonl"
    assert not events.exists() or not events.read_bytes()
    assert git(root / "target", "branch", "--format=%(refname:short)").split() == ["master"]


# -- replay holds the line to its place ----------------------------------------------------


def _refused(tmp_path: Path, edit: Any) -> str:  # noqa: ANN401 - the edit of the log
    run_dir = _started(tmp_path)
    log = lines(run_dir)
    assert refusal(tmp_path, log) == ""  # the opening as written follows
    return refusal(tmp_path, edit(log))


def _dispatch(template: dict[str, Any], subtask_id: str) -> dict[str, Any]:
    return line("stage_entered", template, subtask_id=subtask_id, attempt=1, stage="resolve")


def test_nothing_is_dispatched_in_a_reviewing_run_before_its_review_is_recorded(
    tmp_path: Path,
) -> None:
    kind = design_line_kind()

    def edit(log: list[dict[str, Any]]) -> list[dict[str, Any]]:
        kept = [one for one in log if one["kind"] != kind]
        return [*kept, _dispatch(log[-1], log[4]["subtask_id"])]

    assert "review" in _refused(tmp_path, edit)


def test_the_review_is_recorded_only_in_a_run_that_reviews_its_plan(tmp_path: Path) -> None:
    def edit(log: list[dict[str, Any]]) -> list[dict[str, Any]]:
        first = {k: v for k, v in log[0].items() if k != "design_review"}
        return [first, *log[1:]]

    assert "review" in _refused(tmp_path, edit)


def test_the_review_is_recorded_once(tmp_path: Path) -> None:
    assert "once" in _refused(tmp_path, lambda log: [*log, log[-1]])


def test_the_review_follows_the_plan_it_names(tmp_path: Path) -> None:
    def edit(log: list[dict[str, Any]]) -> list[dict[str, Any]]:
        ran = log[-1]
        return [log[0], log[1], log[2], ran, *log[3:-1]]

    assert "follows the plan" in _refused(tmp_path, edit)


def test_the_review_names_the_plan_the_run_recorded(tmp_path: Path) -> None:
    def edit(log: list[dict[str, Any]]) -> list[dict[str, Any]]:
        return [*log[:-1], {**log[-1], "plan_sha256": "0" * 64}]

    assert "another plan" in _refused(tmp_path, edit)


def test_the_review_comes_before_any_dispatch(tmp_path: Path) -> None:
    def edit(log: list[dict[str, Any]]) -> list[dict[str, Any]]:
        ran = log[-1]
        return [*log[:-1], _dispatch(ran, log[4]["subtask_id"]), ran]

    # Refused for the dispatch before it, which is the rule that matters here.
    assert "review" in _refused(tmp_path, edit)


@pytest.mark.parametrize("which", ["both", "neither"])
def test_the_review_line_says_a_verdict_or_why_there_is_none_and_not_both(
    tmp_path: Path, which: str
) -> None:
    unavailable = {
        "cause": "no_verdict",
        "detail": "no model message in the review",
        "session_id": REVIEW_SESSION,
        "reviewer_model": REVIEWER,
    }

    def edit(log: list[dict[str, Any]]) -> list[dict[str, Any]]:
        ran = dict(log[-1])
        if which == "both":
            ran["unavailable"] = unavailable
        else:
            ran.pop("result")
        return [*log[:-1], ran]

    assert _refused(tmp_path, edit) != ""


def test_the_record_itself_refuses_a_review_its_run_does_not_take(tmp_path: Path) -> None:
    # Held where the opening is written, not only where the decomposition starts the run: a
    # caller that starts a record directly is refused the same, before anything is written.
    from design_review_rig import config, target_repo

    from physgate.orchestrator.record import DecompositionSummary, RunRecord

    repo = target_repo(tmp_path)
    run_dir = tmp_path / "run"
    summary = DecompositionSummary(
        session_id="decomposition-session-1",
        model="claude-opus-5-5",
        num_turns=1,
        subtasks=0,
        interface_nodes=("iface.drive",),
        spec_commit="c" * 40,
        head_revision=1,
        plan_sha256=digest(plan()),
    )
    (run_dir / "decomposition").mkdir(parents=True)
    (run_dir / "decomposition" / "stdout.jsonl").write_text("{}\n")
    for flag, given in (("observe", None), ("off", reviewed(run_dir))):
        record = RunRecord(config(repo, flag), run_dir)
        refused = outcome_of(lambda r=record, g=given: r.start([], decomposed=summary, reviewed=g))
        record.close()
        assert isinstance(refused, RunConfigError), (flag, refused)
        events = run_dir / "events.jsonl"
        assert not events.exists() or not events.read_bytes(), flag
        assert not (run_dir / "run.json").exists(), flag
