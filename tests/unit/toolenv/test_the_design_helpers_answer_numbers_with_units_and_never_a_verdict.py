"""The design helpers answer with numbers and files, each number with its unit, and never judge.

The helpers a part script calls live beside the tool servers, are copied into the tool
environment, and run on its interpreter. What they decide without the CAD kernel is tested
here on the harness's interpreter, by loading the files as they are: the closed set of fields
a result may have, the refusal of any truth value or judgement's name in one, the canonical
description a geometry hash is taken over, the conversion of what the kernel measures into SI,
and the closed-form beam load cases. That nothing in them compares a result with a limit is
read off their syntax trees. What needs the kernel is the integration test's.
"""

from __future__ import annotations

import ast
import copy
import hashlib
import importlib.util
import json
import math
import random
import sys
from pathlib import Path
from types import ModuleType
from typing import Any

import pytest

from physgate.gate import units
from physgate.unit_spelling import require_bounded_spelling

REPO = Path(__file__).resolve().parents[3]
HELPERS = REPO / "toolenv" / "helpers"
FILES = ("geometry.py", "result_file.py", "structure.py")


def _helper(name: str) -> ModuleType:
    path = HELPERS / f"{name}.py"
    assert path.is_file(), f"the tool environment has no {name} helper"
    spec = importlib.util.spec_from_file_location(name, path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    # Under its own name, as on the tool environment's interpreter: the helpers find each
    # other by name in their own directory.
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


@pytest.fixture(scope="module")
def result_file() -> ModuleType:
    return _helper("result_file")


@pytest.fixture(scope="module")
def structure(result_file: ModuleType) -> ModuleType:
    return _helper("structure")


@pytest.fixture(scope="module")
def geometry(result_file: ModuleType) -> ModuleType:
    return _helper("geometry")


def _q(value: object, unit: str) -> dict[str, object]:
    return {"value": value, "unit": unit}


BEAM = {
    "length": _q(60, "mm"),
    "width": _q(10, "mm"),
    "thickness": _q(3, "mm"),
    "modulus": _q(2.3, "GPa"),
    "force": _q(1, "N"),
}


def _load_case(structure: ModuleType) -> dict[str, Any]:
    found = structure.cantilever_end_load("arm", **BEAM)
    assert isinstance(found, dict)
    return found


def _numbers_outside_a_quantity(found: object, inside: bool = False) -> list[object]:
    """Every number in ``found`` that is not the value of something with a unit."""
    if isinstance(found, dict):
        has_unit = "unit" in found
        loose = []
        for name, inner in found.items():
            loose += _numbers_outside_a_quantity(inner, has_unit and name == "value")
        return loose
    if isinstance(found, list):
        return [n for inner in found for n in _numbers_outside_a_quantity(inner, inside)]
    if isinstance(found, bool) or not isinstance(found, (int, float)):
        return []
    return [] if inside else [found]


def _truth_values(found: object) -> list[bool]:
    if isinstance(found, dict):
        return [b for inner in found.values() for b in _truth_values(inner)]
    if isinstance(found, list):
        return [b for inner in found for b in _truth_values(inner)]
    return [found] if isinstance(found, bool) else []


# ---- a result: a closed set of fields, and no judgement ----------------------------------------


def test_a_value_has_a_unit_and_is_a_finite_number(result_file: ModuleType) -> None:
    assert result_file.quantity(2.5, "kg") == {"value": 2.5, "unit": "kg"}
    assert result_file.quantity([1.0, 2.0], "m", about="x") == {
        "value": [1.0, 2.0],
        "unit": "m",
        "about": "x",
    }
    for bad in (
        math.nan,
        math.inf,
        -math.inf,
        "2.5",
        None,
        True,
        [1.0, math.nan],
        [[1.0], [False]],
    ):
        with pytest.raises(result_file.HelperRefusedError):
            result_file.quantity(bad, "kg")
    with pytest.raises(result_file.HelperRefusedError, match="unit"):
        result_file.quantity(2.5, "")


def test_a_load_case_result_has_exactly_its_fields_and_every_number_a_unit(
    result_file: ModuleType, structure: ModuleType
) -> None:
    found = _load_case(structure)
    assert set(found) == {
        "schema",
        "kind",
        "case",
        "model",
        "formulas",
        "assumptions",
        "inputs",
        "values",
    }
    assert set(found) == set(result_file.FIELDS["load_case"])
    assert found["kind"] == "load_case" and found["schema"] == 1
    assert set(found["values"]) == {
        "second_moment_of_area",
        "tip_deflection",
        "peak_bending_stress",
        "reaction_force",
        "reaction_moment",
    }
    assert _numbers_outside_a_quantity({k: v for k, v in found.items() if k != "schema"}) == []
    assert _truth_values(found) == []
    assert len(found["assumptions"]) >= 3
    assert set(found["formulas"]) == set(found["values"])


def test_the_kinds_of_result_and_their_fields_are_a_closed_list(result_file: ModuleType) -> None:
    assert {kind: sorted(fields) for kind, fields in result_file.FIELDS.items()} == {
        "geometry": sorted(
            ["schema", "kind", "part", "geometry_hash", "values", "inputs", "exports", "libraries"]
        ),
        "pair": sorted(
            ["schema", "kind", "parts", "placed_geometry_hashes", "values", "libraries"]
        ),
        "load_case": sorted(
            ["schema", "kind", "case", "model", "formulas", "assumptions", "inputs", "values"]
        ),
    }
    named = {name for fields in result_file.FIELDS.values() for name in fields}
    assert not named & set(result_file.JUDGEMENT_WORDS)


@pytest.mark.parametrize("word", ["ok", "pass", "passed", "clean", "valid", "verdict", "safe"])
def test_a_result_with_a_field_that_states_a_judgement_is_refused_wherever_it_sits(
    result_file: ModuleType, structure: ModuleType, word: str
) -> None:
    assert word in result_file.JUDGEMENT_WORDS
    sound = _load_case(structure)
    assert result_file.checked(sound) == sound
    for spelt in (word, word.upper(), word.capitalize()):
        top = sound | {spelt: "yes"}
        with pytest.raises(result_file.HelperRefusedError):
            result_file.checked(top)
        nested = copy.deepcopy(sound)
        nested["values"][spelt] = _q(1.0, "dimensionless")
        with pytest.raises(result_file.HelperRefusedError, match="judgement"):
            result_file.checked(nested)
        deeper = copy.deepcopy(sound)
        deeper["values"]["tip_deflection"][spelt] = "yes"
        with pytest.raises(result_file.HelperRefusedError, match="judgement"):
            result_file.checked(deeper)
        listed = copy.deepcopy(sound)
        listed["assumptions"] = [{spelt: "yes"}]
        with pytest.raises(result_file.HelperRefusedError, match="judgement"):
            result_file.checked(listed)


@pytest.mark.parametrize("value", [True, False])
def test_a_result_with_a_truth_value_is_refused_whatever_its_field_is_called(
    result_file: ModuleType, structure: ModuleType, value: bool
) -> None:
    sound = _load_case(structure)
    nested = copy.deepcopy(sound)
    nested["values"]["within"] = value
    with pytest.raises(result_file.HelperRefusedError, match="truth value"):
        result_file.checked(nested)
    in_a_quantity = copy.deepcopy(sound)
    in_a_quantity["values"]["tip_deflection"]["value"] = value
    with pytest.raises(result_file.HelperRefusedError, match="truth value"):
        result_file.checked(in_a_quantity)
    listed = copy.deepcopy(sound)
    listed["assumptions"] = ["small deflections", value]
    with pytest.raises(result_file.HelperRefusedError, match="truth value"):
        result_file.checked(listed)


def test_a_result_with_a_field_more_or_fewer_than_its_kind_s_is_refused(
    result_file: ModuleType, structure: ModuleType
) -> None:
    sound = _load_case(structure)
    with pytest.raises(result_file.HelperRefusedError, match="exactly its own fields"):
        result_file.checked(sound | {"margin_of_safety": _q(1.2, "dimensionless")})
    for name in sound:
        fewer = {k: v for k, v in sound.items() if k != name}
        with pytest.raises(result_file.HelperRefusedError):
            result_file.checked(fewer)
    for kind in ("", "verdict", "series", None, 1):
        with pytest.raises(result_file.HelperRefusedError, match="kind"):
            result_file.checked(sound | {"kind": kind})
    with pytest.raises(result_file.HelperRefusedError, match="layout version"):
        result_file.checked(sound | {"schema": 2})


def test_a_result_holds_only_finite_numbers_text_lists_and_objects_to_a_bounded_depth(
    result_file: ModuleType, structure: ModuleType
) -> None:
    sound = _load_case(structure)
    for bad in (math.nan, math.inf, b"bytes", {1, 2}, 1j):
        changed = copy.deepcopy(sound)
        changed["values"]["tip_deflection"]["value"] = bad
        with pytest.raises(result_file.HelperRefusedError):
            result_file.checked(changed)
    numbered = copy.deepcopy(sound)
    numbered["values"][3] = "x"
    with pytest.raises(result_file.HelperRefusedError, match="not text"):
        result_file.checked(numbered)
    deep: object = "bottom"
    # The list of assumptions is one level down already.
    for _ in range(result_file.MAX_DEPTH - 1):
        deep = [deep]
    at_the_bound = copy.deepcopy(sound)
    at_the_bound["assumptions"] = deep
    assert result_file.checked(at_the_bound)["assumptions"] == deep
    too_deep = copy.deepcopy(sound)
    too_deep["assumptions"] = [deep]
    with pytest.raises(result_file.HelperRefusedError, match="too deep"):
        result_file.checked(too_deep)


def test_a_result_file_is_the_checked_result_sorted_bounded_and_named_as_one(
    result_file: ModuleType, structure: ModuleType, tmp_path: Path
) -> None:
    sound = _load_case(structure)
    text = result_file.render(sound)
    assert text.endswith("}\n") and not text.endswith("\n\n")
    assert json.loads(text) == sound
    shuffled = dict(reversed(list(sound.items())))
    assert result_file.render(shuffled) == text
    assert list(json.loads(text)) == sorted(sound)
    written = result_file.write(tmp_path / "arm.result.json", sound)
    assert written == str(tmp_path / "arm.result.json")
    assert (tmp_path / "arm.result.json").read_text(encoding="utf-8") == text
    with pytest.raises(result_file.HelperRefusedError, match=r"\.result\.json"):
        result_file.write(tmp_path / "arm.json", sound)
    assert not (tmp_path / "arm.json").exists()
    with pytest.raises(result_file.HelperRefusedError, match="judgement"):
        result_file.write(tmp_path / "bad.result.json", sound | {"values": {"ok": "yes"}})
    assert not (tmp_path / "bad.result.json").exists()
    big = copy.deepcopy(sound)
    big["assumptions"] = ["x" * 1000] * (result_file.MAX_RESULT_BYTES // 1000)
    with pytest.raises(result_file.HelperRefusedError, match="at most"):
        result_file.render(big)
    big["assumptions"] = ["x" * 1000] * (result_file.MAX_RESULT_BYTES // 1000 - 200)
    assert len(result_file.render(big)) < result_file.MAX_RESULT_BYTES


# ---- the closed-form load cases ----------------------------------------------------------------


def test_a_cantilever_s_deflection_stress_and_reactions_are_the_beam_formula_s(
    structure: ModuleType,
) -> None:
    values = _load_case(structure)["values"]
    assert values["second_moment_of_area"] == _q(pytest.approx(2.25e-11, rel=1e-12), "m**4")
    # F L**3 / (3 E I) with 1 N, 60 mm, 2.3 GPa: 1.3913 mm.
    assert values["tip_deflection"] == _q(pytest.approx(1.3913043478260868e-3, rel=1e-12), "m")
    # 6 F L / (b h**2) = 6 * 0.06 / (0.01 * 9e-6) = 4.0 MPa.
    assert values["peak_bending_stress"] == _q(pytest.approx(4.0e6, rel=1e-12), "Pa")
    assert values["reaction_force"] == _q(pytest.approx(1.0), "N")
    assert values["reaction_moment"] == _q(pytest.approx(0.06, rel=1e-12), "N*m")


def test_a_simply_supported_beam_s_numbers_are_the_beam_formula_s(structure: ModuleType) -> None:
    given = {("span" if name == "length" else name): value for name, value in BEAM.items()}
    found = structure.simply_supported_centre_load("deck", **given)
    values = found["values"]
    # F L**3 / (48 E I): a sixteenth of the cantilever's for the same length.
    assert values["centre_deflection"] == _q(
        pytest.approx(1.3913043478260868e-3 / 16, rel=1e-12), "m"
    )
    # 3 F L / (2 b h**2) = 3 * 0.06 / (2 * 0.01 * 9e-6) = 1.0 MPa.
    assert values["peak_bending_stress"] == _q(pytest.approx(1.0e6, rel=1e-12), "Pa")
    assert values["reaction_force"]["value"] == pytest.approx(0.5)
    assert values["reaction_force"]["unit"] == "N"
    assert "each" in values["reaction_force"]["at"]
    assert set(found["formulas"]) == set(values)
    assert found["inputs"]["span"] == _q(pytest.approx(0.06), "m")


def test_a_load_case_scales_as_the_formula_says(structure: ModuleType) -> None:
    base = _load_case(structure)["values"]
    doubled = structure.cantilever_end_load("arm", **(BEAM | {"force": _q(2, "N")}))["values"]
    assert doubled["tip_deflection"]["value"] == pytest.approx(2 * base["tip_deflection"]["value"])
    assert doubled["peak_bending_stress"]["value"] == pytest.approx(
        2 * base["peak_bending_stress"]["value"]
    )
    thick = structure.cantilever_end_load("arm", **(BEAM | {"thickness": _q(6, "mm")}))["values"]
    assert thick["tip_deflection"]["value"] == pytest.approx(base["tip_deflection"]["value"] / 8)
    assert thick["peak_bending_stress"]["value"] == pytest.approx(
        base["peak_bending_stress"]["value"] / 4
    )
    wide = structure.cantilever_end_load("arm", **(BEAM | {"width": _q(20, "mm")}))["values"]
    assert wide["tip_deflection"]["value"] == pytest.approx(base["tip_deflection"]["value"] / 2)
    long = structure.cantilever_end_load("arm", **(BEAM | {"length": _q(120, "mm")}))["values"]
    assert long["tip_deflection"]["value"] == pytest.approx(8 * base["tip_deflection"]["value"])
    assert long["reaction_moment"]["value"] == pytest.approx(0.12)


def test_an_input_is_the_same_in_any_of_its_units_and_recorded_in_si(structure: ModuleType) -> None:
    in_si = {
        "length": _q(0.06, "m"),
        "width": _q(0.01, "m"),
        "thickness": _q(0.003, "m"),
        "modulus": _q(2.3e9, "Pa"),
        "force": _q(1, "N"),
    }
    one, other = _load_case(structure), structure.cantilever_end_load("arm", **in_si)
    for name, found in one["values"].items():
        assert other["values"][name]["value"] == pytest.approx(found["value"], rel=1e-12), name
    in_mpa = structure.cantilever_end_load("arm", **(BEAM | {"modulus": _q(2300, "MPa")}))
    assert in_mpa["values"]["tip_deflection"]["value"] == pytest.approx(
        one["values"]["tip_deflection"]["value"], rel=1e-12
    )
    assert one["inputs"] == {
        "length": _q(pytest.approx(0.06), "m"),
        "width": _q(pytest.approx(0.01), "m"),
        "thickness": _q(pytest.approx(0.003), "m"),
        "modulus": _q(pytest.approx(2.3e9), "Pa"),
        "force": _q(pytest.approx(1.0), "N"),
    }


@pytest.mark.parametrize(
    "bad",
    [
        60,
        60.0,
        "60 mm",
        None,
        {"value": 60},
        {"value": 60, "unit": "mm", "tolerance": 1},
        _q(60, "cm"),
        _q(60, "in"),
        _q(60, ""),
        _q(0, "mm"),
        _q(-60, "mm"),
        _q(math.inf, "mm"),
        _q(math.nan, "mm"),
        _q(True, "mm"),
        _q("60", "mm"),
    ],
)
def test_an_input_without_a_unit_or_not_above_zero_is_refused(
    structure: ModuleType, bad: object
) -> None:
    with pytest.raises(structure.HelperRefusedError):
        structure.cantilever_end_load("arm", **(BEAM | {"length": bad}))
    with pytest.raises(structure.HelperRefusedError):
        structure.simply_supported_centre_load(
            "deck", **({k: v for k, v in BEAM.items() if k != "length"} | {"span": bad})
        )


def test_a_load_case_takes_exactly_its_inputs_and_no_allowable(structure: ModuleType) -> None:
    for name in BEAM:
        fewer = {k: v for k, v in BEAM.items() if k != name}
        with pytest.raises(structure.HelperRefusedError, match="exactly"):
            structure.cantilever_end_load("arm", **fewer)
    for extra in ("allowable_stress", "yield_strength", "limit", "span"):
        with pytest.raises(structure.HelperRefusedError, match="exactly"):
            structure.cantilever_end_load("arm", **(BEAM | {extra: _q(40, "MPa")}))
    for name in ("", "two\nlines"):
        with pytest.raises(structure.HelperRefusedError, match="name"):
            structure.cantilever_end_load(name, **BEAM)


# ---- the description a geometry hash is taken over ---------------------------------------------

BLOCK: dict[str, Any] = {
    "volume": 6000.0,
    "area": 2200.0,
    "centre": [0.0, 0.0, 5.0],
    "box": [-10.0, -15.0, 0.0, 10.0, 15.0, 10.0],
    "faces": [
        ("PLANE", 600.0, 0.0, 0.0, 0.0),
        ("PLANE", 600.0, 0.0, 0.0, 10.0),
        ("PLANE", 200.0, 0.0, -15.0, 5.0),
        ("PLANE", 200.0, 0.0, 15.0, 5.0),
        ("PLANE", 300.0, -10.0, 0.0, 5.0),
        ("PLANE", 300.0, 10.0, 0.0, 5.0),
        ("CYLINDER", 62.83185307179586, 0.0, 0.0, 5.0),
    ],
    "edges": [("LINE", 20.0), ("LINE", 30.0), ("LINE", 10.0), ("CIRCLE", 6.283185307179586)],
    "vertices": [(-10.0, -15.0, 0.0), (10.0, -15.0, 0.0), (10.0, 15.0, 10.0), (1.0, 0.0, 0.0)],
}
#: The hash of the block above, written down so that any change to the description is seen.
BLOCK_HASH = "sha256:831dd8e88b1c6bf4c6378c883bb52dc182ca6ce5ef11a3086828690dcc3674cb"


def _changed(**parts: object) -> dict[str, Any]:
    return copy.deepcopy(BLOCK) | parts


def test_the_hash_is_sha256_over_the_description_which_begins_with_its_version(
    geometry: ModuleType,
) -> None:
    text = geometry.description(BLOCK)
    assert json.loads(text)[0] == geometry.DESCRIPTION_VERSION == 1
    assert " " not in text and "\n" not in text
    found = geometry.hash_of(BLOCK)
    assert found == "sha256:" + hashlib.sha256(text.encode("ascii")).hexdigest()
    assert geometry.HASH.fullmatch(found)
    assert found == BLOCK_HASH


def test_the_hash_does_not_depend_on_the_order_the_kernel_lists_things_in(
    geometry: ModuleType,
) -> None:
    shuffler = random.Random(20261112)
    for _ in range(20):
        mixed = copy.deepcopy(BLOCK)
        for name in ("faces", "edges", "vertices"):
            shuffler.shuffle(mixed[name])
        assert geometry.hash_of(mixed) == BLOCK_HASH


def test_a_tenth_of_a_millimetre_anywhere_changes_the_hash(geometry: ModuleType) -> None:
    seen = {BLOCK_HASH}
    for name in ("volume", "area"):
        seen.add(geometry.hash_of(_changed(**{name: BLOCK[name] + 0.1})))
    for name in ("centre", "box"):
        for index in range(len(BLOCK[name])):
            moved = list(BLOCK[name])
            moved[index] += 0.1
            seen.add(geometry.hash_of(_changed(**{name: moved})))
    for name in ("faces", "edges", "vertices"):
        for item in range(len(BLOCK[name])):
            for index, number in enumerate(BLOCK[name][item]):
                if isinstance(number, str):
                    continue
                moved = [list(entry) for entry in BLOCK[name]]
                moved[item][index] = number + 0.1
                seen.add(geometry.hash_of(_changed(**{name: moved})))
    numbers = 2 + 3 + 6 + 7 * 4 + 4 * 1 + 4 * 3
    assert len(seen) == 1 + numbers


def test_numbers_are_kept_to_six_decimals_of_a_millimetre(geometry: ModuleType) -> None:
    assert geometry.DECIMALS == 6
    # Below half of the last kept decimal the description is the same; at a whole one it is not.
    for name in ("volume", "area"):
        assert geometry.hash_of(_changed(**{name: BLOCK[name] + 4e-7})) == BLOCK_HASH
        assert geometry.hash_of(_changed(**{name: BLOCK[name] + 1e-6})) != BLOCK_HASH
    nudged = [(kind, length + 1e-7) for kind, length in BLOCK["edges"]]
    assert geometry.hash_of(_changed(edges=nudged)) == BLOCK_HASH
    shifted = [(x + 1e-6, y, z) for x, y, z in BLOCK["vertices"]]
    assert geometry.hash_of(_changed(vertices=shifted)) != BLOCK_HASH
    text = geometry.description(_changed(volume=6000.123456789))
    assert json.loads(text)[1][0] == 6000.123457


def test_a_negative_zero_is_written_as_zero(geometry: ModuleType) -> None:
    signed = _changed(
        centre=[-0.0, -1e-17, 5.0],
        vertices=[(-10.0, -15.0, -0.0), (10.0, -15.0, -1e-9), (10.0, 15.0, 10.0), (1.0, -0.0, 0.0)],
    )
    assert "-0.0" not in geometry.description(signed)
    assert geometry.hash_of(signed) == BLOCK_HASH


@pytest.mark.parametrize(
    ("part", "kind"),
    [("faces", "BSPLINE"), ("faces", "SPHERE"), ("faces", "TORUS"), ("faces", "CONE")]
    + [("edges", "ELLIPSE"), ("edges", "BSPLINE"), ("edges", "OTHER")],
)
def test_a_kind_of_face_or_edge_not_measured_on_both_platforms_gets_no_hash(
    geometry: ModuleType, part: str, kind: str
) -> None:
    assert {"PLANE", "CYLINDER"} == set(geometry.MEASURED_FACE_KINDS)
    assert {"LINE", "CIRCLE"} == set(geometry.MEASURED_EDGE_KINDS)
    strange = copy.deepcopy(BLOCK)
    strange[part].append((kind, *BLOCK[part][0][1:]))
    with pytest.raises(geometry.HelperRefusedError, match=kind) as refused:
        geometry.hash_of(strange)
    assert part[:-1] in str(refused.value)
    assert "not been measured" in str(refused.value)


def test_a_shape_with_no_face_gets_no_hash(geometry: ModuleType) -> None:
    with pytest.raises(geometry.HelperRefusedError, match="no face"):
        geometry.hash_of(_changed(faces=[]))


# ---- an assembly's hash ------------------------------------------------------------------------

_A, _B = "sha256:" + "a" * 64, "sha256:" + "b" * 64


def _placed(part: str, position: list[float], unit: str = "mm") -> dict[str, object]:
    return {
        "geometry_hash": part,
        "position": _q(position, unit),
        "rotation": _q([0, 0, 90.0], "deg"),
    }


def test_an_assembly_s_hash_is_over_its_parts_hashes_and_placements_in_any_order(
    geometry: ModuleType,
) -> None:
    parts = [_placed(_A, [0, 0, 0]), _placed(_B, [0, 0, 1.5])]
    found = geometry.assembly_hash(parts)
    assert geometry.HASH.fullmatch(found)
    assert geometry.assembly_hash(list(reversed(parts))) == found
    in_metres = [_placed(_A, [0, 0, 0]), _placed(_B, [0, 0, 0.0015], "m")]
    assert geometry.assembly_hash(in_metres) == found
    others = {
        geometry.assembly_hash([_placed(_A, [0, 0, 0]), _placed(_B, [0, 0, 1.6])]),
        geometry.assembly_hash([_placed(_A, [0, 0, 0]), _placed(_A, [0, 0, 1.5])]),
        geometry.assembly_hash([_placed(_B, [0, 0, 0]), _placed(_A, [0, 0, 1.5])]),
        geometry.assembly_hash([_placed(_A, [0, 0, 0])]),
        geometry.assembly_hash(
            [_placed(_A, [0, 0, 0]), _placed(_B, [0, 0, 1.5]) | {"rotation": _q([0, 0, 0], "deg")}]
        ),
    }
    assert found not in others and len(others) == 5
    # A part's own hash is never an assembly's, even for one part where it was built.
    assert geometry.assembly_hash([_placed(_A, [0, 0, 0])]) != _A


@pytest.mark.parametrize(
    "bad",
    [
        [],
        [{"geometry_hash": _A, "position": _q([0, 0, 0], "mm")}],
        [_placed("a" * 64, [0, 0, 0])],
        [_placed(_A.upper(), [0, 0, 0])],
        [_placed(_A, [0, 0, 0], "cm")],
        [_placed(_A, [0, 0])],
        [_placed(_A, [0, 0, 0]) | {"rotation": _q([0, 0, 1.57], "rad")}],
        [_placed(_A, [0, 0, 0]) | {"rotation": _q([0, 0], "deg")}],
        [_placed(_A, [0, 0, 0]) | {"note": "x"}],
    ],
)
def test_an_assembly_part_without_its_hash_or_its_whole_placement_is_refused(
    geometry: ModuleType, bad: list[dict[str, object]]
) -> None:
    with pytest.raises(geometry.HelperRefusedError):
        geometry.assembly_hash(bad)


# ---- what the kernel measured, in SI -----------------------------------------------------------

PLA = _q(1240, "kg/m**3")


def _properties(geometry: ModuleType, **changed: object) -> dict[str, Any]:
    given: dict[str, object] = {
        "volume_mm3": 6000.0,
        "centre_mm": [1.0, -2.0, 5.0],
        "inertia_mm5": [[650000.0, 0.0, 0.0], [0.0, 250000.0, -3.0], [0.0, -3.0, 500000.0]],
        "box_mm": BLOCK["box"],
        "density": PLA,
        "density_source": "the maker's datasheet",
    }
    found = geometry.properties_from(**(given | changed))
    assert isinstance(found, dict)
    return found


def test_mass_properties_leave_in_si_each_with_its_unit(geometry: ModuleType) -> None:
    found = _properties(geometry)
    assert set(found) == {"volume", "mass", "centre_of_mass", "inertia", "bounding_box", "density"}
    assert found["volume"] == _q(pytest.approx(6.0e-6, rel=1e-12), "m**3")
    assert found["mass"] == _q(pytest.approx(6.0e-6 * 1240, rel=1e-12), "kg")
    assert found["centre_of_mass"] == _q(pytest.approx([0.001, -0.002, 0.005]), "m")
    inertia = found["inertia"]
    assert inertia["unit"] == "kg*m**2"
    # mm**5 times kg/m**3: 1e-15 m**5 each.
    assert inertia["value"][0] == pytest.approx([650000.0 * 1e-15 * 1240, 0.0, 0.0])
    assert inertia["value"][1][2] == pytest.approx(-3.0e-15 * 1240)
    assert inertia["about"] == "the centre of mass"
    assert found["bounding_box"] == {
        "low_corner": _q(pytest.approx([-0.010, -0.015, 0.0]), "m"),
        "high_corner": _q(pytest.approx([0.010, 0.015, 0.010]), "m"),
    }
    assert found["density"] == {
        "value": pytest.approx(1240.0),
        "unit": "kg/m**3",
        "source": "the maker's datasheet",
    }
    assert _numbers_outside_a_quantity(found) == []
    assert _truth_values(found) == []


def test_a_density_is_the_same_in_either_unit(geometry: ModuleType) -> None:
    assert geometry.density_in_si(PLA) == pytest.approx(1240.0)
    assert geometry.density_in_si(_q(1.24, "g/cm**3")) == pytest.approx(1240.0)
    in_grams = _properties(geometry, density=_q(1.24, "g/cm**3"))
    assert in_grams["mass"]["value"] == pytest.approx(_properties(geometry)["mass"]["value"])
    assert in_grams["density"]["unit"] == "kg/m**3"


@pytest.mark.parametrize(
    "bad",
    [
        1240,
        1240.0,
        "1240 kg/m**3",
        None,
        {"value": 1240},
        {"value": 1240, "unit": "kg/m**3", "source": "x"},
        _q(1240, "kg/m3"),
        _q(1240, "kg"),
        _q(0.045, "lb/in**3"),
        _q(0, "kg/m**3"),
        _q(-1240, "kg/m**3"),
        _q(math.inf, "kg/m**3"),
        _q(math.nan, "kg/m**3"),
        _q(True, "kg/m**3"),
        _q("1240", "kg/m**3"),
    ],
)
def test_a_density_without_a_unit_or_not_above_zero_is_refused(
    geometry: ModuleType, bad: object
) -> None:
    with pytest.raises(geometry.HelperRefusedError, match="density"):
        geometry.density_in_si(bad)
    with pytest.raises(geometry.HelperRefusedError, match="density"):
        _properties(geometry, density=bad)
    # Before any shape is measured: a refusal needs no kernel.
    with pytest.raises(geometry.HelperRefusedError, match="density"):
        geometry.mass_properties(object(), density=bad, density_source="a datasheet")


@pytest.mark.parametrize("source", ["", "   ", None, 7])
def test_a_density_is_stated_with_its_source(geometry: ModuleType, source: object) -> None:
    with pytest.raises(geometry.HelperRefusedError, match="source"):
        _properties(geometry, density_source=source)


@pytest.mark.parametrize("name", ["", "Plate", "plate v2", "../plate", "plate.step", "p" * 65, 7])
def test_an_export_is_refused_a_name_that_is_not_a_part_s(
    geometry: ModuleType, tmp_path: Path, name: object
) -> None:
    with pytest.raises(geometry.HelperRefusedError, match="name"):
        geometry.export(object(), tmp_path, name)
    assert list(tmp_path.iterdir()) == []


def test_an_export_goes_into_a_module_s_own_directory(geometry: ModuleType, tmp_path: Path) -> None:
    assert geometry.EXPORTS == "exports"
    assert geometry.STEP_TIMESTAMP == "2000-01-01T00:00:00"
    with pytest.raises(geometry.HelperRefusedError, match="directory"):
        geometry.export(object(), tmp_path / "absent", "plate")
    assert not (tmp_path / "absent").exists()


def test_a_written_file_is_named_by_its_size_and_sha256(
    geometry: ModuleType, tmp_path: Path
) -> None:
    (tmp_path / "plate.step").write_bytes(b"ISO-10303-21;")
    found = geometry.file_entry(str(tmp_path / "plate.step"), "exports/plate.step")
    assert found == {
        "file": "exports/plate.step",
        "size": _q(13, "byte"),
        "sha256": hashlib.sha256(b"ISO-10303-21;").hexdigest(),
    }


# ---- units a graph quantity can carry ----------------------------------------------------------


def test_every_unit_a_helper_writes_is_one_the_physics_gate_s_registry_reads(
    geometry: ModuleType, structure: ModuleType
) -> None:
    found: set[str] = set()

    def collect(part: object) -> None:
        if isinstance(part, dict):
            if "unit" in part:
                found.add(part["unit"])
            for inner in part.values():
                collect(inner)

    collect(_properties(geometry))
    collect(_load_case(structure))
    collect(
        structure.simply_supported_centre_load(
            "deck", **({k: v for k, v in BEAM.items() if k != "length"} | {"span": _q(60, "mm")})
        )
    )
    assert found == {"m", "m**3", "kg", "kg*m**2", "kg/m**3", "Pa", "N", "N*m", "m**4"}
    for unit in sorted(found):
        assert require_bounded_spelling(unit) == unit
        assert units.parse(1, unit) is not None


# ---- read off the syntax trees: no harness, no limit, no judgement -----------------------------

LIMIT_WORDS = (
    "limit",
    "allowable",
    "allowed",
    "threshold",
    "tolerance",
    "maximum",
    "minimum",
    "required",
    "target",
    "criterion",
    "yield",
    "strength",
    "margin",
)
ALLOWED_IMPORTS = {
    "__future__",
    "collections",
    "datetime",
    "hashlib",
    "importlib",
    "json",
    "math",
    "os",
    "re",
    "sys",
    "typing",
    "build123d",
    "result_file",
}


def _imports(tree: ast.AST) -> set[str]:
    roots: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            roots |= {alias.name.split(".")[0] for alias in node.names}
        elif isinstance(node, ast.ImportFrom):
            roots.add((node.module or "").split(".")[0] if node.level == 0 else ".")
    return roots


def _limit_parameters(tree: ast.AST) -> list[str]:
    """Parameters a caller could hand a limit through: named for one, in any function."""
    found = []
    for node in ast.walk(tree):
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.Lambda)):
            args = node.args
            every = [*args.posonlyargs, *args.args, *args.kwonlyargs]
            every += [a for a in (args.vararg, args.kwarg) if a is not None]
            for arg in every:
                words = arg.arg.lower().split("_")
                if any(w.startswith(tuple(LIMIT_WORDS)) or w in ("max", "min") for w in words):
                    found.append(arg.arg)
    return found


def _compared_with_a_number(tree: ast.AST) -> list[str]:
    """Comparisons that hold a number other than zero: a limit written into the helper."""
    found = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Compare):
            for side in (node.left, *node.comparators):
                inner = side.operand if isinstance(side, ast.UnaryOp) else side
                if (
                    isinstance(inner, ast.Constant)
                    and isinstance(inner.value, (int, float, complex))
                    and not isinstance(inner.value, bool)
                    and inner.value != 0
                ):
                    found.append(ast.unparse(node))
    return found


