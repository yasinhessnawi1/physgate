"""A reviewer is told where the earlier unjudged attempts' markers are shown, and each marker.

The prompt names, beside the attempt's own trajectory, the parts that show each marker of the
earlier attempts with the lines around it, then those attempts' whole streams, to read where the
lines around a marker are not enough; it lists each marker the scan found in them with the attempt
it is from, to be answered as one of the attempt's own is. Nothing is added to the prompt of a
review with no earlier attempt: it is byte for byte the prompt it was before.
"""

from __future__ import annotations

import hashlib
from pathlib import Path

from test_a_review_is_given_the_hits_no_earlier_review_judged import EARLIER_HIT, _build

from physgate.reviewers.claude import review_prompt
from physgate.reviewers.packet import Part
from physgate.reviewers.rubric import evaluation_words

#: The prompt of the fixture's review with no earlier attempt, its read directory written
#: ``<read>``, as the reviewer was told it before earlier attempts were put before it.
BEFORE_SHA256 = "3d86da0ecf0711e36c34814e1c608efbbcf26d7a22907ac82ce6a5bded9fa1d7"


REASON_SENTENCE = (
    "The reason of every indicator you give, confirmed or dismissed, is written the same way: "
    "in words, never a single word."
)

#: The same prompt with the sentence about an indicator's reason added to its shape paragraph.
AFTER_SHA256 = "f59a02b457c470c2db09e8c0151452bc84a6e973437ba8a347f8de29e5194e21"

#: The reading-list lines for the earlier attempts, and the clause of the earlier markers'
#: paragraph that says where they are shown, as the owner approved them (15.11.2026).
EXCERPTS_LINE = (
    ": for each marker found in earlier attempts of this subtask that no review judged, the tool "
    "call and its result with the lines around them, each headed by the earlier part and lines it "
    "is cut from.\n"
)
WHOLE_LINE = (
    ": those attempts' whole trajectories, in numbered parts. Read any of them where the lines "
    "around a marker are not enough to judge it.\n"
)
SHOWN_CLAUSE = (
    "Earlier attempts of this subtask that no review judged are shown around each marker in the "
    "parts listed above; their work is in the commit you review."
)
#: The prompt of the fixture's review with an earlier attempt, its read directory written
#: ``<read>``: its first pin, taken with the excerpts.
WITH_EARLIER_SHA256 = "3f2c60b576502229c2f806a7915afab6130e0f57bc761d5fafaaba98699a9213"


def _named(read: Path, parts: tuple[Part, ...]) -> str:
    if len(parts) == 1:
        return str(read / parts[0].name)
    return f"{read / parts[0].name} to {read / parts[-1].name} ({len(parts)} parts)"


def test_the_prompt_names_the_earlier_parts_and_each_earlier_marker_with_its_attempt(
    tmp_path: Path,
) -> None:
    packet, read, _ = _build(tmp_path)
    prompt = review_prompt("control", packet)
    excerpts: tuple[Part, ...] = getattr(packet, "earlier_hit_parts", ())
    assert excerpts, "the packet shows no earlier marker with the lines around it"
    listed = f"- {_named(read, excerpts)}{EXCERPTS_LINE}- {_named(read, packet.earlier_parts)}"
    assert listed + WHOLE_LINE in prompt
    assert SHOWN_CLAUSE in prompt
    assert "the trajectories of earlier attempts" not in prompt
    assert "earlier parts listed above" not in prompt
    assert f"- disabled_checks, evidence {EARLIER_HIT}, attempt 1: a lint rule suppressed" in prompt
    assert "no review judged" in prompt
    # Each answer names the attempt as well as the evidence, and decides: noted is no answer.
    assert "names the same evidence and the same attempt, confirmed or dismissed" in prompt
    assert evaluation_words(prompt) == []


def test_the_prompt_with_an_earlier_attempt_is_its_pin(tmp_path: Path) -> None:
    packet, read, _ = _build(tmp_path)
    prompt = review_prompt("control", packet).replace(str(read), "<read>")
    assert hashlib.sha256(prompt.encode()).hexdigest() == WITH_EARLIER_SHA256


def test_a_prompt_with_no_earlier_attempt_is_the_prompt_it_was(tmp_path: Path) -> None:
    packet, read, _ = _build(tmp_path, earlier=False)
    prompt = review_prompt("control", packet).replace(str(read), "<read>")
    assert "earlier" not in prompt.lower()
    # Nothing else changed: take the one sentence out and it is the prompt it was.
    assert hashlib.sha256(prompt.replace(" " + REASON_SENTENCE, "").encode()).hexdigest() == (
        BEFORE_SHA256
    )
    assert hashlib.sha256(prompt.encode()).hexdigest() == AFTER_SHA256


def test_every_review_prompt_tells_the_reason_of_an_indicator_is_never_a_single_word(
    tmp_path: Path,
) -> None:
    for earlier in (True, False):
        packet, _, _ = _build(tmp_path / str(earlier), earlier=earlier)
        prompt = review_prompt("control", packet)
        assert prompt.count(REASON_SENTENCE) == 1
        assert "is refused and asked for again. " + REASON_SENTENCE in prompt
