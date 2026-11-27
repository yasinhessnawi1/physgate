"""A harness round is refused before its first trial, with its reason, and makes nothing.

Each refusal is read before any decomposition, any run directory, any ledger line and any
output: inside a harness session's environment; while a session left in the work root still
runs; a store a split left unclean; a version the role does not have,
or that the register marks exposed, or that has no record of its blind check; a run root that is
not registered, that is not spelt as the disk spells it, or beneath which the core would refuse a
trial's review root (a telltale word in its path, a checkout around it); parameters that are not
reportable, that leave a protected place of the store open, or that do not look for every
canary; parameters of any tier whose trials are not withheld from one another (the core's rule:
every registered run root of the store withheld whole, nothing else, every root spelt as on
disk); a target whose worktree is not clean, or whose top holds a run's configuration. A held-out
task the check flagged is never run. The command says the refusal as one JSON line and exits 1.
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
import time
import uuid
from collections.abc import Callable
from pathlib import Path
from typing import Any

import pytest
from round_rig import SCORED, Rig, make_rig

from physgate.cli import main
from physgate.evaluation.harness_round import RoundError, run_round
from physgate.evaluation.tiers import exposure
from physgate.evaluation.tiers.exposure import add_run_root, mark_exposed, run_roots
from physgate.evaluation.tiers.issued import issued_bytes
from physgate.evaluation.tiers.store import (
    BASELINE_DIR,
    PLACE,
    pool_dir,
    withheld_root,
    work_root,
)
from physgate.orchestrator.processes import started_at


def _score(_task: Any, _answer: Path) -> dict[str, Any]:  # noqa: ANN401
    return dict(SCORED)


def _refused(rig: Rig, **changes: Any) -> str:  # noqa: ANN401
    driver = rig.driver()
    try:
        run_round(rig.inputs(**changes), driver=driver, scorer=_score, sleep=lambda _: None)
    except RoundError as exc:
        reason = str(exc.context["refused_because"])
    except Exception as exc:  # noqa: BLE001 - what stopped it instead is the row's failure
        reason = f"stopped: {type(exc).__name__}"
    else:
        reason = "not refused"
    assert driver.decomposed == [] and driver.drives == [], f"a trial was started ({reason})"
    assert not (rig.root / "out").exists()
    assert list(rig.run_root.iterdir()) == []
    return reason


def _params(rig: Rig, change: Callable[[dict[str, Any]], None]) -> None:
    fields = json.loads(rig.params.read_text())
    change(fields)
    rig.params.write_text(json.dumps(fields))


def test_a_round_is_refused_inside_a_harness_session(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    rig = make_rig(tmp_path)
    monkeypatch.setenv("CLAUDE_CODE_TMPDIR", str(tmp_path / "session-tmp"))
    assert _refused(rig) == "inside_a_session"


def test_a_round_is_refused_while_a_session_left_in_the_work_root_still_runs(
    tmp_path: Path,
) -> None:
    rig = make_rig(tmp_path)
    # A session's place a killed runner left, its process still running.
    sid = str(uuid.uuid4())
    process = subprocess.Popen(  # noqa: S603 - this interpreter, fixed arguments
        [sys.executable, "-c", "import time; time.sleep(120)", "--session-id", sid],
        start_new_session=True,
    )
    try:
        started = None
        for _ in range(200):
            started = started_at(process.pid)
            if started is not None:
                break
            time.sleep(0.05)
        assert started is not None
        session = work_root(rig.made.store, "control") / f"{BASELINE_DIR}-dead-0001-1"
        session = session / PLACE / "session"
        session.mkdir(parents=True)
        facts = {"pid": process.pid, "started": started, "session_id": sid, "kind": "raw"}
        (session / "process.json").write_text(json.dumps(facts))
        assert _refused(rig) == "session_lives"
    finally:
        process.kill()
        process.wait()


def test_a_round_is_refused_on_a_store_a_split_left_unclean(tmp_path: Path) -> None:
    rig = make_rig(tmp_path)
    (pool_dir(rig.made.store, "control") / "control.left").mkdir(parents=True)
    assert _refused(rig) == "pool_left"


def test_a_round_is_refused_on_a_version_the_role_does_not_have(tmp_path: Path) -> None:
    rig = make_rig(tmp_path)
    assert _refused(rig, version="f" * 64) == "version_unknown"


def test_a_round_is_refused_on_a_version_the_register_marks_exposed(tmp_path: Path) -> None:
    rig = make_rig(tmp_path)
    mark_exposed(rig.made.store, "control", rig.made.version, by="a person", reason="opened it")
    assert _refused(rig) == "version_exposed"


def test_a_round_is_refused_on_a_version_with_no_record_of_its_blind_check(
    tmp_path: Path,
) -> None:
    rig = make_rig(tmp_path, store={"checked": False})
    assert _refused(rig) == "held_out_unchecked"


def test_a_round_is_refused_with_a_run_root_that_is_not_registered(tmp_path: Path) -> None:
    rig = make_rig(tmp_path)
    other = rig.root / "elsewhere"
    other.mkdir()
    assert _refused(rig, run_root=other) == "run_root_not_registered"


def test_a_round_is_refused_with_parameters_that_are_not_reportable(tmp_path: Path) -> None:
    rig = make_rig(tmp_path, reportable=False)
    assert _refused(rig) == "params_not_reportable"


def test_a_round_is_refused_with_parameters_that_leave_a_protected_place_open(
    tmp_path: Path,
) -> None:
    rig = make_rig(tmp_path)

    def drop_work_root(fields: dict[str, Any]) -> None:
        work = str(work_root(rig.made.store, "control"))
        fields["held_out"] = [h for h in fields["held_out"] if h != work]

    _params(rig, drop_work_root)
    assert _refused(rig) == "work_root_not_named"


def test_a_round_is_refused_with_parameters_that_do_not_look_for_every_canary(
    tmp_path: Path,
) -> None:
    rig = make_rig(tmp_path)
    _params(rig, lambda fields: fields.update(held_out_canaries=fields["held_out_canaries"][1:]))
    assert _refused(rig) == "canaries_not_looked_for"


def test_a_round_is_refused_with_a_target_whose_worktree_is_not_clean(tmp_path: Path) -> None:
    rig = make_rig(tmp_path)
    (rig.target / "notes.txt").write_text("not committed\n")
    assert _refused(rig) == "target_not_clean"


def test_a_round_is_refused_with_a_target_whose_top_holds_a_run(tmp_path: Path) -> None:
    rig = make_rig(tmp_path)
    (rig.target / "run.json").write_text("{}\n")
    assert _refused(rig) == "target_holds_a_run"


def _withhold_whole(rig: Rig, roots: object) -> None:
    _params(rig, lambda fields: fields.update(withheld_whole=roots))


def _registered(rig: Rig) -> list[str]:
    return [str(r) for r in run_roots(rig.made.store, "control")]


@pytest.mark.parametrize("tier", ["visible", "validation", "held_out"])
def test_a_round_of_any_tier_whose_parameters_leave_a_run_root_out_is_refused_by_the_core_s_rule(
    tmp_path: Path, tier: str
) -> None:
    """A visible tier's trials lie beside one another as a protected tier's do: none is let off."""
    rig = make_rig(tmp_path, withheld_whole=[])
    assert _refused(rig, tiers=(tier,)) == "run_root_not_withheld"


def test_a_round_whose_parameters_withhold_whole_a_root_that_is_no_run_root_is_refused(
    tmp_path: Path,
) -> None:
    rig = make_rig(tmp_path)
    (rig.root / "other").mkdir()
    _withhold_whole(rig, [*_registered(rig), str(rig.root / "other")])
    assert _refused(rig) == "withheld_whole_not_a_run_root"


@pytest.mark.parametrize("given", ["a string", "a number among the roots", "a root twice"])
def test_a_round_whose_parameters_name_their_roots_withheld_whole_otherwise_is_refused(
    tmp_path: Path, given: str
) -> None:
    rig = make_rig(tmp_path)
    roots = _registered(rig)
    named = {
        "a string": roots[0],
        "a number among the roots": [*roots, 7],
        "a root twice": [*roots, roots[0]],
    }
    _withhold_whole(rig, named[given])
    assert _refused(rig) == "params_unreadable"


def test_a_round_on_a_store_whose_register_spells_a_run_root_through_a_linked_parent_is_refused(
    tmp_path: Path,
) -> None:
    """A line written before the core's spelling rule; the round's own root is spelt as on disk."""
    rig = make_rig(tmp_path)
    (rig.root / "real" / "runs").mkdir(parents=True)
    os.symlink(rig.root / "real", rig.root / "link")
    spelt = rig.root / "link" / "runs"
    exposure._append(  # noqa: SLF001
        withheld_root(rig.made.store, "control"),
        exposure.RUN_ROOTS,
        [{"kind": "run_root", "path": str(spelt)}],
    )
    _withhold_whole(rig, _registered(rig))
    assert str(spelt) in _registered(rig)
    assert _refused(rig) == "run_root_not_spelt_as_on_disk"


def test_a_round_given_its_run_root_through_a_linked_parent_is_refused(tmp_path: Path) -> None:
    rig = make_rig(tmp_path)
    os.symlink(rig.root, rig.root.parent / f"{rig.root.name}-link")
    linked = rig.root.parent / f"{rig.root.name}-link" / rig.run_root.name
    assert _refused(rig, run_root=linked) == "run_root_not_spelt_as_on_disk"


def test_a_round_given_its_run_root_in_another_case_is_refused(tmp_path: Path) -> None:
    rig = make_rig(tmp_path)
    other = rig.run_root.with_name(rig.run_root.name.swapcase())
    if not other.exists():
        pytest.skip("this volume tells cases apart, so another case names no directory")
    assert _refused(rig, run_root=other) == "run_root_not_spelt_as_on_disk"


@pytest.mark.parametrize(
    ("where", "reason"),
    [("telltale", "run_root_telltale"), ("checkout", "run_root_in_a_checkout")],
)
def test_a_round_whose_run_root_no_trial_may_review_beneath_is_refused(
    tmp_path: Path, where: str, reason: str
) -> None:
    """The core refuses at every run a review root whose path tells, or that lies in a checkout."""
    rig = make_rig(tmp_path)
    if where == "telltale":
        root = rig.root / "answers" / "runs"
        root.mkdir(parents=True)
    else:
        repo = rig.root / "repo"
        repo.mkdir()
        subprocess.run(["git", "init", "-q", str(repo)], check=True, capture_output=True)
        root = repo / "runs"
        root.mkdir()
    assert add_run_root(rig.made.store, "control", root)
    _withhold_whole(rig, _registered(rig))
    assert _refused(rig, run_root=root) == reason
    assert list(root.iterdir()) == []


def test_a_held_out_task_the_check_flagged_is_never_run(tmp_path: Path) -> None:
    rig = make_rig(tmp_path, store={"flagged": (0,)})
    flagged = rig.made.tasks["held_out"][0]
    driver = rig.driver()
    status, summary = run_round(
        rig.inputs(tiers=("held_out",), trials=1, tasks=None),
        driver=driver,
        scorer=_score,
        sleep=lambda _: None,
    )
    assert status == "done" and summary["tiers"]["held_out"]["trials"] == 7
    given = {c.brief.read_bytes() for c in driver.decomposed}
    assert len(given) == 7 and issued_bytes(flagged) not in given


def _command(rig: Rig, run_root: Path) -> list[str]:
    return [
        "harness-round",
        "--store",
        str(rig.made.store),
        "--role",
        "control",
        "--version",
        rig.made.version,
        "--tier",
        "visible",
        "--trials",
        "1",
        "--seed-base",
        "100",
        "--params",
        str(rig.params),
        "--run-root",
        str(run_root),
        "--target-from",
        str(rig.target),
        "--install",
        str(rig.root / "install"),
        "--prices",
        "2026-10-16",
        "--out",
        str(rig.root / "out"),
    ]


def _said(capsys: pytest.CaptureFixture[str]) -> dict[str, Any]:
    printed = capsys.readouterr().out.strip().splitlines()
    assert len(printed) == 1
    said: dict[str, Any] = json.loads(printed[0])
    return said


def test_the_command_says_its_refusal_as_one_json_line_and_exits_1(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    rig = make_rig(tmp_path, reportable=False)
    assert main(_command(rig, rig.run_root)) == 1
    said = _said(capsys)
    assert said["refused_because"] == "params_not_reportable" and said["error"]
    assert not (rig.root / "out").exists()


def test_the_command_given_its_run_root_through_a_linked_parent_refuses_it(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """The command hands the root on as it was typed, so the spelling rule sees the link."""
    rig = make_rig(tmp_path)
    os.symlink(rig.root, rig.root.parent / f"{rig.root.name}-link")
    linked = rig.root.parent / f"{rig.root.name}-link" / rig.run_root.name
    assert main(_command(rig, linked)) == 1
    assert _said(capsys)["refused_because"] == "run_root_not_spelt_as_on_disk"
    assert not (rig.root / "out").exists() and list(rig.run_root.iterdir()) == []


@pytest.mark.parametrize(
    ("word", "reason"),
    [
        ({"set_aside": 0}, "set_aside_not_waiting"),
        ({"limit_reset": True}, "limit_reset_not_waiting"),
    ],
)
def test_a_fresh_round_given_a_person_s_word_is_refused_before_anything_is_made(
    tmp_path: Path, word: dict[str, Any], reason: str
) -> None:
    rig = make_rig(tmp_path)
    driver = rig.driver()
    with pytest.raises(RoundError) as refused:
        run_round(rig.inputs(), driver=driver, scorer=_score, sleep=lambda _: None, **word)
    assert refused.value.context["refused_because"] == reason
    assert not (rig.root / "out").exists() and list(rig.run_root.iterdir()) == []


@pytest.mark.parametrize("inside", ["run root", "target", "store"])
def test_a_round_whose_output_directory_lies_in_its_run_root_target_or_store_is_refused(
    tmp_path: Path, inside: str
) -> None:
    rig = make_rig(tmp_path)
    where = {"run root": rig.run_root, "target": rig.target, "store": rig.made.store}[inside]
    assert _refused(rig, out=where / "round-out") == "out_misplaced"
    assert not (where / "round-out").exists()
