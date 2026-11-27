"""A run begun and never finished is a decomposition that spent its call, never a run to drive.

The plan's review is on (``design_review: observe``, as a measured run's is). A decomposition
opens its run's record (the log made, empty) once its call and the plan's review have ended, then
records the configuration, the branch, the commits and the opening a line at a time, and last the
round journal's terminal line. A directory left anywhere in that span holds a log, and the core
will never dispatch it: it refuses to run or resume it and says to decompose again into a fresh
directory. Such a directory is decided from what the core itself checks when it opens the run's
record, never from the log's name alone:

- no recorded configuration beside the log (the start raised, or was killed, before it wrote one);
- the core's record refusing to open it (the opening cut before its review, or the round journal
  with no terminal line or ending void);
- a record that opens with no line in its log.

It is superseded once, kept in place, named with its cause and its spend (read from the round
journal's end lines), out of the run set and the cap; one fresh decomposition follows after the
registered delay, and that is the trial's one more go. Once that is spent, the round stops for a
person until a restart names the trial. A run the machine, the limit or a refused credential
ended at its decomposition still takes its own path: its record opens.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest
from round_rig import SCORED, Killed, Rig, StandInDriver, make_rig

from physgate.evaluation import harness_round
from physgate.evaluation.harness_round import (
    HARNESS_ROUNDS,
    LEDGER,
    ROUND_RECORD,
    RoundError,
    run_round,
)
from physgate.evaluation.tiers.store import withheld_root

#: The decomposition's one call (70) and the plan's review (10), on the round journal's end line.
SPENT = 80


def _score(_task: Any, _answer: Path) -> dict[str, Any]:  # noqa: ANN401
    return dict(SCORED)


def _go(
    rig: Rig,
    driver: StandInDriver,
    slept: list[float],
    *,
    resume: bool = False,
    set_aside: int | None = None,
) -> tuple[str, dict[str, Any]]:
    """The round's status and summary, or the reason it was refused and its context."""
    try:
        status, summary = run_round(
            rig.inputs(trials=1),
            driver=driver,
            scorer=_score,
            resume=resume,
            set_aside=set_aside,
            sleep=slept.append,
        )
    except RoundError as exc:
        return f"refused:{exc.context.get('refused_because')}", {**exc.context, "said": str(exc)}
    except Exception as exc:  # noqa: BLE001 - what stopped it instead is the row's failure
        return f"stopped:{type(exc).__name__}", {"said": str(exc)}
    return status, summary


def _killed(rig: Rig, driver: StandInDriver, *, resume: bool = False) -> None:
    with pytest.raises(Killed):
        run_round(
            rig.inputs(trials=1), driver=driver, scorer=_score, resume=resume, sleep=lambda _: None
        )


def _place(rig: Rig) -> Path:
    summary = json.loads((rig.root / "out" / ROUND_RECORD).read_bytes())
    return withheld_root(rig.made.store, "control") / HARNESS_ROUNDS / str(summary["round"])


def _ledger(rig: Rig, kind: str) -> list[dict[str, Any]]:
    lines = [json.loads(x) for x in (_place(rig) / LEDGER).read_bytes().splitlines()]
    return [x for x in lines if x["kind"] == kind]


def _gone(rig: Rig) -> list[tuple[Any, ...]]:
    return [
        (x["attempt"], x["cause"], x["tokens"], x["by"], x["from_run"])
        for x in _ledger(rig, "superseded")
    ]


def _outcomes(rig: Rig) -> list[str]:
    path = rig.root / "out" / "visible.trials.jsonl"
    return (
        [json.loads(x)["outcome"] for x in path.read_text().splitlines()] if path.exists() else []
    )


def _directory(rig: Rig, name: str) -> Path:
    return rig.run_root / _place(rig).name / name


@pytest.mark.parametrize(
    "how",
    [
        {"killed_before_journal_end": {1}},
        {"killed_before_line": {1: "DesignReviewRan"}},
        {"killed_before_line": {1: "RunStarted"}},
    ],
    ids=["before the journal's last line", "before the opening's review", "before any line"],
)
def test_a_decomposition_killed_while_its_run_is_started_is_superseded_once_with_its_spend(
    tmp_path: Path, how: dict[str, Any]
) -> None:
    rig, slept = make_rig(tmp_path, design_review="observe"), list[float]()
    _killed(rig, rig.driver(**how))
    assert (_directory(rig, "0000-1") / "events.jsonl").is_file()
    then = rig.driver()
    status, _ = _go(rig, then, slept, resume=True)
    assert status == "done"
    assert _gone(rig) == [(1, "killed", SPENT, "rule", False)]
    assert [c.run_dir.name for c in then.decomposed] == ["0000-2"] and slept == [7.0]
    assert _ledger(rig, "left") == [] and _outcomes(rig) == ["pass"]
    runs = json.loads((rig.root / "out" / "visible.runs.json").read_bytes())
    assert [Path(t["run_dir"]).name for t in runs["trials"]] == ["0000-2"]
    # Kept where it was, for the exposure scan, and driven by nobody.
    assert then.drives and {d.run_dir.name for d in then.drives} == {"0000-2"}
    assert (_directory(rig, "0000-1") / "events.jsonl").is_file()


