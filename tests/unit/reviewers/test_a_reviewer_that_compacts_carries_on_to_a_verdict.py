"""A review that nears its window compacts and carries on, and still reaches a verdict (ARCH-060).

Under ``review_compaction: on`` a compaction boundary in the stream no longer ends the review:
the verdict it then gives is a verdict, recorded with how many compactions came before it and
the context size before each. A review that compacted and still outgrew its window reached no
verdict, as before, and its line says how many compactions came first. Under ``off`` a
compaction is ``compacted``, exactly as before the flag.

The hook layer records each compaction it was told of; the stream's count is held to the hook's
records, and a difference either way is no verdict (``reading_incomplete``): a compaction the
hook layer did not see is one after which nothing showed the rubric was read again.

**Stand-in stream.** The streams here are built from the shapes the code's own records give for
a compaction (``{"type": "system", "subtype": "compact_boundary"}``, measured on both pins) and
from the boundary's ``compact_metadata`` (``trigger``, ``pre_tokens``), which the real-binary row
B1 is owed to confirm on each pin; B1's recorded stream replaces them when it runs.
"""

from __future__ import annotations

import inspect
import json
from dataclasses import fields, replace
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest
from test_the_reviewer_judges_an_unissued_revision_by_the_one_line_contract import (
    MODEL,
    REPO,
    ROLE,
    _answer,
)

import physgate.reviewers.claude as claude
from physgate.orchestrator.credentials import Credential
from physgate.orchestrator.dispatch import Installed
from physgate.orchestrator.exceptions import ReviewUnavailableError
from physgate.orchestrator.protocols import ReviewResult
from physgate.orchestrator.run_config import RunBounds
from physgate.reviewers.claude import ClaudeReviewer, ReviewerSetup, unavailable_end
from physgate.reviewers.contract import WRAPPER
from physgate.reviewers.rubric import load_rubric

#: A pin on which a reviewer's compaction was measured: a reviewer is refused ``on`` elsewhere.
VERSION = "2.1.301"
VALID = _answer(not_evaluable_item=False)
INVALID = _answer(not_evaluable_item=True)
COMPLETED = {"type": "result", "is_error": False, "terminal_reason": "completed"}
REFILLED = {"type": "result", "is_error": True, "terminal_reason": "rapid_refill_breaker"}


def boundary(pre_tokens: int | None = 900_000) -> dict[str, Any]:
    """A compaction boundary, in the shape B1 is owed to confirm (a stand-in)."""
    metadata: dict[str, Any] = {"trigger": "auto"}
    if pre_tokens is not None:
        metadata["pre_tokens"] = pre_tokens
    return {"type": "system", "subtype": "compact_boundary", "compact_metadata": metadata}


def _lines(*events: dict[str, Any]) -> str:
    return "".join(json.dumps(e) + "\n" for e in events)


def _allows_compaction() -> None:
    assert "compaction" in inspect.signature(unavailable_end).parameters, (
        "the session's end is read without the run's review_compaction"
    )


# --- the session's end ------------------------------------------------------------------------


def test_a_compaction_where_the_run_allows_it_is_not_an_end() -> None:
    _allows_compaction()
    text = _lines(boundary(), COMPLETED)
    assert unavailable_end(text, COMPLETED, exit_code=0, timed_out=False, compaction="on") is None


def test_under_off_or_unsaid_a_compaction_is_compacted_as_before() -> None:
    _allows_compaction()
    text = _lines(boundary(), COMPLETED)
    off = unavailable_end(text, COMPLETED, exit_code=0, timed_out=False, compaction="off")
    assert off is not None and off[0] == "compacted"
    unsaid = unavailable_end(text, COMPLETED, exit_code=0, timed_out=False)
    assert unsaid is not None and unsaid[0] == "compacted"


def test_a_compaction_that_cannot_keep_up_is_context_exceeded() -> None:
    _allows_compaction()
    text = _lines(boundary(), REFILLED)
    ended = unavailable_end(text, REFILLED, exit_code=1, timed_out=False, compaction="on")
    assert ended is not None and ended[0] == "context_exceeded"


