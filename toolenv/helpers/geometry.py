"""Numbers and files from a shape a part script built with the CAD kernel, and its hash.

A part script builds a shape and asks here for what a design records about it:

- :func:`mass_properties`: volume, mass for a density the script states with its source, the
  centre of mass, and the inertia about the centre of mass;
- :func:`interference` and :func:`clearance` of two shapes as they are placed;
- :func:`geometry_hash`: one hash of the shape itself, the same on every machine and after
  every export, and another after any dimension changes;
- :func:`export`: a STEP and an STL file in the module's ``exports`` folder, by name, size and
  sha256;
- :func:`geometry_result` and :func:`pair_result`: the result a script writes beside itself
  with :func:`result_file.write`;
- :func:`reference_file` and :func:`import_reference`: a published model the environment
  carries in its ``reference`` folder, by its name, size and sha256, and read as a shape;
  :func:`reference_result`: what a script measured from it, and by which rules.

Every number leaves in SI as a value with its unit. Nothing here says whether a number is good,
and no function takes a limit to compare one with.

**The hash** is taken over a description of the shape, not over a file: a STEP file carries a
timestamp, and an STL file's bytes differ between machines for one shape. The description holds
the shape's volume, area, centre of mass and bounding box, every face by its kind, area and
centre, every edge by its kind and length, and every vertex; each list sorted; every number in
millimetres, rounded to six decimals, with a negative zero written as zero. It was measured
equal on macOS arm64 and Linux x86_64 for shapes made of planes and cylinders, lines and
circles. A shape holding any other kind of face or edge is refused, with the kind named, and
never hashed by guess: the kind joins :data:`MEASURED_FACE_KINDS` or
:data:`MEASURED_EDGE_KINDS` once it has been measured equal on both. Six decimals of a
millimetre is a nanometre; the two machines differed by parts in 10**16. A number that happens
to lie on a rounding boundary can still round apart, and then the two hashes differ, visibly.

This file runs on the tool environment's interpreter and imports nothing of the harness. The
kernel is imported only inside the functions that measure a shape, so a refusal needs none.
"""

from __future__ import annotations

import hashlib
import json
import os
import re
import sys
from collections.abc import Mapping, Sequence
from typing import Any

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from result_file import SCHEMA, HelperRefusedError, checked, quantity  # noqa: E402

#: The version of the shape description the hash is taken over, and its first element.
DESCRIPTION_VERSION = 1
#: The decimals of a millimetre (and of a degree, for a placement) the description keeps.
DECIMALS = 6
#: The kinds of face and edge whose description was measured equal on both platforms.
MEASURED_FACE_KINDS = frozenset({"CYLINDER", "PLANE"})
MEASURED_EDGE_KINDS = frozenset({"CIRCLE", "LINE"})
#: The time written into every STEP file's header, so that one machine repeats its bytes.
STEP_TIMESTAMP = "2000-01-01T00:00:00"
#: The folder of a module that holds its exports, and nothing else.
EXPORTS = "exports"
#: A part's name, which is also its files' name.
NAME = re.compile(r"[a-z0-9][a-z0-9_-]{0,63}")
#: A geometry hash as this file writes it.
HASH = re.compile(r"sha256:[0-9a-f]{64}")
#: The spellings a density may have, and the factor that brings each to kg/m**3.
DENSITY_UNITS = {"kg/m**3": 1.0, "g/cm**3": 1000.0}
#: The spellings a placement's position may have, and the factor that brings each to mm.
POSITION_UNITS = {"mm": 1.0, "m": 1000.0}

#: The components of a position, a rotation and a point.
AXES = 3

#: The environment's folder of published models, beside the folder these helpers are copied to.
REFERENCE = "reference"
#: A published model's file name: one name, never a path.
REFERENCE_NAME = re.compile(r"[A-Za-z0-9][A-Za-z0-9._-]{0,127}")
#: What a measurement says it measured: one short line of printable characters.
SUBJECT = re.compile(r"(?=.*[!-~])[ -~]{1,200}")
#: A file's sha256 as a result names it.
SHA256 = re.compile(r"[0-9a-f]{64}")

_MM = 1.0e-3
#: The distributions whose versions a result names: the library and its kernel.
LIBRARIES = ("build123d", "cadquery-ocp-novtk")


# ---- the description and the hash: no kernel needed -------------------------------------------


