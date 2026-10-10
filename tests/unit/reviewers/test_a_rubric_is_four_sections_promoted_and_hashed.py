"""A rubric has ARCH-062's four sections, changes only by promotion, and is loaded by its digest.

A rubric is staged inside the tree only reviewers read, promoted by a person,
and its promotion line records the sha256 of the file as written: the ledger
event for a rubric change. A rubric whose bytes are not its last promoted
version is refused, so a direct edit is caught at the next review.
"""

from __future__ import annotations

import hashlib
import json
from pathlib import Path

import pytest
from rubric_fixture import PLACEHOLDER, PLACEHOLDER_IDS

from physgate.evaluation.inject.corpus import TELLTALES
from physgate.hooks.settings import review_material
from physgate.knowledge import loader, staging
from physgate.knowledge.exceptions import RoleNameError
from physgate.knowledge.promote import _apply, rubric_path
from physgate.reviewers.rubric import (
    EVALUATION_WORDS,
    SECTIONS,
    RubricError,
    check_rubric,
    evaluation_words,
    load_rubric,
)


def _promote(root: Path, text: str, role: str = "control") -> Path:
    """Stage ``text`` as ``role``'s rubric under ``root`` and promote it, as a person would."""
    staged = staging.append(
        "rubric", text, "episode-1", domain=role, staging_root=root / staging.RUBRIC_STAGING_ROOT
    )
    return _apply(
        staged.stem,
        by="a person",
        staging_root=root / staging.STAGING_ROOT,
        knowledge_root=root / "knowledge",
        promotions_path=root / "knowledge" / "promotions.jsonl",
        rubric_staging_root=root / staging.RUBRIC_STAGING_ROOT,
    )


def test_the_placeholder_has_the_form() -> None:
    items = check_rubric(PLACEHOLDER)
    assert tuple(i.id for i in items) == PLACEHOLDER_IDS
    assert [i.section for i in items] == [
        "acceptance_criteria",
        "domain_standards",
        "domain_standards",
        "antipatterns",
        "reward_hacking",
        "reward_hacking",
        "reward_hacking",
    ]


@pytest.mark.parametrize(
    ("text", "match"),
    [
        (
            PLACEHOLDER.replace("## 2. Domain standard violations", "## 2. Domain rules"),
            "no other second-level section",
        ),
        (PLACEHOLDER + "\n## Notes\n\nmore\n", "no other second-level section"),
        (PLACEHOLDER.replace("## Verdict policy", "## 1. Acceptance criteria"), "four"),
        (
            PLACEHOLDER.replace(
                "- **AP-1. An antipattern is present.** One the skill file names.", ""
            ),
            "holds no item",
        ),
        (PLACEHOLDER.replace("**DS-2.", "**DS-1."), "appears twice"),
        (PLACEHOLDER.replace("RH-2. Hard-coded values", "RH-2. Fixed numbers"), "indicator out"),
        (PLACEHOLDER.replace("RH-1. Feature isolation", "RH-1. Narrow features"), "indicator out"),
        (PLACEHOLDER.replace("RH-3. Disabled, skipped", "RH-3. Skipped"), "indicator out"),
        (PLACEHOLDER + "\nKeep the answer key in mind.\n", "being evaluated"),
        (PLACEHOLDER + "\nThe physics gate ran first.\n", "being evaluated"),
    ],
    ids=[
        "renamed",
        "after the required",
        "required in the preamble",
        "empty section",
        "repeated id",
        "no hard-coded values",
        "no feature isolation",
        "no disabled checks",
        "answer",
        "harness name",
    ],
)
def test_a_malformed_rubric_is_refused(text: str, match: str) -> None:
    with pytest.raises(RubricError, match=match):
        check_rubric(text)


def test_the_sections_are_the_architecture_s_four_in_order() -> None:
    assert [title for title, _ in SECTIONS] == [
        "Acceptance criteria",
        "Domain standard violations",
        "Skill-file antipatterns",
        "Reward-hacking indicators",
    ]
    swapped = PLACEHOLDER.replace("## 1. Acceptance criteria", "## X").replace(
        "## 2. Domain standard violations", "## 1. Acceptance criteria"
    )
    with pytest.raises(RubricError):
        check_rubric(swapped.replace("## X", "## 2. Domain standard violations"))


