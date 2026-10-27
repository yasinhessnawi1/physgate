"""Tests of launch.sh: its refusals before any review, and the shape of a block.

Run explicitly, from the repository root: ``uv run pytest -q experiments/R-PG-03``.

Nothing here reaches the network, reads a token or starts a review: the refusals tested come before
the first review, every place is under a fresh directory, and the block's shape is read from the
script itself.
"""

from __future__ import annotations

import os
import re
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
import common  # noqa: E402

LAUNCH = HERE / "launch.sh"
REPO = HERE.parent.parent


def launch(
    tmp: Path, *args: str, extra: dict[str, str] | None = None
) -> subprocess.CompletedProcess[str]:
    env = {k: v for k, v in os.environ.items() if not k.startswith("RP3_")}
    env.update({"HOME": str(tmp / "home"), **(extra or {})})
    (tmp / "home").mkdir(exist_ok=True)
    return subprocess.run(
        ["bash", str(LAUNCH), *args],
        capture_output=True,
        text=True,
        env=env,
        cwd=REPO,
        check=False,
        timeout=600,
    )


@pytest.mark.parametrize(
    "args", [(), ("--block",), ("--block", "x3"), ("--block", "x1", "--alone")]
)
def test_a_bad_command_line_is_refused_with_the_usage(
    tmp_path: Path, args: tuple[str, ...]
) -> None:
    done = launch(tmp_path, *args)
    assert done.returncode == 2 and "usage:" in done.stderr


def test_checks_only_needs_a_records_directory_of_its_own(tmp_path: Path) -> None:
    done = launch(tmp_path, "--block", "x1", "--checks-only")
    assert done.returncode == 1 and "needs RP3_RUNS" in done.stderr
    done = launch(
        tmp_path,
        "--block",
        "x1",
        "--checks-only",
        extra={"RP3_RUNS": str(tmp_path / "home" / "runs" / "rpg03" / "trial")},
    )
    assert done.returncode == 1 and "rpg03-trials" in done.stderr


def test_a_trial_s_records_lie_where_every_real_launch_holds_them_by_r3(tmp_path: Path) -> None:
    # A trial's records may hold copies of the sets: they lie under ~/runs/rpg03-trials, an R3
    # place of every real block.
    done = launch(
        tmp_path, "--block", "x1", "--checks-only", extra={"RP3_RUNS": str(tmp_path / "trial")}
    )
    assert done.returncode == 1 and "rpg03-trials" in done.stderr
    text = "\n".join(code())
    places = next(ln for ln in text.splitlines() if ln.startswith("PLACES=("))
    assert '--place "$TRIALS"' in places and 'TRIALS="$HOME/runs/rpg03-trials"' in text


def test_the_trial_s_settings_are_refused_on_a_run(tmp_path: Path) -> None:
    done = launch(tmp_path, "--block", "x1", extra={"RP3_MASTER_REF": "HEAD"})
    assert done.returncode == 1 and "--checks-only alone" in done.stderr


TRIAL = ("home", "runs", "rpg03-trials", "t1")


def test_a_check_only_trial_refuses_without_commits_filled(tmp_path: Path) -> None:
    trial = tmp_path.joinpath(*TRIAL)
    done = launch(
        tmp_path,
        "--block",
        "x1",
        "--checks-only",
        extra={"RP3_RUNS": str(trial), "RP3_TRIAL_HOST": "1", "RP3_R_K": str(REPO)},
    )
    log = next((trial / "blocks").glob("x1-*/launch.log")).read_text()
    assert done.returncode == 1 and "REFUSED: L2-commits" in log and "Commits filled" in log


def test_a_refused_pre_flight_keeps_its_attempt_s_number_and_its_log_beside(tmp_path: Path) -> None:
    trial = tmp_path.joinpath(*TRIAL)
    extra = {"RP3_RUNS": str(trial), "RP3_TRIAL_HOST": "1", "RP3_R_K": str(REPO)}
    for _ in range(2):
        assert launch(tmp_path, "--block", "x1", "--checks-only", extra=extra).returncode == 1
    blocks = trial / "blocks"
    assert sorted(p.name for p in blocks.iterdir()) == ["x1-1", "x1-1.refused-1"]
    for d in ("x1-1", "x1-1.refused-1"):
        assert "block x1, attempt 1," in (blocks / d / "launch.log").read_text()


