"""Closed-form stress and deflection of a straight beam of rectangular section, as numbers.

A part script states a load case (a length, a section, a material stiffness and a force, each a
value with its unit) and gets back the deflection, the peak bending stress and the reactions the
textbook formula gives, in SI, with the formula and what it assumes written beside them. That
is all: no allowable stress goes in and no margin or judgement comes out. A margin of safety is
the script's own line, against a strength it states with its source, and whether the margin is
enough is the physics gate's and the reviewer's to say.

The formulas are Euler-Bernoulli beam theory (Roark's Formulas for Stress and Strain, table of
beam cases; any mechanics of materials text): a slender, straight, prismatic beam of a linear
elastic material, small deflections, shear deformation neglected. They are evidence for a part
that is close to such a beam and for no other.

The same two load cases can also be solved by finite elements (:func:`solve`), on a rectangular
block the helper meshes itself, with the formula's numbers written beside the solve's. That is
the one shape this helper meshes: a part far from a block has no solve here.

The closed form needs the standard library only; the solve imports scikit-fem and numpy when it
is called. Nothing here imports the harness.
"""

from __future__ import annotations

import math
import os
import re
import sys
from collections.abc import Mapping
from typing import Any

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from result_file import SCHEMA, HelperRefusedError, checked, quantity  # noqa: E402

#: The spellings an input may have, and the factor that brings each to SI.
LENGTH_UNITS = {"m": 1.0, "mm": 1.0e-3}
STIFFNESS_UNITS = {"Pa": 1.0, "MPa": 1.0e6, "GPa": 1.0e9}
FORCE_UNITS = {"N": 1.0}

ASSUMPTIONS = [
    "a straight beam of constant rectangular section, bent about the axis across its width",
    "a linear elastic, isotropic material; stress below yield",
    "small deflections; plane sections stay plane (Euler-Bernoulli)",
    "shear deformation and stress concentrations (holes, corners) are neglected",
]


def in_si(given: Any, units: Mapping[str, float], what: str) -> float:  # noqa: ANN401 - an input as the script wrote it
    """``given`` in the SI unit of its kind; refused unless it is a positive value with a unit.

    Raises:
        HelperRefusedError: it is a bare number, names a unit that is not one of ``units``, or
            its value is not a finite number above zero.
    """
    if not isinstance(given, Mapping) or set(given) != {"value", "unit"}:
        raise HelperRefusedError(f"{what} is given as a value with its unit, and nothing else")
    value, unit = given["value"], given["unit"]
    if unit not in units:
        raise HelperRefusedError(f"{what} is in one of {sorted(units)}, not {unit!r}")
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise HelperRefusedError(f"{what} has a value that is not a number")
    scaled = float(value) * units[unit]
    if not 0 < scaled < float("inf"):
        raise HelperRefusedError(f"{what} is a finite number above zero")
    return scaled


def _section(
    inputs: Mapping[str, Any], length_name: str
) -> tuple[float, float, float, float, float]:
    names = {length_name, "width", "thickness", "modulus", "force"}
    if set(inputs) != names:
        raise HelperRefusedError(f"this load case takes exactly {sorted(names)}")
    return (
        in_si(inputs[length_name], LENGTH_UNITS, f"the {length_name}"),
        in_si(inputs["width"], LENGTH_UNITS, "the width"),
        in_si(inputs["thickness"], LENGTH_UNITS, "the thickness"),
        in_si(inputs["modulus"], STIFFNESS_UNITS, "the modulus of elasticity"),
        in_si(inputs["force"], FORCE_UNITS, "the force"),
    )


def _case(
    case: str, model: str, formulas: dict[str, str], inputs: dict[str, Any], values: dict[str, Any]
) -> dict[str, Any]:
    if not case or not case.isprintable():
        raise HelperRefusedError("a load case has a printable name")
    return checked(
        {
            "schema": SCHEMA,
            "kind": "load_case",
            "case": case,
            "model": model,
            "formulas": formulas,
            "assumptions": list(ASSUMPTIONS),
            "inputs": inputs,
            "values": values,
        }
    )


