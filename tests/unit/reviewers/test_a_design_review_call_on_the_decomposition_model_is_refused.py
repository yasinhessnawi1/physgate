"""The design reviewer is held apart from the plan's implementer at the call, not only in the pins.

The configuration already refuses a design reviewer pinned to the decomposition's model. The call
holds it again, where nothing a caller hands it can step around the check: before anything is
prepared, against the model the run pinned for the decomposition; and once the stream is held to
its seal, against every model the stream shows answering, before any session runs. Only the design
reviewer reviews a plan, and it reviews no attempt. It is built from the run's pins apart from the
role reviewers, which stay exactly as they were.
"""

from __future__ import annotations

from dataclasses import replace
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest
from plan_fixture import (
    BRIEF,
    DECOMPOSITION,
    REPO,
    REVIEWER,
    design_rubric,
    module,
    stream_text,
    under_review,
)

import physgate.reviewers.claude as claude
from physgate.orchestrator.credentials import Credential
from physgate.orchestrator.exceptions import (
    ModelSeparationError,
    ReviewerNotRegisteredError,
    ReviewUnavailableError,
)
from physgate.orchestrator.run_config import ModelStrings, RunBounds
from physgate.reviewers.claude import ClaudeReviewer, ReviewerSetup, claude_reviewers
from physgate.reviewers.contract import issued_criteria
from physgate.reviewers.exceptions import ReviewError
from physgate.reviewers.rubric import evaluation_words, load_rubric

VERSION = "2.1.301"


def _setup(tmp_path: Path, models: dict[str, str]) -> ReviewerSetup:
    return ReviewerSetup(
        run_id="run-1",
        models=models,
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
        library=REPO,
    )


def _design(tmp_path: Path, model: str) -> ClaudeReviewer:
    (tmp_path / "rs").mkdir(exist_ok=True)
    return ClaudeReviewer(
        role="design", setup=_setup(tmp_path, {"design": model}), rubric=design_rubric()
    )


def _review_plan(reviewer: ClaudeReviewer, under: Any) -> Any:  # noqa: ANN401
    assert hasattr(reviewer, "review_plan"), "the reviewer has no plan path"
    return reviewer.review_plan(under)


class _Watched:
    """Records each binary check and session the review reaches, and reaches no further."""

    def __init__(self, monkeypatch: pytest.MonkeyPatch) -> None:
        self.asked: list[str] = []
        self.sessions: list[dict[str, Any]] = []

        def version(binary: str) -> str:
            self.asked.append(binary)
            return VERSION

        def session(_self: object, review: Path, packet: Any, sid: str, **kw: Any) -> str:  # noqa: ANN401
            self.sessions.append({"review": review, "packet": packet, **kw})
            return "reached"

        monkeypatch.setattr(claude, "binary_version", version)
        monkeypatch.setattr(ClaudeReviewer, "_in_session", session, raising=False)


