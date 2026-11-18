"""The isolation probe, with the control scorer: a composing tier fails one-requirement answers.

For each held-out task and each requirement it composes, the probe searches, seeded, for a
controller that meets that requirement's own specifications alone, and scores it on all of the
task's headline specifications, as any answer is scored. Two fixture tiers, each written by the
real split into a version of its own:

- a tier that composes: a fast settling window and a gentle actuator, two requirements that pull
  against each other. A controller found for either alone misses the other, while one controller
  meets both, so the tier is satisfiable and composes in substance;
- an injected tier whose tasks declare two requirements, held stable and steady, where either
  alone decides the pass: on a plant this mild every stable loop with an integrator is steady.
  Every one-requirement answer passes, and the probe's check goes red.

These rows run the search and the scorer, so they are in the evaluation environment.
"""

from __future__ import annotations

import inspect
import json
from pathlib import Path
from typing import Any

import pytest
from control_fixtures import controller, poly

from physgate.cli import main
from physgate.evaluation.per_role import synthesise
from physgate.evaluation.per_role.scorers.control import score
from physgate.evaluation.tiers.store import withheld_root, write_version
from physgate.evaluation.tiers.task import Task, canonical_json, parse_task

pytestmark = pytest.mark.injected

#: A first-order plant, 1 / (s + 1).
PLANT = poly("plant_num", [1.0]) + poly("plant_den", [1.0, 1.0])
SEED = 0


def _composing(i: int) -> dict[str, Any]:
    """Settle within a second, and never drive the actuator past 5 N m: met together only."""
    return {
        "id": f"control.c{i:02d}",
        "role": "control",
        "tier": "visible",
        "source": {"kind": "own"},
        "brief": f"Hold plant number {i} gently and quickly. Write the controller to answer.json.",
        "inputs": [*PLANT, {"name": "actuator_limit", "value": 5.0, "unit": "N*m"}],
        "answer": {"path": "answer.json", "form": "lti_tf"},
        "specs": [
            {
                "name": "settling",
                "metric": "settling_time",
                "op": "in",
                "bound": [{"value": 0.05, "unit": "s"}, {"value": 1.0, "unit": "s"}],
                "composes": ["respond_in_time"],
            },
            {
                "name": "effort",
                "metric": "actuator_peak",
                "op": "<=",
                "bound": {"value": 5.0, "unit": "N*m"},
                "composes": ["respect_actuator"],
            },
        ],
        "scorer": {"id": "control", "version": "1.1.0"},
    }


def _one_decides(i: int) -> dict[str, Any]:
    """Held stable, and steady: two requirements declared, either of which decides the pass."""
    task = _composing(i)
    task.update(
        id=f"control.n{i:02d}",
        brief=f"Hold plant number {i} steady. Write the controller to answer.json.",
        inputs=PLANT,
        specs=[
            {
                "name": "stable",
                "metric": "max_real_pole",
                "op": "<",
                "bound": {"value": 0, "unit": "1/s"},
                "composes": ["hold_the_plant"],
            },
            {
                "name": "accuracy",
                "metric": "steady_state_error",
                "op": "<=",
                "bound": {"value": 0.5, "unit": "1"},
                "composes": ["respond_in_time"],
            },
            {
                "name": "settling",
                "metric": "settling_time",
                "op": "in",
                "bound": [{"value": 0.0, "unit": "s"}, {"value": 100.0, "unit": "s"}],
                "counts": "secondary",
                "composes": ["respond_in_time"],
            },
        ],
    )
    return task


def _store(root: Path, make: Any) -> tuple[Path, str, list[Task]]:  # noqa: ANN401
    """Twenty-four tasks from ``make``, split by the real split; the store, version, held out."""
    store = root.resolve() / "store"
    pool = store / "control" / "withheld" / "pool"
    for i in range(24):
        task = make(i)
        place = pool / task["id"]
        bad = place / "references" / "bad_any"
        good = place / "references" / "good"
        for ref in (good, bad):
            ref.mkdir(parents=True)
            (ref / "answer.json").write_text(json.dumps(controller([1.0], [1.0])))
        (bad / "expect.json").write_text(json.dumps({"fails": task["specs"][0]["name"]}))
        (place / "task.json").write_text(json.dumps(task))
    manifest, _ = write_version(
        store / "control",
        sorted(p for p in pool.iterdir() if p.is_dir()),
        role="control",
        seed=5,
        model="claude-sonnet-5",
        runtime="2.1.301",
        provenance=canonical_json({"sessions": [{"session_id": "s-1", "end": "ended"}]}),
        retire=pool,
        generated="2026-11-18",
    )
    held = store / "control" / manifest.version / "held_out"
    tasks = [
        parse_task((d / "task.json").read_bytes()) for d in sorted(held.iterdir()) if d.is_dir()
    ]
    return store, manifest.version, tasks


