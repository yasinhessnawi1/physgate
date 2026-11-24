"""A killed harness round is started again and goes on: no trial repeated, none skipped.

Every step the round takes is written in its ledger, and synced, before it is taken; each trial's
state is then read from its run's own lines. So a round killed before any line of its ledger,
started again with ``resume``, ends with the records an unkilled round ends with: each trial
decomposed once, in one directory, and every run set naming those directories alone. A run
killed while it was driven is resumed (``physgate resume``), never decomposed again. A
decomposition killed after it recorded its parameters left no run to resume: its directory is
set aside, named in the ledger, and the trial's run is made in a fresh one, its once-more not
spent. A resume given other inputs than the round was started with is refused.
"""

from __future__ import annotations

import json
import subprocess
from pathlib import Path
from typing import Any

import pytest
from round_rig import SCORED, Killed, Rig, StandInDriver, make_rig

from physgate.evaluation import harness_round
from physgate.evaluation.baseline.runner import RunSet
from physgate.evaluation.harness_round import (
    HARNESS_ROUNDS,
    LEDGER,
    ROUND_RECORD,
    RoundError,
    run_round,
)
from physgate.evaluation.tiers.exposure import run_roots, survey
from physgate.evaluation.tiers.store import withheld_root
from physgate.orchestrator.events import Resumed, RunStarted, read_events


def _score(_task: Any, _answer: Path) -> dict[str, Any]:  # noqa: ANN401
    return dict(SCORED)


def _round(rig: Rig, driver: StandInDriver, *, resume: bool = False, **changes: Any) -> Any:  # noqa: ANN401
    return run_round(
        rig.inputs(**changes), driver=driver, scorer=_score, resume=resume, sleep=lambda _: None
    )


def _place(rig: Rig) -> Path:
    summary = json.loads((rig.root / "out" / ROUND_RECORD).read_bytes())
    return withheld_root(rig.made.store, "control") / HARNESS_ROUNDS / str(summary["round"])


def _ledger(rig: Rig) -> list[dict[str, Any]]:
    return [json.loads(x) for x in (_place(rig) / LEDGER).read_bytes().splitlines()]


def _outcomes(rig: Rig) -> list[tuple[int, str]]:
    lines = (rig.root / "out" / "visible.trials.jsonl").read_text().splitlines()
    return [(json.loads(x)["trial"], json.loads(x)["outcome"]) for x in lines]


def _run_dirs(rig: Rig) -> list[str]:
    runs = RunSet.model_validate_json((rig.root / "out" / "visible.runs.json").read_bytes())
    return [Path(e.run_dir).name for e in runs.trials]


@pytest.fixture(scope="module")
def unkilled(tmp_path_factory: pytest.TempPathFactory) -> tuple[list[str], int]:
    """What the round's ledger holds when nothing kills it: its kinds, line by line."""
    rig = make_rig(tmp_path_factory.mktemp("unkilled"))
    _round(rig, rig.driver())
    return [x["kind"] for x in _ledger(rig)], len(_ledger(rig))


def test_the_unkilled_round_s_ledger_names_each_step_before_it_is_taken(
    unkilled: tuple[list[str], int],
) -> None:
    kinds, _ = unkilled
    assert kinds == ["round", "placed", "assembled", "placed", "assembled", "ended"]


@pytest.mark.parametrize("after", range(6))
def test_a_round_killed_before_any_line_of_its_ledger_resumes_to_the_same_end(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, unkilled: tuple[list[str], int], after: int
) -> None:
    kinds, _ = unkilled
    rig = make_rig(tmp_path)
    first = rig.driver()
    written = harness_round._append  # noqa: SLF001 - the ledger's one writer, killed after a line
    count = [0]

    def killed_after(ledger: Path, line: Any) -> None:  # noqa: ANN401
        # Killed once ``after`` lines are written: before the first, at ``after`` 0.
        if count[0] == after:
            raise Killed
        written(ledger, line)
        count[0] += 1

    monkeypatch.setattr(harness_round, "_append", killed_after)
    with pytest.raises(Killed):
        _round(rig, first)
    monkeypatch.setattr(harness_round, "_append", written)
    then = rig.driver()
    status, summary = _round(rig, then, resume=True)
    assert status == "done" and summary["done"] is True
    assert [x["kind"] for x in _ledger(rig)] == kinds
    assert _outcomes(rig) == [(0, "pass"), (1, "pass")]
    assert _run_dirs(rig) == ["0000-1", "0001-1"]
    # Each trial decomposed once, in its one directory, across both processes.
    decomposed = [c.run_dir.name for c in [*first.decomposed, *then.decomposed]]
    assert decomposed == ["0000-1", "0001-1"]
    made = sorted(p.name for p in (rig.run_root / summary["round"]).iterdir())
    assert made == ["0000-1", "0001-1"]


