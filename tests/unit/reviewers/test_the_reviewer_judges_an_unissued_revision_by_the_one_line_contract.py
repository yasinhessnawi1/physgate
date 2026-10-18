"""The reviewer's own judgement of an answer holds a revision with no specification to one line.

The one-line contract has two homes: the schema the session is held to, and ``judge()``
after it. This test drives ``ClaudeReviewer.review`` itself, with the session replaced
by a stand-in whose structured answer reaches ``judge()`` as the binary would hand it
over. It skips the schema on purpose, so that only the production call's ``issued`` flag
stands between a Section 1 item answered "not evaluable" and a review blocked for want
of a specification.
"""

from __future__ import annotations

import copy
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest

import physgate.reviewers.claude as claude
from physgate.engines.claude_code import ClaudeCodeEngine
from physgate.orchestrator.credentials import Credential
from physgate.orchestrator.dispatch import Installed
from physgate.orchestrator.exceptions import ReviewUnavailableError
from physgate.orchestrator.run_config import RunBounds
from physgate.reviewers.claude import ClaudeReviewer, ReviewerSetup
from physgate.reviewers.contract import CONSISTENCY, WRAPPER
from physgate.reviewers.packet import SPEC_AS_ISSUED_NAME
from physgate.reviewers.rubric import load_rubric

REPO = Path(__file__).resolve().parents[3]
ROLE = "electrical"
MODEL = "claude-sonnet-5"
VERSION = "2.1.283"


def _answer(not_evaluable_item: bool) -> dict[str, Any]:
    items = load_rubric(REPO / "knowledge", ROLE).items
    clean = {
        "acceptance_criteria": "met",
        "domain_standards": "n/a",
        "antipatterns": "n/a",
        "reward_hacking": "not observed",
    }
    answer: dict[str, Any] = {
        "verdict": "accept",
        "finding": "the revision is consistent with the design it changes",
        "failing_item": None,
        "subject": None,
        "numeric_output": None,
        "items": {
            i.id: {"result": clean[i.section], "evidence": "design/nodes/n1.json: the node"}
            for i in items
        },
        "acceptance_criteria": [
            {"criterion": CONSISTENCY, "result": "met", "evidence": "design/nodes/n1.json"}
        ],
        "indicators": [],
        "spec_defects": [],
    }
    if not_evaluable_item:
        first = next(i.id for i in items if i.section == "acceptance_criteria")
        answer = copy.deepcopy(answer)
        answer["verdict"] = "blocked"
        answer["items"][first] = {"result": "not evaluable", "evidence": "no specification"}
        answer["spec_defects"] = [
            {"finding": "no specification was issued", "blocking": True, "item": first}
        ]
    return answer


def _review(tmp_path: Path, monkeypatch: pytest.MonkeyPatch, answer: dict[str, Any]) -> object:
    """``review`` of a packet with no specification as issued, the session stood in for."""
    read = tmp_path / "rs" / "review" / "read"
    read.mkdir(parents=True)
    assert not (read / SPEC_AS_ISSUED_NAME).exists()
    packet = SimpleNamespace(read_root=str(read), indicators=(), sha256=lambda: "0" * 64)
    stdout = tmp_path / "stdout.jsonl"
    stdout.write_text("")
    result = {"type": "result", "is_error": False, "structured_output": {WRAPPER: answer}}
    captured = SimpleNamespace(result=result, usage=(), answered={MODEL}, tampered=None)
    monkeypatch.setattr(claude, "binary_version", lambda binary: VERSION)
    monkeypatch.setattr(claude, "review_dir", lambda root, sid: tmp_path / "rs" / "review")
    monkeypatch.setattr(ClaudeReviewer, "_prepare", lambda self, review, a, sid: packet)
    monkeypatch.setattr(
        ClaudeReviewer,
        "_install",
        lambda self, p, sdir: Installed(settings="s", config="c", spawn_args=(), spawn_env={}),
    )
    monkeypatch.setattr(ClaudeReviewer, "_spawn", lambda self, *a, **k: (stdout, 0, False))
    monkeypatch.setattr(claude, "review_prompt", lambda *a, **k: "p")
    # The session's harness side, stood in for: its credential's removal, its stream, its account.
    monkeypatch.setattr(ClaudeCodeEngine, "release", lambda *a: None)
    monkeypatch.setattr(ClaudeCodeEngine, "stream", lambda self, path: captured)
    monkeypatch.setattr(ClaudeCodeEngine, "cost", lambda self, c: c.usage)
    monkeypatch.setattr(claude, "unavailable_end", lambda *a, **k: None)
    monkeypatch.setattr(claude, "read_in_full", lambda *a: True)
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
    )
    reviewer = ClaudeReviewer(role=ROLE, setup=setup, rubric=load_rubric(REPO / "knowledge", ROLE))
    return reviewer.review(SimpleNamespace())  # type: ignore[arg-type]


def test_a_section_1_item_not_evaluable_with_no_specification_is_no_verdict(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    with pytest.raises(ReviewUnavailableError) as refused:
        _review(tmp_path, monkeypatch, _answer(not_evaluable_item=True))
    assert refused.value.cause == "invalid_verdict"


def test_the_one_consistency_line_with_no_specification_is_a_verdict(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The stand-in session refuses nothing on its own: a well-formed answer is a review."""
    result = _review(tmp_path, monkeypatch, _answer(not_evaluable_item=False))
    assert getattr(result, "verdict", None) == "pass"
