"""One driver drives a round at a time.

A driver takes an exclusive lock on its round before it reads the ledger, and holds it for its
life. A second driver started on the same round meanwhile is refused at once, with a plain reason,
and writes nothing: so no trial is run twice and the ledger never names two runs for one trial. A
lock a dead driver left (its process gone, so the lock itself is free, its pid still recorded) is
recognised as such and taken over, and the ledger says so.
"""

from __future__ import annotations

import fcntl
import json
import os
from pathlib import Path
from typing import Any

import pytest
from round_rig import SCORED, Killed, Rig, make_rig

from physgate.evaluation.harness_round import (
    HARNESS_ROUNDS,
    LEDGER,
    ROUND_RECORD,
    RoundError,
    run_round,
)
from physgate.evaluation.tiers.store import withheld_root
from physgate.orchestrator.params_record import record_params

LOCK = "driver.lock"


def _score(_task: Any, _answer: Path) -> dict[str, Any]:  # noqa: ANN401
    return dict(SCORED)


def _round(rig: Rig, driver: Any, *, resume: bool = False) -> Any:  # noqa: ANN401
    return run_round(
        rig.inputs(trials=2), driver=driver, scorer=_score, resume=resume, sleep=lambda _: None
    )


def _place(rig: Rig) -> Path:
    summary = json.loads((rig.root / "out" / ROUND_RECORD).read_bytes())
    return withheld_root(rig.made.store, "control") / HARNESS_ROUNDS / str(summary["round"])


def _ledger(rig: Rig) -> list[dict[str, Any]]:
    return [json.loads(x) for x in (_place(rig) / LEDGER).read_bytes().splitlines()]


def _tree(root: Path) -> dict[str, bytes]:
    """Every file beneath ``root`` and its bytes, the lock's own file left out."""
    return {
        str(p.relative_to(root)): p.read_bytes()
        for p in sorted(root.rglob("*"))
        if p.is_file() and p.name != LOCK
    }


def test_a_second_driver_started_while_the_first_decomposes_is_refused_and_writes_nothing(
    tmp_path: Path,
) -> None:
    rig = make_rig(tmp_path)
    first = rig.driver()
    made = first.decompose
    second: list[Any] = []

    def decompose(call: Any) -> int:  # noqa: ANN401
        if not second:
            # Inside the first trial's decomposition, its parameters recorded.
            record_params(call.run_dir, call.params)
            before = (_tree(rig.root / "out"), _tree(_place(rig)), _tree(rig.run_root))
            other = rig.driver()
            try:
                _round(rig, other, resume=True)
            except RoundError as exc:
                second.append(exc)
            else:
                second.append(None)
            after = (_tree(rig.root / "out"), _tree(_place(rig)), _tree(rig.run_root))
            assert other.decomposed == [] and other.drives == []
            assert after == before, "the second driver wrote something"
            (call.run_dir / "params_source.json").unlink()
        return made(call)

    first.decompose = decompose  # type: ignore[method-assign]
    status, _ = _round(rig, first)
    (refused,) = second
    assert refused is not None, "a second driver went on with the round"
    assert refused.context["refused_because"] == "round_held"
    assert status == "done"
    assembled = [(x["index"], x["attempt"]) for x in _ledger(rig) if x["kind"] == "assembled"]
    assert assembled == [(0, 1), (1, 1)]
    assert [x for x in _ledger(rig) if x["kind"] == "left"] == []


def test_a_round_whose_lock_another_process_holds_is_refused_before_its_ledger_is_read(
    tmp_path: Path,
) -> None:
    rig = make_rig(tmp_path)
    with pytest.raises(Killed):
        _round(rig, rig.driver(killed={1}))
    # A cut line the reading would drop: a refused driver must not even have read it.
    with (_place(rig) / LEDGER).open("ab") as ledger:
        ledger.write(b'{"kind":"placed","ind')
    held = os.open(_place(rig) / LOCK, os.O_RDWR | os.O_CREAT, 0o600)
    try:
        fcntl.flock(held, fcntl.LOCK_EX | fcntl.LOCK_NB)
        later = rig.driver()
        with pytest.raises(RoundError) as refused:
            _round(rig, later, resume=True)
        assert refused.value.context["refused_because"] == "round_held"
        assert later.decomposed == [] and later.drives == []
        assert (_place(rig) / LEDGER).read_bytes().endswith(b'"ind')
    finally:
        os.close(held)


def test_a_lock_a_dead_driver_left_is_taken_over_and_the_ledger_says_so(tmp_path: Path) -> None:
    rig = make_rig(tmp_path)
    with pytest.raises(Killed):
        _round(rig, rig.driver(killed={1}))
    # The killed driver's pid stays in the lock's file; its process (this one, here) holds no lock.
    lock = _place(rig) / LOCK
    assert lock.is_file() and lock.read_text().strip() == str(os.getpid())
    status, _ = _round(rig, rig.driver(), resume=True)
    assert status == "done"
    taken = [x for x in _ledger(rig) if x["kind"] == "lock_taken_over"]
    assert [x["pid"] for x in taken] == [os.getpid()]
    # A driver that ended as it should leaves no pid behind: the next start takes over nothing.
    assert (_place(rig) / LOCK).read_text() == ""
