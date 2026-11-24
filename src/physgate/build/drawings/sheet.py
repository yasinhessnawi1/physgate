"""One drawing composed from the kernel's projection: the SVG and the record written beside it.

Composition is plain code over the projection's numbers; no kernel is needed and nothing is
measured here. The kernel drew the views; this file places them on one A3 sheet and writes the
text a drawing carries:

- **the views**, in first-angle arrangement: the front at the top left, the view from above
  below it, the view from the left to its right, and the isometric view below that. Each view is
  a group ``view-<name>`` of paths, visible edges solid and hidden ones dashed.
- **one scale** for every view, the largest of :data:`SCALES` at which the views and their
  dimensions fit above the title block. The isometric view is the kernel's orthographic
  projection, so its lengths are foreshortened: it is for seeing the part, not for measuring.
- **the overall dimensions**: the part's length along x and height along z on the front view,
  its width along y on the view from above, each the kernel's bounding box shown to
  :data:`SHOWN_TO_MM`, as plain text marked with the quantity it is.
- **the title block**, as plain text, one field per line marked with its name: the part, the
  units, the scale, the geometry hash, the file drawn from, the projection method and the
  generator, and a note that the drawing is shown, not measured, and not for manufacture.

Text is SVG ``<text>``, never shapes the kernel made from a font: a font's outlines differ
between machines, and the checker reads the text itself. Every number is written with three
decimals and a negative zero as zero, so the same projection composes to the same bytes.
"""

from __future__ import annotations

from dataclasses import dataclass
from xml.sax.saxutils import escape, quoteattr

from physgate.build.drawings.record import (
    GENERATOR,
    GENERATOR_VERSION,
    OVERALL,
    SCHEMA,
    TITLE_FIELDS,
    VIEW_DIRECTIONS,
    VIEWS,
    Direction,
    DrawingFiles,
    DrawingRecord,
    FileEntry,
    Generator,
    Millimetres,
    PartRecord,
    Projection,
    Ratio,
    RecordError,
    Scale,
    Sheet,
    View,
    ViewLines,
    ViewName,
    entry_of,
    render,
)

SHOWN = (
    "shown, not measured: one drawing composed from the CAD kernel's own projection of one part, "
    "checked by rules; not a drawing anyone has made a part from"
)
LEFT_OUT = (
    "not in this drawing: STEP AP242 with product manufacturing information, ISO 286 fits, "
    "geometric tolerances and datums, the assembly manual, a PDF, and a person's sign-off; "
    "nothing here claims the drawing is fit to manufacture from"
)
NOTE = "Shown, not measured. Not for manufacture: no tolerances, fits, datums or PMI."

#: The sheet: ISO A3 landscape, in millimetres.
SHEET_SIZE, SHEET_W, SHEET_H = "A3 landscape", 420.0, 297.0
BORDER = 10.0
#: From the border to the first view: room for the dimensions on the views' left.
MARGIN = 25.0
#: Between two views: room for a dimension and a view's label.
GAP = 30.0
TITLE_W, TITLE_H = 180.0, 44.0
#: The scales tried, largest first, as a drawing writes each.
SCALES: tuple[tuple[float, str], ...] = (
    (5.0, "5:1"),
    (2.0, "2:1"),
    (1.0, "1:1"),
    (0.5, "1:2"),
    (0.2, "1:5"),
    (0.1, "1:10"),
)
#: What an overall dimension is shown to, and the most a shown one may differ from the part's
#: bounding box: half of the last digit shown.
SHOWN_TO_MM = 0.1
AGREEMENT_MM = 0.05
PROJECTION_METHOD = "first angle"
#: Where each view sits on the sheet: its column and its row.
PLACES = {"front": (0, 0), "side": (1, 0), "top": (0, 1), "isometric": (1, 1)}
LABELS = {
    "front": "FRONT",
    "top": "TOP",
    "side": "SIDE (FROM THE LEFT)",
    "isometric": "ISOMETRIC (NOT FOR MEASURING)",
}

