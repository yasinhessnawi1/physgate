"""A block solved by finite elements agrees with the beam formulas, and the solve refuses nonsense.

The script of ``design_solve`` runs as a module's own on a provisioned tool environment's
interpreter (scikit-fem on the pinned numpy and scipy), with the helpers of this checkout, a
home of its own and, where this machine can take it away, no network. It solves the fixture bar
as a cantilever and as a simply supported beam and writes a result file for each.

**Stated before the test**, so that no bound is fitted to what the solve happens to give, for
each of the two load cases on the fixture bar at the helper's default mesh:

1. the solve's deflection lies within 5 % of the beam formula's;
2. its reactions sum to the applied load within 1e-6 of the load;
3. the peak axial stress clear of supports and load (farther than one thickness from every held
   face or edge and every loaded face) lies within 10 % of the beam formula's axial stress at
   the same section.

The 5 % allows for what the formula leaves out: the fixed face also stops the bar's Poisson
contraction, a load spread over a face or a strip, and shear. The 10 % allows, besides, for
stresses read at integration points inside the elements, never at the surface fibre the formula
gives. Measured on UiA before this test: cantilever -1.59 %, 9e-10, -4.5 %; simply supported
+0.66 %, 1e-10, -5.6 %. The peak stress at a support is not held to anything: it is singular and
grows as the mesh is refined, and the result says so.

``PHYSGATE_TOOL_ENVIRONMENT`` names a provisioned environment (``toolenv/provision.py``); with
none named one is built here, which needs the network once (``PHYSGATE_TOOLENV_CACHE`` keeps the
downloads).
"""

from __future__ import annotations

import importlib.util
import json
import math
import os
import subprocess
import sys
from collections.abc import Iterator
from pathlib import Path
from types import ModuleType
from typing import Any

import pytest
from design_fixtures import offline_prefix, quiet_environment
from design_solve import BAR, LENGTH_MM, SOLVE, SOLVE_RECORDED, STATED_HASH

from physgate.gate import units
from physgate.unit_spelling import require_bounded_spelling

pytestmark = pytest.mark.integration

REPO = Path(__file__).resolve().parents[3]
HELPERS = REPO / "toolenv" / "helpers"
NAMED = os.environ.get("PHYSGATE_TOOL_ENVIRONMENT", "")
CASES = ("cantilever", "simply_supported")
#: The formula's deflection each case is read against.
FORMULA_DEFLECTION = {"cantilever": "tip_deflection", "simply_supported": "centre_deflection"}
#: Stated before the test (module docstring).
DEFLECTION_AGREES = 0.05
REACTIONS_AGREE = 1e-6
AXIAL_STRESS_AGREES = 0.10
#: How closely a run repeats the recorded Linux values, on any platform.
REPEATS = 1e-6
SOLVE_FIELDS = {
    "schema",
    "kind",
    "case",
    "part",
    "model",
    "mesh",
    "inputs",
    "assumptions",
    "values",
    "closed_form",
    "libraries",
}


def _provision() -> ModuleType:
    spec = importlib.util.spec_from_file_location(
        "toolenv_provision", REPO / "toolenv" / "provision.py"
    )
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def _writable(root: Path) -> None:
    for directory, dirs, _ in os.walk(root):
        for name in [".", *dirs]:
            path = Path(directory, name)
            if not path.is_symlink():
                path.chmod(0o755)


@pytest.fixture(scope="module")
def env(tmp_path_factory: pytest.TempPathFactory) -> Iterator[Path]:
    if NAMED:
        yield Path(NAMED)
        return
    built = tmp_path_factory.mktemp("built") / "env"
    kept = os.environ.get("PHYSGATE_TOOLENV_CACHE")
    cache = Path(kept) if kept else tmp_path_factory.mktemp("toolenv-cache")
    _provision().provision(built, cache)
    yield built
    _writable(built)


class Run:
    """One run of the solve script in a module directory of its own."""

    def __init__(self, env: Path, root: Path, mode: str) -> None:
        self.module = root / "modules" / "bar"
        self.module.mkdir(parents=True)
        home = root / "home"
        home.mkdir()
        script = self.module / "bar.py"
        script.write_text(SOLVE, encoding="utf-8")
        argv = [
            str(env / "venv" / "bin" / "python"),
            "-I",
            str(script),
            str(HELPERS),
            str(self.module),
            json.dumps(BAR),
            str(LENGTH_MM),
            STATED_HASH,
            mode,
        ]
        self.done = subprocess.run(
            [*offline_prefix(), *argv],
            cwd=self.module,
            env=quiet_environment(home),
            capture_output=True,
            text=True,
            timeout=900,
            check=False,
        )

    def lines(self, start: str) -> list[str]:
        assert self.done.returncode == 0, self.done.stderr[-3000:]
        return [ln[len(start) :] for ln in self.done.stdout.splitlines() if ln.startswith(start)]

    def result(self, case: str) -> dict[str, Any]:
        told = json.loads(self.lines("SOLVE ")[0])
        assert told[case] == str(self.module / f"{case}.result.json")
        found = json.loads(Path(told[case]).read_text(encoding="utf-8"))
        assert isinstance(found, dict)
        return found


