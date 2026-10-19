"""Tests of R-PG-02's run scripts, each on the fixture set, a real run of it, or an empty directory.

Run explicitly, from the repository root: uv run pytest -q experiments/R-PG-02/

Every script is run as the launch script runs it: ``python -I <script>``, its exit code and
its one JSON line read. No set of the experiment is read, and nothing is called.
"""

from __future__ import annotations

import json
import shutil
import subprocess
import sys
from pathlib import Path
from typing import Any

import pytest
import rpg02_fixture as fx

HERE = Path(__file__).resolve().parent
REPO = HERE.parent.parent


def script(name: str, *args: str | Path) -> tuple[int, dict[str, Any]]:
    """Run one script as the launch script does; its exit code and its last JSON line."""
    done = subprocess.run(
        [sys.executable, "-I", str(HERE / name), *map(str, args)],
        capture_output=True,
        text=True,
        cwd=REPO,
        check=False,
    )
    lines = [x for x in done.stdout.splitlines() if x.startswith("{")]
    return done.returncode, (json.loads(lines[-1]) if lines else {"stderr": done.stderr})


@pytest.fixture(scope="module")
def made(tmp_path_factory: pytest.TempPathFactory) -> dict[str, Path]:
    base = tmp_path_factory.mktemp("made")
    sourced = fx.write_set(base / "set-s")
    plain = fx.ic.write_corpus(base / "set-p")
    return {
        "base": base,
        "sourced": sourced,
        "plain": plain,
        "run": fx.real_run(sourced, base / "r1", 13, {}, lanes=2),
    }


# ---- lanes.py ------------------------------------------------------------------------------


def test_the_split_gives_the_fresh_arms_equal_lanes_and_the_files_hold_it() -> None:
    lanes = fx_lanes()
    assert lanes.split() == {"a-fresh": 1, "b-fresh": 1, "a-old": 2}
    assert sum(lanes.split().values()) == lanes.BUDGET == 4
    with pytest.raises(ValueError):
        lanes.split(2)
    code, out = script("lanes.py", "split", HERE / "params_fresh.json", HERE / "params_old.json")
    assert code == 0 and out["holds"]
    code, out = script("lanes.py", "split", HERE / "params_old.json", HERE / "params_old.json")
    assert code == 1 and not out["holds"]


def test_the_plan_is_what_the_run_writes_and_every_review_ran_on_its_lane(
    made: dict[str, Path],
) -> None:
    code, plan = script("lanes.py", "plan", made["sourced"], 13, 2)
    assert code == 0 and plan["holds"]
    assert sum(plan["items_per_lane"].values()) == 4
    import hashlib

    assert (
        hashlib.sha256((made["run"] / "lanes.json").read_bytes()).hexdigest()
        == plan["lanes_json_sha256"]
    )
    code, out = script("lanes.py", "check", made["run"], made["sourced"], 13, 2)
    assert code == 0 and out == {
        "holds": True,
        "lanes_json_is_the_plan": True,
        "review_records_missing": 0,
        "reviews_off_their_lane": [],
    }
    moved = made["base"] / "moved"
    shutil.copytree(made["run"], moved)
    record = next((moved / "reviews").glob("*.json"))
    data = json.loads(record.read_text())
    data["lane"] = 1 - data["lane"]
    record.write_text(json.dumps(data))
    code, out = script("lanes.py", "check", moved, made["sourced"], 13, 2)
    assert code == 1 and out["reviews_off_their_lane"] == [record.stem]


def test_lanes_refuses_a_missing_set_and_a_bad_call(
    tmp_path_factory: pytest.TempPathFactory,
) -> None:
    empty = tmp_path_factory.mktemp("empty")
    code, out = script("lanes.py", "plan", empty, 13, 1)
    assert code == 1 and "refused" in out
    assert script("lanes.py", "nothing")[0] == 2


def fx_lanes() -> Any:  # noqa: ANN401 - a module
    import importlib.util

    spec = importlib.util.spec_from_file_location("rpg02_lanes", HERE / "lanes.py")
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


# ---- r3_scan.py ----------------------------------------------------------------------------


def test_the_scan_holds_for_new_roots_apart_from_every_set(made: dict[str, Path]) -> None:
    roots = [made["base"] / "rv" / f"rp2-1-{k}" for k in (1, 2, 3)]
    code, out = script(
        "r3_scan.py",
        "--checkout",
        REPO,
        *[a for r in roots for a in ("--root", r)],
        "--set",
        f"one={made['sourced']}",
        "--set",
        f"two={made['plain']}",
        "--place",
        made["run"],
    )
    assert code == 0, out
    assert out["problems"] == [] and out["library_files_checked"] > 0
    assert set(out["sets"]) == {"one", "two"}


