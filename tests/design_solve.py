"""The block a structure solve is held to, the script that solves it, and the numbers it gave.

The fixture is a 60 x 10 x 3 mm bar of a printed plastic's stiffness (2.3 GPa, Poisson's ratio
0.35) under 1 N, solved as a cantilever and as a simply supported beam on the tool environment's
interpreter. ``SOLVE`` is the script a module would hold: it calls the structure helper, writes
one result file per load case, and prints what it wrote. Given ``refusals`` it instead offers the
helper nonsense, one call at a time, and prints what each was told.

``SOLVE_RECORDED`` holds the values the script gave on Linux x86_64 (UiA, 14.11.2026), against
which every later run is compared to a part in a million.
"""

from __future__ import annotations

#: The fixture block: what a part script states about it, each a value with its unit.
BAR = {
    "width": {"value": 10, "unit": "mm"},
    "thickness": {"value": 3, "unit": "mm"},
    "modulus": {"value": 2.3, "unit": "GPa"},
    "poisson": {"value": 0.35, "unit": "1"},
    "force": {"value": 1, "unit": "N"},
}
#: Its length, or its span between supports.
LENGTH_MM = 60
#: The geometry hash the script states for the cantilever (and none for the other case).
STATED_HASH = "sha256:" + "5" * 64

SOLVE = """
import json, sys
sys.path.insert(0, sys.argv[1])
import result_file, structure

BAR = json.loads(sys.argv[3])
LENGTH = {"value": float(sys.argv[4]), "unit": "mm"}
HASH = sys.argv[5]

if sys.argv[6] == "cases":
    told = {}
    cantilever = structure.solve(
        "bar as a cantilever", load_case="cantilever_end_load", part="bar",
        geometry_hash=HASH, length=LENGTH, **BAR)
    told["cantilever"] = result_file.write(sys.argv[2] + "/cantilever.result.json", cantilever)
    simple = structure.solve(
        "bar on two supports", load_case="simply_supported_centre_load", part="bar",
        span=LENGTH, **BAR)
    named = sys.argv[2] + "/simply_supported.result.json"
    told["simply_supported"] = result_file.write(named, simple)
    print("SOLVE " + json.dumps(told))
else:
    inf, nan = float("inf"), float("nan")
    tries = {
        "no supports": dict(load_case=None),
        "supports by no known name": dict(load_case="free"),
        "zero thickness": dict(thickness={"value": 0, "unit": "mm"}),
        "an infinite load": dict(force={"value": inf, "unit": "N"}),
        "a load that is not a number": dict(force={"value": nan, "unit": "N"}),
        "a load without its unit": dict(force=1),
        "a Poisson's ratio of one half": dict(poisson={"value": 0.5, "unit": "1"}),
        "a mesh over the cap": dict(length={"value": 210, "unit": "mm"}),
    }
    for name, change in tries.items():
        given = {"load_case": "cantilever_end_load", "length": LENGTH, **BAR, **change}
        try:
            structure.solve("nonsense", part="bar", **given)
            print("NOT-REFUSED " + name)
        except structure.HelperRefusedError as refused:
            print("REFUSED " + json.dumps([name, str(refused)]))
"""

#: What the script gave on Linux x86_64 (UiA, 14.11.2026), in SI.
SOLVE_RECORDED = {
    "cantilever": {
        "deflection": 0.0013691477464080077,
        "peak_displacement": 0.0013702568303196297,
        "peak_von_mises_stress": 3580332.343132056,
        "peak_von_mises_stress_clear_of_supports_and_load": 3503957.094145691,
        "peak_axial_stress_clear_of_supports_and_load": 3619051.2779170075,
        "coarser_deflection": 0.0013644699472310036,
    },
    "simply_supported": {
        "deflection": 8.75297806761532e-05,
        "peak_displacement": 8.834348286849942e-05,
        "peak_von_mises_stress": 921099.7393837669,
        "peak_von_mises_stress_clear_of_supports_and_load": 797542.9378351246,
        "peak_axial_stress_clear_of_supports_and_load": -796985.6260595289,
        "coarser_deflection": 8.765507224974716e-05,
    },
}