def code() -> list[str]:
    return [ln for ln in LAUNCH.read_text().splitlines() if not ln.lstrip().startswith("#")]


def smoke_step() -> str:
    """The smoke's own step: from its branch's opening to its ``exit``."""
    text = "\n".join(code())
    start = text.index('if [ "$STOP_AFTER" = smoke ]; then')
    return text[start : text.index("\n  exit 0\nfi", start)]


def run_path() -> str:
    """A block's path: from the owner's confirmation to the arms' start."""
    text = "\n".join(code())
    return text[text.index("check L1-owner") : text.index("check start")]


def test_the_stages_run_in_the_documented_order() -> None:
    text = "\n".join(code())
    names = [
        "L1-host",
        "L1-order",
        "L1-owner",
        "L2-commits",
        "L2-generalist",
        "L3-binary",
        "L4-split",
        "L4-plan",
        "L5-sets",
        "L5-sheet",
        "L6-r4",
        "L7-r3",
        "L8-corpus",
        "check L11",
        "check start",
    ]
    after = text.index(smoke_step()) + len(smoke_step())
    where = [text.index(n, after) for n in names]
    assert where == sorted(where)


def test_the_smoke_is_a_step_of_its_own_before_the_window_s_confirmation() -> None:
    text = "\n".join(code())
    smoke = smoke_step()
    # The smoke's branch ends before the block's checks begin, and the owner's check of the window
    # (which needs a passed smoke ended before it) is the block's, never the smoke's.
    assert text.index(smoke) < text.index("check L1-owner")
    for step in ("L1-host", "L1-smoke", "L3-binary", "L5-sets", "L9-ff", 'streams.py" smoke'):
        assert step in smoke, step
    assert 'ledger.py" session --kind smoke' in smoke and "L1-owner" not in smoke


def test_no_step_after_the_window_s_confirmation_runs_on_the_run_account_before_the_block() -> None:
    # A refused pre-flight then writes no ledger line, so it never locks the first block out.
    path = run_path()
    for word in ('ledger.py" session', 'ledger.py" block', "streams.py", "rp3_exec_with_token"):
        assert word not in path, word


def test_the_smoke_counts_the_prefixes_with_scan_sh_and_ends_with_the_credentials_check() -> None:
    smoke = smoke_step()
    assert "prefix_counts" in smoke and "scan_written rp3_scan_token" in smoke
    assert "scan_written rp3_scan " not in smoke + " "
    record = smoke.index('checks.py" "${CK[@]}" smoke-record')
    assert smoke.index('checks.py" "${CK[@]}" credentials') < record
    assert smoke.index("rp3_drop_token") < smoke.index('checks.py" "${CK[@]}" credentials')


def test_l9_records_not_checked_and_refuses_only_on_a_key_s_count() -> None:
    smoke = smoke_step()
    assert 'check L9-ff py "$HERE/checks.py" "${CK[@]}" ff-status' in smoke
    assert "NOT CHECKED" in smoke and "the reading will be unchecked" in smoke


def test_the_three_arms_start_together_and_never_one_alone() -> None:
    text = "\n".join(code())
    assert text.count("start_one 0") == 1 and "start_one 1" in text and "start_one 2" in text
    assert re.search(r"STARTED\[2\] - STARTED\[0\]\)\) -gt 60", text)
    assert "first_minute.txt" in text and "stop_all" in text
    assert re.search(r'watch_limit\.sh" "\$LAUNCH/watcher\.log" block', text)
    for arm, checkout, mode in (("A2", "CHECKOUT", ""), ("B", "R_K_CHECKOUT", "--generalist")):
        assert arm in text and checkout in text and mode in text


def test_every_arm_runs_the_block_s_seed_lanes_per_class_and_its_own_root() -> None:
    text = "\n".join(code())
    for flag in (
        '--seed "$(SEED_OF',
        '--lanes "$(lanes_of',
        '--per-class "$(PER_CLASS_OF',
        '--scratch "$(scratch_of',
        "--review-clean-twins",
    ):
        assert flag in text
    seed_line = next(ln for ln in text.splitlines() if ln.startswith("SEED_OF()"))
    seeds = dict(re.findall(r"(\w+)\) echo (\d+) ;;", seed_line))
    assert {
        k: int(v)
        for k, v in seeds.items()
        if k in ("x1", "y1", "z1", "z2", "y2", "x2", "s", "p1", "p2")
    } == {"x1": 53, "y1": 59, "z1": 83, "z2": 89, "y2": 67, "x2": 61, "s": 71, "p1": 73, "p2": 79}


