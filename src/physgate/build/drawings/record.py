"""The records a drawing is read from and written as: the part's, the projection's, the drawing's.

Three files, of which only the drawing's record is a closed schema with every numeric quantity
a value with its unit:

- **the part's record**, ``<part>.result.json``, as the tool environment's geometry helper writes
  it beside a part script. It is another writer's file, so it is not closed here: only what a
  drawing needs of it is read (the part's name, its ``geometry_hash``, its bounding box in metres
  and its exported STEP file by name, size and sha256), and the rest is left as it is. It is the
  part's current state for every check: whatever wrote it last is the part.
- **the projection**, ``<part>.projection.json``: what the CAD kernel's own hidden-line projection
  gave for each view, as polylines in the view's own plane, the hash of the shape it was
  projected from, its bounding box (``box_mm``) and the libraries' versions. Its schema is closed,
  but its numbers are bare: every coordinate is in millimetres, as the field's name says.
- **the drawing's record**, ``<part>.drawing.json``, written beside the SVG: the hash the drawing
  was made from, the views, the title block's fields, the overall dimensions and the rule they
  are rounded by, the scale, the files by name, size and sha256, and the generator's version.
  Every number in it is a value with its unit. No time, no absolute path, no machine: made twice
  from one part on one machine, its bytes are the same.
"""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Annotated, Any, Literal

from pydantic import BaseModel, ConfigDict, Field, StringConstraints, ValidationError

#: The version of the drawing record's layout. A reader that meets another number does not guess.
SCHEMA = 1
#: The generator's name and version, written into every record and every title block.
GENERATOR = "physgate drawing"
GENERATOR_VERSION = "1"
ViewName = Literal["front", "top", "side", "isometric"]
OverallName = Literal["length_x", "width_y", "height_z"]
#: The views every drawing holds, in the order they are listed.
VIEWS: tuple[ViewName, ...] = ("front", "top", "side", "isometric")
#: Where each view is seen from (the direction from the part towards the viewer) and which way
#: is up on it, in the part's axes as it was built: the front from -y, the top from +z, the side
#: from the left (-x), and an isometric view from +x, -y, +z.
VIEW_DIRECTIONS: dict[ViewName, tuple[tuple[int, int, int], tuple[int, int, int]]] = {
    "front": ((0, -1, 0), (0, 0, 1)),
    "top": ((0, 0, 1), (0, 1, 0)),
    "side": ((-1, 0, 0), (0, 0, 1)),
    "isometric": ((1, -1, 1), (0, 0, 1)),
}
#: The overall dimensions, each along one of the part's axes as it was built.
OVERALL: tuple[OverallName, ...] = ("length_x", "width_y", "height_z")
#: The title block's fields, in the order they are shown.
TITLE_FIELDS: tuple[str, ...] = (
    "part",
    "units",
    "scale",
    "geometry_hash",
    "drawn_from",
    "projection",
    "generator",
)
#: The most a record file may hold before it is read.
MAX_RECORD_BYTES = 8 << 20

Hash = Annotated[str, StringConstraints(pattern=r"^sha256:[0-9a-f]{64}$")]
Sha256 = Annotated[str, StringConstraints(pattern=r"^[0-9a-f]{64}$")]
PartName = Annotated[str, StringConstraints(pattern=r"^[a-z0-9][a-z0-9_-]{0,63}$")]
#: A file inside a module or beside a drawing: a relative name whose every part starts with a
#: letter or a digit, so never a path out of it.
FileName = Annotated[
    str,
    StringConstraints(pattern=r"^[A-Za-z0-9][A-Za-z0-9._-]*(/[A-Za-z0-9][A-Za-z0-9._-]*)*$"),
]
Text = Annotated[str, StringConstraints(min_length=1)]
Finite = Annotated[float, Field(allow_inf_nan=False)]


class RecordError(ValueError):
    """A record cannot be read as a drawing needs it."""