def _truth_values_outside_a_call_s_options(tree: ast.AST) -> list[str]:
    """``True`` or ``False`` anywhere but as a call's keyword option, and functions answering it."""
    options = {
        id(keyword.value)
        for node in ast.walk(tree)
        if isinstance(node, ast.Call)
        for keyword in node.keywords
    }
    found = [
        ast.unparse(node)
        for node in ast.walk(tree)
        if isinstance(node, ast.Constant)
        and isinstance(node.value, bool)
        and id(node) not in options
    ]
    for node in ast.walk(tree):
        if (
            isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
            and node.returns is not None
            and "bool" in ast.unparse(node.returns)
        ):
            found.append(f"{node.name} -> {ast.unparse(node.returns)}")
    return found


def _judgement_words_as_text(tree: ast.AST, words: frozenset[str]) -> list[str]:
    """A judgement's name written as text or as a name, outside the one list that refuses them."""
    listed: set[int] = set()
    for node in ast.walk(tree):
        if isinstance(node, (ast.Assign, ast.AnnAssign)):
            targets = node.targets if isinstance(node, ast.Assign) else [node.target]
            if any(isinstance(t, ast.Name) and t.id == "JUDGEMENT_WORDS" for t in targets):
                listed |= {id(inner) for inner in ast.walk(node)}
    found = []
    for node in ast.walk(tree):
        if id(node) in listed:
            continue
        if isinstance(node, ast.Constant) and isinstance(node.value, str):
            if node.value.lower() in words:
                found.append(node.value)
        elif isinstance(node, ast.Name) and node.id.lower() in words:
            found.append(node.id)
        elif isinstance(node, ast.keyword) and (node.arg or "").lower() in words:
            found.append(node.arg or "")
        elif isinstance(node, (ast.FunctionDef, ast.arg)):
            name = node.name if isinstance(node, ast.FunctionDef) else node.arg
            if name.lower() in words:
                found.append(name)
    return found


