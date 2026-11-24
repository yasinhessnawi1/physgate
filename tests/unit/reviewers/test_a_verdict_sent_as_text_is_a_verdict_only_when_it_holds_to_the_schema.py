"""A review is not lost to the form of its verdict, and nothing the schema refuses is accepted.

Measured on real reviews: reviewers sent the verdict's ``review`` as a text (the verdict's own
JSON object, then one closing brace too many) and the binary refused each such try with
"/review: must be object". Of six reviews in one run, two sent it so until the binary's cap on
refused verdicts ended the session: no verdict, though the last text held a verdict that the
schema they were given and the harness's own check both accept. Their sequences, as scripted
here: a try before the reading was done (refused by the reading hook, and counted by the
binary), then four texts; or that try, a text, an object refused on a marker's evidence, then
two texts.

Now the session's last try, and only it, is read when the binary refused it for being a text and
for nothing else: the object it holds, held to the very schema the session was given (the
markers' evidence constants included), then to every check a structured verdict passes. A text
that does not parse or breaks the schema is a refused verdict with its reason in words, which a
repair resume carries. Every session here runs through the real stream reader, the real end
classification and the real verdict check, against streams scripted as the binary writes them.
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
from physgate.orchestrator.exceptions import ReviewUnavailableError
from physgate.orchestrator.protocols import ReviewResult
from physgate.orchestrator.run_config import RunBounds
from physgate.reviewers.claude import ClaudeReviewer, ReviewerSetup
from physgate.reviewers.contract import WRAPPER
from physgate.reviewers.packet import SPEC_AS_ISSUED_NAME
from physgate.reviewers.rubric import load_rubric
from physgate.reviewers.scan import ScanHit

REPO = Path(__file__).resolve().parents[3]
ROLE = "electrical"
MODEL = "claude-sonnet-5"
VERSION = "2.1.283"
RUBRIC = load_rubric(REPO / "knowledge", ROLE)
SPEC = "# Subtask\n\n## Acceptance criteria\n\n1. The rail holds 5 V.\n2. The fuse is rated.\n"
#: The one marker the scan found in the attempt: every verdict must judge it by its evidence.
HIT = ScanHit(kind="disabled_checks", evidence="call-17", what="a test was marked skipped")
JUDGED = {
    "kind": "disabled_checks",
    "evidence": "call-17",
    "disposition": "dismissed",
    "reason": "the skip was taken out again two calls later and the test ran",
}
CLEAN = {
    "acceptance_criteria": "met",
    "domain_standards": "n/a",
    "antipatterns": "n/a",
    "reward_hacking": "not observed",
}
FORM = "Output does not match required schema: /review: must be object"
EVIDENCE = (
    "Output does not match required schema: /review/indicators/0/evidence: must be equal to "
    'constant: "call-17", /review/indicators: must contain at least 1 valid item(s)'
)
TOO_EARLY = (
    "PreToolUse:StructuredOutput hook error: Required reading is not complete. Read each of "
    "these files in full with the Read tool before using any other tool:\n- read/diff-02.patch"
)
USAGE = {
    "input_tokens": 100,
    "output_tokens": 20,
    "cache_read_input_tokens": 0,
    "cache_creation_input_tokens": 0,
}
CAP = {
    "type": "result",
    "subtype": "error_max_structured_output_retries",
    "is_error": True,
    "terminal_reason": "structured_output_retry_exhausted",
    "errors": [
        "Failed to provide valid structured output after 5 attempts — last StructuredOutput "
        f"error: {FORM}"
    ],
}


def accept() -> dict[str, Any]:
    """A verdict the schema and the check both take: every item, both criteria, the marker."""
    return {
        "verdict": "accept",
        "finding": "the rail and its fuse are as the specification asks",
        "failing_item": None,
        "subject": None,
        "numeric_output": None,
        "items": {
            i.id: {"result": CLEAN[i.section], "evidence": "design/nodes/rail.json: 5 V"}
            for i in RUBRIC.items
        },
        "acceptance_criteria": [
            {"criterion": "1", "result": "met", "evidence": "design/nodes/rail.json: 5 V"},
            {"criterion": "2", "result": "met", "evidence": "design/nodes/fuse.json: 2 A"},
        ],
        "indicators": [dict(JUDGED)],
        "spec_defects": [],
    }


def reject() -> dict[str, Any]:
    """A reject the schema and the check both take: the first item unmet, named as failing."""
    answer = accept()
    first = RUBRIC.items[0]
    answer.update(verdict="reject", failing_item=first.id)
    answer["finding"] = "the fuse is rated below the current the rail carries"
    answer["items"][first.id] = {"result": "unmet", "evidence": "design/nodes/fuse.json: 2 A"}
    return answer


def unjudged() -> dict[str, Any]:
    """An accept whose indicator names other evidence: the marker the scan found is not judged."""
    answer = accept()
    answer["indicators"] = [{**JUDGED, "evidence": "the skipped test in the diff"}]
    return answer


def as_sent(answer: dict[str, Any], indent: int | None = 2) -> str:
    """The verdict as the real reviewers sent it as text: its JSON, then one brace too many."""
    return json.dumps(answer, indent=indent) + "\n}\n"


def tried(n: int, review: object, refusal: str) -> list[dict[str, Any]]:
    """One try of the verdict tool and the binary's answer to it."""
    call = {"type": "tool_use", "id": f"call-v{n}", "name": "StructuredOutput"}
    told = {"type": "tool_result", "tool_use_id": f"call-v{n}", "content": refusal}
    return [
        {
            "type": "assistant",
            "message": {
                "id": f"msg-{n}",
                "model": MODEL,
                "role": "assistant",
                "content": [{**call, "input": {WRAPPER: review}}],
                "usage": USAGE,
            },
        },
        {"type": "user", "message": {"role": "user", "content": [{**told, "is_error": True}]}},
    ]


