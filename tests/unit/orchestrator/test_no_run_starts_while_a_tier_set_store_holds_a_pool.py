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
import os
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
    (store / "control" / "work").mkdir()
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
    assert leftovers(store) == {"pool_left": 2, "temporary_version_left": 2, "work_left": 0}
    own = store / "control" / "withheld" / "pool"
    assert leftovers(store, continuing=own) == {
        "pool_left": 1,
        "temporary_version_left": 2,
        "work_left": 0,
    }
    assert leftovers(tmp_path / "no-store") == {
        "pool_left": 0,
        "temporary_version_left": 0,
        "work_left": 0,
    }


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


# ----------------------------------------------------- a session's work out of a role's root


def _record(store: Path, name: str) -> None:
    """A record that a session's work is out of a role's root, as an author or a check writes."""
    (store / name).parent.mkdir(parents=True, exist_ok=True)
    (store / name).write_text('{"work": "/elsewhere/work"}\n')


def _whole(store: Path) -> tuple[Path, ...]:
    """What a run on ``store``'s one control version withholds: both tiers, the withheld root."""
    version = store / "control" / VERSION
    return version / "held_out", version / "validation", store / "control" / "withheld"


@pytest.mark.parametrize(
    "record",
    ["control/check.working", "control/author.working", "firmware/author.working"],
    ids=["a check's", "an author's", "another role's"],
)
def test_a_run_naming_a_store_where_a_session_s_work_is_out_of_a_role_s_root_is_refused(
    tmp_path: Path, record: str
) -> None:
    store = _store(tmp_path)
    _record(store, record)
    why = _refusal(_facts(*_whole(store)))
    assert why is not None and "(work_left)" in why and str(store) in why


def test_records_of_work_left_are_counted_and_no_role_s_own_is_its_to_ignore(
    tmp_path: Path,
) -> None:
    leftovers = _api("physgate.evaluation.tiers.store.leftovers")
    store = _store(tmp_path)
    for record in ("control/check.working", "firmware/author.working"):
        _record(store, record)
    own = store / "control" / "withheld" / "pool"
    assert leftovers(store).get("work_left") == 2
    assert leftovers(store, continuing=own).get("work_left") == 2


def test_a_record_of_work_left_under_a_withheld_root_counts_too(tmp_path: Path) -> None:
    leftovers = _api("physgate.evaluation.tiers.store.leftovers")
    store = _store(tmp_path)
    _record(store, "control/withheld/check.working")
    assert leftovers(store).get("work_left") == 1


# ---------------------------------------- a role's root or the store itself names the store


@pytest.mark.parametrize("named", ["the role's root", "the store"])
def test_a_run_naming_a_role_s_root_or_the_store_itself_is_held_to_the_leftovers(
    tmp_path: Path, named: str
) -> None:
    store = _store(tmp_path)
    (store / "firmware" / "withheld" / "pool").mkdir(parents=True)
    entry = store / "control" if named == "the role's root" else store
    why = _refusal(_facts(entry))
    assert why is not None and "(pool_left)" in why, f"{named}: the run starts"


def test_a_store_whose_own_path_holds_a_role_and_a_version_s_name_is_still_the_store(
    tmp_path: Path,
) -> None:
    store = tmp_path.resolve() / "control" / VERSION / "store"
    for tier in ("visible", "validation", "held_out"):
        (store / "control" / VERSION / tier).mkdir(parents=True)
    (store / "control" / "withheld" / "pool").mkdir(parents=True)
    why = _refusal(_facts(*_whole(store)))
    assert why is not None and "(pool_left)" in why and f"store {store} " in why


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


def test_a_run_naming_only_part_of_a_withheld_root_asks_for_all_of_it(tmp_path: Path) -> None:
    store = _store(tmp_path)
    (store / "control" / "withheld" / "author").mkdir(parents=True)
    why = _withheld_refusal(_facts(store / "control" / "withheld" / "author"))
    assert why is not None and "(withheld_root_not_named)" in why
    assert str(store / "control" / "withheld") in why


def test_a_run_naming_part_of_a_withheld_root_before_any_version_asks_for_all_of_it(
    tmp_path: Path,
) -> None:
    store = tmp_path.resolve() / "store"
    (store / "control" / "withheld" / "author").mkdir(parents=True)
    why = _withheld_refusal(_facts(store / "control" / "withheld" / "author"))
    assert why is not None and "(withheld_root_not_named)" in why


