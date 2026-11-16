"""Against every pinned binary: a review under ``review_compaction: on`` that compacts, end to end.

The real binary under the hook layer's reviewer profile, at the scripted endpoint, driven past
its compaction trigger by the last required read; it then reads the rubric again, as the note
after a compaction tells it to, and gives its verdict. The compaction call's own usage is in the
binary's totals and in no message of its stream (measured on both pins), so the review's account
holds it as one line of its own, marked as a compaction, and a repair resume of the same session
does not count it again.

The run-level guard (``COMPACTION_MEASURED_PINS``) is not on this path: the reviewer is built
directly, as every real-binary review row builds it.
"""

from __future__ import annotations

import dataclasses
import json
import os
from pathlib import Path
from typing import Any

import pytest
from compaction_session import COMPACT_USAGE, SUMMARY, CompactingApi, serving, usage_of
from knowledge_fixture import write_fixture
from scripted_endpoint import DUMMY_KEY, Script, text, tool
from test_a_claude_review_is_a_verdict_only_when_it_read_everything import (
    RUBRIC,
    _attempt,
    _config,
    _reading,
    verdict,
)

from physgate.orchestrator.credentials import Credential
from physgate.orchestrator.decompose import binary_version, read_stream
from physgate.orchestrator.install import prepare_install
from physgate.orchestrator.protocols import MessageUsage, ReviewResult
from physgate.reviewers.claude import ClaudeReviewer, ReviewerSetup

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

#: A context past the trigger on every pin, as the last read reports it.
PAST = 999_000
FIELDS = ("input_tokens", "output_tokens", "cache_read_input_tokens", "cache_creation_input_tokens")
KEYS = ("inputTokens", "outputTokens", "cacheReadInputTokens", "cacheCreationInputTokens")


@pytest.fixture(scope="module")
def install(tmp_path_factory: pytest.TempPathFactory) -> Path:
    return prepare_install(
        tmp_path_factory.mktemp("install") / "i", Path(__file__).resolve().parents[3]
    )


@pytest.fixture(params=BINARIES, ids=lambda b: Path(b).name)
def binary(request: pytest.FixtureRequest) -> str:
    return str(request.param)


def _invalid() -> dict[str, Any]:
    """A verdict the schema takes and the check after the session refuses: a one-word finding."""
    return {**verdict(), "finding": "test"}


def _review(
    tmp_path: Path,
    install: Path,
    binary: str,
    answers: list[dict[str, Any]],
    *,
    repair_resumes: int = 0,
) -> tuple[ReviewResult | Exception, Path]:
    """One review driven past its trigger; its outcome and its session directory.

    Every required file is read, the last read past the trigger; then the rubric is read again
    and ``answers`` are given in turn.
    """
    library = tmp_path / "harness"
    write_fixture(library, ("cross", "control"))
    attempt = _attempt(tmp_path)
    config = _config(binary_version(binary)).model_copy(update={"review_compaction": "on"})
    api = CompactingApi(Script(main=[]), SUMMARY)
    plan: list[dict[str, Any]] = []

    def step(_thread: str, cwd: str, _done: int) -> dict[str, Any]:
        if not plan:
            reading = _reading(cwd)
            reads = [tool("Read", file_path=p) for p in reading]
            reads[-1] = {**reads[-1], "usage": usage_of(PAST)}
            again = [tool("Read", file_path=p) for p in reading if p.endswith("rubric.md")]
            plan.extend([*reads, *again, *(tool("StructuredOutput", review=a) for a in answers)])
            plan.append(text("done"))
        return plan.pop(0) if len(plan) > 1 else plan[0]

    api.on_request = step
    with serving(api) as url:
        setup = ReviewerSetup.of_run(
            config,
            review_root=tmp_path / "rs",
            repo=Path(attempt.worktree),
            install_bin=install,
            binary=binary,
            base_url=url,
            credential=Credential(mode="api_key", secret=DUMMY_KEY),
            library=library,
        )
        setup = dataclasses.replace(setup, repair_resumes=repair_resumes)
        reviewer = ClaudeReviewer(role="control", rubric=RUBRIC, setup=setup)
        try:
            outcome: ReviewResult | Exception = reviewer.review(attempt)
        except Exception as exc:  # noqa: BLE001 - what the review raised is what is measured
            outcome = exc
    (session,) = sorted((tmp_path / "rs").glob("*/session"))
    assert api.compaction_requests, "the review was not driven past its compaction trigger"
    return outcome, session


def _totals(stream: Path) -> dict[str, int]:
    result, _, _ = read_stream(stream.read_text())
    (model,) = ((result or {}).get("modelUsage") or {}).values()
    return {f: int(model[k]) for f, k in zip(FIELDS, KEYS, strict=True)}


def _summed(usage: tuple[MessageUsage, ...]) -> dict[str, int]:
    return {f: sum(int(getattr(m.usage, f)) for m in usage) for f in FIELDS}


def _marked(usage: tuple[MessageUsage, ...]) -> list[MessageUsage]:
    return [m for m in usage if getattr(m, "compaction", False)]


def test_a_review_that_compacts_reaches_its_verdict_with_the_compaction_counted_once(
    tmp_path: Path, install: Path, binary: str
) -> None:
    outcome, session = _review(tmp_path, install, binary, [verdict()])
    assert isinstance(outcome, ReviewResult), repr(outcome)
    assert outcome.verdict == "pass" and outcome.compactions == 1
    assert len(outcome.compaction_pre_tokens) == 1
    (line,) = _marked(outcome.usage)
    assert {f: int(getattr(line.usage, f)) for f in FIELDS} == {f: COMPACT_USAGE[f] for f in FIELDS}
    # With the line, the review's account is the binary's own totals, each token once.
    assert _summed(outcome.usage) == _totals(session / "stdout.jsonl")


def test_a_repair_resume_after_a_compaction_does_not_count_it_again(
    tmp_path: Path, install: Path, binary: str
) -> None:
    outcome, session = _review(tmp_path, install, binary, [_invalid(), verdict()], repair_resumes=1)
    assert isinstance(outcome, ReviewResult), repr(outcome)
    assert outcome.verdict == "pass" and outcome.compactions == 1
    assert outcome.repair_resumes == 1
    # One compaction line across both invocations; the resumed invocation's totals are the
    # whole session's, and the account matches them.
    assert len(_marked(outcome.usage)) == 1
    assert _summed(outcome.usage) == _totals(session / "stdout-repair-1.jsonl")
    # The record keeps the mark, and only on the compaction's line.
    dumped = [json.loads(m.model_dump_json()) for m in outcome.usage]
    assert sum(1 for d in dumped if d.get("compaction") is True) == 1
    assert all("compaction" not in d for d in dumped if not d.get("compaction"))
