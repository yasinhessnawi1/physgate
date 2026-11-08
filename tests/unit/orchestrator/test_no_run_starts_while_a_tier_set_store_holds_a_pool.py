"""No run starts while a tier-set store it names holds a pool or a version being written.

The pool holds the tasks that become held-out and validation ones, before the split gives
them their canaries, and a version being written holds them too. No session of a run
withholds either, so a session that read them would see future held-out work and nothing
would detect it. The split removes the pool after the version's rename; whatever a stopped
split left keeps every run that names the store from starting, with a counted reason, until a
person has looked.
"""

from __future__ import annotations

import importlib
from pathlib import Path
from typing import Any

import pytest
from orch_helpers import make_config

from physgate.evaluation.requirements import REQUIREMENTS
from physgate.orchestrator.requirements import RunFacts
from physgate.orchestrator.run_config import HarnessState
from physgate.oslayer.probe import Present

VERSION = "a" * 64
PRESENT = Present(mechanism="seatbelt", claude_version="2.1.301")
CLEAN = HarnessState(commit="c" * 40, clean=True, uncommitted_sha256=None)


def _api(name: str) -> Any:
    """``module.attribute``, or the row fails: what it names is not built yet."""
    module, _, attribute = name.rpartition(".")
    try:
        found = getattr(importlib.import_module(module), attribute, None)
    except ImportError:
        found = None
    assert found is not None, f"{name} is not built"
    return found


def _store(tmp_path: Path) -> Path:
    store = tmp_path.resolve() / "store"
    for tier in ("visible", "validation", "held_out"):
        (store / "control" / VERSION / tier).mkdir(parents=True)
    return store


def _facts(*roots: Path, reportable: bool = True) -> RunFacts:
    config = make_config(
        reportable=reportable,
        harness=CLEAN,
        held_out=tuple(str(r) for r in roots),
        held_out_sha256=tuple("0" * 64 for _ in roots),
    )
    return RunFacts(config=config, os_layer=PRESENT, shell_sessions=True)


def _refusal(facts: RunFacts) -> str | None:
    requirement = _api("physgate.evaluation.requirements.nothing_left_in_a_named_tier_set_store")
    assert requirement in REQUIREMENTS, "the command does not hold runs to it"
    found: str | None = requirement(facts)
    return found


@pytest.mark.parametrize(
    ("left", "reason"),
    [
        ("control/withheld/pool", "pool_left"),
        ("control/withheld/pool.spent", "pool_left"),
        ("firmware/withheld/pool", "pool_left"),
        ("control/.version-0123abcd", "temporary_version_left"),
    ],
    ids=["a pool filling", "a spent pool", "another role's pool", "a version being written"],
)
def test_a_run_naming_a_store_that_holds_a_split_s_leftovers_is_refused_with_its_reason(
    tmp_path: Path, left: str, reason: str
) -> None:
    store = _store(tmp_path)
    (store / left).mkdir(parents=True)
    held_out = store / "control" / VERSION / "held_out"
    why = _refusal(_facts(held_out))
    assert why is not None and f"({reason})" in why and str(store) in why


@pytest.mark.parametrize("tier", ["held_out", "validation"])
def test_either_protected_tier_names_its_store(tmp_path: Path, tier: str) -> None:
    store = _store(tmp_path)
    (store / "control" / "withheld" / "pool").mkdir(parents=True)
    assert _refusal(_facts(store / "control" / VERSION / tier)) is not None


def test_a_run_that_is_not_reportable_is_held_to_it_too(tmp_path: Path) -> None:
    store = _store(tmp_path)
    (store / "control" / "withheld" / "pool").mkdir(parents=True)
    held_out = store / "control" / VERSION / "held_out"
    assert _refusal(_facts(held_out, reportable=False)) is not None


def test_a_run_naming_a_clean_store_or_none_starts(tmp_path: Path) -> None:
    store = _store(tmp_path)
    (store / "control" / "withheld" / "author").mkdir(parents=True)
    (store / "control" / "withheld" / "check").mkdir()
    # A pool beside the withheld root, not in it, is no pool of the store.
    (store / "control" / "pool").mkdir()
    assert _refusal(_facts(store / "control" / VERSION / "held_out")) is None
    elsewhere = tmp_path.resolve() / "private" / "held_out"
    (elsewhere.parent / "pool").mkdir(parents=True)
    assert _refusal(_facts(elsewhere)) is None
    assert _refusal(_facts()) is None


def test_the_leftovers_are_counted_by_reason_and_an_author_s_own_pool_is_its_to_fill(
    tmp_path: Path,
) -> None:
    leftovers = _api("physgate.evaluation.tiers.store.leftovers")
    store = _store(tmp_path)
    for left in (
        "control/withheld/pool",
        "firmware/withheld/pool.spent",
        "control/.version-1",
        "control/.version-2",
    ):
        (store / left).mkdir(parents=True)
    assert leftovers(store) == {"pool_left": 2, "temporary_version_left": 2}
    own = store / "control" / "withheld" / "pool"
    assert leftovers(store, continuing=own) == {"pool_left": 1, "temporary_version_left": 2}
    assert leftovers(tmp_path / "no-store") == {"pool_left": 0, "temporary_version_left": 0}


