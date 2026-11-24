"""A drawing is composed from the kernel's projection into the same bytes every time.

Composition is code over numbers: the committed projection of the chassis plate (as the kernel
gave it on a provisioned tool environment) composes into exactly the committed SVG and records,
here, with no kernel. The record keeps every number as a value with its unit and holds no time
and no path of the machine it was made on. A projection of another shape is refused, and the
scale is the largest at which the views fit one sheet.
"""

from __future__ import annotations

import json
import re
from typing import Any

import pytest
from drawing_helpers import FIXTURE

from physgate.build.drawings.record import (
    PartRecord,
    Projection,
    RecordError,
    load_part,
    parse_projection,
    render,
)
from physgate.build.drawings.sheet import Composed, compose


def _projection(scale: float = 1.0, **changed: Any) -> Projection:  # noqa: ANN401
    data = json.loads((FIXTURE / "plate.projection.json").read_text(encoding="utf-8"))
    if scale != 1.0:
        for view in data["views"].values():
            for kind in ("visible", "hidden"):
                view[kind] = [[[x * scale, y * scale] for x, y in line] for line in view[kind]]
        data["box_mm"] = [c * scale for c in data["box_mm"]]
    data.update(changed)
    return parse_projection(data)


def _part() -> PartRecord:
    return load_part(FIXTURE / "plate.result.json")


def _compose(projection: Projection | None = None) -> Composed:
    part = _part()
    return compose(projection or _projection(), part, part.step())


def test_the_committed_projection_composes_into_the_committed_drawing_byte_for_byte() -> None:
    made = _compose()
    assert made.svg.encode() == (FIXTURE / "plate.svg").read_bytes()
    assert made.projection.encode() == (FIXTURE / "plate.projection.json").read_bytes()
    assert render(made.record).encode() == (FIXTURE / "plate.drawing.json").read_bytes()


def test_composing_twice_gives_the_same_bytes() -> None:
    one, two = _compose(), _compose()
    assert (one.svg, one.projection, render(one.record)) == (
        two.svg,
        two.projection,
        render(two.record),
    )


def test_a_projection_of_another_shape_is_refused() -> None:
    other = _projection(geometry_hash="sha256:" + "1" * 64)
    with pytest.raises(RecordError, match="not the part's shape"):
        _compose(other)


def _loose_numbers(found: object, inside: bool = False) -> list[object]:
    if isinstance(found, dict):
        has_unit = "unit" in found
        return [n for k, v in found.items() for n in _loose_numbers(v, has_unit and k == "value")]
    if isinstance(found, list):
        return [n for v in found for n in _loose_numbers(v, inside)]
    if isinstance(found, bool) or not isinstance(found, (int, float)):
        return []
    return [] if inside else [found]


def test_the_record_holds_every_number_with_its_unit_and_no_time_or_path() -> None:
    text = (FIXTURE / "plate.drawing.json").read_text(encoding="utf-8")
    record = json.loads(text)
    assert record["schema"] == 1
    rest = {name: value for name, value in record.items() if name != "schema"}
    assert _loose_numbers(rest) == []
    assert not re.search(r"\d{4}-\d{2}-\d{2}|\d{2}:\d{2}:\d{2}", text)
    assert "/Users/" not in text and "/home/" not in text and "/tmp" not in text
    assert record["drawn_from"]["file"] == "exports/plate.step"
    assert "fit to manufacture" in record["left_out"]


def test_the_plate_at_half_its_size_is_drawn_at_two_to_one() -> None:
    assert _compose().record.scale.shown_as == "1:1"
    assert _compose(_projection(0.5)).record.scale.shown_as == "2:1"


def test_a_part_too_large_for_one_sheet_at_one_to_ten_is_refused() -> None:
    with pytest.raises(RecordError, match="does not fit one A3 sheet"):
        _compose(_projection(100.0))


def test_the_overall_dimensions_are_the_kernel_s_box_shown_to_a_tenth() -> None:
    overall = _compose().record.overall
    assert {name: m.value for name, m in overall.items()} == {
        "length_x": 110.0,
        "width_y": 60.0,
        "height_z": 3.0,
    }
    assert {m.unit for m in overall.values()} == {"mm"}


def test_the_svg_keeps_the_title_block_and_the_dimensions_as_plain_text() -> None:
    svg = _compose().svg
    assert '<text class="field" data-field="geometry_hash"' in svg
    assert re.search(r'data-quantity="length_x"[^>]*>110\.0</text>', svg)
    assert "<!DOCTYPE" not in svg
    for name in ("front", "top", "side", "isometric"):
        assert f'<g id="view-{name}" class="view">' in svg