def test_a_withheld_root_named_in_another_case_does_not_stand_in_for_it(tmp_path: Path) -> None:
    store = _store(tmp_path)
    (store / "control" / "withheld").mkdir()
    version = store / "control" / VERSION
    other = store / "CONTROL" / "WITHHELD"
    why = _withheld_refusal(_facts(version / "held_out", version / "validation", other))
    assert why is not None and "(withheld_root_not_named)" in why


# ------------------------------- every protected tier under a role's root is withheld with it


def _tier_refusal(facts: RunFacts) -> str | None:
    requirement = _api(
        "physgate.evaluation.requirements.every_named_role_root_s_protected_tiers_are_withheld"
    )
    assert requirement in REQUIREMENTS, "the command does not hold runs to it"
    found: str | None = requirement(facts)
    return found


def test_a_run_naming_held_out_without_its_validation_tier_is_refused(tmp_path: Path) -> None:
    store = _store(tmp_path)
    version = store / "control" / VERSION
    why = _tier_refusal(_facts(version / "held_out", store / "control" / "withheld"))
    assert why is not None and "(protected_tier_not_named)" in why
    assert str(version / "validation") in why and str(version / "held_out") + "," not in why


def test_a_run_on_one_version_not_naming_an_older_version_s_tiers_is_refused(
    tmp_path: Path,
) -> None:
    store = _store(tmp_path)
    newer = store / "control" / ("b" * 64)
    for tier in ("visible", "validation", "held_out"):
        (newer / tier).mkdir(parents=True)
    named = (newer / "held_out", newer / "validation", store / "control" / "withheld")
    why = _tier_refusal(_facts(*named))
    older = store / "control" / VERSION
    assert why is not None and "(protected_tier_not_named)" in why
    assert str(older / "held_out") in why and str(older / "validation") in why
    assert str(newer / "held_out") not in why


