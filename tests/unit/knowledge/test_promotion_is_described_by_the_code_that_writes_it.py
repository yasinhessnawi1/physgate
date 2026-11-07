"""What a promotion would write is computed by the code that writes it, and by nothing else.

The operator UI shows a staged candidate's effect before anyone promotes it: whether it creates
the file, adds to it or replaces it whole, and the bytes the file would then hold. If the UI
computed those bytes itself, its description could drift from the write the terminal makes, and
the screen would describe a promotion that does not happen. So the arithmetic lives in one pure
function, ``promotion_bytes``, which the write calls; and the finder the write uses to locate a
candidate is public as ``find_staged``, unchanged.

Each case below stages a candidate in a library, asks ``promotion_bytes`` what promoting it would
write, then promotes it with the real write in that library and compares the file's bytes. The
write calls the function, so that comparison alone would pass a wrong function; each case also
pins the exact bytes the file must hold, written out here. For a rubric, the write appends its
opaque canary line after the computed bytes, and the function never does: the UI must never
hold a canary.

``promotion_bytes`` is pure: it opens no file, and it needs no terminal (the suite's stdin is
not one, so a terminal check inside it would refuse here).
"""

from __future__ import annotations

import hashlib
import json
import os
import sys
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path

import pytest

from physgate.knowledge import promote as promotion
from physgate.knowledge import staging
from physgate.knowledge.promote import PromotionError, _apply, find_staged, promotion_bytes
from physgate.knowledge.staging import Candidate, Kind

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "reviewers"))
from rubric_fixture import PLACEHOLDER  # noqa: E402

#: Content with trailing blank lines and spaces, so a write that keeps them differs from one
#: that trims them.
CONTENT = "# A proposed text\n\nOne rule, stated once.   \n\n\n"

EXISTING_STANDARDS = b"# Control standards\n\nThe rule as promoted.\n"
EXISTING_SKILL = b"# Control skill\n\nA promoted pattern.\n"

#: ``CONTENT`` as every write puts it in a file: trailing space trimmed, one newline.
WRITTEN = b"# A proposed text\n\nOne rule, stated once.\n"
#: ``CONTENT`` added after control's skill: what the file held, a rule, then the content.
ADDED = (
    b"# Control skill\n\nA promoted pattern.\n"
    b"\n---\n\n"
    b"# A proposed text\n\nOne rule, stated once.\n"
)


@pytest.fixture
def library(tmp_path: Path) -> Path:
    """A checkout-like root whose library holds control's standards and skill, nothing else."""
    knowledge = tmp_path / "knowledge"
    (knowledge / "control").mkdir(parents=True)
    (knowledge / "control" / "standards.md").write_bytes(EXISTING_STANDARDS)
    (knowledge / "control" / "skill.md").write_bytes(EXISTING_SKILL)
    return tmp_path


def _stage(root: Path, kind: Kind, domain: str, *, replaces: bool = False) -> Path:
    content = PLACEHOLDER if kind == "rubric" else CONTENT
    staged_under = staging.RUBRIC_STAGING_ROOT if kind == "rubric" else staging.STAGING_ROOT
    return staging.append(
        kind,
        content,
        "episode-1",
        domain=domain,
        staging_root=root / staged_under,
        replaces=replaces,
    )


def _promote(root: Path, candidate_id: str) -> Path:
    return _apply(
        candidate_id,
        by="a person",
        staging_root=root / staging.STAGING_ROOT,
        knowledge_root=root / "knowledge",
        promotions_path=root / "knowledge" / "promotions.jsonl",
        rubric_staging_root=root / staging.RUBRIC_STAGING_ROOT,
    )


def _last_promotion(root: Path) -> dict[str, object]:
    lines = (root / "knowledge" / "promotions.jsonl").read_text().splitlines()
    record: dict[str, object] = json.loads(lines[-1])
    return record


CASES = [
    # (name, kind, domain, replaces, destination, whole as the function states it, the bytes)
    (
        "standards replacing a file",
        "standards",
        "control",
        False,
        "control/standards.md",
        True,
        WRITTEN,
    ),
    (
        "standards creating a file",
        "standards",
        "electrical",
        False,
        "electrical/standards.md",
        True,
        WRITTEN,
    ),
    ("skill creating a file", "skill", "electrical", False, "electrical/skill.md", False, WRITTEN),
    ("skill adding to a file", "skill", "control", False, "control/skill.md", False, ADDED),
    ("skill replacing a file whole", "skill", "control", True, "control/skill.md", True, WRITTEN),
    (
        "antipattern adding to a file",
        "antipattern",
        "control",
        False,
        "control/skill.md",
        False,
        ADDED,
    ),
    (
        "antipattern creating a file",
        "antipattern",
        "firmware",
        False,
        "firmware/skill.md",
        False,
        WRITTEN,
    ),
]


@pytest.mark.parametrize(
    ("kind", "domain", "replaces", "destination", "whole", "golden"),
    [case[1:] for case in CASES],
    ids=[case[0] for case in CASES],
)
def test_the_bytes_described_are_the_bytes_the_promotion_writes(
    library: Path,
    kind: Kind,
    domain: str,
    replaces: bool,
    destination: str,
    whole: bool,
    golden: bytes,
) -> None:
    staged = _stage(library, kind, domain, replaces=replaces)
    candidate = Candidate.model_validate_json(staged.read_text())
    target = library / "knowledge" / destination
    current = target.read_bytes() if target.exists() else None
    described, described_whole = promotion_bytes(candidate, kind, current)
    assert described_whole is whole
    assert described == golden
    written_to = _promote(library, candidate.candidate_id)
    assert written_to == target
    assert target.read_bytes() == golden
    assert _last_promotion(library)["sha256"] == hashlib.sha256(golden).hexdigest()


