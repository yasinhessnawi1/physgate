"""A plan review whose session met a refused credential ends the rounds on the credential.

The reviewer reads the session's end as ``infrastructure``, no verdict, with the session's own
cause beside it. Under a mode that holds the plan the rounds then end void; the terminal line
names ``credential_refused``, so a reader of the journal (the harness round among them) tells it
from the machine's end and stops for a person, spending no attempt. The cause rides on the
review's record as the usage limit does: left out of every other end, so a journal written before
it reads as it always did.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import pytest
import test_a_decomposition_stopped_by_the_usage_limit_waits_for_its_reset as limit_rows
from replan_rig import DESIGN, Step, events, journal
from test_a_decomposition_stopped_by_the_usage_limit_waits_for_its_reset import (
    NOTHING,
    LimitScript,
    made,
)

from physgate.orchestrator.design_rounds import journal_spend, read_journal
from physgate.orchestrator.events import DesignUnavailable
from physgate.orchestrator.exceptions import ReviewUnavailableError, RunStateError
from physgate.orchestrator.protocols import MessageUsage


@dataclass
class CredentialScript(LimitScript):
    """The scripted rounds, with ``review="credential"``: a review a refused credential ended."""

    def review_plan(self, under: Any) -> Any:  # noqa: ANN401
        k = len(self.calls)
        if self._step(k).review != "credential":
            return super().review_plan(under)
        self.seen.append(under)
        raise ReviewUnavailableError(
            "the session ended with credential_refused",
            cause="infrastructure",
            session_id=f"review-{k}",
            reviewer_model=DESIGN,
            usage=(MessageUsage(message_id=f"r{k}", usage=NOTHING),),
            session_cause="credential_refused",
        )


@pytest.fixture
def credential_script(monkeypatch: pytest.MonkeyPatch) -> None:
    # ``made`` puts the limit's script in place; this one is put in place of that.
    monkeypatch.setattr(limit_rows, "LimitScript", CredentialScript)


def _made(root: Path, mode: str, capsys: Any, monkeypatch: pytest.MonkeyPatch) -> Any:  # noqa: ANN401
    ran = made(root, mode, [Step(review="credential")], capsys, monkeypatch)
    assert isinstance(ran.script, CredentialScript)
    return ran


@pytest.mark.usefixtures("credential_script")
@pytest.mark.parametrize("mode", ["on", "repair:1"])
def test_under_a_mode_that_holds_the_rounds_end_void_naming_the_refused_credential(
    tmp_path: Path, mode: str, capsys: pytest.CaptureFixture[str], monkeypatch: pytest.MonkeyPatch
) -> None:
    ran = _made(tmp_path, mode, capsys, monkeypatch)
    lines = journal(ran.run_dir)
    ended = next(one for one in lines if one["kind"] == "round_ended")
    assert ended["ending"]["review_cause"] == "infrastructure"
    assert ended["review"]["unavailable"]["session_cause"] == "credential_refused"
    assert "usage_limit" not in ended
    terminal = lines[-1]
    assert (terminal["follows"], terminal["ending_class"], terminal["cause"]) == (
        "void",
        "infrastructure",
        "credential_refused",
    )
    read_journal(ran.run_dir, last=2 if mode == "repair:1" else 1)
    assert journal_spend(ran.run_dir)[0] == "credential_refused"
    assert events(ran.run_dir) == [], "a void decomposition starts no run"


@pytest.mark.usefixtures("credential_script")
def test_an_observed_run_starts_naming_the_credential_its_review_met(
    tmp_path: Path, capsys: pytest.CaptureFixture[str], monkeypatch: pytest.MonkeyPatch
) -> None:
    # An observed review's infrastructure end starts the run, as it always has; the record says
    # the review's session met a refused credential.
    ran = _made(tmp_path, "observe", capsys, monkeypatch)
    (line,) = [e for e in events(ran.run_dir) if e["kind"] == "design_review_ran"]
    assert line["unavailable"]["cause"] == "infrastructure"
    assert line["unavailable"]["session_cause"] == "credential_refused"
    read_journal(ran.run_dir, last=1, holds=False)


@pytest.mark.usefixtures("credential_script")
def test_the_terminal_line_names_the_credential_only_where_its_review_s_record_does(
    tmp_path: Path, capsys: pytest.CaptureFixture[str], monkeypatch: pytest.MonkeyPatch
) -> None:
    ran = _made(tmp_path, "on", capsys, monkeypatch)
    lines = journal(ran.run_dir)
    ended = next(one for one in lines if one["kind"] == "round_ended")
    del ended["review"]["unavailable"]["session_cause"]
    _rewrite(ran.run_dir, lines)
    with pytest.raises(RunStateError) as refused:
        read_journal(ran.run_dir, last=1)
    assert refused.value.context["check"] == "terminal"
    # As a journal written before the cause was recorded: both lines name the machine's end.
    lines[-1]["cause"] = "infrastructure"
    _rewrite(ran.run_dir, lines)
    read_journal(ran.run_dir, last=1)
    assert journal_spend(ran.run_dir)[0] == "infrastructure"


def test_only_an_infrastructure_end_off_the_limit_names_a_refused_credential() -> None:
    fields: dict[str, Any] = {
        "detail": "x",
        "session_id": "s",
        "reviewer_model": DESIGN,
        "session_cause": "credential_refused",
    }
    assert DesignUnavailable(cause="infrastructure", **fields).model_dump()["session_cause"] == (
        "credential_refused"
    )
    with pytest.raises(ValueError, match="refused credential"):
        DesignUnavailable(cause="no_verdict", **fields)
    plain = DesignUnavailable(
        cause="infrastructure", detail="x", session_id="s", reviewer_model=None
    )
    assert "session_cause" not in plain.model_dump(), "an end without it keeps its bytes"


def _rewrite(run_dir: Path, lines: list[dict[str, Any]]) -> None:
    path = run_dir / "decomposition" / "rounds.jsonl"
    path.write_text("".join(json.dumps(one) + "\n" for one in lines))
