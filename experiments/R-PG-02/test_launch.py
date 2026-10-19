"""Tests of launch.sh: its refusals before any run, its pins, and the scan it counts with.

Run explicitly, from the repository root: uv run pytest -q experiments/R-PG-02/

Nothing here reaches the network, reads a token or starts a run: the refusals tested come
before the script's first fetch, with ``uname`` stood in for and every place under a fresh
directory.
"""

from __future__ import annotations

import os
import re
import subprocess
from pathlib import Path

import pytest

HERE = Path(__file__).resolve().parent
REPO = HERE.parent.parent
LAUNCH = HERE / "launch.sh"
FILL = "[FILL AT FREEZE]"
#: The only values left to the freeze (and the fresh set's dated fill).
FILLED_AT_FREEZE = {
    "TOOLING_COMMIT",
    "RUBRICS_TREE",
    "RUBRIC_CONTROL",
    "RUBRIC_ELECTRICAL",
    "RUBRIC_FIRMWARE",
    "RUBRIC_MECHANICAL",
    "FRESH_MANIFEST_SHA256",
    "OLD_TWINS_COUNT",
    "OLD_TWINS_RECORDS_SHA256",
}


def pins() -> dict[str, str]:
    """Every ``NAME=value`` the script pins at its top."""
    text = LAUNCH.read_text()
    block = text[text.index("# ---- what CRITERIA.md") : text.index("# ---- where things go")]
    return dict(re.findall(r'^([A-Z0-9_]+)="?([^"\n]+)"?$', block, re.MULTILINE))


def launch(tmp_path: Path, uname: str, *args: str) -> subprocess.CompletedProcess[str]:
    stub = tmp_path / "bin"
    stub.mkdir(exist_ok=True)
    (stub / "uname").write_text(f"#!/bin/sh\necho {uname}\n")
    (stub / "uname").chmod(0o755)
    env = {
        **os.environ,
        "PATH": f"{stub}:{os.environ['PATH']}",
        "HOME": str(tmp_path / "home"),
        "R_PG_02_RUN_ROOT": str(tmp_path / "runs"),
        "R_PG_02_REVIEW_BASE": str(tmp_path / "rv"),
        "R_PG_02_PRACTICE": str(tmp_path / "practice"),
        "R_PG_02_PRACTICE_RUNS": str(tmp_path / "practice-runs"),
    }
    return subprocess.run(
        ["bash", str(LAUNCH), *args],
        capture_output=True,
        text=True,
        env=env,
        cwd=REPO,
        check=False,
        timeout=60,
    )


def test_an_unknown_flag_is_refused_with_the_usage(tmp_path: Path) -> None:
    done = launch(tmp_path, "Linux", "--only-a-fresh")
    assert done.returncode == 2 and "usage:" in done.stderr


def test_another_machine_is_refused_before_anything(tmp_path: Path) -> None:
    done = launch(tmp_path, "Darwin")
    assert done.returncode == 1 and "REFUSED: the run machine" in done.stderr
    assert not (tmp_path / "runs" / "attempt-1").exists()


def test_the_practice_places_must_be_named(tmp_path: Path) -> None:
    stub = tmp_path / "bin"
    stub.mkdir()
    (stub / "uname").write_text("#!/bin/sh\necho Linux\n")
    (stub / "uname").chmod(0o755)
    env = {k: v for k, v in os.environ.items() if not k.startswith("R_PG_02_")}
    env.update(
        {
            "PATH": f"{stub}:{os.environ['PATH']}",
            "HOME": str(tmp_path / "home"),
            "R_PG_02_RUN_ROOT": str(tmp_path / "runs"),
        }
    )
    done = subprocess.run(
        ["bash", str(LAUNCH)],
        capture_output=True,
        text=True,
        env=env,
        cwd=REPO,
        check=False,
        timeout=60,
    )
    assert done.returncode == 1 and "name the practice set" in done.stderr


