"""The account of a revision says what the revision is, in the same words for every artefact.

A proposed change to the design graph is not a whole implementation: it wrote no
simulation, measurement or timing budget, the parts sheet it is built from gives no plant
pole, inertia, rate limit or friction coefficient, and its numbers are written to three
significant figures. A review that is not told this holds the revision to records it could
not have written, and to arithmetic it was asked to round. So the account carries three
fixed paragraphs, byte for byte the same for every artefact, whose digest is pinned here
and recorded on every run; they hold no telltale word, and they pass the blindness guard.
"""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any

import pytest
from instrument_corpus import (
    BASE_NODES,
    LABEL,
    MAGNITUDE_ARTEFACT,
    PROPAGATION_ARTEFACT,
    SeededFakeReviewer,
    write_corpus,
)

from physgate.evaluation.inject.corpus import Base, Patch, load_corpus, telltales
from physgate.evaluation.inject.exceptions import CorpusError
from physgate.evaluation.inject.materialise import (
    ACCOUNT_ABSENCES,
    ACCOUNT_FORM,
    ACCOUNT_PRECISION,
    ACCOUNT_SHA256,
    ACCOUNT_SHEET,
    ACCOUNT_SHEET_GIVEN,
    ACCOUNT_SHEET_GIVEN_SHA256,
    ACCOUNT_SHEET_REMARKS,
    ACCOUNT_SHEET_REMARKS_SHA256,
    ACCOUNT_SHEET_SHA256,
    materialise,
    neutral_trajectory,
    require_blind,
)
from physgate.evaluation.inject.runner import CONFIG_NAME, run_instrument

BASE = Base.model_validate_json(json.dumps({"label": LABEL, "nodes": list(BASE_NODES)}))
#: The digest of the three paragraphs as approved for the calibration round. A change to
#: any byte of them is a change to what every reviewed item is told, and moves this pin.
PINNED = "8580efd05af6fd2d304810950f00bb2c3d462302dddfd00b1d12373e340ab838"
#: The parts-sheet sentence a review is told when no row of its sheet gives a value as written:
#: the sentence every measured run so far was told, byte for byte.
PINNED_SHEET = "4adba41d2ba10410d8fa734013dcfa305c0918190e0757cb54ab6f3fc625c9c9"
#: The sentence a review is told when rows of its sheet give values as written, or notes.
PINNED_SHEET_GIVEN = "09f545b2df9d39fe8c27784768d58d5dfa71a243c2fa5808996ed8a0718fe439"
#: The sentence a review is told when its sheet carries its authors' remarks.
PINNED_SHEET_REMARKS = "65a39190adc73dcd083fb10807765af9e4dcd8b3ebbce51a36731e93dd5a5a77"
#: Every account of two committed corpora written before rows gave values (each artefact,
#: clean and injected, in id order), digested as the code before that change wrote them.
OLD_ACCOUNTS = {
    "corpora/injected-errors/fresh-v1": (
        "303dad9ab3c2df976f8bd04412ab0cf6327b83970647418d5194de914df1c393"
    ),
    "experiments/R-PG-02/practice/corpus-v1": (
        "413881ab246905495e3d8e9dbd9dd8da720b2c275ad55772c148f037e07ea71a"
    ),
}
REPO = Path(__file__).resolve().parents[3]


def _patch(artefact: dict[str, object], which: str) -> Patch:
    return Patch.model_validate_json(json.dumps(artefact[which]))


def test_the_three_paragraphs_digest_is_pinned() -> None:
    joined = (ACCOUNT_FORM + ACCOUNT_ABSENCES + ACCOUNT_PRECISION).encode()
    assert hashlib.sha256(joined).hexdigest() == ACCOUNT_SHA256 == PINNED


def test_the_paragraphs_hold_no_telltale_word() -> None:
    for paragraph in (ACCOUNT_FORM, ACCOUNT_ABSENCES, ACCOUNT_PRECISION):
        assert telltales(paragraph) == []


