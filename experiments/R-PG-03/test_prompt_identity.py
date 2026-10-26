"""Tests of prompt_identity.py (§3.3): one packet per role, built with no session, compared.

Run explicitly, from the repository root: ``uv run pytest -q experiments/R-PG-03``.

The builds run at this checkout's code, as the run's builds run at R and R_K; a build at another
tree is the same command under that tree's project (``launch.sh`` runs them).
"""

from __future__ import annotations

import copy
import json
import os
import sys
import tempfile
from pathlib import Path
from typing import Any

import pytest

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
import prompt_identity as pi  # noqa: E402

#: One fixed review root for every build, as the launch builds every packet at one fixed path:
#: each build removes it when it is done. Outside every checkout, no telltale word in its path.
FIXED_ROOT = (
    Path(tempfile.mkdtemp(prefix="rp3pi-", dir=os.environ.get("RP3_TEST_ROOTS", "/tmp"))) / "r"
)


def root(name: str) -> Path:
    """The fixed root (``name`` only documents the build)."""
    del name
    return FIXED_ROOT


@pytest.fixture(scope="module")
def built(tmp_path_factory: pytest.TempPathFactory) -> dict[str, Any]:
    base = tmp_path_factory.mktemp("identity")
    facts = pi.write_test_corpus(base / "corpus")
    return {
        "facts": facts,
        "A2": pi.build("A2", base / "corpus", root("a")),
        "B": pi.build("B", base / "corpus", root("b")),
        "base": base,
    }


def test_the_test_design_reaches_every_role(built: dict[str, Any]) -> None:
    assert built["facts"]["roles"] == ["control", "electrical", "firmware", "mechanical"]
    assert built["A2"]["roles"] == built["facts"]["roles"]


def test_the_same_tree_twice_differs_in_nothing(built: dict[str, Any], tmp_path: Path) -> None:
    again = pi.build("A2", built["base"] / "corpus", root("c"))
    found = pi.compare(built["A2"], again)
    assert (
        found["holds"]
        and found["differences"] == []
        and found["exact_differences_explained_by_the_sentence"] == []
    )


def test_the_generalist_s_rubric_differs_from_the_paired_and_is_reported(
    built: dict[str, Any],
) -> None:
    b = {**built["B"], "arm": "A2"}
    found = pi.compare(built["A2"], b)
    assert not found["holds"] and any("the rubric" in d for d in found["differences"])


def test_a_difference_in_the_sheet_s_sentence_alone_is_allowed_and_any_other_is_not(
    built: dict[str, Any],
) -> None:
    other = copy.deepcopy(built["A2"])
    for r in other["per_role"].values():
        r["exact"]["account"] = "0" * 64  # the account's bytes moved, its normalised form did not
    found = pi.compare(built["A2"], other)
    assert found["holds"] and len(found["exact_differences_explained_by_the_sentence"]) == 4
    worse = copy.deepcopy(built["A2"])
    worse["per_role"]["control"]["normalised"]["read/rubric.md"] = "0" * 64
    found = pi.compare(built["A2"], worse)
    assert not found["holds"] and found["differences"] == ["control: read/rubric.md"]


def test_a_loader_s_refusal_is_recorded_and_the_older_form_is_the_same_rows_numbers_only(
    built: dict[str, Any], tmp_path: Path
) -> None:
    sheet = json.loads((built["base"] / "corpus" / "sources.json").read_text())
    pi.older_sheet(built["base"] / "corpus", tmp_path / "older")
    older = json.loads((tmp_path / "older" / "sources.json").read_text())
    assert list(older["rows"]) == list(sheet["rows"])
    assert all(set(r) == {"quantity", "value", "unit", "url"} for r in older["rows"].values())
    refused = pi.compare({"arm": "A2", "refused_by_the_loader": "x"}, built["A2"])
    assert not refused["holds"]


def test_a_review_root_that_exists_is_refused(built: dict[str, Any], tmp_path: Path) -> None:
    there = Path(tempfile.mkdtemp(prefix="rp3pj-", dir="/tmp")) / "r"
    there.mkdir()
    with pytest.raises(SystemExit):
        pi.build("A2", built["base"] / "corpus", there)
