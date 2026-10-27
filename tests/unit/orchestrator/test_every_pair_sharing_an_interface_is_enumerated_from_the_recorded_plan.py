"""The module pairs whose contract is tested are read from the plan, recorded before any dispatch.

In a run with the integration role, every module that produces an interface is paired with each
module the plan names as reading it, and the pair holds every interface between the two in that
direction: two modules coupled both ways are two pairs. The set is the plan's, never what the
modules later write, and it is recorded in the run's opening, after the planning lines, so the
first dispatch finds it on the record. Both sides of a pair are read by role, since a node
carries its owner's role and no module, so the plan check refuses an interface whose producing
role, or a consumer's role, has more than one module; that narrows only plans with integration,
and the prompt and schema it sends are unchanged. Replay holds the recorded set to the plan's
recorded lines and refuses a dispatch before it, a second one, one in a run without consumers, a
planning line after it, and any set the plan does not give. A run without integration records no
such line.

The tests read the log as raw lines, so they name the line by its kind and fields alone.
"""

from __future__ import annotations

import hashlib
import json
import subprocess
from pathlib import Path
from typing import Any

import pytest
from knowledge_fixture import FIXTURE_ROLES, write_fixture
from loop_fakes import Rig
from orch_helpers import make_config
from pydantic import ValidationError

from physgate import roles
from physgate.contracts.pairs import ContractPair
from physgate.orchestrator.decompose import (
    IntegratedPlan,
    Outcome,
    Plan,
    mint_id,
    plan_problems,
    plan_schema,
    prompt_for,
    start_run,
)
from physgate.orchestrator.events import EventLog
from physgate.orchestrator.exceptions import (
    CorruptEventLogError,
    DecompositionError,
    RunConfigError,
)
from physgate.orchestrator.git import head_of
from physgate.orchestrator.record import PlanEntry
from physgate.orchestrator.replay import RunState
from physgate.orchestrator.run_config import ModelStrings

BOTH = ("control", "firmware", "integration", "sizing")
DOMAINS = ("control", "firmware")
SEED = 7
RUN_ID = "run-1"
BRIEF = "Build a robot.\n\n## Acceptance criteria\n\n1. It stands.\n"

#: The prompt and the schema of a run with integration as they were sent before the pairing
#: rule: the rule is a check on the answer and changes neither.
INTEGRATED_SCHEMA_SHA256 = "3eec10e96f3662df89989d4631da7fe7f1c2a6e5d973563551ecc8154ccb90fd"
INTEGRATED_PROMPT_SHA256 = {
    ("control", "firmware", "integration"): (
        "65026b5313078a25c905d9f1a5b9c4bc99b19a57025641ec965aeb1ab520e9ae"
    ),
    BOTH: "7f6bc346dff9f1a870646845d79451cc0672a0c796d0b32b0925de421faeffde",
}


def spec() -> str:
    return "Do the work.\n\n## Acceptance criteria\n\n1. It holds.\n"


def module(name: str, role: str) -> dict[str, str]:
    return {"name": name, "role": role, "module_dir": f"modules/{name}", "spec": spec()}


def interface(node_id: str, owner: str) -> dict[str, Any]:
    return {
        "id": node_id,
        "kind": "interface",
        "domain": "cross",
        "owner_role": owner,
        "quantities": {"v": {"value": 12, "unit": "V", "source": "brief", "written_by": owner}},
        "requirements": [],
        "constrains": [],
        "model": None,
        "geometry_hash": "sha256:0",
        "updated": "2026-10-25T00:00:00Z",
    }


#: Each module's name differs from its role. Control's drive produces two interfaces, one read
#: by firmware's fw and by sizing's budget; fw produces one that drive reads.
MODULES = [module("budget", "sizing"), module("drive", "control"), module("fw", "firmware")]
NODES = [
    interface("iface.drive", "control"),
    interface("iface.speed", "control"),
    interface("iface.tilt", "firmware"),
]
#: Listed out of id order, so a pair's interfaces are in order only if they are put in order.
CONSUMERS: list[dict[str, Any]] = [
    {"interface": "iface.speed", "consumers": ["fw"]},
    {"interface": "iface.drive", "consumers": ["fw", "budget"]},
    {"interface": "iface.tilt", "consumers": ["drive"]},
]
REQUIREMENTS = [{"requirement": "1", "contributing": [{"module": "drive", "criterion": "1"}]}]


