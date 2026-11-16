"""Runs are compared on the protected tiers' digests, never on the role's withheld root's.

A run records the digest of every root it withholds, the role's withheld root and work root
among them. Neither holds a task of a version: the register's logs, heads and locks, the
vectors, the gap trend and the baseline rounds' records lie in the first, the blind check's work
in the second, and every write there changes its digest. So two runs made either side of a
register line, a vector or a trend line are one comparison, for ``compare`` and for the counting
rule, while a changed protected tier is drift for both. A vector written under the earlier rule,
whose configuration digest held the withheld root's, is refused in words: never taken as equal,
never silently refused as drift.
"""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any

import pytest
from gap_fixtures import Measured, StandInStore, api, design, measured, stand_in_store

from physgate.cli import main
from physgate.evaluation.observe.compare import drift
from physgate.evaluation.tiers.heldout import tier_digest
from physgate.evaluation.tiers.store import withheld_root
from physgate.evaluation.tiers.task import canonical_json
from physgate.orchestrator.run_config import RunConfig, load_run_config

WRITE = "physgate.evaluation.tiers.measure.write_vector"
RECORD = "physgate.evaluation.tiers.exposure.record_measurement"
#: Where the stand-in store's runs list each root: the withheld root, the work root, then the
#: version's validation and held-out tiers.
WITHHELD, WORK, VALIDATION, HELD_OUT = range(4)


@pytest.fixture
def made(tmp_path: Path) -> StandInStore:
    return stand_in_store(tmp_path / "st")


def _now(made: StandInStore) -> list[str]:
    """Each root's digest as a run made now records it."""
    return [tier_digest(Path(root)) for root in made.held_out]


def _vector(made: StandInStore, tier: str, m: Measured) -> Path:
    withheld = withheld_root(made.store, "control")
    key = api(WRITE)(withheld, version=made.version, tier=tier, runs=m.runs, trials=m.trials)
    return withheld / "gaps" / f"{key}.json"


def _config(m: Measured) -> RunConfig:
    return load_run_config(m.run_dirs[0] / "run.json")


def _gaps(
    capsys: pytest.CaptureFixture[str],
    tmp_path: Path,
    runs: Path,
    trials: Path,
    held_out: Path,
    *extra: str,
    body: dict[str, Any],
) -> tuple[int, dict[str, Any]]:
    path = tmp_path / "design.json"
    path.write_text(json.dumps(body))
    argv = ["gaps", "--design", str(path), "--runs", str(runs), "--trials", str(trials)]
    code = main([*argv, "--held-out", str(held_out), *extra])
    out = capsys.readouterr().out.strip().splitlines()
    assert out, "gaps printed nothing"
    return code, json.loads(out[-1])


@pytest.mark.parametrize("write", ["register line", "vector", "trend line"])
def test_runs_made_either_side_of_a_write_beneath_the_withheld_root_are_one_comparison(
    tmp_path: Path, made: StandInStore, capsys: pytest.CaptureFixture[str], write: str
) -> None:
    held = _vector(
        made, "held_out", measured(made, "held_out", tmp_path / "h", held_out_sha256=_now(made))
    )
    before = measured(made, "visible", tmp_path / "v0", held_out_sha256=_now(made))
    valid = measured(made, "validation", tmp_path / "w", held_out_sha256=_now(made))
    body = design(made, before, validation_tasks=None)
    mid = _now(made)
    if write == "register line":
        api(RECORD)(made.store, "control", made.version, measured="probe", key="e" * 64)
    elif write == "vector":
        _vector(made, "validation", valid)
    else:
        trend = tmp_path / "gaps.jsonl"
        code, said = _gaps(
            capsys, tmp_path, before.runs, before.trials, held, "--append", str(trend), body=body
        )
        assert code == 0, said
        assert len(trend.read_text().splitlines()) == 1
    then = _now(made)
    assert then[WITHHELD] != mid[WITHHELD], f"the {write} left the withheld root's digest as it was"
    assert then[WORK:] == mid[WORK:], f"the {write} changed a root that is not the withheld one"
    after = measured(made, "visible", tmp_path / "v1", held_out_sha256=then)
    assert drift(_config(before), _config(after)) == []
    code, said = _gaps(capsys, tmp_path, after.runs, after.trials, held, body=body)
    assert code == 0, said


