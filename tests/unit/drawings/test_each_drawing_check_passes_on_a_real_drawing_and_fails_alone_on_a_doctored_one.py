"""Each check of a drawing passes on a real one and fails on its own when the drawing is doctored.

The drawing is the chassis plate's, made by the kernel on a provisioned tool environment and
committed beside these rows. Each row changes one thing (the part's record, the SVG, or the
drawing's record) and reads the verdicts: the check that owns the change fails, and only it,
since every check is judged whatever another found. When the SVG is changed, the record is made
to name the changed file unless the row is about the file itself, so the file check stays out of
the way of the check under test.
"""

from __future__ import annotations

import hashlib
import json
import re
from collections.abc import Callable
from pathlib import Path
from typing import Any

import pytest
from drawing_helpers import FIXTURE, PLATE_HASH, Copy, all_pass_but

from physgate.build.drawings.check import EXIT_FAILS, EXIT_PASSES, EXIT_STALE, exit_status
from physgate.build.drawings.record import DrawingRecord, RecordError

OTHER_HASH = "sha256:" + "0" * 64


@pytest.fixture
def copy(tmp_path: Path) -> Copy:
    return Copy(tmp_path / "drawing")


def _drop_group(svg: str, group: str) -> str:
    return re.sub(rf'<g id="{group}"[^>]*>.*?</g>\n', "", svg, count=1, flags=re.S)


def _in_group(svg: str, group: str, edit: Callable[[str], str]) -> str:
    start = svg.index(f'<g id="{group}"')
    end = svg.index("</g>", start)
    return svg[:start] + edit(svg[start:end]) + svg[end:]


# --- the real drawing -------------------------------------------------------------------------


def test_the_real_drawing_passes_every_check(copy: Copy) -> None:
    findings = copy.check()
    assert copy.verdicts() == all_pass_but()
    assert exit_status(findings) == EXIT_PASSES
    assert PLATE_HASH in copy.message("part")


# --- part -------------------------------------------------------------------------------------


def test_a_part_whose_hash_changed_makes_the_drawing_stale_and_nothing_else(copy: Copy) -> None:
    copy.part_record(lambda part: part.update(geometry_hash=OTHER_HASH))
    assert copy.verdicts() == all_pass_but(part="stale")
    said = copy.message("part")
    assert said.startswith("STALE") and PLATE_HASH in said and OTHER_HASH in said
    assert "never patched" in said
    assert exit_status(copy.check()) == EXIT_STALE


def test_a_stale_drawing_is_stale_first_whatever_else_fails(copy: Copy) -> None:
    copy.part_record(lambda part: part.update(geometry_hash=OTHER_HASH))
    copy.record(lambda r: r["overall"]["length_x"].update(value=120.0))
    assert copy.verdicts() == all_pass_but(part="stale", dimensions="fails")
    assert exit_status(copy.check()) == EXIT_STALE


def test_a_drawing_of_another_part_fails_the_part_check(copy: Copy) -> None:
    copy.part_record(lambda part: part.update(part="motor_mount"))
    assert copy.verdicts() == all_pass_but(part="fails")
    assert "motor_mount" in copy.message("part")
    assert exit_status(copy.check()) == EXIT_FAILS


# --- file -------------------------------------------------------------------------------------


def test_a_drawing_file_changed_after_it_was_made_fails_the_file_check(copy: Copy) -> None:
    copy.svg_text(lambda svg: svg + "<!-- changed by hand -->\n", restamp=False)
    assert copy.verdicts() == all_pass_but(file="fails")
    assert "is not the file the record names" in copy.message("file")


def test_a_drawing_file_changed_in_place_to_the_same_size_fails_the_file_check(
    copy: Copy,
) -> None:
    # One digit of one line moved: the same size, other bytes.
    size = copy.svg.stat().st_size
    copy.svg_text(lambda svg: svg.replace('d="M35.000', 'd="M36.000', 1), restamp=False)
    assert copy.svg.stat().st_size == size
    assert copy.verdicts() == all_pass_but(file="fails")


