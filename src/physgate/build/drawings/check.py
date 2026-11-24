"""The drawing checker: rules over the drawing's files and the part's record, and no kernel.

It reads four files and runs nothing: the drawing's record, the SVG and the projection it names
beside it, and the part's record (``<part>.result.json``), which is the part's current state for
every check. Each check is judged on its own, whatever another found, so a drawing doctored in
one way fails in that one line:

1. **part**: the hash the drawing was made from is the part's current ``geometry_hash``. If it
   is not, the drawing is **stale**: the part changed after it was made, and a drawing is made
   again from the part, never patched (ARCH-111). If it is, the STEP file the drawing was drawn
   from is the one the part's record names, by name, size and sha256.
2. **file**: the SVG and the projection beside the record are the ones it names, by size and
   sha256; the SVG is on the record's sheet; the projection is of the record's hash, from the
   record's libraries, with as many lines of each kind in each view as the record says.
3. **views**: the SVG holds the front, top, side and isometric views, in that order in the
   record, each with at least one drawn line of two points or more and as many lines of each
   kind as the record says, and each seen from where this version draws it from.
4. **title block**: every field of the title block is in the SVG, with the text the record
   gives it, and the record's part, units, scale, hash, file drawn from, projection method and
   generator are the ones its fields show; its scale's number is the one its text writes.
5. **dimensions**: each overall dimension, as the record gives it and as the SVG shows it, is the
   part's extent as the part's record holds it, rounded once, half up, to a tenth of a
   millimetre (:func:`~physgate.build.drawings.sheet.shown_dimension`), so within
   :data:`AGREEMENT_MM` of it; and the record states that rule.

Every field of the drawing's record is read by one of these, except what
:data:`RECORDED_NOT_CHECKED` names: nothing else says those, so nothing can be compared with
them. The checker redraws nothing: what it does not catch is said in the command's help.

The verdict of a check is ``passes``, ``fails``, or for the first only, ``stale``.
"""

from __future__ import annotations

import hashlib
import json
import re
from dataclasses import dataclass
from typing import TYPE_CHECKING, Literal
from xml.etree import ElementTree

from physgate.build.drawings.record import (
    MAX_RECORD_BYTES,
    OVERALL,
    TITLE_FIELDS,
    VIEW_DIRECTIONS,
    VIEWS,
    RecordError,
    load_drawing,
    load_part,
    parse_projection,
)
from physgate.build.drawings.sheet import (
    AGREEMENT_MM,
    ROUNDING,
    RULE,
    SHOWN_TO_MM,
    shown_dimension,
)

if TYPE_CHECKING:
    from pathlib import Path

    from physgate.build.drawings.record import DrawingRecord, FileEntry, PartRecord, Projection

Verdict = Literal["passes", "fails", "stale"]

EXIT_PASSES = 0
EXIT_FAILS = 1
EXIT_REFUSED = 2
EXIT_STALE = 3

CHECKS: tuple[str, ...] = ("part", "file", "views", "title block", "dimensions")
#: The most an SVG may hold before it is read.
MAX_SVG_BYTES = 8 << 20
SVG = "{http://www.w3.org/2000/svg}"
#: A move or a line in a path's data, with its two coordinates.
_STEP = re.compile(r"[ML]\s*(-?\d+(?:\.\d+)?)\s+(-?\d+(?:\.\d+)?)")
#: A dimension as the drawing shows it: millimetres to one decimal.
_SHOWN = re.compile(r"[0-9]{1,6}\.[0-9]")
#: A scale as a drawing writes it: drawn length to the part's length.
_RATIO = re.compile(r"([1-9][0-9]{0,3}):([1-9][0-9]{0,3})")
#: What the drawing's record holds that no check reads, since nothing else says it.
RECORDED_NOT_CHECKED = "the record's shown and left_out words and the sheet's name"


@dataclass(frozen=True)
class Finding:
    """One check's verdict, with what it found in words."""

    check: str
    verdict: Verdict
    message: str


@dataclass(frozen=True)
class _Svg:
    """The SVG as read: its bytes, its parsed tree, or why there is neither."""

    data: bytes | None
    root: ElementTree.Element | None
    problem: str | None