def test_a_design_review_call_on_the_decomposition_model_is_refused(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    watched = _Watched(monkeypatch)
    # Pinned past the configuration's check, as a mapping a caller builds can be.
    reviewer = _design(tmp_path, DECOMPOSITION)
    under = under_review(tmp_path)
    with pytest.raises(ModelSeparationError):
        _review_plan(reviewer, under)
    # Refused before anything: no binary asked, nothing prepared, no session.
    assert watched.asked == []
    assert list((tmp_path / "rs").iterdir()) == []
    assert watched.sessions == []


def test_a_design_review_of_a_stream_its_own_model_answered_is_refused(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    watched = _Watched(monkeypatch)
    reviewer = _design(tmp_path, REVIEWER)
    # The run pinned another model for the decomposition, and the reviewer's own answered it.
    under = under_review(tmp_path, stream_text=stream_text(model=REVIEWER))
    assert under.decomposition_model != REVIEWER
    with pytest.raises(ModelSeparationError):
        _review_plan(reviewer, under)
    assert watched.sessions == []
    assert not list((tmp_path / "rs").glob("*/session"))


def test_a_design_review_on_another_model_reaches_its_session_with_the_brief_s_criteria(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    watched = _Watched(monkeypatch)
    reviewer = _design(tmp_path, REVIEWER)
    under = under_review(tmp_path)
    assert _review_plan(reviewer, under) == "reached"
    assert watched.asked == ["claude"]
    [session] = watched.sessions
    assert session["criteria"] == issued_criteria(BRIEF) == ("1", "2")
    assert session["was_issued"] is True
    packet = session["packet"]
    assert packet.kind == "plan"
    module("plan_packet").check_plan_packet(packet, under)
    prompt = session["prompt"]("<the contract>")
    assert prompt == claude.plan_review_prompt(packet, "<the contract>")


def test_a_plan_whose_packet_cannot_be_built_is_unprepared(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    watched = _Watched(monkeypatch)
    reviewer = _design(tmp_path, REVIEWER)
    under = under_review(tmp_path)
    Path(under.stream).write_text(stream_text() + "{}\n")
    with pytest.raises(ReviewUnavailableError) as refused:
        _review_plan(reviewer, under)
    assert refused.value.cause == "unprepared"
    assert watched.sessions == []


def test_only_the_design_reviewer_reviews_a_plan(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    watched = _Watched(monkeypatch)
    (tmp_path / "rs").mkdir()
    rubric = load_rubric(REPO / "knowledge", "control")
    reviewer = ClaudeReviewer(
        role="control", setup=_setup(tmp_path, {"control": REVIEWER}), rubric=rubric
    )
    with pytest.raises(ReviewError, match="design reviewer"):
        _review_plan(reviewer, under_review(tmp_path))
    assert watched.asked == []


def test_the_design_reviewer_reviews_no_attempt(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    watched = _Watched(monkeypatch)
    reviewer = _design(tmp_path, REVIEWER)

    class PreparedError(Exception):
        pass

    def prepared(*args: object) -> None:
        raise PreparedError

    monkeypatch.setattr(ClaudeReviewer, "_prepare", prepared)
    with pytest.raises((ReviewError, PreparedError)) as raised:
        reviewer.review(SimpleNamespace())  # type: ignore[arg-type]
    assert raised.type is ReviewError
    assert "never an attempt" in str(raised.value)
    assert watched.asked == []
    assert list((tmp_path / "rs").iterdir()) == []


def _config(reviewers: dict[str, str]) -> Any:  # noqa: ANN401 - what design_reviewer reads
    models = ModelStrings(
        decomposition=DECOMPOSITION, roles={"control": DECOMPOSITION}, reviewers=reviewers
    )
    return SimpleNamespace(models=models)


def _design_reviewer() -> Any:  # noqa: ANN401
    assert hasattr(claude, "design_reviewer"), "no design reviewer is registered from the pins"
    return claude.design_reviewer


def test_the_design_reviewer_is_built_from_the_run_s_pin_with_the_design_rubric(
    tmp_path: Path,
) -> None:
    setup = _setup(tmp_path, {"control": REVIEWER})
    built = _design_reviewer()(setup, _config({"control": REVIEWER, "design": REVIEWER}))
    assert isinstance(built, ClaudeReviewer)
    assert built.model == REVIEWER
    assert built.rubric == design_rubric()
    # The role reviewers are what they were: the design reviewer is not among them.
    assert sorted(claude_reviewers(setup)) == ["control"]


def test_a_run_that_pins_no_design_reviewer_has_none(tmp_path: Path) -> None:
    setup = _setup(tmp_path, {"control": REVIEWER})
    assert _design_reviewer()(setup, _config({"control": REVIEWER})) is None
    assert ModelStrings(decomposition=DECOMPOSITION, roles={}, reviewers={}).model_dump() == {
        "decomposition": DECOMPOSITION,
        "roles": {},
        "reviewers": {},
    }


def test_a_design_reviewer_whose_rubric_does_not_load_is_not_registered(tmp_path: Path) -> None:
    setup = _setup(tmp_path, {"control": REVIEWER})
    empty = tmp_path / "harness"
    (empty / "knowledge").mkdir(parents=True)
    with pytest.raises(ReviewerNotRegisteredError, match="design"):
        _design_reviewer()(replace(setup, library=empty), _config({"design": REVIEWER}))


def test_the_pins_name_the_design_reviewer_by_one_key() -> None:
    import physgate.orchestrator.run_config as run_config

    assert getattr(run_config, "DESIGN_REVIEWER", None) == "design"
    models = ModelStrings(decomposition=DECOMPOSITION, roles={}, reviewers={"design": REVIEWER})
    assert getattr(models, "design_reviewer", None) == REVIEWER


def test_what_the_design_reviewer_is_told_says_nothing_of_being_evaluated(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    watched = _Watched(monkeypatch)
    _review_plan(_design(tmp_path, REVIEWER), under_review(tmp_path))
    [session] = watched.sessions
    read = session["packet"].read_root
    prompt = session["prompt"]("").replace(read, "<read>")
    assert evaluation_words(prompt) == []
    assert "No search for the markers of a check switched off was run" in prompt
    assert "the brief exactly as the decomposition was given it" in prompt