def test_a_changed_protected_tier_is_drift(
    tmp_path: Path, made: StandInStore, capsys: pytest.CaptureFixture[str]
) -> None:
    held = _vector(
        made, "held_out", measured(made, "held_out", tmp_path / "h", held_out_sha256=_now(made))
    )
    before = measured(made, "visible", tmp_path / "v0", held_out_sha256=_now(made))
    tier = Path(made.held_out[HELD_OUT])
    task = next(p for p in sorted(tier.iterdir()) if p.is_dir())
    was = _now(made)
    (task / "notes.txt").write_text("a byte the version was not written with\n")
    changed = _now(made)
    assert changed[HELD_OUT] != was[HELD_OUT]
    assert changed[:HELD_OUT] == was[:HELD_OUT], "only the held-out tier was changed"
    after = measured(made, "visible", tmp_path / "v1", held_out_sha256=changed)
    assert drift(_config(before), _config(after)) == ["held_out_sha256"]
    body = design(made, before, validation_tasks=None)
    code, said = _gaps(capsys, tmp_path, after.runs, after.trials, held, body=body)
    assert code == 1 and said.get("refused_because") == "drift", said
    # And within one run set: a run recorded on the changed tier is not counted with the rest.
    mixed = tmp_path / "mixed"
    runs = json.loads(before.runs.read_text())
    runs["trials"][-1]["run_dir"] = str(after.run_dirs[-1])
    mixed.mkdir()
    (mixed / "runs.json").write_text(json.dumps(runs))
    code, said = _gaps(capsys, tmp_path, mixed / "runs.json", before.trials, held, body=body)
    assert code == 1 and said.get("refused_because") == "drift", said


def _earlier_rule(config: RunConfig) -> str:
    """The configuration digest as the vector writer made it before: every recorded digest."""
    dumped = config.model_dump(mode="json")
    held: dict[str, Any] = {}
    for field in api("physgate.evaluation.tiers.measure.HELD_EQUAL"):
        value: Any = dumped
        for part in field.split("."):
            value = value.get(part) if isinstance(value, dict) else None
        held[field] = value
    return hashlib.sha256(canonical_json(held)).hexdigest()


def test_a_vector_written_under_the_earlier_rule_is_refused_in_words(
    tmp_path: Path, made: StandInStore, capsys: pytest.CaptureFixture[str]
) -> None:
    first = _now(made)
    visible = measured(made, "visible", tmp_path / "v", held_out_sha256=first)
    written = _vector(
        made, "held_out", measured(made, "held_out", tmp_path / "h", held_out_sha256=first)
    )
    # The vector as the writer wrote it before the rule changed, counted as the writer counts.
    body = json.loads(written.read_bytes())
    body |= {"format": 1, "drift_sha256": _earlier_rule(_config(visible))}
    raw = canonical_json(body)
    key = hashlib.sha256(raw).hexdigest()
    earlier = written.parent / f"{key}.json"
    if not earlier.exists():
        earlier.write_bytes(raw)
        api(RECORD)(made.store, "control", made.version, measured="gaps", key=key)
    design_body = design(made, visible, validation_tasks=None)
    code, said = _gaps(capsys, tmp_path, visible.runs, visible.trials, earlier, body=design_body)
    assert code == 1, f"a vector of the earlier rule was taken: {said}"
    assert said.get("refused_because") == "vector_earlier_rule", said
    words = said.get("error", "")
    assert "earlier" in words and "again" in words, words