# --- a review, its sessions stood in for ------------------------------------------------------


def _setup(tmp_path: Path, compaction: str, repairs: int = 0) -> ReviewerSetup:
    assert "review_compaction" in {f.name for f in fields(ReviewerSetup)}, (
        "a reviewer's setup does not carry the run's review_compaction"
    )
    extra: dict[str, Any] = {"review_compaction": compaction}
    return ReviewerSetup(
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
        **extra,
    )


def _review(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    sessions: list[tuple[list[dict[str, Any]], dict[str, Any]]],
    *,
    compaction: str = "on",
    hook_saw: int | None = None,
    repairs: int = 0,
) -> ReviewResult | ReviewUnavailableError:
    """Review with each invocation's stream events and result scripted in order.

    ``hook_saw`` is how many compactions the hook layer recorded; by default, as many as the
    streams show.
    """
    setup = _setup(tmp_path, compaction, repairs)
    read = tmp_path / "rs" / "review" / "read"
    read.mkdir(parents=True)
    packet = SimpleNamespace(read_root=str(read), indicators=(), sha256=lambda: "0" * 64)
    spawned: list[Path] = []

    def spawn(self: object, *args: object, **kwargs: Any) -> tuple[Path, int, bool]:  # noqa: ANN401
        events, _ = sessions[len(spawned)]
        path = tmp_path / f"stream-{len(spawned)}.jsonl"
        path.write_text(_lines(*events))
        spawned.append(path)
        return path, 0, False

    def captured(path: Path, data: bytes | None = None) -> object:
        _, result = sessions[spawned.index(path)]
        return SimpleNamespace(result=result, usage=(), answered={MODEL}, tampered=None)

    def shown() -> int:
        # As the hook layer would have recorded them by the end of the latest invocation.
        return sum(
            1
            for events, _ in sessions[: len(spawned)]
            for e in events
            if e.get("type") == "system" and e.get("subtype") == "compact_boundary"
        )

    monkeypatch.setattr(claude, "binary_version", lambda binary: VERSION)
    monkeypatch.setattr(claude, "review_dir", lambda root, sid: tmp_path / "rs" / "review")
    monkeypatch.setattr(ClaudeReviewer, "_prepare", lambda self, review, a, sid: packet)
    monkeypatch.setattr(
        ClaudeReviewer,
        "_install",
        lambda *_a: Installed(settings="s", config="c", spawn_args=(), spawn_env={}),
    )
    monkeypatch.setattr(ClaudeReviewer, "_spawn", spawn)
    monkeypatch.setattr(claude, "review_prompt", lambda *a, **k: "p")
    monkeypatch.setattr(claude, "remove_secrets", lambda *a: None)
    monkeypatch.setattr(claude, "redact", lambda *a: None)
    monkeypatch.setattr(claude, "read_captured", captured)
    monkeypatch.setattr(claude, "compaction_line", lambda *a, **k: None)
    monkeypatch.setattr(claude, "read_in_full", lambda *a: True)
    monkeypatch.setattr(claude, "write_key_helper", lambda state, key, place: None)
    monkeypatch.setattr(
        claude,
        "compactions_seen",
        lambda *a: shown() if hook_saw is None else hook_saw,
        raising=False,
    )
    reviewer = ClaudeReviewer(role=ROLE, setup=setup, rubric=load_rubric(REPO / "knowledge", ROLE))
    try:
        return reviewer.review(SimpleNamespace())  # type: ignore[arg-type]
    except ReviewUnavailableError as exc:
        return exc


def _verdict(answer: dict[str, Any]) -> dict[str, Any]:
    return {**COMPLETED, "structured_output": {WRAPPER: answer}}


