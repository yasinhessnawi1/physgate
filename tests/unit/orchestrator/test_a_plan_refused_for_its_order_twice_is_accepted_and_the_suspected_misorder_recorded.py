"""A text check of the plan's order cannot end a run: refused once, accepted when made again.

A plan that lists a builder before the designer whose design it runs is refused once, told which
two modules and on what node, so the planner can reorder. The call made again accepts such a plan:
the opening then records one entry on the design pairs line naming the suspected misorder (the
builder, the designer and the nodes), and no hold is made for it, so the modules are dispatched in
the plan's order. The entry is left out of the line when there is none, so every other record
keeps its bytes. A refusal on the retry for any other reason still ends the decomposition, and no
third call is made. Replay refuses an entry out of its place, or naming what the plan does not
have; the run's status and the page say it in plain words.
"""

from __future__ import annotations

import json
import shutil
from collections.abc import Iterator
from pathlib import Path
from typing import Any

import pytest
import replan_rig
from test_a_plan_that_puts_a_builder_before_its_designer_is_refused_and_made_once_more import (
    CRITERIA,
    MISORDERED,
    judged,
    module,
)
from test_every_pair_sharing_an_interface_is_enumerated_from_the_recorded_plan import (
    SEED,
    integrated,
    line,
    lines,
    refusal,
    start,
)
from test_every_pair_sharing_an_interface_is_enumerated_from_the_recorded_plan import (
    sizing_registered as sizing_registered,  # noqa: F401 - the register, a fixture
)
from test_the_decomposition_prompt_states_how_a_unit_is_spelt import REFUSED

from physgate.orchestrator.decompose import IntegratedPlan, judge, mint_id
from physgate.orchestrator.design_pairs import DesignPair

NAMES = ["budget", "fw", "drive"]


def plan_in_order(*order: str) -> IntegratedPlan:
    """The pair test's plan, drive designing on ``drive.law`` and fw running it, in ``order``."""
    base = {m.name: m.model_dump() for m in integrated().modules}
    base["drive"]["spec"] = "Write the law on `drive.law`, your own node." + CRITERIA
    base["fw"]["spec"] = "Run exactly what `drive.law` holds, as merged." + CRITERIA
    return integrated(modules=[base[name] for name in order])


def ids(order: tuple[str, ...] = tuple(NAMES)) -> dict[str, str]:
    return {name: mint_id(SEED, order.index(name), name) for name in order}


# --- the refusal is made once, and the call made again accepts ----------------------------------


def judged_as(accept: bool, *modules: dict[str, str]) -> Any:  # noqa: ANN401
    result = {
        "type": "result",
        "subtype": "success",
        "is_error": False,
        "terminal_reason": "completed",
        "num_turns": 2,
        "modelUsage": {"claude-sonnet-5": {}},
        "structured_output": {
            "modules": list(modules),
            "interface_nodes": [
                {
                    "id": "firmware.loop_io",
                    "kind": "interface",
                    "domain": "cross",
                    "owner_role": "firmware",
                    "quantities": {
                        "rate": {
                            "value": 200,
                            "unit": "Hz",
                            "source": "brief",
                            "written_by": "firmware",
                        }
                    },
                    "requirements": [],
                    "constrains": [],
                    "model": None,
                    "geometry_hash": "sha256:0",
                    "updated": "2026-11-20T00:00:00Z",
                }
            ],
        },
    }
    cause, detail, plan, *_ = judge(
        result,
        exit_code=0,
        timed_out=False,
        model="claude-sonnet-5",
        roles=["control", "firmware"],
        answered=frozenset({"claude-sonnet-5"}),
        brief="Build a robot.",
        accept_misorder=accept,
    )
    return cause, detail, plan


CONTROL = "`control.law` is this module's own node: the gains to run." + CRITERIA
FIRMWARE = "Runs the gains on `control.law` as merged." + CRITERIA


def test_the_first_call_refuses_a_misordered_plan_and_the_call_made_again_accepts_it() -> None:
    misordered = (module("firmware", FIRMWARE), module("control", CONTROL))
    cause, detail, plan = judged_as(False, *misordered)
    assert (cause, plan) == (REFUSED, None) and detail.startswith("the plan puts module ")
    cause, detail, plan = judged_as(True, *misordered)
    assert (cause, detail) == (None, "a plan")
    assert [m.name for m in plan.modules] == ["firmware", "control"]


def test_a_plan_made_again_is_still_held_to_everything_but_its_order() -> None:
    # A module of a role the run has none of: the plan's own problems end the call as they did.
    stranger = module("control", CONTROL, "welding")
    cause, _, plan = judged_as(True, module("firmware", FIRMWARE), stranger)
    assert (cause, plan) == ("invalid_plan", None)