def test_every_account_carries_the_same_bytes_before_its_nodes(tmp_path: Path) -> None:
    # Neutral directory names: the artefact's id or its kind in a path is itself refused.
    made = [
        materialise(BASE, _patch(a, which), tmp_path / f"r{n}")
        for n, (a, which) in enumerate(
            (a, which)
            for a in (MAGNITUDE_ARTEFACT, PROPAGATION_ARTEFACT)
            for which in ("clean", "injected")
        )
    ]
    heads = [m.trajectory.read_text().split("\n## ")[0] for m in made]
    assert len(set(heads)) == 1
    assert ACCOUNT_FORM in heads[0]
    for m in made:
        require_blind(m, ("m1", "p1"))


def test_with_a_parts_sheet_the_account_states_its_absences_and_its_precision() -> None:
    nodes = tuple(dict(n) for n in BASE_NODES[:1])
    with_sheet = neutral_trajectory(nodes, parts_sheet=True)
    without = neutral_trajectory(nodes, parts_sheet=False)
    assert ACCOUNT_FORM in with_sheet and ACCOUNT_FORM in without
    assert ACCOUNT_ABSENCES in with_sheet and ACCOUNT_PRECISION in with_sheet
    assert ACCOUNT_ABSENCES not in without and ACCOUNT_PRECISION not in without
    # The form first, then what the sheet lacks, then how numbers are written, then nodes.
    order = [with_sheet.index(p) for p in (ACCOUNT_FORM, ACCOUNT_ABSENCES, ACCOUNT_PRECISION)]
    assert order == sorted(order) < [with_sheet.index("\n## ")]


@pytest.mark.parametrize(
    "said",
    [
        "proposed change to the design graph alone",
        "did not write one",
        "absent from the design by construction, not a missing input",
        "three significant figures",
        "half a unit in the third significant figure",
    ],
)
def test_the_account_says_what_the_round_needs_it_to_say(said: str) -> None:
    assert said in ACCOUNT_FORM + ACCOUNT_ABSENCES + ACCOUNT_PRECISION


def test_every_run_records_the_account_s_digest(tmp_path: Path) -> None:
    # A later reader holds the run's reviews to the account they were told: the digest is
    # on the run's own configuration, never only in the code that wrote it.
    corpus = load_corpus(write_corpus(tmp_path / "corpus"))
    run_instrument(
        corpus,
        {"electrical": SeededFakeReviewer()},
        run_dir=tmp_path / "run",
        scratch=tmp_path / "scratch",
        run_id="dry-1",
        seed=11,
    )
    config = json.loads((tmp_path / "run" / CONFIG_NAME).read_text())
    assert config["account_sha256"] == ACCOUNT_SHA256 == PINNED


def test_each_parts_sheet_sentence_is_pinned_by_its_own_digest() -> None:
    assert hashlib.sha256(ACCOUNT_SHEET.encode()).hexdigest() == ACCOUNT_SHEET_SHA256
    assert ACCOUNT_SHEET_SHA256 == PINNED_SHEET
    assert hashlib.sha256(ACCOUNT_SHEET_GIVEN.encode()).hexdigest() == ACCOUNT_SHEET_GIVEN_SHA256
    assert ACCOUNT_SHEET_GIVEN_SHA256 == PINNED_SHEET_GIVEN
    assert hashlib.sha256(ACCOUNT_SHEET_REMARKS.encode()).hexdigest() == (
        ACCOUNT_SHEET_REMARKS_SHA256
    )
    assert ACCOUNT_SHEET_REMARKS_SHA256 == PINNED_SHEET_REMARKS
    sentences = (ACCOUNT_SHEET, ACCOUNT_SHEET_GIVEN, ACCOUNT_SHEET_REMARKS)
    assert all(telltales(s) == [] for s in sentences) and len(set(sentences)) == 3


def test_the_remarks_sentence_is_the_given_sentence_and_names_the_remarks() -> None:
    assert ACCOUNT_SHEET_REMARKS.startswith(ACCOUNT_SHEET_GIVEN.rstrip("\n"))
    assert "`remarks`" in ACCOUNT_SHEET_REMARKS
    assert "`remarks`" not in ACCOUNT_SHEET + ACCOUNT_SHEET_GIVEN


def test_the_given_sentence_names_the_sheet_s_authors_not_the_datasheet() -> None:
    assert "`given`, its value as the parts sheet's authors wrote it" in ACCOUNT_SHEET_GIVEN
    assert "`note`" in ACCOUNT_SHEET_GIVEN and "datasheet" not in ACCOUNT_SHEET_GIVEN
    assert "`given`" not in ACCOUNT_SHEET and "`note`" not in ACCOUNT_SHEET


