"""Tests of lanes.py (§3.4, R8) and regate.py (R6), on real runs of the fixture set.

Run explicitly, from the repository root: ``uv run pytest -q experiments/R-PG-03``.
"""

from __future__ import annotations

import json
import shutil
import sys
from pathlib import Path
from typing import Any

import pytest

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
import common  # noqa: E402
import fixture as fx  # noqa: E402
import lanes  # noqa: E402
import regate  # noqa: E402


@pytest.fixture(scope="module")
def made(tmp_path_factory: pytest.TempPathFactory) -> dict[str, Any]:
    base = tmp_path_factory.mktemp("lanes")
    corpus = fx.write_set(base / "fresh-v2-x1")
    seed = common.BLOCK_SEED["x1"]
    runs = {arm: fx.real_run(corpus, base / arm, seed, arm, {}) for arm in common.ARMS}
    return {"base": base, "corpus": corpus, "runs": runs}


def test_the_split_is_3_3_2_and_the_files_are_r_pg_02_s_but_lanes() -> None:
    found = lanes.split()
    assert found["holds"] and found["files"] == {"A2": 3, "A1": 3, "B": 2}
    assert (HERE / "params_a.json").read_bytes() == (common.REPO / common.PARAMS_FRESH).read_bytes()


def test_a_parameters_file_that_differs_in_another_field_or_in_lanes_fails(tmp_path: Path) -> None:
    for name in ("params_a.json", "params_b.json"):
        shutil.copy(HERE / name, tmp_path / name)
    data = json.loads((tmp_path / "params_b.json").read_text())
    data["effort"] = "low"
    (tmp_path / "params_b.json").write_text(json.dumps(data))
    found = lanes.split(here=tmp_path)
    assert not found["holds"] and found["fields_other_than_lanes_that_differ"]["B"] == ["effort"]
    data["effort"] = "high"
    data["lanes"] = 3
    (tmp_path / "params_b.json").write_text(json.dumps(data))
    assert not lanes.split(here=tmp_path)["holds"]


def test_a_block_s_plan_is_seeded_and_a2_and_a1_share_it(made: dict[str, Any]) -> None:
    found = lanes.plan(made["corpus"], "x1")
    assert found["holds"] and found["seed"] == 53 and found["a2_and_a1_share_a_plan"]
    assert sum(found["plans"]["B"]["items_per_lane"].values()) == 8  # four items and their twins


def test_each_arm_s_run_ran_on_its_plan_and_a_moved_review_is_found(
    made: dict[str, Any], tmp_path: Path
) -> None:
    for arm, run in made["runs"].items():
        assert lanes.check(run, made["corpus"], "x1", arm)["holds"], arm
    moved = fx.copy_run(made["runs"]["A2"], tmp_path / "run")
    record = next((moved / "reviews").glob("*.json"))
    data = json.loads(record.read_text())
    data["lane"] = (data["lane"] + 1) % 3
    record.write_text(json.dumps(data))
    assert not lanes.check(moved, made["corpus"], "x1", "A2")["holds"]


def test_r6_the_gate_repeats_and_every_arm_s_records_are_a2_s(
    made: dict[str, Any], tmp_path: Path
) -> None:
    found = regate.block("x1", made["corpus"], made["runs"], tmp_path / "again")
    assert found["holds"], found
    b = fx.copy_run(made["runs"]["B"], tmp_path / "b")
    log = b / "events.jsonl"
    lines = [json.loads(x) for x in log.read_text().splitlines()]
    for x in lines:
        if x.get("kind") == "gate_ran":
            x["result"]["checks"] = x["result"]["checks"][:-1]
            break
    log.write_text("".join(json.dumps(x) + "\n" for x in lines))
    found = regate.block("x1", made["corpus"], {**made["runs"], "B": b}, tmp_path / "again2")
    assert not found["holds"] and found["b_against_a2"]["differ"] == 1


def test_block_s_s_plan_deals_its_one_class_round_the_lanes_and_its_runs_keep_it(
    tmp_path: Path,
) -> None:
    corpus = fx.write_set(tmp_path / common.BLOCK_CORPUS["s"], standard=True)
    found = lanes.plan(corpus, "s")
    assert found["holds"] and found["seed"] == 71 and found["a2_and_a1_share_a_plan"]
    for arm in ("A2", "B"):
        per_lane = found["plans"][arm]["classes_per_lane"]
        assert list(per_lane) == [common.STANDARD_CLASS], arm
        assert sum(per_lane[common.STANDARD_CLASS].values()) == 4, arm
    run = fx.real_run(corpus, tmp_path / "A2", 71, "A2", {})
    assert lanes.check(run, corpus, "s", "A2")["holds"]
    assert regate.block("s", corpus, {"A2": run, "A1": run, "B": run}, tmp_path / "again")["holds"]
