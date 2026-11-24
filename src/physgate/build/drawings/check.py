"""The drawing checker: rules over the drawing's files and the part's record, and no kernel.

It reads three files and runs nothing: the drawing's record, the SVG it names beside it, and the
part's record (``<part>.result.json``), which is the part's current state for every check. Each
check is judged on its own, whatever another found, so a drawing doctored in one way fails in
that one line:

1. **part**: the hash the drawing was made from is the part's current ``geometry_hash``. If it
   is not, the drawing is **stale**: the part changed after it was made, and a drawing is made
   again from the part, never patched (ARCH-111).
2. **file**: the SVG beside the record is the one the record names, by size and sha256.
3. **views**: the SVG holds the front, top, side and isometric views, each with at least one
   drawn line of two points or more, and as many lines of each kind as the record says.
4. **title block**: every field of the title block is in the SVG, with the text the record
   gives it, and the record's part, units, scale and hash are the ones its fields show.
5. **dimensions**: each overall dimension, as the record gives it and as the SVG shows it, is
   within :data:`AGREEMENT_MM` of the part's bounding box as the part's record holds it: half
   of the 0.1 mm a dimension is shown to.

The verdict of a check is ``passes``, ``fails``, or for the first only, ``stale``.
"""

from __future__ import annotations

import hashlib
import re
from dataclasses import dataclass
from typing import TYPE_CHECKING, Literal
from xml.etree import ElementTree

from physgate.build.drawings.record import (
    OVERALL,
    TITLE_FIELDS,
    VIEWS,
    load_drawing,
    load_part,
)
from physgate.build.drawings.sheet import AGREEMENT_MM

if TYPE_CHECKING:
    from pathlib import Path

    from physgate.build.drawings.record import DrawingRecord, PartRecord

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
#: Room for a sum of two numbers each written to three decimals to differ in its last bit.
_EPSILON = 1e-9


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
    if record.geometry_hash == part.geometry_hash:
        return Finding(
            "part",
            "passes",
            f"made from the part as its record now stands: {part.geometry_hash}",
        )
    return Finding(
        "part",
        "stale",
        f"STALE: the part has changed since this drawing was made. The drawing was made from "
        f"{record.geometry_hash}; the part's record now holds {part.geometry_hash}. Make the "
        "drawing again from the part: a drawing is never patched",
    )


def check_file(record: DrawingRecord, svg: _Svg) -> Finding:
    """Whether the SVG beside the record is the file the record names."""
    named = record.files.svg
    if svg.data is None:
        return Finding("file", "fails", svg.problem or "the drawing file cannot be read")
    found = hashlib.sha256(svg.data).hexdigest()
    if found != named.sha256 or len(svg.data) != named.size.value:
        return Finding(
            "file",
            "fails",
            f"{named.file} is not the file the record names: it holds {len(svg.data)} bytes with "
            f"sha256 {found}, and the record names {named.size.value} bytes with {named.sha256}",
        )
    return Finding("file", "passes", f"{named.file} is the file the record names, by sha256")


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
    }
    return [
        f"the record's {name.replace('_', ' ')} is {value}, and its title block shows "
        f"{fields.get(name)}"
        for name, value in own.items()
        if fields.get(name) != value
    ]


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
    """Whether each overall dimension agrees with the part's bounding box, recorded and shown."""
    if svg.root is None:
        return Finding("dimensions", "fails", svg.problem or "the drawing file cannot be read")
    box = part.values.bounding_box.extents_mm()
    problems: list[str] = []
    said: list[str] = []
    for name in OVERALL:
        actual = box[name]
        recorded = record.overall.get(name)
        text = _text(svg.root, "data-quantity", name)
        if recorded is None:
            problems.append(f"the record gives no {name}")
        elif abs(recorded.value - actual) > AGREEMENT_MM + _EPSILON:
            problems.append(f"the record's {name} is {recorded.value} mm, the part's {actual:.3f}")
        try:
            shown = None if text is None else float(text)
        except ValueError:
            shown = None
        if shown is None:
            problems.append(f"the drawing shows no {name}")
        elif abs(shown - actual) > AGREEMENT_MM + _EPSILON:
            problems.append(f"the drawing shows {name} {text} mm, the part's is {actual:.3f}")
        said.append(f"{name} {text} mm (part {actual:.3f})")
    if problems:
        return Finding("dimensions", "fails", "; ".join(problems))
    return Finding(
        "dimensions",
        "passes",
        f"within {AGREEMENT_MM} mm of the part's bounding box: {', '.join(said)}",
    )


def check_drawing(drawing: Path, part_record: Path) -> tuple[Finding, ...]:
    """Every check of the drawing whose record is at ``drawing``, against the part's record.

    Raises:
        RecordError: either record cannot be read as a drawing's or a part's.
    """
    record = load_drawing(drawing)
    part = load_part(part_record)
    svg = _read_svg(record, drawing)
    return (
        check_part(record, part),
        check_file(record, svg),
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