def _trees() -> dict[str, ast.AST]:
    found = sorted(path.name for path in HELPERS.glob("*.py"))
    assert found == sorted(FILES), "a helper was added or removed; this test names each one"
    return {name: ast.parse((HELPERS / name).read_text(encoding="utf-8")) for name in found}


def test_no_helper_imports_the_harness_or_anything_but_the_kernel_and_the_standard_library() -> (
    None
):
    for name, tree in _trees().items():
        roots = _imports(tree)
        assert roots, name
        assert "physgate" not in roots, name
        assert roots <= ALLOWED_IMPORTS, (name, sorted(roots - ALLOWED_IMPORTS))


def test_no_helper_function_takes_a_limit() -> None:
    for name, tree in _trees().items():
        assert _limit_parameters(tree) == [], name


def test_no_helper_compares_anything_with_a_number_written_into_it() -> None:
    for name, tree in _trees().items():
        assert _compared_with_a_number(tree) == [], name


def test_no_helper_holds_a_truth_value_or_answers_one() -> None:
    for name, tree in _trees().items():
        assert _truth_values_outside_a_call_s_options(tree) == [], name


def test_no_helper_writes_a_judgement_s_name_but_in_the_list_that_refuses_them(
    result_file: ModuleType,
) -> None:
    words = frozenset(result_file.JUDGEMENT_WORDS)
    assert {"pass", "ok", "clean", "valid", "verdict"} <= words
    for name, tree in _trees().items():
        assert _judgement_words_as_text(tree, words) == [], name