def _read_svg(record: DrawingRecord, drawing: Path) -> _Svg:
    path = drawing.parent / record.files.svg.file
    name = record.files.svg.file
    try:
        if path.is_symlink() or not path.is_file():
            return _Svg(None, None, f"the drawing file {name} is not there beside the record")
        if path.stat().st_size > MAX_SVG_BYTES:
            return _Svg(None, None, f"the drawing file {name} is over {MAX_SVG_BYTES} bytes")
        data = path.read_bytes()
    except OSError as exc:
        return _Svg(None, None, f"the drawing file {name} cannot be read: {exc.strerror}")
    # This writer declares no document type; one that does is not its file, and an entity is
    # never expanded here.
    if b"<!DOCTYPE" in data or b"<!ENTITY" in data:
        return _Svg(data, None, f"the drawing file {name} declares a document type")
    try:
        root = ElementTree.fromstring(data)  # noqa: S314 - bounded, no document type
    except ElementTree.ParseError as exc:
        return _Svg(data, None, f"the drawing file {name} is not well-formed XML: {exc}")
    return _Svg(data, root, None)


@dataclass(frozen=True)
class _Projection:
    """The projection file as read: its bytes, its parsed projection, or why there is neither."""

    data: bytes | None
    told: Projection | None
    problem: str | None


def _read_projection(record: DrawingRecord, drawing: Path) -> _Projection:
    name = record.files.projection.file
    path = drawing.parent / name
    try:
        if path.is_symlink() or not path.is_file():
            return _Projection(None, None, f"the projection file {name} is not there")
        if path.stat().st_size > MAX_RECORD_BYTES:
            problem = f"the projection file {name} is over {MAX_RECORD_BYTES} bytes"
            return _Projection(None, None, problem)
        data = path.read_bytes()
    except OSError as exc:
        return _Projection(None, None, f"the projection file {name} cannot be read: {exc.strerror}")
    try:
        told = parse_projection(json.loads(data))
    except (ValueError, RecordError) as exc:
        return _Projection(data, None, f"the projection file {name} is not one this reads: {exc}")
    return _Projection(data, told, None)


def _by_id(root: ElementTree.Element, wanted: str) -> ElementTree.Element | None:
    return next((e for e in root.iter(f"{SVG}g") if e.get("id") == wanted), None)


def _text(root: ElementTree.Element, attribute: str, wanted: str) -> str | None:
    found = next((e for e in root.iter(f"{SVG}text") if e.get(attribute) == wanted), None)
    return None if found is None else "".join(found.itertext())


# --- the checks -------------------------------------------------------------------------------


def check_part(record: DrawingRecord, part: PartRecord) -> Finding:
    """Whether the drawing was made from the part as its record now stands."""
    if record.part != part.part:
        return Finding(
            "part",
            "fails",
            f"the drawing is of part {record.part}, and the part's record is of {part.part}",
        )
    if record.geometry_hash != part.geometry_hash:
        return Finding(
            "part",
            "stale",
            f"STALE: the part has changed since this drawing was made. The drawing was made from "
            f"{record.geometry_hash}; the part's record now holds {part.geometry_hash}. Make the "
            "drawing again from the part: a drawing is never patched",
        )
    # Only with the hash agreeing: a part that changed has a new STEP file too, and is stale.
    try:
        step = part.step()
    except RecordError as exc:
        return Finding("part", "fails", str(exc))
    drawn = record.drawn_from
    if drawn != step:
        return Finding(
            "part",
            "fails",
            f"the drawing was drawn from {drawn.file} ({drawn.size.value} bytes, sha256 "
            f"{drawn.sha256}), and the part's record names {step.file} ({step.size.value} bytes, "
            f"sha256 {step.sha256}). Make the drawing again from the part",
        )
    return Finding(
        "part",
        "passes",
        f"made from the part as its record now stands: {part.geometry_hash}, from {step.file}",
    )


def _digest(named: FileEntry, data: bytes) -> str | None:
    found = hashlib.sha256(data).hexdigest()
    if found == named.sha256 and len(data) == named.size.value:
        return None
    return (
        f"{named.file} is not the file the record names: it holds {len(data)} bytes with "
        f"sha256 {found}, and the record names {named.size.value} bytes with {named.sha256}"
    )


def _sheet(record: DrawingRecord, root: ElementTree.Element) -> str | None:
    sheet = record.sheet
    wanted = (f"{sheet.width.value:g}mm", f"{sheet.height.value:g}mm")
    found = (root.get("width"), root.get("height"))
    if found == wanted:
        return None
    return (
        f"the record's sheet is {wanted[0]} by {wanted[1]}, and the SVG's is "
        f"{found[0]} by {found[1]}"
    )