def test_a_store_that_cannot_be_listed_refuses(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    store = _store(tmp_path)
    store_module = _api("physgate.evaluation.tiers.store")
    real = store_module.os.listdir

    def unlistable(path: Any = ".") -> list[str]:
        if Path(path) == store / "control":
            raise PermissionError(f"cannot list {path}")
        return list(real(path))

    monkeypatch.setattr(store_module.os, "listdir", unlistable)
    why = _refusal(_facts(store / "control" / VERSION / "held_out"))
    assert why is not None and "(store_unreadable)" in why


# ------------------------------------------- what sessions wrote is withheld from every run


def _withheld_refusal(facts: RunFacts) -> str | None:
    requirement = _api(
        "physgate.evaluation.requirements.every_named_store_s_withheld_root_is_withheld"
    )
    assert requirement in REQUIREMENTS, "the command does not hold runs to it"
    found: str | None = requirement(facts)
    return found


@pytest.mark.parametrize("tier", ["held_out", "validation"])
def test_a_run_naming_a_tier_but_not_its_store_s_withheld_root_is_refused(
    tmp_path: Path, tier: str
) -> None:
    store = _store(tmp_path)
    why = _withheld_refusal(_facts(store / "control" / VERSION / tier))
    assert why is not None and "(withheld_root_not_named)" in why
    assert str(store / "control" / "withheld") in why


def test_a_run_naming_the_tiers_and_their_withheld_root_starts(tmp_path: Path) -> None:
    store = _store(tmp_path)
    version = store / "control" / VERSION
    facts = _facts(version / "held_out", version / "validation", store / "control" / "withheld")
    assert _withheld_refusal(facts) is None
    assert _withheld_refusal(_facts()) is None
    assert _withheld_refusal(_facts(tmp_path.resolve() / "private" / "held_out")) is None


def test_each_role_s_withheld_root_is_asked_for_and_another_s_does_not_stand_in(
    tmp_path: Path,
) -> None:
    store = _store(tmp_path)
    (store / "firmware" / VERSION / "held_out").mkdir(parents=True)
    facts = _facts(
        store / "control" / VERSION / "held_out",
        store / "firmware" / VERSION / "held_out",
        store / "control" / "withheld",
    )
    why = _withheld_refusal(facts)
    assert why is not None and str(store / "firmware" / "withheld") in why
    assert str(store / "control" / "withheld") not in why


def test_a_withheld_root_spelt_otherwise_is_the_same_root(tmp_path: Path) -> None:
    store = _store(tmp_path)
    spelt = f"{store}/control/./withheld/"
    config = make_config(
        reportable=True,
        harness=CLEAN,
        held_out=(str(store / "control" / VERSION / "held_out"), spelt),
        held_out_sha256=("0" * 64, "0" * 64),
    )
    facts = RunFacts(config=config, os_layer=PRESENT, shell_sessions=True)
    assert _withheld_refusal(facts) is None


def _spelt(store: Path, how: str) -> str:
    """The held-out tier of ``store``'s one control version, spelt as ``how`` says."""
    if how == "dot":
        return f"{store}/control/./{VERSION}/held_out"
    if how == "dot-dot":
        return f"{store}/control/elsewhere/../{VERSION}/held_out"
    if how == "trailing slash":
        return f"{store}/control/{VERSION}/held_out/"
    if how == "another case":
        return f"{store}/CONTROL/{VERSION.upper()}/held_out"
    if how == "beneath the tier":
        return f"{store}/control/{VERSION}/held_out/sub"
    alias = store.parent / "alias"
    alias.symlink_to(store / "control" / VERSION)
    return f"{alias}/held_out"


@pytest.mark.parametrize(
    "how", ["dot", "dot-dot", "trailing slash", "another case", "beneath the tier", "a link"]
)
def test_a_tier_however_spelt_still_asks_for_its_withheld_root(tmp_path: Path, how: str) -> None:
    store = _store(tmp_path)
    config = make_config(
        reportable=True,
        harness=CLEAN,
        held_out=(_spelt(store, how),),
        held_out_sha256=("0" * 64,),
    )
    why = _withheld_refusal(RunFacts(config=config, os_layer=PRESENT, shell_sessions=True))
    assert why is not None and "(withheld_root_not_named)" in why, f"{how}: the run starts"


@pytest.mark.parametrize("how", ["dot-dot", "a link"])
def test_a_tier_however_spelt_names_its_store_for_the_leftovers_too(
    tmp_path: Path, how: str
) -> None:
    store = _store(tmp_path)
    (store / "control" / "withheld" / "pool").mkdir(parents=True)
    config = make_config(
        reportable=True,
        harness=CLEAN,
        held_out=(_spelt(store, how), str(store / "control" / "withheld")),
        held_out_sha256=("0" * 64, "0" * 64),
    )
    assert _refusal(RunFacts(config=config, os_layer=PRESENT, shell_sessions=True)) is not None