def test_the_review_vocabulary_is_allowed() -> None:
    assert evaluation_words("A wrong unit error, an incorrect bug, a reviewer's mistake.") == []


def test_the_evaluation_words_are_the_instrument_s_own() -> None:
    assert set(EVALUATION_WORDS) <= set(TELLTALES)
    for word in ("planted", "corpora", "twin", "physgate", "expected check", "injected"):
        assert evaluation_words(f"some {word} here"), word


def test_a_promoted_rubric_loads_with_its_digest(tmp_path: Path) -> None:
    destination = _promote(tmp_path, PLACEHOLDER)
    assert destination == rubric_path(tmp_path / "knowledge", "control")
    line = json.loads((tmp_path / "knowledge" / "promotions.jsonl").read_text().splitlines()[-1])
    digest = hashlib.sha256(destination.read_bytes()).hexdigest()
    assert line["kind"] == "rubric" and line["domain"] == "control" and line["sha256"] == digest
    rubric = load_rubric(tmp_path / "knowledge", "control")
    assert rubric.sha256 == digest and rubric.text == destination.read_text()


def test_a_direct_edit_is_refused(tmp_path: Path) -> None:
    destination = _promote(tmp_path, PLACEHOLDER)
    destination.write_text(destination.read_text() + "\n- One more line, never promoted.\n")
    with pytest.raises(RubricError, match="not the version its last promotion recorded"):
        load_rubric(tmp_path / "knowledge", "control")


def test_a_rubric_never_promoted_is_refused(tmp_path: Path) -> None:
    path = rubric_path(tmp_path / "knowledge", "control")
    path.parent.mkdir(parents=True)
    path.write_text(PLACEHOLDER)
    with pytest.raises(RubricError, match="not the version"):
        load_rubric(tmp_path / "knowledge", "control")


def test_a_later_promotion_is_the_version_loaded(tmp_path: Path) -> None:
    _promote(tmp_path, PLACEHOLDER)
    second = PLACEHOLDER + "\n"
    _promote(tmp_path, second.replace("Used by the test suite only.", "Second version."))
    rubric = load_rubric(tmp_path / "knowledge", "control")
    assert "Second version." in rubric.text
    lines = (tmp_path / "knowledge" / "promotions.jsonl").read_text().splitlines()
    assert len(lines) == 2


def test_a_missing_rubric_and_an_unsafe_role_are_refused(tmp_path: Path) -> None:
    with pytest.raises(RubricError, match="no rubric"):
        load_rubric(tmp_path / "knowledge", "control")
    with pytest.raises(RubricError, match="plain lower-case"):
        load_rubric(tmp_path / "knowledge", "../control")


def test_a_rubric_is_staged_and_promoted_inside_the_withheld_tree(tmp_path: Path) -> None:
    worktree = tmp_path / "checkout"
    (withheld,) = review_material(worktree, None)
    assert staging.staging_root_for("rubric") == staging.RUBRIC_STAGING_ROOT
    assert (worktree / staging.RUBRIC_STAGING_ROOT).is_relative_to(withheld)
    assert rubric_path(worktree / "knowledge", "control").is_relative_to(withheld)
    assert not (worktree / staging.STAGING_ROOT).is_relative_to(withheld)


@pytest.mark.parametrize("role", ["control", "firmware", "electrical", "mechanical"])
def test_no_role_loads_or_must_read_a_rubric(role: str) -> None:
    paths = [*loader.always_loaded(role), *loader.required_reading(role, Path("specs/x.md"))]
    assert paths
    assert not [p for p in paths if "reviewers" in p.parts]


@pytest.mark.parametrize("name", ["reviewers", "staging"])
def test_the_withheld_tree_and_staging_are_no_role_s(name: str) -> None:
    with pytest.raises(RoleNameError, match="no role's files"):
        loader.always_loaded(name)


def test_the_library_copy_into_a_target_never_takes_a_rubric(tmp_path: Path) -> None:
    from knowledge_fixture import write_fixture

    from physgate.knowledge.library import read_library

    write_fixture(tmp_path, ("cross", "control"))
    _promote(tmp_path, PLACEHOLDER)
    copied = read_library(tmp_path, ["control"])
    assert copied
    assert not [p for p in copied if "reviewers" in p.parts]
