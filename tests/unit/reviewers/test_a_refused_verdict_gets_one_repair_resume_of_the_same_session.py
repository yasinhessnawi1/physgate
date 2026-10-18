"""A review whose verdict was refused is resumed once, the same session, told why.

The binary's cap on refused structured answers, or the check after the session, ends a
review with no verdict; on the injected-error instrument that is one item lost from the
count. With repair resumes on, the same session is resumed once with the check's own
reason, so the reviewer answers what it already read; it is the same review, counted on
its line. Any other end is never resumed, and resumes are off unless the run says so.
The session is stood in for: what each invocation's stream would hold is scripted.
"""

from __future__ import annotations

import copy
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest
from test_the_reviewer_judges_an_unissued_revision_by_the_one_line_contract import (
    MODEL,
    REPO,
    ROLE,
    VERSION,
    _answer,
)

import physgate.reviewers.claude as claude
from physgate.orchestrator.credentials import Credential
from physgate.orchestrator.dispatch import Installed
from physgate.orchestrator.exceptions import ReviewUnavailableError
from physgate.orchestrator.protocols import ReviewResult
from physgate.orchestrator.run_config import RunBounds
from physgate.reviewers.claude import ClaudeReviewer, ReviewerSetup
from physgate.reviewers.contract import WRAPPER
from physgate.reviewers.rubric import load_rubric

INVALID = _answer(not_evaluable_item=True)  # a Section 1 item "not evaluable": refused
VALID = _answer(not_evaluable_item=False)


def _accept_with_a_bad_failing_item() -> dict[str, Any]:
    answer = copy.deepcopy(VALID)
    answer["failing_item"] = "no-such-item"
    return answer


def _review(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    sessions: list[tuple[dict[str, Any] | None, tuple[str, str] | None]],
    repairs: int,
) -> tuple[object, list[dict[str, Any]], list[str]]:
    """Review with each invocation's answer, or its end, scripted in order."""
    read = tmp_path / "rs" / "review" / "read"
    read.mkdir(parents=True)
    packet = SimpleNamespace(read_root=str(read), indicators=(), sha256=lambda: "0" * 64)
    spawns: list[dict[str, Any]] = []
    rewritten: list[str] = []
    streams: dict[Path, int] = {}

    def spawn(self: object, *args: object, **kwargs: Any) -> tuple[Path, int, bool]:  # noqa: ANN401
        spawns.append(kwargs)
        path = tmp_path / f"stream-{len(spawns)}.jsonl"
        path.write_text("")
        streams[path] = len(spawns) - 1
        return path, 0, False

    def captured(path: Path) -> object:
        answer, _ = sessions[streams[path]]
        result = {"type": "result", "structured_output": {WRAPPER: answer}}
        return SimpleNamespace(result=result, usage=(), answered={MODEL}, tampered=None)

    def ended(text: str, result: object, **kwargs: object) -> tuple[str, str] | None:
        return sessions[len(spawns) - 1][1]

    monkeypatch.setattr(claude, "binary_version", lambda binary: VERSION)
    monkeypatch.setattr(claude, "review_dir", lambda root, sid: tmp_path / "rs" / "review")
    monkeypatch.setattr(ClaudeReviewer, "_prepare", lambda self, review, a, sid: packet)
    monkeypatch.setattr(
        ClaudeReviewer,
        "_install",
        lambda self, p, sdir: Installed(settings="s", config="c", spawn_args=(), spawn_env={}),
    )
    monkeypatch.setattr(ClaudeReviewer, "_spawn", spawn)
    monkeypatch.setattr(claude, "review_prompt", lambda *a, **k: "p")
    monkeypatch.setattr(claude, "remove_secrets", lambda *a: None)
    monkeypatch.setattr(claude, "redact", lambda *a: None)
    monkeypatch.setattr(claude, "read_captured", captured)
    monkeypatch.setattr(claude, "require_matching_totals", lambda *a: None)
    monkeypatch.setattr(claude, "unavailable_end", ended)
    monkeypatch.setattr(claude, "read_in_full", lambda *a: True)
    monkeypatch.setattr(claude, "write_key_helper", lambda state, key: rewritten.append(str(state)))
    setup = ReviewerSetup(
        run_id="run-1",
        models={ROLE: MODEL},
        claude_version=VERSION,
        bounds=RunBounds(
            binary_max_retries=0,
            session_wall_clock_s=60.0,
            session_max_turns=20,
            infra_retry_delays_s=(),
        ),
        effort="high",
        max_output_tokens=64000,
        token_ceiling=100_000,
        review_root=tmp_path / "rs",
        repo=None,
        install_bin=tmp_path / "install" / "bin" / "x",
        binary="claude",
        base_url=None,
        credential=Credential(mode="api_key", secret="not-a-key"),
        library=tmp_path / "harness",
        repair_resumes=repairs,
    )
    reviewer = ClaudeReviewer(role=ROLE, setup=setup, rubric=load_rubric(REPO / "knowledge", ROLE))
    try:
        return reviewer.review(SimpleNamespace()), spawns, rewritten  # type: ignore[arg-type]
    except ReviewUnavailableError as exc:
        return exc, spawns, rewritten


