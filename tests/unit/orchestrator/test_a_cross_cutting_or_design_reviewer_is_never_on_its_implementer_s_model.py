"""A paired reviewer is on another model than what it judges, for the new reviewers too.

Sizing and integration are held at the run's start like every domain role: a reviewer
pinned to the implementer's model string is refused (ARCH-060). The design reviewer
judges the plan, whose implementer is the decomposition, so a run configuration that
pins it to the decomposition's model is refused when it is built, before any call is
made.
"""

from __future__ import annotations

from types import SimpleNamespace
from typing import Any

import pytest
from orch_helpers import make_config
from pydantic import ValidationError

from physgate import roles
from physgate.orchestrator.exceptions import ModelSeparationError
from physgate.orchestrator.loop import refuse_unregistered
from physgate.orchestrator.run_config import ModelStrings, RunConfig

#: The evaluation's pins: implementers and decomposition on one model, reviewers on another.
IMPLEMENTER = "claude-opus-5-5"
REVIEWER = "claude-sonnet-5"
#: A decomposition pinned apart from every role, so a check held against a role's model
#: instead of the decomposition's is told apart from the right one.
DECOMPOSITION = "claude-fable-5"


def _config(name: str, reviewer: str) -> RunConfig:
    base = make_config(gate_mode="off")
    models = base.models.model_copy(
        update={"roles": {name: IMPLEMENTER}, "reviewers": {name: reviewer}}
    )
    return base.model_copy(update={"models": models})


@pytest.mark.parametrize("name", ["sizing", "integration"])
def test_a_reviewer_on_the_implementers_model_is_refused_for_both_roles(
    name: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    # Registered here as they will be once their content ships, so the check after the
    # register's is the one exercised.
    monkeypatch.setitem(roles.ROLES, name, getattr(roles, name.upper()))
    other: Any = SimpleNamespace(model=REVIEWER)
    refuse_unregistered(_config(name, REVIEWER), None, {name: other})
    same: Any = SimpleNamespace(model=IMPLEMENTER)
    with pytest.raises(ModelSeparationError):
        refuse_unregistered(_config(name, IMPLEMENTER), None, {name: same})


@pytest.mark.parametrize("decomposition", [IMPLEMENTER, DECOMPOSITION])
def test_a_design_reviewer_on_the_decomposition_model_is_refused(decomposition: str) -> None:
    with pytest.raises(ValidationError, match="decomposition"):
        ModelStrings(
            decomposition=decomposition,
            roles={"control": IMPLEMENTER, "firmware": IMPLEMENTER},
            reviewers={"control": REVIEWER, "firmware": REVIEWER, "design": decomposition},
        )


def test_a_design_reviewer_on_a_role_s_model_but_not_the_decomposition_s_is_accepted() -> None:
    # The design reviewer judges the plan, not a role's work: only the decomposition's
    # model is its implementer's.
    models = ModelStrings(
        decomposition=DECOMPOSITION,
        roles={"control": IMPLEMENTER, "firmware": REVIEWER},
        reviewers={"control": REVIEWER, "firmware": IMPLEMENTER, "design": IMPLEMENTER},
    )
    assert models.reviewers["design"] == IMPLEMENTER


def test_a_design_reviewer_on_another_model_is_accepted() -> None:
    models = ModelStrings(
        decomposition=IMPLEMENTER,
        roles={"control": IMPLEMENTER},
        reviewers={"control": REVIEWER, "design": REVIEWER},
    )
    assert models.reviewers["design"] == REVIEWER


def test_a_run_with_no_design_reviewer_is_unchanged() -> None:
    # Every run recorded so far pins none; the check asks nothing of them.
    models = ModelStrings(
        decomposition=IMPLEMENTER, roles={"control": IMPLEMENTER}, reviewers={"control": REVIEWER}
    )
    assert "design" not in models.reviewers


def test_the_whole_run_configuration_refuses_it_too() -> None:
    with pytest.raises(ValidationError, match="decomposition"):
        make_config(
            models={
                "decomposition": DECOMPOSITION,
                "roles": {"control": IMPLEMENTER},
                "reviewers": {"control": REVIEWER, "design": DECOMPOSITION},
            }
        )
