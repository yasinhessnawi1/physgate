"""A round goes on only on the code and the client it began with.

The harness checkout (its commit, and anything not committed), the client binary (its bytes and
platform) and the client's version are measured as the round starts, recorded in its ledger's
first line, and measured again at every restart: a restart on anything else is refused before any
step, naming what differs. A run continued on other code is two runs under one name, and so is a
round. A round is refused before anything is written on a checkout that is not clean.
"""

from __future__ import annotations

import json
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


def _score(_task: Any, _answer: Path) -> dict[str, Any]:  # noqa: ANN401
    return dict(SCORED)


def _round(rig: Rig, driver: StandInDriver, *, resume: bool = False) -> Any:  # noqa: ANN401
    return run_round(
        rig.inputs(trials=2), driver=driver, scorer=_score, resume=resume, sleep=lambda _: None
    )


def _place(rig: Rig) -> Path:
    summary = json.loads((rig.root / "out" / ROUND_RECORD).read_bytes())
    return withheld_root(rig.made.store, "control") / HARNESS_ROUNDS / str(summary["round"])


def _first_line(rig: Rig) -> dict[str, Any]:
    return dict(json.loads((_place(rig) / LEDGER).read_bytes().splitlines()[0]))


def _killed_once(rig: Rig) -> bytes:
    with pytest.raises(Killed):
        _round(rig, rig.driver(killed={2}))
    return (_place(rig) / LEDGER).read_bytes()


def test_the_round_records_the_code_and_client_it_began_with(tmp_path: Path) -> None:
    rig = make_rig(tmp_path)
    driver = rig.driver()
    _round(rig, driver)
    assert _first_line(rig).get("pins") == driver.pins()


@pytest.mark.parametrize(
    ("change", "named"),
    [
        (lambda p: p["harness"].update(commit="d" * 40), "harness.commit"),
        (lambda p: p["harness"].update(clean=False, uncommitted_sha256="e" * 64), "harness.clean"),
        (lambda p: p["binary"].update(sha256="f" * 64), "binary.sha256"),
        (lambda p: p.update(claude_version="2.1.999"), "claude_version"),
    ],
)
def test_a_restart_on_other_code_or_another_client_is_refused_naming_what_differs(
    tmp_path: Path, change: Any, named: str
) -> None:  # noqa: ANN401
    rig = make_rig(tmp_path)
    held = _killed_once(rig)
    later = rig.driver()
    change(later.pin_record)
    with pytest.raises(RoundError) as refused:
        _round(rig, later, resume=True)
    assert refused.value.context["refused_because"] == "harness_differs"
    assert named in refused.value.context["fields"].split(",")
    assert later.decomposed == [] and later.drives == []
    assert (_place(rig) / LEDGER).read_bytes() == held


def test_a_restart_on_the_same_code_and_client_goes_on(tmp_path: Path) -> None:
    rig = make_rig(tmp_path)
    _killed_once(rig)
    status, _ = _round(rig, rig.driver(), resume=True)
    assert status == "done"


def test_a_round_on_a_checkout_that_is_not_clean_is_refused_before_anything_is_written(
    tmp_path: Path,
) -> None:
    rig = make_rig(tmp_path)
    driver = rig.driver()
    driver.pin_record["harness"].update(clean=False, uncommitted_sha256="e" * 64)
    with pytest.raises(RoundError) as refused:
        _round(rig, driver)
    assert refused.value.context["refused_because"] == "harness_not_clean"
    assert not (rig.root / "out").exists() and list(rig.run_root.iterdir()) == []
    assert driver.decomposed == []
