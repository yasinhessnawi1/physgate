"""A law moves from ``warn`` to ``block`` only through its staged clearance and a promotion line.

The move is the same person-only step as a promotion (its terminal check is proven beside
this file; these tests call the step after it, in a library under a temporary directory). Once
run, it:

- sets the row's status to ``block`` and gives it the audit's clearance, dated the day the
  person approved the move;
- appends one ``law_status`` line carrying the clearance, which the loader holds the move to;
- removes the staged clearance;
- shows the person the law, the clearance and the table's sha256 before and after, first.

It is refused, with nothing written and the clearance left staged, when no clearance is staged,
when the law is not in the table or is already at ``block``, when the clearance already carries
the person's date, or when the table would not load with it: a clearance under the block bar
never moves a law.
"""

from __future__ import annotations

import datetime
import hashlib
import tomllib
from collections.abc import Callable
from pathlib import Path
from typing import Any

import pytest
from law_cards import FIRST, SECOND, Library, card_row, card_text, clearance_text, law_promotion
from law_cards import library as empty_library

from physgate.gate.laws import load_laws

PROMOTED = datetime.date(2026, 11, 6)
MOVED = datetime.date(2026, 11, 20)
LAW = "electrical_power"


def library(tmp_path: Path) -> Library:
    """A table holding two promoted laws at ``warn``, the first one's clearance staged."""
    module = law_promotion()
    found = empty_library(tmp_path)
    found.stage(FIRST, card_text(card_row(LAW)))
    found.stage(SECOND, card_text(card_row("another_power")))
    for candidate_id in (FIRST, SECOND):
        module._apply_law(candidate_id, by="a person", on=PROMOTED, notice=None, **found.kwargs())
    found.stage_clearance(LAW, clearance_text())
    return found


def attempt(found: Library, law_id: str = LAW, **changes: Any) -> Path:
    """Move ``law_id`` to ``block`` in ``found``, as the step after the terminal check does."""
    module = law_promotion()
    kwargs: dict[str, Any] = {"by": "a person", "on": MOVED, "notice": None, **found.kwargs()}
    kwargs.update(changes)
    destination: Path = module._apply_block(law_id, **kwargs)
    return destination


def move(found: Library, law_id: str = LAW, **changes: Any) -> Path:
    """A move that should go ahead; an assertion fails if it is refused."""
    module = law_promotion()
    try:
        return attempt(found, law_id, **changes)
    except module.PromotionError as exc:
        raise AssertionError(f"the move was refused, where it should go ahead: {exc}") from None


def refusal(call: Callable[[], object]) -> str:
    """The move's refusal, as text; an assertion fails if it went ahead."""
    module = law_promotion()
    try:
        call()
    except module.PromotionError as exc:
        return f"{exc} {exc.context}"
    raise AssertionError("the move went ahead, where a refusal was expected")


def rows(found: Library) -> dict[str, dict[str, Any]]:
    table = tomllib.loads(found.table.read_text(encoding="utf-8"))
    return {row["id"]: row for row in table.get("law", [])}


# --- what a move writes ----------------------------------------------------------------------


def test_a_moved_law_is_at_block_with_its_clearance_dated_by_the_person(tmp_path: Path) -> None:
    found = library(tmp_path)
    assert move(found) == found.table
    law = load_laws(found.table, found.promotions).laws[LAW]
    assert law.status == "block"
    assert law.cleared is not None
    assert law.cleared.model_dump(mode="json") == {
        "audit_sha256": "b" * 64,
        "evaluated_clean": 12,
        "designs": ["practice-set", "g11-run-4"],
        "unexplained": 0,
        "approved": MOVED.isoformat(),
    }


def test_the_move_s_line_carries_the_clearance_and_the_table_as_written(tmp_path: Path) -> None:
    found = library(tmp_path)
    move(found, by="yasin")
    line = found.lines()[-1]
    assert set(line) == {
        "kind",
        "law_id",
        "status",
        "audit_sha256",
        "cleared",
        "destination",
        "promoted_by",
        "promoted",
        "sha256",
    }
    assert (line["kind"], line["law_id"], line["status"]) == ("law_status", LAW, "block")
    assert line["audit_sha256"] == "b" * 64
    assert line["cleared"] == {
        "audit_sha256": "b" * 64,
        "evaluated_clean": 12,
        "designs": ["practice-set", "g11-run-4"],
        "unexplained": 0,
        "approved": MOVED.isoformat(),
    }
    assert line["destination"] == str(found.table)
    assert line["promoted_by"] == "yasin"
    assert line["sha256"] == hashlib.sha256(found.table.read_bytes()).hexdigest()


