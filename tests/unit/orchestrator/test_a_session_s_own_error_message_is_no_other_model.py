"""A session's own error message is no other model, in the harness arm's checks of who answered.

The pinned client writes messages of its own into a session's stream under the model name
``<synthetic>``: an API error's notice, the usage limit's. They are no model's answer, so a role
session or a decomposition call that met one and was then answered by its pinned model was
answered by that model alone. Nothing else is left out: a second real model, a name that only
looks like the client's, or no model at all is still a mismatch.

The role session's rows play a stand-in binary in the real dispatcher and the real worktree; the
decomposition call's are read by the code that judges its answer.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest
from test_a_role_session_leaves_nothing_running_before_the_orchestrator_s_git import (
    MODEL,
    SESSION,
    Session,
)
from test_the_decomposition_answer_is_untrusted_input import BRIEF, result

from physgate.orchestrator.budget import SessionEnd
from physgate.orchestrator.decompose import judge
from physgate.orchestrator.exceptions import InvocationError

SYNTHETIC = "<synthetic>"
PLANNER = "claude-sonnet-5"

#: A role session that met one API error's notice between two messages and then completed. The
#: second message is ``ANSWERER``'s; with no answerer, the notice is the stream's only message.
#: The prelude of the other module's stand-in is prepended.
NOTICE_THEN_DONE = r"""
import json, os, shlex, subprocess, sys

argv = sys.argv[1:]
if argv == ["--version"]:
    print("2.1.272 (Claude Code)")
    sys.exit(0)
settings = json.load(open(argv[argv.index("--settings") + 1]))
session_id = argv[argv.index("--session-id") + 1]


def hook(event):
    command = settings["hooks"][event][0]["hooks"][0]["command"]
    body = json.dumps({"session_id": session_id, "cwd": os.getcwd(), "hook_event_name": event})
    subprocess.run(shlex.split(command), input=body.encode(), capture_output=True, check=False)


hook("SessionStart")
os.makedirs("modules/power", exist_ok=True)
open("modules/power/done.py", "w").write("z = 2\n")
hook("SessionEnd")
usage = {"input_tokens": 3, "output_tokens": 5}
nothing = {"input_tokens": 0, "output_tokens": 0}
said = [{"type": "text", "text": "API Error: 529 Overloaded."}]
notice = {"id": "n1", "model": NOTICE_MODEL, "role": "assistant", "type": "message",
          "usage": nothing, "content": said}
error = {"type": "assistant", "message": notice, "error": "unknown", "is_api_error_message": True}
if ANSWERER is None:
    said, totals = [error], {"inputTokens": 0, "outputTokens": 0}
else:
    said = [
        {"type": "assistant", "message": {"id": "m1", "model": MODEL_NAME, "usage": usage}},
        error,
        {"type": "assistant", "message": {"id": "m2", "model": ANSWERER, "usage": usage}},
    ]
    totals = {"inputTokens": 6, "outputTokens": 10}
lines = [*said, {"type": "result", "is_error": False, "terminal_reason": "completed",
                 "modelUsage": {MODEL_NAME: totals}}]
sys.stdout.write("".join(json.dumps(line) + "\n" for line in lines))
sys.stdout.flush()
sys.exit(0)
"""


def _dispatched(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, *, answerer: str | None, notice: str
) -> Any:  # noqa: ANN401 - the dispatcher's report, or what it raised
    session = Session(tmp_path, "plain", pause=0.0, wall_clock_s=60.0)
    written = session.binary.read_text()
    prelude = written[: written.index(SESSION)]
    given = f"ANSWERER = {answerer!r}\nNOTICE_MODEL = {notice!r}\n"
    session.binary.write_text(prelude + given + NOTICE_THEN_DONE)
    dispatcher = session.dispatcher(monkeypatch)
    try:
        return dispatcher.run(session.request(), session.spawned)
    except InvocationError as exc:
        return exc


def test_a_role_session_that_met_a_notice_and_was_answered_by_its_pin_completes(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    report = _dispatched(tmp_path, monkeypatch, answerer=MODEL, notice=SYNTHETIC)
    assert not isinstance(report, InvocationError), f"the client's own message halted: {report}"
    assert report.end == SessionEnd(outcome="completed", cause=None)
    assert report.attempt_commit is not None


@pytest.mark.parametrize(
    ("answerer", "notice"),
    [("claude-haiku-4-5-20251001", SYNTHETIC), (None, "<Synthetic>"), (None, "<synthetic> ")],
    ids=["another model after the notice", "a lookalike name", "a lookalike with a space"],
)
def test_a_role_session_answered_by_any_other_name_is_still_refused(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, answerer: str | None, notice: str
) -> None:
    report = _dispatched(tmp_path, monkeypatch, answerer=answerer or MODEL, notice=notice)
    assert isinstance(report, InvocationError), report
    assert str(report) == "the session was answered by a model other than the pinned one"
    assert report.context["asked"] == MODEL


def test_a_completed_role_session_no_model_answered_is_refused_never_taken_as_the_pin(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    report = _dispatched(tmp_path, monkeypatch, answerer=None, notice=SYNTHETIC)
    assert isinstance(report, InvocationError), report
    assert str(report) == "the session was answered by a model other than the pinned one"
    assert (report.context["asked"], report.context["answered"]) == (MODEL, "")


def _judged(answered: frozenset[str]) -> tuple[Any, ...]:
    return judge(
        result(),
        exit_code=0,
        timed_out=False,
        model=PLANNER,
        roles=["electrical"],
        answered=answered,
        brief=BRIEF,
    )


def test_a_decomposition_call_that_met_a_notice_and_was_answered_by_its_pin_is_a_plan() -> None:
    cause, _, plan, named, _ = _judged(frozenset({PLANNER, SYNTHETIC}))
    assert (cause, plan is not None) == (None, True)
    # The model the call's records name (the outcome's, as the decomposition takes it): the pin.
    assert named == PLANNER


def test_a_decomposition_call_only_the_client_wrote_to_is_never_recorded_as_the_pin() -> None:
    cause, _, plan, named, _ = _judged(frozenset({SYNTHETIC}))
    assert (cause, plan) == ("model_mismatch", None)
    assert named == SYNTHETIC, "the call no model answered is recorded as answered by the pin"


@pytest.mark.parametrize(
    "answered",
    [
        frozenset({SYNTHETIC}),
        frozenset({PLANNER, SYNTHETIC, "claude-haiku-4-5-20251001"}),
        frozenset({PLANNER, "<Synthetic>"}),
        frozenset({PLANNER, "synthetic"}),
    ],
    ids=[
        "the notice alone",
        "a second real model",
        "a lookalike name",
        "a lookalike without brackets",
    ],
)
def test_a_decomposition_call_answered_by_any_other_name_or_none_is_a_mismatch(
    answered: frozenset[str],
) -> None:
    cause, said, plan, _, _ = _judged(answered)
    assert (cause, plan) == ("model_mismatch", None)
    shown = sorted(answered - {SYNTHETIC})
    assert said == f"asked for {PLANNER}, answered by {shown}"