def _aimable() -> None:
    parameters = inspect.signature(synthesise.search).parameters
    assert "specs" in parameters, "the search cannot be aimed at some of a task's specs"


def _probe(store: Path, version: str, capsys: pytest.CaptureFixture[str]) -> dict[str, Any]:
    args = ["tiers", "probe", "--withheld", str(withheld_root(store, "control"))]
    try:
        code = main([*args, "--version", version, "--seed", str(SEED)])
    except SystemExit as exc:
        code = int(exc.code or 0)
    out = capsys.readouterr()
    assert code == 0, f"the probe did not run: {out.out}{out.err}"
    said: dict[str, Any] = json.loads(out.out.strip().splitlines()[-1])
    return said


def _composes(result: dict[str, Any]) -> bool:
    """The probe's check: every scenario failed by every one-requirement answer."""
    findings = result["findings"]
    return bool(
        findings["tasks"] > 0
        and findings["tasks_failed_by_every_single_requirement_answer"] == findings["tasks"]
    )


def _rows(task: Task, answer: Any, tmp_path: Path) -> dict[str, bool]:  # noqa: ANN401
    path = tmp_path / "answer.json"
    path.write_bytes(canonical_json(answer.model_dump(mode="json")))
    return {row["name"]: row["passed"] for row in score(task, path)["specs"]}


def test_a_search_aimed_at_one_requirement_s_specs_meets_those_specs(tmp_path: Path) -> None:
    _aimable()
    task = parse_task(json.dumps(_composing(0)).encode())
    for spec in ("settling", "effort"):
        answer = synthesise.search(task, seed=SEED, specs={spec})
        assert _rows(task, answer, tmp_path / spec)[spec], f"the answer misses {spec}"


@pytest.mark.parametrize("specs", [set(), {"no_such_spec"}, {"settling", "no_such_spec"}])
def test_a_search_is_aimed_only_at_headline_specs_the_task_has(specs: set[str]) -> None:
    _aimable()
    task = parse_task(json.dumps(_composing(0)).encode())
    with pytest.raises(ValueError, match="headline"):
        synthesise.search(task, specs=specs)


def test_a_search_is_never_aimed_at_a_secondary_spec() -> None:
    _aimable()
    task = parse_task(json.dumps(_one_decides(0)).encode())
    with pytest.raises(ValueError, match="headline"):
        synthesise.search(task, specs={"settling"})


def test_on_a_tier_that_composes_every_one_requirement_answer_fails_its_scenario(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    store, version, held = _store(tmp_path, _composing)
    # Satisfiable: one controller meets both requirements together.
    both = synthesise.search(held[0], seed=SEED)
    assert all(_rows(held[0], both, tmp_path / "both").values())
    result = _probe(store, version, capsys)
    findings = result["findings"]
    assert findings["tasks"] == 8
    assert findings["answers"]["found"] == 16 and findings["answers"]["fail"] == 16
    assert findings["tasks_failed_by_every_single_requirement_answer"] == 8
    assert findings["tasks_passed_by_a_single_requirement_answer"] == 0
    assert _composes(result)


def test_on_a_tier_whose_scenarios_turn_on_one_requirement_the_probe_goes_red(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    store, version, _ = _store(tmp_path, _one_decides)
    result = _probe(store, version, capsys)
    findings = result["findings"]
    assert findings["tasks_passed_by_a_single_requirement_answer"] == 8
    assert findings["answers"]["pass"] == 16
    with pytest.raises(AssertionError):
        assert _composes(result), "the probe's check holds on a tier that does not compose"


def test_the_same_tier_and_seed_give_the_same_counts_and_key(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    store, version, _ = _store(tmp_path, _one_decides)
    first, second = _probe(store, version, capsys), _probe(store, version, capsys)
    assert first["findings"] == second["findings"]
    assert first["measurement"]["key"] == second["measurement"]["key"]
    assert (first["measurement"]["count"], second["measurement"]["count"]) == (1, 2)
    assert first["method"]["generations"] == synthesise.GENERATIONS
