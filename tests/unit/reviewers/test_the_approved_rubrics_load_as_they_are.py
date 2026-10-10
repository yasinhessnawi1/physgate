"""The approved rubrics load as they are, byte for byte, and every item must be answered.

Their content went through rounds of adversarial review; the loader adapts to
their form, not the reverse. Each approved version is pinned here by its sha256:
a corrected rubric is a new version, approved the same way, and an earlier one
stays pinned, since runs judged with it. The promoted copy in the library (with
the canary line that promotion appends set aside) must be one of its role's
approved versions, and a staged rubric must be the latest. Each version is read
from the promoted copy when that is the version, and otherwise from the frozen
file the drafting track left, named by ``PHYSGATE_FROZEN_RUBRICS`` or found in
the drafting workspace. Where neither exists, as on a machine that has not seen
the drafts, it skips and says so.
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

#: role: (each approved version, oldest first, as its drafting directory and the sha256
#: of its file; item count; id prefix per section)
APPROVED = {
    "control": (
        (
            ("final", "b45abf4d37895942490c4cd4f097a18a45068b10699958f590e5d049519f24c6"),
            # Corrected: a zero or delay limit counts only what every fed-back output shares.
            ("final_v2", "17e9fafbe883d28bd2ce0b092cd39327982db0bb46b3cdd9ca753fdecfcdf66f"),
        ),
        55,
        ("A", "D", "S", "R"),
    ),
    "firmware": (
        (("final", "a89e71572901d4a2d44c27f3f9029d2817c714ca1c2926e47965de1c9498c1ce"),),
        53,
        ("AC", "DS", "AP", "RH"),
    ),
}
VERSIONS = [(role, folder) for role, (versions, _, _) in APPROVED.items() for folder, _ in versions]
_CANARY = re.compile(rb"\n\n<!-- [0-9a-f]{32} -->\n\Z")
SECTION_ORDER = ("acceptance_criteria", "domain_standards", "antipatterns", "reward_hacking")


def _digest(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _promoted(role: str) -> bytes | None:
    """The promoted copy, its canary line set aside; ``None`` if none is promoted."""
    path = Path("knowledge") / "reviewers" / role / "rubric.md"
    return _CANARY.sub(b"\n", path.read_bytes()) if path.is_file() else None


def _approved(role: str, folder: str | None = None) -> bytes:
    """One approved version of ``role``'s rubric, the latest unless ``folder`` names one."""
    versions = dict(APPROVED[role][0])
    folder = folder or list(versions)[-1]
    digest = versions[folder]
    promoted = _promoted(role)
    if promoted is not None and _digest(promoted) == digest:
        return promoted
    drafts = Path(os.environ.get("PHYSGATE_FROZEN_RUBRICS", Path.home() / "rubric-drafting"))
    path = drafts / role / folder / "rubric.md"
    if path.is_file():
        data = path.read_bytes()
        if _digest(data) == digest:
            return data
        pytest.fail(f"{path} is not the approved {role} rubric")
    pytest.skip(f"the approved {role} rubric ({folder}) is not on this machine")


@pytest.mark.parametrize("role", sorted(APPROVED))
def test_the_promoted_rubric_is_an_approved_version(role: str) -> None:
    promoted = _promoted(role)
    if promoted is None:
        pytest.skip(f"no {role} rubric is promoted here")
    assert _digest(promoted) in dict(APPROVED[role][0]).values(), role


@pytest.mark.parametrize("role", sorted(APPROVED))
def test_a_staged_rubric_is_the_latest_approved_version(role: str) -> None:
    latest = list(dict(APPROVED[role][0]).values())[-1]
    staged = [c for c in staging.candidates("rubric") if c.domain == role]
    for candidate in staged:
        text = candidate.content.rstrip() + "\n"  # what promotion writes, before its canary
        assert _digest(text.encode()) == latest, candidate.candidate_id


@pytest.mark.parametrize(("role", "folder"), VERSIONS)
def test_the_approved_rubric_parses_as_it_is(role: str, folder: str) -> None:
    text = _approved(role, folder).decode("utf-8")
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


@pytest.mark.parametrize(("role", "folder"), VERSIONS)
def test_a_verdict_must_answer_every_approved_item(role: str, folder: str) -> None:
    items = check_rubric(_approved(role, folder).decode("utf-8"))
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


@pytest.mark.parametrize(("role", "folder"), VERSIONS)
def test_the_approved_rubric_promoted_loads_with_its_canary(
    role: str, folder: str, tmp_path: Path
) -> None:
    text = _approved(role, folder).decode("utf-8")
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
