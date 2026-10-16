"""The validation driver can re-run some of its reviews, named, and never a name it lacks.

After the six validation reviews, three did not match their expectation, and only those
three are reviewed again under a new criteria stamp. The driver takes them by name: it
makes and reviews those artefacts and no other, in its own fixed order, and refuses a name
it does not hold or an empty selection, before anything is made. The electrical
consistent revision is now expected ``blocked``: the thermal records it leaves out need
inputs the given design does not hold, and the rubric blocks on a missing input.
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "integration" / "orchestrator"))
import domain_review_artefacts as artefacts  # noqa: E402
from real_domain_reviewers import all_artefacts, review_id, selected  # noqa: E402

RERUN = ("e-consistent", "m-consistent", "m-attempt")


def test_no_selection_is_all_six_in_the_driver_s_order() -> None:
    assert selected(None) == (*artefacts.REVISIONS, *artefacts.ATTEMPTS)


def test_a_selection_keeps_the_driver_s_order() -> None:
    assert selected("m-attempt,e-consistent,m-consistent") == RERUN


@pytest.mark.parametrize(
    "only", ["", "e-consistent,", "e-consistent,nothing", "e-consistent,e-consistent"]
)
def test_an_unknown_empty_or_repeated_name_is_refused(only: str) -> None:
    with pytest.raises(ValueError, match="review"):
        selected(only)


def test_only_the_named_artefacts_are_made(tmp_path: Path) -> None:
    made = all_artefacts(tmp_path, RERUN)
    assert [aid for aid, _ in made] == list(RERUN)
    assert [a.subtask_id for _, a in made] == [review_id(aid) for aid in RERUN]
    assert sorted(p.name for p in (tmp_path / "made").iterdir()) == sorted(
        review_id(aid) for aid in RERUN
    )


def test_the_electrical_consistent_revision_is_expected_blocked() -> None:
    verdict, deciding, _ = artefacts.EXPECTED["e-consistent"]
    assert (verdict, deciding) == ("blocked", ())
    # The other five are as the first stamp set them.
    assert {aid: e[0] for aid, e in artefacts.EXPECTED.items() if aid != "e-consistent"} == {
        "e-with-error": "reject",
        "m-consistent": "reject",
        "m-with-error": "reject",
        "e-attempt": "blocked",
        "m-attempt": "blocked",
    }