def test_a_whole_write_or_a_new_file_holds_the_content_trimmed_and_ended_by_one_newline(
    library: Path,
) -> None:
    candidate = Candidate.model_validate_json(_stage(library, "standards", "control").read_text())
    data, whole = promotion_bytes(candidate, "standards", EXISTING_STANDARDS)
    assert whole is True
    assert data == b"# A proposed text\n\nOne rule, stated once.\n"


def test_an_addition_keeps_what_the_file_held_then_a_rule_then_the_content(
    library: Path,
) -> None:
    candidate = Candidate.model_validate_json(_stage(library, "skill", "control").read_text())
    data, whole = promotion_bytes(candidate, "skill", EXISTING_SKILL)
    assert whole is False
    assert data == EXISTING_SKILL + b"\n---\n\n" + b"# A proposed text\n\nOne rule, stated once.\n"


def test_a_rubric_is_described_without_its_canary_and_written_with_it(library: Path) -> None:
    staged = _stage(library, "rubric", "control")
    candidate = Candidate.model_validate_json(staged.read_text())
    target = promotion.rubric_path(library / "knowledge", "control")
    target.parent.mkdir(parents=True)
    target.write_bytes(b"# an older rubric\n")
    described, whole = promotion_bytes(candidate, "rubric", target.read_bytes())
    assert whole is True
    assert b"<!--" not in described
    _promote(library, candidate.candidate_id)
    canary = _last_promotion(library)["canary"]
    assert isinstance(canary, str)
    assert canary not in described.decode()
    assert target.read_bytes() == described + f"\n<!-- {canary} -->\n".encode()
    # Pinned apart from the function: the rubric's text, trimmed, one newline, then a blank
    # line and the canary's own line, which ends the file.
    text = PLACEHOLDER.rstrip().encode()
    assert described == text + b"\n"
    assert target.read_bytes() == text + f"\n\n<!-- {canary} -->\n".encode()


@contextmanager
def _opens() -> Iterator[list[str]]:
    """Every file opened while the block runs, as the interpreter reports it."""
    seen: list[str] = []
    _RECORDING.append(seen)
    try:
        yield seen
    finally:
        _RECORDING.remove(seen)


_RECORDING: list[list[str]] = []


def _audit(event: str, args: tuple[object, ...]) -> None:
    if _RECORDING and event == "open":
        _RECORDING[-1].append(str(args[0]))


sys.addaudithook(_audit)


def test_describing_a_promotion_opens_no_file_and_needs_no_terminal(library: Path) -> None:
    candidate = Candidate.model_validate_json(_stage(library, "skill", "control").read_text())
    assert not sys.stdin.isatty(), "the case this proves: a terminal check here would refuse"
    with _opens() as seen:
        promotion_bytes(candidate, "skill", EXISTING_SKILL)
        promotion_bytes(candidate, "skill", None)
    assert seen == []


# -- the finder, public and unchanged --------------------------------------------------------


def _roots(root: Path) -> tuple[Path, Path]:
    return root / staging.STAGING_ROOT, root / staging.RUBRIC_STAGING_ROOT


def test_the_finder_returns_the_kind_the_candidate_and_where_it_is_staged(library: Path) -> None:
    staged = _stage(library, "antipattern", "control")
    candidate_id = staged.stem
    found = find_staged(candidate_id, *_roots(library))
    assert found is not None
    kind, candidate, path = found
    assert (kind, candidate.candidate_id, path) == ("antipattern", candidate_id, staged)
    assert find_staged("no-such-candidate", *_roots(library)) is None


def test_the_finder_refuses_an_id_that_is_not_a_plain_id(library: Path) -> None:
    with pytest.raises(PromotionError, match="plain id"):
        find_staged("../escape", *_roots(library))


def test_the_finder_refuses_a_staged_link_before_reading_it(library: Path, tmp_path: Path) -> None:
    """Refused by the finder's own check, which names the staged file as the link.

    A second layer, the read that will not follow a link, would refuse a live link too, but
    in other words and only once it reads; the finder's check is the one that says what is wrong.
    """
    staged = _stage(library, "skill", "control")
    elsewhere = tmp_path / "elsewhere.json"
    staged.rename(elsewhere)
    staged.symlink_to(elsewhere)
    with pytest.raises(PromotionError, match="staged candidate is a link"):
        find_staged(staged.stem, *_roots(library))


def test_the_finder_refuses_a_staged_link_that_points_nowhere(
    library: Path, tmp_path: Path
) -> None:
    """A link to nothing is still a link, never "no such candidate"."""
    staged = _stage(library, "skill", "control")
    staged.unlink()
    staged.symlink_to(tmp_path / "gone.json")
    with pytest.raises(PromotionError, match="staged candidate is a link"):
        find_staged(staged.stem, *_roots(library))


def test_the_finder_refuses_a_candidate_staged_under_another_kind(library: Path) -> None:
    staged = _stage(library, "skill", "control")
    moved = staged.parent.parent / "standards" / staged.name
    moved.parent.mkdir(parents=True, exist_ok=True)
    os.replace(staged, moved)
    with pytest.raises(PromotionError, match="not the kind of the directory"):
        find_staged(staged.stem, *_roots(library))


def test_the_finder_looks_for_a_rubric_only_under_the_rubric_root(library: Path) -> None:
    general, rubrics = _roots(library)
    misplaced = general / "rubric"
    misplaced.mkdir(parents=True)
    staged = _stage(library, "rubric", "control")
    os.replace(staged, misplaced / staged.name)
    assert find_staged(staged.stem, general, rubrics) is None
    found = find_staged(staged.stem, general, general)
    assert found is not None
    assert found[0] == "rubric"
