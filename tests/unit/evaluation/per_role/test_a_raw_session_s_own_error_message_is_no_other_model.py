"""A raw session's own error message is no other model: the record and the pair check agree.

The pinned client writes messages of its own into a session's stream, under the model name
``<synthetic>``: an API error's notice, the usage limit's. They are no model's answer. A raw
session that met one such notice and was then answered by the pinned model was answered by that
model alone: its record says so and the pair check holds it equal to the harness arm. Nothing
else is left out: a second real model, or a name that only looks like the client's, is still
recorded and still named, in the same words. A session that only the client wrote to was
answered by no model: its record says none, the pair check names it, and its end is the
machine's, so it is never a counted trial.

Each row runs the raw arm's own record-writing on a scripted stream (nothing is spawned) and the
pair check on the directory that record and stream make, laid out as the raw arm leaves it.
"""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest
from test_the_two_arms_differ_in_the_harness_alone import (
    MODEL,
    TASK,
    _harness_run,
    _pins,
    _settings,
)

from physgate.evaluation.per_role.arms import raw
from physgate.evaluation.per_role.arms.compare import differences
from physgate.evaluation.per_role.assemble import raw_ended_by_infrastructure
from physgate.hooks.settings import PROFILE_TOOLS

#: Another real model, answering beside or instead of the pinned one.
OTHER = "claude-sonnet-5"
#: The client's name for the messages it writes itself, spelt as the streams spell it.
SYNTHETIC = "<synthetic>"
USAGE = {
    "input_tokens": 300,
    "output_tokens": 100,
    "cache_read_input_tokens": 0,
    "cache_creation_input_tokens": 0,
}
NONE_SPENT = {
    "input_tokens": 0,
    "output_tokens": 0,
    "cache_read_input_tokens": 0,
    "cache_creation_input_tokens": 0,
}


def _notice(text: str, *, model: str = SYNTHETIC, **outer: Any) -> dict[str, Any]:  # noqa: ANN401
    """A message the client wrote itself, in the shape the pinned binary writes one."""
    return {
        "type": "assistant",
        "message": {
            "id": "notice-" + hashlib.sha256(text.encode()).hexdigest()[:12],
            "model": model,
            "role": "assistant",
            "type": "message",
            "content": [{"type": "text", "text": text}],
            "usage": NONE_SPENT,
        },
        "parent_tool_use_id": None,
        **outer,
    }


#: One transient API error, as the binary notes it in the stream before it goes on.
API_ERROR = [
    _notice(
        "API Error: 529 Overloaded. The service is busy.",
        error="unknown",
        is_api_error_message=True,
    )
]
#: The account's usage limit, as a live stream gave it: the limit's event, then the notice.
USAGE_LIMIT = [
    {
        "type": "rate_limit_event",
        "rate_limit_info": {
            "status": "rejected",
            "resetsAt": 1794572400,
            "rateLimitType": "five_hour",
        },
    },
    _notice("You've hit your session limit · resets 1:20pm (Europe/Oslo)", error="rate_limit"),
]


def _answer(model: str = MODEL, n: int = 1) -> dict[str, Any]:
    return {"type": "assistant", "message": {"id": f"msg_{n}", "model": model, "usage": USAGE}}


COMPLETED = {"type": "result", "is_error": False, "terminal_reason": "completed"}
ENDED_ON_AN_API_ERROR = {
    "type": "result",
    "is_error": True,
    "terminal_reason": "api_error",
    "api_error_status": 529,
}


def _raw_arm(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, lines: list[dict[str, Any]], *, exit_code: int
) -> tuple[Path, dict[str, Any]]:
    """The raw arm's directory and record for a session whose stream is ``lines``.

    The record is the one the raw arm writes from the stream (its session is scripted, so
    nothing is spawned); the directory holds it, the stream and the generated settings, as the
    raw arm leaves them, with the pins a fair pair records.
    """
    raw_dir = tmp_path / "raw"
    sdir = raw_dir / "session"
    sdir.mkdir(parents=True)
    text = "".join(json.dumps(line) + "\n" for line in lines)

    def session(*_a: object, **_k: object) -> tuple[object, ...]:
        (sdir / "stdout.jsonl").write_text(text)
        ended = SimpleNamespace(timed_out=False, exit_code=exit_code, left_running=())
        return ended, SimpleNamespace(end=None, failure=None), 1.0, {}

    monkeypatch.setattr(raw, "_session", session)
    monkeypatch.setattr(raw, "_clean", lambda *a, **k: None)
    setup = SimpleNamespace(credential=SimpleNamespace(secret="not-a-key"), held_out_canaries=())
    # The harness run's total, which the fair pair's raw session is capped at.
    record = raw._run("brief", setup, raw_dir, raw_dir, sdir, "raw-1", None, 1000)  # type: ignore[arg-type]
    record.update(task=TASK.id, pins=_pins(), answer="no_answer")
    (raw_dir / "raw.json").write_text(json.dumps(record))
    _settings(sdir / "session", "baseline", None, list(PROFILE_TOOLS["baseline"]))
    return raw_dir, record