def cantilever_end_load(case: str, **inputs: Any) -> dict[str, Any]:  # noqa: ANN401 - each a value with its unit
    """A beam clamped at one end with a transverse force at the other.

    ``inputs`` are ``length``, ``width``, ``thickness`` (the dimension along the force),
    ``modulus`` (of elasticity) and ``force``, each ``{"value": ..., "unit": ...}``.

    Raises:
        HelperRefusedError: an input is missing, extra, without a unit or not above zero.
    """
    length, width, thickness, modulus, force = _section(inputs, "length")
    second_moment = width * thickness**3 / 12
    return _case(
        case,
        "cantilever, transverse end load, rectangular section",
        {
            "second_moment_of_area": "I = b*h**3/12",
            "tip_deflection": "delta = F*L**3/(3*E*I)",
            "peak_bending_stress": "sigma = 6*F*L/(b*h**2), at the clamp, at the outer fibre",
            "reaction_force": "R = F, at the clamp",
            "reaction_moment": "M = F*L, at the clamp",
        },
        {
            "length": quantity(length, "m"),
            "width": quantity(width, "m"),
            "thickness": quantity(thickness, "m"),
            "modulus": quantity(modulus, "Pa"),
            "force": quantity(force, "N"),
        },
        {
            "second_moment_of_area": quantity(second_moment, "m**4"),
            "tip_deflection": quantity(force * length**3 / (3 * modulus * second_moment), "m"),
            "peak_bending_stress": quantity(6 * force * length / (width * thickness**2), "Pa"),
            "reaction_force": quantity(force, "N"),
            "reaction_moment": quantity(force * length, "N*m"),
        },
    )


def simply_supported_centre_load(case: str, **inputs: Any) -> dict[str, Any]:  # noqa: ANN401 - each a value with its unit
    """A beam resting on two end supports with a transverse force at mid-span.

    ``inputs`` are ``span``, ``width``, ``thickness`` (the dimension along the force),
    ``modulus`` (of elasticity) and ``force``, each ``{"value": ..., "unit": ...}``.

    Raises:
        HelperRefusedError: an input is missing, extra, without a unit or not above zero.
    """
    span, width, thickness, modulus, force = _section(inputs, "span")
    second_moment = width * thickness**3 / 12
    return _case(
        case,
        "simply supported beam, transverse load at mid-span, rectangular section",
        {
            "second_moment_of_area": "I = b*h**3/12",
            "centre_deflection": "delta = F*L**3/(48*E*I)",
            "peak_bending_stress": "sigma = 3*F*L/(2*b*h**2), at mid-span, at the outer fibre",
            "reaction_force": "R = F/2, at each support",
        },
        {
            "span": quantity(span, "m"),
            "width": quantity(width, "m"),
            "thickness": quantity(thickness, "m"),
            "modulus": quantity(modulus, "Pa"),
            "force": quantity(force, "N"),
        },
        {
            "second_moment_of_area": quantity(second_moment, "m**4"),
            "centre_deflection": quantity(force * span**3 / (48 * modulus * second_moment), "m"),
            "peak_bending_stress": quantity(3 * force * span / (2 * width * thickness**2), "Pa"),
            "reaction_force": quantity(force / 2, "N", at="each of the two supports"),
        },
    )


# ---- the same load cases, solved by finite elements on a block ----------------------------------

#: Poisson's ratio is a ratio, written with the unit one.
RATIO_UNITS = {"1": 1.0}
#: The Poisson's ratio of a material that keeps its volume; a solid's lies below it.
INCOMPRESSIBLE = 0.5
#: Quadratic elements through the thickness and across the width of the solve's own mesh.
LAYERS = 4
#: How many times as long along the block as it is thick an element may be, at most.
ELONGATION = 2
#: The most unknowns a solve takes; a bigger mesh is refused before it is built.
UNKNOWNS_CAP = 65_000
#: The longest name a part may be given.
PART_NAME_CHARS = 200
#: How a geometry hash is written, when a script states one.
HASH_FORM = re.compile(r"sha256:[0-9a-f]{64}")
#: The directions of the block: along its length, across its width, through its thickness.
ALONG, ACROSS, THROUGH = 0, 1, 2

