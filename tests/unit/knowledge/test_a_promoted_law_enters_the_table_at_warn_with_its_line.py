"""Promoting a staged law card writes its row at ``warn``, one promotion line, and nothing else.

What a promotion does once the person at the terminal has run it (the terminal check itself is
proven in the test file beside this one, and these tests call the step after it, in a library
under a temporary directory):

- the card's row enters the law table at ``status = "warn"``, its approval naming the card's
  candidate id and the date, in id order with every earlier row kept as it was;
- one line is appended to the promotion record: the law, the candidate, where it went, who
  promoted it, and the sha256 of the table as written, which the loader then holds the row to;
- the staged card is removed;
- before anything is written, the person is shown the row, its provenance and the table's
  sha256 before and after.

A card is refused, with nothing written and the card left staged, when the row it carries could
not load in the gate (its examples are run), when it already carries what only promotion sets,
when its reviewer rejected it or is the model that drafted it, when it has no page for the
person, or when its law's id is already in the table.
"""

from __future__ import annotations

import datetime
import hashlib
import os
import tomllib
from collections.abc import Callable
from pathlib import Path
from typing import Any

import pytest
from law_cards import FIRST, SECOND, Library, card_row, card_text, law_promotion, library
from law_rows import sound_law

from physgate.gate.laws import load_laws

ON = datetime.date(2026, 11, 6)


def promote(found: Library, candidate_id: str, **changes: Any) -> Path:
    """Promote ``candidate_id`` in ``found``, as the step after the terminal check does."""
    module = law_promotion()
    kwargs: dict[str, Any] = {"by": "a person", "on": ON, "notice": None, **found.kwargs()}
    kwargs.update(changes)
    destination: Path = module._apply_law(candidate_id, **kwargs)
    return destination


def refusal(call: Callable[[], object]) -> str:
    """The promotion's refusal, as text; an assertion fails if it went ahead."""
    module = law_promotion()
    try:
        call()
    except module.PromotionError as exc:
        return f"{exc} {exc.context}"
    raise AssertionError("the promotion went ahead, where a refusal was expected")


def rows(found: Library) -> list[dict[str, Any]]:
    table: list[dict[str, Any]] = tomllib.loads(found.table.read_text(encoding="utf-8")).get(
        "law", []
    )
    return table


# --- what a promotion writes ---------------------------------------------------------------


def test_a_promoted_law_enters_the_table_at_warn_approved_by_its_candidate_and_date(
    tmp_path: Path,
) -> None:
    found = library(tmp_path)
    found.stage(FIRST, card_text(card_row()))
    assert promote(found, FIRST) == found.table
    loaded = load_laws(found.table, found.promotions)
    assert list(loaded.laws) == ["electrical_power"]
    law = loaded.laws["electrical_power"]
    assert law.status == "warn"
    assert (law.approved.candidate_id, law.approved.date) == (FIRST, ON)
    expected = sound_law(approved={"candidate_id": FIRST, "date": ON.isoformat()})
    assert law.model_dump(mode="json", exclude_none=True) == expected


def test_the_promotion_line_names_the_law_its_candidate_and_the_table_as_written(
    tmp_path: Path,
) -> None:
    found = library(tmp_path)
    found.stage(FIRST, card_text(card_row()))
    promote(found, FIRST, by="yasin")
    (line,) = found.lines()
    assert set(line) == {
        "kind",
        "law_id",
        "candidate_id",
        "destination",
        "promoted_by",
        "promoted",
        "sha256",
    }
    assert line["kind"] == "law"
    assert line["law_id"] == "electrical_power"
    assert line["candidate_id"] == FIRST
    assert line["destination"] == str(found.table)
    assert line["promoted_by"] == "yasin"
    assert line["sha256"] == hashlib.sha256(found.table.read_bytes()).hexdigest()


def test_a_promotion_appends_to_the_record_and_keeps_every_earlier_line(tmp_path: Path) -> None:
    found = library(tmp_path)
    earlier = '{"candidate_id": "x", "kind": "skill"}\n'
    found.promotions.write_text(earlier, encoding="utf-8")
    found.stage(FIRST, card_text(card_row()))
    promote(found, FIRST)
    text = found.promotions.read_text(encoding="utf-8")
    assert text.startswith(earlier)
    assert [line["kind"] for line in found.lines()] == ["skill", "law"]


