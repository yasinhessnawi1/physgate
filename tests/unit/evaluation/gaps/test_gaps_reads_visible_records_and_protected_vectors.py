"""``physgate gaps``: both gaps from the visible tier's records and the protected tiers' vectors.

The visible tier is read from its trial records and its run set, held to the same counting rule
as the vectors were; the held-out and validation tiers only through their vectors, each verified
against the measurement line its writing added to the register. A rate is never printed without
its count; on one task the interval is said to be none, and a small count is said in words. The
second gap is labelled a noise floor. The harness commit and the account are printed with the
result. A vector the register does not hold, runs under another configuration than the
vectors', a version exposed as read now and the raw arm are each refused.
"""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any

import pytest
from gap_fixtures import Measured, StandInStore, api, design, measured, stand_in_store

from physgate.cli import main
from physgate.evaluation.observe.compare import DRIFT
from physgate.evaluation.tiers.store import withheld_root
from physgate.evaluation.tiers.task import canonical_json

WRITE = "physgate.evaluation.tiers.measure.write_vector"


@pytest.fixture
def made(tmp_path: Path) -> StandInStore:
    return stand_in_store(tmp_path / "st")


def _vector(made: StandInStore, tier: str, m: Measured) -> Path:
    withheld = withheld_root(made.store, "control")
    key = api(WRITE)(withheld, version=made.version, tier=tier, runs=m.runs, trials=m.trials)
    return withheld / "gaps" / f"{key}.json"


def _gaps(
    capsys: pytest.CaptureFixture[str],
    tmp_path: Path,
    body: dict[str, Any],
    visible: Measured,
    held_out: Path,
    validation: Path | None,
    *extra: str,
) -> tuple[int, dict[str, Any]]:
    path = tmp_path / "design.json"
    path.write_text(json.dumps(body))
    argv = ["gaps", "--design", str(path), "--runs", str(visible.runs)]
    argv += ["--trials", str(visible.trials), "--held-out", str(held_out)]
    if validation is not None:
        argv += ["--validation", str(validation)]
    code = main([*argv, *extra])
    out = capsys.readouterr().out.strip().splitlines()
    assert out, "gaps printed nothing"
    return code, json.loads(out[-1])


def test_one_task_per_tier_matches_the_hand_table(
    tmp_path: Path, made: StandInStore, capsys: pytest.CaptureFixture[str]
) -> None:
    # Hand table, task 0 of each tier, two trials (gap_fixtures.PASSES): visible passes both
    # (2/2), validation trial 0 only (1/2), held out trial 0 only (1/2). Reward-hacking gap
    # 1 - 1/2 = 0.5; optimiser-overfit gap 1/2 - 1/2 = 0.
    visible = measured(made, "visible", tmp_path / "v", tasks=1)
    held = _vector(made, "held_out", measured(made, "held_out", tmp_path / "h", tasks=1))
    valid = _vector(made, "validation", measured(made, "validation", tmp_path / "w", tasks=1))
    body = design(made, visible, held_out_tasks=1, validation_tasks=1)
    code, said = _gaps(capsys, tmp_path, body, visible, held, valid)
    assert code == 0, said
    assert [said[t]["passed"] for t in ("visible", "validation", "held_out")] == [2, 1, 1]
    assert [said[t]["n"] for t in ("visible", "validation", "held_out")] == [2, 2, 2]
    assert said["reward_hacking"]["gap"] == pytest.approx(0.5)
    assert said["optimiser_overfit"]["gap"] == pytest.approx(0.0)
    for gap in ("reward_hacking", "optimiser_overfit"):
        assert said[gap]["interval"] is None, "one task gave an interval"
        assert "one task: no interval" in said[gap]["words"]
    assert any("held out: 1 task, so this rate is that task's outcome" in n for n in said["notes"])
    assert "noise floor" in (said["optimiser_overfit"]["label"] or ""), said
    for tier in ("visible", "validation", "held_out"):
        assert "/" in said[tier]["rate"] and said[tier]["rate"].startswith(
            f"{said[tier]['passed']}/{said[tier]['n']}"
        ), "a rate is printed without its count"
    assert said["harness_commits"] == ["c" * 40]
    assert said["accounts"] and all(isinstance(a, str) for a in said["accounts"])


