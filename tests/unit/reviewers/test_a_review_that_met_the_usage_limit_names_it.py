"""A review session that ended on the account's usage limit says so, with the reset it read.

The review is no verdict, as any infrastructure end is (its cause stays ``infrastructure``, so
every reader of that cause reads it as before). The loop is told the limit beside it, so it
does not retry the review inside the limit's window or send the attempt to a person: it waits.
A 503 carries no limit and is retried as today. The streams are stand-ins (see the loop's rows).
"""

from __future__ import annotations

import json
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest

import physgate.reviewers.claude as claude
from physgate.orchestrator.credentials import Credential
from physgate.orchestrator.dispatch import Installed
from physgate.orchestrator.exceptions import ReviewUnavailableError
from physgate.orchestrator.run_config import RunBounds
from physgate.orchestrator.usage_limit import UsageLimit
from physgate.reviewers.claude import ClaudeReviewer, ReviewerSetup
from physgate.reviewers.rubric import Rubric

MODEL = "claude-sonnet-5"
VERSION = "2.1.283"
LIMIT = "You've hit your session limit · resets 1:20pm (Europe/Oslo)"
OUTAGE = "API Error: 503 credential validation failed. This is usually temporary."


def _setup(tmp_path: Path) -> ReviewerSetup:
    return ReviewerSetup(
        run_id="run-1",
        models={"control": MODEL},
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
        held_out_canaries=(),
    )


def _review(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, text: str, status: str, error: str
) -> ReviewUnavailableError:
    read = tmp_path / "rs" / "review" / "read"
    read.mkdir(parents=True)
    packet = SimpleNamespace(read_root=str(read), indicators=(), sha256=lambda: "0" * 64)
    result: dict[str, Any] = {
        "type": "result",
        "subtype": "success",
        "is_error": True,
        "terminal_reason": "api_error",
        "result": text,
    }
    said = {
        "type": "assistant",
        "message": {"model": "<synthetic>", "content": [{"type": "text", "text": text}]},
        "error": error,
    }
    limit_state = {"type": "rate_limit_event", "rate_limit_info": {"status": status}}
    stdout = tmp_path / "stdout.jsonl"
    stdout.write_text("".join(json.dumps(e) + "\n" for e in (limit_state, said, result)))
    captured = SimpleNamespace(result=result, usage=(), answered={"<synthetic>"}, tampered=None)
    monkeypatch.setattr(claude, "binary_version", lambda binary: VERSION)
    monkeypatch.setattr(claude, "review_dir", lambda root, sid: tmp_path / "rs" / "review")
    monkeypatch.setattr(ClaudeReviewer, "_prepare", lambda self, review, a, sid: packet)
    monkeypatch.setattr(
        ClaudeReviewer,
        "_install",
        lambda *_a: Installed(settings="s", config="c", spawn_args=(), spawn_env={}),
    )
    monkeypatch.setattr(ClaudeReviewer, "_spawn", lambda self, *a, **k: (stdout, 1, False))
    monkeypatch.setattr(claude, "review_prompt", lambda *a, **k: "p")
    monkeypatch.setattr(claude, "remove_secrets", lambda *a: None)
    monkeypatch.setattr(claude, "redact", lambda *a: None)
    monkeypatch.setattr(claude, "read_captured", lambda path, data=None: captured)
    monkeypatch.setattr(claude, "require_matching_totals", lambda *a: None)
    monkeypatch.setattr(claude, "verdict_schema", lambda *a, **k: {})
    monkeypatch.setattr(claude, "contract_text", lambda *a, **k: "c")
    rubric = Rubric(role="control", text="r", sha256="0" * 64)
    reviewer = ClaudeReviewer(role="control", setup=_setup(tmp_path), rubric=rubric)
    try:
        reviewer.review(SimpleNamespace())  # type: ignore[arg-type]
    except ReviewUnavailableError as exc:
        return exc
    msg = "the review gave a verdict"
    raise AssertionError(msg)


def test_a_review_on_the_limit_is_no_verdict_and_names_the_limit_and_its_reset(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    raised = _review(tmp_path, monkeypatch, LIMIT, "rejected", "rate_limit")
    assert raised.cause == "infrastructure"
    assert raised.usage_limit == UsageLimit(resets="1:20pm (Europe/Oslo)")
    assert raised.session_id


def test_a_review_s_503_names_no_limit(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    raised = _review(tmp_path, monkeypatch, OUTAGE, "allowed", "server_error")
    assert raised.cause == "infrastructure"
    assert raised.usage_limit is None