def integrated(**changes: Any) -> IntegratedPlan:  # noqa: ANN401 - the plan's own fields
    answer = {
        "modules": MODULES,
        "interface_nodes": NODES,
        "interface_consumers": CONSUMERS,
        "system_requirements": REQUIREMENTS,
        **changes,
    }
    return IntegratedPlan.model_validate_json(json.dumps(answer))


def side(name: str, role: str) -> dict[str, str]:
    """A pair's side: the module, the subtask its place in the plan minted, its role."""
    index = [m["name"] for m in MODULES].index(name)
    return {"module": name, "subtask_id": mint_id(SEED, index, name), "role": role}


#: The pairs of the plan above, ordered by producer then consumer.
EXPECTED = [
    {
        "producer": side("drive", "control"),
        "consumer": side("budget", "sizing"),
        "interfaces": ["iface.drive"],
    },
    {
        "producer": side("drive", "control"),
        "consumer": side("fw", "firmware"),
        "interfaces": ["iface.drive", "iface.speed"],
    },
    {
        "producer": side("fw", "firmware"),
        "consumer": side("drive", "control"),
        "interfaces": ["iface.tilt"],
    },
]


def git(cwd: Path, *args: str) -> str:
    return subprocess.run(
        ["git", *args], cwd=cwd, check=True, capture_output=True, text=True
    ).stdout


def target_repo(root: Path) -> Path:
    repo = root / "target"
    (repo / "modules").mkdir(parents=True)
    (repo / "README.md").write_text("target\n")
    git(repo, "init", "-q", "-b", "master")
    git(repo, "-c", "user.email=t@example.invalid", "-c", "user.name=t", "add", "-A")
    git(repo, "-c", "user.email=t@example.invalid", "-c", "user.name=t", "commit", "-q", "-m", "i")
    return repo


def outcome(plan: Plan) -> Outcome:
    return Outcome(
        session_id="no-call",
        ok=True,
        cause=None,
        detail="",
        plan=plan,
        usage=(),
        model="claude-opus-5-5",
        num_turns=1,
    )


def start(root: Path, plan: Plan, run_roles: tuple[str, ...] = BOTH) -> tuple[Path, Path]:
    """Start a run of ``run_roles`` from ``plan``; its run directory and its target."""
    repo = target_repo(root)
    library = root / "library"
    write_fixture(library, (*FIXTURE_ROLES, *run_roles))
    run_dir = root / "run"
    config = make_config(
        run_id=RUN_ID,
        seed=SEED,
        target_head=head_of(repo, "master"),
        models=ModelStrings(
            decomposition="claude-opus-5-5",
            roles=dict.fromkeys(run_roles, "claude-opus-5-5"),
            reviewers=dict.fromkeys(run_roles, "claude-sonnet-5"),
        ),
    )
    start_run(
        outcome(plan), config=config, run_dir=run_dir, target_repo=repo, library=library
    ).close()
    return run_dir, repo


def lines(run_dir: Path) -> list[dict[str, Any]]:
    return [json.loads(raw) for raw in (run_dir / "events.jsonl").read_text().splitlines()]


def the_pairs(log: list[dict[str, Any]]) -> dict[str, Any]:
    (line,) = [one for one in log if one["kind"] == "contract_pairs_planned"]
    return line


def refusal(root: Path, log: list[dict[str, Any]]) -> str:
    """Why a run state refuses ``log`` (renumbered) at open, or ``""`` if it follows it."""
    path = root / "edited" / "events.jsonl"
    path.parent.mkdir(exist_ok=True)
    path.write_text("".join(json.dumps({**one, "seq": i}) + "\n" for i, one in enumerate(log)))
    try:
        EventLog(path, run_id=RUN_ID, gate_mode="on", state=RunState()).close()
    except CorruptEventLogError as exc:
        return exc.context["reason"]
    finally:
        path.unlink()
    return ""


def line(kind: str, template: dict[str, Any], **fields: Any) -> dict[str, Any]:  # noqa: ANN401
    """A line of ``kind`` with ``template``'s envelope and ``fields``."""
    envelope = {k: template[k] for k in ("seq", "ts", "run_id", "gate_mode")}
    return {**envelope, "kind": kind, **fields}


@pytest.fixture(autouse=True)
def sizing_registered(monkeypatch: pytest.MonkeyPatch) -> None:
    """The register as it will stand once sizing ships; integration already does."""
    monkeypatch.setitem(roles.ROLES, roles.SIZING.name, roles.SIZING)


