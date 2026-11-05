"""The code carries its reasons, never an id that points at a record the reader cannot open.

The repository is meant to be read by people who have only the repository. Its working notes,
the maintenance rows, the decision logs and the research questions, are kept elsewhere and are
not published, so an id that names one of them (a capital letter or two and a number, such as
the decision and maintenance ids those notes use) tells a reader nothing and leaks where the
work happened. A comment, a docstring or a test name writes the reason itself instead.

The architecture specification's ids (``ARCH`` and a number) are allowed: that document is
published with the thesis, so a reader can look one up.
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent
#: The trees whose text is code or describes code: the package, its tests and the UI's source.
SCANNED = ("src", "tests", "ui/src")
#: Directories a run of the tools fills, which hold no text anyone wrote.
SKIPPED_DIRS = frozenset({"__pycache__", ".pytest_cache", ".mypy_cache", ".ruff_cache"})

#: A decision id (``D-`` and a capital tag), a maintenance row or a research question, each a
#: hyphen and a number, with nothing alphanumeric touching either end.
PRIVATE_ID = re.compile(r"(?<![A-Za-z0-9])(?:D-[A-Z0-9]+|M|RQ)-[0-9]+(?![0-9])")


def _scanned_files() -> list[Path]:
    files: list[Path] = []
    for tree in SCANNED:
        for path in sorted((REPO_ROOT / tree).rglob("*")):
            if path.is_file() and not SKIPPED_DIRS.intersection(path.parts):
                files.append(path)
    return files


def _ids_in(text: str) -> list[str]:
    return PRIVATE_ID.findall(text)


@pytest.mark.parametrize(
    "written",
    [
        # Built from parts, so this file holds no id of its own for the scan to find.
        "(" + "D-" + "A2" + "-37)",
        "D-" + "ARK" + "-45:",
        "a reason (" + "M" + "-128) here",
        "RQ" + "-3",
        "D-" + "K0" + "-12",
    ],
)
def test_the_pattern_finds_each_kind_of_private_id(written: str) -> None:
    assert _ids_in(written) != []


@pytest.mark.parametrize(
    "written",
    [
        "ARCH-080 amended",
        "(ARCH-080)",
        "SS-24 names the two fraction kinds",
        "an M-shaped bracket",
        "PM-128",
        "item-12",
        "run-esc-s1",
        "D-A2",
    ],
)
def test_the_pattern_leaves_published_ids_and_ordinary_words_alone(written: str) -> None:
    assert _ids_in(written) == []


def test_the_scan_reads_the_trees_it_names() -> None:
    # Without this a renamed tree would leave the scan below passing over nothing.
    files = _scanned_files()
    for tree in SCANNED:
        assert any(f.is_relative_to(REPO_ROOT / tree) for f in files), f"{tree} holds no file"


def test_no_scanned_file_names_a_private_record() -> None:
    found: list[str] = []
    for path in _scanned_files():
        try:
            text = path.read_text(encoding="utf-8")
        except UnicodeDecodeError:
            continue
        for number, line in enumerate(text.splitlines(), start=1):
            for written in _ids_in(line):
                found.append(f"{path.relative_to(REPO_ROOT)}:{number}: {written}")
    assert found == [], "write the reason, not the id:\n" + "\n".join(found)
