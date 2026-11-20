"""Every combination of the ablation switches runs to completion, or is refused before it starts.

ARCH-140's acceptance, as amended: every flag combination either runs to completion or is refused
at its configuration, before any action, by a rule that names it; none is refused once the run
has started. The matrix is every value of every switch ARCH-140 names that is built (the physics
gate, the plan's review, the role reviewers, the skill library, hook enforcement), crossed with
the run's kind (neither, reportable, ablation, or both at once). The register's other flags are
run conditions, each held at the value a measured run takes; a flag the matrix does not class
fails the census row, so a switch added later joins the matrix or is named as a condition.

Each combination is configured by ``physgate decompose`` itself, with a stand-in call and plan
reviewer, and an admitted one is driven by the real loop on real git (``ablation_matrix_rig``).

- **A refused combination** exits before the call: the refusal names one of the rules it
  breaks, stated here apart from the code (a run is one kind; a re-plan is an experiment's arm;
  each arm that removes a component is an ablation run's; a measured run reviews its plan), and
  nothing of the run exists afterwards: no configuration, no event line, no store, no queue, and
  the target's refs as they were.
- **An admitted combination** runs to its end (``done``) with no halt and no incident, and each
  switch behaves as its arm says, whatever the others are: the configuration and the run's
  opening record it; the gate refuses the first attempt under ``on``, records and lets it through
  under ``observe``, and is skipped under ``off``; the plan's review is recorded before anything
  is dispatched, or nothing of a review is; the role review runs with the paired rubric or its
  generalist, or is recorded as skipped and merges on the gate alone; every role session's
  installation reads the skill file and the target holds it, or neither; and every session is
  installed with the run's hooks value, the design discipline's three hooks wired or not and every
  other hook wired either way.

The plan's review under ``repair:1``, ``repair:2`` and ``repair:3`` is admitted for a reportable
run and runs to completion here, but no repair round is exercised: the stand-in plan reviewer
always passes the plan, so nothing is re-planned. These rows prove only that the value is
accepted, recorded, and reviewed once before any session. What a repair round does is held by
``test_repair_n_is_an_experiment_arm_of_a_reportable_run.py`` and
``test_a_re_planned_run_s_opening_holds_every_round_and_holds_on_the_last.py`` (on
``replan_rig``).
"""

from __future__ import annotations

import collections
import hashlib
import json
from pathlib import Path

import ablation_matrix_rig as rig
import pytest
from ablation_matrix_rig import Combination, Machine

import physgate.flags as flags
from physgate.hooks.settings import DISCIPLINE_HOOKS
from physgate.knowledge.promote import KNOWLEDGE_ROOT
from physgate.orchestrator import run_config
from physgate.reviewers.rubric import generalist_of, load_rubric

COMBINATIONS = rig.every_combination()
#: Every hook a role session keeps whatever the hooks value.
KEPT_HOOKS = {"sentinel", "tools", "paths", "shell_paths", "git_ops", "os_abort", "survivors"}
SKILL = f"knowledge/{rig.ROLE}/skill.md"
STANDARDS = (f"knowledge/{rig.ROLE}/standards.md", "knowledge/cross/standards.md")
#: What a run recorded before each switch existed reads as, and what its opening leaves out.
BEFORE = {"design_review": "off", **run_config.BEFORE_THE_SWITCH}


@pytest.fixture(scope="session")
def machine(tmp_path_factory: pytest.TempPathFactory) -> Machine:
    return rig.build_machine(tmp_path_factory.mktemp("machine"))


# -- what the matrix spans --------------------------------------------------------------------


def test_every_flag_of_the_register_is_a_switch_of_the_matrix_or_a_condition_it_holds() -> None:
    names = [flag.name for flag in flags.REGISTER]
    switches, conditions = set(rig.SWITCHES), set(rig.CONDITIONS)
    assert not switches & conditions
    assert switches | conditions == set(names), "a flag the matrix does not class"
    # Every switch ARCH-140 names is an axis, and the plan's review, which its amendment adds.
    assert {f.name for f in flags.REGISTER if f.architecture == "ARCH-140"} <= switches
    assert "design_review" in switches


def test_each_switch_takes_every_value_the_register_gives_it_and_each_is_built() -> None:
    by_name = {flag.name: flag for flag in flags.REGISTER}
    for name, values in rig.SWITCHES.items():
        assert values == by_name[name].values, name
        assert values == run_config.BUILT.get(name, values), f"{name}: a value is not built"


def test_each_condition_is_held_at_one_of_its_flag_s_values() -> None:
    by_name = {flag.name: flag for flag in flags.REGISTER}
    for name, (value, why) in rig.CONDITIONS.items():
        assert value in by_name[name].values, name
        assert why