@pytest.mark.parametrize(
    ("source", "reader"),
    [
        ("def check(stress, limit): ...", "limit"),
        ("def check(stress, *, allowable_stress): ...", "limit"),
        ("def check(stress, max_stress=1): ...", "limit"),
        ("def check(stress, **limits): ...", "limit"),
        ("f = lambda value, threshold: value", "limit"),
        ("if stress > 40e6: pass", "number"),
        ("if 0.2 <= clearance: pass", "number"),
        ("x = volume == -1", "number"),
        ("x = [v for v in values if v < 1e-3]", "number"),
        ("result = {'within': True}", "truth"),
        ("def fits(a, b) -> bool: ...", "truth"),
        ("def fits(a, b):\n    return False", "truth"),
        ("result = {'ok': 1}", "word"),
        ("result = dict(verdict='fine')", "word"),
        ("passed = stress", "word"),
        ("def valid(x): ...", "word"),
    ],
)
def test_each_reading_of_a_syntax_tree_sees_what_it_is_for(source: str, reader: str) -> None:
    tree = ast.parse(source)
    words = frozenset({"ok", "verdict", "passed", "valid"})
    found = {
        "limit": _limit_parameters(tree),
        "number": _compared_with_a_number(tree),
        "truth": _truth_values_outside_a_call_s_options(tree),
        "word": _judgement_words_as_text(tree, words),
    }
    assert found[reader] != [], source


def test_the_readings_pass_what_a_helper_legitimately_writes() -> None:
    tree = ast.parse(
        "import os\n"
        "def in_si(given, units, what):\n"
        "    if not 0 < given < float('inf'):\n"
        "        raise ValueError(what)\n"
        "    if len(given) != AXES or depth > MAX_DEPTH:\n"
        "        os.makedirs(what, exist_ok=True)\n"
        "    return given\n"
    )
    assert _limit_parameters(tree) == []
    assert _compared_with_a_number(tree) == []
    assert _truth_values_outside_a_call_s_options(tree) == []
    assert _judgement_words_as_text(tree, frozenset({"ok"})) == []
