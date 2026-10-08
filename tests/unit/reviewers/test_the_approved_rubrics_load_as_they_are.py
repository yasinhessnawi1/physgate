"""The two approved rubrics load as they are, byte for byte, and every item must be answered.

Their content went through rounds of adversarial review; the loader adapts to
their form, not the reverse. Each is pinned here by its sha256. The test reads
the promoted copy in the library when there is one (with the canary line that
promotion appends set aside), and otherwise the frozen file the drafting track
left, named by ``PHYSGATE_FROZEN_RUBRICS`` or found in the drafting workspace.
Where neither exists, as on a machine that has not seen the drafts, it skips and
says so.
"""

from __future__ import annotations

import hashlib
import os
import re
from pathlib import Path

import pytest

from physgate.knowledge import staging
from physgate.knowledge.promote import _apply, rubric_path
from physgate.reviewers.rubric import check_rubric, evaluation_words, load_rubric
from physgate.reviewers.scan import ScanHit
from physgate.reviewers.verdict import Answered, Unavailable, judge

#: role: (sha256 of the approved file, item count, id prefix per section)
APPROVED = {
    "control": (
        "b45abf4d37895942490c4cd4f097a18a45068b10699958f590e5d049519f24c6",
        55,
        ("A", "D", "S", "R"),
    ),
    "firmware": (
        "a89e71572901d4a2d44c27f3f9029d2817c714ca1c2926e47965de1c9498c1ce",
        53,
        ("AC", "DS", "AP", "RH"),
    ),
}
_CANARY = re.compile(rb"\n\n<!-- [0-9a-f]{32} -->\n\Z")
SECTION_ORDER = ("acceptance_criteria", "domain_standards", "antipatterns", "reward_hacking")


def _approved(role: str) -> bytes:
    digest = APPROVED[role][0]
    promoted = Path("knowledge") / "reviewers" / role / "rubric.md"
    drafts = Path(os.environ.get("PHYSGATE_FROZEN_RUBRICS", Path.home() / "rubric-drafting"))
    for path, strip in ((promoted, True), (drafts / role / "final" / "rubric.md", False)):
        if path.is_file():
            data = path.read_bytes()
            body = _CANARY.sub(b"\n", data) if strip else data
            if hashlib.sha256(body).hexdigest() == digest:
                return body
            pytest.fail(f"{path} is not the approved {role} rubric")
    pytest.skip(f"the approved {role} rubric is not on this machine")


@pytest.mark.parametrize("role", sorted(APPROVED))
def test_the_approved_rubric_parses_as_it_is(role: str) -> None:
    text = _approved(role).decode("utf-8")
    items = check_rubric(text)
    _, count, prefixes = APPROVED[role]
    assert len(items) == count
    assert evaluation_words(text) == []
    for section, prefix in zip(SECTION_ORDER, prefixes, strict=True):
        ids = [i.id for i in items if i.section == section]
        assert ids and all(re.fullmatch(rf"{prefix}-?[0-9]+", i) for i in ids), (section, ids)


def _answer(items: list[dict[str, str]]) -> dict[str, object]:
    return {
        "verdict": "accept",
        "finding": "every item is met",
        "failing_item": None,
        "subject": None,
        "numeric_output": None,
        "items": items,
        "acceptance_criteria": [{"criterion": "1", "result": "met", "evidence": "x:1"}],
        "indicators": [],
        "spec_defects": [],
    }


@pytest.mark.parametrize("role", sorted(APPROVED))
def test_a_verdict_must_answer_every_approved_item(role: str) -> None:
    items = check_rubric(_approved(role).decode("utf-8"))
    every = [
        {
            "item": i.id,
            "section": i.section,
            "result": "not observed" if i.section == "reward_hacking" else "met",
            "evidence": "diff: m/x.c:1",
        }
        for i in items
    ]
    assert isinstance(judge(_answer(every), (), items), Answered)
    for left_out in (0, len(every) // 2, len(every) - 1):
        partial = every[:left_out] + every[left_out + 1 :]
        outcome = judge(_answer(partial), (), items)
        assert isinstance(outcome, Unavailable) and outcome.cause == "invalid_verdict"
        assert items[left_out].id in outcome.detail


@pytest.mark.parametrize("role", sorted(APPROVED))
def test_the_approved_rubric_promoted_loads_with_its_canary(role: str, tmp_path: Path) -> None:
    text = _approved(role).decode("utf-8")
    staged = staging.append(
        "rubric", text, "approved", domain=role, staging_root=tmp_path / staging.RUBRIC_STAGING_ROOT
    )
    _apply(
        staged.stem,
        by="a person",
        staging_root=tmp_path / staging.STAGING_ROOT,
        knowledge_root=tmp_path / "knowledge",
        promotions_path=tmp_path / "knowledge" / "promotions.jsonl",
        rubric_staging_root=tmp_path / staging.RUBRIC_STAGING_ROOT,
    )
    loaded = load_rubric(tmp_path / "knowledge", role)
    assert len(loaded.items) == APPROVED[role][1]
    promoted = rubric_path(tmp_path / "knowledge", role).read_bytes()
    assert _CANARY.sub(b"\n", promoted) == text.encode()


def test_a_scan_hit_must_be_answered_against_an_approved_rubric_too() -> None:
    items = check_rubric(_approved("firmware").decode("utf-8"))
    every = [
        {
            "item": i.id,
            "section": i.section,
            "result": "not observed" if i.section == "reward_hacking" else "met",
            "evidence": "diff: m/x.c:1",
        }
        for i in items
    ]
    hit = ScanHit(kind="disabled_checks", evidence="t9", what="a lint rule suppressed")
    outcome = judge(_answer(every), (hit,), items)
    assert isinstance(outcome, Unavailable) and "t9" in outcome.detail