def test_each_block_s_size_per_class_is_the_one_the_instrument_holds_its_corpus_to() -> None:
    text = "\n".join(code())
    line = next(ln for ln in text.splitlines() if ln.startswith("PER_CLASS_OF()"))
    sizes = {k: int(v) for k, v in re.findall(r"(\S+)\) echo (\d+) ;;", line)}
    # Block s's corpus holds the standard class alone, ten of it; every other batch, five of each
    # of the four classes.
    assert sizes == {"s": common.PER_CLASS_S, "*": common.PER_CLASS_BATCH} == {"s": 10, "*": 5}
    assert common.BLOCK_ITEMS["s"] == common.PER_CLASS_S
    assert all(common.BLOCK_ITEMS[b] == 4 * common.PER_CLASS_BATCH for b in common.PRIMARY_BLOCKS)


def test_the_end_of_a_block_checks_ledgers_logins_and_scans_before_it_says_valid() -> None:
    text = "\n".join(code())
    for step in (
        'checks.py" "${CK[@]}" after',
        'ledger.py" block',
        'checks.py" "${CK[@]}" credentials',
        'prefix_counts "${WRITTEN[@]}"',
        'scan_written rp3_scan_token "${WRITTEN[@]}" "$LAUNCH"',
        "rp3_drop_token",
    ):
        assert step in text, step
    assert text.index('prefix_counts "${WRITTEN[@]}"') < text.rindex("rp3_drop_token")
    assert 'count_files_with "$pattern"' in text  # the prefixes are counted with scan.sh


def test_a_deviation_is_refused_as_one_and_never_said_void() -> None:
    text = "\n".join(code())
    assert "DEVIATION" in text and "checks.py classify" in text


def test_an_arm_stopped_or_crashed_has_its_sessions_stopped_before_the_end_checks() -> None:
    # The instrument starts each review session in a session of its own and cannot end them once
    # killed: the launch stops what the review roots' records prove still running, and removes
    # their login files, as the watcher does at a limit.
    text = "\n".join(code())
    waits = text.index('wait "${PIDS[$i]}"')
    stop = text.index('checks.py" "${CK[@]}" stop-sessions', waits)
    assert stop < text.index('checks.py" "${CK[@]}" after')
    call = text[stop : text.index("\n", stop)]
    for arm in ("A2", "A1", "B"):
        assert f'--scratch "$(scratch_of {arm})"' in call
    guard = text[text.rindex("\nif ", 0, stop) : stop]
    assert "first_minute.txt" in guard and "ABNORMAL" in guard


def test_before_the_first_block_the_practice_figure_is_checked_as_the_tally_checks_it() -> None:
    smoke = smoke_step()
    call = smoke.index('tally3.py" practice-figure --practice "round-1=$RP3_PRACTICE_ROUND1"')
    assert call < smoke.index('streams.py" smoke')
    handling = smoke[call : smoke.index("esac", call)]
    assert "1)" in handling and "NOT COMPUTABLE" in handling and "refuse" in handling


def test_a_login_file_left_after_the_block_refuses_it_valid() -> None:
    text = "\n".join(code())
    end = text.index('checks.py" "${CK[@]}" after')  # the block's end, not the smoke's
    credentials = text.index('CREDENTIALS_OK=1; py "$HERE/checks.py" "${CK[@]}" credentials', end)
    refusal = text.index('[ "$CREDENTIALS_OK" = 1 ] || refuse', credentials)
    assert refusal < text.index("is valid", refusal)


@pytest.mark.skipif(shutil.which("shellcheck") is None, reason="shellcheck is not installed here")
def test_every_script_passes_shellcheck_from_the_repository_root() -> None:
    scripts = sorted(str(p.relative_to(REPO)) for p in HERE.glob("*.sh"))
    done = subprocess.run(
        ["shellcheck", *scripts], capture_output=True, text=True, check=False, cwd=REPO
    )
    assert done.returncode == 0, done.stdout[-2000:]


def test_l2_holds_the_block_s_own_commits_a_corrected_one_for_an_instrument_defect() -> None:
    text = "\n".join(code())
    line = next(ln for ln in text.splitlines() if ln.startswith("check L2-commits"))
    assert line.endswith('--block "$BLOCK"')