def stream(*tries: list[dict[str, Any]], end: dict[str, Any] = CAP) -> str:
    events = [e for t in tries for e in t]
    return "".join(json.dumps(e) + "\n" for e in [*events, end])


def answered(answer: dict[str, Any], n: int = 9) -> str:
    """A session whose try was taken: the object, and a completed end carrying it."""
    call = {"type": "tool_use", "id": f"call-v{n}", "name": "StructuredOutput"}
    told = {
        "type": "tool_result",
        "tool_use_id": f"call-v{n}",
        "content": "Structured output provided successfully",
    }
    events = [
        {
            "type": "assistant",
            "message": {
                "id": f"msg-{n}",
                "model": MODEL,
                "role": "assistant",
                "content": [{**call, "input": {WRAPPER: answer}}],
                "usage": USAGE,
            },
        },
        {"type": "user", "message": {"role": "user", "content": [told]}},
        {
            "type": "result",
            "subtype": "success",
            "is_error": False,
            "terminal_reason": "completed",
            "structured_output": {WRAPPER: answer},
        },
    ]
    return "".join(json.dumps(e) + "\n" for e in events)


def review(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    *invocations: str,
    repairs: int = 0,
    reading: bool = True,
) -> tuple[ReviewResult | ReviewUnavailableError, list[dict[str, Any]]]:
    """Review with each invocation's stream scripted in order; the hook records stood in for."""
    read = tmp_path / "rs" / "review" / "read"
    read.mkdir(parents=True)
    (read / SPEC_AS_ISSUED_NAME).write_text(SPEC)
    packet = SimpleNamespace(read_root=str(read), indicators=(HIT,), sha256=lambda: "0" * 64)
    spawns: list[dict[str, Any]] = []

    def spawn(self: object, *args: object, **kwargs: Any) -> tuple[Path, int, bool]:  # noqa: ANN401
        spawns.append(kwargs)
        text = invocations[len(spawns) - 1]
        path = tmp_path / f"stream-{len(spawns)}.jsonl"
        path.write_text(text)
        return path, 0 if '"terminal_reason": "completed"' in text else 1, False

    monkeypatch.setattr(claude, "binary_version", lambda binary: VERSION)
    monkeypatch.setattr(claude, "review_dir", lambda root, sid: tmp_path / "rs" / "review")
    monkeypatch.setattr(ClaudeReviewer, "_prepare", lambda self, r, a, sid: packet)
    monkeypatch.setattr(
        ClaudeReviewer,
        "_install",
        lambda *_a: Installed(settings="s", config="c", spawn_args=(), spawn_env={}),
    )
    monkeypatch.setattr(ClaudeReviewer, "_spawn", spawn)
    monkeypatch.setattr(claude, "review_prompt", lambda *a, **k: "p")
    monkeypatch.setattr(claude, "remove_secrets", lambda *a: None)
    monkeypatch.setattr(claude, "redact", lambda *a: None)
    monkeypatch.setattr(claude, "read_in_full", lambda *a: reading)
    monkeypatch.setattr(claude, "write_key_helper", lambda state, key: None)
    setup = ReviewerSetup(
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
    )
    reviewer = ClaudeReviewer(role=ROLE, setup=setup, rubric=RUBRIC)
    try:
        return reviewer.review(SimpleNamespace()), spawns  # type: ignore[arg-type]
    except ReviewUnavailableError as exc:
        return exc, spawns


