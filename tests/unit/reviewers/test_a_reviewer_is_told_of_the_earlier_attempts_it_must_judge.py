"""A reviewer is told where the earlier unjudged attempts' streams are, and each marker in them.

The prompt names the earlier attempts' parts beside the attempt's own trajectory, and lists each
marker the scan found in them with the attempt it is from, to be answered as one of the attempt's
own is. Nothing is added to the prompt of a review with no earlier attempt: it is byte for byte
the prompt it was before.
"""

from __future__ import annotations

import hashlib
from pathlib import Path

from test_a_review_is_given_the_hits_no_earlier_review_judged import EARLIER_HIT, _build

from physgate.reviewers.claude import review_prompt
from physgate.reviewers.rubric import evaluation_words

#: The prompt of the fixture's review with no earlier attempt, its read directory written
#: ``<read>``, as the reviewer was told it before earlier attempts were put before it.
BEFORE_SHA256 = "3d86da0ecf0711e36c34814e1c608efbbcf26d7a22907ac82ce6a5bded9fa1d7"


def test_the_prompt_names_the_earlier_parts_and_each_earlier_marker_with_its_attempt(
    tmp_path: Path,
) -> None:
    packet, read, _ = _build(tmp_path)
    prompt = review_prompt("control", packet)
    first, last = packet.earlier_parts[0].name, packet.earlier_parts[-1].name
    named = str(read / first) if first == last else f"{read / first} to {read / last}"
    assert f"- {named}: the trajectories of earlier attempts of this subtask" in prompt
    assert f"- disabled_checks, evidence {EARLIER_HIT}, attempt 1: a lint rule suppressed" in prompt
    assert "no review judged" in prompt
    assert evaluation_words(prompt) == []


def test_a_prompt_with_no_earlier_attempt_is_the_prompt_it_was(tmp_path: Path) -> None:
    packet, read, _ = _build(tmp_path, earlier=False)
    prompt = review_prompt("control", packet).replace(str(read), "<read>")
    assert "earlier" not in prompt.lower()
    assert hashlib.sha256(prompt.encode()).hexdigest() == BEFORE_SHA256
