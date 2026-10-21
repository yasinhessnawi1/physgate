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
from physgate.reviewers.rubric import ITEM_PREFIXES, check_rubric, evaluation_words, load_rubric
from physgate.reviewers.scan import ScanHit
from physgate.reviewers.verdict import Answered, Unavailable, judge

#: role: (each approved version, oldest first, as its drafting directory, the sha256 of its
#: file and its item count; id prefix per section)
APPROVED = {
    "control": (
        (
            ("final", "b45abf4d37895942490c4cd4f097a18a45068b10699958f590e5d049519f24c6", 55),
            # Corrected: a zero or delay limit counts only what every fed-back output shares.
            ("final_v2", "17e9fafbe883d28bd2ce0b092cd39327982db0bb46b3cdd9ca753fdecfcdf66f", 55),
            # The automated checks are listed, never a reason to skip a check; a revision issued
            # with no specification and no trajectory is judged on what it wrote, a condition of
            # the design it changes being recorded, not charged to it.
            ("final_v3", "af736f6a827f204fcf57c04ce4315bf868a82feca52f5425afe274e777a8eea9", 56),
            # Given values are decided per value written, never per node; missing evidence has
            # one rule, unmet when every input was there, not evaluable when one is missing.
            ("final_v4", "39d54707edfbd283e1b39a3fd98d6900b105b812647bbbd3731fa4ec8f852a8f", 56),
            # A duty of the work is decided per check, by whether it involves a written value,
            # never by which node the revision wrote.
            ("final_v5", "1388fe4a74c08aee4f736e2c1498549bd871f8dafe70cea773ac6ac5dd78e053", 56),
            # A record the work owes that a proposed revision did not write is noted, never
            # unmet: what rejects is what is written (the calibration round's text).
            ("final_v6", "d415614e0256ba66836fd44ec210d543b62ebe17cdf730d093e62c6032a6ff58", 56),
            # A sub-check whose input the account lists as absent from a stand-in design is
            # noted, never blocked and never unmet; everything else is judged as before.
            ("final_v7", "239abc99afc21f133d27377d3daae6f3f62914f76c0fa2d7d9ee2ddf723bf506", 56),
        ),
        ("A", "D", "S", "R"),
    ),
    "firmware": (
        (
            ("final", "a89e71572901d4a2d44c27f3f9029d2817c714ca1c2926e47965de1c9498c1ce", 53),
            # The same two changes as control's third version.
            ("final_v2", "4ee697be3577a11048eb504513c0d1c0996bf935eb09f033f254c694061b3357", 54),
            # The same two clarifications as control's fourth version.
            ("final_v3", "44461085e65aeec5bdada9d7f404e4a649c499ac1f324f5ede5364f3e7362200", 54),
            # The same per-check duty as control's fifth version.
            ("final_v4", "a741381dfd3703f6a49eded46e20b402fbb8949f2ad8ad7e6d07ac52999c8989", 54),
            # The same unwritten-records rule as control's sixth version.
            ("final_v5", "23f3695b69e3bd73b38caba4bdf1239c46231e47f7e2381027de7c6974543698", 54),
            # The same stand-in-absences rule as control's seventh version.
            ("final_v6", "6e34b7524282e98923983e075f81b9f603d398f3ec79d1c92f0fada1562603fe", 54),
        ),
        ("AC", "DS", "AP", "RH"),
    ),
    "electrical": (
        (
            ("final", "8d989189695fad474ee0ab60e0fe8bc2b685e2f356ca5d551dd29cba45565dcf", 66),
            # The same two clarifications as control's fourth version.
            ("final_v2", "e2d0bb8e2f50014f2d40e2545fdf5224fdea85ae4c9a3d1989239612e9312f24", 66),
            # The same per-check duty as control's fifth version.
            ("final_v3", "a1858e681ca2aee87e4b1c669c4619f006c9d5d05634c20f8a477c77f941e2e9", 66),
            # The same unwritten-records rule as control's sixth version.
            ("final_v4", "3eeb546ec900cbcb615b8dcb5fd2ece89f43514de128aab4916448e976efb712", 66),
            # The same stand-in-absences rule as control's seventh version.
            ("final_v5", "02f4afd8f51f7fc2e87f10d47190fc966674ecfe3b8d0e4631407366f318e793", 66),
        ),
        ("EA", "ES", "EP", "EH"),
    ),
    "mechanical": (
        (
            ("final", "b53ae125c8e63c22794c708f7dc28eba923c5cc7901d47b488873dad94203e09", 61),
            # The same two clarifications as control's fourth version.
            ("final_v2", "5a19d543316e4154518c407c1df8df1802a98e7b891e195491f2cd6ac66b3836", 61),
            # The same per-check duty as control's fifth version; no label points at a document
            # the reviewer is not given.
            ("final_v3", "33e39c6c0fc1980751cc9d7bdc8772896497e8192343831a0ad25a12c8a5d7e1", 61),
            # The same unwritten-records rule as control's sixth version.
            ("final_v4", "d07b7f4722f64da7d0d08bf5c68ae99801d22397c4401ad95f1e9b37cf508653", 61),
            # The same stand-in-absences rule as control's seventh version.
            ("final_v5", "d63d5daf943790c9c726907794483d6185d8bfdaf841cadc66d504762abb58d0", 61),
        ),
        ("MA", "MS", "MP", "MH"),
    ),
    "integration": (
        (("final", "68b7b1ac4af9f821078c18891729b055ee086fc285a6ddefb5c498192fac198e", 57),),
        ("IA", "IS", "IP", "IH"),
    ),
    "design": (
        (("final", "04aa9d73f433efcf10376b5be74e74a2397ef66d653441a61e52819996931c67", 65),),
        ("PA", "PS", "PP", "PH"),
    ),
}
VERSIONS = [(role, folder) for role, (versions, _) in APPROVED.items() for folder, _, _ in versions]
_CANARY = re.compile(rb"\n\n<!-- [0-9a-f]{32} -->\n\Z")
SECTION_ORDER = ("acceptance_criteria", "domain_standards", "antipatterns", "reward_hacking")