#: The load cases a block is solved for: the input its length is given by, the formula beside
#: it, how it is held and loaded, where its deflection is read, and how many thicknesses long
#: it is at least (so that a band one thickness clear of every support and load is left).
SOLVED: dict[str, dict[str, Any]] = {
    "cantilever_end_load": {
        "length": "length",
        "formula": cantilever_end_load,
        "held": "one end face fixed in every direction",
        "loaded": "the force spread evenly over the other end face, along the thickness",
        "deflection": (
            "the mean displacement along the thickness of the loaded end face's corner nodes"
        ),
        "thicknesses": 3,
    },
    "simply_supported_centre_load": {
        "length": "span",
        "formula": simply_supported_centre_load,
        "held": (
            "the bottom edge across the width at each end held along the thickness, the one at "
            "the start also along the block, and its middle point across the width"
        ),
        "loaded": (
            "the force spread evenly, along the thickness, over a strip of the top face one "
            "thickness wide at mid-span"
        ),
        "deflection": (
            "the mean displacement along the thickness of the corner nodes on the mid-plane at "
            "mid-span"
        ),
        "thicknesses": 6,
    },
}

SOLVE_ASSUMPTIONS = [
    "a rectangular block of a linear elastic, isotropic material, meshed by this helper; the block "
    "stands for the part, and nothing compares it with the part's shape",
    "small displacements and strains: linear elasticity in three dimensions",
    "27-node hexahedra (quadratic), integrated at order 4",
    "stresses are read at the integration points, inside the elements, not at a surface",
    "clear of supports and load means farther than one thickness, along the block, from every "
    "held face or edge and every loaded face",
    "the peak von Mises stress over the whole body includes the zone at a support, where a fixed "
    "face or edge makes the stress singular: that peak grows as the mesh is refined",
    "a second solve at half the element counts in each direction is reported beside this one with "
    "the relative change, (this mesh - coarser mesh) / this mesh; nothing more is said of the mesh",
]


def along(load_case: str, length: float, thickness: float, layers: int) -> list[float]:
    """The element boundaries along the block, in metres, for ``layers`` through its thickness.

    Every support, every edge of a loaded strip and the mid-span lie on a boundary, and no
    element is longer than :data:`ELONGATION` times its thickness.
    """
    step = ELONGATION * thickness / layers
    marks = {0.0, length}
    if load_case == "simply_supported_centre_load":
        marks |= {length / 2 - thickness / 2, length / 2, length / 2 + thickness / 2}
    ordered = sorted(marks)
    edges = [ordered[0]]
    for index in range(len(ordered) - 1):
        start, end = ordered[index], ordered[index + 1]
        count = max(1, math.ceil((end - start) / step * (1 - 1e-12)))
        edges += [start + (end - start) * k / count for k in range(1, count + 1)]
    return edges


def unknowns(load_case: str, length: float, thickness: float, layers: int) -> int:
    """How many unknowns the block's mesh at ``layers`` holds: three per node of its elements."""
    elements = len(along(load_case, length, thickness, layers)) - 1
    return 3 * (2 * elements + 1) * (2 * layers + 1) ** 2


