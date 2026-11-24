"""A reviewer that sends its verdict as a string of JSON is told so, sends the object, and stands.

Real reviewers have passed ``review`` as a string holding the verdict's JSON with one
stray closing brace. The binary refuses that ("/review: must be object"), and one
reviewer repeated it until the binary's cap on refused structured answers ended the
session with no verdict. Through the real binary, a reviewer that stringifies once is
refused, the refusal stands, the next request carries the precise correction, and the
object it then sends is the verdict. A reviewer that never corrects ends at the cap as before;
its last try, a text the binary refused only for being one, is then read as the object it holds
and held to the same schema: a verdict where it holds, a refused verdict in words where not.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from test_the_first_real_reviews_replay_as_they_ended import (
    BINARIES,
    REFUSED,
    review_requests,
    valid,
)
from test_the_first_real_reviews_replay_as_they_ended import binary as binary  # noqa: F401
from test_the_first_real_reviews_replay_as_they_ended import install as install  # noqa: F401

from physgate.hooks.verdict_shape import CORRECTION, NOT_AN_OBJECT
from physgate.orchestrator.budget import STRUCTURED_OUTPUT_EXHAUSTED
from physgate.orchestrator.decompose import binary_version, read_stream
from physgate.orchestrator.exceptions import ReviewUnavailableError
from physgate.reviewers.claude import schema_refusals
from physgate.reviewers.rubric import load_rubric

pytestmark = [
    pytest.mark.integration,
    pytest.mark.skipif(not BINARIES, reason="no pinned Claude Code binary named on this machine"),
]

REPO = Path(__file__).resolve().parents[3]
#: How many refused verdicts end a review session, per pin (measured: the binary's own cap).
REFUSALS_BEFORE_THE_CAP = {"2.1.301": 5, "2.1.322": 5}


@pytest.mark.parametrize("role", ["control", "firmware"])
def test_a_review_sent_once_as_a_string_is_corrected_and_ends_in_a_verdict(
    tmp_path: Path, install: Path, binary: str, role: str
) -> None:
    items = load_rubric(REPO / "knowledge", role).items
    # As the real reviewers sent it: the verdict's JSON with one closing brace too many.
    stringified = json.dumps(valid(items)) + "}"
    result, requests = review_requests(tmp_path, install, binary, role, {"review": stringified})
    refused = [i for i, r in enumerate(requests) if r.last_user.startswith(REFUSED)]
    assert len(refused) == 1, [r.last_user for r in requests[-3:]]
    # The refusal stands as the binary worded it; the correction comes beside it.
    assert NOT_AN_OBJECT in requests[refused[0]].last_user
    assert CORRECTION in requests[refused[0]].after_user
    assert [i for i, r in enumerate(requests) if CORRECTION in r.after_user] == refused
    assert result.verdict == "pass" and result.schema_refusals == 1
    assert len(result.items) == len(items)


def test_a_reviewer_that_never_corrects_is_read_from_its_last_text_at_the_cap(
    tmp_path: Path, install: Path, binary: str
) -> None:
    # The binary ends the session at its cap on refused structured answers, as it always did;
    # the last try held a verdict the schema takes, so that verdict is recorded, marked so.
    items = load_rubric(REPO / "knowledge", "control").items
    stringified = json.dumps(valid(items)) + "}"
    result, _ = review_requests(
        tmp_path, install, binary, "control", {"review": stringified}, then_correct=False
    )
    cap = REFUSALS_BEFORE_THE_CAP[binary_version(binary)]
    assert result.verdict == "pass" and result.verdict_from_text is True
    assert result.schema_refusals == cap
    (stream,) = [p.read_text() for p in (tmp_path / "rs").glob("*/session/stdout.jsonl")]
    assert schema_refusals(stream) == cap
    ended, _, _ = read_stream(stream)
    assert ended is not None and ended["terminal_reason"] == STRUCTURED_OUTPUT_EXHAUSTED
    assert "structured_output" not in ended


def test_a_reviewer_that_never_corrects_a_text_the_schema_refuses_is_an_invalid_verdict(
    tmp_path: Path, install: Path, binary: str
) -> None:
    # The same end, its last text leaving a rubric item out: an invalid verdict, never
    # infrastructure, saying why in words.
    items = load_rubric(REPO / "knowledge", "control").items
    short = valid(items)
    del short["items"][items[-1].id]
    with pytest.raises(ReviewUnavailableError) as raised:
        review_requests(
            tmp_path,
            install,
            binary,
            "control",
            {"review": json.dumps(short) + "}"},
            then_correct=False,
        )
    assert raised.value.cause == "invalid_verdict"
    cap = REFUSALS_BEFORE_THE_CAP[binary_version(binary)]
    assert f"after {cap} attempts" in str(raised.value)
    assert "the verdict was sent as text" in str(raised.value)
    assert f"must have required property '{items[-1].id}'" in str(raised.value)
    (stream,) = [p.read_text() for p in (tmp_path / "rs").glob("*/session/stdout.jsonl")]
    assert schema_refusals(stream) == cap
