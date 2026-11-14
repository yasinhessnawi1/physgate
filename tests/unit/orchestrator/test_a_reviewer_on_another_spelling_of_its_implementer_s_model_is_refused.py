"""A reviewer on another spelling of its implementer's model is refused wherever the check runs.

One model has several names: a dated release (``-20261001``, or ``@20261001`` as one provider
writes it), a provider's prefix and version suffix (``us.anthropic.…-v1:0``), the long-context
variant (``[1m]``). Model separation compares the names with those taken off, so a judge on any
spelling of the model it judges is refused (ARCH-060). The configuration's model strings admit the
dated and prefixed forms; a reviewer's own name, or a model a stream shows answering, may be any.
"""

from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest
from loop_fakes import Rig, plan
from orch_helpers import make_config
from pydantic import ValidationError

from physgate import roles
from physgate.orchestrator.exceptions import ModelSeparationError
from physgate.orchestrator.loop import refuse_unregistered
from physgate.orchestrator.protocols import require_separate_models
from physgate.orchestrator.run_config import ModelStrings, RunConfig

MODEL = "claude-opus-5-5"
#: Spellings a run's configuration admits as model strings.
PINNED = [f"{MODEL}-20261001", f"us.anthropic.{MODEL}-20261001", f"global.anthropic.{MODEL}"]
#: Every spelling, including those only a reviewer's own name or a stream can carry.
EVERY = [*PINNED, f"{MODEL}@20261001", f"eu.anthropic.{MODEL}-20261001-v1:0", f"{MODEL}[1m]"]


@pytest.mark.parametrize("spelling", EVERY)
def test_the_check_refuses_every_spelling_of_one_model(spelling: str) -> None:
    with pytest.raises(ModelSeparationError):
        require_separate_models(implementer=MODEL, reviewer=spelling)
    with pytest.raises(ModelSeparationError):
        require_separate_models(implementer=spelling, reviewer=MODEL)


@pytest.mark.parametrize(
    "other", ["claude-sonnet-5", "claude-opus-5-5-mini", "claude-opus-5", "claude-opus-5-6"]
)
def test_the_check_passes_another_model(other: str) -> None:
    require_separate_models(implementer=MODEL, reviewer=other)


def _config(name: str, implementer: str, reviewer: str) -> RunConfig:
    base = make_config(gate_mode="off")
    models = base.models.model_copy(
        update={"roles": {name: implementer}, "reviewers": {name: reviewer}}
    )
    return base.model_copy(update={"models": models})


@pytest.mark.parametrize("spelling", PINNED)
def test_the_loop_s_configuration_check_refuses_a_reviewer_on_a_dated_spelling(
    spelling: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setitem(roles.ROLES, "sizing", roles.SIZING)
    same: Any = SimpleNamespace(model=spelling)
    with pytest.raises(ModelSeparationError):
        refuse_unregistered(_config("sizing", MODEL, spelling), None, {"sizing": same})


@pytest.mark.parametrize("spelling", PINNED)
def test_the_call_time_check_refuses_a_reviewer_on_a_dated_spelling_of_the_recorded_model(
    tmp_path: Path, spelling: str
) -> None:
    rig = Rig(tmp_path)
    loop = rig.open()
    loop.start(plan("s1"))
    # The record names the rig's implementer; the caller's configuration names another, and the
    # reviewer is on a dated spelling of the recorded one.
    recorded = loop.config.models.roles["electrical"]
    loop.config = make_config(
        os_layer_absent="allow",
        reviewers="paired",
        skills="on",
        hooks="on",
        ablation=False,
        design_review="off",
        parts_on_hand="off",
        models=ModelStrings(
            decomposition="claude-fable-5",
            roles={"electrical": "claude-haiku-4-5"},
            reviewers={"electrical": f"{recorded}-20261001"},
        ),
    )
    rig.reviewer.model = f"{recorded}-20261001"
    with pytest.raises(ModelSeparationError):
        loop.run()
    loop.close()
    assert rig.reviewer.seen == []


@pytest.mark.parametrize("spelling", PINNED)
def test_the_configuration_refuses_a_design_reviewer_on_a_dated_spelling_of_the_decomposition(
    spelling: str,
) -> None:
    with pytest.raises(ValidationError, match="decomposition"):
        ModelStrings(
            decomposition=MODEL,
            roles={"control": "claude-sonnet-5"},
            reviewers={"control": "claude-fable-5", "design": spelling},
        )


# --- every spelling the configuration's model strings admit -------------------------------------

#: The decorations a model string can carry that name the same model, each in the alphabet the
#: configuration admits (``[a-z0-9._/-]``): a provider's path, a region and vendor prefix, the
#: version written with dots, and a release, alias or provider's version suffix.
PATHS = ["", "anthropic/", "bedrock/", "bedrock/converse/", "vertex_ai/", "openrouter/anthropic/"]
PREFIXES = ["", "anthropic.", "us.anthropic.", "global.anthropic."]
VERSIONS = ["claude-opus-5-5", "claude-opus-5.5"]
SUFFIXES = ["", "-20261001", "_20261001", ".20261001", "-latest", "-v1", "-20261001-v1"]
ADMITTED = [
    f"{path}{prefix}{version}{suffix}"
    for path in PATHS
    for prefix in PREFIXES
    for version in VERSIONS
    for suffix in SUFFIXES
]


def _admitted(spelling: str) -> bool:
    try:
        ModelStrings.model_validate(
            {
                "decomposition": spelling,
                "roles": {},
                "reviewers": {},
            }
        )
    except ValidationError:
        return False
    return True


def test_every_decorated_spelling_is_one_the_configuration_admits() -> None:
    refused = [s for s in ADMITTED if not _admitted(s)]
    assert refused == [], f"not model strings, so not this set: {refused}"


@pytest.mark.parametrize("spelling", ADMITTED)
def test_the_check_refuses_every_admitted_spelling_of_one_model(spelling: str) -> None:
    for implementer, reviewer in ((MODEL, spelling), (spelling, MODEL)):
        try:
            require_separate_models(implementer=implementer, reviewer=reviewer)
        except ModelSeparationError:
            continue
        msg = f"{reviewer} judged {implementer}"
        raise AssertionError(msg)