@pytest.fixture(scope="module")
def solved(env: Path, tmp_path_factory: pytest.TempPathFactory) -> Run:
    return Run(env, tmp_path_factory.mktemp("cases"), "cases")


@pytest.fixture(scope="module")
def refused(env: Path, tmp_path_factory: pytest.TempPathFactory) -> Run:
    return Run(env, tmp_path_factory.mktemp("refusals"), "refusals")


def _value(result: dict[str, Any], *path: str) -> Any:  # noqa: ANN401 - a number or a list
    found: Any = result
    for name in path:
        found = found[name]
    return found["value"]


# ---- the agreement, stated before the test ----------------------------------------------------


@pytest.mark.parametrize("case", CASES)
def test_the_solve_s_deflection_is_within_5_percent_of_the_beam_formula_s(
    solved: Run, case: str
) -> None:
    result = solved.result(case)
    solve = _value(result, "values", "deflection")
    formula = _value(result, "closed_form", "values", FORMULA_DEFLECTION[case])
    assert abs(solve - formula) <= DEFLECTION_AGREES * formula, (solve, formula)


@pytest.mark.parametrize("case", CASES)
def test_the_reactions_sum_to_the_applied_load_within_a_part_in_a_million(
    solved: Run, case: str
) -> None:
    result = solved.result(case)
    applied = _value(result, "values", "applied_force")
    reaction = _value(result, "values", "reaction_force")
    load = _value(result, "inputs", "force")
    assert math.isclose(applied[2], -load, rel_tol=1e-9)
    for direction in range(3):
        assert abs(reaction[direction] + applied[direction]) <= REACTIONS_AGREE * load
    assert _value(result, "values", "residual_off_supports") <= REACTIONS_AGREE * load
    if case == "simply_supported":
        each = _value(result, "values", "reaction_force_at_each_support")
        assert sum(each) == pytest.approx(reaction[2], rel=1e-9)
        # Each share is summed over its own support's edge: the start and the end of the span,
        # read off the nodes it was summed over (the load is symmetric, so the shares alone
        # cannot tell the two edges apart).
        span = _value(result, "inputs", "span")
        where = result["values"]["reaction_force_at_each_support"]["at"]
        assert where["unit"] == "m"
        assert where["value"] == pytest.approx([0.0, span], abs=1e-12)
        for share in each:
            assert abs(share - load / 2) <= REACTIONS_AGREE * load
    else:
        moment = _value(result, "values", "reaction_moment")
        length = _value(result, "inputs", "length")
        assert abs(abs(moment[1]) - load * length) <= REACTIONS_AGREE * load * length


@pytest.mark.parametrize("case", CASES)
def test_the_axial_stress_clear_of_supports_and_load_is_within_10_percent_of_the_formula_s(
    solved: Run, case: str
) -> None:
    result = solved.result(case)
    found = result["values"]["peak_axial_stress_clear_of_supports_and_load"]
    beside = result["closed_form"]["values"]["axial_stress_at_the_section_of_the_clear_peak"]
    section = found["at"]["value"][0]
    assert beside["at"]["value"] == section
    inputs = {name: _value(result, "inputs", name) for name in result["inputs"]}
    length = inputs["length"] if "length" in inputs else inputs["span"]
    force, width, thickness = inputs["force"], inputs["width"], inputs["thickness"]
    # The formula, done here by hand at the section the solve read.
    if case == "cantilever":
        by_hand = 6 * force * (length - section) / (width * thickness**2)
    else:
        by_hand = 3 * force * min(section, length - section) / (width * thickness**2)
    assert beside["value"] == pytest.approx(by_hand, rel=1e-12)
    # Clear of supports and load: farther than one thickness from each.
    assert thickness < section < length - thickness
    if case == "simply_supported":
        assert abs(section - length / 2) > thickness / 2 + thickness
    assert abs(abs(found["value"]) - by_hand) <= AXIAL_STRESS_AGREES * by_hand, (found, by_hand)


# ---- what the result holds ---------------------------------------------------------------------


def _quantities(found: object) -> list[dict[str, Any]]:
    if isinstance(found, dict):
        own = [found] if "unit" in found else []
        return own + [q for inner in found.values() for q in _quantities(inner)]
    if isinstance(found, list):
        return [q for inner in found for q in _quantities(inner)]
    return []


def _loose_numbers(found: object, inside: bool = False) -> list[object]:
    if isinstance(found, dict):
        has_unit = "unit" in found
        return [
            n
            for name, inner in found.items()
            for n in _loose_numbers(inner, has_unit and name == "value")
        ]
    if isinstance(found, list):
        return [n for inner in found for n in _loose_numbers(inner, inside)]
    if isinstance(found, bool):
        return [found]
    return [] if inside or not isinstance(found, (int, float)) else [found]


