"""Every review is given the parts sheet the design's numbers cite, the same bytes each time.

A corpus writes a number's source as a URL, or as arithmetic over rows of its parts sheet
(``derived: [R1.03] * [R5.02]``). A reviewer that cannot read the sheet cannot check such a
source, and a rubric reads a written value whose source it cannot read as a finding. So
every artefact's review, and every clean twin's, is given the corpus's parts sheet as a file
of its worktree, listed to it like every other file:

- byte for byte the corpus's own file, whose digest its manifest holds, so every review is
  given the same bytes and a reader can tell which sheet it was;
- in the given design's commit, so it is part of what was given and never part of the
  revision a reviewer judges;
- named in the account of the revision, which is otherwise the same for every artefact;
- held to the blindness check like everything else a reviewer is shown, so a sheet that
  names the corpus, an artefact or an answer stops the run before any review. A real sheet is
  written indented over many lines, so it is read as one JSON value, its strings decoded,
  never line by line;
- whole: a sheet converted from its authors' table carries every range, list, text and note
  that table holds, and they reach the review as the table writes them, the account naming
  where each is.
"""

from __future__ import annotations

import hashlib
import json
import subprocess
from pathlib import Path
from typing import Any

import parts_sheet_sources as converter
import pytest
from instrument_corpus import AUTHOR, LABEL, SOURCE, SOURCE_ROWS, SeededFakeReviewer, write_corpus

from physgate.evaluation.inject.corpus import (
    SOURCES_NAME,
    Corpus,
    load_corpus,
    manifest_for,
    write_manifest,
)
from physgate.evaluation.inject.exceptions import BlindnessError, CorpusError
from physgate.evaluation.inject.materialise import PARTS_SHEET_NAME
from physgate.evaluation.inject.runner import run_instrument
from physgate.orchestrator.protocols import Artefact


def _git(worktree: str, *args: str) -> str:
    done = subprocess.run(["git", *args], cwd=worktree, capture_output=True, text=True, check=True)
    return done.stdout


def _run(corpus: Corpus, root: Path, reviewer: SeededFakeReviewer) -> None:
    run_instrument(
        corpus,
        {"electrical": reviewer},
        run_dir=root / "run",
        scratch=root / "scratch",
        run_id="sheet-1",
        seed=5,
        review_clean_twins=True,
    )


def test_every_review_and_every_twin_s_is_given_the_corpus_s_own_sheet(tmp_path: Path) -> None:
    corpus = load_corpus(write_corpus(tmp_path / "corpus"))
    sheet = (corpus.root / SOURCES_NAME).read_bytes()
    given: list[bytes] = []
    in_the_base: list[bytes] = []
    in_the_revision: list[str] = []
    accounts: list[str] = []

    def look(artefact: Artefact) -> None:
        given.append((Path(artefact.worktree) / PARTS_SHEET_NAME).read_bytes())
        shown = _git(artefact.worktree, "show", f"{artefact.base_commit}:{PARTS_SHEET_NAME}")
        in_the_base.append(shown.encode())
        assert artefact.base_commit is not None and artefact.attempt_commit is not None
        names = _git(
            artefact.worktree, "diff", "--name-only", artefact.base_commit, artefact.attempt_commit
        )
        in_the_revision.extend(names.split())
        accounts.append(Path(artefact.trajectory).read_text())

    _run(corpus, tmp_path, SeededFakeReviewer(before_verdict=look))
    assert len(given) == 2 * len(corpus.artefacts)  # each artefact and each twin
    assert set(given) == {sheet} and set(in_the_base) == {sheet}
    assert hashlib.sha256(sheet).hexdigest() == corpus.manifest.files[SOURCES_NAME]
    assert corpus.parts_sheet == sheet
    assert PARTS_SHEET_NAME not in in_the_revision
    assert all(f"`{PARTS_SHEET_NAME}`" in account for account in accounts)


def test_the_loaded_sheet_is_the_one_the_manifest_digests(tmp_path: Path) -> None:
    root = write_corpus(tmp_path / "corpus")
    corpus = load_corpus(root)
    assert hashlib.sha256(corpus.parts_sheet).hexdigest() == corpus.manifest.files[SOURCES_NAME]
    (root / SOURCES_NAME).write_bytes(corpus.parts_sheet + b" ")
    with pytest.raises(CorpusError, match="not the one its manifest lists"):
        load_corpus(root)