def test_a_drawing_file_that_is_a_link_is_not_read_even_to_the_right_bytes(
    copy: Copy, tmp_path: Path
) -> None:
    elsewhere = tmp_path / "elsewhere.svg"
    elsewhere.write_bytes(copy.svg.read_bytes())
    copy.svg.unlink()
    copy.svg.symlink_to(elsewhere)
    assert copy.verdicts() == all_pass_but(
        file="fails", views="fails", title_block="fails", dimensions="fails"
    )
    assert "is not there" in copy.message("file")


def test_a_missing_drawing_file_fails_every_check_of_the_drawing_but_not_the_part(
    copy: Copy,
) -> None:
    copy.svg.unlink()
    assert copy.verdicts() == all_pass_but(
        file="fails", views="fails", title_block="fails", dimensions="fails"
    )
    assert "is not there" in copy.message("views")


def test_a_drawing_that_declares_a_document_type_is_not_read(copy: Copy) -> None:
    doctype = '<!DOCTYPE svg [<!ENTITY part "plate">]>\n'
    copy.svg_text(lambda svg: svg.replace("<svg ", doctype + "<svg ", 1))
    assert copy.verdicts() == all_pass_but(views="fails", title_block="fails", dimensions="fails")
    assert "document type" in copy.message("title block")


# --- views ------------------------------------------------------------------------------------


def test_a_drawing_without_its_side_view_fails_the_views_check(copy: Copy) -> None:
    copy.svg_text(lambda svg: _drop_group(svg, "view-side"))
    assert copy.verdicts() == all_pass_but(views="fails")
    assert "no side view" in copy.message("views")


def test_a_view_whose_lines_are_single_points_draws_nothing(copy: Copy) -> None:
    def one_point_each(group: str) -> str:
        return re.sub(r'd="(M[-0-9.]+ [-0-9.]+)[^"]*"', r'd="\1"', group)

    copy.svg_text(lambda svg: _in_group(svg, "view-top", one_point_each))
    assert copy.verdicts() == all_pass_but(views="fails")
    assert "the top view draws no line" in copy.message("views")


def test_a_view_with_a_line_fewer_than_its_record_says_fails_the_views_check(copy: Copy) -> None:
    def drop_one_hidden(group: str) -> str:
        return re.sub(r'<path class="hidden" d="[^"]*"/>\n', "", group, count=1)

    copy.svg_text(lambda svg: _in_group(svg, "view-front", drop_one_hidden))
    assert copy.verdicts() == all_pass_but(views="fails")
    assert "the record says" in copy.message("views")


def test_a_view_with_a_visible_line_fewer_than_its_record_says_fails_the_views_check(
    copy: Copy,
) -> None:
    def drop_one_visible(group: str) -> str:
        return re.sub(r'<path class="visible" d="[^"]*"/>\n', "", group, count=1)

    copy.svg_text(lambda svg: _in_group(svg, "view-top", drop_one_visible))
    assert copy.verdicts() == all_pass_but(views="fails")
    assert "the top view draws" in copy.message("views")


def test_a_record_that_lists_three_views_fails_the_views_check(copy: Copy) -> None:
    copy.record(lambda r: r.update(views=r["views"][:3]))
    assert copy.verdicts() == all_pass_but(views="fails")


def test_a_record_that_lists_the_views_in_another_order_fails_the_views_check(
    copy: Copy,
) -> None:
    copy.record(lambda r: r.update(views=[r["views"][i] for i in (1, 0, 2, 3)]))
    assert copy.verdicts() == all_pass_but(views="fails")
    assert "the record lists the views top, front" in copy.message("views")


# --- title block ------------------------------------------------------------------------------


def test_a_title_block_without_the_geometry_hash_fails_the_title_block_check(copy: Copy) -> None:
    field = r'<text class="field" data-field="geometry_hash".*\n'
    copy.svg_text(lambda svg: re.sub(field, "", svg))
    assert copy.verdicts() == all_pass_but(title_block="fails")
    assert "no geometry hash in the title block" in copy.message("title block")


def test_a_title_block_that_shows_another_scale_fails_the_title_block_check(copy: Copy) -> None:
    copy.svg_text(lambda svg: re.sub(r'(data-field="scale"[^>]*>)1:1<', r"\g<1>1:2<", svg))
    assert copy.verdicts() == all_pass_but(title_block="fails")
    assert "scale 1:2, not 1:1" in copy.message("title block")


