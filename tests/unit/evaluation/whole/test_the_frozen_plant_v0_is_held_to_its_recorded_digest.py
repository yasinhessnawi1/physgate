"""The first frozen plant, v0: the candidate's content, frozen, and never edited afterwards.

A frozen plant is the one a whole design is judged on, so it is held byte for byte to the
digest recorded when it was frozen. A change is a new version, in a new file with a new
digest; this file is never edited. The freeze takes only what a frozen plant may hold: every
assumption ranges, every cited value says where in its source the number is read, and no
source is blank.
"""

from __future__ import annotations

import copy
import hashlib
import json
from pathlib import Path
from typing import Any

import pytest

_ROOT = Path(__file__).resolve().parents[4]
FROZEN = _ROOT / "src/physgate/evaluation/whole/plant_v0.json"
#: The digest recorded at the freeze. v0 was frozen once more, before any score cited it, when
#: the five assumptions' reasons changed from a proposal to accepted assumptions; no value,
#: range, source or measurement changed. The first freeze's digest was c45d089b...05a2.
FROZEN_SHA256 = "cfa93bec3323af6ecc8f41916f63762bfc3ae0f1c35f60da3b44f91e7244b4a1"
#: The candidate it was frozen from: the same bytes with the status a draft.
CANDIDATE_SHA256 = "bcfe01cea39cf13cc3fc89ebdc0d7c896aeaab04fc0e2af4441fd448eeb5c476"


def _raw() -> bytes:
    assert FROZEN.is_file(), f"no frozen plant at {FROZEN}"
    return FROZEN.read_bytes()


def _doc() -> dict[str, Any]:
    loaded: dict[str, Any] = json.loads(_raw())
    return loaded


def test_the_frozen_plant_is_byte_for_byte_the_one_recorded() -> None:
    assert hashlib.sha256(_raw()).hexdigest() == FROZEN_SHA256


def test_the_frozen_plant_is_the_candidate_with_its_status_frozen() -> None:
    raw = _raw()
    assert raw.count(b'"status": "frozen"') == 1
    as_candidate = raw.replace(b'"status": "frozen"', b'"status": "draft"')
    assert hashlib.sha256(as_candidate).hexdigest() == CANDIDATE_SHA256


def test_the_scorer_knows_this_digest_as_the_frozen_plant_v0() -> None:
    from physgate.evaluation.whole import plant as plant_module

    frozen = getattr(plant_module, "FROZEN_PLANTS", None)
    assert frozen is not None, "the plant module names no frozen plant"
    assert frozen == {FROZEN_SHA256: "v0"}


def test_the_frozen_plant_is_taken_as_frozen() -> None:
    from physgate.evaluation.whole.plant import PlantError, parse_plant

    try:
        plant = parse_plant(_raw())
    except PlantError as exc:
        pytest.fail(f"the frozen plant was refused: {exc}")
    assert plant.status == "frozen"


def _assumption_at_a_point(doc: dict[str, Any]) -> None:
    p = doc["parameters"]["rotor_inertia"]
    p.update(low=p["value"], high=p["value"])


@pytest.mark.parametrize(
    ("change", "says"),
    [
        (_assumption_at_a_point, "an assumption held at a point in a frozen plant"),
        (lambda d: d["parameters"]["kit_mass"].pop("locator"), "names no locator"),
        (lambda d: d["parameters"]["wheel_mass"].update(locator=" "), "names no locator"),
        (lambda d: d["parameters"]["kit_mass"].update(source=" "), "names no source"),
        (lambda d: d["parameters"]["com_height"].update(source=""), "plant parameter file"),
    ],
    ids=[
        "assumption_at_a_point",
        "cited_without_locator",
        "cited_with_blank_locator",
        "source_blank",
        "source_empty",
    ],
)
def test_the_freeze_refuses_what_a_frozen_plant_may_not_hold(change: Any, says: str) -> None:
    from physgate.evaluation.whole.plant import PlantError, parse_plant

    doc = copy.deepcopy(_doc())
    assert doc["status"] == "frozen"
    change(doc)
    try:
        parse_plant(json.dumps(doc).encode())
    except PlantError as exc:
        assert says in str(exc), str(exc)
        return
    pytest.fail(f"a frozen plant was taken; it should be refused for {says!r}")
