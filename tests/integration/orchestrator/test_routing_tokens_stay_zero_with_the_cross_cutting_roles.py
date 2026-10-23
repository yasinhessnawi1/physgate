"""With sizing and integration among a run's roles, the one model call is still the only one.

The two cross-cutting roles ask more of the plan: sizing has one module at most, and
integration's consumers and system requirements are planned in the same call that
plans every module (ARCH-001, ARCH-051). Nothing about them is asked of a model
anywhere else. Through the real binary against the scripted endpoint: the call is one
request, it is offered the plan's larger form, the answer it is held to comes back as
that form, and the run's token account holds one decomposition and nothing spent on
routing.

What the binary is offered is exactly what the prompt and schema functions give for the
run's roles, with both roles and with neither: for a run with neither, those are the
bytes every run was sent before the two roles were planned for.
"""

from __future__ import annotations

import json
import os
import shutil
from pathlib import Path
from typing import Any

import pytest
from git_rig import config, target_repo
from knowledge_fixture import FIXTURE_ROLES, write_fixture
from scripted_endpoint import DUMMY_KEY, Script, serving, tool

from physgate import roles
from physgate.orchestrator import decompose
from physgate.orchestrator.accounting import TokenAccount
from physgate.orchestrator.credentials import Credential
from physgate.orchestrator.events import read_events
from physgate.orchestrator.git import head_of
from physgate.orchestrator.run_config import ModelStrings, RunConfig

pytestmark = [
    pytest.mark.integration,
    pytest.mark.skipif(
        not (os.environ.get("PHYSGATE_CLAUDE_BIN") or shutil.which("claude")),
        reason="no Claude Code binary on this machine",
    ),
]

ROLES = ("control", "firmware", "integration", "sizing")
BRIEF = (
    "Build a two-wheeled balancing robot.\n\n"
    "## Acceptance criteria\n\n"
    "1. It stands upright for 60 s.\n"
    "2. It recovers from a 5 N push.\n"
)
SPEC = "Do the work.\n\n## Acceptance criteria\n\n1. The first holds.\n2. The second holds.\n"
NODE: dict[str, Any] = {
    "id": "iface.drive",
    "kind": "interface",
    "domain": "control",
    "owner_role": "control",
    "quantities": {"v": {"value": 12, "unit": "V", "source": "brief", "written_by": "control"}},
    "requirements": [],
    "constrains": [],
    "model": None,
    "geometry_hash": "sha256:0",
    "updated": "2026-10-23T00:00:00Z",
}
#: Each module's name differs from its role: the consumers and the contributing criteria
#: name modules, and the interface node is owned by a role.
PLAN: dict[str, Any] = {
    "modules": [
        {"name": name, "role": role, "module_dir": f"modules/{name}", "spec": SPEC}
        for name, role in (("budget", "sizing"), ("drive", "control"), ("fw", "firmware"))
    ],
    "interface_nodes": [NODE],
    "interface_consumers": [{"interface": "iface.drive", "consumers": ["fw"]}],
    "system_requirements": [
        {
            "requirement": "2",
            "contributing": [
                {"module": "drive", "criterion": "1"},
                {"module": "fw", "criterion": "2"},
            ],
        }
    ],
}


def _decompose(
    root: Path, run_roles: tuple[str, ...], plan: dict[str, Any]
) -> tuple[Any, decompose.Outcome, RunConfig, Path]:
    """The run's one call through the real binary, for a run of ``run_roles``."""
    repo = target_repo(root)
    base = config()
    models = ModelStrings(
        decomposition=base.models.decomposition,
        roles=dict.fromkeys(run_roles, "claude-sonnet-5"),
        reviewers=dict.fromkeys(run_roles, "claude-opus-5-5"),
    )
    cfg = base.model_copy(update={"models": models, "target_head": head_of(repo, "master")})
    with serving(Script(main=[tool("StructuredOutput", **plan)])) as (api, url):
        outcome = decompose.call(
            BRIEF,
            config=cfg,
            workdir=root / "run" / "decomposition",
            base_url=url,
            credential=Credential("api_key", DUMMY_KEY),
        )
    return api, outcome, cfg, repo


@pytest.fixture
def sizing_registered(monkeypatch: pytest.MonkeyPatch) -> None:
    """The register as it will stand once sizing ships; integration already does."""
    monkeypatch.setitem(roles.ROLES, roles.SIZING.name, roles.SIZING)


def test_routing_tokens_stay_zero_with_the_two_new_roles(
    tmp_path: Path, sizing_registered: None
) -> None:
    api, outcome, cfg, repo = _decompose(tmp_path, ROLES, PLAN)
    assert outcome.ok, outcome.detail
    assert isinstance(outcome.plan, decompose.IntegratedPlan)
    assert len(api.requests) == 1
    (request,) = api.requests
    assert request.offered_tools == ("StructuredOutput",)
    schema = request.structured_schema
    assert schema is not None
    assert {"interface_consumers", "system_requirements"} <= set(schema["properties"])
    assert "Roles available: control, firmware, sizing." in request.last_user
    library = tmp_path / "library"
    write_fixture(library, (*FIXTURE_ROLES, "sizing"))
    run_dir = tmp_path / "run"
    decompose.start_run(
        outcome, config=cfg, run_dir=run_dir, target_repo=repo, library=library
    ).close()
    account = TokenAccount.from_events(read_events(run_dir / "events.jsonl"))
    assert account.decomposition_invocations() == 1
    spent = {kind for kind, usage in account.by_kind().items() if usage.total()}
    assert spent == {"decomposition"}
    assert account.by_kind()["routing"].total() == 0
    account.assert_no_routing()


@pytest.mark.parametrize(
    "run_roles", [ROLES, ("control", "firmware")], ids=["both roles", "neither role"]
)
def test_the_binary_is_offered_exactly_the_prompt_and_schema_of_the_run_s_roles(
    tmp_path: Path, sizing_registered: None, run_roles: tuple[str, ...]
) -> None:
    # The binary passes both through unchanged, so what the endpoint receives is what the
    # prompt and schema functions give for the run's roles: for a run with neither role,
    # the bytes the unit tests pin as those sent before either role was planned for.
    with_lists = "integration" in run_roles
    plan = (
        PLAN
        if with_lists
        else {
            "modules": [m for m in PLAN["modules"] if m["role"] != "sizing"],
            "interface_nodes": PLAN["interface_nodes"],
        }
    )
    api, outcome, _, _ = _decompose(tmp_path, run_roles, plan)
    assert outcome.ok, outcome.detail
    assert isinstance(outcome.plan, decompose.IntegratedPlan) is with_lists
    (request,) = api.requests
    offered = json.dumps(request.structured_schema, sort_keys=True, separators=(",", ":"))
    assert offered == decompose.plan_schema(run_roles)
    assert request.last_user == decompose.prompt_for(BRIEF, run_roles)


def test_the_call_holds_the_system_requirements_to_its_brief(
    tmp_path: Path, sizing_registered: None
) -> None:
    # The brief numbers two acceptance criteria; a requirement numbered 3 is not one of
    # them, and the call that made the plan is the one that refuses it.
    unknown = {
        **PLAN,
        "system_requirements": [
            {"requirement": "3", "contributing": [{"module": "drive", "criterion": "1"}]}
        ],
    }
    api, outcome, _, _ = _decompose(tmp_path, ROLES, unknown)
    assert len(api.requests) == 1
    assert not outcome.ok and outcome.cause == "invalid_plan"
    assert "'3' is not one of the brief's numbered acceptance criteria (1, 2)" in outcome.detail
