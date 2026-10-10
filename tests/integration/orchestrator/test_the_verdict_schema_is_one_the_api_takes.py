"""The verdict schema a review offers is one the API takes, and one the binary compiles cleanly.

The second real paired run failed before any review began: the API refused the verdict
schema on the first request of every review, because it had ``allOf`` at its top level,
and the binary warned of hundreds of untyped subschemas as it compiled it. The scripted
endpoint now refuses what the API refuses, with the API's own message, so a dry run fails
the way that run did.

Replayed here, through the real binary: the second run's exact schema (``replayed/``) is
refused on the first request, and the review is unavailable for infrastructure; the
schema the reviewer generates now is taken, the review is a verdict, and the binary's
stderr holds no strict-mode line. A strict-mode line on stderr fails a review test.
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
from test_the_first_real_reviews_replay_as_they_ended import valid

import physgate.reviewers.claude as claude
from physgate.orchestrator.credentials import Credential
from physgate.orchestrator.decompose import binary_version
from physgate.orchestrator.exceptions import ReviewUnavailableError
from physgate.orchestrator.install import prepare_install
from physgate.orchestrator.protocols import ReviewResult
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
#: The API's own refusal, as the second real run recorded it.
REFUSAL = (
    "tools.1.custom.input_schema: input_schema does not support oneOf, allOf, or anyOf at the "
    "top level"
)
STRICT_MODE = "strict mode"


@pytest.fixture(scope="module")
def install(tmp_path_factory: pytest.TempPathFactory) -> Path:
    return prepare_install(tmp_path_factory.mktemp("install") / "i", REPO)


@pytest.fixture(params=BINARIES, ids=lambda b: Path(b).name)
def binary(request: pytest.FixtureRequest) -> str:
    return str(request.param)


def _review(
    tmp_path: Path, install: Path, binary: str, role: str
) -> tuple[ReviewResult | Exception, list[str], str]:
    """One review: what it came to, what the endpoint refused, and the binary's stderr."""
    rubric = load_rubric(REPO / "knowledge", role)
    attempt = _attempt(tmp_path).model_copy(update={"assigned_role": role})
    pins = ModelStrings(
        decomposition="claude-sonnet-5",
        roles={role: "claude-opus-5-5"},
        reviewers={role: "claude-sonnet-5"},
    )
    config = _config(binary_version(binary)).model_copy(update={"models": pins})
    corrected = valid(rubric.items)

    def step(_thread: str, cwd: str, done: int) -> dict[str, Any]:
        steps = [tool("Read", file_path=p) for p in _reading(cwd)]
        steps.append(tool("StructuredOutput", review=corrected))
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
        outcome: ReviewResult | Exception
        try:
            outcome = ClaudeReviewer(role=role, setup=setup, rubric=rubric).review(attempt)
        except ReviewUnavailableError as exc:
            outcome = exc
        refused = list(api.refusals)
    (stderr,) = [p.read_text() for p in (tmp_path / "rs").glob("*/session/stderr.txt")]
    return outcome, refused, stderr


@pytest.mark.parametrize("role", ["control", "firmware"])
def test_the_second_real_run_s_schema_is_refused_on_the_first_request(
    tmp_path: Path,
    install: Path,
    binary: str,
    role: str,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    sent = json.loads((REPLAYED / f"v2_schema_{role}.json").read_text())
    monkeypatch.setattr(claude, "verdict_schema", lambda *a, **k: sent)
    outcome, refused, stderr = _review(tmp_path, install, binary, role)
    assert refused == [REFUSAL]  # one request, refused as the API refused it
    assert isinstance(outcome, ReviewUnavailableError) and outcome.cause == "infrastructure"
    assert STRICT_MODE in stderr  # and the binary warned as it compiled it


@pytest.mark.parametrize("role", ["control", "firmware"])
def test_the_schema_generated_now_is_taken_and_compiles_without_a_warning(
    tmp_path: Path, install: Path, binary: str, role: str
) -> None:
    outcome, refused, stderr = _review(tmp_path, install, binary, role)
    assert refused == []
    assert isinstance(outcome, ReviewResult) and outcome.verdict == "pass"
    assert STRICT_MODE not in stderr, [x for x in stderr.splitlines() if STRICT_MODE in x][:3]


def test_the_pre_flight_takes_today_s_schema_and_would_have_refused_the_second_run_s(
    tmp_path: Path, binary: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The cheap check run before a real paired run, here on the scripted endpoint."""
    import real_paired_reviewers as driver
    from scripted_endpoint import DUMMY_OAUTH_TOKEN

    monkeypatch.setenv("PHYSGATE_CLAUDE_BIN", binary)
    sent: dict[str, dict[str, Any]] = {
        role: json.loads((REPLAYED / f"v2_schema_{role}.json").read_text())
        for role in ("control", "firmware")
    }

    def second_run_s(items: Any, **_: Any) -> dict[str, Any]:  # noqa: ANN401
        return sent["control" if items[0].id == "A1" else "firmware"]

    with serving(Script(main=[text("done")])) as (_, url):
        today = driver.preflight(tmp_path / "now", DUMMY_OAUTH_TOKEN, url)
        monkeypatch.setattr(driver, "verdict_schema", second_run_s)
        then = driver.preflight(tmp_path / "then", DUMMY_OAUTH_TOKEN, url)

        def nested_but_untyped(items: Any, **kw: Any) -> dict[str, Any]:  # noqa: ANN401
            inner = second_run_s(items, **kw)
            return {"type": "object", "required": ["review"], "properties": {"review": inner}}

        monkeypatch.setattr(driver, "verdict_schema", nested_but_untyped)
        untyped = driver.preflight(tmp_path / "untyped", DUMMY_OAUTH_TOKEN, url)
    assert today["all_accepted"] is True
    assert all(today[r]["strict_mode_warnings"] == 0 for r in ("control", "firmware"))
    assert then["all_accepted"] is False
    assert all(then[r]["refused_400"] for r in ("control", "firmware"))
    assert all("at the top level" in str(then[r]["api_error"]) for r in ("control", "firmware"))
    # Taken by the API, but compiled with strict-mode warnings: not accepted either.
    assert untyped["all_accepted"] is False
    assert all(not untyped[r]["refused_400"] for r in ("control", "firmware"))
    assert all(untyped[r]["strict_mode_warnings"] > 0 for r in ("control", "firmware"))