def test_two_tasks_give_an_interval(
    tmp_path: Path, made: StandInStore, capsys: pytest.CaptureFixture[str]
) -> None:
    visible = measured(made, "visible", tmp_path / "v")
    held = _vector(made, "held_out", measured(made, "held_out", tmp_path / "h"))
    code, said = _gaps(
        capsys, tmp_path, design(made, visible, validation_tasks=None), visible, held, None
    )
    assert code == 0, said
    low, high = said["reward_hacking"]["interval"]
    assert low <= said["reward_hacking"]["gap"] <= high
    assert "optimiser_overfit" not in said or said["optimiser_overfit"] is None


def test_a_vector_the_register_does_not_hold_is_refused(
    tmp_path: Path, made: StandInStore, capsys: pytest.CaptureFixture[str]
) -> None:
    visible = measured(made, "visible", tmp_path / "v")
    held = _vector(made, "held_out", measured(made, "held_out", tmp_path / "h"))
    forged = json.loads(held.read_text())
    forged["tasks"][0]["passes"] = 2
    raw = canonical_json(forged)
    planted = held.with_name(f"{hashlib.sha256(raw).hexdigest()}.json")
    planted.write_bytes(raw)
    code, said = _gaps(
        capsys, tmp_path, design(made, visible, validation_tasks=None), visible, planted, None
    )
    assert code == 1 and said.get("refused_because") == "vector_unmeasured", said


def test_visible_runs_under_another_configuration_are_refused(
    tmp_path: Path, made: StandInStore, capsys: pytest.CaptureFixture[str]
) -> None:
    assert "effort" in DRIFT
    visible = measured(made, "visible", tmp_path / "v", effort="low")
    held = _vector(made, "held_out", measured(made, "held_out", tmp_path / "h"))
    code, said = _gaps(
        capsys, tmp_path, design(made, visible, validation_tasks=None), visible, held, None
    )
    assert code == 1 and said.get("refused_because") == "drift", said


def test_a_version_exposed_since_its_vectors_is_refused(
    tmp_path: Path, made: StandInStore, capsys: pytest.CaptureFixture[str]
) -> None:
    visible = measured(made, "visible", tmp_path / "v")
    held = _vector(made, "held_out", measured(made, "held_out", tmp_path / "h"))
    api("physgate.evaluation.tiers.exposure.mark_exposed")(
        made.store, "control", made.version, by="a person", reason="opened a task file"
    )
    code, said = _gaps(
        capsys, tmp_path, design(made, visible, validation_tasks=None), visible, held, None
    )
    assert code == 1 and said.get("refused_because") == "version_exposed", said


def test_the_raw_arm_is_refused_in_words(
    tmp_path: Path, made: StandInStore, capsys: pytest.CaptureFixture[str]
) -> None:
    visible = measured(made, "visible", tmp_path / "v")
    held = _vector(made, "held_out", measured(made, "held_out", tmp_path / "h"))
    body = design(made, visible, validation_tasks=None, arm="raw")
    code, said = _gaps(capsys, tmp_path, body, visible, held, None)
    assert code == 1 and said.get("refused_because") == "raw_arm_has_no_run_sets", said
    assert "raw" in said.get("error", ""), said


def test_a_vector_of_other_task_counts_than_the_design_is_refused(
    tmp_path: Path, made: StandInStore, capsys: pytest.CaptureFixture[str]
) -> None:
    visible = measured(made, "visible", tmp_path / "v")
    held = _vector(made, "held_out", measured(made, "held_out", tmp_path / "h"))
    body = design(made, visible, validation_tasks=None, held_out_tasks=3)
    code, said = _gaps(capsys, tmp_path, body, visible, held, None)
    assert code == 1 and said.get("refused_because") == "not_the_design", said


def test_visible_runs_that_are_not_the_design_s_tasks_times_trials_are_refused(
    tmp_path: Path, made: StandInStore, capsys: pytest.CaptureFixture[str]
) -> None:
    visible = measured(made, "visible", tmp_path / "v")
    held = _vector(made, "held_out", measured(made, "held_out", tmp_path / "h"))
    for changes in ({"trials": 3}, {"visible": [visible.tasks[0].id]}):
        body = design(made, visible, validation_tasks=None) | changes
        code, said = _gaps(capsys, tmp_path, body, visible, held, None)
        assert code == 1 and said.get("refused_because") == "not_the_design", (changes, said)


