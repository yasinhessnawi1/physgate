"""Tests of packets_identity.py (L5, L6, L7) on the instrument's own invented test corpus.

Run explicitly, in the run checkout: ``uv run --frozen pytest -q experiments/R-PG-01b``.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import Any

import pytest

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
sys.path.insert(0, str(HERE.parent.parent / "tests"))
sys.path.insert(0, str(HERE.parent.parent / "tests" / "unit" / "evaluation"))
import packets_identity as PI  # noqa: E402
from instrument_corpus import ARTEFACTS, SOURCE_ROWS, write_corpus  # noqa: E402


def _sheet_whole() -> dict[str, Any]:
    """The test sheet as a whole sheet gives it: every value as written, and notes."""
    rows = {k: dict(v) for k, v in SOURCE_ROWS.items()}
    for k, row in rows.items():
        if row["value"] is None:
            row["given"] = "a range as its authors wrote it"
        row["note"] = f"a note on {k}"
    return rows


def _build(tmp: Path, name: str, arm: str, **kw: Any) -> dict[str, Any]:
    corpus = write_corpus(tmp / f"corpus-{name}", sheet_indent=1, **kw)
    return PI.build(arm, corpus, tmp / "fixed-root")


def test_two_builds_of_one_design_set_are_byte_identical(tmp_path: Path) -> None:
    a, b = _build(tmp_path, "a", "I"), _build(tmp_path, "b", "I")
    assert a["packets"] == 2 * len(ARTEFACTS)
    assert {k: v["exact"] for k, v in a["per_packet"].items()} == {
        k: v["exact"] for k, v in b["per_packet"].items()
    }
    assert a["blindness_refused"] == 0


def test_a_whole_sheet_differs_only_where_l7_allows(tmp_path: Path) -> None:
    i = _build(tmp_path, "i", "I")
    f = _build(tmp_path, "f", "F", rows=_sheet_whole())
    for k, p in i["per_packet"].items():
        assert f["per_packet"][k]["exact"] != p["exact"]
        assert f["per_packet"][k]["normalised"] == p["normalised"]
        assert p["sentence_in_account"] == f["per_packet"][k]["sentence_in_account"] == 1
    found = PI.compare(i, f, i)
    assert found["L7_arm_F_differs_only_as_allowed"] == found["packets"]
    assert found["L5_arm_I_identical_to_8bc03fc"] == found["packets"]


def test_any_other_difference_is_not_set_aside(tmp_path: Path) -> None:
    i = _build(tmp_path, "i", "I")
    moved = [json.loads(json.dumps(a)) for a in ARTEFACTS]
    node = moved[0]["injected"]["nodes"][0]
    quantity = next(iter(node["quantities"]))
    node["quantities"][quantity]["value"] = node["quantities"][quantity]["value"] * 2
    f = _build(tmp_path, "f", "F", rows=_sheet_whole(), artefacts=tuple(moved))
    same = [
        k for k, p in i["per_packet"].items() if f["per_packet"][k]["normalised"] == p["normalised"]
    ]
    assert len(same) == 2 * len(ARTEFACTS) - 1


def test_a_sheet_that_tells_is_counted_as_a_refusal(tmp_path: Path) -> None:
    rows = _sheet_whole()
    first = next(iter(rows))
    rows[first]["note"] = "the answer key"
    f = _build(tmp_path, "f", "F", rows=rows)
    assert f["blindness_refused"] == 2 * len(ARTEFACTS)


def test_the_build_refuses_a_root_that_exists(tmp_path: Path) -> None:
    (tmp_path / "fixed-root").mkdir()
    with pytest.raises(SystemExit):
        _build(tmp_path, "a", "I")