def _rounded(value: Any) -> float:  # noqa: ANN401 - a number as the kernel gave it
    """``value`` to the description's decimals, a negative zero written as zero."""
    kept = round(float(value), DECIMALS)
    return 0.0 if kept == 0 else kept


def description(measured: Mapping[str, Any]) -> str:
    """The canonical text of a measured shape, which its hash is taken over.

    ``measured`` is what :func:`measure` reads off a shape, in millimetres: ``volume``,
    ``area``, ``centre`` (of mass), ``box`` (the bounding box's low corner, then its high one),
    ``faces`` (each a kind, an area and a centre), ``edges`` (each a kind and a length) and
    ``vertices``.

    Raises:
        HelperRefusedError: a face or an edge is of a kind not measured equal on both
            platforms, or the shape has no face.
    """
    faces = [
        (str(face[0]), *(_rounded(number) for number in face[1:])) for face in measured["faces"]
    ]
    edges = [(str(edge[0]), _rounded(edge[1])) for edge in measured["edges"]]
    if not faces:
        raise HelperRefusedError("a shape with no face has no geometry hash")
    for what, found, known in (
        ("face", faces, MEASURED_FACE_KINDS),
        ("edge", edges, MEASURED_EDGE_KINDS),
    ):
        unmeasured = sorted({item[0] for item in found} - known)
        if unmeasured:
            raise HelperRefusedError(
                f"the shape has a {what} of kind {', '.join(unmeasured)}, whose description has "
                "not been measured equal on both platforms; it gets no geometry hash until it has"
            )
    head = [
        _rounded(measured["volume"]),
        _rounded(measured["area"]),
        *(_rounded(number) for number in measured["centre"]),
        *(_rounded(number) for number in measured["box"]),
    ]
    vertices = sorted(
        tuple(_rounded(number) for number in vertex) for vertex in measured["vertices"]
    )
    whole = [DESCRIPTION_VERSION, head, sorted(faces), sorted(edges), vertices]
    return json.dumps(whole, separators=(",", ":"), allow_nan=False)


def hash_of(measured: Mapping[str, Any]) -> str:
    """The geometry hash of a measured shape: ``sha256:`` over :func:`description`."""
    return "sha256:" + hashlib.sha256(description(measured).encode("ascii")).hexdigest()


def assembly_hash(parts: Sequence[Mapping[str, Any]]) -> str:
    """The hash of an assembly: its parts' hashes with where each is placed, sorted.

    Each part is ``{"geometry_hash": ..., "position": {"value": [x, y, z], "unit": "mm"},
    "rotation": {"value": [rx, ry, rz], "unit": "deg"}}``, the placement as the script states
    it. Two spellings of one rotation are two placements here.

    Raises:
        HelperRefusedError: there is no part, or a part's hash or placement is not as above.
    """
    if not parts:
        raise HelperRefusedError("an assembly has at least one part")
    lines = []
    for part in parts:
        if set(part) != {"geometry_hash", "position", "rotation"}:
            raise HelperRefusedError("a placed part is a geometry_hash, a position and a rotation")
        if not isinstance(part["geometry_hash"], str) or not HASH.fullmatch(part["geometry_hash"]):
            raise HelperRefusedError("a placed part names its geometry hash")
        position, rotation = part["position"], part["rotation"]
        if position.get("unit") not in POSITION_UNITS or rotation.get("unit") != "deg":
            raise HelperRefusedError("a position is in mm or m, and a rotation in deg")
        if len(position["value"]) != AXES or len(rotation["value"]) != AXES:
            raise HelperRefusedError("a position and a rotation have three components each")
        scale = POSITION_UNITS[position["unit"]]
        lines.append(
            [
                part["geometry_hash"],
                *(_rounded(float(number) * scale) for number in position["value"]),
                *(_rounded(number) for number in rotation["value"]),
            ]
        )
    whole = [DESCRIPTION_VERSION, "assembly", sorted(lines)]
    text = json.dumps(whole, separators=(",", ":"), allow_nan=False)
    return "sha256:" + hashlib.sha256(text.encode("ascii")).hexdigest()


def density_in_si(density: Any) -> float:  # noqa: ANN401 - a density as the script wrote it
    """``density`` in kg/m**3; refused unless it is a positive value with a known unit.

    Raises:
        HelperRefusedError: it is a bare number, in a unit that is not one of
            :data:`DENSITY_UNITS`, or its value is not a finite number above zero.
    """
    if not isinstance(density, Mapping) or set(density) != {"value", "unit"}:
        raise HelperRefusedError("a density is given as a value with its unit, and nothing else")
    value, unit = density["value"], density["unit"]
    if unit not in DENSITY_UNITS:
        raise HelperRefusedError(f"a density is in one of {sorted(DENSITY_UNITS)}, not {unit!r}")
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise HelperRefusedError("a density has a value that is not a number")
    scaled = float(value) * DENSITY_UNITS[unit]
    if not 0 < scaled < float("inf"):
        raise HelperRefusedError("a density is a finite number above zero")
    return scaled