# --- what is recorded ------------------------------------------------------------------------


def test_every_pair_sharing_an_interface_is_enumerated_from_the_recorded_plan(
    tmp_path: Path,
) -> None:
    run_dir, _ = start(tmp_path, integrated())
    log = lines(run_dir)
    kinds = [one["kind"] for one in log]
    # Once, as the last line of the opening: after every planning line, before any dispatch.
    assert kinds.count("contract_pairs_planned") == 1
    assert kinds[-1] == "contract_pairs_planned"
    assert kinds[-2] == "subtask_planned"
    assert the_pairs(log)["pairs"] == EXPECTED
    # Sizing's side is its opening pass, the subtask its place in the plan minted; the closing
    # pass, planned after the domain modules, is no side of any pair.
    closing = mint_id(SEED, len(MODULES), "budget-closing")
    assert closing in [one["subtask_id"] for one in log if one["kind"] == "subtask_planned"]
    assert closing not in json.dumps(the_pairs(log))
    # A run state follows the recorded opening, as it did when the line was written.
    assert refusal(tmp_path, log) == ""


def test_a_two_way_coupling_is_two_pairs(tmp_path: Path) -> None:
    run_dir, _ = start(tmp_path, integrated())
    pairs = the_pairs(lines(run_dir))["pairs"]
    between = [(p["producer"]["module"], p["consumer"]["module"]) for p in pairs]
    assert ("drive", "fw") in between and ("fw", "drive") in between
    assert len(between) == len(set(between)) == 3


def test_a_run_without_integration_records_no_pairs_and_its_opening_as_before(
    tmp_path: Path,
) -> None:
    plan = Plan.model_validate_json(
        json.dumps({"modules": MODULES[1:], "interface_nodes": NODES[:1]})
    )
    run_dir, _ = start(tmp_path, plan, DOMAINS)
    kinds = [one["kind"] for one in lines(run_dir)]
    assert kinds == ["run_started", "decomposed", "subtask_planned", "subtask_planned"]


@pytest.mark.parametrize("run_roles", sorted(INTEGRATED_PROMPT_SHA256), ids=", ".join)
def test_the_prompt_and_schema_with_integration_are_the_bytes_sent_before(
    run_roles: tuple[str, ...],
) -> None:
    schema = plan_schema(run_roles)
    assert hashlib.sha256(schema.encode()).hexdigest() == INTEGRATED_SCHEMA_SHA256
    prompt = prompt_for("Build a robot.", run_roles)
    assert hashlib.sha256(prompt.encode()).hexdigest() == INTEGRATED_PROMPT_SHA256[run_roles]


def test_a_pair_is_of_two_roles_and_names_each_interface_once_in_order() -> None:
    # Each wrong pair differs from the right one in one thing only.
    fields = {"producer": side("drive", "control"), "consumer": side("fw", "firmware")}
    right = {**fields, "interfaces": ["iface.drive", "iface.speed"]}
    ContractPair.model_validate_json(json.dumps(right))
    for wrong in (
        {**right, "interfaces": ["iface.speed", "iface.drive"]},
        {**right, "interfaces": ["iface.drive", "iface.drive"]},
        {**right, "interfaces": []},
        {**right, "consumer": side("budget", "control")},
    ):
        with pytest.raises(ValidationError):
            ContractPair.model_validate_json(json.dumps(wrong))


# --- the plan check --------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("changes", "named"),
    [
        (
            {"modules": [*MODULES, module("steer", "control")]},
            "interface node 'iface.drive' is produced by the 'control' role, which has 2 "
            "modules in the plan (drive, steer)",
        ),
        (
            {
                "modules": [*MODULES[:2], module("fw", "firmware"), module("fw2", "firmware")],
                "interface_nodes": NODES[:1],
                "interface_consumers": [{"interface": "iface.drive", "consumers": ["fw"]}],
            },
            "interface node 'iface.drive' is read by a module of the 'firmware' role, which has "
            "2 modules in the plan (fw, fw2)",
        ),
        (
            {
                "modules": [*MODULES[:2], module("fw", "firmware"), module("fw2", "firmware")],
                "interface_nodes": NODES[:1],
                "interface_consumers": [{"interface": "iface.drive", "consumers": ["fw", "fw2"]}],
            },
            "interface node 'iface.drive' is read by a module of the 'firmware' role, which has "
            "2 modules in the plan (fw, fw2)",
        ),
    ],
    ids=["the producing role", "a consumer's role, its other module no consumer", "two consumers"],
)
def test_a_role_with_two_modules_on_either_side_of_an_interface_is_refused(
    changes: dict[str, Any], named: str
) -> None:
    found = plan_problems(integrated(**changes), BOTH, BRIEF)
    assert any(named in problem for problem in found), found


