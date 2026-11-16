"""The law table a promotion writes reads back to exactly the rows it meant to write.

A promotion writes the table whole, so its spelling of every value the table can hold is what
keeps every earlier row as it was: strings with quotes, escapes, control characters and any
script; integers, floats in every notation, booleans, dates; lists, lists of tables and nested
tables. A value it cannot spell (a time of day, a number that is not finite) is refused, and a
table that does not read back as written is never written.
"""

from __future__ import annotations

import datetime
import math
import tomllib
from pathlib import Path
from typing import Any

import pytest
from law_cards import FIRST, SECOND, card_row, card_text, law_promotion, library

ROW: dict[str, Any] = {
    "id": "a_row",
    "text": 'quotes " and \\ backslashes, a tab\t, a line\nbreak, \x00 \x1f \x7f, ½ Ω µ 漢字 😀',
    "count": -7,
    "floats": [0.1, -2.5, 1e-05, 1e16, 6.02e23, 0.0, -0.0],
    "flags": [True, False],
    "when": datetime.date(2026, 11, 6),
    "empty_list": [],
    "empty_table": {},
    "nested": {"a": {"b": [1, 2], "c": "d"}, "spaced key": 1, "ключ": "value"},
    "tables": [
        {"value": 1.5, "unit": "mW", "list": [{"x": 1}, {"x": 2}]},
        {"value": 2, "unit": "V"},
    ],
}


def test_every_value_a_row_can_hold_reads_back_as_written() -> None:
    module = law_promotion()
    meta = {"format": 1}
    text = module._table_text(meta, [ROW])
    try:
        parsed = tomllib.loads(text)
    except tomllib.TOMLDecodeError as exc:
        raise AssertionError(f"the table written is not TOML: {exc}") from None
    assert parsed == {"meta": meta, "law": [ROW]}
    assert text.startswith(module.HEADER)
    signs = [math.copysign(1, f) for f in parsed["law"][0]["floats"]]
    assert signs == [math.copysign(1, f) for f in ROW["floats"]], "a float's sign was lost"


def test_only_a_row_s_own_list_of_tables_spans_lines() -> None:
    module = law_promotion()
    lines = module._row_text({"id": "a", "tables": ROW["tables"]}).splitlines()
    assert lines[:3] == ["[[law]]", 'id = "a"', "tables = ["]
    assert lines[-1] == "]" and len(lines) == 6, "a table inside the list spans lines"


@pytest.mark.parametrize(
    "value",
    [
        math.inf,
        -math.inf,
        math.nan,
        datetime.datetime(2026, 11, 6, 12),
        datetime.time(12),
        object(),
    ],
    ids=["inf", "minus-inf", "nan", "date-and-time", "time", "object"],
)
def test_a_value_toml_cannot_spell_here_is_refused(value: object) -> None:
    module = law_promotion()
    try:
        module._table_text({"format": 1}, [{"id": "a", "value": value}])
    except module.PromotionError:
        return
    raise AssertionError(f"{value!r} was spelled, where a refusal was expected")


def test_a_table_that_would_not_read_back_is_never_written(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    module = law_promotion()
    found = library(tmp_path)
    found.stage(FIRST, card_text(card_row("electrical_power")))
    module._apply_law(FIRST, by="a person", on=None, notice=None, **found.kwargs())
    found.stage(SECOND, card_text(card_row("another_power")))
    before = found.state()
    spell = module._table_text
    # A spelling that loses the earlier row, as a broken writer would.
    monkeypatch.setattr(module, "_table_text", lambda meta, rows: spell(meta, rows[:1]))
    try:
        module._apply_law(SECOND, by="a person", on=None, notice=None, **found.kwargs())
    except module.PromotionError as exc:
        assert "read back" in str(exc)
    else:
        raise AssertionError("a table that does not read back was written")
    assert found.state() == before
    assert found.card(SECOND).is_file()


def test_a_table_that_would_not_parse_is_never_written(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    module = law_promotion()
    found = library(tmp_path)
    found.stage(FIRST, card_text(card_row()))
    before = found.state()
    monkeypatch.setattr(module, "_table_text", lambda meta, rows: "[meta\n")
    try:
        module._apply_law(FIRST, by="a person", on=None, notice=None, **found.kwargs())
    except module.PromotionError as exc:
        assert "read back" in str(exc)
    else:
        raise AssertionError("a table that does not parse was written")
    assert found.state() == before


def test_a_table_that_does_not_load_as_it_stands_is_refused_not_rewritten(
    tmp_path: Path,
) -> None:
    # A row the record does not account for: the gate does not build on this table, and a
    # promotion does not quietly carry the row on.
    module = law_promotion()
    found = library(tmp_path)
    found.stage(FIRST, card_text(card_row("electrical_power")))
    module._apply_law(FIRST, by="a person", on=None, notice=None, **found.kwargs())
    found.promotions.write_text("", encoding="utf-8")
    found.stage(SECOND, card_text(card_row("another_power")))
    before = found.state()
    try:
        module._apply_law(SECOND, by="a person", on=None, notice=None, **found.kwargs())
    except module.PromotionError as exc:
        assert "as it stands" in str(exc)
    else:
        raise AssertionError("a table that does not load was rewritten")
    assert found.state() == before


def test_a_missing_table_is_refused(tmp_path: Path) -> None:
    module = law_promotion()
    found = library(tmp_path)
    found.table.unlink()
    found.stage(FIRST, card_text(card_row()))
    try:
        module._apply_law(FIRST, by="a person", on=None, notice=None, **found.kwargs())
    except module.PromotionError as exc:
        assert "no law table" in str(exc)
    else:
        raise AssertionError("a promotion went ahead with no table")
    assert not found.table.exists()


def test_the_date_is_today_s_when_none_is_given(tmp_path: Path) -> None:
    module = law_promotion()
    found = library(tmp_path)
    found.stage(FIRST, card_text(card_row()))
    day = datetime.date.today()
    module._apply_law(FIRST, by="a person", on=None, notice=None, **found.kwargs())
    (row,) = tomllib.loads(found.table.read_text(encoding="utf-8"))["law"]
    assert row["approved"]["date"] in (day, datetime.date.today())