def test_the_core_s_own_start_raising_once_its_record_is_opened_is_superseded_with_its_spend(
    tmp_path: Path,
) -> None:
    rig, slept = make_rig(tmp_path, design_review="observe"), list[float]()
    driver = rig.driver(library_refused_at_start={1})
    status, _ = _go(rig, driver, slept)
    assert status == "done"
    ((attempt, cause, tokens, by, from_run),) = _gone(rig)
    assert (attempt, tokens, by, from_run) == (1, SPENT, "rule", False)
    assert cause != "killed", "the void the journal ended on is the cause"
    assert [c.run_dir.name for c in driver.decomposed] == ["0000-1", "0000-2"]
    assert _outcomes(rig) == ["pass"] and slept == [7.0]


def test_a_round_whose_start_raised_once_is_started_again_as_it_was(tmp_path: Path) -> None:
    rig, slept = make_rig(tmp_path, design_review="observe"), list[float]()
    status, _ = _go(rig, rig.driver(library_refused_at_start={1}), slept)
    assert status == "done"
    again = rig.driver()
    status, said = _go(rig, again, slept, resume=True)
    assert status == "done", said
    assert again.decomposed == [] and again.drives == []


def test_a_run_begun_and_never_finished_after_the_once_more_stops_the_round_for_a_person(
    tmp_path: Path,
) -> None:
    rig, slept = make_rig(tmp_path, design_review="observe"), list[float]()
    _killed(rig, rig.driver(killed_before_journal_end={1}))
    _killed(rig, rig.driver(killed_before_journal_end={1}), resume=True)
    again = rig.driver()
    status, summary = _go(rig, again, slept, resume=True)
    assert status == "waiting_for_a_person"
    assert again.decomposed == [] and again.drives == []
    waiting = summary["waiting"]
    assert (waiting["index"], waiting["cause"], waiting["tokens"]) == (0, "killed", SPENT)
    assert Path(waiting["run_dir"]).name == "0000-2"
    named = rig.driver()
    status, _ = _go(rig, named, slept, resume=True, set_aside=0)
    assert status == "done" and _outcomes(rig) == ["pass"]
    assert [c.run_dir.name for c in named.decomposed] == ["0000-3"]
    assert [(x[0], x[3]) for x in _gone(rig)] == [(1, "rule"), (2, "operator")]


@pytest.mark.parametrize(
    ("cause", "kind"),
    [("api_error", "superseded"), ("usage_limit", "limit"), ("credential_refused", "credential")],
)
def test_a_reviewed_decomposition_the_machine_the_limit_or_a_credential_ended_keeps_its_own_line(
    tmp_path: Path, cause: str, kind: str
) -> None:
    rig = make_rig(tmp_path, design_review="observe")
    _go(rig, rig.driver(fails={1: cause}), [])
    (line,) = _ledger(rig, kind)
    assert line["attempt"] == 1
    if kind == "superseded":
        assert (line["cause"], line["from_run"]) == ("api_error", True)


def test_a_run_whose_log_holds_a_line_no_orchestrator_wrote_is_a_run_for_the_core_to_refuse(
    tmp_path: Path,
) -> None:
    """Read of the directory alone: the store's scan refuses such a run before a round reads it."""
    rig = make_rig(tmp_path, design_review="observe")
    _killed(rig, rig.driver(killed_in_drive={1}))
    run_dir = _directory(rig, "0000-1")
    assert harness_round._state(run_dir) == "run"
    # A whole line the log's writer could not have written: the core's record refuses to open it,
    # for a reason a person looks at. It is no run begun and never finished.
    with (run_dir / "events.jsonl").open("ab") as log:
        log.write(b'{"written": "by nobody"}\n')
    assert harness_round._state(run_dir) == "run"


def test_a_decomposition_killed_before_its_configuration_is_recorded_is_superseded_on_restart(
    tmp_path: Path,
) -> None:
    rig, slept = make_rig(tmp_path, design_review="observe"), list[float]()
    _killed(rig, rig.driver(killed_before_configuration={1}))
    assert not (_directory(rig, "0000-1") / "run.json").exists()
    status, said = _go(rig, rig.driver(), slept, resume=True)
    assert status == "done", said
    assert _gone(rig) == [(1, "killed", SPENT, "rule", False)]