def test_two_modules_of_a_role_in_no_interface_or_without_integration_are_not_refused() -> None:
    hulls = [module("hull-a", "mechanical"), module("hull-b", "mechanical")]
    found = plan_problems(integrated(modules=[*MODULES, *hulls]), (*BOTH, "mechanical"), BRIEF)
    assert not [p for p in found if "modules in the plan" in p], found
    base = Plan.model_validate_json(
        json.dumps(
            {"modules": [*MODULES[1:], module("steer", "control")], "interface_nodes": NODES}
        )
    )
    assert plan_problems(base, DOMAINS, BRIEF) == []


@pytest.mark.parametrize(
    "changes",
    [
        {"modules": [*MODULES, module("steer", "control")]},
        {
            "modules": [*MODULES[:2], module("fw", "firmware"), module("fw2", "firmware")],
            "interface_nodes": NODES[:1],
            "interface_consumers": [{"interface": "iface.drive", "consumers": ["fw", "fw2"]}],
        },
    ],
    ids=["two modules of the producing role", "two modules of a consumer's role"],
)
def test_start_run_fails_closed_on_a_plan_whose_pairs_cannot_be_formed(
    tmp_path: Path, changes: dict[str, Any]
) -> None:
    plan = integrated(**changes)
    with pytest.raises(DecompositionError, match="contract pairs"):
        start(tmp_path, plan)
    assert not any((tmp_path / "run" / name).exists() for name in ("events.jsonl", "run.json"))
    assert "physgate/" not in git(tmp_path / "target", "branch", "--list")


# --- replay ----------------------------------------------------------------------------------


def test_replay_refuses_a_dispatch_or_the_call_before_the_pairs_are_recorded(
    tmp_path: Path,
) -> None:
    log = lines(start(tmp_path, integrated())[0])
    first = next(one["subtask_id"] for one in log if one["kind"] == "subtask_planned")
    resolve = line("stage_entered", log[-1], subtask_id=first, attempt=1, stage="resolve")
    call = line("integration_gate_skipped", log[-1], reason="nothing_planned", subtasks=[])
    assert refusal(tmp_path, [*log, resolve]) == ""
    without = [one for one in log if one["kind"] != "contract_pairs_planned"]
    for dispatched in (resolve, call):
        assert "before the run's contract pairs" in refusal(tmp_path, [*without, dispatched])


def test_replay_refuses_a_second_pairs_line_and_a_planning_line_after_one(tmp_path: Path) -> None:
    log = lines(start(tmp_path, integrated())[0])
    assert "recorded once" in refusal(tmp_path, [*log, log[-1]])
    moved = [*log[:-2], log[-1], log[-2]]
    assert "nothing is planned after the run's contract pairs" in refusal(tmp_path, moved)


def test_replay_refuses_pairs_in_a_run_whose_plan_names_no_consumers(tmp_path: Path) -> None:
    pairs = the_pairs(lines(start(tmp_path / "a", integrated())[0]))
    plan = Plan.model_validate_json(json.dumps({"modules": MODULES, "interface_nodes": NODES}))
    log = lines(start(tmp_path / "b", plan, ("control", "firmware", "sizing"))[0])
    reason = refusal(tmp_path, [*log, {**pairs, "seq": len(log)}])
    assert "names its interfaces' consumers" in reason


def _drop_budget(pairs: list[dict[str, Any]]) -> None:
    del pairs[0]


def _one_side_moved(pairs: list[dict[str, Any]]) -> None:
    pairs[2]["producer"]["subtask_id"] = "fw-000000"


def _two_producers(pairs: list[dict[str, Any]]) -> None:
    pairs[2]["interfaces"] = ["iface.drive", "iface.tilt"]


def _unplanned(pairs: list[dict[str, Any]]) -> None:
    for pair in pairs:
        for one in ("producer", "consumer"):
            if pair[one]["module"] == "fw":
                pair[one]["subtask_id"] = "fw-000000"


def _integration_side(pairs: list[dict[str, Any]], integration: str) -> None:
    pairs[0]["consumer"] = {
        "module": "integration",
        "subtask_id": integration,
        "role": "integration",
    }


