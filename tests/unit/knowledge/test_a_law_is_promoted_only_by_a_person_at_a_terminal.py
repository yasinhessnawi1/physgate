"""A law enters the table, or moves to ``block``, only when a person at a terminal runs it.

The law table is what the physics gate refuses designs by, so the step that writes it is a
person's and never a session's. Both entries, the promotion of a staged card and the move to
``block``, refuse before reading anything unless standard input is a real terminal, and so does
the command that runs them. These tests prove the refusal the way a session meets it: standard
input a pipe or a file, never a terminal. Nothing here stands in a terminal.

A refusal leaves everything as it was: the table, the promotion record and the staged card.
"""

from __future__ import annotations

import io
from collections.abc import Callable
from pathlib import Path

import pytest
from law_cards import FIRST, Library, card_row, card_text, clearance_text, law_promotion, library

from physgate.cli import main


def refusal(call: Callable[[], object]) -> str:
    """The promotion's refusal, as text; an assertion fails if it went ahead."""
    module = law_promotion()
    try:
        call()
    except module.PromotionError as exc:
        return f"{exc} {exc.context}"
    raise AssertionError("the promotion went ahead, where a refusal was expected")


def staged(tmp_path: Path) -> Library:
    """A library with one sound card staged, so only the terminal can refuse it."""
    found = library(tmp_path)
    found.stage(FIRST, card_text(card_row()))
    return found


def promoted_once(tmp_path: Path) -> Library:
    """A library whose table already holds the sound law at ``warn``, and its clearance staged."""
    module = law_promotion()
    found = staged(tmp_path)
    module._apply_law(FIRST, by="a person", on=None, notice=None, **found.kwargs())
    found.stage_clearance("electrical_power", clearance_text())
    return found


@pytest.mark.parametrize("stdin", [io.StringIO("yes\n"), io.StringIO("")], ids=["pipe", "empty"])
def test_a_promotion_refuses_when_standard_input_is_not_a_terminal(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, stdin: io.StringIO
) -> None:
    found = staged(tmp_path)
    before = found.state()
    monkeypatch.setattr("sys.stdin", stdin)
    module = law_promotion()
    why = refusal(lambda: module.promote_law(FIRST, by="a person", **found.kwargs()))
    assert "non-interactively" in why
    assert found.state() == before
    assert found.card(FIRST).is_file(), "the staged card was removed by a refused promotion"


def test_a_move_to_block_refuses_when_standard_input_is_not_a_terminal(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    found = promoted_once(tmp_path)
    before = found.state()
    monkeypatch.setattr("sys.stdin", io.StringIO("yes\n"))
    module = law_promotion()
    why = refusal(lambda: module.block_law("electrical_power", by="a person", **found.kwargs()))
    assert "non-interactively" in why
    assert found.state() == before
    assert found.clearance("electrical_power").is_file()


def test_the_refusal_comes_before_anything_is_read(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    # No card, no table: a session learns nothing about either from the refusal it gets.
    monkeypatch.setattr("sys.stdin", io.StringIO(""))
    module = law_promotion()
    for call in (
        lambda: module.promote_law(FIRST, by="a person", **Library(tmp_path).kwargs()),
        lambda: module.block_law("electrical_power", by="a person", **Library(tmp_path).kwargs()),
    ):
        assert "non-interactively" in refusal(call)
    assert not (tmp_path / "knowledge").exists()


def run(argv: list[str]) -> int:
    """The top-level command's exit code; a usage error is a code, not a raised exit."""
    try:
        return main(argv)
    except SystemExit as exc:
        return int(exc.code or 0)


@pytest.mark.parametrize("action", ["promote-law", "block-law"])
def test_each_command_is_registered_and_needs_its_argument(action: str) -> None:
    assert run(["knowledge", action, "--help"]) == 0, f"knowledge {action} is not a command"
    assert run(["knowledge", action]) == 2  # argparse's usage error: the argument is required


def test_the_promote_law_command_refuses_without_a_terminal_and_says_why(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    monkeypatch.chdir(tmp_path)
    found = staged(Path("."))
    before = found.state()
    monkeypatch.setattr("sys.stdin", io.StringIO("yes\n"))
    code = run(["knowledge", "promote-law", FIRST, "--by", "a person"])
    out = capsys.readouterr().out
    assert code == 1
    assert "refused" in out and "non-interactively" in out
    assert found.state() == before and found.card(FIRST).is_file()


def test_the_block_law_command_refuses_without_a_terminal_and_says_why(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    monkeypatch.chdir(tmp_path)
    found = promoted_once(Path("."))
    before = found.state()
    monkeypatch.setattr("sys.stdin", io.StringIO("yes\n"))
    code = run(["knowledge", "block-law", "electrical_power", "--by", "a person"])
    out = capsys.readouterr().out
    assert code == 1
    assert "refused" in out and "non-interactively" in out
    assert found.state() == before and found.clearance("electrical_power").is_file()
