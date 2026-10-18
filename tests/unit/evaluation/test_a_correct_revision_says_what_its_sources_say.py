"""A corpus's correct revisions are held to their parts sheet, number by number.

A clean twin whose number differs from its own parts-sheet row is not a correct
design, so before a corpus is used its base and every clean patch are checked: a number
copied from a row's address equals that row, converted only between units; a derived
number is its arithmetic over the rows it cites. A difference of rows is listed apart,
since it carries any disagreement between them into the design. The injected patches
are never read. The corpus here is written for the test.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest
from instrument_corpus import (
    BASE_NODES,
    MAGNITUDE_ARTEFACT,
    SOURCE,
    SOURCE_ROWS,
    node,
    with_quantity,
    write_corpus,
)

from physgate.cli import main
from physgate.evaluation.inject.corpus import load_corpus
from physgate.evaluation.inject.source_check import check_sources

PACK = "electrical.battery"


def _pack(value: float, unit: str, source: str) -> dict[str, Any]:
    payload = node(PACK, quantities={"supply_voltage": (value, unit)})
    payload["quantities"]["supply_voltage"]["source"] = source
    return payload


def _corpus(tmp_path: Path, clean: dict[str, Any], injected: dict[str, Any] | None = None) -> Path:
    artefact = {
        **MAGNITUDE_ARTEFACT,
        "clean": {"nodes": [clean]},
        "injected": {"nodes": [injected or with_quantity(clean, "supply_voltage", 70.0, "V")]},
    }
    rows = {
        **SOURCE_ROWS,
        "R9.01": {"quantity": "pack mass", "value": 0.2, "unit": "kg", "url": SOURCE},
    }
    return write_corpus(
        tmp_path / "c",
        artefacts=(artefact,),
        base_nodes=(*BASE_NODES, _pack(7.2, "V", "derived: [R5.01] * [R5.02]")),
        rows=rows,
    )


def test_a_derived_number_that_is_its_arithmetic_and_a_copied_one_equal_to_its_row_pass(
    tmp_path: Path,
) -> None:
    corpus = load_corpus(_corpus(tmp_path, _pack(7200, "mV", "derived: [R5.01] * [R5.02]")))
    found = check_sources(corpus)
    # The base's driver current limit (3 A) is copied from an address whose current row
    # says 1.5 A: the fixture's own design is not its sheet, and the check says so.
    assert [f.kind for f in found if f.node == PACK] == []


def test_a_derived_number_off_its_arithmetic_is_a_mismatch_named_in_one_fact(
    tmp_path: Path,
) -> None:
    corpus = load_corpus(_corpus(tmp_path, _pack(7.5, "V", "derived: [R5.01] * [R5.02]")))
    (finding,) = [f for f in check_sources(corpus) if f.node == PACK]
    assert finding.kind == "mismatch" and finding.where == "revision m1"
    assert finding.fact() == (
        "revision m1: supply_voltage of electrical.battery is 7.5 V, and its source gives "
        "7.2 V (derived: [R5.01] * [R5.02])"
    )


def test_a_copied_number_unlike_every_row_at_its_address_is_a_mismatch(tmp_path: Path) -> None:
    found = check_sources(
        load_corpus(_corpus(tmp_path, _pack(7.2, "V", "derived: [R5.01] * [R5.02]")))
    )
    driver = [f for f in found if f.node == "electrical.driver" and f.where == "base"]
    assert [f.kind for f in driver] == ["mismatch"]
    assert "no row at its source gives that number; its rows of that kind give 1.5 A" in (
        driver[0].fact()
    )


def test_a_number_whose_address_holds_no_number_of_its_kind_is_unresolved(tmp_path: Path) -> None:
    elsewhere = "https://www.pololu.com/product/0000"  # an address no row of the sheet has
    found = check_sources(load_corpus(_corpus(tmp_path, _pack(7.2, "V", elsewhere))))
    (finding,) = [f for f in found if f.node == PACK and f.where == "revision m1"]
    assert finding.kind == "unresolved"


def test_a_difference_of_rows_is_listed_apart_even_when_it_is_its_arithmetic(
    tmp_path: Path,
) -> None:
    corpus = load_corpus(_corpus(tmp_path, _pack(6.0, "V", "derived: [R5.01] * [R5.02] - [R5.01]")))
    (finding,) = [f for f in check_sources(corpus) if f.node == PACK and f.where == "revision m1"]
    assert finding.kind == "subtracted"


def test_the_injected_patch_is_never_read(tmp_path: Path) -> None:
    clean = _pack(7.2, "V", "derived: [R5.01] * [R5.02]")
    corpus = load_corpus(
        _corpus(tmp_path, clean, with_quantity(clean, "supply_voltage", 99.0, "V"))
    )
    assert not [f for f in check_sources(corpus) if f.node == PACK]


def test_the_command_prints_the_facts_and_fails_on_a_mismatch(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    root = _corpus(tmp_path, _pack(7.5, "V", "derived: [R5.01] * [R5.02]"))
    assert main(["inject-sources", "--corpus", str(root)]) == 1
    printed = json.loads(capsys.readouterr().out)
    assert printed["counts"]["mismatch"] >= 1
    assert any("7.5 V" in fact for fact in printed["facts"])