def _block(  # noqa: PLR0913, PLR0915 - one solve, its numbers read in one place
    load_case: str,
    length: float,
    width: float,
    thickness: float,
    modulus: float,
    ratio: float,
    force: float,
    layers: int,
) -> dict[str, Any]:
    """Solve the block at ``layers``; its numbers in SI, as plain floats and lists."""
    import numpy as np
    from skfem import (
        Basis,
        ElementHex2,
        ElementVector,
        FacetBasis,
        LinearForm,
        MeshHex,
        asm,
        condense,
    )
    from skfem import solve as solve_system
    from skfem.models.elasticity import lame_parameters, linear_elasticity

    near = 1e-9 * length

    def at(found: Any, place: float) -> Any:  # noqa: ANN401 - numpy arrays
        return np.abs(found - place) <= near

    mesh = MeshHex.init_tensor(
        np.array(along(load_case, length, thickness, layers)),
        np.linspace(0.0, width, layers + 1),
        np.linspace(0.0, thickness, layers + 1),
    )
    element = ElementVector(ElementHex2())
    basis = Basis(mesh, element, intorder=4)
    stiffness = asm(linear_elasticity(*lame_parameters(modulus, ratio)), basis)
    count = basis.N
    axis = np.full(count, -1)
    for dofs in (basis.nodal_dofs, basis.edge_dofs, basis.facet_dofs, basis.interior_dofs):
        if dofs.shape[0]:
            for direction in (ALONG, ACROSS, THROUGH):
                axis[dofs[direction::3].ravel()] = direction
    where = basis.doflocs

    middle = length / 2
    if load_case == "cantilever_end_load":
        held = np.nonzero(at(where[ALONG], 0.0))[0]
        facets = mesh.facets_satisfying(lambda x: at(x[ALONG], length))
        area = width * thickness
    else:
        bottom = at(where[THROUGH], 0.0)
        start = bottom & at(where[ALONG], 0.0)
        ends = start | (bottom & at(where[ALONG], length))
        pin = start & at(where[ACROSS], width / 2)
        held = np.nonzero(
            (ends & (axis == THROUGH)) | (start & (axis == ALONG)) | (pin & (axis == ACROSS))
        )[0]
        facets = mesh.facets_satisfying(
            lambda x: (
                at(x[THROUGH], thickness) & (np.abs(x[ALONG] - middle) <= thickness / 2 + near)
            )
        )
        area = width * thickness
    if not held.size:
        raise HelperRefusedError("a solve holds the block somewhere; no node was held")
    traction = -force / area

    @LinearForm
    def load(v: Any, w: Any) -> Any:  # noqa: ANN401, ARG001 - the library's form
        return traction * v.value[THROUGH]

    applied = asm(load, FacetBasis(mesh, element, facets=facets, intorder=4))
    landed = float(applied[axis == THROUGH].sum())
    if not math.isclose(landed, -force, rel_tol=1e-9):
        raise HelperRefusedError(
            f"the load spread over the block sums to {landed} N, not {-force} N"
        )
    displacement = solve_system(*condense(stiffness, applied, D=held))
    if not np.all(np.isfinite(displacement)):
        raise HelperRefusedError("the solve gave a displacement that is not a finite number")
    residual = stiffness @ displacement - applied
    free = np.setdiff1d(np.arange(count), held)
    directions = (ALONG, ACROSS, THROUGH)
    reaction = [float(residual[held][axis[held] == d].sum()) for d in directions]

    corners = mesh.p
    moved = np.array([displacement[basis.nodal_dofs[d]] for d in directions])
    size = np.sqrt((moved**2).sum(axis=0))
    if load_case == "cantilever_end_load":
        read = at(corners[ALONG], length)
    else:
        read = at(corners[ALONG], middle) & at(corners[THROUGH], thickness / 2)

    gradient = basis.interpolate(displacement).grad
    strain = 0.5 * (gradient + np.transpose(gradient, (1, 0, 2, 3)))
    lam, mu = lame_parameters(modulus, ratio)
    stress = 2 * mu * strain
    trace = strain[0, 0] + strain[1, 1] + strain[2, 2]
    for d in directions:
        stress[d, d] += lam * trace
    s = stress
    von_mises = np.sqrt(
        0.5 * ((s[0, 0] - s[1, 1]) ** 2 + (s[1, 1] - s[2, 2]) ** 2 + (s[2, 2] - s[0, 0]) ** 2)
        + 3 * (s[0, 1] ** 2 + s[1, 2] ** 2 + s[0, 2] ** 2)
    )
    points = basis.global_coordinates().value
    x = points[ALONG]
    clear = (x > thickness) & (x < length - thickness)
    if load_case == "simply_supported_centre_load":
        clear &= np.abs(x - middle) > thickness / 2 + thickness
    flat = [points[d].ravel() for d in directions]

    def place(index: Any) -> list[float]:  # noqa: ANN401 - a numpy index
        return [float(flat[d][index]) for d in directions]

    axial = s[0, 0].ravel()
    inside = np.nonzero(clear.ravel())[0]
    peak = int(von_mises.ravel().argmax())
    clear_peak = int(inside[von_mises.ravel()[inside].argmax()])
    axial_peak = int(inside[np.abs(axial[inside]).argmax()])
    found: dict[str, Any] = {
        "counts": {
            "along": len(along(load_case, length, thickness, layers)) - 1,
            "across": layers,
            "through": layers,
        },
        "unknowns": int(count),
        "deflection": float(-moved[THROUGH][read].mean()),
        "peak_displacement": float(size.max()),
        "peak_displacement_at": [float(corners[d][size.argmax()]) for d in directions],
        "reaction": reaction,
        "applied": [float(applied[axis == d].sum()) for d in directions],
        "residual": float(np.abs(residual[free]).max()),
        "von_mises": float(von_mises.ravel()[peak]),
        "von_mises_at": place(peak),
        "clear_von_mises": float(von_mises.ravel()[clear_peak]),
        "clear_von_mises_at": place(clear_peak),
        "clear_axial": float(axial[axial_peak]),
        "clear_axial_at": place(axial_peak),
    }
    if load_case == "cantilever_end_load":
        centre = np.array([0.0, width / 2, thickness / 2])
        arms = where[:, held] - centre[:, None]
        pushed = np.zeros((3, held.size))
        pushed[axis[held], np.arange(held.size)] = residual[held]
        found["moment"] = [float(m) for m in np.cross(arms.T, pushed.T).sum(axis=0)]
        found["moment_about"] = [float(c) for c in centre]
    else:
        lifted = held[axis[held] == THROUGH]
        found["supports"] = [
            float(residual[lifted][at(where[ALONG][lifted], place_x)].sum())
            for place_x in (0.0, length)
        ]
    return found