def test_a_sheet_changed_after_the_listing_is_refused_not_given(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The bytes every review is given are the bytes held to the digest, not a later read."""
    import physgate.evaluation.inject.corpus as corpus_module

    root = write_corpus(tmp_path / "corpus")
    listed = corpus_module.files_under

    def listed_then_changed(where: Path) -> dict[str, str]:
        found = listed(where)
        (where / SOURCES_NAME).write_bytes((where / SOURCES_NAME).read_bytes() + b" ")
        return found

    monkeypatch.setattr(corpus_module, "files_under", listed_then_changed)
    with pytest.raises(CorpusError, match="not the one its manifest lists"):
        load_corpus(root)


@pytest.mark.parametrize(
    ("row", "found"),
    [
        ({"quantity": "the injected stall current", "value": 2, "unit": "A"}, "inject"),
        ({"quantity": "see m1", "value": 2, "unit": "A"}, "m1"),
        ({"quantity": "as the reviewer reads it", "value": 2, "unit": "A"}, "reviewer"),
        ({"quantity": "expected_check", "value": None, "unit": None}, "expected_check"),
    ],
    ids=["a-telling-word", "an-artefact-id", "the-reader", "an-answer-field"],
)
def test_a_sheet_that_tells_stops_the_run_before_any_review(
    tmp_path: Path, row: dict[str, object], found: str
) -> None:
    rows = {**SOURCE_ROWS, "R9.01": {**row, "url": SOURCE}}
    corpus = load_corpus(write_corpus(tmp_path / "corpus", rows=rows))
    reviewer = SeededFakeReviewer()
    with pytest.raises(BlindnessError) as caught:
        _run(corpus, tmp_path, reviewer)
    assert found in caught.value.context["found"]
    assert reviewer.seen == []


def test_an_indented_sheet_over_many_lines_is_read_whole_and_given(tmp_path: Path) -> None:
    """The measurement's sheet is indented, nearly a thousand lines; no line of it is JSON alone."""
    corpus = load_corpus(write_corpus(tmp_path / "corpus", sheet_indent=1))
    assert corpus.parts_sheet.count(b"\n") > 10
    given: list[bytes] = []
    reviewer = SeededFakeReviewer(
        before_verdict=lambda a: given.append((Path(a.worktree) / PARTS_SHEET_NAME).read_bytes())
    )
    _run(corpus, tmp_path, reviewer)
    assert given and set(given) == {corpus.parts_sheet}


def test_an_escaped_telling_word_in_an_indented_sheet_is_refused(tmp_path: Path) -> None:
    """A word escaped in the file is found in the string it decodes to, wherever it sits."""
    rows = {**SOURCE_ROWS, "R9.01": {"quantity": "the injected rate", "value": 2, "unit": "Hz"}}
    rows["R9.01"]["url"] = SOURCE
    root = write_corpus(tmp_path / "corpus", rows=rows, sheet_indent=1)
    sheet = root / SOURCES_NAME
    sheet.write_text(sheet.read_text().replace("injected", "\\u0069njected"))
    write_manifest(root, manifest_for(root, label=LABEL, author_model=AUTHOR))
    corpus = load_corpus(root)
    assert b"injected" not in corpus.parts_sheet
    reviewer = SeededFakeReviewer()
    with pytest.raises(BlindnessError) as caught:
        _run(corpus, tmp_path, reviewer)
    assert "inject" in caught.value.context["found"]
    assert reviewer.seen == []


#: An authors' table for the test design: its numbers as the sheet above has them, and rows a
#: single number cannot hold (a list, a range, a text), with notes.
TABLE = (
    "| Row | Quantity | Value | Unit | Source URL | Retrieved | Note |\n"
    "|---|---|---|---|---|---|---|\n"
    f"| R1.01 | stall current @ 6V | 1.5 | A | {SOURCE} | 2026-10-01 | at the stated voltage |\n"
    f"| R1.02 | mass (weight) | 9.5 | g | same URL as above | 2026-10-01 | — |\n"
    f"| R5.01 | cell nominal voltage | 1.2 | V | {SOURCE} | 2026-10-01 | — |\n"
    f"| R5.02 | number of cells in the pack | 6 | dimensionless | {SOURCE} | 2026-10-01 | — |\n"
    f"| R8.01 | gyroscope ODR options | 12.5, 26, 52, 104, 208 | Hz | {SOURCE} | 2026-10-01 "
    "| the register's settings |\n"
    f"| R8.02 | supply range | 2.7–3.6 | V | {SOURCE} | 2026-10-01 | min and max |\n"
    f"| R8.03 | package | LGA-14 | — | {SOURCE} | 2026-10-01 | a text value |\n"
)
#: What the table gives that a single number cannot, and its notes, as the table writes them.
GIVEN = {"R8.01": "12.5, 26, 52, 104, 208 Hz", "R8.02": "2.7–3.6 V", "R8.03": "LGA-14"}
NOTES = {
    "R1.01": "at the stated voltage",
    "R8.01": "the register's settings",
    "R8.02": "min and max",
    "R8.03": "a text value",
}


def test_a_sheet_converted_from_its_table_reaches_every_review_with_every_value_and_note(
    tmp_path: Path,
) -> None:
    root = write_corpus(tmp_path / "corpus")
    (root / SOURCES_NAME).write_bytes(converter.convert(TABLE, label="a test parts sheet"))
    (root / "parts_sheet.md").write_text(TABLE)
    write_manifest(root, manifest_for(root, label=LABEL, author_model=AUTHOR))
    corpus = load_corpus(root)
    given: list[dict[str, Any]] = []
    accounts: list[str] = []

    def look(artefact: Artefact) -> None:
        given.append(json.loads((Path(artefact.worktree) / PARTS_SHEET_NAME).read_bytes()))
        accounts.append(Path(artefact.trajectory).read_text())

    _run(corpus, tmp_path, SeededFakeReviewer(before_verdict=look))
    assert len(given) == 2 * len(corpus.artefacts)
    for sheet in given:
        rows = sheet["rows"]
        assert list(rows) == ["R1.01", "R1.02", "R5.01", "R5.02", "R8.01", "R8.02", "R8.03"]
        assert all(r["value"] is not None or r.get("given") for r in rows.values())
        assert {k: r["given"] for k, r in rows.items() if "given" in r} == GIVEN
        assert {k: r["note"] for k, r in rows.items() if "note" in r} == NOTES
    assert all("`given`" in account and "`note`" in account for account in accounts)