def _another_role(pairs: list[dict[str, Any]]) -> None:
    pairs[0]["consumer"]["role"] = "firmware"


def _closing_pass(pairs: list[dict[str, Any]], closing: str) -> None:
    pairs[0]["consumer"]["subtask_id"] = closing


def _foreign_interface(pairs: list[dict[str, Any]]) -> None:
    pairs[0]["interfaces"] = ["iface.drive", "iface.ghost"]


def _reordered(pairs: list[dict[str, Any]]) -> None:
    pairs.reverse()


def _split(pairs: list[dict[str, Any]]) -> None:
    second = json.loads(json.dumps(pairs[1]))
    pairs[1]["interfaces"], second["interfaces"] = ["iface.drive"], ["iface.speed"]
    pairs.insert(2, second)


@pytest.mark.parametrize(
    ("edit", "why"),
    [
        (_drop_budget, "is in no pair"),
        (_one_side_moved, "named with two subtasks or roles"),
        (_two_producers, "two producers"),
        (_unplanned, "no planned module's subtask"),
        (_integration_side, "no planned module's subtask"),
        (_another_role, "its subtask is planned for"),
        (_closing_pass, "not the one planned for module 'budget'"),
        (_foreign_interface, "do not cover the plan's interface nodes"),
        (_reordered, "not the ones the plan gives"),
        (_split, "not the ones the plan gives"),
    ],
    ids=[
        "a pair dropped",
        "a module named with two subtasks",
        "an interface with two producers",
        "a side's subtask not planned",
        "integration's subtask as a side",
        "a side of another role than its subtask",
        "sizing's closing pass as its side",
        "an interface the plan has not",
        "the pairs out of order",
        "one pair split in two",
    ],
)
def test_replay_refuses_pairs_the_plan_does_not_give(
    tmp_path: Path,
    edit: Any,
    why: str,  # noqa: ANN401 - each edit takes what it needs
) -> None:
    log = lines(start(tmp_path, integrated())[0])
    planned = [one["subtask_id"] for one in log if one["kind"] == "subtask_planned"]
    pairs = json.loads(json.dumps(the_pairs(log)["pairs"]))
    if edit is _integration_side:
        edit(pairs, planned[-1])
    elif edit is _closing_pass:
        edit(pairs, mint_id(SEED, len(MODULES), "budget-closing"))
    else:
        edit(pairs)
    reason = refusal(tmp_path, [*log[:-1], {**log[-1], "pairs": pairs}])
    assert "contract pairs are not its plan's" in reason and why in reason, reason


@pytest.mark.parametrize("written", ["modules/Budget", "modules/budget/"])
def test_replay_refuses_an_opening_whose_module_directories_are_one_with_case_folded(
    tmp_path: Path, written: str
) -> None:
    """Where case is ignored, as on the machine runs are made on, the two are one directory."""
    log = lines(start(tmp_path, integrated())[0])
    planned = [one for one in log if one["kind"] == "subtask_planned"]
    fw = next(one for one in planned if one["module_dir"] == "modules/fw")
    moved = [{**one, "module_dir": written} if one is fw else one for one in log]
    reason = refusal(tmp_path, moved)
    assert "modules/budget" in reason and written in reason and "one directory" in reason, reason
    # As the plan check refuses the same plan before anything is written.
    modules = [{**one, "module_dir": written} if one["name"] == "fw" else one for one in MODULES]
    assert "overlap" in " ".join(plan_problems(integrated(modules=modules), BOTH, BRIEF))
    # The same directory written the same way twice is one module and its later pass.
    assert [one["module_dir"] for one in planned].count("modules/budget") == 2
    assert refusal(tmp_path, log) == ""


def test_directories_one_with_case_folded_are_refused_however_far_apart_they_are_planned(
    tmp_path: Path,
) -> None:
    """Every module planned before is asked, not only the one planned just before."""
    planned = [("s1", "modules/s1"), ("s2", "modules/s2"), ("s3", "modules/S1")]
    entries = [
        PlanEntry(
            subtask_id=subtask_id,
            spec_path=f"specs/{subtask_id}.md",
            assigned_role="electrical",
            module_dir=module_dir,
        )
        for subtask_id, module_dir in planned
    ]
    loop = Rig(tmp_path).open()
    with pytest.raises(RunConfigError, match="modules/s1 and modules/S1 are one directory"):
        loop.start(entries)
    loop.close()
    log = tmp_path / "events.jsonl"
    assert not log.exists() or not log.read_bytes()