def _change(fine: float, coarse: float, unit: str) -> dict[str, Any]:
    return {
        "coarser_mesh": quantity(coarse, unit),
        "relative_change": quantity((fine - coarse) / fine, "1"),
    }


def solve(
    case: str,
    *,
    load_case: str,
    part: str,
    geometry_hash: str | None = None,
    **inputs: Any,  # noqa: ANN401 - each a value with its unit
) -> dict[str, Any]:
    """One of the beam load cases solved by finite elements on a block of the stated size.

    ``load_case`` is a key of :data:`SOLVED`, which says how the block is held and loaded;
    ``inputs`` are the closed form's (``length`` or ``span``, ``width``, ``thickness``,
    ``modulus``, ``force``) and ``poisson`` (the unit ``1``), each ``{"value": ..., "unit": ...}``.
    ``part`` names the part the block stands for; a ``geometry_hash`` the script states is
    recorded as it was stated and marked unchecked. The formula's numbers are written beside
    the solve's, and a second solve at half the element counts beside this one.

    Raises:
        HelperRefusedError: the load case names no supports this helper knows, an input is
            missing, extra, without its unit or not a finite number above zero, Poisson's ratio
            is not below one half, the block is too short for a band clear of its supports and
            load, its mesh holds more than :data:`UNKNOWNS_CAP` unknowns, the part's name or
            hash is not written as one, or the solve gave a number that is not finite.
    """
    if load_case not in SOLVED:
        raise HelperRefusedError(
            f"a solve is held by naming one of {sorted(SOLVED)}; {load_case!r} names no supports"
        )
    if (
        not isinstance(part, str)
        or not part
        or not part.isprintable()
        or len(part) > PART_NAME_CHARS
    ):
        raise HelperRefusedError(
            f"a part is named by printable text of 1 to {PART_NAME_CHARS} characters"
        )
    if geometry_hash is not None and (
        not isinstance(geometry_hash, str) or not HASH_FORM.fullmatch(geometry_hash)
    ):
        raise HelperRefusedError("a geometry hash is written sha256: and 64 lowercase hex digits")
    given = dict(inputs)
    if "poisson" not in given:
        raise HelperRefusedError("a solve is given Poisson's ratio as poisson, with the unit 1")
    ratio = in_si(given.pop("poisson"), RATIO_UNITS, "Poisson's ratio")
    if not ratio < INCOMPRESSIBLE:
        raise HelperRefusedError("Poisson's ratio of a solid is below one half")
    chosen = SOLVED[load_case]
    closed = chosen["formula"](case, **given)
    si = {name: closed["inputs"][name]["value"] for name in closed["inputs"]}
    length, width, thickness = si[chosen["length"]], si["width"], si["thickness"]
    if length < chosen["thicknesses"] * thickness:
        raise HelperRefusedError(
            f"this block is at least {chosen['thicknesses']} thicknesses long, so that a band "
            "one thickness clear of every support and load is left"
        )
    held = unknowns(load_case, length, thickness, LAYERS)
    if held > UNKNOWNS_CAP:
        raise HelperRefusedError(
            f"this block's mesh holds {held} unknowns; a solve takes at most {UNKNOWNS_CAP}"
        )
    numbers = (load_case, length, width, thickness, si["modulus"], ratio, si["force"])
    fine = _block(*numbers, LAYERS)
    coarse = _block(*numbers, LAYERS // 2)

    section = fine["clear_axial_at"][ALONG]
    if load_case == "cantilever_end_load":
        formula = "sigma = 6*F*(L - x)/(b*h**2), at the outer fibre"
        expected = 6 * si["force"] * (length - section) / (width * thickness**2)
    else:
        formula = "sigma = 3*F*min(x, L - x)/(b*h**2), at the outer fibre"
        expected = 3 * si["force"] * min(section, length - section) / (width * thickness**2)

    def counts(found: dict[str, Any]) -> dict[str, Any]:
        return {"counts": found["counts"], "unknowns": found["unknowns"]}

    values: dict[str, Any] = {
        "deflection": quantity(fine["deflection"], "m", read=chosen["deflection"]),
        "peak_displacement": quantity(
            fine["peak_displacement"], "m", at=quantity(fine["peak_displacement_at"], "m")
        ),
        "applied_force": quantity(fine["applied"], "N", directions="along, across, through"),
        "reaction_force": quantity(
            fine["reaction"],
            "N",
            directions="along, across, through",
            on="the block, from its supports",
        ),
        "residual_off_supports": quantity(
            fine["residual"], "N", read="the largest out-of-balance force at an unknown not held"
        ),
        "peak_von_mises_stress": quantity(
            fine["von_mises"],
            "Pa",
            at=quantity(fine["von_mises_at"], "m"),
            read=(
                "over the whole body, the support's singular zone included; it grows as the "
                "mesh is refined"
            ),
        ),
        "peak_von_mises_stress_clear_of_supports_and_load": quantity(
            fine["clear_von_mises"], "Pa", at=quantity(fine["clear_von_mises_at"], "m")
        ),
        "peak_axial_stress_clear_of_supports_and_load": quantity(
            fine["clear_axial"], "Pa", at=quantity(fine["clear_axial_at"], "m")
        ),
        "mesh_change": {
            "deflection": _change(fine["deflection"], coarse["deflection"], "m"),
            "peak_von_mises_stress": _change(fine["von_mises"], coarse["von_mises"], "Pa"),
            "peak_von_mises_stress_clear_of_supports_and_load": _change(
                fine["clear_von_mises"], coarse["clear_von_mises"], "Pa"
            ),
            "peak_axial_stress_clear_of_supports_and_load": _change(
                fine["clear_axial"], coarse["clear_axial"], "Pa"
            ),
        },
    }
    if load_case == "cantilever_end_load":
        values["reaction_moment"] = quantity(
            fine["moment"],
            "N*m",
            directions="along, across, through",
            about=quantity(fine["moment_about"], "m"),
        )
    else:
        values["reaction_force_at_each_support"] = quantity(
            fine["supports"], "N", direction="through", at=quantity([0.0, length], "m")
        )
    from importlib.metadata import version

    return checked(
        {
            "schema": SCHEMA,
            "kind": "solve",
            "case": closed["case"],
            "part": {
                "name": part,
                "geometry_hash": geometry_hash,
                "geometry_hash_check": (
                    "unchecked: recorded as the script stated it; nothing compares it with the "
                    "block solved"
                ),
            },
            "model": f"{closed['model']}, by finite elements: {chosen['held']}; {chosen['loaded']}",
            "mesh": {
                "element": (
                    "27-node hexahedron (quadratic), one displacement per direction per node"
                ),
                **counts(fine),
                "coarser": counts(coarse),
                "unknowns_cap": UNKNOWNS_CAP,
            },
            "inputs": closed["inputs"] | {"poisson": quantity(ratio, "1")},
            "assumptions": list(SOLVE_ASSUMPTIONS),
            "values": values,
            "closed_form": {
                "assumptions": closed["assumptions"],
                "formulas": closed["formulas"] | {"axial_stress_at_a_section": formula},
                "values": closed["values"]
                | {
                    "axial_stress_at_the_section_of_the_clear_peak": quantity(
                        expected, "Pa", at=quantity(section, "m")
                    )
                },
            },
            "libraries": {name: version(name) for name in ("scikit-fem", "numpy", "scipy")},
        }
    )