def test_an_attempt_is_never_resumed(tmp_path: Path) -> None:
    (tmp_path / "runs" / "attempt-1").mkdir(parents=True)
    done = launch(tmp_path, "Linux", "--preflight-only")
    assert done.returncode == 1 and "already exists" in done.stderr


def test_a_used_review_root_is_refused_too(tmp_path: Path) -> None:
    (tmp_path / "rv" / "rp2-1-2").mkdir(parents=True)
    done = launch(tmp_path, "Linux", "--through-r4")
    assert done.returncode == 1 and "rp2-1-2 already exists" in done.stderr


def test_the_three_runs_start_together_and_never_one_alone() -> None:
    text = LAUNCH.read_text()
    calls = re.findall(r"^start_one (\d)$", text, re.MULTILINE)
    assert calls == ["0", "1", "2"]
    assert re.search(r"^RUNS=\(a-fresh b-fresh a-old\)$", text, re.MULTILINE)
    flags = re.findall(r"^  (--[a-z0-9-]+)\)", text, re.MULTILINE)
    assert flags == ["--preflight-only", "--through-r4"]
    assert "stop_all" in text and "-le 60" in text
    assert text.count("--generalist") == 1


def test_only_the_freeze_s_values_are_left_to_fill() -> None:
    pinned = pins()
    assert {k for k, v in pinned.items() if v == FILL} == FILLED_AT_FREEZE
    criteria = (HERE / "CRITERIA.md").read_text()
    for name, value in pinned.items():
        if value != FILL and re.fullmatch(r"[0-9a-f]{40}|[0-9a-f]{64}", value):
            assert value in criteria, name


@pytest.mark.parametrize(
    ("name", "path"),
    [
        ("GATE_TREE", "src/physgate/gate"),
        ("REVIEWERS_TREE", "src/physgate/reviewers"),
        ("INJECT_TREE", "src/physgate/evaluation/inject"),
        ("SPELLING_BLOB", "src/physgate/unit_spelling.py"),
        ("BOUNDS_ELECTRICAL_BLOB", "knowledge/electrical/bounds.toml"),
        ("BOUNDS_CROSS_BLOB", "knowledge/cross/bounds.toml"),
    ],
)
def test_the_pinned_trees_are_this_commit_s(name: str, path: str) -> None:
    """At the run's commit, every tree and blob the script holds it to is the checkout's."""
    here = subprocess.run(
        ["git", "rev-parse", f"HEAD:{path}"], capture_output=True, text=True, cwd=REPO, check=True
    ).stdout.strip()
    assert pins()[name] == here


def test_the_pinned_digests_are_this_commit_s() -> None:
    from physgate.evaluation.inject.materialise import ACCOUNT_SHA256
    from physgate.gate.catalogue import catalogue_digest

    assert pins()["CATALOGUE_SHA256"] == catalogue_digest()
    assert pins()["ACCOUNT_SHA256"] == ACCOUNT_SHA256


@pytest.mark.parametrize(("planted", "count"), [(False, "0"), (True, "1")])
def test_the_scan_counts_an_empty_directory_as_zero_under_pipefail(
    tmp_path: Path, planted: bool, count: str
) -> None:
    (tmp_path / "d").mkdir()
    if planted:
        (tmp_path / "d" / "f.txt").write_text("sk-ant-" + "x" * 8)
    done = subprocess.run(
        [
            "bash",
            "-c",
            "set -euo pipefail; source scripts/experiment/scan.sh; "
            'n="$(count_files_with sk-ant- "$1")"; echo "n=$n done"',
            "_",
            str(tmp_path / "d"),
        ],
        capture_output=True,
        text=True,
        cwd=REPO,
        check=False,
    )
    assert done.returncode == 0 and done.stdout.strip() == f"n={count} done"


def test_the_script_is_clean_under_shellcheck() -> None:
    import shutil

    tool = shutil.which("shellcheck")
    if tool is None:
        pytest.skip("shellcheck is not installed here")
    done = subprocess.run(
        [tool, "-x", str(LAUNCH)], capture_output=True, text=True, cwd=HERE, check=False
    )
    assert done.returncode == 0, done.stdout
