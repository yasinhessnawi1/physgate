"""The library files a reviewer is shown, and every rubric, hold no evaluation-revealing word.

Read from the real ``knowledge/`` tree at the repository root, which is this
test's working directory under ``scripts/check.sh``.

**A pinned residual, not a pass.** Three promoted library files say "physics
gate", the harness's name, or "deliberate", each in a legitimate sense (the
gate's own checks, a code path in a source file's path, a stated exception to a
rule). A reviewer would be shown them. Their content is curated and promoted by
a person, so this test does not fix it: it pins exactly what is found today, and
goes red the moment the set changes in either direction, so the fix is noticed
and the pin removed, and no new word arrives unnoticed.
"""

from __future__ import annotations

from pathlib import Path

from physgate.knowledge import loader
from physgate.reviewers.rubric import evaluation_words

LIBRARY = Path("knowledge")
#: The roles that have a paired reviewer.
REVIEWED = ("control", "firmware")
#: What is found today, file by file.
PINNED = {
    "knowledge/cross/standards.md": ["physgate", "physics gate"],
    "knowledge/firmware/skill.md": ["deliberate"],
    "knowledge/firmware/standards.md": ["deliberate", "physics gate"],
}


def _shown() -> list[Path]:
    library = {LIBRARY.parent / p for role in REVIEWED for p in loader.always_loaded(role)}
    rubrics = set((LIBRARY / "reviewers").glob("*/rubric.md"))
    return sorted(library | rubrics)


def test_the_files_a_reviewer_is_shown_exist() -> None:
    shown = _shown()
    assert len(shown) >= 5, shown
    assert all(p.is_file() for p in shown)


def test_no_shown_file_says_it_is_evaluated_beyond_the_pinned_residual() -> None:
    found = {p.as_posix(): evaluation_words(p.read_text()) for p in _shown()}
    assert {k: v for k, v in found.items() if v} == PINNED
