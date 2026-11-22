"""Every gate result names the law table that judged it, by content.

The catalogue digest already names every kind, name and relation; the law table decides what
the eighth check judges, so the digest covers it too. It is taken over what the table says,
never over its bytes: a comment or a reflowed line moves nothing, and any change to a law, its
status, or the set of laws moves it. Each law record carries the sha256 of the file's bytes as
well, the way a magnitude record carries its bounds table's, and the gate built from a table
names that table's digest on every result.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from law_fixtures import cleared, load, sound_law

from physgate.gate import catalogue


def digest(root: Path, laws: list[dict[str, Any]], **kwargs: Any) -> str:
    return str(catalogue.catalogue_digest(load(root, laws, **kwargs)))


def test_a_comment_moves_the_file_s_digest_and_not_the_catalogue_s(tmp_path: Path) -> None:
    first = load(tmp_path / "a", [sound_law()], comment="one wording")
    second = load(tmp_path / "b", [sound_law()], comment="another wording")
    assert first.sha256 != second.sha256
    assert catalogue.catalogue_digest(first) == catalogue.catalogue_digest(second)


def test_any_change_to_a_law_moves_the_digest(tmp_path: Path) -> None:
    before = digest(tmp_path / "before", [sound_law()])
    changes = {
        "statement": digest(tmp_path / "s", [sound_law(statement="P is V times I at DC")]),
        "expression": digest(tmp_path / "e", [sound_law(expression="V * I == P")]),
        "idealisation": digest(tmp_path / "i", [sound_law(idealisation="steady DC")]),
        "status": digest(tmp_path / "b", [sound_law(status="block", cleared=cleared())]),
        "a law added": digest(tmp_path / "a", [sound_law(), sound_law("cell_power")]),
        "no law": digest(tmp_path / "n", []),
    }
    for change, after in changes.items():
        assert after != before, change
    assert len(set(changes.values())) == len(changes)


def test_the_order_of_the_rows_in_the_file_does_not_move_it(tmp_path: Path) -> None:
    one = digest(tmp_path / "a", [sound_law("a_law"), sound_law("b_law")])
    two = digest(tmp_path / "b", [sound_law("b_law"), sound_law("a_law")])
    assert one == two


def test_the_digest_still_covers_the_catalogue_itself(tmp_path: Path, monkeypatch: Any) -> None:
    table = load(tmp_path, [sound_law()])
    before = catalogue.catalogue_digest(table)
    monkeypatch.setattr(catalogue, "QUALIFIERS", (*catalogue.QUALIFIERS, "_peak"))
    assert catalogue.catalogue_digest(table) != before
