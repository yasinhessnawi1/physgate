"""The library files a reviewer is shown, and every rubric, hold no evaluation-revealing word.

Read from the real ``knowledge/`` tree at the repository root, which is this
test's working directory under ``scripts/check.sh``.

Nothing is pinned: the three promoted library files that once said such a word
were corrected through the knowledge layer's own staging and promotion, and the
set is now empty. A word arriving in any file a reviewer is shown turns this red.
"""

from __future__ import annotations

from pathlib import Path

from physgate.knowledge import loader
from physgate.reviewers.rubric import evaluation_words

LIBRARY = Path("knowledge")
#: The roles that have a paired reviewer.
REVIEWED = ("control", "firmware")
#: What is found today, file by file: nothing.
PINNED: dict[str, list[str]] = {}


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
