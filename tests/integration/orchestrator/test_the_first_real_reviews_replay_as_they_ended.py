"""The first real paired reviews' submissions, replayed on the scripted endpoint, end as they did.

Both real reviews read everything they had to and submitted one structured verdict, which the
binary accepted: the verdict schema it was offered constrains nothing about which items there
are or which results each section allows. The harness's own check then refused each one after
the session had ended, so the reviewer never saw why and never had a second turn. The control
review grouped items and answered the specification's criteria instead of the rubric's ids; the
firmware review did the same and used ``n/a`` for a reward-hacking item.

Each submission is kept as the model sent it (``replayed/``) and replayed here against the
promoted rubric of its role, through the real binary, so the failure's shape is reproduced
exactly: the binary accepts the submission, and the review ends with the same cause and the same
first problem the real run recorded. A fix must turn this into a refusal the reviewer sees in its
session.
"""

from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any

import pytest
from scripted_endpoint import DUMMY_KEY, Script, serving, text, tool
from test_a_claude_review_is_a_verdict_only_when_it_read_everything import (
    _attempt,
    _config,
    _reading,
)

from physgate.orchestrator.credentials import Credential
from physgate.orchestrator.decompose import binary_version
from physgate.orchestrator.exceptions import ReviewUnavailableError
from physgate.orchestrator.install import prepare_install
from physgate.orchestrator.run_config import ModelStrings
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
REPLAYED = Path(__file__).resolve().parent / "replayed"
#: What the real run recorded as each review's cause and first problem.
RECORDED = {
    "control": (
        "items.16: Value error, only a reward-hacking indicator is noted rather than confirmed"
    ),
    "firmware": (
        "items.9: Value error, an acceptance criterion or a reward-hacking indicator is never "
        "not applicable"
    ),
}


@pytest.fixture(scope="module")
def install(tmp_path_factory: pytest.TempPathFactory) -> Path:
    return prepare_install(tmp_path_factory.mktemp("install") / "i", REPO)


@pytest.fixture(params=BINARIES, ids=lambda b: Path(b).name)
def binary(request: pytest.FixtureRequest) -> str:
    return str(request.param)


@pytest.mark.parametrize("role", ["control", "firmware"])
def test_a_real_submission_is_accepted_by_the_binary_and_refused_only_after(
    tmp_path: Path, install: Path, binary: str, role: str
) -> None:
    submitted = json.loads((REPLAYED / f"review_submission_{role}.json").read_text())
    attempt = _attempt(tmp_path).model_copy(update={"assigned_role": role})
    pins = ModelStrings(
        decomposition="claude-sonnet-5",
        roles={role: "claude-opus-5-5"},
        reviewers={role: "claude-sonnet-5"},
    )
    config = _config(binary_version(binary)).model_copy(update={"models": pins})

    def step(_thread: str, cwd: str, done: int) -> dict[str, Any]:
        steps = [tool("Read", file_path=p) for p in _reading(cwd)]
        steps.append(tool("StructuredOutput", **submitted))
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
        reviewer = ClaudeReviewer(
            role=role, setup=setup, rubric=load_rubric(REPO / "knowledge", role)
        )
        with pytest.raises(ReviewUnavailableError) as raised:
            reviewer.review(attempt)
        told = [r.last_user for r in api.requests]
    assert raised.value.cause == "invalid_verdict"
    assert str(raised.value) == RECORDED[role]
    # The binary took the submission at once: the reviewer was never told anything was wrong.
    assert not any("does not match required schema" in t for t in told)
