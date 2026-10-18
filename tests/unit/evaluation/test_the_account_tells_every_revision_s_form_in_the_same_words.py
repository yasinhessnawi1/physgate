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

import pytest
from instrument_corpus import BASE_NODES, LABEL, MAGNITUDE_ARTEFACT, PROPAGATION_ARTEFACT

from physgate.evaluation.inject.corpus import Base, Patch, telltales
from physgate.evaluation.inject.materialise import (
    ACCOUNT_ABSENCES,
    ACCOUNT_FORM,
    ACCOUNT_PRECISION,
    ACCOUNT_SHA256,
    materialise,
    neutral_trajectory,
    require_blind,
)

BASE = Base.model_validate_json(json.dumps({"label": LABEL, "nodes": list(BASE_NODES)}))
#: The digest of the three paragraphs as approved for the calibration round. A change to
#: any byte of them is a change to what every reviewed item is told, and moves this pin.
PINNED = "8580efd05af6fd2d304810950f00bb2c3d462302dddfd00b1d12373e340ab838"


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
