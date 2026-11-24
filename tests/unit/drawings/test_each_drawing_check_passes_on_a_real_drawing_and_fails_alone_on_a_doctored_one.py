"""Each check of a drawing passes on a real one and fails on its own when the drawing is doctored.

The drawing is the chassis plate's, made by the kernel on a provisioned tool environment and
committed beside these rows. Each row changes one thing (the part's record, the SVG, or the
drawing's record) and reads the verdicts: the check that owns the change fails, and only it,
since every check is judged whatever another found. When the SVG is changed, the record is made
to name the changed file unless the row is about the file itself, so the file check stays out of
the way of the check under test.
"""

from __future__ import annotations

import re
from pathlib import Path
from typing import Any

import pytest
from drawing_helpers import PLATE_HASH, Copy, all_pass_but

from physgate.build.drawings.check import EXIT_FAILS, EXIT_PASSES, EXIT_STALE, exit_status

OTHER_HASH = "sha256:" + "0" * 64


@pytest.fixture
def copy(tmp_path: Path) -> Copy:
    return Copy(tmp_path / "drawing")


def _drop_group(svg: str, group: str) -> str:
    return re.sub(rf'<g id="{group}"[^>]*>.*?</g>\n', "", svg, count=1, flags=re.S)


def _in_group(svg: str, group: str, edit: Any) -> str:  # noqa: ANN401 - a function of a string
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


def test_a_record_that_lists_three_views_fails_the_views_check(copy: Copy) -> None:
    copy.record(lambda r: r.update(views=r["views"][:3]))
    assert copy.verdicts() == all_pass_but(views="fails")


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


def test_a_part_wider_by_exactly_half_a_tenth_still_agrees_with_the_drawing(copy: Copy) -> None:
    copy.part_record(_wider(0.05e-3))
    assert copy.verdicts() == all_pass_but()


# --- each check on its own --------------------------------------------------------------------


def test_two_things_doctored_fail_two_checks(copy: Copy) -> None:
    copy.svg_text(lambda svg: _drop_group(_drop_group(svg, "view-isometric"), "title-block"))
    copy.part_record(lambda part: part.update(geometry_hash=OTHER_HASH))
    assert copy.verdicts() == all_pass_but(part="stale", views="fails", title_block="fails")