def _digest(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _digests(role: str) -> dict[str, str]:
    """Each approved version of ``role``'s rubric, oldest first: its folder and its sha256."""
    return {folder: digest for folder, digest, _ in APPROVED[role][0]}


def _count(role: str, folder: str) -> int:
    """How many items the approved version ``folder`` of ``role``'s rubric holds."""
    return next(count for name, _, count in APPROVED[role][0] if name == folder)


def _promoted(role: str) -> bytes | None:
    """The promoted copy, its canary line set aside; ``None`` if none is promoted."""
    path = Path("knowledge") / "reviewers" / role / "rubric.md"
    return _CANARY.sub(b"\n", path.read_bytes()) if path.is_file() else None


def _approved(role: str, folder: str | None = None) -> bytes:
    """One approved version of ``role``'s rubric, the latest unless ``folder`` names one."""
    versions = _digests(role)
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


def test_the_pinned_prefixes_are_the_registered_ones() -> None:
    for role, (_, prefixes) in APPROVED.items():
        assert ITEM_PREFIXES[role] == prefixes, role


@pytest.mark.parametrize("role", sorted(APPROVED))
def test_the_promoted_rubric_is_an_approved_version(role: str) -> None:
    promoted = _promoted(role)
    if promoted is None:
        pytest.skip(f"no {role} rubric is promoted here")
    assert _digest(promoted) in _digests(role).values(), role


@pytest.mark.parametrize("role", sorted(APPROVED))
def test_a_staged_rubric_is_the_latest_approved_version(role: str) -> None:
    latest = list(_digests(role).values())[-1]
    staged = [c for c in staging.candidates("rubric") if c.domain == role]
    for candidate in staged:
        text = candidate.content.rstrip() + "\n"  # what promotion writes, before its canary
        assert _digest(text.encode()) == latest, candidate.candidate_id


@pytest.mark.parametrize(("role", "folder"), VERSIONS)
def test_the_approved_rubric_parses_as_it_is(role: str, folder: str) -> None:
    text = _approved(role, folder).decode("utf-8")
    items = check_rubric(text)
    prefixes = ITEM_PREFIXES[role]
    assert len(items) == _count(role, folder)
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
    assert len(loaded.items) == _count(role, folder)
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
