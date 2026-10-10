"""The third real control review's submission, replayed through the binary: a blocked review.

The real control reviewer read everything and submitted ``blocked``: the stand-in brief
dictates one literal node and gives none of the inputs the rubric's safety-critical checks
need. The binary accepted the submission and the reviewer recorded no refusal, but the
harness then logged it as a review with no verdict. Replayed here against the same brief
and the same promoted control rubric, the reviewer returns it as what it is, a review whose
verdict is blocked, with every item, every criterion line and every defect it sent. How the
loop routes that result is the unit replay's to show, on the same submission.
"""

from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any

import pytest
import test_a_claude_review_is_a_verdict_only_when_it_read_everything as reading
from real_domain_roles import CONTROL_SPEC
from scripted_endpoint import DUMMY_KEY, Script, serving, text, tool

from physgate.orchestrator.credentials import Credential
from physgate.orchestrator.decompose import binary_version
from physgate.orchestrator.install import prepare_install
from physgate.reviewers.claude import ClaudeReviewer, ReviewerSetup
from physgate.reviewers.rubric import load_rubric

BINARIES = [
    b
    for b in (
        os.environ.get("PHYSGATE_PINNED_BINS") or os.environ.get("PHYSGATE_CLAUDE_BIN") or ""
    ).split(os.pathsep)
    if b
]
pytestmark = [
    pytest.mark.integration,
    pytest.mark.skipif(not BINARIES, reason="no pinned Claude Code binary named on this machine"),
]

REPO = Path(__file__).resolve().parents[3]
SUBMISSION = Path(__file__).resolve().parent / "replayed" / "review_submission_v3_control.json"
REFUSED = "Output does not match required schema"


@pytest.fixture(scope="module")
def install(tmp_path_factory: pytest.TempPathFactory) -> Path:
    return prepare_install(tmp_path_factory.mktemp("install") / "i", REPO)


@pytest.fixture(params=BINARIES, ids=lambda b: Path(b).name)
def binary(request: pytest.FixtureRequest) -> str:
    return str(request.param)


def test_the_real_blocked_submission_is_a_review_whose_verdict_is_blocked(
    tmp_path: Path, install: Path, binary: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    submitted = json.loads(SUBMISSION.read_text())
    # The brief the real control session was issued, as the attempt's issued specification.
    monkeypatch.setattr(reading, "ISSUED", CONTROL_SPEC)
    attempt = reading._attempt(tmp_path)
    rubric = load_rubric(REPO / "knowledge", "control")
    config = reading._config(binary_version(binary))

    def step(_thread: str, cwd: str, done: int) -> dict[str, Any]:
        steps = [tool("Read", file_path=p) for p in reading._reading(cwd)]
        steps.append(tool("StructuredOutput", review=submitted))
        return steps[done] if done < len(steps) else text("done")

    with serving(Script(main=[])) as (api, url):
        api.on_request = step
        setup = ReviewerSetup.of_run(
            config,
            review_root=tmp_path / "rs",
            repo=Path(attempt.worktree),
            install_bin=install,
            binary=binary,
            base_url=url,
            credential=Credential(mode="api_key", secret=DUMMY_KEY),
            library=REPO,
        )
        result = ClaudeReviewer(role="control", setup=setup, rubric=rubric).review(attempt)
        told = [r.last_user for r in api.requests]
    assert not [t for t in told if t.startswith(REFUSED)]
    assert result.verdict == "blocked" and result.schema_refusals == 0
    assert result.failing_item is None and result.finding == submitted["finding"]
    assert result.rubric_kind == "paired" and result.rubric_sha256 == rubric.sha256
    assert len(result.items) == len(rubric.items) == len(submitted["items"])
    assert len(result.criteria) == len(submitted["acceptance_criteria"])
    assert [d.finding for d in result.spec_defects] == [
        d["finding"] for d in submitted["spec_defects"]
    ]
    assert sum(d.blocking for d in result.spec_defects) == sum(
        d["blocking"] for d in submitted["spec_defects"]
    )