def _pair(tmp_path: Path, raw_dir: Path) -> list[str]:
    return differences(_harness_run(tmp_path), raw_dir, role="control", task=TASK)


@pytest.mark.parametrize("notice", [API_ERROR, USAGE_LIMIT], ids=["an API error", "a usage limit"])
def test_a_session_that_met_a_notice_and_was_then_answered_by_the_pinned_model_is_its_alone(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, notice: list[dict[str, Any]]
) -> None:
    lines = [_answer(n=1), *notice, _answer(n=2), COMPLETED]
    raw_dir, record = _raw_arm(tmp_path, monkeypatch, lines, exit_code=0)
    assert record["answered_by"] == [MODEL], "the client's own message is recorded as a model"
    assert _pair(tmp_path, raw_dir) == [], "the pair is stopped for the client's own message"


@pytest.mark.parametrize("notice", [API_ERROR, USAGE_LIMIT], ids=["an API error", "a usage limit"])
def test_a_second_real_model_beside_the_pinned_one_still_stops_the_round_in_the_same_words(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, notice: list[dict[str, Any]]
) -> None:
    lines = [_answer(n=1), *notice, _answer(OTHER, n=2), COMPLETED]
    raw_dir, record = _raw_arm(tmp_path, monkeypatch, lines, exit_code=0)
    assert record["answered_by"] == [MODEL, OTHER]
    assert _pair(tmp_path, raw_dir) == [
        f"answered_by: the harness pinned {MODEL!r}, the raw arm was answered by {[MODEL, OTHER]!r}"
    ]


def test_a_session_answered_after_a_notice_by_another_model_alone_is_named_as_that_model(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    lines = [*API_ERROR, _answer(OTHER), COMPLETED]
    raw_dir, record = _raw_arm(tmp_path, monkeypatch, lines, exit_code=0)
    assert record["answered_by"] == [OTHER]
    assert _pair(tmp_path, raw_dir) == [
        f"answered_by: the harness pinned {MODEL!r}, the raw arm was answered by {[OTHER]!r}"
    ]


@pytest.mark.parametrize(
    "lookalike", ["<Synthetic>", "<synthetic> ", "synthetic", "<synthetic>-2", "<synth"]
)
def test_a_name_that_only_looks_like_the_client_s_own_is_kept_and_named(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, lookalike: str
) -> None:
    lines = [_answer(n=1), _notice("API Error: 529 Overloaded.", model=lookalike), COMPLETED]
    raw_dir, record = _raw_arm(tmp_path, monkeypatch, lines, exit_code=0)
    assert record["answered_by"] == sorted([MODEL, lookalike])
    assert _pair(tmp_path, raw_dir) == [
        f"answered_by: the harness pinned {MODEL!r}, the raw arm was answered by "
        f"{sorted([MODEL, lookalike])!r}"
    ]


@pytest.mark.parametrize("notice", [API_ERROR, USAGE_LIMIT], ids=["an API error", "a usage limit"])
def test_a_session_only_the_client_wrote_to_was_answered_by_no_model_and_is_the_machine_s_end(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, notice: list[dict[str, Any]]
) -> None:
    """Never read as answered by the pinned model: the pair check names it, and it is no trial."""
    lines = [*notice, ENDED_ON_AN_API_ERROR]
    raw_dir, record = _raw_arm(tmp_path, monkeypatch, lines, exit_code=1)
    assert record["answered_by"] == []
    assert _pair(tmp_path, raw_dir) == [
        f"answered_by: the harness pinned {MODEL!r}, the raw arm was answered by []"
    ]
    # The session left no answer, and its end is the machine's: run once more, never scored.
    stream = raw_dir / "session" / "stdout.jsonl"
    assert raw_ended_by_infrastructure(record, stream, TASK) is True
