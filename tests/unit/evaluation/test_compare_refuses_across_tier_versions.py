"""``compare`` refuses two runs measured on different tier versions, or one named on one side only.

The held-out digests are a run's own record: a protected tier's is refused when it differs, while
a tier-set store's withheld and work roots', which hold no task of a version, are not compared
(a root of that name is set aside only beside a protected tier of its own role). The version
and the visible and validation digests are the evaluation's, in ``evaluation/tiers.json`` beside
a run: absent from both runs there is nothing to hold; present in one only, differing, or not a
record, the comparison is refused and the record named.
"""

from __future__ import annotations

from pathlib import Path

import pytest
from observe_rig import fake_run, target_repo

from physgate.evaluation.baseline.record import TiersRecord, record_bytes
from physgate.evaluation.observe.compare import compare, drift
from physgate.evaluation.observe.exceptions import CompareRefusedError
from physgate.evaluation.observe.manifest import read_manifest

RECORD = Path("evaluation") / "tiers.json"


def _tiers(version: str = "1" * 64, held_out: str = "4" * 64) -> bytes:
    return record_bytes(
        TiersRecord(
            format=1,
            version=version,
            role="control",
            visible="2" * 64,
            validation="3" * 64,
            held_out=held_out,
        )
    )


def _write(run_dir: Path, data: bytes) -> None:
    (run_dir / RECORD).parent.mkdir(parents=True, exist_ok=True)
    (run_dir / RECORD).write_bytes(data)


def _refused(baseline: Path, candidate: Path) -> None:
    for one, other in ((baseline, candidate), (candidate, baseline)):
        with pytest.raises(CompareRefusedError) as refusal:
            compare(one, other)
        assert "evaluation/tiers.json" in refusal.value.context.get("drifted", "").split(",")


@pytest.mark.parametrize(
    "case",
    ["one side only", "another version", "another digest", "not a record", "neither a record"],
)
def test_runs_on_different_tier_versions_are_not_compared(tmp_path: Path, case: str) -> None:
    repo = target_repo(tmp_path)
    baseline, candidate = fake_run(tmp_path, "base", repo), fake_run(tmp_path, "cand", repo)
    _write(baseline, _tiers())
    if case == "another version":
        _write(candidate, _tiers(version="5" * 64))
    elif case == "another digest":
        _write(candidate, _tiers(held_out="6" * 64))
    elif case == "not a record":
        _write(candidate, b'{"format": 1}')
    elif case == "neither a record":
        _write(baseline, b'{"format": 1}')
        _write(candidate, b'{"format": 1}')
    _refused(baseline, candidate)


def test_runs_on_one_tier_version_or_on_none_are_compared(tmp_path: Path) -> None:
    repo = target_repo(tmp_path)
    baseline, candidate = fake_run(tmp_path, "base", repo), fake_run(tmp_path, "cand", repo)
    compare(baseline, candidate)
    _write(baseline, _tiers())
    _write(candidate, _tiers())
    compare(baseline, candidate)


def test_runs_whose_held_out_digests_differ_are_refused_as_drifted(tmp_path: Path) -> None:
    repo = target_repo(tmp_path)
    baseline = fake_run(tmp_path, "base", repo)
    held = read_manifest(baseline).config
    assert held.held_out_sha256 == ()
    candidate = fake_run(
        tmp_path,
        "cand",
        repo,
        overrides={"held_out": ("/nowhere/held_out",), "held_out_sha256": ("7" * 64,)},
    )
    with pytest.raises(CompareRefusedError) as refusal:
        compare(baseline, candidate)
    assert "held_out_sha256" in refusal.value.context["drifted"].split(",")


def _store_roots(tmp_path: Path) -> tuple[str, ...]:
    """What a run on a tier-set store withholds, in the order a run lists it.

    The role's withheld and work roots, then the version's validation and held-out tiers.
    Nothing is read there: the digests are given.
    """
    role = tmp_path / "store" / "control"
    version = role / ("1" * 64)
    return (
        str(role / "withheld"),
        str(role / "work"),
        str(version / "validation"),
        str(version / "held_out"),
    )


def _on_store(tmp_path: Path, repo: Path, name: str, digests: tuple[str, ...]) -> Path:
    roots = _store_roots(tmp_path)
    return fake_run(tmp_path, name, repo, overrides={"held_out": roots, "held_out_sha256": digests})


#: The version's validation and held-out tiers' digests, as both runs recorded them.
TIERS_AS_RECORDED = ("3" * 64, "4" * 64)


def test_runs_whose_withheld_and_work_roots_alone_differ_are_compared(tmp_path: Path) -> None:
    # A register line, a vector, a trend line or the blind check's work lies beneath those two
    # roots and changes their digests; none of it is a task of the version.
    repo = target_repo(tmp_path)
    baseline = _on_store(tmp_path, repo, "base", ("8" * 64, "9" * 64, *TIERS_AS_RECORDED))
    candidate = _on_store(tmp_path, repo, "cand", ("a" * 64, "b" * 64, *TIERS_AS_RECORDED))
    mine, theirs = read_manifest(baseline).config, read_manifest(candidate).config
    assert drift(mine, theirs) == [] and drift(theirs, mine) == []
    compare(baseline, candidate)
    compare(candidate, baseline)


@pytest.mark.parametrize("tier", ["validation", "held_out"])
def test_runs_whose_protected_tier_digest_differs_are_refused_as_drifted(
    tmp_path: Path, tier: str
) -> None:
    repo = target_repo(tmp_path)
    changed = ("5" * 64, "4" * 64) if tier == "validation" else ("3" * 64, "5" * 64)
    baseline = _on_store(tmp_path, repo, "base", ("8" * 64, "9" * 64, *TIERS_AS_RECORDED))
    candidate = _on_store(tmp_path, repo, "cand", ("8" * 64, "9" * 64, *changed))
    for one, other in ((baseline, candidate), (candidate, baseline)):
        with pytest.raises(CompareRefusedError) as refusal:
            compare(one, other)
        assert "held_out_sha256" in refusal.value.context["drifted"].split(",")


@pytest.mark.parametrize("beside", ["no protected tier", "another role's tiers"])
def test_a_root_named_withheld_is_set_aside_only_beside_its_own_role_s_protected_tier(
    tmp_path: Path, beside: str
) -> None:
    # A root called withheld or work that no protected tier of its own role's root stands
    # beside is a held-out root like any other, and is compared.
    repo = target_repo(tmp_path)
    withheld, work, *tiers = _store_roots(tmp_path)
    if beside == "another role's tiers":
        tiers = [t.replace("/control/", "/firmware/") for t in tiers]
    roots = (withheld, work) if beside == "no protected tier" else (withheld, work, *tiers)
    rest = TIERS_AS_RECORDED[: len(roots) - 2]
    configs = []
    for name, first in (("base", "8"), ("cand", "a")):
        run = fake_run(
            tmp_path,
            name,
            repo,
            overrides={"held_out": roots, "held_out_sha256": (first * 64, "9" * 64, *rest)},
        )
        configs.append(read_manifest(run).config)
    assert drift(*configs) == ["held_out_sha256"]
