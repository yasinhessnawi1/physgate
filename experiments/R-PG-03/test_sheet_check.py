"""Tests of sheet_check.py (§2.4, §2.5 item 5): the one-word edit, §2.4's call, its outcomes.

Run explicitly, from the repository root: ``uv run pytest -q experiments/R-PG-03``.

The edit and the outcomes are tested on invented tables; the last test re-runs §2.4's call on
R-PG-02's frozen table and the tuning set's sheet, by script, and reads counts and digests only.
"""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path
from typing import Any

import pytest

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
import common  # noqa: E402
import sheet_check as sc  # noqa: E402

HEAD = (
    "| Row | Quantity | Value | Unit | Source URL | Retrieved | Note |\n"
    "|---|---|---|---|---|---|---|\n"
)


def table(*rows: str) -> bytes:
    return (HEAD + "".join(r + "\n" for r in rows)).encode()


ROW = (
    "| R6.05 | a delay | 5 | ms | https://example.invalid/a | 2026-10-01 "
    "| it answered within the bound |"
)


def test_the_edit_changes_one_word_of_row_r6_05_s_note_and_nothing_else() -> None:
    before = table("| R1.01 | a mass | 1 | g | https://example.invalid/b | 2026-10-01 | - |", ROW)
    after = sc.edit_table(before)
    assert after == before.replace(b"answered", b"responded")
    assert sc.word_diff(before, after) == [{"kind": "replace", "removed": 1, "added": 1}]


@pytest.mark.parametrize(
    "rows",
    [
        (ROW, ROW),
        ("| R1.01 | a mass | 1 | g | https://example.invalid/b | 2026-10-01 | answered |", ROW),
        (ROW.replace("it answered", "it answered, answered"),),
        (ROW.replace("answered", "replied"),),
        ("| R6.05 | a delay | 5 | ms | https://example.invalid/a | answered |",),
    ],
    ids=["the-row-twice", "the-word-elsewhere", "the-word-twice", "no-word", "six-cells"],
)
def test_an_edit_that_is_not_exactly_one_word_of_one_note_is_refused(rows: tuple[str, ...]) -> None:
    with pytest.raises(sc.RefusedError):
        sc.edit_table(table(*rows))


def test_the_word_level_diff_counts_every_change() -> None:
    assert sc.word_diff(b"a b c", b"a b c") == []
    assert len(sc.word_diff(b"a b c d", b"a x c y")) == 2


def found(counts: dict[str, Any] | None = None, refused: str | None = None) -> dict[str, Any]:
    c = {**common.PROBE_COUNTS, "sha256": common.PROBE_SHEET_SHA256, **(counts or {})}
    return {"counts": c} if refused is None else {"refused": refused}


def test_the_outcome_follows_section_2_4_s_procedure() -> None:
    assert sc.outcome(found()) == "recorded"
    assert sc.outcome(found({"sha256": "0" * 64})) == "digest differs"
    assert sc.outcome(found({"notes": 129})) == "not used"
    assert sc.outcome(found({"telltale_words": 1})) == "not used"
    assert sc.outcome(found(refused="the converter refused")) == "not used"


def test_the_converter_s_printed_counts_are_read_as_names_and_numbers() -> None:
    printed = (
        "rows 163 number 101 given 111 given-only 62 empty 0 notes 130 references 13 "
        "prose-dropped 9 named-dropped 1\nkept 101 changed 0\n"
    )
    got = sc.printed_counts(printed)
    assert got["rows"] == 163 and got["prose-dropped"] == 9 and got["changed"] == 0


def test_the_call_is_the_criteria_s_with_its_named_line_digest() -> None:
    argv = sc.converter_argv(Path("/r"), Path("/t.md"), Path("/o.json"), Path("/k.json"))
    assert argv[1:] == [
        "/r/scripts/parts_sheet_sources.py",
        "/t.md",
        "/o.json",
        "--keep-values-from",
        "/k.json",
        "--prose",
        "drop",
        "--drop-prose-line-sha256",
        "4c7844dc7a445b5e8628c27a5ae14b526275b2d45270d0e4ff571fb4e1dd7a8c",
    ]


