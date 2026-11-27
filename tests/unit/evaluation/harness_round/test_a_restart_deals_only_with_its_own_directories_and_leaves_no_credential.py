"""A restart deals only with the directories its own round placed, and leaves no credential behind.

What the round's earlier process left is dealt with first, before any refusal can end the start:

- a left review whose stream cannot be read has its credential files removed all the same, at the
  first start, however the start then ends;
- only a directory reached beneath the run root through directories, never through a link (at the
  round's folder or at the trial's own), is dealt with by the restart: what a link leads to is not
  the round's (shown on a start refused once the restart has dealt with what is its own, so that
  nothing after the restart acts on the directory);
- a ledger that does not begin with its own round, and a start from inside a session, are refused
  before anything is touched.

The plan's review is on (``design_review: observe``), and the decomposition goes through the core's
own rounds with its call and its review scripted (the test rig's stand-in driver).
"""

from __future__ import annotations

import json
import os
import signal
from collections.abc import Iterator
from pathlib import Path
from typing import Any

import pytest
from round_rig import SCORED, Killed, Rig, StandInDriver, make_rig

from physgate.evaluation.harness_round import (
    HARNESS_ROUNDS,
    LEDGER,
    ROUND_RECORD,
    RoundError,
    run_round,
)
from physgate.evaluation.tiers.store import withheld_root
from physgate.orchestrator.processes import started_at


def _score(_task: Any, _answer: Path) -> dict[str, Any]:  # noqa: ANN401
    return dict(SCORED)


@pytest.fixture
def drivers() -> Iterator[list[StandInDriver]]:
    """Every driver a row makes; a review session one of them left running is stopped after."""
    made: list[StandInDriver] = []
    yield made
    for driver in made:
        for pid, _sid in driver.left_reviews:
            if started_at(pid) is not None:
                os.kill(pid, signal.SIGKILL)


def _driver(rig: Rig, drivers: list[StandInDriver], **how: Any) -> StandInDriver:  # noqa: ANN401
    driver = rig.driver(**how)
    drivers.append(driver)
    return driver


def _go(rig: Rig, driver: StandInDriver) -> str:
    """The restarted round's status, or the reason it was refused."""
    try:
        status, _ = run_round(
            rig.inputs(trials=1), driver=driver, scorer=_score, resume=True, sleep=lambda _: None
        )
    except RoundError as exc:
        return f"refused:{exc.context.get('refused_because')}"
    return status


def _refused_after_the_restart(rig: Rig, driver: StandInDriver) -> str:
    """A restart given another run root: refused once the round's own directories are dealt with."""
    elsewhere = rig.root / "another-run-root"
    elsewhere.mkdir(exist_ok=True)
    with pytest.raises(RoundError) as refused:
        run_round(
            rig.inputs(trials=1, run_root=elsewhere),
            driver=driver,
            scorer=_score,
            resume=True,
            sleep=lambda _: None,
        )
    return str(refused.value.context.get("refused_because"))


def _left(rig: Rig, drivers: list[StandInDriver]) -> int:
    """A round killed in its first trial's plan review; the review session's pid, still running."""
    first = _driver(rig, drivers, killed_in_review={1})
    with pytest.raises(Killed):
        run_round(rig.inputs(trials=1), driver=first, scorer=_score, sleep=lambda _: None)
    ((pid, _sid),) = first.left_reviews
    assert started_at(pid) is not None
    return pid


def _place(rig: Rig) -> Path:
    summary = json.loads((rig.root / "out" / ROUND_RECORD).read_bytes())
    return withheld_root(rig.made.store, "control") / HARNESS_ROUNDS / str(summary["round"])


def _keys(under: Path) -> list[Path]:
    """The credential files of sessions beneath ``under``, as a session's login puts one."""
    return [p for p in under.rglob("key") if p.parent.name == "state"]


