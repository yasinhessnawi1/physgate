"""The generalist rubric is the role's promoted rubric with its two domain sections left out.

ARCH-063's baseline holds everything but the domain fixed: the same reviewer,
model and artefact, and a rubric made by code from the paired one. Its domain
sections keep their headings, each followed by one fixed line; every other byte
is the promoted rubric's, its canary line included. The same paired rubric always
gives the same bytes. The section rule takes the kind, a generalist rubric is never
loaded as a role's rubric, and its review is shown only what every role reads.
"""

from __future__ import annotations

import hashlib
import json
import re
from pathlib import Path

import pytest
from knowledge_fixture import write_fixture
from packet_fixture import ISSUED, SPEC, artefact_of, make_attempt, stream
from rubric_fixture import PLACEHOLDER

from physgate.knowledge import staging
from physgate.knowledge.exceptions import KnowledgeError
from physgate.knowledge.promote import _apply, rubric_path
from physgate.orchestrator.protocols import IssuedSpec
from physgate.reviewers.packet import KNOWLEDGE_NAME, build_packet
from physgate.reviewers.rubric import (
    NOT_IN_REVIEW,
    Rubric,
    RubricError,
    check_rubric,
    generalist_of,
    load_rubric,
    parse_rubric,
)
from physgate.reviewers.verdict import Answered, Unavailable, judge

CANARY = "\n<!-- 0123456789abcdef0123456789abcdef -->\n"


def _paired(text: str = PLACEHOLDER + CANARY) -> Rubric:
    return Rubric(
        role="control",
        text=text,
        sha256=hashlib.sha256(text.encode()).hexdigest(),
        items=check_rubric(text),
    )


def _outside_domain(text: str) -> list[str]:
    """The lines outside the two domain sections, their headings kept."""
    kept, skipping = [], False
    for line in text.splitlines(keepends=True):
        if line.startswith("## "):
            skipping = "Domain standard" in line or "antipatterns" in line
            kept.append(line)
        elif not skipping:
            kept.append(line)
    return kept


def test_the_generalist_keeps_every_byte_but_the_domain_sections() -> None:
    paired = _paired()
    generalist = generalist_of(paired)
    assert (generalist.kind, generalist.role) == ("generalist", "control")
    assert generalist.sha256 == hashlib.sha256(generalist.text.encode()).hexdigest()
    assert _outside_domain(generalist.text) == _outside_domain(paired.text)
    assert generalist.text.endswith(CANARY)
    assert generalist.text.count(NOT_IN_REVIEW) == 2
    assert "DS-1" not in generalist.text and "AP-1" not in generalist.text
    assert "### A subheading" not in generalist.text
    assert [i.id for i in generalist.items] == ["AC-1", "RH-1", "RH-2", "RH-3"]


def test_the_same_paired_rubric_always_gives_the_same_generalist() -> None:
    assert generalist_of(_paired()).sha256 == generalist_of(_paired()).sha256
    assert generalist_of(_paired()).text == generalist_of(_paired()).text


def test_the_section_rule_takes_the_kind() -> None:
    generalist = generalist_of(_paired()).text
    with pytest.raises(RubricError, match="holds no item"):
        parse_rubric(generalist)  # a paired rubric needs items in all four
    assert parse_rubric(generalist, "generalist")
    with pytest.raises(RubricError, match="no item under a domain section"):
        parse_rubric(PLACEHOLDER, "generalist")
    without_criteria = re.sub(r"- \*\*AC-1\..*\n", "", generalist)
    with pytest.raises(RubricError, match="holds no item"):
        parse_rubric(without_criteria, "generalist")


def test_a_generalist_is_made_only_from_a_paired_rubric() -> None:
    with pytest.raises(RubricError, match="paired rubric"):
        generalist_of(generalist_of(_paired()))


def test_a_generalist_text_is_never_loaded_as_a_role_s_rubric(tmp_path: Path) -> None:
    text = generalist_of(_paired(PLACEHOLDER)).text
    staged = staging.append(
        "rubric", text, "episode-1", domain="control", staging_root=tmp_path / "rs"
    )
    with pytest.raises((KnowledgeError, RubricError)):
        _apply(
            staged.stem,
            by="a person",
            staging_root=tmp_path / staging.STAGING_ROOT,
            knowledge_root=tmp_path / "knowledge",
            promotions_path=tmp_path / "knowledge" / "promotions.jsonl",
            rubric_staging_root=tmp_path / "rs",
        )
    assert not rubric_path(tmp_path / "knowledge", "control").exists()
    # Written in place with a promotion line that names its bytes: still refused.
    knowledge = tmp_path / "knowledge"
    path = rubric_path(knowledge, "control")
    path.parent.mkdir(parents=True)
    path.write_text(text)
    digest = hashlib.sha256(text.encode()).hexdigest()
    line = {"kind": "rubric", "domain": "control", "sha256": digest}
    (knowledge / "promotions.jsonl").write_text(json.dumps(line) + "\n")
    with pytest.raises(RubricError, match="holds no item"):
        load_rubric(knowledge, "control")


def test_every_generalist_item_is_answered_and_no_domain_item_is() -> None:
    items = generalist_of(_paired()).items

    def answer(*ids: tuple[str, str]) -> dict[str, object]:
        return {
            "verdict": "accept",
            "finding": "every item is met",
            "failing_item": None,
            "subject": None,
            "numeric_output": None,
            "items": [
                {
                    "item": i,
                    "section": s,
                    "result": "not observed" if s == "reward_hacking" else "met",
                    "evidence": "diff.patch: 1",
                }
                for i, s in ids
            ],
            "acceptance_criteria": [{"criterion": "1", "result": "met", "evidence": "x:1"}],
            "indicators": [],
            "spec_defects": [],
        }

    every = [("AC-1", "acceptance_criteria")] + [(f"RH-{n}", "reward_hacking") for n in (1, 2, 3)]
    assert isinstance(judge(answer(*every), (), items), Answered)
    assert isinstance(judge(answer(*every[:-1]), (), items), Unavailable)
    extra = judge(answer(*every, ("DS-1", "domain_standards")), (), items)
    assert isinstance(extra, Unavailable) and "DS-1" in extra.detail


def test_a_generalist_review_is_shown_only_what_every_role_reads(tmp_path: Path) -> None:
    attempt = make_attempt(tmp_path, stream())
    library = tmp_path / "harness"
    write_fixture(library, ("cross", "control"))
    spec = IssuedSpec(
        commit=attempt.spec_commit, path=SPEC, sha256=hashlib.sha256(ISSUED.encode()).hexdigest()
    )
    shown = {}
    for name, rubric in (("paired", _paired()), ("generalist", generalist_of(_paired()))):
        review = tmp_path / "reviews" / f"r{'0' if name == 'paired' else '1'}123456789ab"
        packet = build_packet(
            review,
            artefact_of(attempt),
            repo=attempt.worktree,
            base_commit=attempt.spec_commit,
            rubric=rubric,
            library=library,
            spec=spec,
        )
        files = (review / "read" / KNOWLEDGE_NAME).rglob("*")
        read = review / "read"
        shown[name] = sorted(p.relative_to(read).as_posix() for p in files if p.is_file())
        assert packet.rubric_sha256 == rubric.sha256
    assert shown["paired"] == [
        "knowledge/control/skill.md",
        "knowledge/control/standards.md",
        "knowledge/cross/standards.md",
    ]
    assert shown["generalist"] == ["knowledge/cross/standards.md"]