@pytest.mark.parametrize("case", CASES)
def test_a_solve_s_result_has_its_fields_and_every_number_a_unit_the_gate_reads(
    solved: Run, case: str
) -> None:
    result = solved.result(case)
    assert set(result) == SOLVE_FIELDS
    assert result["kind"] == "solve"
    assert result["libraries"] == {"scikit-fem": "12.0.2", "numpy": "2.1.2", "scipy": "1.14.1"}
    # Every number is a value with its unit, save the mesh's counts and the layout version.
    loose = _loose_numbers({k: v for k, v in result.items() if k not in ("mesh", "schema")})
    assert loose == []
    found = {q["unit"] for q in _quantities(result)}
    assert found == {"m", "Pa", "N", "N*m", "m**4", "1"} - (
        {"N*m"} if case == "simply_supported" else set()
    )
    for unit in sorted(found):
        assert require_bounded_spelling(unit) == unit
        assert units.parse(1, unit) is not None
    for name in ("deflection", "peak_displacement", "residual_off_supports"):
        assert result["values"][name]["unit"] in ("m", "N")
    assert result["values"]["peak_von_mises_stress"]["unit"] == "Pa"


@pytest.mark.parametrize("case", CASES)
def test_the_peak_at_a_support_is_marked_as_growing_and_no_word_says_converged(
    solved: Run, case: str
) -> None:
    result = solved.result(case)
    peak = result["values"]["peak_von_mises_stress"]
    clear = result["values"]["peak_von_mises_stress_clear_of_supports_and_load"]
    assert "singular" in peak["read"] and "grows as the mesh is refined" in peak["read"]
    assert peak["value"] >= clear["value"]
    text = (solved.module / f"{case}.result.json").read_text(encoding="utf-8").lower()
    assert "converg" not in text


@pytest.mark.parametrize("case", CASES)
def test_a_second_solve_at_half_the_counts_is_reported_with_the_relative_change(
    solved: Run, case: str
) -> None:
    result = solved.result(case)
    mesh = result["mesh"]
    assert mesh["counts"] == {"along": 40, "across": 4, "through": 4}
    assert mesh["unknowns"] == 19683
    coarser = mesh["coarser"]
    assert coarser["counts"]["across"] == coarser["counts"]["through"] == 2
    expected_along = 20 if case == "cantilever" else 22
    assert coarser["counts"]["along"] == expected_along
    assert coarser["unknowns"] == 3 * (2 * expected_along + 1) * 25
    assert mesh["unknowns_cap"] == 65000
    changes = result["values"]["mesh_change"]
    assert set(changes) == {
        "deflection",
        "peak_von_mises_stress",
        "peak_von_mises_stress_clear_of_supports_and_load",
        "peak_axial_stress_clear_of_supports_and_load",
    }
    for name, change in changes.items():
        fine = result["values"][name]["value"]
        coarse = change["coarser_mesh"]["value"]
        assert coarse != fine, name
        assert change["relative_change"] == {"value": (fine - coarse) / fine, "unit": "1"}


def test_a_stated_geometry_hash_is_recorded_as_stated_and_marked_unchecked(solved: Run) -> None:
    stated = solved.result("cantilever")["part"]
    assert stated["name"] == "bar"
    assert stated["geometry_hash"] == STATED_HASH
    assert stated["geometry_hash_check"].startswith("unchecked")
    unstated = solved.result("simply_supported")["part"]
    assert unstated["geometry_hash"] is None
    assert unstated["geometry_hash_check"].startswith("unchecked")


@pytest.mark.parametrize("case", CASES)
def test_the_numbers_repeat_the_recorded_linux_ones_to_a_part_in_a_million(
    solved: Run, case: str
) -> None:
    result = solved.result(case)
    recorded = SOLVE_RECORDED[case]
    for name, value in recorded.items():
        if name == "coarser_deflection":
            found = result["values"]["mesh_change"]["deflection"]["coarser_mesh"]["value"]
        else:
            found = result["values"][name]["value"]
        assert found == pytest.approx(value, rel=REPEATS), name


# ---- nonsense is refused -----------------------------------------------------------------------


def test_the_solve_refuses_no_supports_zero_thickness_and_a_load_that_is_not_finite(
    refused: Run,
) -> None:
    told = dict(json.loads(line) for line in refused.lines("REFUSED "))
    assert refused.lines("NOT-REFUSED ") == []
    assert "names no supports" in told["no supports"]
    assert "names no supports" in told["supports by no known name"]
    assert "thickness" in told["zero thickness"]
    assert "force" in told["an infinite load"]
    assert "force" in told["a load that is not a number"]
    assert "force" in told["a load without its unit"]
    assert "below one half" in told["a Poisson's ratio of one half"]
    assert "at most 65000" in told["a mesh over the cap"]
    assert len(told) == 8
    assert not list(refused.module.glob("*.result.json"))
