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
from real_domain_reviewers import (  # noqa: E402
    REPO_ROOT,
    all_artefacts,
    review_id,
    scripted_verdict,
    selected,
)

from physgate.knowledge.promote import KNOWLEDGE_ROOT  # noqa: E402
from physgate.reviewers.contract import issued_criteria  # noqa: E402
from physgate.reviewers.packet import SPEC_AS_ISSUED_NAME  # noqa: E402
from physgate.reviewers.rubric import load_rubric, not_evaluable_needs  # noqa: E402
from physgate.reviewers.verdict import Answered, judge  # noqa: E402

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


@pytest.mark.parametrize("role", ["electrical", "mechanical"])
@pytest.mark.parametrize("issued", [False, True])
def test_a_scripted_blocked_verdict_is_one_the_reviewer_s_check_takes(
    tmp_path: Path, role: str, issued: bool
) -> None:
    """A dry run's blocked verdict holds to the answer contract, with or without a specification.

    With no specification issued, the consistency line is met or unmet only, so the
    scripted review blocks on a Section 2 item instead of on that line.
    """
    read = tmp_path / "read"
    read.mkdir()
    rubric = load_rubric(REPO_ROOT / KNOWLEDGE_ROOT, role)
    (read / "rubric.md").write_text(rubric.text)
    spec = artefacts.ELECTRICAL_SPEC if role == "electrical" else artefacts.MECHANICAL_SPEC
    criteria = None
    if issued:
        (read / SPEC_AS_ISSUED_NAME).write_text(spec)
        criteria = issued_criteria(spec)
    answer = scripted_verdict(read, {"indicators": []}, "blocked")
    outcome = judge(
        answer,
        (),
        rubric.items,
        criteria=criteria,
        not_evaluable=not_evaluable_needs(role),
        issued=issued,
    )
    assert isinstance(outcome, Answered), outcome
    assert outcome.answer.verdict == "blocked"