def test_a_plan_reordered_after_one_refusal_is_a_normal_plan_with_its_pair() -> None:
    cause, detail, plan = judged_as(True, module("control", CONTROL), module("firmware", FIRMWARE))
    assert (cause, detail) == (None, "a plan")
    assert [m.name for m in plan.modules] == ["control", "firmware"]


@pytest.mark.parametrize("review", ["off", "on"])
def test_only_the_call_made_again_accepts_a_plan_misordered(
    tmp_path: Path, review: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    # The first call's output refused (as its order is: the rig's refusal), the second asked to
    # accept; the number of calls is what it was, two.
    real = replan_rig.Script.call

    def call(self: replan_rig.Script, brief: str, *, workdir: Path, **given: Any) -> Any:  # noqa: ANN401
        outcome = real(self, brief, workdir=workdir, **given)
        if outcome.cause == REFUSED:
            return outcome.model_copy(update={"detail": MISORDERED})
        return outcome

    monkeypatch.setattr(replan_rig.Script, "call", call)
    steps = [replan_rig.Step(call=REFUSED), replan_rig.Step(review="pass")]
    ran = replan_rig.decompose(tmp_path, review, steps)
    assert ran.code == 0, ran.err
    first, second = ran.script.calls
    assert first.get("accept_misorder", False) is False
    assert second["accept_misorder"] is True
    assert len(ran.script.calls) == 2


@pytest.mark.parametrize("review", ["off", "on"])
def test_a_schema_refusal_first_accepts_an_order_refusal_on_the_retry_too(
    tmp_path: Path, review: str
) -> None:
    # A first call refused for something else, a retry that would be refused for its order: order
    # alone must not end a run, so the retry is asked to accept whatever the first refusal was.
    steps = [replan_rig.Step(call=REFUSED), replan_rig.Step(review="pass")]
    ran = replan_rig.decompose(tmp_path, review, steps)
    assert ran.code == 0, ran.err
    assert [c.get("accept_misorder", False) for c in ran.script.calls] == [False, True]


# --- the opening records the suspected misorder, and holds nothing ------------------------------


def test_a_misordered_plan_records_one_entry_on_the_pairs_line_and_holds_nothing(
    tmp_path: Path,
) -> None:
    run_dir, _ = start(tmp_path, plan_in_order("budget", "fw", "drive"))
    log = lines(run_dir)
    (planned,) = [one for one in log if one["kind"] == "design_pairs_planned"]
    named = ids()
    assert planned["pairs"] == []
    assert planned["misordered"] == [
        {"designer": named["drive"], "builder": named["fw"], "nodes": ["drive.law"]}
    ]
    assert "mutual" not in planned
    assert refusal(tmp_path, log) == ""
    # The modules are planned in the plan's order, and nothing is held.
    first = [one["subtask_id"] for one in log if one["kind"] == "subtask_planned"]
    assert first[:3] == [named["budget"], named["fw"], named["drive"]]
    assert not [one for one in log if one["kind"] == "builder_held"]


def test_a_plan_reordered_as_told_records_its_pair_and_no_entry(tmp_path: Path) -> None:
    log = lines(start(tmp_path, plan_in_order("budget", "drive", "fw"))[0])
    (planned,) = [one for one in log if one["kind"] == "design_pairs_planned"]
    named = ids(("budget", "drive", "fw"))
    assert planned["pairs"] == [
        {"designer": named["drive"], "builder": named["fw"], "nodes": ["drive.law"]}
    ]
    assert "misordered" not in planned


def test_a_plan_with_no_misorder_keeps_the_bytes_of_every_line_it_had(tmp_path: Path) -> None:
    log = lines(start(tmp_path, integrated())[0])
    assert "design_pairs_planned" not in [one["kind"] for one in log]
    assert all("misordered" not in one for one in log)


def test_the_entry_is_one_per_builder_and_designer_in_the_run_s_order(tmp_path: Path) -> None:
    # Two builders before the designer they both run: one entry each, by builder in plan order.
    base = {m.name: m.model_dump() for m in integrated().modules}
    base["drive"]["spec"] = "Write the law on `drive.law`, your own node." + CRITERIA
    base["fw"]["spec"] = "Run what `drive.law` holds." + CRITERIA
    base["budget"]["spec"] = "Size from what `drive.law` holds." + CRITERIA
    plan = integrated(modules=[base["fw"], base["budget"], base["drive"]])
    log = lines(start(tmp_path, plan)[0])
    (planned,) = [one for one in log if one["kind"] == "design_pairs_planned"]
    named = ids(("fw", "budget", "drive"))
    got = [(e["builder"], e["designer"]) for e in planned["misordered"]]
    # Sizing opens the domain work whatever the plan says: it is no builder here.
    assert got == [(named["fw"], named["drive"])]


# --- replay -------------------------------------------------------------------------------------


def opened(tmp_path: Path) -> list[dict[str, Any]]:
    return lines(start(tmp_path, plan_in_order("budget", "fw", "drive"))[0])


def test_replay_refuses_an_entry_out_of_its_place_or_naming_what_the_plan_does_not_have(
    tmp_path: Path,
) -> None:
    log = opened(tmp_path)
    planned = log[-1]
    (entry,) = planned["misordered"]
    closing = mint_id(SEED, 3, "budget-closing")

    def with_entry(*changed: dict[str, Any]) -> list[dict[str, Any]]:
        return [*log[:-1], {**planned, "misordered": list(changed)}]

    reversed_ = {**entry, "designer": entry["builder"], "builder": entry["designer"]}
    cases = {
        "not dispatched before its designer": with_entry(reversed_),
        "plans no module": with_entry({**entry, "builder": closing}),
        "on an interface node": with_entry({**entry, "nodes": ["iface.drive"]}),
        "each named once": with_entry({**entry, "nodes": ["drive.law", "drive.law"]}),
        "each recorded once": with_entry(entry, entry),
    }
    for said, edited in cases.items():
        assert said in refusal(tmp_path, edited), said
    # Once, before anything is dispatched, and not on a line that says nothing.
    assert "recorded once" in refusal(tmp_path, [*log, log[-1]])
    first = next(one["subtask_id"] for one in log if one["kind"] == "subtask_planned")
    resolve = line("stage_entered", log[-1], subtask_id=first, attempt=1, stage="resolve")
    assert "before anything is dispatched" in refusal(tmp_path, [*log[:-1], resolve, planned])
    swapped = [*log[:-2], log[-1], log[-2]]
    assert "follow its contract pairs" in refusal(tmp_path, swapped)


def test_replay_refuses_an_entry_that_is_a_recorded_pair_the_other_way_round(
    tmp_path: Path,
) -> None:
    log = lines(start(tmp_path, plan_in_order("budget", "drive", "fw"))[0])
    planned = log[-1]
    (pair,) = planned["pairs"]
    crossed = {**pair, "designer": pair["builder"], "builder": pair["designer"]}
    edited = [*log[:-1], {**planned, "misordered": [crossed]}]
    assert "the other way round" in refusal(tmp_path, edited)


def test_a_line_that_records_neither_a_pair_nor_an_entry_is_no_line_the_log_reads(
    tmp_path: Path,
) -> None:
    log = opened(tmp_path)
    empty = {**log[-1], "misordered": []}
    assert refusal(tmp_path, [*log[:-1], empty]) != ""


# --- what a person is told ----------------------------------------------------------------------


@pytest.fixture(scope="module")
def world(tmp_path_factory: pytest.TempPathFactory) -> Iterator[dict[str, Any]]:
    from ui_rig import fake_ui

    base = tmp_path_factory.mktemp("misordered")
    root = base / "runs"
    root.mkdir()
    with pytest.MonkeyPatch.context() as monkeypatch:
        from physgate import roles

        monkeypatch.setitem(roles.ROLES, roles.SIZING.name, roles.SIZING)
        run_dir, _ = start(base / "mis", plan_in_order("budget", "fw", "drive"))
        shutil.copytree(run_dir, root / "mis")
        run_dir, _ = start(base / "ok", plan_in_order("budget", "drive", "fw"))
        shutil.copytree(run_dir, root / "ok")
    yield {"root": root, "ui": fake_ui(base / "checkout")}


def test_the_status_says_in_plain_words_which_builder_is_listed_before_its_designer(
    world: dict[str, Any],
) -> None:
    from ui_rig import context_over, serving

    named = ids()
    with serving(context_over(world["root"], ui_root=world["ui"])) as live:
        status, _, body = live.request("GET", "/api/runs/0/mis/status")
        assert status == 200, body[:300]
        found = json.loads(body)
        assert found["misordered"] == [
            {
                "builder": named["fw"],
                "designer": named["drive"],
                "nodes": ["drive.law"],
                "words": f"the plan lists {named['fw']} before {named['drive']}, whose design "
                "it may build: check the order",
            }
        ]
        assert found["held"] == []
        status, _, body = live.request("GET", "/api/runs/0/ok/status")
        assert json.loads(body)["misordered"] == []


def test_a_misordered_plan_the_judge_accepts_is_the_plan_the_opening_reads() -> None:
    # The same modules, through the judge and then the opening's reading: one entry, as recorded.
    cause, _, plan = judged(module("firmware", FIRMWARE), module("control", CONTROL))
    assert cause == REFUSED and plan is None
    accepted = judged_as(True, module("firmware", FIRMWARE), module("control", CONTROL))[2]
    from physgate.orchestrator.decompose import planned_misorders

    found = planned_misorders(
        accepted, ["control", "firmware"], {"firmware": "f-1", "control": "c-2"}
    )
    assert found == (DesignPair(designer="c-2", builder="f-1", nodes=("control.law",)),)