def test_a_run_killed_while_it_was_driven_is_resumed_and_never_decomposed_again(
    tmp_path: Path,
) -> None:
    rig = make_rig(tmp_path)
    first = rig.driver(killed={1})
    with pytest.raises(Killed):
        _round(rig, first)
    then = rig.driver()
    status, _ = _round(rig, then, resume=True)
    assert status == "done"
    assert [c.run_dir.name for c in first.decomposed] == ["0000-1"]
    assert [c.run_dir.name for c in then.decomposed] == ["0001-1"]
    assert [(d.run_dir.name, d.resume) for d in then.drives] == [
        ("0000-1", True),
        ("0001-1", False),
    ]
    events = read_events(rig.run_root / _place(rig).name / "0000-1" / "events.jsonl")
    assert sum(isinstance(e, RunStarted) for e in events) == 1
    assert any(isinstance(e, Resumed) for e in events)
    assert _outcomes(rig) == [(0, "pass"), (1, "pass")]


def test_a_decomposition_killed_after_its_parameters_is_set_aside_and_made_again(
    tmp_path: Path,
) -> None:
    rig = make_rig(tmp_path)
    first = rig.driver(killed_in_decompose={1})
    with pytest.raises(Killed):
        _round(rig, first)
    # What it left in the run root (the clone, the parameters' record) is read whole by the scan.
    seen = survey(rig.made.store, "control", run_roots(rig.made.store, "control"))
    assert seen.unread == () and seen.findings == ()
    then = rig.driver()
    status, summary = _round(rig, then, resume=True)
    assert status == "done"
    lines = _ledger(rig)
    left = [x for x in lines if x["kind"] == "left"]
    assert [(x["index"], x["attempt"]) for x in left] == [(0, 1)]
    assert not [x for x in lines if x["kind"] == "superseded"]
    assert _run_dirs(rig) == ["0000-2", "0001-1"]
    record = json.loads((_place(rig) / ROUND_RECORD).read_bytes())
    assert [(x["index"], x["attempt"]) for x in record["left"]] == [(0, 1)]
    # The set-aside directory stays where it was, for the exposure scan; no run in it.
    kept = rig.run_root / summary["round"] / "0000-1"
    assert kept.is_dir() and not (kept / "events.jsonl").exists()


def test_a_resume_with_other_inputs_than_the_round_was_started_with_is_refused(
    tmp_path: Path,
) -> None:
    rig = make_rig(tmp_path)
    with pytest.raises(Killed):
        _round(rig, rig.driver(killed={2}))
    later = rig.driver()
    with pytest.raises(RoundError) as refused:
        _round(rig, later, resume=True, trials=3)
    assert refused.value.context["refused_because"] == "inputs_differ"
    assert "trials" in refused.value.context["fields"]
    assert later.decomposed == [] and later.drives == []


def test_a_resume_of_a_directory_that_holds_no_round_is_refused(tmp_path: Path) -> None:
    rig = make_rig(tmp_path)
    driver = rig.driver()
    with pytest.raises(RoundError) as refused:
        _round(rig, driver, resume=True)
    assert refused.value.context["refused_because"] == "no_round"
    assert driver.decomposed == []


def test_a_second_round_into_an_output_directory_that_exists_is_refused(tmp_path: Path) -> None:
    rig = make_rig(tmp_path)
    (rig.root / "out").mkdir()
    driver = rig.driver()
    with pytest.raises(RoundError) as refused:
        _round(rig, driver)
    assert refused.value.context["refused_because"] == "out_exists"
    assert driver.decomposed == []


def test_a_ledger_line_a_kill_cut_off_is_dropped_and_its_step_taken_again(tmp_path: Path) -> None:
    rig = make_rig(tmp_path)
    with pytest.raises(Killed):
        _round(rig, rig.driver(killed={2}))
    with (_place(rig) / LEDGER).open("ab") as ledger:
        ledger.write(b'{"kind":"placed","ind')
    status, _ = _round(rig, rig.driver(), resume=True)
    assert status == "done"
    assert _outcomes(rig) == [(0, "pass"), (1, "pass")]
    assert (_place(rig) / LEDGER).read_bytes().endswith(b"\n")


def test_a_resume_after_the_target_moved_is_refused(tmp_path: Path) -> None:
    rig = make_rig(tmp_path)
    with pytest.raises(Killed):
        _round(rig, rig.driver(killed={2}))
    (rig.target / "later.txt").write_text("a later commit\n")
    for args in (["add", "-A"], ["commit", "-q", "-m", "later"]):
        subprocess.run(
            ["git", "-c", "user.email=t@example.invalid", "-c", "user.name=t", *args],
            cwd=rig.target,
            check=True,
            capture_output=True,
        )
    later = rig.driver()
    with pytest.raises(RoundError) as refused:
        _round(rig, later, resume=True)
    assert refused.value.context["refused_because"] == "inputs_differ"
    assert refused.value.context["fields"] == "target_head"
    assert later.decomposed == [] and later.drives == []