def _projection_agrees(record: DrawingRecord, told: Projection) -> list[str]:
    name = record.files.projection.file
    problems: list[str] = []
    if told.geometry_hash != record.geometry_hash:
        problems.append(f"{name} is a projection of {told.geometry_hash}, not of the record's hash")
    if told.libraries != record.libraries:
        found = ", ".join(f"{k} {v}" for k, v in sorted(told.libraries.items()))
        problems.append(f"{name} was made with {found}, not with the record's libraries")
    for view in record.views:
        lines = told.views.get(view.name)
        counts = (None, None) if lines is None else (len(lines.visible), len(lines.hidden))
        if counts != (view.visible_paths.value, view.hidden_paths.value):
            problems.append(
                f"{name} holds {counts[0]} visible and {counts[1]} hidden lines in the "
                f"{view.name} view, and the record says {view.visible_paths.value} and "
                f"{view.hidden_paths.value}"
            )
    return problems


def check_file(record: DrawingRecord, svg: _Svg, projection: _Projection) -> Finding:
    """Whether the SVG and the projection beside the record are the files the record names."""
    problems: list[str] = []
    if svg.data is None:
        problems.append(svg.problem or "the drawing file cannot be read")
    else:
        problems += [p for p in (_digest(record.files.svg, svg.data),) if p]
        if svg.root is not None:
            problems += [p for p in (_sheet(record, svg.root),) if p]
    if projection.data is None:
        problems.append(projection.problem or "the projection file cannot be read")
    else:
        problems += [p for p in (_digest(record.files.projection, projection.data),) if p]
        if projection.told is None:
            problems.append(projection.problem or "the projection file cannot be read")
        else:
            problems += _projection_agrees(record, projection.told)
    if problems:
        return Finding("file", "fails", "; ".join(problems))
    return Finding(
        "file",
        "passes",
        f"{record.files.svg.file} and {record.files.projection.file} are the files the record "
        "names, by sha256; the projection is of the record's hash, libraries and lines",
    )


def _points(d: str) -> int:
    return len(_STEP.findall(d))


def check_views(record: DrawingRecord, svg: _Svg) -> Finding:
    """Whether every view is in the SVG with drawn lines, as many as the record says."""
    if svg.root is None:
        return Finding("views", "fails", svg.problem or "the drawing file cannot be read")
    listed = tuple(view.name for view in record.views)
    problems: list[str] = []
    if listed != VIEWS:
        problems.append(f"the record lists the views {', '.join(listed) or 'none'}")
    for view in record.views:
        toward, up = VIEW_DIRECTIONS[view.name]
        wanted = (tuple(float(c) for c in toward), tuple(float(c) for c in up))
        if (view.viewed_from.value, view.up.value) != wanted:
            problems.append(
                f"the record has the {view.name} view seen from {view.viewed_from.value} with "
                f"{view.up.value} up, and this version draws it from {wanted[0]} with "
                f"{wanted[1]} up"
            )
    for name in VIEWS:
        group = _by_id(svg.root, f"view-{name}")
        if group is None:
            problems.append(f"no {name} view")
            continue
        drawn = {
            kind: [p for p in group.iter(f"{SVG}path") if p.get("class") == kind]
            for kind in ("visible", "hidden")
        }
        lines = [p for kind in drawn.values() for p in kind if _points(p.get("d", "")) >= 2]  # noqa: PLR2004
        if not lines:
            problems.append(f"the {name} view draws no line")
            continue
        view = next((v for v in record.views if v.name == name), None)
        if view is not None and (
            len(drawn["visible"]) != view.visible_paths.value
            or len(drawn["hidden"]) != view.hidden_paths.value
        ):
            problems.append(
                f"the {name} view draws {len(drawn['visible'])} visible and "
                f"{len(drawn['hidden'])} hidden lines, and the record says "
                f"{view.visible_paths.value} and {view.hidden_paths.value}"
            )
    if problems:
        return Finding("views", "fails", "; ".join(problems))
    return Finding("views", "passes", f"{', '.join(VIEWS)}: each draws its lines")


def check_title_block(record: DrawingRecord) -> list[str]:
    """What in the record's own title block does not agree with the rest of the record."""
    fields = record.title_block
    own = {
        "part": record.part,
        "units": record.units,
        "scale": record.scale.shown_as,
        "geometry_hash": record.geometry_hash,
        "drawn_from": record.drawn_from.file,
        "projection": record.projection_method,
        "generator": f"{record.generator.name} {record.generator.version}",
    }
    problems = [
        f"the record's {name.replace('_', ' ')} is {value}, and its title block shows "
        f"{fields.get(name)}"
        for name, value in own.items()
        if fields.get(name) != value
    ]
    ratio = _RATIO.fullmatch(record.scale.shown_as)
    if ratio is None or int(ratio[1]) / int(ratio[2]) != record.scale.value:
        problems.append(
            f"the record's scale is {record.scale.value}, and it is written {record.scale.shown_as}"
        )
    return problems