def properties_from(
    volume_mm3: float,
    centre_mm: Sequence[float],
    inertia_mm5: Sequence[Sequence[float]],
    box_mm: Sequence[float],
    density: Any,  # noqa: ANN401 - a density as the script wrote it
    density_source: str,
) -> dict[str, Any]:
    """Mass properties in SI from what the kernel measured in millimetres at unit density.

    Raises:
        HelperRefusedError: the density is refused (:func:`density_in_si`), or no source for
            it is stated.
    """
    rho = density_in_si(density)
    if not isinstance(density_source, str) or not density_source.strip():
        raise HelperRefusedError("a density is stated with its source (a datasheet, a measurement)")
    # kg/m**3 on mm**3 and mm**5: one millimetre cubed is 1e-9 m**3, and to the fifth 1e-15 m**5.
    return {
        "volume": quantity(volume_mm3 * _MM**3, "m**3"),
        "mass": quantity(volume_mm3 * _MM**3 * rho, "kg"),
        "centre_of_mass": quantity([float(c) * _MM for c in centre_mm], "m"),
        "inertia": quantity(
            [[float(element) * _MM**5 * rho for element in row] for row in inertia_mm5],
            "kg*m**2",
            about="the centre of mass",
            axes="parallel to the x, y and z the shape was built in",
        ),
        "bounding_box": {
            "low_corner": quantity([float(c) * _MM for c in box_mm[:AXES]], "m"),
            "high_corner": quantity([float(c) * _MM for c in box_mm[AXES:]], "m"),
        },
        "density": quantity(rho, "kg/m**3", source=density_source.strip()),
    }


def _part_name(name: str) -> str:
    if not isinstance(name, str) or not NAME.fullmatch(name):
        raise HelperRefusedError(
            "a part's name is lower-case letters, digits, - and _, at most 64 characters"
        )
    return name


# ---- reading a shape: the kernel ----------------------------------------------------------------


def library_versions() -> dict[str, str]:
    """The installed versions of the CAD library and its kernel, for a result to name."""
    from importlib.metadata import version

    return {name: version(name) for name in LIBRARIES}


def measure(shape: Any) -> dict[str, Any]:  # noqa: ANN401 - a shape of the kernel's
    """What the description needs, read off ``shape`` in millimetres."""
    from build123d import CenterOf

    centre = shape.center(CenterOf.MASS)
    box = shape.bounding_box()
    return {
        "volume": float(shape.volume),
        "area": float(shape.area),
        "centre": [float(centre.X), float(centre.Y), float(centre.Z)],
        "box": [box.min.X, box.min.Y, box.min.Z, box.max.X, box.max.Y, box.max.Z],
        "faces": [
            (face.geom_type.name, face.area, *_xyz(face.center(CenterOf.MASS)))
            for face in shape.faces()
        ],
        "edges": [(edge.geom_type.name, edge.length) for edge in shape.edges()],
        "vertices": [(vertex.X, vertex.Y, vertex.Z) for vertex in shape.vertices()],
    }


def _xyz(vector: Any) -> tuple[float, float, float]:  # noqa: ANN401 - a vector of the kernel's
    return float(vector.X), float(vector.Y), float(vector.Z)


def geometry_hash(shape: Any) -> str:  # noqa: ANN401 - a shape of the kernel's
    """The geometry hash of ``shape``.

    Raises:
        HelperRefusedError: the shape holds a kind of face or edge not yet measured equal on
            both platforms (the module docstring says why it is not hashed anyway).
    """
    return hash_of(measure(shape))


def mass_properties(shape: Any, *, density: Any, density_source: str) -> dict[str, Any]:  # noqa: ANN401 - a shape; a density as written
    """Volume, mass, centre of mass, inertia about it and the bounding box of ``shape``, in SI.

    ``density`` is ``{"value": ..., "unit": "kg/m**3"}`` (or ``g/cm**3``) for the solid as it is
    made: a printed part's infill and walls are the script's to account for in the number it
    states. ``density_source`` says where the number comes from.

    Raises:
        HelperRefusedError: the density or its source is refused.
    """
    # Judged before the kernel is asked anything: a refusal needs no shape.
    density_in_si(density)
    found = measure(shape)
    inertia = shape.matrix_of_inertia
    rows = [[float(inertia[i][j]) for j in range(AXES)] for i in range(AXES)]
    return properties_from(
        found["volume"], found["centre"], rows, found["box"], density, density_source
    )


