"""A review session's stream is scanned for the run's held-out canaries, as a role's is.

A reviewer reads its packet and nothing else, but a review session is a session like any
other: a read the hooks could not judge would show a held-out canary in its own stream.
Its stream is scanned before anything else is concluded from it, so an exposure is never
hidden behind an unavailable review, a tampered stream or a broken account. A stream that is
not there to scan is no stream that showed nothing: the review stops the run, unretried.
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
from physgate.orchestrator.exceptions import (
    AccountingError,
    HeldOutExposedError,
    InvocationError,
    ReviewUnavailableError,
)
from physgate.orchestrator.run_config import RunBounds
from physgate.reviewers.claude import ClaudeReviewer, ReviewerSetup
from physgate.reviewers.rubric import Rubric

CANARY = "0123456789abcdef0011223344556677"
MODEL = "claude-sonnet-5"
VERSION = "2.1.283"


def _setup(tmp_path: Path, canaries: tuple[str, ...]) -> ReviewerSetup:
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
        held_out_canaries=canaries,
    )


def _review(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    shown: str,
    canaries: tuple[str, ...] = (CANARY,),
    tampered: str | None = None,
    totals_hold: bool = True,
    gone: bool = False,
) -> object:
    read = tmp_path / "rs" / "review" / "read"
    read.mkdir(parents=True)
    packet = SimpleNamespace(read_root=str(read), indicators=(), sha256=lambda: "0" * 64)
    stdout = tmp_path / "stdout.jsonl"
    tool_output = {
        "type": "user",
        "message": {"content": [{"type": "tool_result", "content": shown}]},
    }
    if not gone:
        stdout.write_text(json.dumps(tool_output) + "\n")
    captured = SimpleNamespace(result=None, usage=(), answered={MODEL}, tampered=tampered)

    def totals(*_a: Any) -> None:  # noqa: ANN401
        if not totals_hold:
            msg = "the result's totals are not the messages'"
            raise AccountingError(msg)

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
    monkeypatch.setattr(claude, "remove_secrets", lambda *a: None)
    monkeypatch.setattr(claude, "redact", lambda *a: None)
    monkeypatch.setattr(claude, "read_captured", lambda path: captured)
    monkeypatch.setattr(claude, "require_matching_totals", totals)
    monkeypatch.setattr(claude, "verdict_schema", lambda *a, **k: {})
    monkeypatch.setattr(claude, "contract_text", lambda *a, **k: "c")
    rubric = Rubric(role="control", text="r", sha256="0" * 64)
    reviewer = ClaudeReviewer(role="control", setup=_setup(tmp_path, canaries), rubric=rubric)
    return reviewer.review(SimpleNamespace())  # type: ignore[arg-type]


@pytest.mark.parametrize(
    ("tampered", "totals_hold"),
    [(None, True), ("a tail after the result", True), (None, False)],
    ids=["alone", "and-tampered", "and-broken-account"],
)
def test_a_review_that_showed_a_held_out_canary_raises_an_exposure_first(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, tampered: str | None, totals_hold: bool
) -> None:
    with pytest.raises(HeldOutExposedError) as raised:
        _review(
            tmp_path,
            monkeypatch,
            f"read: <!-- {CANARY} -->",
            tampered=tampered,
            totals_hold=totals_hold,
        )
    assert raised.value.reviewer_model == MODEL
    assert raised.value.session_id
    assert CANARY[:8] not in str(raised.value)


def test_a_canary_shown_in_another_form_is_an_exposure_too(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    with pytest.raises(HeldOutExposedError):
        _review(tmp_path, monkeypatch, CANARY.encode().hex())


def test_a_review_whose_stream_is_gone_halts_and_is_never_scanned_as_clean(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    # The stream was opened by this process before the session ran, so a stream that is
    # not there was removed: nothing can be concluded from it, an exposure least of all,
    # and the review is not an infrastructure failure the loop would retry.
    with pytest.raises(InvocationError) as raised:
        _review(tmp_path, monkeypatch, f"read: <!-- {CANARY} -->", gone=True)
    assert not isinstance(raised.value, ReviewUnavailableError)
    assert CANARY[:8] not in str(raised.value)


def test_an_empty_stream_is_read_as_the_session_ending_with_no_result(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    stdout = tmp_path / "stdout.jsonl"
    stdout.write_text("")
    with pytest.raises(ReviewUnavailableError) as raised:
        _review(tmp_path, monkeypatch, "", gone=True)
    assert raised.value.cause == "infrastructure"


def test_a_review_of_a_run_with_no_held_out_canary_is_not_scanned(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    with pytest.raises(Exception) as raised:  # noqa: PT011 - any end but an exposure
        _review(tmp_path, monkeypatch, f"read: <!-- {CANARY} -->", canaries=())
    assert not isinstance(raised.value, HeldOutExposedError)


def test_a_driven_run_s_reviewers_carry_its_held_out_canaries() -> None:
    from test_a_review_is_a_verdict_only_when_its_session_gives_one import _config

    config = _config().model_copy(update={"held_out_canaries": (CANARY,)})
    setup = ReviewerSetup.of_run(
        config,
        review_root=Path("/r"),
        repo=Path("/t"),
        install_bin=Path("/i/physgate"),
        binary="claude",
        base_url=None,
        credential=Credential(mode="api_key", secret="not-a-key"),
        library=Path("/h"),
    )
    assert setup.held_out_canaries == (CANARY,)
