"""A run that reviews its plan is held to its record: the flags, the seal, the session, the defects.

- ``decompose`` asks the requirements as of a new run, so a reportable run that does not observe
  its plan's review is refused before the call is spent.
- A run is opened only from a first line that says what its configuration says of the switches
  replay reads from that line: whether it acts on decisions, and whether it reviews its plan.
- The opening records the seal the call took over its stream, and a call that gave no plan under
  ``observe`` is recorded as a failed decomposition, with no review asked.
- The review's tokens are attributed to the session its line names, and to no other.
- A review that reached no verdict keeps the specification defects it named.
- A plan the run could not start is refused before its review is spent.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest
from design_review_rig import lines, outcome_of, refusal, reviewed, started
from test_decompose_reviews_the_plan_before_it_writes_anything import (
    REVIEWING,
    Calls,
    StandIn,
    _args,
    _exit,
    _nothing_recorded,
    _verdict,
)
from test_the_physgate_command_starts_and_decides import fake_binary

import physgate.orchestrator.cli as orchestrator_cli
from physgate.evaluation.requirements import observed_design_review_for_reportable_runs
from physgate.orchestrator.decompose import Outcome
from physgate.orchestrator.exceptions import ReviewUnavailableError, RunConfigError
from physgate.orchestrator.plan import Plan
from physgate.orchestrator.protocols import MessageUsage, SpecDefect, Usage
from physgate.orchestrator.record import RunRecord
from physgate.orchestrator.requirements import RunFacts
from physgate.orchestrator.run_config import load_run_config
from physgate.orchestrator.trajectory import seal


@pytest.fixture
def calls(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Calls:
    """The one model call, stood in for as the command's own tests stand it in."""
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-ant-test-dummy-not-a-credential")
    monkeypatch.setenv("PHYSGATE_CLAUDE_BIN", str(fake_binary(tmp_path, "2.1.272")))
    made = Calls()
    monkeypatch.setattr(orchestrator_cli, "call", made)
    return made


DEFECT = SpecDefect(finding="the brief gives no supply voltage", blocking=True)


def _log(tmp_path: Path) -> list[dict[str, Any]]:
    events = (tmp_path / "run" / "events.jsonl").read_text().splitlines()
    return [json.loads(raw) for raw in events]