def check_title(record: DrawingRecord, svg: _Svg) -> Finding:
    """Whether every title block field is in the SVG, as the record gives it."""
    if svg.root is None:
        return Finding("title block", "fails", svg.problem or "the drawing file cannot be read")
    block = _by_id(svg.root, "title-block")
    if block is None:
        return Finding("title block", "fails", "the drawing has no title block")
    problems: list[str] = []
    for name in TITLE_FIELDS:
        shown = _text(block, "data-field", name)
        given = record.title_block.get(name)
        if shown is None or not shown.strip():
            problems.append(f"no {name.replace('_', ' ')} in the title block")
        elif given is None:
            problems.append(f"the record gives no {name.replace('_', ' ')}")
        elif shown != given:
            problems.append(f"the title block shows {name.replace('_', ' ')} {shown}, not {given}")
    problems += check_title_block(record)
    if problems:
        return Finding("title block", "fails", "; ".join(problems))
    return Finding("title block", "passes", f"{', '.join(TITLE_FIELDS)}: each shown as recorded")


def check_dimensions(record: DrawingRecord, part: PartRecord, svg: _Svg) -> Finding:
    """Whether each overall dimension is the part's bounding box as the drawing's rule writes it."""
    if svg.root is None:
        return Finding("dimensions", "fails", svg.problem or "the drawing file cannot be read")
    box = part.values.bounding_box.extents_mm()
    problems: list[str] = []
    said: list[str] = []
    stated = (record.shown_to.value, record.rounding, record.agreement_within.value)
    if stated != (SHOWN_TO_MM, ROUNDING, AGREEMENT_MM):
        problems.append(
            f"the record states another rule (shown to {stated[0]} mm, rounded {stated[1]}, "
            f"within {stated[2]} mm), and this version's is: {RULE}"
        )
    for name in OVERALL:
        actual = box[name]
        written = shown_dimension(actual)
        recorded = record.overall.get(name)
        text = _text(svg.root, "data-quantity", name)
        if recorded is None:
            problems.append(f"the record gives no {name}")
        elif recorded.value != float(written):
            problems.append(
                f"the record's {name} is {recorded.value} mm; the part's is {actual!r} mm, which "
                f"is written {written}"
            )
        # Read only as the writer writes it: digits, a point and one decimal. Anything else
        # (a sign, an exponent, "nan") is no dimension.
        if text is None or not _SHOWN.fullmatch(text):
            problems.append(f"the drawing shows no {name}")
        elif text != written:
            problems.append(
                f"the drawing shows {name} {text} mm; the part's is {actual!r} mm, which is "
                f"written {written}"
            )
        said.append(f"{name} {text} mm (part {actual!r} mm)")
    if problems:
        return Finding("dimensions", "fails", "; ".join(problems))
    return Finding(
        "dimensions",
        "passes",
        f"each the part's bounding box rounded {ROUNDING} to {SHOWN_TO_MM:g} mm: {', '.join(said)}",
    )


def check_drawing(drawing: Path, part_record: Path) -> tuple[Finding, ...]:
    """Every check of the drawing whose record is at ``drawing``, against the part's record.

    Raises:
        RecordError: either record cannot be read as a drawing's or a part's.
    """
    record = load_drawing(drawing)
    part = load_part(part_record)
    svg = _read_svg(record, drawing)
    projection = _read_projection(record, drawing)
    return (
        check_part(record, part),
        check_file(record, svg, projection),
        check_views(record, svg),
        check_title(record, svg),
        check_dimensions(record, part, svg),
    )


def exit_status(findings: tuple[Finding, ...]) -> int:
    """0 every check passes, 3 the drawing is stale, 1 it is not stale and a check fails.

    A stale drawing is made again whatever else its checks found, so staleness is the answer
    first: the other lines still say what no longer agrees.
    """
    verdicts = {finding.verdict for finding in findings}
    if "stale" in verdicts:
        return EXIT_STALE
    if "fails" in verdicts:
        return EXIT_FAILS
    return EXIT_PASSES