STYLE = (
    ".border{fill:none;stroke:#000;stroke-width:0.7}"
    ".visible{fill:none;stroke:#000;stroke-width:0.5;stroke-linecap:round}"
    ".hidden{fill:none;stroke:#000;stroke-width:0.25;stroke-dasharray:2 1}"
    ".dimension-line{fill:none;stroke:#000;stroke-width:0.18}"
    ".arrow{fill:#000;stroke:none}"
    "text{font-family:monospace;fill:#000}"
    ".label{font-size:2.5px}.view-label{font-size:3px}"
    ".dimension{font-size:3.5px}.field{font-size:2.5px}.note{font-size:2.2px}"
)


def number(value: float) -> str:
    """``value`` with three decimals, a negative zero written as zero."""
    text = f"{value:.3f}"
    return "0.000" if text == "-0.000" else text


@dataclass(frozen=True)
class _Extent:
    low_x: float
    high_x: float
    low_y: float
    high_y: float

    @property
    def width(self) -> float:
        return self.high_x - self.low_x

    @property
    def height(self) -> float:
        return self.high_y - self.low_y


def _extent(lines: ViewLines) -> _Extent:
    points = [point for line in (*lines.visible, *lines.hidden) for point in line]
    if not points:
        msg = "a view the kernel projected holds no line"
        raise RecordError(msg)
    xs, ys = [p[0] for p in points], [p[1] for p in points]
    return _Extent(min(xs), max(xs), min(ys), max(ys))


@dataclass(frozen=True)
class _Layout:
    scale: float
    shown_as: str
    #: Each view's top left corner on the sheet.
    corners: dict[str, tuple[float, float]]


def _layout(extents: dict[str, _Extent]) -> _Layout:
    """The largest scale at which every view fits above the title block, and where each sits."""
    left, top = BORDER + MARGIN, BORDER + MARGIN
    right_limit = SHEET_W - BORDER - 5.0
    bottom_limit = SHEET_H - BORDER - TITLE_H - 5.0
    for scale, shown_as in SCALES:
        column = max(extents["front"].width, extents["top"].width) * scale
        row = max(extents["front"].height, extents["side"].height) * scale
        second_x, second_y = left + column + GAP, top + row + GAP
        right = second_x + max(extents["side"].width, extents["isometric"].width) * scale
        bottom = second_y + max(extents["top"].height, extents["isometric"].height) * scale
        if right <= right_limit and bottom <= bottom_limit:
            xs, ys = (left, second_x), (top, second_y)
            corners = {name: (xs[c], ys[r]) for name, (c, r) in PLACES.items()}
            return _Layout(scale, shown_as, corners)
    msg = "the part does not fit one A3 sheet at 1:10, the smallest scale here"
    raise RecordError(msg)


def _path(points: tuple[tuple[float, float], ...], at: tuple[float, float], extent: _Extent,
          scale: float, kind: str) -> str:  # fmt: skip
    x0, y0 = at
    moves = [
        f"{'M' if i == 0 else 'L'}{number(x0 + (x - extent.low_x) * scale)} "
        f"{number(y0 + (extent.high_y - y) * scale)}"
        for i, (x, y) in enumerate(points)
    ]
    return f'<path class="{kind}" d="{" ".join(moves)}"/>'


def _view(name: str, lines: ViewLines, at: tuple[float, float], extent: _Extent,
          scale: float) -> list[str]:  # fmt: skip
    out = [f'<g id="view-{name}" class="view">']
    out.append(
        f'<text class="view-label" x="{number(at[0])}" y="{number(at[1] - 5.0)}">'
        f"{escape(LABELS[name])}</text>"
    )
    out += [_path(line, at, extent, scale, "visible") for line in lines.visible]
    out += [_path(line, at, extent, scale, "hidden") for line in lines.hidden]
    out.append("</g>")
    return out


ARROW, ARROW_HALF = 2.5, 0.8


def _arrow(tip: tuple[float, float], along: tuple[float, float]) -> str:
    """A filled arrowhead with its tip at ``tip``, pointing along the unit vector ``along``."""
    (x, y), (dx, dy) = tip, along
    bx, by = x - dx * ARROW, y - dy * ARROW
    px, py = -dy * ARROW_HALF, dx * ARROW_HALF
    return (
        f'<path class="arrow" d="M{number(x)} {number(y)} L{number(bx + px)} {number(by + py)} '
        f'L{number(bx - px)} {number(by - py)} Z"/>'
    )


