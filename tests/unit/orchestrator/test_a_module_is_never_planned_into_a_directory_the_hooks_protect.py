"""No module is planned into a directory the hooks protect from every session.

A module's directory is where its session works and the whole of what its attempt may
change. The hook layer refuses every session's write under a protected root of its
worktree: the gate's and the hooks' sources, the curated knowledge, the evaluation
corpora carrying their answers, the frozen experiments, the harness's own places
under ``.physgate``. A module planned into one of them, or around one, could never do
its work there, or would hold protected files inside its own scope. The plan check
refuses it before any session runs.

The roots are not a second list kept beside the hooks': they are read from the
configuration the hook layer gives a role session, so a root the hooks gain is refused
here too. A path beneath a root that the hook still lets a session write (the
knowledge library's staging directory) is a module's like any other. Directories are
compared with case folded, as the hooks compare them and as the file system the runs
are made on resolves them.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest

from physgate.hooks import settings
from physgate.hooks.config import ProtectedRoot
from physgate.orchestrator.decompose import Plan, plan_problems

NODE: dict[str, Any] = {
    "id": "power.bus",
    "kind": "interface",
    "domain": "electrical",
    "owner_role": "electrical",
    "quantities": {"v": {"value": 12, "unit": "V", "source": "brief", "written_by": "electrical"}},
    "requirements": [],
    "constrains": [],
    "model": None,
    "geometry_hash": "sha256:0",
    "updated": "2026-10-23T00:00:00Z",
}
ROLES = ("electrical",)
BRIEF = "Build a robot."


def plan_in(module_dir: str) -> Plan:
    module = {"name": "power", "role": "electrical", "module_dir": module_dir, "spec": "do it"}
    return Plan.model_validate_json(json.dumps({"modules": [module], "interface_nodes": [NODE]}))


def refusals(module_dir: str) -> list[str]:
    return [p for p in plan_problems(plan_in(module_dir), ROLES, BRIEF) if "the hooks protect" in p]


@pytest.mark.parametrize(
    "module_dir",
    [
        "knowledge",
        "knowledge/control",
        "Knowledge/Control",
        "corpora",
        "corpora/injected",
        "CORPORA",
        "experiments",
        "experiments/R-XX-01",
        "src/physgate/gate",
        "src/physgate/hooks/x",
        "SRC/PHYSGATE/GATE",
        # Around a root: the module's scope would hold protected files.
        "src",
        "src/physgate",
    ],
)
def test_a_module_in_or_around_a_protected_root_is_refused(module_dir: str) -> None:
    assert refusals(module_dir), plan_problems(plan_in(module_dir), ROLES, BRIEF)


@pytest.mark.parametrize(
    "module_dir",
    [
        "modules/power",
        "src/firmware",
        "knowledge/staging",
        "knowledge/staging/candidate",
        "Knowledge/Staging/candidate",
    ],
)
def test_a_module_anywhere_else_or_where_the_hook_still_lets_a_session_write_is_not(
    module_dir: str,
) -> None:
    assert plan_problems(plan_in(module_dir), ROLES, BRIEF) == []


def test_every_module_is_held_to_the_roots_not_only_the_first() -> None:
    modules = [
        {"name": "power", "role": "electrical", "module_dir": "modules/power", "spec": "do it"},
        {"name": "wiring", "role": "electrical", "module_dir": "knowledge/x", "spec": "do it"},
    ]
    plan = Plan.model_validate_json(json.dumps({"modules": modules, "interface_nodes": [NODE]}))
    found = [p for p in plan_problems(plan, ROLES, BRIEF) if "the hooks protect" in p]
    assert len(found) == 1 and found[0].startswith("module 'wiring' "), found


def test_the_roots_are_the_ones_the_hook_layer_gives_a_role_session() -> None:
    roots = dict(settings.protected_in_a_worktree())
    for root in (
        "knowledge",
        "corpora",
        "experiments",
        "src/physgate/gate",
        "src/physgate/hooks",
        ".physgate/lib",
        ".physgate/series",
        ".claude",
        ".env",
    ):
        assert Path(root).as_posix() in {r.as_posix() for r in roots}, (root, roots)
    knowledge = next(v for k, v in roots.items() if k.as_posix() == "knowledge")
    assert [e.as_posix() for e in knowledge] == ["knowledge/staging"]
    # Nothing of the machine's or the session's own outside the worktree is among them.
    assert all(not r.is_absolute() and ".." not in r.parts for r in roots)


def test_a_root_the_hook_layer_gains_is_refused_by_the_plan(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # The plan reads the hooks' own configuration, not a copy of it: a root added there
    # is refused here with no change to the plan check.
    assert refusals("modules/locked") == []
    built = settings.build_config

    def with_one_more(request: settings.InstallRequest, installation: Any) -> Any:  # noqa: ANN401
        config = built(request, installation)
        locked = ProtectedRoot(
            path=str(Path(request.worktree) / "modules" / "locked"),
            reason="a root the hooks gained",
            watch="revert",
        )
        return config.model_copy(update={"protected_roots": (*config.protected_roots, locked)})

    monkeypatch.setattr(settings, "build_config", with_one_more)
    assert refusals("modules/locked")
    assert refusals("Modules/Locked/x")
    assert refusals("modules/other") == []
