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
from physgate.orchestrator.protocols import MessageUsage, Usage
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
    line: MessageUsage | None = None,
    after: bytes = b"",
    redacting: bool = False,
    told: list[tuple[str, bytes]] | None = None,
    first_read_fails: bool = False,
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
        stdout.write_bytes((json.dumps(tool_output) + "\n").encode() + after)
    captured = SimpleNamespace(result=None, usage=(), answered={MODEL}, tampered=tampered)

    def totals(*_a: Any, **_k: Any) -> MessageUsage | None:  # noqa: ANN401
        if not totals_hold:
            msg = "the result's totals are not the messages'"
            raise AccountingError(msg)
        return line

    monkeypatch.setattr(claude, "binary_version", lambda binary: VERSION)
    monkeypatch.setattr(claude, "review_dir", lambda root, sid: tmp_path / "rs" / "review")
    monkeypatch.setattr(ClaudeReviewer, "_prepare", lambda self, review, a, sid: packet)
    monkeypatch.setattr(
        ClaudeReviewer,
        "_install",
        lambda *_a: Installed(settings="s", config="c", spawn_args=(), spawn_env={}),
    )
    monkeypatch.setattr(ClaudeReviewer, "_spawn", lambda self, *a, **k: (stdout, 0, False))
    monkeypatch.setattr(claude, "review_prompt", lambda *a, **k: "p")
    monkeypatch.setattr(claude, "remove_secrets", lambda *a: None)
    if not redacting:
        monkeypatch.setattr(claude, "redact", lambda *a: None)
    monkeypatch.setattr(claude, "read_captured", lambda path, data=None: captured)
    if first_read_fails:
        real_read = claude.read_stream_file
        reads: list[Path] = []

        def once_refused(path: Path) -> bytes:
            reads.append(path)
            if len(reads) == 1:
                msg = "the stream could not be read this once"
                raise InvocationError(msg)
            return real_read(path)

        monkeypatch.setattr(claude, "read_stream_file", once_refused)
    monkeypatch.setattr(claude, "compaction_line", totals)
    monkeypatch.setattr(claude, "verdict_schema", lambda *a, **k: {})
    monkeypatch.setattr(claude, "contract_text", lambda *a, **k: "c")
    rubric = Rubric(role="control", text="r", sha256="0" * 64)
    reviewer = ClaudeReviewer(role="control", setup=_setup(tmp_path, canaries), rubric=rubric)
    if told is not None and hasattr(reviewer, "record_shown"):
        # What the stream holds when the review says its scan showed a canary.
        reviewer.record_shown(lambda session: told.append((session, stdout.read_bytes())))
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


def test_an_exposed_review_raises_with_its_compaction_s_own_usage(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    spent = Usage(
        input_tokens=70_001,
        output_tokens=301,
        cache_read_input_tokens=0,
        cache_creation_input_tokens=0,
    )
    line = MessageUsage(message_id="compaction-1", usage=spent, compaction=True)
    with pytest.raises(HeldOutExposedError) as raised:
        _review(tmp_path, monkeypatch, f"read: <!-- {CANARY} -->", line=line)
    # The compaction's call was spent before the exposure was found: it is counted with it.
    assert line in raised.value.usage, "an exposed review's compaction is not counted"


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


@pytest.mark.parametrize(
    "unreadable",
    [
        b'{"type":"user","message":{"content":"caf\xe9"}}\n',
        b'{"type":"user","type":"assistant","message":{"content":"x"}}\n',
    ],
    ids=["not UTF-8", "a key twice"],
)
def test_a_line_the_redaction_replaces_whole_is_scanned_as_it_was_written(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, unreadable: bytes
) -> None:
    # A line that cannot be read counts as the canary. The redaction replaces such a line whole,
    # so the stream is scanned before it, as the exposure register and the next command scan it.
    with pytest.raises(Exception) as raised:  # noqa: PT011 - which end it came to is the point
        _review(tmp_path, monkeypatch, "nothing held out", after=unreadable, redacting=True)
    assert isinstance(raised.value, HeldOutExposedError), repr(raised.value)


@pytest.mark.parametrize(
    "unreadable",
    [
        b'{"type":"user","message":{"content":"caf\xe9"}}\n',
        b'{"type":"user","type":"assistant","message":{"content":"x"}}\n',
    ],
    ids=["not UTF-8", "a key twice"],
)
def test_a_review_says_its_scan_showed_a_canary_before_its_redaction_replaces_the_line(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, unreadable: bytes
) -> None:
    told: list[tuple[str, bytes]] = []
    with pytest.raises(HeldOutExposedError) as raised:
        _review(
            tmp_path, monkeypatch, "nothing held out", after=unreadable, redacting=True, told=told
        )
    # Told once, with the line still in the stream: a kill after the redaction loses nothing.
    assert [(session, unreadable in held) for session, held in told] == [
        (raised.value.session_id, True)
    ]
    assert unreadable not in (tmp_path / "stdout.jsonl").read_bytes(), "the stream was redacted"


def test_a_review_that_showed_nothing_says_nothing(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    told: list[tuple[str, bytes]] = []
    with pytest.raises(Exception) as raised:  # noqa: PT011 - any end but an exposure
        _review(tmp_path, monkeypatch, "nothing held out", redacting=True, told=told)
    assert not isinstance(raised.value, HeldOutExposedError)
    assert told == []


def test_a_canary_the_first_read_missed_is_found_by_the_read_after_the_redaction(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    with pytest.raises(Exception) as raised:  # noqa: PT011 - which end it came to is the point
        _review(tmp_path, monkeypatch, f"read: <!-- {CANARY} -->", first_read_fails=True)
    assert isinstance(raised.value, HeldOutExposedError), repr(raised.value)


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
