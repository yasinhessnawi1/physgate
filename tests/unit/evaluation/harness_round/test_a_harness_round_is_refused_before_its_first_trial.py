"""A harness round is refused before its first trial, with its reason, and makes nothing.

Each refusal is read before any decomposition, any run directory, any ledger line and any
output: inside a harness session's environment; while a session left in the work root still
runs; a store a split left unclean; a version the role does not have,
or that the register marks exposed, or that has no record of its blind check; a run root that is
not registered; parameters that are not reportable, that leave a protected place of the store
open, or that do not look for every canary; a target whose worktree is not clean, or whose top
holds a run's configuration; a protected tier whose runs are not withheld from one another (until
the core withholds every run root of a store whole, every protected tier is). A held-out task the
check flagged is never run. The command says the refusal as one JSON line and exits 1.
"""

from __future__ import annotations

import json
import subprocess
import sys
import time
import uuid
from collections.abc import Callable
from pathlib import Path
from typing import Any

import pytest
from round_rig import SCORED, Rig, make_rig, protected_tiers_withheld

from physgate.cli import main
from physgate.evaluation.harness_round import RoundError, run_round
from physgate.evaluation.tiers.exposure import mark_exposed
from physgate.evaluation.tiers.store import BASELINE_DIR, PLACE, pool_dir, work_root
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


@pytest.mark.parametrize("tier", ["validation", "held_out"])
def test_a_protected_tier_is_refused_while_its_runs_are_not_withheld_from_one_another(
    tmp_path: Path, tier: str
) -> None:
    """Refused while the core has no whole-root withholding, and once it has, by its own rule."""
    rig = make_rig(tmp_path, withheld_whole=[])
    assert _refused(rig, tiers=(tier,)) in (
        "protected_tier_not_withheld",
        "run_root_not_withheld",
    )


def test_a_held_out_task_the_check_flagged_is_never_run(tmp_path: Path) -> None:
    rig = make_rig(tmp_path, store={"flagged": (0,)})
    flagged = rig.made.tasks["held_out"][0]
    driver = rig.driver()
    with protected_tiers_withheld():
        status, summary = run_round(
            rig.inputs(tiers=("held_out",), trials=1, tasks=None),
            driver=driver,
            scorer=_score,
            sleep=lambda _: None,
        )
    assert status == "done" and summary["tiers"]["held_out"]["trials"] == 7
    given = {c.brief.read_bytes() for c in driver.decomposed}
    assert len(given) == 7 and flagged.brief.encode() not in given


def test_the_command_says_its_refusal_as_one_json_line_and_exits_1(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    rig = make_rig(tmp_path, reportable=False)
    argv = [
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
        str(rig.run_root),
        "--target-from",
        str(rig.target),
        "--install",
        str(rig.root / "install"),
        "--prices",
        "2026-10-16",
        "--out",
        str(rig.root / "out"),
    ]
    assert main(argv) == 1
    printed = capsys.readouterr().out.strip().splitlines()
    assert len(printed) == 1
    said = json.loads(printed[0])
    assert said["refused_because"] == "params_not_reportable" and said["error"]
    assert not (rig.root / "out").exists()


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