class _Frozen(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid", strict=True, allow_inf_nan=False)


class _Read(BaseModel):
    """A model of another writer's file: the fields read here, the rest left as it is."""

    model_config = ConfigDict(frozen=True, extra="ignore", strict=True, allow_inf_nan=False)


# --- the part's record, as the geometry helper writes it ---------------------------------------


class Bytes(_Frozen):
    """A file's size."""

    value: Annotated[int, Field(ge=0)]
    unit: Literal["byte"]


class FileEntry(_Frozen):
    """A file by its name, its size and its sha256."""

    file: FileName
    size: Bytes
    sha256: Sha256


class Corner(_Read):
    """A corner of the bounding box, in metres."""

    value: Annotated[tuple[Finite, Finite, Finite], Field()]
    unit: Literal["m"]


class BoundingBox(_Read):
    """The part's bounding box as the kernel measured it."""

    low_corner: Corner
    high_corner: Corner

    def extents_mm(self) -> dict[OverallName, float]:
        """The box's length along x, width along y and height along z, in millimetres."""
        low, high = self.low_corner.value, self.high_corner.value
        return {name: (high[i] - low[i]) * 1000.0 for i, name in enumerate(OVERALL)}


class PartValues(_Read):
    """What of a part's values a drawing reads: its bounding box."""

    bounding_box: BoundingBox


class PartRecord(_Read):
    """A part's record as the geometry helper writes it: what a drawing reads of it."""

    schema_: Literal[1] = Field(alias="schema")
    kind: Literal["geometry"]
    part: PartName
    geometry_hash: Hash
    values: PartValues
    exports: tuple[FileEntry, ...]

    def step(self) -> FileEntry:
        """The part's exported STEP file.

        Raises:
            RecordError: the record names no STEP file, or more than one.
        """
        found = [entry for entry in self.exports if entry.file.endswith(".step")]
        if len(found) != 1:
            msg = f"the part's record names {len(found)} STEP files; a drawing is made from one"
            raise RecordError(msg)
        return found[0]


# --- the projection, as the kernel gave it ----------------------------------------------------

Point = tuple[Finite, Finite]
Polyline = Annotated[tuple[Point, ...], Field(min_length=2)]


class ViewLines(_Frozen):
    """One view's edges as the kernel projected them: visible, and hidden behind the part."""

    visible: tuple[Polyline, ...]
    hidden: tuple[Polyline, ...]


class Projection(_Frozen):
    """The kernel's projection of a part's shape onto the four views."""

    kind: Literal["projection"]
    geometry_hash: Hash
    #: The shape's bounding box in millimetres: the low corner, then the high one.
    box_mm: tuple[Finite, Finite, Finite, Finite, Finite, Finite]
    views: dict[ViewName, ViewLines]
    libraries: dict[Text, Text]


# --- the drawing's record ---------------------------------------------------------------------


class Millimetres(_Frozen):
    """A length on the drawing or of the part, in millimetres."""

    value: Finite
    unit: Literal["mm"]


class Ratio(_Frozen):
    """A dimensionless number: a scale, a count."""

    value: Finite | int
    unit: Literal["1"]


class Direction(_Frozen):
    """A direction in the part's axes, as it was built."""

    value: tuple[Finite, Finite, Finite]
    unit: Literal["1"]


class Scale(_Frozen):
    """The drawing's one scale: drawn length over the part's length, and as a drawing writes it."""

    value: Finite
    unit: Literal["1"]
    shown_as: Text


class Sheet(_Frozen):
    """The sheet the views are drawn on."""

    size: Text
    width: Millimetres
    height: Millimetres


class View(_Frozen):
    """One view: where it is seen from, which way is up, and how many lines it draws."""

    name: ViewName
    #: The direction from the part towards the viewer, in the part's axes.
    viewed_from: Direction
    up: Direction
    visible_paths: Ratio
    hidden_paths: Ratio


class Generator(_Frozen):
    """What made the drawing."""

    name: Text
    version: Text


class DrawingFiles(_Frozen):
    """The files a drawing is: the SVG and the projection it was composed from."""

    svg: FileEntry
    projection: FileEntry


class DrawingRecord(_Frozen):
    """The record written beside a drawing."""

    schema_: Literal[1] = Field(alias="schema")
    kind: Literal["drawing"]
    shown: Text
    left_out: Text
    part: PartName
    geometry_hash: Hash
    drawn_from: FileEntry
    files: DrawingFiles
    sheet: Sheet
    scale: Scale
    units: Literal["mm"]
    projection_method: Text
    views: tuple[View, ...]
    overall: dict[OverallName, Millimetres]
    shown_to: Millimetres
    #: How a dimension is rounded to ``shown_to``: ``half up``.
    rounding: Text
    agreement_within: Millimetres
    title_block: dict[str, Text]
    generator: Generator
    libraries: dict[Text, Text]


# --- reading and writing ----------------------------------------------------------------------


def _json_of(path: Path, what: str) -> str:
    """The text of the JSON file at ``path``, read once and checked to be JSON."""
    try:
        if path.is_symlink() or not path.is_file():
            msg = f"{what} is not a file: {path.name}"
            raise RecordError(msg)
        if path.stat().st_size > MAX_RECORD_BYTES:
            msg = f"{what} is over {MAX_RECORD_BYTES} bytes: {path.name}"
            raise RecordError(msg)
        text = path.read_text(encoding="utf-8")
        json.loads(text)
    except OSError as exc:
        msg = f"{what} cannot be read: {exc.strerror}"
        raise RecordError(msg) from exc
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        msg = f"{what} is not JSON: {path.name}"
        raise RecordError(msg) from exc
    return text


def _first_problem(exc: ValidationError) -> str:
    error = exc.errors()[0]
    where = ".".join(str(part) for part in error["loc"]) or "the top level"
    return f"{where}: {error['msg']}"


def load_part(path: Path) -> PartRecord:
    """The part's record at ``path``.

    Raises:
        RecordError: it is no file, not JSON, or not a part's record as the geometry helper
            writes one.
    """
    text = _json_of(path, "the part's record")
    try:
        return PartRecord.model_validate_json(text)
    except ValidationError as exc:
        msg = f"the part's record is not one the geometry helper writes: {_first_problem(exc)}"
        raise RecordError(msg) from exc


def load_drawing(path: Path) -> DrawingRecord:
    """The drawing's record at ``path``.

    Raises:
        RecordError: it is no file, not JSON, or not a drawing's record of this layout.
    """
    text = _json_of(path, "the drawing's record")
    try:
        return DrawingRecord.model_validate_json(text)
    except ValidationError as exc:
        msg = f"the drawing's record is not one this version writes: {_first_problem(exc)}"
        raise RecordError(msg) from exc


def parse_projection(data: Any) -> Projection:  # noqa: ANN401 - JSON as the kernel printed it
    """The projection in ``data``, held to its schema.

    JSON has no tuples, so the lists are read as tuples here (the model is strict).

    Raises:
        RecordError: it is not a projection of the four views.
    """
    try:
        projection = Projection.model_validate_json(json.dumps(data))
    except (TypeError, ValueError) as exc:
        detail = _first_problem(exc) if isinstance(exc, ValidationError) else str(exc)
        msg = f"the kernel's projection is not one this version reads: {detail}"
        raise RecordError(msg) from exc
    missing = [name for name in VIEWS if name not in projection.views]
    if missing:
        msg = f"the kernel's projection has no {', '.join(missing)} view"
        raise RecordError(msg)
    return projection


def render(data: BaseModel | dict[str, Any]) -> str:
    """A record's text: sorted keys, two-space indents, one line end."""
    dumped = data.model_dump(mode="json", by_alias=True) if isinstance(data, BaseModel) else data
    return json.dumps(dumped, sort_keys=True, indent=2, allow_nan=False) + "\n"


def compact(data: BaseModel) -> str:
    """A large record's text: sorted keys, no spaces, one line end."""
    dumped = data.model_dump(mode="json", by_alias=True)
    return json.dumps(dumped, sort_keys=True, separators=(",", ":"), allow_nan=False) + "\n"


def entry_of(data: bytes, name: str) -> FileEntry:
    """A file's bytes as a record names the file: ``name``, its size and its sha256."""
    return FileEntry(
        file=name,
        size=Bytes(value=len(data), unit="byte"),
        sha256=hashlib.sha256(data).hexdigest(),
    )
