"""``compare`` refuses two runs measured on different tier versions, or one named on one side only.

The held-out digests are a run's own record and already refused when they differ. The version
and the visible and validation digests are the evaluation's, in ``evaluation/tiers.json`` beside
a run: absent from both runs there is nothing to hold; present in one only, differing, or not a
record, the comparison is refused and the record named.
"""

from __future__ import annotations

from pathlib import Path

import pytest
from observe_rig import fake_run, target_repo

from physgate.evaluation.baseline.record import TiersRecord, record_bytes
from physgate.evaluation.observe.compare import compare
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
