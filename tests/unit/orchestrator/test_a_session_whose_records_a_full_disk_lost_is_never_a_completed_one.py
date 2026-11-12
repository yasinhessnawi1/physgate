"""A session whose own records a full disk lost is named for that, never read as completed.

Measured on 2.1.322 with the session's transcript directory on a full volume: the result
event says ``completed``, the exit status is 0, and one more event follows the result,
saying what could not be saved and why. 2.1.301 loses the same writes and says nothing,
so there is nothing to read on it. Where the binary says it, the decomposition call gives
no plan (its own cause), and a review is infrastructure with the loss named, never a
verdict. What the stream says is read against a closed list: nothing of it is repeated.

The streams are the measured events; the decomposition call runs a stand-in binary.
"""

from __future__ import annotations

import json
import stat
import sys
from pathlib import Path
from typing import Any

import pytest
from orch_helpers import make_config

import physgate.orchestrator.decompose as decompose
from physgate.orchestrator.budget import writes_lost
from physgate.orchestrator.credentials import Credential
from physgate.orchestrator.decompose import judge, read_stream
from physgate.reviewers.claude import unavailable_end

NODE: dict[str, Any] = {
    "id": "power.bus",
    "kind": "interface",
    "domain": "electrical",
    "owner_role": "electrical",
    "quantities": {"v": {"value": 12, "unit": "V", "source": "brief", "written_by": "electrical"}},
    "requirements": [],
    "constrains": [],
    "model": None,
    "geometry_hash": "sha256:0",
    "updated": "2026-09-26T00:00:00Z",
}
PLAN = {
    "modules": [
        {"name": "power", "role": "electrical", "module_dir": "modules/power", "spec": "do it"}
    ],
    "interface_nodes": [NODE],
}
MODEL = "claude-sonnet-5"
SESSION = "2da87ae5-5fde-4ac4-a5a5-013abf528784"
ANSWER = {"type": "assistant", "message": {"id": "m1", "model": MODEL, "content": []}}
RESULT = {
    "type": "result",
    "subtype": "success",
    "is_error": False,
    "terminal_reason": "completed",
    "api_error_status": None,
    "num_turns": 2,
    "structured_output": PLAN,
}
#: The event as 2.1.322 wrote it after its result (measured; the two ids are the run's own).
LOST = {
    "type": "system",
    "subtype": "session_writes_lost",
    "error_code": "ENOSPC",
    "lost": ["transcript"],
    "transcript_session_ids": [SESSION],
    "uuid": "0a37ef0a-4f10-4967-bafb-d35df17b58a4",
    "session_id": SESSION,
}


def stream(*events: dict[str, Any]) -> str:
    return "".join(json.dumps(event) + "\n" for event in events)


SAVED = stream(ANSWER, RESULT)
NOT_SAVED = stream(ANSWER, RESULT, LOST)


def test_the_binary_s_word_that_it_could_not_save_its_records_is_read_from_the_stream() -> None:
    assert writes_lost(NOT_SAVED) == "transcript (ENOSPC)"
    assert writes_lost(SAVED) is None
    assert writes_lost("") is None
    both = {**LOST, "error_code": "EDQUOT", "lost": ["transcript", "global_config"]}
    assert writes_lost(stream(ANSWER, RESULT, both)) == "transcript, global_config (EDQUOT)"


def test_only_the_binary_s_own_event_counts_and_nothing_of_it_is_repeated() -> None:
    # The same words inside a tool's output are one string of another event, not an event.
    quoted = {
        "type": "user",
        "message": {"content": [{"type": "tool_result", "content": json.dumps(LOST)}]},
    }
    assert writes_lost(stream(ANSWER, quoted, RESULT)) is None
    assert writes_lost(stream(ANSWER, RESULT, {**LOST, "type": "assistant"})) is None
    assert writes_lost(stream(ANSWER, RESULT, {**LOST, "subtype": "status"})) is None
    # A value outside the binary's own list is not carried into a record.
    odd = {**LOST, "error_code": "rm -rf /", "lost": ["transcript", "x" * 500, 7]}
    assert writes_lost(stream(ANSWER, RESULT, odd)) == "transcript (a cause it did not name)"
    bare = {"type": "system", "subtype": "session_writes_lost"}
    assert writes_lost(stream(RESULT, bare)) == "records (a cause it did not name)"


def _judged(text: str) -> tuple[str | None, str, object]:
    result, _, answered = read_stream(text)
    cause, detail, plan, _, _ = judge(
        result,
        exit_code=0,
        timed_out=False,
        model=MODEL,
        roles=["electrical"],
        answered=answered,
        lost=writes_lost(text),
    )
    return cause, detail, plan


def test_a_decomposition_whose_records_were_lost_gives_no_plan_and_says_why() -> None:
    cause, detail, plan = _judged(NOT_SAVED)
    assert cause == "writes_lost" and plan is None
    assert "transcript (ENOSPC)" in detail
    cause, _, plan = _judged(SAVED)
    assert cause is None and plan is not None


def test_a_call_that_failed_for_another_reason_keeps_that_reason() -> None:
    overloaded = {**RESULT, "is_error": True, "terminal_reason": "api_error"}
    result, _, answered = read_stream(stream(ANSWER, overloaded, LOST))
    cause = judge(
        result,
        exit_code=1,
        timed_out=False,
        model=MODEL,
        roles=["electrical"],
        answered=answered,
        lost="transcript (ENOSPC)",
    )[0]
    assert cause == "api_error"


STANDIN = r"""
import sys
args = sys.argv[1:]
if args == ["--version"]:
    print("2.1.322 (Claude Code)")
    sys.exit(0)
sys.stdout.write(STREAM)
sys.exit(0)
"""


def _call(tmp_path: Path, monkeypatch: pytest.MonkeyPatch, text: str) -> decompose.Outcome:
    binary = tmp_path / "bin" / "claude"
    binary.parent.mkdir(parents=True)
    binary.write_text(f"#!{sys.executable}\nSTREAM = {text!r}\n{STANDIN}")
    binary.chmod(binary.stat().st_mode | stat.S_IXUSR)
    monkeypatch.setenv("PHYSGATE_CLAUDE_BIN", str(binary))
    return decompose.call(
        "brief",
        config=make_config(claude_version="2.1.322"),
        workdir=tmp_path / "w",
        base_url=None,
        credential=Credential("api_key", "not-a-key"),
    )


def test_the_decomposition_call_reads_the_loss_from_its_own_stream(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    saved = _call(tmp_path / "saved", monkeypatch, SAVED)
    assert saved.ok and saved.plan is not None, saved.detail
    lost = _call(tmp_path / "lost", monkeypatch, NOT_SAVED)
    assert not lost.ok and lost.plan is None
    assert lost.cause == "writes_lost", lost.detail


def test_a_review_whose_records_were_lost_is_infrastructure_with_the_loss_named() -> None:
    result, _, _ = read_stream(NOT_SAVED)
    cut = unavailable_end(NOT_SAVED, result, exit_code=0, timed_out=False)
    assert cut is not None
    cause, detail = cut
    assert cause == "infrastructure"
    assert "could not save" in detail and "transcript (ENOSPC)" in detail
    result, _, _ = read_stream(SAVED)
    assert unavailable_end(SAVED, result, exit_code=0, timed_out=False) is None