def test_decompose_refuses_a_reportable_new_run_that_does_not_observe_its_plan_s_review(
    tmp_path: Path,
    calls: Calls,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    # The command's facts, asked of the evaluation's rule as of a reportable run: the other
    # reportable requirements (a clean checkout, the OS layer) are this machine's, not the rule's.
    def refusals(facts: RunFacts) -> list[str]:
        reportable = facts.config.model_copy(update={"reportable": True})
        asked = RunFacts(
            config=reportable,
            os_layer=facts.os_layer,
            shell_sessions=facts.shell_sessions,
            new_run=facts.new_run,
        )
        why = observed_design_review_for_reportable_runs(asked)
        return [] if why is None else [why]

    monkeypatch.setattr(orchestrator_cli, "refusals", refusals)
    reviewer = StandIn(_verdict())
    params = {**REVIEWING, "design_review": "off"}
    assert _exit(_args(tmp_path, params, places=False), reviewer) == 2
    assert "design_review: observe" in capsys.readouterr().err
    assert calls.made == 0
    assert reviewer.seen == []
    _nothing_recorded(tmp_path / "run")


@pytest.mark.parametrize(
    ("design_review", "edit"),
    [
        ("observe", lambda first: {k: v for k, v in first.items() if k != "design_review"}),
        ("off", lambda first: {**first, "design_review": "observe"}),
    ],
    ids=["observe_dropped", "observe_added"],
)
def test_a_run_opens_only_from_a_first_line_naming_its_plan_review(
    tmp_path: Path, design_review: str, edit: Any
) -> None:
    run_dir = outcome_of(
        lambda: started(
            tmp_path, design_review, review=reviewed if design_review != "off" else None
        )
    )
    assert isinstance(run_dir, Path), run_dir
    log = lines(run_dir)
    kept = [one for one in log[1:] if one["kind"] != "design_review_ran"]
    (run_dir / "events.jsonl").write_text(
        "".join(json.dumps({**one, "seq": i}) + "\n" for i, one in enumerate([edit(log[0]), *kept]))
    )
    opened = outcome_of(lambda: RunRecord(load_run_config(run_dir / "run.json"), run_dir))
    assert isinstance(opened, RunConfigError), opened
    assert "design_review" in str(opened.context)


@pytest.mark.parametrize("queue_decisions", ["act", "record"])
def test_a_run_opens_only_from_a_first_line_naming_whether_it_acts(
    tmp_path: Path, queue_decisions: str
) -> None:
    from plan_hold_rig import PRESENT

    overrides: dict[str, Any] = {"queue_decisions": queue_decisions}
    if queue_decisions == "act":
        overrides["os_layer"] = PRESENT
    run_dir = outcome_of(lambda: started(tmp_path, **overrides))
    assert isinstance(run_dir, Path), run_dir
    log = lines(run_dir)
    first = {k: v for k, v in log[0].items() if k != "queue_decisions"}
    if queue_decisions == "record":
        first["queue_decisions"] = "act"
    (run_dir / "events.jsonl").write_text(
        "".join(json.dumps({**one, "seq": i}) + "\n" for i, one in enumerate([first, *log[1:]]))
    )
    opened = outcome_of(lambda: RunRecord(load_run_config(run_dir / "run.json"), run_dir))
    assert isinstance(opened, RunConfigError), opened
    assert "queue_decisions" in str(opened.context)


def test_the_opening_records_the_seal_the_call_took(tmp_path: Path, calls: Calls) -> None:
    assert _exit(_args(tmp_path, REVIEWING), StandIn(_verdict())) == 0
    stream = tmp_path / "run" / "decomposition" / "stdout.jsonl"
    assert _log(tmp_path)[-1]["stream_seal"] == seal(stream.read_bytes()).model_dump()


def test_a_failed_call_under_observe_is_recorded_as_failed_with_no_review(
    tmp_path: Path, calls: Calls, monkeypatch: pytest.MonkeyPatch
) -> None:
    real = Calls.__call__

    def failed(self: Calls, brief: str, **kw: Any) -> Outcome:  # noqa: ANN401
        made = real(self, brief, **kw)
        return made.model_copy(
            update={"ok": False, "plan": None, "cause": "invalid_plan", "detail": "none"}
        )

    monkeypatch.setattr(Calls, "__call__", failed)
    reviewer = StandIn(_verdict())
    assert _exit(_args(tmp_path, REVIEWING), reviewer) == 1
    assert reviewer.seen == []
    log = _log(tmp_path)
    assert log[0]["design_review"] == "observe"
    assert [one["kind"] for one in log][-1] == "halted"
    assert all(one["kind"] != "design_review_ran" for one in log)


def test_the_review_s_tokens_name_the_session_its_ending_names(tmp_path: Path) -> None:
    refused = outcome_of(
        lambda: started(tmp_path, review=lambda d: reviewed(d, session_id="someone-else"))
    )
    assert not isinstance(refused, Path), refused
    assert "session" in str(refused)


def test_a_review_s_record_names_one_session_for_its_tokens_and_its_ending(tmp_path: Path) -> None:
    from design_review_rig import stream
    from pydantic import ValidationError

    stream(tmp_path / "run")
    refused = outcome_of(lambda: reviewed(tmp_path / "run", session_id="someone-else"))
    assert isinstance(refused, ValidationError), refused
    assert "the session its ending names" in str(refused)
    assert not isinstance(outcome_of(lambda: reviewed(tmp_path / "run")), Exception)


def test_replay_holds_the_review_s_tokens_to_the_session_its_line_names(tmp_path: Path) -> None:
    run_dir = outcome_of(lambda: started(tmp_path))
    assert isinstance(run_dir, Path), run_dir
    log = lines(run_dir)
    assert refusal(tmp_path, log) == ""
    assert log[-2]["attribution"] == "reviewer:review-session-1"
    edited = [*log[:-2], {**log[-2], "attribution": "reviewer:someone-else"}, log[-1]]
    assert "session" in refusal(tmp_path, edited)


def test_a_review_with_no_verdict_keeps_its_specification_defects(
    tmp_path: Path, calls: Calls
) -> None:
    usage = Usage(
        input_tokens=1, output_tokens=1, cache_read_input_tokens=0, cache_creation_input_tokens=0
    )
    error = ReviewUnavailableError(
        "the verdict did not validate",
        cause="invalid_verdict",
        session_id="review-session-2",
        reviewer_model="claude-opus-5-5",
        usage=(MessageUsage(message_id="r9", usage=usage),),
        spec_defects=(DEFECT,),
    )
    assert _exit(_args(tmp_path, REVIEWING), StandIn(error)) == 0
    ran = _log(tmp_path)[-1]
    assert ran["kind"] == "design_review_ran"
    assert ran["unavailable"].get("spec_defects") == [DEFECT.model_dump()]


def test_a_review_with_no_verdict_and_no_defects_keeps_its_line_s_bytes(tmp_path: Path) -> None:
    run_dir = outcome_of(
        lambda: started(
            tmp_path,
            review=lambda d: reviewed(
                d,
                unavailable={
                    "cause": "reading_incomplete",
                    "detail": "a file not read",
                    "session_id": "review-session-1",
                    "reviewer_model": "claude-sonnet-5",
                },
            ),
        )
    )
    assert isinstance(run_dir, Path), run_dir
    assert "spec_defects" not in lines(run_dir)[-1]["unavailable"]


def test_a_plan_the_run_could_not_start_is_refused_before_its_review_is_spent(
    tmp_path: Path, calls: Calls, monkeypatch: pytest.MonkeyPatch
) -> None:
    real = Calls.__call__

    def bad_id(self: Calls, brief: str, **kw: Any) -> Outcome:  # noqa: ANN401
        made = real(self, brief, **kw)
        assert made.plan is not None
        raw = json.loads(made.plan.model_dump_json())
        raw["interface_nodes"][0]["id"] = "iface.Bus"
        return made.model_copy(update={"plan": Plan.model_validate_json(json.dumps(raw))})

    monkeypatch.setattr(Calls, "__call__", bad_id)
    reviewer = StandIn(_verdict())
    assert _exit(_args(tmp_path, REVIEWING), reviewer) == 2
    assert reviewer.seen == []
    assert calls.made == 1
    _nothing_recorded(tmp_path / "run")