def test_a_record_whose_title_block_names_another_hash_fails_the_title_block_check(
    copy: Copy,
) -> None:
    def other(record: dict[str, Any]) -> None:
        record["title_block"]["geometry_hash"] = OTHER_HASH

    copy.record(other)
    assert copy.verdicts() == all_pass_but(title_block="fails")
    assert OTHER_HASH in copy.message("title block")


def test_a_record_and_its_title_block_that_agree_on_another_hash_still_fail(copy: Copy) -> None:
    # The SVG and the record's title block both say another hash: only the record's own hash,
    # the one the part check judges, still says the plate's.
    copy.svg_text(lambda svg: svg.replace(PLATE_HASH, OTHER_HASH))

    def other(record: dict[str, Any]) -> None:
        record["title_block"]["geometry_hash"] = OTHER_HASH

    copy.record(other)
    assert copy.verdicts() == all_pass_but(title_block="fails")
    assert "the record's geometry hash is" in copy.message("title block")


def _title_field(field: str, now: str, then: str) -> Callable[[str], str]:
    def edit(svg: str) -> str:
        return re.sub(rf'(data-field="{field}"[^>]*>){re.escape(now)}<', rf"\g<1>{then}<", svg)

    return edit


def test_a_title_block_and_its_record_that_agree_on_another_file_drawn_from_still_fail(
    copy: Copy,
) -> None:
    # The SVG and the record's title block both name another file; the record's own drawn_from
    # still names the plate's STEP file.
    copy.svg_text(_title_field("drawn_from", "exports/plate.step", "exports/other.step"))
    copy.record(lambda r: r["title_block"].update(drawn_from="exports/other.step"))
    assert copy.verdicts() == all_pass_but(title_block="fails")
    assert "the record's drawn from is exports/plate.step" in copy.message("title block")


def test_a_title_block_and_its_record_that_agree_on_another_scale_still_fail(copy: Copy) -> None:
    copy.svg_text(_title_field("scale", "1:1", "1:2"))
    copy.record(lambda r: r["title_block"].update(scale="1:2"))
    assert copy.verdicts() == all_pass_but(title_block="fails")
    assert "the record's scale is 1:1" in copy.message("title block")


def test_a_drawing_without_a_title_block_fails_the_title_block_check(copy: Copy) -> None:
    copy.svg_text(lambda svg: _drop_group(svg, "title-block"))
    assert copy.verdicts() == all_pass_but(title_block="fails")


# --- dimensions -------------------------------------------------------------------------------


def test_a_drawing_that_shows_another_length_fails_the_dimensions_check(copy: Copy) -> None:
    shown = r'(data-quantity="length_x"[^>]*>)110\.0<'
    copy.svg_text(lambda svg: re.sub(shown, r"\g<1>111.0<", svg))
    assert copy.verdicts() == all_pass_but(dimensions="fails")
    assert "shows length_x 111.0 mm" in copy.message("dimensions")


def test_a_record_that_gives_another_length_fails_the_dimensions_check(copy: Copy) -> None:
    copy.record(lambda r: r["overall"]["length_x"].update(value=110.2))
    assert copy.verdicts() == all_pass_but(dimensions="fails")
    assert "the record's length_x is 110.2 mm" in copy.message("dimensions")


@pytest.mark.parametrize("written", ["nan", "inf", "1.1e2", "-110.0", "110"])
def test_a_length_not_written_as_a_dimension_is_no_dimension(copy: Copy, written: str) -> None:
    shown = r'(data-quantity="length_x"[^>]*>)110\.0<'
    copy.svg_text(lambda svg: re.sub(shown, rf"\g<1>{written}<", svg))
    assert copy.verdicts() == all_pass_but(dimensions="fails")
    assert "shows no length_x" in copy.message("dimensions")


def test_a_drawing_that_does_not_show_the_width_fails_the_dimensions_check(copy: Copy) -> None:
    copy.svg_text(lambda svg: svg.replace('data-quantity="width_y"', 'data-quantity="w"'))
    assert copy.verdicts() == all_pass_but(dimensions="fails")
    assert "shows no width_y" in copy.message("dimensions")