@pytest.mark.parametrize(
    ("gives", "remarks", "told"),
    [
        (False, False, ACCOUNT_SHEET),
        (True, False, ACCOUNT_SHEET_GIVEN),
        (False, True, ACCOUNT_SHEET_REMARKS),
        (True, True, ACCOUNT_SHEET_REMARKS),
    ],
    ids=["a-sheet-of-numbers", "a-sheet-that-gives-values", "remarks", "values-and-remarks"],
)
def test_the_account_tells_the_one_sentence_its_sheet_calls_for(
    gives: bool, remarks: bool, told: str
) -> None:
    nodes = tuple(dict(n) for n in BASE_NODES[:1])
    account = neutral_trajectory(nodes, parts_sheet=True, sheet_gives=gives, sheet_remarks=remarks)
    others = {ACCOUNT_SHEET, ACCOUNT_SHEET_GIVEN, ACCOUNT_SHEET_REMARKS} - {told}
    # Each sentence is a whole line of the account, so one cannot hide inside another.
    assert account.split("\n").count(told.rstrip("\n")) == 1
    assert all(account.split("\n").count(o.rstrip("\n")) == 0 for o in others)
    without = neutral_trajectory(nodes, parts_sheet=False, sheet_gives=gives, sheet_remarks=remarks)
    assert without.count("parts sheet") == 0


def _sheet(rows: dict[str, Any]) -> bytes:
    remarks = rows.pop("remarks", None)
    sheet: dict[str, Any] = {"label": "a sheet", "rows": rows}
    if remarks is not None:
        sheet["remarks"] = remarks
    return json.dumps(sheet).encode()


ROW: dict[str, Any] = {"quantity": "rate", "value": 2, "unit": "Hz", "url": "https://e.com/x"}


@pytest.mark.parametrize(
    ("rows", "told"),
    [
        ({"R1.01": ROW}, ACCOUNT_SHEET),
        ({"R1.01": {**ROW, "given": "2.0 Hz"}}, ACCOUNT_SHEET_GIVEN),
        ({"R1.01": {**ROW, "note": "typical"}}, ACCOUNT_SHEET_GIVEN),
        ({"R1.01": ROW, "remarks": ["one line"]}, ACCOUNT_SHEET_REMARKS),
        ({"R1.01": {**ROW, "note": "typical"}, "remarks": ["one line"]}, ACCOUNT_SHEET_REMARKS),
    ],
    ids=["numbers-only", "a-given-value", "a-note", "remarks", "a-note-and-remarks"],
)
def test_materialise_reads_from_the_sheet_which_sentence_it_calls_for(
    tmp_path: Path, rows: dict[str, Any], told: str
) -> None:
    made = materialise(BASE, _patch(MAGNITUDE_ARTEFACT, "clean"), tmp_path / "r", _sheet(rows))
    lines = made.trajectory.read_text().split("\n")
    assert lines.count(told.rstrip("\n")) == 1


def test_materialise_refuses_a_sheet_that_is_no_parts_sheet_before_writing_anything(
    tmp_path: Path,
) -> None:
    with pytest.raises(CorpusError, match="parts sheet"):
        materialise(BASE, _patch(MAGNITUDE_ARTEFACT, "clean"), tmp_path / "r", b"[1, 2]")
    assert not (tmp_path / "r").exists()


@pytest.mark.parametrize("where", sorted(OLD_ACCOUNTS))
def test_a_committed_corpus_s_accounts_are_byte_for_byte_what_they_were(
    tmp_path: Path, where: str
) -> None:
    corpus = load_corpus(REPO / where)
    digest = hashlib.sha256()
    for n, artefact in enumerate(corpus.artefacts):
        for which in ("clean", "injected"):
            patch = getattr(artefact, which)
            made = materialise(corpus.base, patch, tmp_path / f"r{n}{which[0]}", corpus.parts_sheet)
            digest.update(made.trajectory.read_bytes())
    assert digest.hexdigest() == OLD_ACCOUNTS[where]