@pytest.mark.parametrize(
    "case",
    [
        "root_inside_a_set",
        "root_not_empty",
        "root_named_for_the_harness",
        "two_roots_nested",
        "library_holds_a_set_file",
        "no_root",
    ],
)
def test_the_scan_stops_on_each_kind_of_hit(made: dict[str, Path], case: str) -> None:
    where = made["base"] / f"hit-{case}"
    where.mkdir()
    checkout, roots = REPO, [where / "rv-a"]
    if case == "root_inside_a_set":
        roots = [made["sourced"] / "rv"]
    elif case == "root_not_empty":
        roots[0].mkdir()
        (roots[0] / "left.txt").write_text("x")
    elif case == "root_named_for_the_harness":
        roots = [where / "physgate-reviews"]
    elif case == "two_roots_nested":
        roots = [where / "rv-a", where / "rv-a" / "inner"]
    elif case == "library_holds_a_set_file":
        checkout = where / "checkout"
        (checkout / "knowledge").mkdir(parents=True)
        shutil.copy(made["sourced"] / "base.json", checkout / "knowledge" / "copy.json")
    elif case == "no_root":
        roots = []
    code, out = script(
        "r3_scan.py",
        "--checkout",
        checkout,
        *[a for r in roots for a in ("--root", r)],
        "--set",
        f"one={made['sourced']}",
    )
    assert code == 1 and out["problems"], case


# ---- twins_old.py and twins_fresh.py -------------------------------------------------------


def test_the_old_twins_check_measures_once_then_holds_the_run_to_it(made: dict[str, Path]) -> None:
    code, first = script("twins_old.py", made["sourced"], made["base"] / "o1", "--any-count")
    assert code == 0 and first["measured"] and first["twins_with_no_failing_record"] == 2
    assert set(first) == {
        "manifest_sha256",
        "measured",
        "records_sha256",
        "twins",
        "twins_with_no_failing_record",
    }
    code, again = script(
        "twins_old.py",
        made["sourced"],
        made["base"] / "o2",
        "2",
        first["records_sha256"],
        "--any-count",
    )
    assert code == 0 and again["holds"]
    code, off = script(
        "twins_old.py", made["sourced"], made["base"] / "o3", "2", "0" * 64, "--any-count"
    )
    assert code == 1 and not off["holds"]


def test_the_old_twins_check_refuses_a_used_directory_and_an_incomplete_set(
    made: dict[str, Path],
) -> None:
    used = made["base"] / "used"
    used.mkdir()
    assert script("twins_old.py", made["sourced"], used, "--any-count")[0] != 0
    assert script("twins_old.py", made["sourced"], made["base"] / "o4")[0] != 0


def test_the_fresh_twins_precondition_needs_the_gate_and_the_source_check(
    made: dict[str, Path],
) -> None:
    code, out = script("twins_fresh.py", made["sourced"], made["base"] / "f1", "--any-count")
    assert code == 0 and out["holds"]
    assert out["source_check"] == {"mismatch": 0, "unresolved": 2, "subtracted": 0}
    # The instrument's plain test set cites one page for every number: its rows disagree.
    code, out = script("twins_fresh.py", made["plain"], made["base"] / "f2", "--any-count")
    assert code == 1 and out["source_check"]["mismatch"] > 0
    assert script("twins_fresh.py", made["sourced"], made["base"] / "f3")[0] != 0


# ---- regate.py and read_catches.py ---------------------------------------------------------


def test_a_second_gate_pass_repeats_the_run_byte_for_byte(made: dict[str, Path]) -> None:
    code, out = script("regate.py", "again", made["sourced"], made["run"], 13, made["base"] / "g1")
    assert code == 0 and out == {"compared": 4, "differ": 0, "holds": True, "missing": 0}
    code, out = script("regate.py", "compare", made["run"], made["run"])
    assert code == 0 and out["holds"] and out["compared"] == 4


def test_a_changed_gate_line_is_a_difference(made: dict[str, Path]) -> None:
    changed = made["base"] / "changed"
    shutil.copytree(made["run"], changed)
    log = changed / "events.jsonl"
    lines = [json.loads(x) for x in log.read_text().splitlines()]
    for line in lines:
        if line["kind"] == "gate_ran":
            line["result"]["finding"] = line["result"]["finding"] + " (edited)"
            break
    log.write_text("".join(json.dumps(x) + "\n" for x in lines))
    code, out = script("regate.py", "compare", made["run"], changed)
    assert code == 1 and out["differ"] == 1
    assert script("regate.py", "nothing")[0] == 2


def test_the_catches_command_agrees_with_the_rows(made: dict[str, Path]) -> None:
    code, out = script("read_catches.py", made["run"])
    assert code == 0, out
    assert out["caught_from_rows"] == 2 and out["twins_failed_from_rows"] == 0