def _dimension(quantity: str, shown: float, start: tuple[float, float], end: tuple[float, float],
               *, vertical: bool) -> list[str]:  # fmt: skip
    """A dimension line from ``start`` to ``end`` with its arrows and its text."""
    (x1, y1), (x2, y2) = start, end
    span = abs(x2 - x1) if not vertical else abs(y2 - y1)
    ux, uy = (0.0, 1.0) if vertical else (1.0, 0.0)
    # A span too short for two arrows inside it gets them outside, pointing in.
    inside = span >= 3 * ARROW
    out = [
        f'<path class="dimension-line" d="M{number(x1)} {number(y1)} L{number(x2)} {number(y2)}"/>'
    ]
    if inside:
        out += [_arrow((x1, y1), (-ux, -uy)), _arrow((x2, y2), (ux, uy))]
    else:
        out += [_arrow((x1, y1), (ux, uy)), _arrow((x2, y2), (-ux, -uy))]
    text = f"{shown:.1f}"
    marked = f'class="dimension" data-quantity="{quantity}"'
    if vertical:
        tx, ty = x1 - 1.5, (y1 + y2) / 2
        out.append(
            f'<text {marked} x="{number(tx)}" y="{number(ty)}" text-anchor="middle" '
            f'transform="rotate(-90 {number(tx)} {number(ty)})">{text}</text>'
        )
    else:
        tx, ty = (x1 + x2) / 2, y1 - 1.5
        out.append(
            f'<text {marked} x="{number(tx)}" y="{number(ty)}" text-anchor="middle">{text}</text>'
        )
    return out


def _dimensions(layout: _Layout, extents: dict[str, _Extent],
                shown: dict[str, float]) -> list[str]:  # fmt: skip
    s = layout.scale
    fx, fy = layout.corners["front"]
    front = extents["front"]
    tx, ty = layout.corners["top"]
    top = extents["top"]
    below = fy + front.height * s + 10.0
    out = ['<g id="dimensions">']
    out += _dimension("length_x", shown["length_x"], (fx, below), (fx + front.width * s, below),
                      vertical=False)  # fmt: skip
    out += _dimension("height_z", shown["height_z"], (fx - 10.0, fy),
                      (fx - 10.0, fy + front.height * s), vertical=True)  # fmt: skip
    out += _dimension("width_y", shown["width_y"], (tx - 10.0, ty),
                      (tx - 10.0, ty + top.height * s), vertical=True)  # fmt: skip
    out.append("</g>")
    return out


def _title_block(fields: dict[str, str]) -> list[str]:
    x0, y0 = SHEET_W - BORDER - TITLE_W, SHEET_H - BORDER - TITLE_H
    out = [
        '<g id="title-block">',
        f'<rect class="border" x="{number(x0)}" y="{number(y0)}" width="{number(TITLE_W)}" '
        f'height="{number(TITLE_H)}"/>',
    ]
    for i, name in enumerate(TITLE_FIELDS):
        y = y0 + 5.0 + i * 5.0
        out.append(
            f'<text class="label" x="{number(x0 + 2.0)}" y="{number(y)}">'
            f"{escape(name.replace('_', ' '))}</text>"
        )
        out.append(
            f'<text class="field" data-field={quoteattr(name)} x="{number(x0 + 30.0)}" '
            f'y="{number(y)}">{escape(fields[name])}</text>'
        )
    out.append(
        f'<text class="note" x="{number(x0 + 2.0)}" y="{number(y0 + TITLE_H - 2.5)}">'
        f"{escape(NOTE)}</text>"
    )
    out.append("</g>")
    return out


@dataclass(frozen=True)
class Composed:
    """A drawing as it is written: its SVG, its projection's text and its record."""

    svg: str
    projection: str
    record: DrawingRecord


