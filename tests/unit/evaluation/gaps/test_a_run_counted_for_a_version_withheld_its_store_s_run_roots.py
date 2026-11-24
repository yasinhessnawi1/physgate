"""A run is counted for a tier version only if it withheld every run root of the store whole.

A reportable run naming no tier passes every requirement a run is held to, and its sessions then
withhold neither the store nor the run roots, where the earlier runs on the store lie. So the
counting rule holds each run it counts to what its recorded parameters name. Among the roots it
withheld whole there must be every run root registered for the store's roles; one that named
none, or missed one, is refused before anything is counted (``run_roots_not_withheld``). It is
said by the run's place in the run set, never by a path.
"""

from __future__ import annotations

from pathlib import Path

import pytest
from gap_fixtures import StandInStore, measured, stand_in_store

from physgate.evaluation.gaps.vector import GapsError
from physgate.evaluation.tiers.exposure import add_run_root, run_roots
from physgate.evaluation.tiers.measure import census
from physgate.evaluation.tiers.store import make_role_root, role_root


@pytest.fixture
def made(tmp_path: Path) -> StandInStore:
    return stand_in_store(tmp_path.resolve() / "st")


def _registered(made: StandInStore, root: Path) -> list[str]:
    root.mkdir(parents=True, exist_ok=True)
    add_run_root(made.store, "control", root)
    return [str(r) for r in run_roots(made.store, "control")]


def _count(made: StandInStore, where: Path, *, withheld_whole: list[str]) -> object:
    m = measured(made, "visible", where, trials=1, withheld_whole=withheld_whole)
    return census(made.store, "control", made.version, "visible", m.runs, m.trials)


def test_a_run_that_withheld_every_run_root_whole_is_counted(
    made: StandInStore, tmp_path: Path
) -> None:
    base = tmp_path.resolve()
    roots = _registered(made, base / "runs")
    assert _count(made, base, withheld_whole=roots) is not None


@pytest.mark.parametrize("named", ["none", "one of two"])
def test_a_run_that_did_not_withhold_every_run_root_whole_is_not_counted(
    made: StandInStore, tmp_path: Path, named: str
) -> None:
    base = tmp_path.resolve()
    roots = _registered(made, base / "runs")
    if named == "one of two":
        _registered(made, base / "older")
    with pytest.raises(GapsError) as raised:
        _count(made, base, withheld_whole=[] if named == "none" else roots)
    assert raised.value.context.get("refused_because") == "run_roots_not_withheld"
    assert str(base) not in str(raised.value), raised.value


def test_a_run_that_did_not_withhold_another_role_s_run_root_whole_is_not_counted(
    made: StandInStore, tmp_path: Path
) -> None:
    base = tmp_path.resolve()
    roots = _registered(made, base / "runs")
    # Another role's root in the same store, with its own run root registered.
    make_role_root(role_root(made.store, "firmware"))
    (base / "firmware-runs").mkdir()
    assert add_run_root(made.store, "firmware", base / "firmware-runs")
    try:
        counted: object = _count(made, base, withheld_whole=roots)
    except GapsError as exc:
        counted = exc
    assert isinstance(counted, GapsError), "a run that left another role's run root was counted"
    assert counted.context.get("refused_because") == "run_roots_not_withheld", counted.context
    assert str(base) not in str(counted), counted