def test_the_move_keeps_every_other_row_and_line_as_it_was(tmp_path: Path) -> None:
    found = library(tmp_path)
    other = rows(found)["another_power"]
    earlier = found.lines()
    move(found)
    assert "another_power" in rows(found), "the move dropped another law's row"
    assert rows(found)["another_power"] == other
    assert found.lines()[:-1] == earlier
    moved = rows(found)[LAW]
    assert moved["approved"] == {"candidate_id": FIRST, "date": PROMOTED}


def test_the_staged_clearance_is_removed_once_the_law_is_moved(tmp_path: Path) -> None:
    found = library(tmp_path)
    move(found)
    assert not found.clearance(LAW).exists()


def test_the_person_is_shown_the_law_the_clearance_and_the_table_before_and_after(
    tmp_path: Path,
) -> None:
    found = library(tmp_path)
    before = found.table.read_bytes()
    told: list[str] = []
    written_when_told: list[bytes] = []

    def notice(text: str) -> None:
        told.append(text)
        written_when_told.append(found.table.read_bytes())

    move(found, notice=notice)
    assert len(told) == 1 and written_when_told == [before]
    after = found.table.read_bytes()
    for part in (
        LAW,
        "block",
        "b" * 64,
        "12",
        "practice-set",
        "g11-run-4",
        hashlib.sha256(before).hexdigest(),
        hashlib.sha256(after).hexdigest(),
    ):
        assert part in told[0], f"the person was not shown {part!r}"


# --- what a move refuses -----------------------------------------------------------------


def refused_move(found: Library, law_id: str = LAW) -> str:
    """Move ``law_id``; the refusal, with nothing written and any staged clearance kept."""
    before = found.state()
    staged = found.clearance(law_id).is_file()
    why = refusal(lambda: attempt(found, law_id))
    assert found.state() == before, "a refused move wrote to the table or the record"
    assert found.clearance(law_id).is_file() == staged, "a refused move removed the clearance"
    return why


@pytest.mark.parametrize(
    ("clearance", "said"),
    [
        (clearance_text(evaluated_clean=9), "would not load"),
        (clearance_text(designs=["practice-set"]), "would not load"),
        (clearance_text(unexplained=1), "would not load"),
        (clearance_text(approved="2026-11-19"), "only a move sets"),
        (clearance_text(audit_sha256="not a digest"), "clearance"),
        ("[cleared]\naudit_sha256 = 1 = 2\n", "TOML"),
        ("[audit]\nevaluated_clean = 12\n", "clearance"),
    ],
    ids=[
        "under-the-count",
        "one-design",
        "an-unexplained-block",
        "already-dated",
        "not-a-digest",
        "not-toml",
        "no-cleared-table",
    ],
)
def test_a_clearance_that_cannot_move_the_law_is_refused_and_nothing_is_written(
    tmp_path: Path, clearance: str, said: str
) -> None:
    found = library(tmp_path)
    found.stage_clearance(LAW, clearance)
    assert said in refused_move(found)


def test_a_law_with_no_staged_clearance_is_refused(tmp_path: Path) -> None:
    found = library(tmp_path)
    assert "no staged clearance" in refused_move(found, "another_power")


def test_a_law_not_in_the_table_is_refused(tmp_path: Path) -> None:
    found = library(tmp_path)
    found.stage_clearance("missing_law", clearance_text())
    assert "not in the table" in refused_move(found, "missing_law")


def test_a_law_already_at_block_is_refused(tmp_path: Path) -> None:
    found = library(tmp_path)
    move(found)
    found.stage_clearance(LAW, clearance_text(audit_sha256="c" * 64))
    assert "already" in refused_move(found)


def test_a_move_without_a_person_s_name_is_refused(tmp_path: Path) -> None:
    found = library(tmp_path)
    before = found.state()
    assert "name" in refusal(lambda: attempt(found, by=""))
    assert found.state() == before


def test_a_law_id_that_is_not_a_plain_name_is_refused(tmp_path: Path) -> None:
    found = library(tmp_path)
    before = found.state()
    assert "plain" in refusal(lambda: attempt(found, "../laws"))
    assert found.state() == before