def test_one_task_written_twice_counts_two_looks(
    tmp_path: Path, made: StandInStore, capsys: pytest.CaptureFixture[str]
) -> None:
    # One task: the shuffle cannot change the bytes, so both writes give one key, and the
    # register holds two lines. Each line is a look.
    visible = measured(made, "visible", tmp_path / "v", tasks=1)
    held = measured(made, "held_out", tmp_path / "h", tasks=1)
    first, second = _vector(made, "held_out", held), _vector(made, "held_out", held)
    assert first == second, "one task's vector was written to two keys"
    body = design(made, visible, held_out_tasks=1, validation_tasks=None)
    code, said = _gaps(capsys, tmp_path, body, visible, second, None)
    assert code == 0, said
    assert said["measurements"] == 2, "two looks were counted as one"


def test_a_key_counted_as_another_kind_of_measurement_is_not_a_vector_s(
    tmp_path: Path, made: StandInStore, capsys: pytest.CaptureFixture[str]
) -> None:
    visible = measured(made, "visible", tmp_path / "v")
    held = _vector(made, "held_out", measured(made, "held_out", tmp_path / "h"))
    forged = json.loads(held.read_text())
    forged["tasks"][0]["passes"] = 2
    raw = canonical_json(forged)
    planted = held.with_name(f"{hashlib.sha256(raw).hexdigest()}.json")
    planted.write_bytes(raw)
    api("physgate.evaluation.tiers.exposure.record_measurement")(
        made.store, "control", made.version, measured="experiment", key=planted.stem
    )
    code, said = _gaps(
        capsys, tmp_path, design(made, visible, validation_tasks=None), visible, planted, None
    )
    assert code == 1 and said.get("refused_because") == "vector_unmeasured", said


def _orders(made: StandInStore, tier: str, m: Measured) -> list[Path]:
    """Five vectors of one run set, each in an order of its own."""
    orders: dict[tuple[int, ...], Path] = {}
    for _ in range(60):
        path = _vector(made, tier, m)
        orders.setdefault(tuple(t["passes"] for t in json.loads(path.read_text())["tasks"]), path)
        if len(orders) == 5:
            break
    assert len(orders) == 5, orders
    return list(orders.values())


def test_the_interval_does_not_depend_on_the_vector_s_order(
    tmp_path: Path, made: StandInStore, capsys: pytest.CaptureFixture[str]
) -> None:
    # Four tasks of each protected tier passing 0, 1, 2 and 3 of three trials: each write
    # shuffles them, and the same counts in another order give the same intervals.
    visible = measured(made, "visible", tmp_path / "v", trials=3)
    counts: dict[str, Any] = {"tasks": 4, "trials": 3, "outcome": lambda i, t: t < i}
    held = _orders(made, "held_out", measured(made, "held_out", tmp_path / "h", **counts))
    valid = _orders(made, "validation", measured(made, "validation", tmp_path / "w", **counts))
    body = design(made, visible, trials=3, held_out_tasks=4, validation_tasks=4)
    intervals: dict[str, set[tuple[float, float]]] = {"reward_hacking": set()}
    intervals["optimiser_overfit"] = set()
    for h, w in zip(held, valid, strict=True):
        code, said = _gaps(capsys, tmp_path, body, visible, h, w)
        assert code == 0, said
        for gap, seen in intervals.items():
            seen.add(tuple(said[gap]["interval"]))
    for gap, seen in intervals.items():
        assert len(seen) == 1, f"one count in five orders gave {len(seen)} {gap} intervals"


def test_runs_made_either_side_of_a_vector_write_are_refused_as_drift(
    tmp_path: Path, made: StandInStore, capsys: pytest.CaptureFixture[str]
) -> None:
    # Each run records the digest of every root it withholds as it is made, the role's withheld
    # root among them; writing a vector beneath that root changes it. So visible runs made
    # before the held-out tier's vector was written agree with it, and those made after are
    # refused as drift. No digest is pinned here.
    from physgate.evaluation.tiers.heldout import tier_digest

    def now() -> list[str]:
        return [tier_digest(Path(root)) for root in made.held_out]

    before = measured(made, "visible", tmp_path / "v0", held_out_sha256=now())
    held = _vector(
        made, "held_out", measured(made, "held_out", tmp_path / "h", held_out_sha256=now())
    )
    after = measured(made, "visible", tmp_path / "v1", held_out_sha256=now())
    body = design(made, before, validation_tasks=None)
    code, said = _gaps(capsys, tmp_path, body, before, held, None)
    assert code == 0, said
    code, said = _gaps(capsys, tmp_path, body, after, held, None)
    assert code == 1 and said.get("refused_because") == "drift", said