def compose(projection: Projection, part: PartRecord, drawn_from: FileEntry) -> Composed:
    """The drawing of ``part`` from the kernel's ``projection`` of the STEP file ``drawn_from``.

    Raises:
        RecordError: the projection is not of the part's recorded shape, a view holds no line,
            or the part does not fit one sheet.
    """
    if projection.geometry_hash != part.geometry_hash:
        msg = (
            f"the STEP file read back hashes to {projection.geometry_hash}, not to the "
            f"{part.geometry_hash} the part's record holds: it is not the part's shape"
        )
        raise RecordError(msg)
    extents: dict[str, _Extent] = {name: _extent(projection.views[name]) for name in VIEWS}
    layout = _layout(extents)
    box = projection.box_mm
    shown: dict[str, float] = {
        name: round(box[i + 3] - box[i], 1) for i, name in enumerate(OVERALL)
    }
    fields = {
        "part": part.part,
        "units": "mm",
        "scale": layout.shown_as,
        "geometry_hash": part.geometry_hash,
        "drawn_from": drawn_from.file,
        "projection": PROJECTION_METHOD,
        "generator": f"{GENERATOR} {GENERATOR_VERSION}",
    }
    body = [
        '<?xml version="1.0" encoding="UTF-8"?>',
        f'<svg xmlns="http://www.w3.org/2000/svg" width="{SHEET_W:g}mm" height="{SHEET_H:g}mm" '
        f'viewBox="0 0 {SHEET_W:g} {SHEET_H:g}">',
        f"<title>{escape(part.part)}: drawing</title>",
        f"<style>{STYLE}</style>",
        f'<rect class="border" x="{number(BORDER)}" y="{number(BORDER)}" '
        f'width="{number(SHEET_W - 2 * BORDER)}" height="{number(SHEET_H - 2 * BORDER)}"/>',
    ]
    for name in VIEWS:
        body += _view(name, projection.views[name], layout.corners[name], extents[name],
                      layout.scale)  # fmt: skip
    body += _dimensions(layout, extents, shown)
    body += _title_block(fields)
    body.append("</svg>")
    svg = "\n".join(body) + "\n"
    projection_text = render(projection)
    stem = part.part
    record = DrawingRecord.model_validate(
        {
            "schema": SCHEMA,
            "kind": "drawing",
            "shown": SHOWN,
            "left_out": LEFT_OUT,
            "part": stem,
            "geometry_hash": part.geometry_hash,
            "drawn_from": drawn_from,
            "files": DrawingFiles(
                svg=entry_of(svg.encode("utf-8"), f"{stem}.svg"),
                projection=entry_of(projection_text.encode("utf-8"), f"{stem}.projection.json"),
            ),
            "sheet": Sheet(
                size=SHEET_SIZE,
                width=Millimetres(value=SHEET_W, unit="mm"),
                height=Millimetres(value=SHEET_H, unit="mm"),
            ),
            "scale": Scale(value=layout.scale, unit="1", shown_as=layout.shown_as),
            "units": "mm",
            "projection_method": PROJECTION_METHOD,
            "views": tuple(_view_record(name, projection.views[name]) for name in VIEWS),
            "overall": {q: Millimetres(value=v, unit="mm") for q, v in shown.items()},
            "shown_to": Millimetres(value=SHOWN_TO_MM, unit="mm"),
            "agreement_within": Millimetres(value=AGREEMENT_MM, unit="mm"),
            "title_block": fields,
            "generator": Generator(name=GENERATOR, version=GENERATOR_VERSION),
            "libraries": dict(projection.libraries),
        }
    )
    return Composed(svg=svg, projection=projection_text, record=record)


def _view_record(name: ViewName, lines: ViewLines) -> View:
    toward, up = VIEW_DIRECTIONS[name]
    return View.model_validate(
        {
            "name": name,
            "viewed_from": Direction(value=tuple(float(c) for c in toward), unit="1"),  # type: ignore[arg-type]
            "up": Direction(value=tuple(float(c) for c in up), unit="1"),  # type: ignore[arg-type]
            "visible_paths": Ratio(value=len(lines.visible), unit="1"),
            "hidden_paths": Ratio(value=len(lines.hidden), unit="1"),
        }
    )