def test_a_verdict_the_check_refused_is_repaired_by_resuming_the_same_session_once(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    result, spawns, rewritten = _review(tmp_path, monkeypatch, [(INVALID, None), (VALID, None)], 1)
    assert isinstance(result, ReviewResult) and result.verdict == "pass"
    assert result.repair_resumes == 1
    assert [s.get("resume", False) for s in spawns] == [False, True]
    assert "Section 1" in spawns[1]["prompt"] or "not evaluable" in spawns[1]["prompt"]
    assert spawns[1]["stream_name"] == "stdout-repair-1.jsonl"
    assert len(rewritten) == 1  # the credential put back for the resumed invocation


def test_the_binary_s_cap_on_refused_answers_is_repaired_the_same_way(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    capped = ("invalid_verdict", "the binary's cap on refused verdicts ended it: no items")
    result, spawns, _ = _review(tmp_path, monkeypatch, [(None, capped), (VALID, None)], 1)
    assert isinstance(result, ReviewResult) and result.repair_resumes == 1
    assert "cap on refused verdicts" in spawns[1]["prompt"]


def test_a_second_refusal_is_no_verdict_and_says_it_followed_a_repair(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    bad = _accept_with_a_bad_failing_item()
    result, spawns, _ = _review(tmp_path, monkeypatch, [(INVALID, None), (bad, None)], 1)
    assert isinstance(result, ReviewUnavailableError) and result.cause == "invalid_verdict"
    assert "after 1 repair resume" in str(result) and len(spawns) == 2


def test_an_end_for_another_cause_is_never_resumed(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    outage = ("infrastructure", "the session ended with api_error")
    result, spawns, _ = _review(tmp_path, monkeypatch, [(None, outage), (VALID, None)], 1)
    assert isinstance(result, ReviewUnavailableError) and result.cause == "infrastructure"
    assert len(spawns) == 1


def test_with_repair_resumes_off_a_refused_verdict_ends_the_review_as_before(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    result, spawns, _ = _review(tmp_path, monkeypatch, [(INVALID, None), (VALID, None)], 0)
    assert isinstance(result, ReviewUnavailableError) and result.cause == "invalid_verdict"
    assert "repair" not in str(result) and len(spawns) == 1


def test_a_verdict_given_at_once_records_no_resume(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    on, _, _ = _review(tmp_path / "on", monkeypatch, [(VALID, None)], 1)
    off, _, _ = _review(tmp_path / "off", monkeypatch, [(VALID, None)], 0)
    assert isinstance(on, ReviewResult) and on.repair_resumes == 0
    assert isinstance(off, ReviewResult) and off.repair_resumes is None


def test_the_repair_message_holds_no_word_that_tells_the_reviewer_what_is_measured() -> None:
    from physgate.evaluation.inject.corpus import telltales

    assert telltales(claude.REPAIR) == []


def test_a_resumed_review_continues_its_session_and_a_fresh_one_names_it() -> None:
    from physgate.orchestrator.invocation import reviewer_argv

    common: dict[str, Any] = {
        "prompt": "p",
        "spawn_args": (),
        "schema": "{}",
        "model": MODEL,
        "session_id": "s-1",
        "max_turns": 20,
        "effort": "high",
    }
    fresh = reviewer_argv("claude", **common)
    resumed = reviewer_argv("claude", **common, resume=True)
    assert fresh[fresh.index("--session-id") + 1] == "s-1" and "--resume" not in fresh
    assert resumed[resumed.index("--resume") + 1] == "s-1" and "--session-id" not in resumed
