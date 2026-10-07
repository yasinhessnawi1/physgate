"""With the real reviewer registered, gate-failed work never reaches it and costs no review.

The loop's ordering, re-proved with the Claude reviewer in the review stage rather
than a fake: its binary is a stand-in that records every call. Three attempts the
gate fails never call it, never prepare a review, and spend no review token. The
control: an attempt the gate passes does reach it.
"""

from __future__ import annotations

import stat
from pathlib import Path
from typing import Any, cast

import pytest
from loop_fakes import FakeGate, Rig, plan
from orch_helpers import make_config

from physgate.orchestrator.accounting import TokenAccount
from physgate.orchestrator.credentials import Credential
from physgate.orchestrator.events import ReviewRan, ReviewUnavailable, read_events
from physgate.reviewers.claude import ClaudeReviewer
from physgate.reviewers.rubric import Rubric

pytestmark = pytest.mark.injected


def _reviewer(tmp_path: Path) -> tuple[ClaudeReviewer, Path]:
    calls = tmp_path / "calls.txt"
    binary = tmp_path / "bin" / "claude"
    binary.parent.mkdir()
    binary.write_text(f'#!/bin/sh\necho "$@" >> {calls}\necho "2.1.272 (Claude Code)"\n')
    binary.chmod(binary.stat().st_mode | stat.S_IXUSR)
    reviewer = ClaudeReviewer(
        role="electrical",
        config=make_config(),
        rubric=Rubric(role="electrical", text="r", sha256="0" * 64),
        library=tmp_path / "harness",
        review_root=tmp_path / "rs",
        repo=tmp_path / "target",
        install_bin=tmp_path / "install" / "bin" / "physgate",
        binary=str(binary),
        base_url=None,
        credential=Credential(mode="api_key", secret="not-a-key"),
    )
    return reviewer, calls


def _run(tmp_path: Path, verdicts: list[str]) -> tuple[Path, list[Any]]:
    reviewer, calls = _reviewer(tmp_path)
    rig = Rig(tmp_path / "run", gate=FakeGate(verdicts=verdicts), reviewer=cast(Any, reviewer))
    rig.run_dir.mkdir()
    loop = rig.open()
    loop.start(plan("s1"))
    loop.run()
    loop.close()
    return calls, read_events(rig.run_dir / "events.jsonl")


def test_three_gate_failed_attempts_never_call_the_reviewer_s_binary(tmp_path: Path) -> None:
    calls, events = _run(tmp_path, ["fail", "fail", "fail"])
    assert not calls.exists(), calls.read_text()
    assert not (tmp_path / "rs").exists()
    assert not [e for e in events if isinstance(e, ReviewRan | ReviewUnavailable)]
    assert TokenAccount.from_events(events).by_kind()["reviewer"].total() == 0


def test_an_attempt_the_gate_passes_reaches_the_reviewer(tmp_path: Path) -> None:
    calls, events = _run(tmp_path, ["pass"])
    assert calls.read_text().startswith("--version")
    assert [e for e in events if isinstance(e, ReviewRan | ReviewUnavailable)]
