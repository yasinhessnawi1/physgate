"""The account's usage limit never spends a trial's attempt and never makes it ``unscored``.

A usage-limit end, at the decomposition or inside a session, any number of times and in any order
with the machine's other ends, leaves the trial where it was: the round stops as waiting for the
limit (exit 75) and goes on when it is started again after the reset. Nothing is superseded,
counted or spent on it: a decomposition that ended on the limit is named in the ledger and the
round's record with its spend, apart from the superseded runs, and the trial's one more go (a
fresh decomposition, or a resume after a machine halt) is still whole after it.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from round_rig import SCORED, Rig, StandInDriver, make_rig

from physgate.evaluation.harness_round import HARNESS_ROUNDS, LEDGER, ROUND_RECORD, run_round
from physgate.evaluation.tiers.store import withheld_root
from physgate.orchestrator.events import Halted, read_events


def _score(_task: Any, _answer: Path) -> dict[str, Any]:  # noqa: ANN401
    return dict(SCORED)


def _round(
    rig: Rig,
    driver: StandInDriver,
    slept: list[float] | None = None,
    *,
    resume: bool = False,
    limit_reset: bool = False,
) -> Any:  # noqa: ANN401
    return run_round(
        rig.inputs(trials=1),
        driver=driver,
        scorer=_score,
        resume=resume,
        limit_reset=limit_reset,
        sleep=(slept.append if slept is not None else (lambda _: None)),
    )


def _place(rig: Rig) -> Path:
    summary = json.loads((rig.root / "out" / ROUND_RECORD).read_bytes())
    return withheld_root(rig.made.store, "control") / HARNESS_ROUNDS / str(summary["round"])


def _ledger(rig: Rig, kind: str) -> list[dict[str, Any]]:
    lines = [json.loads(x) for x in (_place(rig) / LEDGER).read_bytes().splitlines()]
    return [x for x in lines if x["kind"] == kind]


def _outcomes(rig: Rig) -> list[str]:
    path = rig.root / "out" / "visible.trials.jsonl"
    if not path.exists():
        return []
    return [json.loads(x)["outcome"] for x in path.read_text().splitlines()]


def _halts(rig: Rig, name: str) -> list[str]:
    events = read_events(rig.run_root / _place(rig).name / name / "events.jsonl")
    return [e.reason for e in events if isinstance(e, Halted)]


def test_a_decomposition_on_the_limit_then_one_the_machine_ended_still_gets_its_fresh_decomposition(
    tmp_path: Path,
) -> None:
    rig, slept = make_rig(tmp_path), list[float]()
    status, _ = _round(rig, rig.driver(fails={1: "usage_limit"}), slept)
    assert status == "waiting_for_limit"
    then = rig.driver(fails={1: "api_error"})
    status, _ = _round(rig, then, slept, resume=True, limit_reset=True)
    assert status == "done"
    assert [c.run_dir.name for c in then.decomposed] == ["0000-2", "0000-3"]
    assert [(x["attempt"], x["cause"]) for x in _ledger(rig, "superseded")] == [(2, "api_error")]
    assert _outcomes(rig) == ["pass"]


def test_a_decomposition_on_the_limit_then_a_session_halted_on_the_machine_is_still_resumed(
    tmp_path: Path,
) -> None:
    rig = make_rig(tmp_path)
    _round(rig, rig.driver(fails={1: "usage_limit"}))
    then = rig.driver(infra={1, 2})
    status, _ = _round(rig, then, resume=True, limit_reset=True)
    assert status == "done"
    assert [(d.run_dir.name, d.resume) for d in then.drives] == [
        ("0000-2", False),
        ("0000-2", True),
    ]
    assert _outcomes(rig) == ["pass"]


def test_a_decomposition_on_the_limit_twice_waits_twice_and_spends_nothing(tmp_path: Path) -> None:
    rig = make_rig(tmp_path)
    status, _ = _round(rig, rig.driver(fails={1: "usage_limit"}))
    assert status == "waiting_for_limit"
    status, summary = _round(
        rig, rig.driver(fails={1: "usage_limit"}), resume=True, limit_reset=True
    )
    assert status == "waiting_for_limit" and summary["done"] is False
    assert _ledger(rig, "superseded") == [] and _ledger(rig, "assembled") == []
    then = rig.driver()
    status, _ = _round(rig, then, resume=True, limit_reset=True)
    assert status == "done" and _outcomes(rig) == ["pass"]
    assert [c.run_dir.name for c in then.decomposed] == ["0000-3"]
    # Each limit end is named with its spend, apart from the superseded runs.
    record = json.loads((_place(rig) / ROUND_RECORD).read_bytes())
    assert [(x["attempt"], x["tokens"]) for x in record["usage_limit"]] == [(1, 70), (2, 70)]
    assert record["superseded"] == []


def test_a_session_on_the_limit_then_a_machine_halt_is_still_resumed_once(tmp_path: Path) -> None:
    rig = make_rig(tmp_path)
    status, _ = _round(rig, rig.driver(limited={1}))
    assert status == "waiting_for_limit"
    then = rig.driver(infra={1, 2})
    status, _ = _round(rig, then, resume=True, limit_reset=True)
    assert status == "done"
    assert _halts(rig, "0000-1") == ["usage_limit", "infrastructure_exhausted"]
    assert [d.resume for d in then.drives] == [True, True]
    assert _outcomes(rig) == ["pass"]


def test_a_session_on_the_limit_twice_waits_twice_and_is_scored(tmp_path: Path) -> None:
    rig = make_rig(tmp_path)
    status, _ = _round(rig, rig.driver(limited={1}))
    assert status == "waiting_for_limit"
    status, _ = _round(rig, rig.driver(limited={1}), resume=True, limit_reset=True)
    assert status == "waiting_for_limit"
    status, _ = _round(rig, rig.driver(), resume=True, limit_reset=True)
    assert status == "done"
    assert _halts(rig, "0000-1") == ["usage_limit", "usage_limit"]
    assert _outcomes(rig) == ["pass"]


def test_a_machine_halt_resumed_then_a_session_on_the_limit_waits_and_is_scored(
    tmp_path: Path,
) -> None:
    rig = make_rig(tmp_path)
    status, _ = _round(rig, rig.driver(infra={1, 2}, limited={3}))
    assert status == "waiting_for_limit"
    status, _ = _round(rig, rig.driver(), resume=True, limit_reset=True)
    assert status == "done"
    assert _halts(rig, "0000-1") == ["infrastructure_exhausted", "usage_limit"]
    assert _outcomes(rig) == ["pass"]
