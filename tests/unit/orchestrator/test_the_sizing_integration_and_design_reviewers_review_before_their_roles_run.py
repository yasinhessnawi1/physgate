"""The sizing, integration and design reviewers are registered to review, never to admit a role.

Each of the three has a rubric rule (a criterion not evaluable always blocks, as its
verdict policy states) and its own item prefixes, distinct from every other role's, so an
item id in a verdict names its rubric. None of that admits a session of the role: a run
naming one is refused at the role register whatever reviewer it brings, and a reviewer on
the implementer's model string is refused for each, the design reviewer's implementer
being the decomposition.
"""

from __future__ import annotations

import re
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


def test_no_prefix_of_one_role_reads_as_an_item_of_another() -> None:
    # A one-letter prefix followed by digits must never match a two-letter one's ids.
    owners = {p: role for role, prefixes in ITEM_PREFIXES.items() for p in prefixes}
    for prefix in owners:
        for other in owners:
            if other != prefix:
                assert not re.fullmatch(rf"{prefix}-?[0-9]+", f"{other}-1"), (prefix, other)


@pytest.mark.parametrize("role", NEW)
def test_a_run_naming_a_new_role_is_refused_whatever_reviewer_it_brings(role: str) -> None:
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
        refuse_unregistered(config, None, {role: reviewer})  # type: ignore[dict-item]
    assert role in refused.value.context["roles"]


@pytest.mark.parametrize("role", NEW)
def test_a_reviewer_on_the_implementer_s_model_is_refused_for_each_new_role(role: str) -> None:
    config = make_config(
        models=make_config().models.model_copy(
            update={
                "decomposition": IMPLEMENTER,
                "roles": {role: IMPLEMENTER},
                "reviewers": {role: REVIEWER},
            }
        )
    )
    # The design reviewer judges the plan, so its implementer is the decomposition.
    implementer = config.models.decomposition if role == "design" else config.models.roles[role]
    require_separate_models(implementer=implementer, reviewer=config.models.reviewers[role])
    with pytest.raises(ModelSeparationError):
        require_separate_models(implementer=implementer, reviewer=implementer)
