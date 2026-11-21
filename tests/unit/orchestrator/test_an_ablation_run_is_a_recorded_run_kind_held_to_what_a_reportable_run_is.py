"""An ablation run is a recorded run kind beside the reportable run, and is never reportable.

ARCH-140: a run measured with a component switched off is held to every rule a reportable run
is held to, so its numbers can be read beside one. It names itself with ``ablation``, a required
parameter with no default, recorded like the flags; a run recorded before the field existed was
none, and reads so with its digest unchanged. A run that names both kinds is refused. An
ablation run starts only from a clean checkout with a commit, inside the OS layer and with no
allowance for its absence, with ``network: none`` enforced where it asks for it, recording queue
decisions and its plan's review.
"""

from __future__ import annotations

import json
from collections.abc import Callable
from pathlib import Path
from typing import Any

import pytest
from design_review_rig import outcome_of
from orch_helpers import CLEAN_HARNESS, make_config

from physgate.evaluation import requirements
from physgate.orchestrator.requirements import RunFacts
from physgate.orchestrator.run_config import (
    HarnessState,
    ModelStrings,
    RunConfig,
    load_run_config,
    write_run_config,
)
from physgate.oslayer.probe import Absent, Present

PRESENT = Present(mechanism="seatbelt", claude_version="2.1.301")
ABSENT = Absent(reason="Linux: bubblewrap (bwrap) is not on the session's search path")
DIRTY = HarnessState(commit="c" * 40, clean=False, uncommitted_sha256="d" * 64)
PINNED = ModelStrings(
    decomposition="claude-sonnet-5",
    roles={"electrical": "claude-sonnet-5"},
    reviewers={"electrical": "claude-opus-5-5", "design": "claude-opus-5-5"},
)
#: A run the evaluation takes: every flag as every run has had it, its plan's review recorded.
MEASURED: dict[str, Any] = {
    "reviewers": "paired",
    "skills": "on",
    "hooks": "on",
    "harness": CLEAN_HARNESS,
    "models": PINNED,
    "design_review": "observe",
    "os_layer": PRESENT,
}


def _config(**fields: Any) -> Any:  # noqa: ANN401 - a configuration, or why there is none
    return outcome_of(lambda: make_config(**(MEASURED | {"ablation": True} | fields)))


def test_ablation_is_a_required_recorded_parameter_with_no_default(tmp_path: Path) -> None:
    field = RunConfig.model_fields.get("ablation")
    assert field is not None, "the run's configuration has no ablation"
    assert field.is_required() and field.annotation is bool
    ablation, ordinary = _config(), _config(ablation=False)
    assert isinstance(ablation, RunConfig), ablation
    assert isinstance(ordinary, RunConfig), ordinary
    assert json.loads(ablation.canonical_bytes())["ablation"] is True
    assert "ablation" not in json.loads(ordinary.canonical_bytes())
    assert ablation.sha256() != ordinary.sha256()
    write_run_config(tmp_path / "ablation.json", ablation)
    write_run_config(tmp_path / "ordinary.json", ordinary)
    assert load_run_config(tmp_path / "ablation.json").ablation is True
    before = load_run_config(tmp_path / "ordinary.json")
    assert before.ablation is False and before.sha256() == ordinary.sha256()


def test_a_run_is_never_both_an_ablation_and_reportable() -> None:
    both = _config(reportable=True)
    assert not isinstance(both, RunConfig), both
    assert "an ablation run is never reportable" in str(both)
    assert isinstance(_config(ablation=False, reportable=True), RunConfig)
    assert isinstance(_config(), RunConfig)


@pytest.mark.parametrize(
    "harness", [DIRTY, HarnessState(commit=None, clean=False, uncommitted_sha256=None)]
)
def test_an_ablation_run_starts_only_from_a_clean_checkout_with_a_commit(
    harness: HarnessState,
) -> None:
    refused = _config(harness=harness)
    assert not isinstance(refused, RunConfig), refused
    assert "an ablation run starts only from a clean checkout with a commit" in str(refused)
    # A run of neither kind is the product's, and runs from any checkout.
    assert isinstance(_config(ablation=False, harness=harness), RunConfig)


#: Each rule a reportable run is held to, with a run that breaks it and where its sessions run.
BROKEN: list[tuple[str, dict[str, Any], Present | Absent]] = [
    ("os_layer_for_reportable_runs", {"os_layer": ABSENT, "os_layer_absent": "allow"}, ABSENT),
    ("no_os_layer_allowance_for_reportable_runs", {"os_layer_absent": "allow"}, PRESENT),
    (
        "network_none_for_reportable_runs",
        {
            "network": "none",
            "os_layer": ABSENT,
            "network_enforced": False,
            "os_layer_absent": "allow",
        },
        ABSENT,
    ),
    ("record_decisions_for_reportable_runs", {"queue_decisions": "act"}, PRESENT),
    ("observed_design_review_for_reportable_runs", {"design_review": "off"}, PRESENT),
]


def _asked(rule: str, config: RunConfig, layer: Present | Absent) -> Any:  # noqa: ANN401
    requirement: Callable[[RunFacts], str | None] = getattr(requirements, rule)
    facts = RunFacts(config=config, os_layer=layer, shell_sessions=True, new_run=True)
    return outcome_of(lambda: requirement(facts))


@pytest.mark.parametrize(("rule", "broken", "layer"), BROKEN, ids=[row[0] for row in BROKEN])
def test_an_ablation_run_is_refused_whatever_a_reportable_run_is_refused_for(
    rule: str, broken: dict[str, Any], layer: Present | Absent
) -> None:
    ablation = _config(**broken)
    assert isinstance(ablation, RunConfig), ablation
    why = _asked(rule, ablation, layer)
    assert isinstance(why, str), why
    assert "an ablation run" in why and "a reportable run" not in why
    # The same run as a reportable one is refused in a reportable run's name, as it was.
    reportable = _config(**broken, ablation=False, reportable=True)
    assert isinstance(reportable, RunConfig), reportable
    said = _asked(rule, reportable, layer)
    assert isinstance(said, str), said
    assert "a reportable run" in said and "an ablation run" not in said
    assert said.replace("a reportable run", "an ablation run") == why
    # And as a run of neither kind it is the product's to run.
    ordinary = _config(**broken, ablation=False)
    assert isinstance(ordinary, RunConfig), ordinary
    assert _asked(rule, ordinary, layer) is None


def test_an_ablation_run_that_meets_every_rule_is_refused_by_none() -> None:
    ablation = _config()
    assert isinstance(ablation, RunConfig), ablation
    facts = RunFacts(config=ablation, os_layer=PRESENT, shell_sessions=True, new_run=True)
    assert [why for rule in requirements.REQUIREMENTS if (why := rule(facts))] == []