def test_the_staged_card_is_removed_once_promoted(tmp_path: Path) -> None:
    found = library(tmp_path)
    found.stage(FIRST, card_text(card_row()))
    promote(found, FIRST)
    assert not found.card(FIRST).exists()


def test_the_person_is_shown_the_row_its_provenance_and_the_table_before_and_after(
    tmp_path: Path,
) -> None:
    found = library(tmp_path)
    found.stage(FIRST, card_text(card_row()))
    before = found.table.read_bytes()
    told: list[str] = []
    written_when_told: list[bytes] = []

    def notice(text: str) -> None:
        told.append(text)
        written_when_told.append(found.table.read_bytes())

    promote(found, FIRST, notice=notice)
    assert len(told) == 1, "the person is told once, before the write"
    assert written_when_told == [before], "the person was told after the table was written"
    shown = told[0]
    after = found.table.read_bytes()
    for part in (
        FIRST,
        "electrical_power",
        "warn",
        "P == V * I",
        "Fundamentals of Electric Circuits",
        "1.5, power and energy",
        "claude-opus-5-5",
        "claude-sonnet-5",
        "accept",
        hashlib.sha256(before).hexdigest(),
        hashlib.sha256(after).hexdigest(),
    ):
        assert part in shown, f"the person was not shown {part!r}"


def test_rows_are_kept_in_id_order_whatever_order_they_are_promoted_in(tmp_path: Path) -> None:
    found = library(tmp_path)
    found.stage(FIRST, card_text(card_row("electrical_power")))
    found.stage(SECOND, card_text(card_row("another_power")))
    promote(found, FIRST)
    promote(found, SECOND)
    assert [row["id"] for row in rows(found)] == ["another_power", "electrical_power"]
    loaded = load_laws(found.table, found.promotions)
    assert sorted(loaded.laws) == ["another_power", "electrical_power"]
    assert loaded.laws["another_power"].approved.candidate_id == SECOND


def test_a_promotion_keeps_every_earlier_row_as_it_was(tmp_path: Path) -> None:
    found = library(tmp_path)
    found.stage(FIRST, card_text(card_row("electrical_power")))
    promote(found, FIRST)
    (first,) = rows(found)
    found.stage(SECOND, card_text(card_row("another_power")))
    promote(found, SECOND)
    assert rows(found)[1] == first


@pytest.mark.parametrize(
    "statement",
    [
        'the "power" a node draws is its voltage times its current',
        "a back\\slash, a tab\tand a line\nbreak",
        "the power P = V·I, in watts — or ½ of 2 W, Ω and µ kept",
        "a delete character \x7f and a bell \x07 kept as they are",
    ],
    ids=["quotes", "escapes", "unicode", "controls"],
)
def test_a_row_s_text_is_written_back_exactly_as_the_card_gave_it(
    tmp_path: Path, statement: str
) -> None:
    found = library(tmp_path)
    found.stage(FIRST, card_text(card_row(statement=statement)))
    promote(found, FIRST)
    law = load_laws(found.table, found.promotions).laws["electrical_power"]
    assert law.statement == statement.strip()


def test_the_table_s_format_line_is_kept(tmp_path: Path) -> None:
    found = library(tmp_path)
    found.stage(FIRST, card_text(card_row()))
    promote(found, FIRST)
    assert tomllib.loads(found.table.read_text(encoding="utf-8"))["meta"] == {"format": 1}


# --- what a promotion refuses --------------------------------------------------------------


def refused_card(tmp_path: Path, text: str, **changes: Any) -> str:
    """Stage ``text`` and promote it; the refusal, with nothing written and the card kept."""
    found = library(tmp_path)
    found.stage(FIRST, text)
    before = found.state()
    why = refusal(lambda: promote(found, FIRST, **changes))
    assert found.state() == before, "a refused promotion wrote to the table or the record"
    assert found.card(FIRST).is_file(), "a refused promotion removed the staged card"
    return why