def test_a_review_that_compacted_twice_is_a_verdict_recording_both(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    events = [boundary(900_000), boundary(955_000), COMPLETED]
    result = _review(tmp_path, monkeypatch, [(events, _verdict(VALID))])
    assert isinstance(result, ReviewResult), result
    assert result.verdict == "pass"
    assert getattr(result, "compactions", None) == 2
    assert getattr(result, "compaction_pre_tokens", None) == (900_000, 955_000)
    line = json.loads(result.model_dump_json())
    assert line["compactions"] == 2
    assert line["compaction_pre_tokens"] == [900_000, 955_000]


def test_compactions_are_counted_across_a_repair_resume(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    sessions = [
        ([boundary(910_000), COMPLETED], _verdict(INVALID)),
        ([boundary(930_000), COMPLETED], _verdict(VALID)),
    ]
    result = _review(tmp_path, monkeypatch, sessions, repairs=1)
    assert isinstance(result, ReviewResult), result
    assert getattr(result, "compactions", None) == 2
    assert getattr(result, "compaction_pre_tokens", None) == (910_000, 930_000)


def test_a_boundary_that_names_no_context_size_leaves_the_sizes_out(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    events = [boundary(900_000), boundary(None), COMPLETED]
    result = _review(tmp_path, monkeypatch, [(events, _verdict(VALID))])
    assert isinstance(result, ReviewResult), result
    assert getattr(result, "compactions", None) == 2
    assert "compaction_pre_tokens" not in json.loads(result.model_dump_json())


def test_a_review_without_a_compaction_is_written_as_before(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    assert "compactions" in ReviewResult.model_fields
    result = _review(tmp_path, monkeypatch, [([COMPLETED], _verdict(VALID))])
    assert isinstance(result, ReviewResult), result
    assert result.compactions is None
    line = json.loads(result.model_dump_json())
    assert "compactions" not in line and "compaction_pre_tokens" not in line


def test_outgrowing_the_window_after_a_compaction_goes_to_a_person_saying_so(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    result = _review(tmp_path, monkeypatch, [([boundary(), REFILLED], REFILLED)])
    assert isinstance(result, ReviewUnavailableError), result
    assert result.cause == "context_exceeded"
    assert getattr(result, "compactions", None) == 1
    assert str(result).endswith("(after 1 compaction)"), str(result)


def test_two_compactions_are_counted_in_the_words_too(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    events = [boundary(), boundary(), REFILLED]
    result = _review(tmp_path, monkeypatch, [(events, REFILLED)])
    assert isinstance(result, ReviewUnavailableError), result
    assert getattr(result, "compactions", None) == 2
    assert str(result).endswith("(after 2 compactions)"), str(result)


def test_a_review_with_no_verdict_and_no_compaction_says_nothing_of_one(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    result = _review(tmp_path, monkeypatch, [([REFILLED], REFILLED)])
    assert isinstance(result, ReviewUnavailableError), result
    assert result.cause == "context_exceeded"
    assert getattr(result, "compactions", "absent") is None
    assert "compaction" not in str(result)


def test_a_compaction_the_hook_layer_did_not_see_is_no_verdict(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    result = _review(
        tmp_path, monkeypatch, [([boundary(), COMPLETED], _verdict(VALID))], hook_saw=0
    )
    assert isinstance(result, ReviewUnavailableError), result
    assert result.cause == "reading_incomplete"
    assert "a compaction the hook layer did not see" in str(result)


def test_a_compaction_the_hook_layer_recorded_and_the_stream_does_not_show_is_no_verdict(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    result = _review(tmp_path, monkeypatch, [([COMPLETED], _verdict(VALID))], hook_saw=1)
    assert isinstance(result, ReviewUnavailableError), result
    assert result.cause == "reading_incomplete"


def test_under_off_a_compaction_is_still_no_verdict(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    result = _review(
        tmp_path, monkeypatch, [([boundary(), COMPLETED], _verdict(VALID))], compaction="off"
    )
    assert isinstance(result, ReviewUnavailableError), result
    assert result.cause == "compacted"


# --- where compaction was not measured --------------------------------------------------------


def test_compaction_on_is_refused_at_the_start_on_a_pin_where_it_was_not_measured(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from physgate.orchestrator.exceptions import ReviewerNotRegisteredError

    measured = getattr(claude, "COMPACTION_MEASURED_PINS", None)
    assert measured is not None, "no pin is named as one where a reviewer's compaction was measured"
    monkeypatch.setattr(claude, "load_rubric", lambda root, role: SimpleNamespace(role=role))
    monkeypatch.setattr(claude, "COMPACTION_MEASURED_PINS", frozenset())
    with pytest.raises(ReviewerNotRegisteredError, match="review_compaction"):
        claude.claude_reviewers(_setup(tmp_path, "on"))
    # Compaction off needs no measurement beyond the ones every pin already has.
    assert set(claude.claude_reviewers(_setup(tmp_path, "off"))) == {ROLE}
    monkeypatch.setattr(claude, "COMPACTION_MEASURED_PINS", frozenset({VERSION}))
    assert set(claude.claude_reviewers(_setup(tmp_path, "on"))) == {ROLE}


#: The pins on which every row the release of compaction needs passed: the measured boundary,
#: schema, accounting, session-start and resume rows, the accounting rows of a compacting
#: review, what a compaction carries, and a review that reads its rubric by the note's range.
MEASURED = ("2.1.301", "2.1.322")
#: A pinned binary on which a reviewer's compaction was never measured.
UNMEASURED = "2.1.272"


@pytest.mark.parametrize("version", MEASURED)
def test_compaction_on_starts_on_a_pin_where_it_was_measured(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, version: str
) -> None:
    from physgate.orchestrator.exceptions import ReviewerNotRegisteredError

    monkeypatch.setattr(claude, "load_rubric", lambda root, role: SimpleNamespace(role=role))
    refused: ReviewerNotRegisteredError | None = None
    try:
        started = claude.claude_reviewers(replace(_setup(tmp_path, "on"), claude_version=version))
    except ReviewerNotRegisteredError as exc:
        refused, started = exc, {}
    assert refused is None, f"review_compaction: on is refused on {version}, where it was measured"
    assert set(started) == {ROLE}


def test_compaction_on_is_still_refused_on_a_pin_where_it_was_not_measured(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from physgate.orchestrator.exceptions import ReviewerNotRegisteredError

    monkeypatch.setattr(claude, "load_rubric", lambda root, role: SimpleNamespace(role=role))
    assert UNMEASURED not in claude.COMPACTION_MEASURED_PINS
    with pytest.raises(ReviewerNotRegisteredError, match="review_compaction"):
        claude.claude_reviewers(replace(_setup(tmp_path, "on"), claude_version=UNMEASURED))
    off = claude.claude_reviewers(replace(_setup(tmp_path, "off"), claude_version=UNMEASURED))
    assert set(off) == {ROLE}


def test_a_reviewer_built_directly_is_refused_compaction_on_a_pin_where_it_was_not_measured(
    tmp_path: Path,
) -> None:
    from physgate.orchestrator.exceptions import ReviewerNotRegisteredError
    from physgate.reviewers.rubric import Rubric

    rubric = Rubric(role=ROLE, text="r", sha256="0" * 64)
    # Every path that builds a reviewer goes through its constructor, not only the run's.
    refused: Exception | None = None
    try:
        ClaudeReviewer(
            role=ROLE,
            setup=replace(_setup(tmp_path, "on"), claude_version=UNMEASURED),
            rubric=rubric,
        )
    except ReviewerNotRegisteredError as exc:
        refused = exc
    assert refused is not None, "a reviewer built directly compacts on an unmeasured pin"
    assert "review_compaction" in str(refused)
    for version in MEASURED:
        ClaudeReviewer(
            role=ROLE, setup=replace(_setup(tmp_path, "on"), claude_version=version), rubric=rubric
        )
    ClaudeReviewer(
        role=ROLE, setup=replace(_setup(tmp_path, "off"), claude_version=UNMEASURED), rubric=rubric
    )