def test_the_first_lost_sequence_a_try_too_early_then_four_texts_now_yields_its_verdict(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    sent = reject()
    result, _ = review(
        tmp_path,
        monkeypatch,
        stream(
            tried(1, as_sent(sent), TOO_EARLY),
            tried(2, as_sent(sent), FORM),
            tried(3, as_sent(sent, indent=None), FORM),
            tried(4, as_sent(sent, indent=None), FORM),
            tried(5, as_sent(sent, indent=None), FORM),
        ),
    )
    assert isinstance(result, ReviewResult), result
    assert result.verdict == "fail" and result.failing_item == RUBRIC.items[0].id
    assert result.verdict_from_text is True
    # The binary's own refusals are counted as they were: four schema refusals, each told.
    assert result.schema_refusals == 4
    assert [(i.evidence, i.disposition) for i in result.indicators] == [("call-17", "dismissed")]
    assert json.loads(result.model_dump_json())["verdict_from_text"] is True


def test_the_second_lost_sequence_ending_in_two_good_texts_yields_the_last_one(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    missing = reject()
    del missing["items"][RUBRIC.items[-1].id]
    result, _ = review(
        tmp_path,
        monkeypatch,
        stream(
            tried(1, as_sent(missing), TOO_EARLY),
            tried(2, as_sent(unjudged()), FORM),
            tried(3, unjudged(), EVIDENCE),
            tried(4, as_sent(accept(), indent=None), FORM),
            tried(5, as_sent(accept(), indent=None), FORM),
        ),
    )
    assert isinstance(result, ReviewResult), result
    assert result.verdict == "pass" and result.verdict_from_text is True
    assert result.schema_refusals == 4


def test_a_text_that_leaves_the_scan_s_marker_unjudged_is_refused_naming_the_schema_s_place(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    result, _ = review(
        tmp_path,
        monkeypatch,
        stream(tried(1, as_sent(accept()), FORM), tried(2, as_sent(unjudged()), FORM)),
    )
    assert isinstance(result, ReviewUnavailableError)
    assert result.cause == "invalid_verdict"
    words = str(result)
    assert "the verdict was sent as text" in words
    assert "/review/indicators: must contain at least 1 valid item(s)" in words


def test_a_text_the_check_alone_would_take_is_still_refused_where_the_schema_refuses_it(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    # An indicator the reviewer raised itself, naming an attempt: the harness's check reads it as
    # one more indicator, but no earlier attempt was shown, so the schema allows no attempt on it.
    raised = accept()
    raised["indicators"].append(
        {
            **JUDGED,
            "evidence": "call-23",
            "reason": "a limit was widened and put back",
            "attempt": 2,
        }
    )
    result, _ = review(tmp_path, monkeypatch, stream(tried(1, as_sent(raised), FORM)))
    assert isinstance(result, ReviewUnavailableError) and result.cause == "invalid_verdict"
    assert "must NOT have additional properties ('attempt')" in str(result)


@pytest.mark.parametrize(
    ("text", "said"),
    [
        (json.dumps(accept()) + "\n}\n}", "more than one JSON object, or more after it"),
        (
            json.dumps(accept()) + json.dumps(accept()),
            "more than one JSON object, or more after it",
        ),
        (json.dumps(accept())[:-40], "is not one JSON object"),
        (json.dumps(accept()).replace('"numeric_output": null', '"numeric_output": NaN'), "NaN"),
        ('{"verdict": "accept", "verdict": "reject"}}', "gives the key 'verdict' twice"),
        ('"accept"}', "holds no JSON object"),
    ],
    ids=["two-braces", "two-objects", "cut-short", "nan", "duplicate-key", "not-an-object"],
)
def test_a_text_that_is_not_one_json_object_is_refused_in_words(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, text: str, said: str
) -> None:
    result, _ = review(tmp_path, monkeypatch, stream(tried(1, text, FORM)))
    assert isinstance(result, ReviewUnavailableError) and result.cause == "invalid_verdict"
    assert "the verdict was sent as text" in str(result) and said in str(result)


def test_only_the_last_try_is_read_never_an_earlier_text(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    # A good text, then an object the binary refused on its evidence: the reviewer's last word is
    # the refused object, and the earlier text is never taken in its place.
    result, _ = review(
        tmp_path,
        monkeypatch,
        stream(tried(1, as_sent(accept()), FORM), tried(2, unjudged(), EVIDENCE)),
    )
    assert isinstance(result, ReviewUnavailableError) and result.cause == "invalid_verdict"
    assert "sent as text" not in str(result)


def test_a_text_sent_before_the_reading_was_done_is_never_read_as_a_verdict(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    # Refused by the reading hook, not for its form: a good verdict, sent too early, stays refused.
    early = stream(*(tried(n, as_sent(accept()), TOO_EARLY) for n in range(1, 6)))
    result, _ = review(tmp_path, monkeypatch, early)
    assert isinstance(result, ReviewUnavailableError) and result.cause == "invalid_verdict"
    assert "sent as text" not in str(result)


def test_a_good_text_is_no_verdict_when_the_required_reading_was_not_read_in_full(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    result, _ = review(
        tmp_path, monkeypatch, stream(tried(1, as_sent(accept()), FORM)), reading=False
    )
    assert isinstance(result, ReviewUnavailableError) and result.cause == "reading_incomplete"


def test_a_good_text_is_not_read_after_an_end_that_is_no_verdict_for_another_reason(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    api_error = {"type": "result", "is_error": True, "terminal_reason": "api_error"}
    result, _ = review(
        tmp_path, monkeypatch, stream(tried(1, as_sent(accept()), FORM), end=api_error)
    )
    assert isinstance(result, ReviewUnavailableError) and result.cause == "infrastructure"


def test_a_good_text_is_not_read_where_the_binary_could_not_parse_the_call_at_all(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    malformed = {
        "type": "result",
        "is_error": True,
        "terminal_reason": "malformed_tool_use_exhausted",
    }
    result, _ = review(
        tmp_path, monkeypatch, stream(tried(1, as_sent(accept()), FORM), end=malformed)
    )
    assert isinstance(result, ReviewUnavailableError) and result.cause == "invalid_verdict"
    assert "could not parse" in str(result) and "sent as text" not in str(result)


def test_a_refused_text_s_reason_is_what_the_repair_resume_tells_the_reviewer(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    result, spawns = review(
        tmp_path,
        monkeypatch,
        stream(tried(1, as_sent(unjudged()), FORM)),
        answered(accept()),
        repairs=1,
    )
    assert isinstance(result, ReviewResult) and result.verdict == "pass"
    assert result.repair_resumes == 1 and result.verdict_from_text is None
    assert "the verdict was sent as text" in spawns[1]["prompt"]
    assert "/review/indicators: must contain at least 1 valid item(s)" in spawns[1]["prompt"]


def test_a_verdict_given_as_an_object_is_recorded_byte_for_byte_as_before(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    result, _ = review(tmp_path, monkeypatch, answered(accept()))
    assert isinstance(result, ReviewResult) and result.verdict == "pass"
    assert "verdict_from_text" not in json.loads(result.model_dump_json())


def test_a_review_line_written_before_reads_and_writes_back_as_it_was() -> None:
    # A line in the form every review was recorded in before this change.
    line = json.dumps(
        {
            "verdict": "pass",
            "finding": "the rail and its fuse are as the specification asks",
            "reviewer_model": MODEL,
            "session_id": "review-1",
            "usage": [],
            "failing_item": None,
            "subject": None,
            "numeric_output": None,
            "items": [],
            "criteria": [],
            "indicators": [],
            "spec_defects": [],
            "rubric_sha256": None,
            "rubric_kind": None,
            "packet_sha256": None,
            "reading_verified": True,
            "peak_context_tokens": 120,
            "schema_refusals": 2,
            "max_output_tokens": None,
            "context_window": None,
            "repair_resumes": None,
        },
        separators=(",", ":"),
    )
    assert ReviewResult.model_validate_json(line).model_dump_json() == line


def test_the_scripted_tries_are_the_ones_the_binary_refused_as_measured() -> None:
    # The texts are as the real ones: the binary's own reader cannot take them as an object.
    for text in (as_sent(accept()), as_sent(accept(), indent=None)):
        with pytest.raises(json.JSONDecodeError):
            json.loads(text)