FAILING_PASS_EXAMPLE = [
    {
        "outcome": "pass",
        "source": "numbers that break the law",
        "values": {
            "P": {"value": 30, "unit": "mW"},
            "V": {"value": 3.3, "unit": "V"},
            "I": {"value": 3.9, "unit": "mA"},
        },
    },
    sound_law()["example"][1],
]


@pytest.mark.parametrize(
    ("text", "said"),
    [
        (card_text(card_row(status="warn")), "status"),
        (card_text(card_row(status="block")), "status"),
        (card_text(card_row(approved={"candidate_id": FIRST, "date": "2026-11-05"})), "approved"),
        (card_text(card_row(cleared={"audit_sha256": "b" * 64})), "cleared"),
        (card_text(card_row(), verdict="reject"), "reject"),
        (card_text(card_row(), reviewed_by="claude-opus-5-5"), "same model"),
        (card_text(card_row(), page="   "), "page"),
        (card_text(card_row(example=FAILING_PASS_EXAMPLE)), "would not load"),
        (card_text(card_row(expression="P == V * I * 6")), "would not load"),
        ("[card]\nformat = 1\n", "card"),
        ("this is not TOML = = =", "TOML"),
    ],
    ids=[
        "status-warn",
        "status-block",
        "approved",
        "cleared",
        "rejected",
        "reviewer-is-drafter",
        "no-page",
        "example-fails",
        "undeclared-literal",
        "no-row",
        "not-toml",
    ],
)
def test_a_card_that_cannot_be_promoted_is_refused_and_nothing_is_written(
    tmp_path: Path, text: str, said: str
) -> None:
    assert said in refused_card(tmp_path, text)


def test_a_law_already_in_the_table_is_refused_and_nothing_is_written(tmp_path: Path) -> None:
    found = library(tmp_path)
    found.stage(FIRST, card_text(card_row()))
    promote(found, FIRST)
    found.stage(SECOND, card_text(card_row()))
    before = found.state()
    why = refusal(lambda: promote(found, SECOND))
    assert "already" in why and "electrical_power" in why
    assert found.state() == before
    assert found.card(SECOND).is_file()


@pytest.mark.parametrize(
    ("candidate_id", "said"),
    [("b" * 32, "no staged"), ("../" + "a" * 29, "plain id"), ("A" * 32, "plain id")],
    ids=["not-staged", "a-path", "not-lowercase-hex"],
)
def test_a_candidate_that_is_not_staged_under_its_plain_id_is_refused(
    tmp_path: Path, candidate_id: str, said: str
) -> None:
    found = library(tmp_path)
    found.stage(FIRST, card_text(card_row()))
    before = found.state()
    assert said in refusal(lambda: promote(found, candidate_id))
    assert found.state() == before


def test_a_promotion_without_a_person_s_name_is_refused(tmp_path: Path) -> None:
    assert "name" in refused_card(tmp_path, card_text(card_row()), by="  ")


def test_a_staged_card_that_is_a_link_is_refused(tmp_path: Path) -> None:
    found = library(tmp_path)
    elsewhere = tmp_path / "elsewhere.toml"
    elsewhere.write_text(card_text(card_row()), encoding="utf-8")
    found.card(FIRST).parent.mkdir(parents=True)
    os.symlink(elsewhere, found.card(FIRST))
    before = found.state()
    assert "link" in refusal(lambda: promote(found, FIRST))
    assert found.state() == before


def test_a_table_that_is_a_link_is_refused_and_what_it_names_is_not_written(
    tmp_path: Path,
) -> None:
    found = library(tmp_path)
    found.stage(FIRST, card_text(card_row()))
    elsewhere = tmp_path / "elsewhere.toml"
    elsewhere.write_text("# the law table\n[meta]\nformat = 1\n", encoding="utf-8")
    found.table.unlink()
    os.symlink(elsewhere, found.table)
    assert "link" in refusal(lambda: promote(found, FIRST))
    assert elsewhere.read_text(encoding="utf-8") == "# the law table\n[meta]\nformat = 1\n"
    assert found.lines() == []