def _wider(by_m: float) -> Any:  # noqa: ANN401 - an edit of a record
    def edit(part: dict[str, Any]) -> None:
        part["values"]["bounding_box"]["high_corner"]["value"][1] += by_m

    return edit


def test_a_part_wider_than_the_drawing_shows_by_more_than_half_a_tenth_fails(copy: Copy) -> None:
    copy.part_record(_wider(0.06e-3))
    assert copy.verdicts() == all_pass_but(dimensions="fails")
    assert "width_y" in copy.message("dimensions")


def test_a_part_wider_by_less_than_half_a_tenth_is_still_shown_as_drawn(copy: Copy) -> None:
    copy.part_record(_wider(0.04e-3))
    assert copy.verdicts() == all_pass_but()


def test_a_part_wider_by_exactly_half_a_tenth_is_shown_a_tenth_wider_so_the_drawing_fails(
    copy: Copy,
) -> None:
    # 60.05 mm, rounded half up, is written 60.1: a drawing that shows 60.0 is not this part's.
    copy.part_record(_wider(0.05e-3))
    assert copy.verdicts() == all_pass_but(dimensions="fails")
    said = copy.message("dimensions")
    assert "shows width_y 60.0 mm" in said and "60.05 mm" in said and "60.1" in said


def test_a_dimension_s_message_gives_the_part_s_length_in_full(copy: Copy) -> None:
    # 110.0504 mm is written 110.1; the message shows all of it, not three decimals of it.
    def longer(part: dict[str, Any]) -> None:
        part["values"]["bounding_box"]["high_corner"]["value"][0] = 0.0550504

    copy.part_record(longer)
    assert copy.verdicts() == all_pass_but(dimensions="fails")
    assert "110.0504 mm" in copy.message("dimensions")


# --- each check on its own --------------------------------------------------------------------


def test_two_things_doctored_fail_two_checks(copy: Copy) -> None:
    copy.svg_text(lambda svg: _drop_group(_drop_group(svg, "view-isometric"), "title-block"))
    copy.part_record(lambda part: part.update(geometry_hash=OTHER_HASH))
    assert copy.verdicts() == all_pass_but(part="stale", views="fails", title_block="fails")


# --- every field of the drawing's record ------------------------------------------------------

OTHER_SHA = "0" * 64


def _set(*where: str | int, to: object) -> Callable[[dict[str, Any]], None]:
    def edit(record: dict[str, Any]) -> None:
        held: Any = record
        for key in where[:-1]:
            held = held[key]
        held[where[-1]] = to

    return edit