def test_the_matrix_is_every_combination_once() -> None:
    sizes = [len(values) for values in rig.SWITCHES.values()]
    assert (
        len(COMBINATIONS) == len(rig.KINDS) * sizes[0] * sizes[1] * sizes[2] * sizes[3] * sizes[4]
    )
    assert len({c.label for c in COMBINATIONS}) == len(COMBINATIONS)


def test_the_matrix_as_counted() -> None:
    """The matrix, pasted: how many run, and how many each set of broken rules refuses."""
    admitted = [c for c in COMBINATIONS if not rig.expected_rules(c)]
    by_kind = collections.Counter(c.kind for c in admitted)
    refused = collections.Counter(
        " + ".join(rig.expected_rules(c)) for c in COMBINATIONS if rig.expected_rules(c)
    )
    assert len(COMBINATIONS) == 864
    assert len(admitted) == 96
    assert by_kind == {"ablation": 72, "reportable": 15, "ordinary": 9}
    assert sum(refused.values()) == 768
    one = "reviewers' arm is an ablation run's"
    skills, hooks = "skills' arm is an ablation run's", "hooks' arm is an ablation run's"
    replan = "a re-plan is an experiment's arm"
    assert refused == {
        "a run is one kind": 216,
        replan: 117,
        one: 54,
        f"{one} + {hooks}": 54,
        f"{one} + {skills}": 54,
        f"{one} + {skills} + {hooks}": 54,
        "a measured run reviews its plan": 39,
        hooks: 27,
        skills: 27,
        f"{skills} + {hooks}": 27,
        f"{replan} + {one}": 18,
        f"{replan} + {one} + {hooks}": 18,
        f"{replan} + {one} + {skills}": 18,
        f"{replan} + {one} + {skills} + {hooks}": 18,
        f"{replan} + {hooks}": 9,
        f"{replan} + {skills}": 9,
        f"{replan} + {skills} + {hooks}": 9,
    }


# -- every combination ------------------------------------------------------------------------


