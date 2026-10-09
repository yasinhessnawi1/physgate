"""A reviewer that sends its verdict as a string of JSON is told so, sends the object, and stands.

Real reviewers have passed ``review`` as a string holding the verdict's JSON with one
stray closing brace. The binary refuses that ("/review: must be object"), and one
reviewer repeated it until the binary's cap on refused structured answers ended the
session with no verdict. Through the real binary, a reviewer that stringifies once is
refused, the refusal stands, the next request carries the precise correction, and the
object it then sends is the verdict. Nothing reads the string.
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
from physgate.reviewers.rubric import load_rubric

pytestmark = [
    pytest.mark.integration,
    pytest.mark.skipif(not BINARIES, reason="no pinned Claude Code binary named on this machine"),
]

REPO = Path(__file__).resolve().parents[3]


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