#: Each field of the drawing's record, edited in the record alone, and the verdicts that follow.
#: "refused" means the record is not read at all. A field the help names as recorded and not
#: checked changes no verdict.
FIELD_EDITS: dict[str, tuple[Callable[[dict[str, Any]], None], dict[str, str] | str]] = {
    "schema": (_set("schema", to=2), "refused"),
    "kind": (_set("kind", to="projection"), "refused"),
    "shown": (_set("shown", to="measured"), all_pass_but()),
    "left_out": (_set("left_out", to="nothing"), all_pass_but()),
    "part": (_set("part", to="motor_mount"), all_pass_but(part="fails", title_block="fails")),
    "geometry_hash": (
        _set("geometry_hash", to=OTHER_HASH),
        all_pass_but(part="stale", file="fails", title_block="fails"),
    ),
    "drawn_from.sha256": (_set("drawn_from", "sha256", to=OTHER_SHA), all_pass_but(part="fails")),
    "drawn_from.size": (_set("drawn_from", "size", "value", to=1), all_pass_but(part="fails")),
    "files.svg.sha256": (_set("files", "svg", "sha256", to=OTHER_SHA), all_pass_but(file="fails")),
    "files.projection.sha256": (
        _set("files", "projection", "sha256", to=OTHER_SHA),
        all_pass_but(file="fails"),
    ),
    "files.projection.size": (
        _set("files", "projection", "size", "value", to=1),
        all_pass_but(file="fails"),
    ),
    "sheet.width": (_set("sheet", "width", "value", to=400.0), all_pass_but(file="fails")),
    "sheet.height": (_set("sheet", "height", "value", to=210.0), all_pass_but(file="fails")),
    "sheet.size": (_set("sheet", "size", to="A4 landscape"), all_pass_but()),
    "scale.value": (_set("scale", "value", to=2.0), all_pass_but(title_block="fails")),
    "units": (_set("units", to="in"), "refused"),
    "projection_method": (
        _set("projection_method", to="third angle"),
        all_pass_but(title_block="fails"),
    ),
    "views.side.viewed_from": (
        _set("views", 2, "viewed_from", "value", to=[1.0, 0.0, 0.0]),
        all_pass_but(views="fails"),
    ),
    "views.front.up": (
        _set("views", 0, "up", "value", to=[0.0, 0.0, -1.0]),
        all_pass_but(views="fails"),
    ),
    "views.front.hidden_paths": (
        _set("views", 0, "hidden_paths", "value", to=0),
        all_pass_but(views="fails", file="fails"),
    ),
    "overall.height_z": (
        _set("overall", "height_z", "value", to=3.1),
        all_pass_but(dimensions="fails"),
    ),
    "shown_to": (_set("shown_to", "value", to=1.0), all_pass_but(dimensions="fails")),
    "agreement_within": (
        _set("agreement_within", "value", to=0.5),
        all_pass_but(dimensions="fails"),
    ),
    "rounding": (_set("rounding", to="half even"), all_pass_but(dimensions="fails")),
    "title_block.units": (_set("title_block", "units", to="in"), all_pass_but(title_block="fails")),
    "generator.version": (_set("generator", "version", to="9"), all_pass_but(title_block="fails")),
    "generator.name": (
        _set("generator", "name", to="another drawer"),
        all_pass_but(title_block="fails"),
    ),
    "libraries": (
        _set("libraries", "build123d", to="0.0.0"),
        all_pass_but(file="fails"),
    ),
}


@pytest.mark.parametrize("field", sorted(FIELD_EDITS))
def test_a_record_edited_in_one_field_alone_gives_the_verdicts_that_field_is_checked_by(
    copy: Copy, field: str
) -> None:
    edit, then = FIELD_EDITS[field]
    copy.record(edit)
    if then == "refused":
        with pytest.raises(RecordError):
            copy.check()
    else:
        assert copy.verdicts() == then


def test_every_field_of_the_drawing_s_record_has_a_row_above() -> None:
    fields = {info.alias or name for name, info in DrawingRecord.model_fields.items()}
    edited = {field.split(".")[0] for field in FIELD_EDITS}
    assert edited == fields


# --- the projection file ----------------------------------------------------------------------


def test_a_missing_projection_file_fails_the_file_check(copy: Copy) -> None:
    (copy.root / "plate.projection.json").unlink()
    assert copy.verdicts() == all_pass_but(file="fails")
    assert "plate.projection.json" in copy.message("file")


def test_a_projection_file_of_another_shape_fails_the_file_check(copy: Copy) -> None:
    copy.projection(lambda p: p.update(geometry_hash=OTHER_HASH))
    assert copy.verdicts() == all_pass_but(file="fails")
    assert OTHER_HASH in copy.message("file")


def test_a_projection_file_from_other_libraries_fails_the_file_check(copy: Copy) -> None:
    copy.projection(lambda p: p["libraries"].update(build123d="0.0.0"))
    assert copy.verdicts() == all_pass_but(file="fails")
    assert "0.0.0" in copy.message("file")


def test_a_projection_file_with_a_line_fewer_than_the_record_says_fails_the_file_check(
    copy: Copy,
) -> None:
    copy.projection(lambda p: p["views"]["top"]["visible"].pop())
    assert copy.verdicts() == all_pass_but(file="fails")
    assert "top" in copy.message("file")


def test_the_committed_projection_is_the_one_the_committed_record_names() -> None:
    record = json.loads((FIXTURE / "plate.drawing.json").read_text(encoding="utf-8"))
    data = (FIXTURE / "plate.projection.json").read_bytes()
    assert record["files"]["projection"]["sha256"] == hashlib.sha256(data).hexdigest()