def interference(first: Any, second: Any) -> dict[str, Any]:  # noqa: ANN401 - two shapes of the kernel's
    """The volume the two shapes share as they are placed, in m**3."""
    common = first & second
    solids = common.solids() if common is not None and hasattr(common, "solids") else []
    volume = sum(float(solid.volume) for solid in solids)
    return {"interference_volume": quantity(volume * _MM**3, "m**3")}


def clearance(first: Any, second: Any) -> dict[str, Any]:  # noqa: ANN401 - two shapes of the kernel's
    """The shortest distance between the two shapes as they are placed, in m."""
    return {"clearance": quantity(float(first.distance_to(second)) * _MM, "m")}


def export(shape: Any, module: str | os.PathLike[str], name: str) -> list[dict[str, Any]]:  # noqa: ANN401 - a shape of the kernel's
    """Write ``<module>/exports/<name>.step`` and ``.stl``; return each by name, size and sha256.

    The STEP header carries a fixed time, so exporting one shape twice on one machine gives
    the same bytes. Bytes still differ between machines; the shape's identity is its
    :func:`geometry_hash`, never a file's digest.

    Raises:
        HelperRefusedError: the name is not a part's name, or ``module`` is not a directory.
    """
    # Judged before the kernel is imported: a refusal needs none.
    _part_name(name)
    if not os.path.isdir(module):
        raise HelperRefusedError("exports are written into a module's own directory")
    from datetime import datetime

    from build123d import export_step, export_stl

    folder = os.path.join(os.fspath(module), EXPORTS)
    os.makedirs(folder, exist_ok=True)
    step, stl = os.path.join(folder, f"{name}.step"), os.path.join(folder, f"{name}.stl")
    export_step(shape, step, timestamp=datetime.fromisoformat(STEP_TIMESTAMP))
    export_stl(shape, stl)
    return [file_entry(path, f"{EXPORTS}/{os.path.basename(path)}") for path in (step, stl)]


def file_entry(path: str, name: str) -> dict[str, Any]:
    """A written file as a result names it: its name in the module, its size and its sha256."""
    with open(path, "rb") as handle:
        digest = hashlib.file_digest(handle, "sha256").hexdigest()
    return {
        "file": name,
        "size": quantity(os.path.getsize(path), "byte"),
        "sha256": digest,
    }


def geometry_result(
    name: str,
    shape: Any,  # noqa: ANN401 - a shape of the kernel's
    *,
    density: Any,  # noqa: ANN401 - a density as the script wrote it
    density_source: str,
    exports: Sequence[Mapping[str, Any]] = (),
) -> dict[str, Any]:
    """The result of one part: its hash, its mass properties, its inputs and its exports.

    Raises:
        HelperRefusedError: the name, the density or its source is refused, or the shape gets
            no geometry hash.
    """
    values = mass_properties(shape, density=density, density_source=density_source)
    stated = values.pop("density")
    return checked(
        {
            "schema": SCHEMA,
            "kind": "geometry",
            "part": _part_name(name),
            "geometry_hash": geometry_hash(shape),
            "values": values,
            "inputs": {"density": stated},
            "exports": [dict(entry) for entry in exports],
            "libraries": library_versions(),
        }
    )


def pair_result(names: Sequence[str], first: Any, second: Any) -> dict[str, Any]:  # noqa: ANN401 - two shapes of the kernel's
    """The result of two placed parts: what they share and how far apart they are.

    Each shape is named by its hash as it is placed: its position is part of that hash, so it
    differs from the part's own hash unless the part sits where it was built. The pair's
    numbers are about exactly these two placed shapes.

    Raises:
        HelperRefusedError: there are not two names, a name is refused, or a shape gets no
            geometry hash.
    """
    if len(names) != len((first, second)):
        raise HelperRefusedError("a pair has two names, one for each shape")
    return checked(
        {
            "schema": SCHEMA,
            "kind": "pair",
            "parts": [_part_name(name) for name in names],
            "placed_geometry_hashes": [geometry_hash(first), geometry_hash(second)],
            "values": {**interference(first, second), **clearance(first, second)},
            "libraries": library_versions(),
        }
    )