@pytest.mark.parametrize("how", ["gone", "link"])
def test_a_left_review_whose_stream_cannot_be_read_leaves_no_credential_after_the_first_start(
    tmp_path: Path, drivers: list[StandInDriver], how: str
) -> None:
    rig = make_rig(tmp_path, design_review="observe")
    pid = _left(rig, drivers)
    left = rig.run_root / _place(rig).name / "0000-1"
    (stream,) = (left / "review").rglob("stdout.jsonl")
    stream.unlink()
    if how == "link":
        stream.symlink_to(left / "params_source.json")
    assert len(_keys(rig.run_root)) == 1
    status = _go(rig, _driver(rig, drivers))
    # The session is stopped and its credential gone, however the start then ends.
    assert started_at(pid) is None
    assert status.startswith("refused:"), status
    assert _keys(rig.run_root) == [], "a credential file stays beneath the run root"


def test_a_restart_deals_with_nothing_a_link_at_the_round_s_folder_leads_to(
    tmp_path: Path, drivers: list[StandInDriver]
) -> None:
    rig = make_rig(tmp_path, design_review="observe")
    pid = _left(rig, drivers)
    folder = rig.run_root / _place(rig).name
    elsewhere = rig.root / "elsewhere"
    elsewhere.mkdir()
    folder.rename(elsewhere / folder.name)
    folder.symlink_to(elsewhere / folder.name)
    assert _refused_after_the_restart(rig, _driver(rig, drivers)) == "run_root_not_registered"
    # What the link leads to lies outside the run root: not the round's, so left as it is.
    assert started_at(pid) is not None, "a restart dealt with a directory through a link"
    assert len(_keys(elsewhere)) == 1


def test_a_restart_deals_with_nothing_a_link_at_the_trial_s_directory_leads_to(
    tmp_path: Path, drivers: list[StandInDriver]
) -> None:
    rig = make_rig(tmp_path, design_review="observe")
    pid = _left(rig, drivers)
    trial = rig.run_root / _place(rig).name / "0000-1"
    elsewhere = rig.root / "elsewhere"
    elsewhere.mkdir()
    trial.rename(elsewhere / trial.name)
    trial.symlink_to(elsewhere / trial.name)
    assert _refused_after_the_restart(rig, _driver(rig, drivers)) == "run_root_not_registered"
    assert started_at(pid) is not None, "a restart dealt with a directory through a link"
    assert len(_keys(elsewhere)) == 1


def test_a_restart_refused_after_it_deals_with_its_own_directories_has_dealt_with_them(
    tmp_path: Path, drivers: list[StandInDriver]
) -> None:
    rig = make_rig(tmp_path, design_review="observe")
    pid = _left(rig, drivers)
    assert _refused_after_the_restart(rig, _driver(rig, drivers)) == "run_root_not_registered"
    assert started_at(pid) is None and _keys(rig.run_root) == []


def test_a_restart_whose_ledger_begins_with_another_round_touches_nothing(
    tmp_path: Path, drivers: list[StandInDriver]
) -> None:
    rig = make_rig(tmp_path, design_review="observe")
    pid = _left(rig, drivers)
    ledger = _place(rig) / LEDGER
    first, *rest = ledger.read_bytes().splitlines(keepends=True)
    header = json.loads(first)
    header["round"] = "f" * 16
    ledger.write_bytes(json.dumps(header).encode() + b"\n" + b"".join(rest))
    status = _go(rig, _driver(rig, drivers))
    assert status == "refused:ledger_unreadable"
    assert started_at(pid) is not None and len(_keys(rig.run_root)) == 1


def test_a_restart_from_inside_a_session_is_refused_before_it_touches_anything(
    tmp_path: Path, drivers: list[StandInDriver], monkeypatch: pytest.MonkeyPatch
) -> None:
    rig = make_rig(tmp_path, design_review="observe")
    pid = _left(rig, drivers)
    with monkeypatch.context() as patch:
        patch.setenv("CLAUDE_CODE_TMPDIR", str(tmp_path / "a-session-s-own"))
        status = _go(rig, _driver(rig, drivers))
    assert status == "refused:inside_a_session"
    assert started_at(pid) is not None and len(_keys(rig.run_root)) == 1