def test_a_role_s_root_that_cannot_be_listed_refuses_the_run(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    store = _store(tmp_path)
    store_module = _api("physgate.evaluation.tiers.store")
    real = store_module.os.listdir

    def unlistable(path: Any = ".") -> list[str]:
        if isinstance(path, str | os.PathLike) and Path(path) == store / "control":
            raise PermissionError(f"cannot list {path}")
        return list(real(path))

    monkeypatch.setattr(store_module.os, "listdir", unlistable)
    try:
        why = _tier_refusal(_facts(*_whole(store)))
    except OSError as exc:
        pytest.fail(f"an unlistable role's root raises, not a counted refusal: {exc!r}")
    assert why is not None and "(store_unreadable)" in why


def test_a_run_withholding_every_protected_tier_or_the_role_s_root_starts(tmp_path: Path) -> None:
    store = _store(tmp_path)
    newer = store / "control" / ("b" * 64)
    for tier in ("visible", "validation", "held_out"):
        (newer / tier).mkdir(parents=True)
    older = store / "control" / VERSION
    every = (
        older / "held_out",
        older / "validation",
        newer / "held_out",
        newer / "validation",
        store / "control" / "withheld",
    )
    for named in (every, (older, newer, store / "control" / "withheld"), (store / "control",)):
        facts = _facts(*named)
        assert _tier_refusal(facts) is None, named
        assert _withheld_refusal(facts) is None, named
    assert _tier_refusal(_facts(tmp_path.resolve() / "private" / "held_out")) is None


# ------------------------------------------ a named store's roots are spelt as they are on disk


def _spelling_refusal(facts: RunFacts) -> str | None:
    requirement = _api(
        "physgate.evaluation.requirements.a_named_store_s_roots_are_spelt_as_on_disk"
    )
    assert requirement in REQUIREMENTS, "the command does not hold runs to it"
    found: str | None = requirement(facts)
    return found


def test_a_withheld_root_not_spelt_as_it_is_on_disk_is_refused(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    store = _store(tmp_path)
    (store / "control" / "withheld").mkdir()
    store_module = _api("physgate.evaluation.tiers.store")
    real = store_module.os.listdir

    # The volume ignores case and spells the root ``Withheld``: the run's ``withheld`` reaches
    # the same files, but is not the spelling on disk.
    def spelt_otherwise(path: Any = ".") -> list[str]:
        names = list(real(path))
        if isinstance(path, str | os.PathLike) and Path(path) == store / "control":
            return ["Withheld" if name == "withheld" else name for name in names]
        return names

    monkeypatch.setattr(store_module.os, "listdir", spelt_otherwise)
    why = _spelling_refusal(_facts(*_whole(store)))
    assert why is not None and "(held_out_not_spelt_as_on_disk)" in why
    assert str(store / "control" / "withheld") in why
    assert str(store / "control" / VERSION / "held_out") not in why


def test_a_root_named_in_another_case_is_refused_where_the_volume_ignores_case(
    tmp_path: Path,
) -> None:
    store = _store(tmp_path)
    (store / "control" / "withheld").mkdir()
    if not (store / "CONTROL").exists():
        pytest.skip("this volume tells case apart, so another case is another path")
    version = store / "control" / VERSION
    other = store / "CONTROL" / "withheld"
    why = _spelling_refusal(_facts(version / "held_out", version / "validation", other))
    assert why is not None and "(held_out_not_spelt_as_on_disk)" in why


def test_a_root_whose_spelling_cannot_be_judged_is_refused(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    store = _store(tmp_path)
    (store / "control" / "withheld").mkdir()
    store_module = _api("physgate.evaluation.tiers.store")
    real = store_module.os.listdir

    def unlistable(path: Any = ".") -> list[str]:
        if isinstance(path, str | os.PathLike) and Path(path) == store / "control" / VERSION:
            raise PermissionError(f"cannot list {path}")
        return list(real(path))

    monkeypatch.setattr(store_module.os, "listdir", unlistable)
    why = _spelling_refusal(_facts(*_whole(store)))
    assert why is not None and "(held_out_not_spelt_as_on_disk)" in why
    assert "cannot be judged" in why


def test_roots_spelt_as_on_disk_or_a_run_naming_no_store_start(tmp_path: Path) -> None:
    store = _store(tmp_path)
    (store / "control" / "withheld").mkdir()
    assert _spelling_refusal(_facts(*_whole(store))) is None
    assert _spelling_refusal(_facts(tmp_path.resolve() / "private" / "held_out")) is None
    assert _spelling_refusal(_facts()) is None


# ----------------------------------------------- what cannot be listed or is a link refuses


def _unlistable_at(monkeypatch: pytest.MonkeyPatch, place: Path) -> None:
    """``os.listdir`` refuses ``place``, as a directory that can be passed but not read."""
    store_module = _api("physgate.evaluation.tiers.store")
    real = store_module.os.listdir

    def unlistable(path: Any = ".") -> list[str]:
        if isinstance(path, str | os.PathLike) and Path(path) == place:
            raise PermissionError(f"cannot list {path}")
        return list(real(path))

    monkeypatch.setattr(store_module.os, "listdir", unlistable)


def test_a_run_naming_a_store_that_cannot_be_listed_is_refused(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    store = _store(tmp_path)
    _record(store, "control/check.working")
    _unlistable_at(monkeypatch, store)
    try:
        why = _refusal(_facts(store))
    except OSError as exc:
        pytest.fail(f"an unlistable store raises, not a counted refusal: {exc!r}")
    assert why is not None and "(store_unreadable)" in why, "the run starts"


def test_a_run_naming_a_role_s_root_that_cannot_be_listed_is_refused(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    store = _store(tmp_path)
    _unlistable_at(monkeypatch, store / "control")
    try:
        why = _refusal(_facts(store / "control"))
    except OSError as exc:
        pytest.fail(f"an unlistable role's root raises, not a counted refusal: {exc!r}")
    assert why is not None and "(store_unreadable)" in why, "the run starts"


def test_a_run_naming_a_place_in_a_role_s_root_that_cannot_be_listed_is_refused(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    # Only the directory named as a role cannot be listed: what it holds is taken to be a
    # role's root, so its store is named, and its leftovers cannot be ruled out.
    store = _store(tmp_path)
    _unlistable_at(monkeypatch, store / "control")
    try:
        why = _refusal(_facts(store / "control" / "notes"))
    except OSError as exc:
        pytest.fail(f"an unlistable role's root raises, not a counted refusal: {exc!r}")
    assert why is not None and "(store_unreadable)" in why, "the run starts"


@pytest.mark.parametrize("link", ["firmware", "control/withheld"])
def test_a_role_s_root_or_withheld_root_that_is_a_link_refuses(tmp_path: Path, link: str) -> None:
    store = _store(tmp_path)
    elsewhere = tmp_path.resolve() / "elsewhere"
    (elsewhere / "withheld" / "pool").mkdir(parents=True)
    (elsewhere / "pool").mkdir()
    (elsewhere / "check.working").write_text('{"work": "/elsewhere/work"}\n')
    (store / link).parent.mkdir(parents=True, exist_ok=True)
    (store / link).symlink_to(elsewhere)
    why = _refusal(_facts(store))
    assert why is not None and "(store_unreadable)" in why, f"{link}: the link is skipped"


# ------------------------------------------------- the blind check's work is withheld too


def _work_refusal(facts: RunFacts) -> str | None:
    requirement = _api(
        "physgate.evaluation.requirements.every_named_role_root_s_work_root_is_withheld"
    )
    assert requirement in REQUIREMENTS, "the command does not hold runs to it"
    found: str | None = requirement(facts)
    return found


def test_a_run_not_withholding_the_role_s_work_root_is_refused(tmp_path: Path) -> None:
    store = _store(tmp_path)
    why = _work_refusal(_facts(*_whole(store)))
    assert why is not None and "(work_root_not_named)" in why
    assert str(store / "control" / "work") in why


def test_a_run_withholding_the_work_root_or_what_holds_it_starts(tmp_path: Path) -> None:
    store = _store(tmp_path)
    for named in (
        (*_whole(store), store / "control" / "work"),
        (store / "control",),
        (store,),
    ):
        assert _work_refusal(_facts(*named)) is None, named
    assert _work_refusal(_facts(tmp_path.resolve() / "private" / "held_out")) is None


def test_a_check_s_work_in_the_work_root_is_work_left(tmp_path: Path) -> None:
    leftovers = _api("physgate.evaluation.tiers.store.leftovers")
    store = _store(tmp_path)
    (store / "control" / "work" / "check-0" / "worktree").mkdir(parents=True)
    assert leftovers(store).get("work_left") == 1
    why = _refusal(_facts(*_whole(store), store / "control" / "work"))
    assert why is not None and "(work_left)" in why


def test_a_work_root_that_is_a_link_refuses(tmp_path: Path) -> None:
    store = _store(tmp_path)
    elsewhere = tmp_path.resolve() / "elsewhere"
    elsewhere.mkdir()
    (store / "control" / "work").symlink_to(elsewhere)
    why = _refusal(_facts(store))
    assert why is not None and "(store_unreadable)" in why, "the link is skipped"


@pytest.mark.parametrize(
    "left",
    [
        "control/copy.json",
        "control/pool/control.t00/task.json",
        "control/Withheld/copy.json",
        "control/Work",
        f"control/{VERSION}/copy.json",
        f"control/{'B' * 64}/held_out/task.json",
        "control/" + "c" * 64,
        "control/author.working",
    ],
    ids=[
        "a task copy in the role's root",
        "a folder in the role's root",
        "the withheld root's name in another case",
        "the work root's name in another case",
        "a file in a version beside its tiers",
        "a version's name in another case",
        "a file named as a version",
        "a record of work",
    ],
)
def test_anything_out_of_place_in_a_role_s_root_is_work_left_and_refuses_the_run(
    tmp_path: Path, left: str
) -> None:
    leftovers = _api("physgate.evaluation.tiers.store.leftovers")
    store = _store(tmp_path)
    place = store / left
    place.parent.mkdir(parents=True, exist_ok=True)
    if left.endswith("/Work"):
        place.mkdir()
    else:
        place.write_text('{"id": "control.t00", "brief": "a held-out brief"}')
    assert leftovers(store)["work_left"] == 1, f"{left} is not counted"
    refusal = _refusal(_facts(store / "control" / VERSION / "held_out"))
    assert refusal is not None and refusal.endswith("(work_left)")


def test_the_known_places_of_a_role_s_root_are_not_work_left(tmp_path: Path) -> None:
    leftovers = _api("physgate.evaluation.tiers.store.leftovers")
    store = _store(tmp_path)
    version = store / "control" / VERSION
    (version / "tierset.json").write_text("{}")
    (version / "provenance.json").write_text("{}")
    (store / "control" / "withheld" / "author" / "s-1").mkdir(parents=True)
    (store / "control" / "work").mkdir()
    (store / "firmware" / "withheld").mkdir(parents=True)
    assert leftovers(store) == {"pool_left": 0, "temporary_version_left": 0, "work_left": 0}