def test_the_sheet_counts_are_the_probe_s_measures() -> None:
    sheet = json.dumps(
        {
            "label": "x",
            "rows": {
                "R1.01": {"quantity": "q", "value": 1, "unit": "V", "url": "u", "note": "n"},
                "R1.02": {
                    "quantity": "q",
                    "value": None,
                    "unit": None,
                    "url": "u",
                    "given": "1-2 V",
                },
                "R1.03": {"quantity": "q", "value": 2, "unit": "V", "url": "u", "given": "2.0 V"},
            },
        }
    ).encode()
    got = sc.sheet_counts(sheet)
    assert got["rows"] == 3 and got["rows_with_a_number"] == 2 and got["rows_with_given"] == 2
    assert got["rows_with_given_only"] == 1 and got["rows_with_neither"] == 0 and got["notes"] == 1


def test_a_byte_difference_is_given_by_line_numbers_only() -> None:
    got = sc.byte_difference(b"a\nb\nc\n", b"a\nB\nc\n")
    assert got["lines_differing"] == [2] and got["lines_differing_count"] == 1


def test_a_corpus_whose_table_is_not_the_edited_one_is_refused(tmp_path: Path) -> None:
    (tmp_path / "c").mkdir()
    (tmp_path / "c" / "parts_sheet.md").write_bytes(table(ROW))
    with pytest.raises(sc.RefusedError, match="not the edited"):
        sc.corpus_check(common.REPO, tmp_path / "c", "0" * 64, tmp_path / "out")


def test_nothing_is_written_over(tmp_path: Path) -> None:
    (tmp_path / "out").mkdir()
    with pytest.raises(sc.RefusedError, match="exists"):
        sc.convert(common.REPO, tmp_path / "out")


def test_section_2_4_s_call_gives_the_probe_s_sheet_at_this_checkout(tmp_path: Path) -> None:
    done = subprocess.run(
        [
            sys.executable,
            "-I",
            str(HERE / "sheet_check.py"),
            "convert",
            "--into",
            str(tmp_path / "s"),
        ],
        capture_output=True,
        text=True,
        check=False,
        cwd=common.REPO,
    )
    got = json.loads(done.stdout.splitlines()[-1])
    assert done.returncode == 0, got
    assert got["fresh-v2"]["outcome"] == "recorded"
    assert got["fresh-v2"]["counts"]["sha256"] == common.PROBE_SHEET_SHA256
    assert got["fresh_v1c_sheet_is_fresh_v2_s"] and got["fresh_v1c_table_is_fresh_v2_s"]
    assert got["table"]["edited_sha256"] == common.EDITED_TABLE_SHA256


def test_a_corpus_s_sheet_is_held_to_sheet_filled_s_digest(tmp_path: Path) -> None:
    corpus = tmp_path / "c"
    corpus.mkdir()
    import fixture as fx

    (corpus / common.TABLE_NAME).write_bytes(fx.edited_table())
    (corpus / common.SHEET_NAME).write_text("{}")
    sc.corpus_check(common.REPO, corpus, "0" * 64, tmp_path / "first")
    (corpus / common.SHEET_NAME).write_bytes((tmp_path / "first" / common.SHEET_NAME).read_bytes())
    filled = common.sha256_file(corpus / common.SHEET_NAME)
    assert sc.corpus_check(common.REPO, corpus, filled, tmp_path / "o1")["holds"]
    assert not sc.corpus_check(common.REPO, corpus, "0" * 64, tmp_path / "o2")["holds"]


def test_a_digest_that_differs_is_recorded_only_with_its_byte_level_difference(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    # §2.4: every count equal, the digest different: the difference is printed and published.
    monkeypatch.setattr(common, "PROBE_SHEET_SHA256", "0" * 64)
    got = sc.convert(common.REPO, tmp_path / "s")
    assert got["fresh-v2"]["outcome"] == "digest differs"
    assert not got["holds"] and "--reference" in got["refused"]