@pytest.mark.parametrize("c", COMBINATIONS, ids=[c.label for c in COMBINATIONS])
def test_the_combination_runs_to_completion_or_is_refused_before_its_first_line(
    c: Combination, machine: Machine, outside_tmp: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    rig.on_the_machine(monkeypatch, machine)
    decomposed = rig.decompose(outside_tmp, c, machine)
    expected = rig.expected_rules(c)
    if expected:
        _refused_before_anything(c, expected, decomposed, outside_tmp / "run")
    else:
        _runs_as_each_arm_says(c, decomposed, outside_tmp, machine)


def _refused_before_anything(
    c: Combination, expected: list[str], decomposed: rig.Decomposed, run_dir: Path
) -> None:
    assert decomposed.code == 2, f"{c.label} was not refused at its configuration"
    said = json.dumps(decomposed.error)
    assert any(rig.rule_text(rule, c) in said for rule in expected), (
        f"{c.label}: the refusal names none of {expected}: {said}"
    )
    assert decomposed.calls == 0, "the call was spent on a refused run"
    assert decomposed.plan_reviews == 0, "a plan reviewer was asked of a refused run"
    for name in ("run.json", "events.jsonl", "ledger.jsonl", "store", "queue.jsonl"):
        assert not (run_dir / name).exists(), f"{c.label}: a refused run left {name}"
    assert decomposed.refs_after == decomposed.refs_before, "a refused run touched its target"


def _runs_as_each_arm_says(
    c: Combination, decomposed: rig.Decomposed, root: Path, machine: Machine
) -> None:
    assert decomposed.code == 0, f"{c.label} was refused: {decomposed.error}"
    assert decomposed.calls == 1
    driven = rig.drive(root, machine)
    log = rig.lines(root / "run")
    kinds = [line["kind"] for line in log]
    assert driven.step == "done", f"{c.label} ended on {driven.step}"
    assert not {"halted", "incident", "escalated", "subtask_rejected"} & set(kinds), kinds
    merged = [line for line in log if line["kind"] == "merged"]
    assert len(merged) == 1, kinds
    _recorded(c, driven, log, root / "run")
    _gate(c, driven, log, merged[0]["attempt"])
    _plan_review(c, decomposed, kinds)
    _role_review(c, driven, log, merged[0]["attempt"], root / "run", machine)
    _skills(c, driven, root / "target")
    _hooks(c, driven)


def _recorded(
    c: Combination, driven: rig.Driven, log: list[dict[str, object]], run_dir: Path
) -> None:
    config = driven.config
    for name, value in c.switches.items():
        assert getattr(config, name) == value, name
    assert (config.reportable, config.ablation) == (c.reportable, c.ablation)
    opening = log[0]
    assert opening["kind"] == "run_started"
    assert (
        opening["config_sha256"] == hashlib.sha256((run_dir / "run.json").read_bytes()).hexdigest()
    )
    assert opening["gate_mode"] == c.gate_mode
    for name in ("design_review", "reviewers", "skills", "hooks"):
        # Carried where it differs from what a run before the switch ran under, and only there.
        value = getattr(c, name)
        assert opening.get(name, BEFORE[name]) == value, name
        assert (name in opening) == (value != BEFORE[name]), name
    assert opening.get("ablation", False) is c.ablation


def _gate(c: Combination, driven: rig.Driven, log: list[dict[str, object]], merged: object) -> None:
    gate_lines = [line for line in log if line["kind"] in ("gate_ran", "gate_skipped")]
    rejected = [line["attempt"] for line in log if line["kind"] == "attempt_rejected"]
    if c.gate_mode == "off":
        assert [line["kind"] for line in gate_lines] == ["gate_skipped"]
        assert driven.gate.calls == 0
        assert (merged, rejected) == (1, [])
    elif c.gate_mode == "observe":
        (ran,) = gate_lines
        result = ran["result"]
        assert isinstance(result, dict)
        assert (result["verdict"], result["mode"]) == ("fail", "observe")
        assert (merged, rejected) == (1, []), "observe refused an attempt"
    else:
        verdicts = [line["result"]["verdict"] for line in gate_lines]  # type: ignore[index]
        assert verdicts == ["fail", "pass"]
        assert (merged, rejected) == (2, [1]), "the gate's refusal did not hold"


def _plan_review(c: Combination, decomposed: rig.Decomposed, kinds: list[str]) -> None:
    if c.design_review == "off":
        assert "design_review_ran" not in kinds
        assert decomposed.plan_reviews == 0
        return
    assert kinds.count("design_review_ran") == 1
    assert decomposed.plan_reviews == 1
    assert kinds.index("design_review_ran") < kinds.index("session_ended"), (
        "a session ran before the plan's review"
    )


def _role_review(
    c: Combination,
    driven: rig.Driven,
    log: list[dict[str, object]],
    merged: object,
    run_dir: Path,
    machine: Machine,
) -> None:
    ran = [line for line in log if line["kind"] == "review_ran"]
    skipped = [line for line in log if line["kind"] == "review_skipped"]
    seen = sum(len(reviewer.seen) for reviewer in driven.reviewers.values())
    ledger = json.loads((run_dir / "ledger.jsonl").read_text().splitlines()[-1])
    if c.reviewers == "off":
        assert ran == [] and seen == 0, "a reviewer was invoked under reviewers: off"
        assert [(line["attempt"], line["reason"]) for line in skipped] == [
            (merged, "reviewers=off")
        ]
        assert ledger["review_result"] == "skipped"
        return
    assert skipped == []
    assert [line["attempt"] for line in ran] == [merged] and seen == 1
    paired = load_rubric(machine.library / KNOWLEDGE_ROOT, rig.ROLE)
    rubric = paired if c.reviewers == "paired" else generalist_of(paired)
    result = ran[0]["result"]
    assert isinstance(result, dict)
    assert (result["rubric_kind"], result["rubric_sha256"]) == (c.reviewers, rubric.sha256)
    assert ledger["review_result"] == "pass"


def _skills(c: Combination, driven: rig.Driven, target: Path) -> None:
    for installed in driven.session.installed:
        given = [*installed.values("--reading"), *installed.values("--always-loaded")]
        read = {path for path in given if path.endswith(SKILL)}
        assert bool(read) == (c.skills == "on"), f"skills: {c.skills} read {sorted(read)}"
        for standards in STANDARDS:
            assert any(path.endswith(standards) for path in installed.values("--always-loaded"))
    commit = driven.session.requests[0].spec_commit
    assert commit is not None
    tree = rig.files_at(target, commit)
    assert (SKILL in tree) == (c.skills == "on"), f"skills: {c.skills}, the target holds {SKILL}"
    assert set(STANDARDS) <= set(tree)


def _hooks(c: Combination, driven: rig.Driven) -> None:
    assert driven.session.installed, "no role session was installed"
    for installed in driven.session.installed:
        assert installed.values("--hooks") == [c.hooks]
        wired = installed.wired()
        assert wired >= KEPT_HOOKS, f"hooks: {c.hooks} dropped {sorted(KEPT_HOOKS - wired)}"
        if c.hooks == "on":
            assert set(DISCIPLINE_HOOKS) <= wired
        else:
            assert not set(DISCIPLINE_HOOKS) & wired
            assert installed.values("--run-config"), "hooks: off installed without the record"