# ---- a published model: read from the environment, measured by a script ----------------------


def reference_file(
    name: str, root: str | os.PathLike[str] | None = None
) -> tuple[str, dict[str, Any]]:
    """The published model ``name`` in the environment: its path, and its file's entry.

    The entry names the file as a result does: by its name, size and sha256.

    ``root`` is the environment; by default the one these helpers were copied into, found
    from this file's own folder. Provisioning placed the file there by the digest it was
    pinned with; the sha256 here is read from the bytes, for the result to carry.

    Raises:
        HelperRefusedError: the name is not a plain file name, or no regular file of that name
            is there (a link is refused).
    """
    if not isinstance(name, str) or not REFERENCE_NAME.fullmatch(name):
        raise HelperRefusedError("a published model is named by its file name, never a path")
    base = os.fspath(root) if root is not None else os.path.dirname(os.path.dirname(__file__))
    path = os.path.join(os.path.abspath(base), REFERENCE, name)
    if os.path.islink(path) or not os.path.isfile(path):
        raise HelperRefusedError(f"the environment carries no published model named {name}")
    return path, file_entry(path, f"{REFERENCE}/{name}")


def import_reference(
    name: str, root: str | os.PathLike[str] | None = None
) -> tuple[Any, dict[str, Any]]:
    """The published model ``name`` read as a shape by the kernel, and its file's entry.

    Raises:
        HelperRefusedError: as :func:`reference_file`.
    """
    path, entry = reference_file(name, root)
    from build123d import import_step

    return import_step(path), entry


def _reference_entry(reference: Any) -> dict[str, Any]:  # noqa: ANN401 - an entry as given
    if not isinstance(reference, Mapping) or set(reference) != {"file", "size", "sha256"}:
        raise HelperRefusedError("a measurement names its file as reference_file gave it")
    file, digest = reference["file"], reference["sha256"]
    named = isinstance(file, str) and file.startswith(f"{REFERENCE}/")
    if not named or not REFERENCE_NAME.fullmatch(file[len(REFERENCE) + 1 :]):
        raise HelperRefusedError("a measurement names its file as reference_file gave it")
    if not isinstance(digest, str) or not SHA256.fullmatch(digest):
        raise HelperRefusedError("a measurement names its file's sha256 as reference_file gave it")
    return dict(reference)


def _texts(given: Any, what: str) -> list[str]:  # noqa: ANN401 - a list as the script wrote it
    if not isinstance(given, (list, tuple)):
        raise HelperRefusedError(f"a measurement's {what} is a list of sentences")
    if not all(isinstance(item, str) and item.strip() for item in given):
        raise HelperRefusedError(f"each of a measurement's {what} is a sentence")
    return [item.strip() for item in given]


def reference_result(
    subject: str,
    reference: Mapping[str, Any],
    *,
    method: Sequence[str],
    values: Mapping[str, Any],
    inputs: Mapping[str, Any],
    assumptions: Sequence[str],
) -> dict[str, Any]:
    """What a script measured from a published model, as a result of its own kind.

    ``subject`` says in one line what was measured; ``reference`` is the file's entry from
    :func:`reference_file`; ``method`` lists, as sentences, the rules by which the features
    were found, so that a second reader can repeat them; ``inputs`` are what the script
    stated (a mass and its source); ``assumptions`` what it assumed; ``values`` the numbers,
    each with its unit.

    Raises:
        HelperRefusedError: the subject is not one short line, the file is not named as
            :func:`reference_file` names it, no rule is given, a list holds anything but
            sentences, or the result is refused (:func:`result_file.checked`).
    """
    line = subject.strip() if isinstance(subject, str) else ""
    if not SUBJECT.fullmatch(line):
        raise HelperRefusedError("a measurement says in one short line what was measured")
    rules = _texts(method, "rules")
    if not rules:
        raise HelperRefusedError("a measurement gives the rules that found its features")
    if not isinstance(values, Mapping) or not isinstance(inputs, Mapping):
        raise HelperRefusedError("a measurement's values and inputs are objects")
    return checked(
        {
            "schema": SCHEMA,
            "kind": "reference_measurement",
            "subject": line,
            "reference": _reference_entry(reference),
            "method": rules,
            "inputs": dict(inputs),
            "assumptions": _texts(assumptions, "assumptions"),
            "values": dict(values),
            "libraries": library_versions(),
        }
    )
