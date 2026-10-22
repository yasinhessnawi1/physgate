"""The sizing, integration and design reviewers are registered to review, never to admit a role.

Each of the three has a rubric rule (a criterion not evaluable always blocks) and its own
item prefixes, distinct from every other role's, so an item id in a verdict names its
rubric. None of that admits a session of the role: only the role register does. Integration
is registered, with its reading and its reviewer's promoted rubric; sizing is not yet, and
``design`` names the plan's reviewer, never a role. A run naming either is refused at the
role register whatever reviewer it brings. The generic model separation check is exercised
once, not per role.
"""

from __future__ import annotations

from types import SimpleNamespace

import pytest
from orch_helpers import make_config

from physgate.orchestrator.exceptions import ModelSeparationError, RoleNotRegisteredError
from physgate.orchestrator.loop import refuse_unregistered
from physgate.orchestrator.protocols import require_separate_models
from physgate.reviewers.rubric import ITEM_PREFIXES, SECTIONS, RubricItem, not_evaluable_needs

NEW = ("sizing", "integration", "design")
#: The evaluation's pins: implementers and decomposition on one model, reviewers on another.
IMPLEMENTER = "claude-opus-5-5"
REVIEWER = "claude-sonnet-5"


@pytest.mark.parametrize("role", NEW)
def test_a_criterion_not_evaluable_blocks_for_each_new_reviewer(role: str) -> None:
    assert not_evaluable_needs(role) == "blocking"


@pytest.mark.parametrize("role", NEW)
def test_each_new_reviewer_has_four_prefixes_an_item_id_can_carry(role: str) -> None:
    prefixes = ITEM_PREFIXES[role]
    assert len(prefixes) == len(SECTIONS) == 4
    for prefix, (_, section) in zip(prefixes, SECTIONS, strict=True):
        # The id an item of that section would carry is one the rubric's item model takes.
        assert RubricItem(id=f"{prefix}-1", section=section, title="t").id == f"{prefix}-1"


def test_no_two_roles_share_a_prefix() -> None:
    every = [p for prefixes in ITEM_PREFIXES.values() for p in prefixes]
    assert every, "the prefix table is empty"
    assert len(every) == len(set(every)), sorted(p for p in every if every.count(p) > 1)


@pytest.mark.parametrize("role", [r for r in NEW if r != "integration"])
def test_a_run_naming_an_unregistered_new_role_is_refused_whatever_reviewer_it_brings(
    role: str,
) -> None:
    base = make_config(gate_mode="off")
    models = base.models.model_copy(
        update={
            "roles": {**base.models.roles, role: IMPLEMENTER},
            "reviewers": {**base.models.reviewers, role: REVIEWER},
        }
    )
    config = base.model_copy(update={"models": models})
    reviewer = SimpleNamespace(model=REVIEWER)
    with pytest.raises(RoleNotRegisteredError) as refused:
        refuse_unregistered(config, None, {role: reviewer})
    assert role in refused.value.context["roles"]


def test_the_model_separation_check_takes_a_distinct_reviewer_and_refuses_the_same_model() -> None:
    # The generic check every role's review passes through, not a per-role refusal. The
    # design reviewer against the decomposition's model is refused in the run configuration,
    # and again at the review call once the plan review exists.
    require_separate_models(implementer=IMPLEMENTER, reviewer=REVIEWER)
    with pytest.raises(ModelSeparationError):
        require_separate_models(implementer=IMPLEMENTER, reviewer=IMPLEMENTER)
