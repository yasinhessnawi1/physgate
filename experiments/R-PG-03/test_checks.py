"""Tests of checks.py: the block order and dates, the owner, R and R_K, R3, and an attempt's end.

Run explicitly, from the repository root: ``uv run pytest -q experiments/R-PG-03``.

R and R_K are this checkout's HEAD and a commit made in a temporary worktree that restores the
five paths to K's state, never pushed; the runs are the fixture's.
"""

from __future__ import annotations

import json
import os
import platform
import re
import signal
import subprocess
import sys
from pathlib import Path
from typing import Any

import pytest

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
import checks as ck  # noqa: E402
import common  # noqa: E402
import fixture as fx  # noqa: E402
import tally3 as t3  # noqa: E402

AFTER = ck._seconds("2026-11-06T09:00:00Z")
#: The owner's account file: a weekly reset read from the usage page, Thursdays at 07:00 UTC.
ACCOUNT = {"account_label": "the run account", "weekly_reset_utc": "2026-10-29T07:00:00Z"}
#: Thursday 5.11's reset and the next week's, as that one reset gives them.
FIRST, SECOND = "2026-11-05T07:00:00Z", "2026-11-12T07:00:00Z"


def holds(call: Any) -> Any:  # noqa: ANN401
    """The call returns; one of this module's refusals fails on an assertion."""
    return fx.holds(call, ck.RefusedError, common.RefusedError)


@pytest.fixture
def runs_dir(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    monkeypatch.setenv("RP3_RUNS", str(tmp_path / "runs"))
    owner_file(tmp_path / "runs", "account.json", ACCOUNT)
    return tmp_path / "runs"


def blocks(
    runs: Path, attempts: list[dict[str, Any]], not_run: dict[str, str] | None = None
) -> None:
    fx.write_blocks(runs, attempts, not_run)


def att(block: str, valid: bool | None) -> dict[str, Any]:
    return {"block": block, "attempt": 1, "valid": valid}


# ---- the order, the void attempts, the dates -----------------------------------------------------


def test_the_first_block_may_start_on_its_date_and_not_before(runs_dir: Path) -> None:
    assert ck.order("x1", now=AFTER)["attempt"] == 1
    with pytest.raises(ck.RefusedError, match="2026-11-05"):
        ck.order("x1", now=ck._seconds("2026-11-04T23:00:00Z"))


def test_r_pg_01b_in_a_second_window_moves_the_first_start_a_week(runs_dir: Path) -> None:
    ledger = [{"kind": "rpg01b-round", "started_utc": "2026-11-05T08:00:00Z"}]
    with pytest.raises(ck.RefusedError, match="2026-11-12"):
        ck.order("x1", now=AFTER, ledger=ledger)


def test_r_pg_01b_re_attempting_a_round_after_the_5_11_reset_moves_the_start_a_week(
    runs_dir: Path,
) -> None:
    # R-PG-01b's ledger gives a round's earliest attempt's start: a round voided before 5.11 and
    # re-run after the reset keeps its older start, and its end tells that it ran on.
    line = {
        "kind": "rpg01b-round",
        "started_utc": "2026-11-04T10:00:00Z",
        "ended_utc": "2026-11-05T18:00:00Z",
        "attempts": 2,
    }
    with pytest.raises(ck.RefusedError, match="2026-11-12"):
        ck.order("x1", now=AFTER, ledger=[line])
    before = {**line, "ended_utc": "2026-11-04T20:00:00Z"}
    assert ck.order("x1", now=AFTER, ledger=[before])["earliest"] == FIRST


@pytest.mark.parametrize(
    ("ended", "earliest"),
    [("2026-11-05T06:59:59Z", FIRST), ("2026-11-05T07:00:00Z", SECOND)],
    ids=["a-second-before-5-11-s-reset", "at-5-11-s-reset"],
)
def test_the_blocks_earliest_start_is_5_11_s_reset_from_the_owner_s_recorded_one(
    runs_dir: Path, ended: str, earliest: str
) -> None:
    # A line of R-PG-01b's ending at 5.11's reset or later ran into its second weekly window.
    line = {"kind": "rpg01b-round", "started_utc": "2026-11-04T10:00:00Z", "ended_utc": ended}
    assert ck.earliest_start([line]) == earliest
    # A reset that falls on 5.11 local time: Thursday 00:30 in Norway is Wednesday 23:30 UTC.
    owner_file(runs_dir, "account.json", {**ACCOUNT, "weekly_reset_utc": "2026-10-28T23:30:00Z"})
    assert ck.earliest_start([]) == "2026-11-04T23:30:00Z"
    (runs_dir / "owner" / "account.json").unlink()
    fx.refuses(ck.RefusedError, "records no weekly reset", lambda: ck.earliest_start([]))


@pytest.mark.parametrize(
    ("stamp", "why"),
    [("2026-11-07T07:00:00Z", "after now"), ("2026-11-04T07:00:00Z", "before")],
    ids=["in-the-future", "before-the-earliest-start"],
)
def test_the_window_s_confirmation_is_bounded_in_time(runs_dir: Path, stamp: str, why: str) -> None:
    owner_file(runs_dir, "block-x1-1.json", BLOCK_X1)
    owner_file(runs_dir, "window.json", {"weekly_limit_reset_confirmed_utc": stamp})
    smoked(runs_dir, (0, "2026-11-04T06:00:00Z"))
    with pytest.raises(ck.RefusedError, match=why):
        ck.owner("x1", 1, [], now=AFTER)


def test_the_window_s_confirmation_is_after_r_pg_01b_s_second_window_began_if_it_ran_into_one(
    runs_dir: Path,
) -> None:
    owner_file(runs_dir, "block-x1-1.json", BLOCK_X1)
    owner_file(runs_dir, "window.json", WINDOW)  # 5.11, 07:00
    smoked(runs_dir, (0, "2026-11-04T06:00:00Z"))
    ran_on = {
        "kind": "rpg01b-round",
        "started_utc": "2026-11-05T01:00:00Z",
        "ended_utc": "2026-11-05T09:00:00Z",
    }
    with pytest.raises(ck.RefusedError, match="before"):
        ck.owner("x1", 1, [ran_on], now=ck._seconds("2026-11-13T09:00:00Z"))


def test_the_fixed_order_holds(runs_dir: Path) -> None:
    with pytest.raises(ck.RefusedError, match="x1 comes first"):
        ck.order("y1", now=AFTER)
    blocks(runs_dir, [att(b, True) for b in common.PRIMARY_BLOCKS])
    assert ck.order("s", now=AFTER)["block"] == "s"
    blocks(runs_dir, [att(b, True) for b in common.PRIMARY_BLOCKS], {"s": "the class's cap"})
    assert ck.order("p1", now=AFTER)["block"] == "p1"
    with pytest.raises(ck.RefusedError, match="not run"):
        ck.order("s", now=AFTER)


def test_a_block_is_never_resumed_and_three_voids_go_to_the_owner(runs_dir: Path) -> None:
    blocks(runs_dir, [att("x1", None)])
    with pytest.raises(ck.RefusedError, match="not been closed"):
        ck.order("x1", now=AFTER)
    blocks(runs_dir, [att("x1", False), att("x1", False)])
    assert ck.order("x1", now=AFTER)["attempt"] == 3
    blocks(runs_dir, [att("x1", False)] * 3)
    with pytest.raises(ck.RefusedError, match="owner declares"):
        ck.order("x1", now=AFTER)
    blocks(runs_dir, [att("x1", True)])
    with pytest.raises(ck.RefusedError, match="already has a valid"):
        ck.order("x1", now=AFTER)


def test_only_s_p1_and_p2_may_be_recorded_as_not_run(runs_dir: Path) -> None:
    with pytest.raises(ck.RefusedError):
        ck.not_run("x1", "no")
    assert ck.not_run("p1", "fresh-v1c failed its acceptance checks")["block"] == "p1"


# ---- the owner's word ----------------------------------------------------------------------------


def owner_file(runs: Path, name: str, data: dict[str, Any]) -> None:
    (runs / "owner").mkdir(parents=True, exist_ok=True)
    (runs / "owner" / name).write_text(json.dumps(data))


def test_the_owner_confirms_each_block_and_the_window_before_the_first(runs_dir: Path) -> None:
    with pytest.raises(ck.RefusedError, match="no owner confirmation"):
        ck.owner("x1", 1, [])
    owner_file(
        runs_dir,
        "block-x1-1.json",
        {"account_label": "the run account", "no_other_session_on_the_run_account": False},
    )
    with pytest.raises(ck.RefusedError, match="no other session"):
        ck.owner("x1", 1, [])
    owner_file(
        runs_dir,
        "block-x1-1.json",
        {"account_label": "the run account", "no_other_session_on_the_run_account": True},
    )
    with pytest.raises(ck.RefusedError, match="window"):
        ck.owner("x1", 1, [])
    owner_file(
        runs_dir, "window.json", {"weekly_limit_reset_confirmed_utc": "2026-11-05T07:00:00Z"}
    )
    smoked(runs_dir, (0, "2026-11-04T21:00:00Z"))
    assert ck.owner("x1", 1, [], now=AFTER)["window_confirmed_utc"] == "2026-11-05T07:00:00Z"
    later = [{"kind": "authoring", "started_utc": "2026-11-05T07:30:00Z"}]
    with pytest.raises(ck.RefusedError, match="nothing else runs"):
        ck.owner("x1", 1, later, now=AFTER)
    blocks(runs_dir, [att("x1", True)])
    owner_file(
        runs_dir,
        "block-y1-1.json",
        {"account_label": "a", "no_other_session_on_the_run_account": True},
    )
    assert ck.owner("y1", 1, later)["first_block"] is False


WINDOW = {"weekly_limit_reset_confirmed_utc": "2026-11-05T07:00:00Z"}
BLOCK_X1 = {"account_label": "the run account", "no_other_session_on_the_run_account": True}


def smoked(runs: Path, *attempts: tuple[int, str]) -> None:
    """The smoke record: each attempt's exit code and end."""
    for code, ended in attempts:
        ck.smoke_record(code, "2026-11-04T20:00:00Z", ended, "every key matches one line", runs)


def test_the_first_block_needs_a_passed_smoke_ended_before_the_window_s_confirmation(
    runs_dir: Path,
) -> None:
    owner_file(runs_dir, "block-x1-1.json", BLOCK_X1)
    owner_file(runs_dir, "window.json", WINDOW)
    with pytest.raises(ck.RefusedError, match="smoke"):
        ck.owner("x1", 1, [], now=AFTER)
    smoked(runs_dir, (4, "2026-11-04T20:30:00Z"))
    with pytest.raises(ck.RefusedError, match="smoke"):
        ck.owner("x1", 1, [], now=AFTER)  # the last smoke did not pass
    smoked(runs_dir, (0, "2026-11-05T07:10:00Z"))
    with pytest.raises(ck.RefusedError, match="smoke"):
        ck.owner("x1", 1, [], now=AFTER)  # it ended after the confirmation
    smoked(runs_dir, (0, "2026-11-04T21:00:00Z"))
    smoke_line = {"kind": "smoke", "started_utc": "2026-11-04T20:00:00Z"}
    found = ck.owner("x1", 1, [smoke_line], now=AFTER)
    assert found["smoke"]["passed"] is True
    # A refused launch writes no ledger line, so the first block is never locked out by one.
    assert ck.owner("x1", 1, [smoke_line], now=AFTER)["first_block"] is True


def test_the_smoke_runs_before_the_window_s_confirmation_and_before_any_block(
    runs_dir: Path,
) -> None:
    (runs_dir / "owner" / "account.json").unlink()
    with pytest.raises(ck.RefusedError, match="account"):
        ck.smoke_ready("x1")
    owner_file(runs_dir, "account.json", ACCOUNT)
    with pytest.raises(ck.RefusedError, match="first block"):
        ck.smoke_ready("y1")
    got = ck.smoke_ready("x1")
    assert got["account_label"] == "the run account"
    assert got["weekly_reset_utc"] == "2026-10-29T07:00:00Z"
    owner_file(runs_dir, "window.json", WINDOW)
    with pytest.raises(ck.RefusedError, match="before the owner"):
        ck.smoke_ready("x1")
    (runs_dir / "owner" / "window.json").unlink()
    blocks(runs_dir, [att("x1", False)])
    with pytest.raises(ck.RefusedError, match="before the first block"):
        ck.smoke_ready("x1")


def test_the_false_finding_keys_on_records_not_at_their_digests_are_not_checked_not_refused(
    tmp_path: Path,
) -> None:
    for label in ("round-1", "repeat-K"):
        (tmp_path / label).mkdir()
    practice = {"round-1": tmp_path / "round-1", "repeat-K": tmp_path / "repeat-K"}
    got = holds(lambda: ck.ff_status(practice))
    assert got["status"] == "not checked" and "digest" in got["why"]


# ---- R and R_K -----------------------------------------------------------------------------------


def git(repo: Path, *args: str) -> str:
    return subprocess.run(
        ["git", "-C", str(repo), *args], capture_output=True, text=True, check=True
    ).stdout.strip()


@pytest.fixture(scope="module")
def r_k(tmp_path_factory: pytest.TempPathFactory) -> Any:  # noqa: ANN401
    base = tmp_path_factory.mktemp("rk")
    head = git(common.REPO, "rev-parse", "HEAD")
    made: list[Path] = []

    def make(
        name: str,
        extra: dict[str, str] | None = None,
        drop_promotion: int = 4,
        r_extra: dict[str, str] | None = None,
        k_commits: int = 1,
    ) -> tuple[Path, Path, str, str]:
        r = base / f"{name}-r"
        k = base / f"{name}-k"
        for d in (r, k):
            git(common.REPO, "worktree", "add", "-q", "--detach", str(d), head)
            made.append(d)
        if r_extra:
            for rel, text in r_extra.items():
                (r / rel).write_text(text)
            git(r, "add", "-A")  # a new file of R' (a correction's test) too
            git(r, "-c", "user.email=t@example.invalid", "-c", "user.name=t", "commit", "-qm", "R")
            git(k, "checkout", "-q", "--detach", git(r, "rev-parse", "HEAD"))
        for role in common.ROLES:
            blob = subprocess.run(
                [
                    "git",
                    "-C",
                    str(k),
                    "show",
                    f"{common.K_COMMIT}:knowledge/reviewers/{role}/rubric.md",
                ],
                capture_output=True,
                check=True,
            ).stdout
            (k / "knowledge" / "reviewers" / role / "rubric.md").write_bytes(blob)
        added = [
            x[1:]
            for x in git(
                k, "show", "--format=", "-U0", common.FIX_COMMIT, "--", common.PROMOTIONS
            ).splitlines()
            if x.startswith("+") and not x.startswith("+++")
        ]
        lines = (k / common.PROMOTIONS).read_text().splitlines()
        kept = [x for x in lines if x not in added[:drop_promotion]]
        (k / common.PROMOTIONS).write_text("\n".join(kept) + "\n")
        for rel, text in (extra or {}).items():
            (k / rel).write_text(text)
        git(
            k,
            "-c",
            "user.email=t@example.invalid",
            "-c",
            "user.name=t",
            "commit",
            "-q",
            "-am",
            "K's rubrics",
        )
        for n in range(1, k_commits):  # R_K more than one commit above R
            ident = ("-c", "user.email=t@example.invalid", "-c", "user.name=t")
            git(k, *ident, "commit", "-q", "--allow-empty", "-m", f"one more {n}")
        return r, k, git(r, "rev-parse", "HEAD"), git(k, "rev-parse", "HEAD")

    yield make
    for d in made:
        subprocess.run(
            ["git", "-C", str(common.REPO), "worktree", "remove", "--force", str(d)], check=False
        )


def test_r_and_r_k_hold_section_3_2(r_k: Any) -> None:  # noqa: ANN401
    r, k, rs, ks = r_k("ok")
    found = ck.commits(r, k, {"commits": {"R": rs, "R_K": ks}}, master_ref=rs)
    assert found["the paths R_K differs from R in"] == sorted(common.R_K_PATHS)


def test_r_k_with_a_sixth_path_is_refused(r_k: Any) -> None:  # noqa: ANN401
    r, k, rs, ks = r_k("six", extra={"README.md": "changed\n"})
    with pytest.raises(ck.RefusedError, match="paths R_K differs"):
        ck.commits(r, k, {"commits": {"R": rs, "R_K": ks}}, master_ref=rs)


def test_r_k_s_promotions_are_compared_by_content_line_for_line(r_k: Any) -> None:  # noqa: ANN401
    r, k, rs, ks = r_k("three", drop_promotion=3)
    with pytest.raises(ck.RefusedError, match="promotions"):
        ck.commits(r, k, {"commits": {"R": rs, "R_K": ks}}, master_ref=rs)


def test_commits_filled_must_be_on_record_and_be_the_checkouts(r_k: Any) -> None:  # noqa: ANN401
    r, k, rs, ks = r_k("fills")
    with pytest.raises(common.RefusedError, match="Commits filled"):
        ck.commits(r, k, {}, master_ref=rs)
    with pytest.raises(ck.RefusedError, match="R is"):
        ck.commits(r, k, {"commits": {"R": "0" * 40, "R_K": ks}}, master_ref=rs)
    with pytest.raises(ck.RefusedError, match="tree"):
        ck.commits(
            r,
            k,
            {"commits": {"R": rs, "R_K": ks, "trees": {"src/physgate/gate": "0" * 40}}},
            master_ref=rs,
        )


CRITERIA = f"{common.EXPERIMENT}/CRITERIA.md"
README = f"{common.EXPERIMENT}/README.md"


@pytest.mark.parametrize("path", [CRITERIA, README])
def test_r_k_holding_a_frozen_file_other_than_the_freeze_s_is_refused(
    r_k: Any,  # noqa: ANN401
    path: str,
) -> None:
    r, k, rs, ks = r_k(f"k-{Path(path).stem}", extra={path: "changed\n"})
    with pytest.raises(ck.RefusedError, match=f"R_K's {re.escape(path)}"):
        ck.commits(r, k, {"commits": {"R": rs, "R_K": ks}}, master_ref=rs)


def test_r_holding_a_frozen_file_other_than_the_freeze_s_is_refused(r_k: Any) -> None:  # noqa: ANN401
    r, k, rs, ks = r_k("r-readme", r_extra={README: "changed\n"})
    with pytest.raises(ck.RefusedError, match=f"R's {re.escape(README)}"):
        ck.commits(r, k, {"commits": {"R": rs, "R_K": ks}}, master_ref=rs)


def test_the_master_ref_holding_no_frozen_criteria_is_refused(r_k: Any) -> None:  # noqa: ANN401
    r, k, rs, ks = r_k("master")
    # fc28f32 is older than the freeze: CRITERIA.md is not there.
    with pytest.raises(ck.RefusedError, match=f"the master ref's {re.escape(CRITERIA)}"):
        ck.commits(r, k, {"commits": {"R": rs, "R_K": ks}}, master_ref=common.R_FLOOR)
    found = ck.commits(r, k, {"commits": {"R": rs, "R_K": ks}}, master_ref=rs)
    assert found[f"the master ref's {CRITERIA}"] == common.FROZEN_BLOBS[CRITERIA]


def test_r_k_more_than_one_commit_above_r_is_refused(r_k: Any) -> None:  # noqa: ANN401
    r, k, rs, ks = r_k("two-above", k_commits=2)
    with pytest.raises(ck.RefusedError, match="R_K's parent"):
        ck.commits(r, k, {"commits": {"R": rs, "R_K": ks}}, master_ref=rs)


def test_a1_s_four_rubric_digests_are_held(r_k: Any, monkeypatch: pytest.MonkeyPatch) -> None:  # noqa: ANN401
    r, k, rs, ks = r_k("a1-pins")
    monkeypatch.setitem(common.RUBRIC_SHA256["A1"], "firmware", "0" * 64)
    with pytest.raises(ck.RefusedError, match="A1 firmware rubric"):
        ck.commits(r, k, {"commits": {"R": rs, "R_K": ks}}, master_ref=rs)


@pytest.mark.parametrize("path", sorted(common.KNOWLEDGE_TREES))
def test_the_five_knowledge_trees_are_held_in_r_and_r_k(
    r_k: Any,
    monkeypatch: pytest.MonkeyPatch,
    path: str,  # noqa: ANN401
) -> None:
    r, k, rs, ks = r_k(f"trees-{Path(path).name}")
    monkeypatch.setitem(common.KNOWLEDGE_TREES, path, "0" * 40)
    with pytest.raises(ck.RefusedError, match=f"R {re.escape(path)}"):
        ck.commits(r, k, {"commits": {"R": rs, "R_K": ks}}, master_ref=rs)


def test_the_account_s_paragraphs_are_held_to_their_digest_before_the_run(
    r_k: Any,  # noqa: ANN401
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    r, k, rs, ks = r_k("account")
    assert (
        ck.commits(r, k, {"commits": {"R": rs, "R_K": ks}}, master_ref=rs)["R's account paragraphs"]
        == common.ACCOUNT_SHA256
    )
    # generalist() runs whole in R_K's checkout alone (K's digests); its account check comes first.
    monkeypatch.setattr(common, "ACCOUNT_SHA256", "0" * 64)
    with pytest.raises(ck.RefusedError, match="account paragraphs"):
        ck.commits(r, k, {"commits": {"R": rs, "R_K": ks}}, master_ref=rs)
    with pytest.raises(ck.RefusedError, match="account paragraphs"):
        ck.generalist()


def fills_repo(tmp: Path, steps: list[tuple[str, dict[str, Any], dict[str, str] | None]]) -> Path:
    """A repository whose fills record is written by ``steps``: (subject, record, other files)."""
    repo = tmp / "repo"
    repo.mkdir()
    ident = ("-c", "user.email=t@example.invalid", "-c", "user.name=t")
    git(repo, "init", "-q")
    (repo / "README.md").write_text("x\n")
    git(repo, "add", "-A")
    git(repo, *ident, "commit", "-qm", "the start")
    where = repo / common.EXPERIMENT / common.FILLS_NAME
    where.parent.mkdir(parents=True)
    for subject, record, others in steps:
        where.write_text(json.dumps(record, indent=1) + "\n")
        for rel, text in (others or {}).items():
            (repo / rel).write_text(text)
        git(repo, "add", "-A")
        git(repo, *ident, "commit", "-qm", subject)
    return repo


COMMITS = {"R": "a" * 40, "R_K": "b" * 40}
SHEET = {"sha256": "c" * 64}
SETS = {"manifests": {"fresh-v2-x1": "d" * 64}}


#: A tracked test that depends on no verdict, as a correction names one per block it touches.
TEST = "experiments/R-PG-03/test_checks.py"
ONE: dict[str, Any] = {"attempt": 1, "test": TEST}
C1: dict[str, Any] = {"id": "c1", "R": "f" * 40, "R_K": "e" * 40, "blocks": {"x1": ONE}}
C2: dict[str, Any] = {**C1, "id": "c2", "blocks": {"y1": ONE, "z1": ONE}}
ALL = {"commits": COMMITS, "sheet": SHEET, "sets": SETS}
FILLED: list[tuple[str, dict[str, Any], dict[str, str] | None]] = [
    ("docs(r-pg-03): Commits filled", {"commits": COMMITS}, None),
    ("docs(r-pg-03): Sheet filled", {"commits": COMMITS, "sheet": SHEET}, None),
    ("docs(r-pg-03): Set filled", ALL, None),
]


def test_a_correction_after_set_filled_is_read(tmp_path: Path) -> None:
    steps = [
        *FILLED,
        ("docs(r-pg-03): Commits corrected, block x1", {**ALL, "corrections": [C1]}, None),
        (
            "docs(r-pg-03): Commits corrected, blocks y1 and z1",
            {**ALL, "corrections": [C1, C2]},
            None,
        ),
    ]
    assert common.fills_on(fills_repo(tmp_path, steps), "HEAD")["corrections"] == [C1, C2]


@pytest.mark.parametrize(
    ("steps", "why"),
    [
        (
            [
                *FILLED[:2],
                (
                    "docs: Commits corrected, block x1",
                    {"commits": COMMITS, "sheet": SHEET, "corrections": [C1]},
                    None,
                ),
            ],
            "after",
        ),
        ([*FILLED, ("docs: Commits corrected", {**ALL, "corrections": [C1]}, None)], "names"),
        ([*FILLED, ("docs: block x1 fixed", {**ALL, "corrections": [C1]}, None)], "names"),
        (
            [
                *FILLED,
                (
                    "docs: Commits corrected, block x1",
                    {**ALL, "commits": {**COMMITS, "R": "f" * 40}, "corrections": [C1]},
                    None,
                ),
            ],
            "changes",
        ),
        (
            [
                *FILLED,
                ("docs: Commits corrected, block x1", {**ALL, "corrections": [C1, C2]}, None),
            ],
            "adds",
        ),
        (
            [
                *FILLED,
                ("docs: Commits corrected, block x1", {**ALL, "corrections": [C1]}, None),
                (
                    "docs: Commits corrected, blocks y1 and z1",
                    {**ALL, "corrections": [{**C1, "R": "d" * 40}, C2]},
                    None,
                ),
            ],
            "changes",
        ),
        (
            [*FILLED, ("docs: Commits corrected, block y1", {**ALL, "corrections": [C2]}, None)],
            "every block it touches",
        ),
        (
            [
                *FILLED,
                ("docs: Commits corrected, block x1", {**ALL, "corrections": [C1]}, None),
                (
                    "docs: Commits corrected, blocks y1 and z1",
                    {**ALL, "corrections": [C1, {**C2, "id": "c1"}]},
                    None,
                ),
            ],
            "an id an earlier correction",
        ),
        (
            [
                *FILLED,
                (
                    "docs: Commits corrected, block x1",
                    {**ALL, "corrections": [{**C1, "blocks": {}}]},
                    None,
                ),
            ],
            "the blocks it touches",
        ),
        (
            [
                *FILLED,
                (
                    "docs: Commits corrected, block x1",
                    {**ALL, "corrections": [{**C1, "blocks": {"x1": {**ONE, "test": "a.py"}}}]},
                    None,
                ),
            ],
            "the blocks it touches",
        ),
        (
            [
                *FILLED,
                (
                    "docs: Commits corrected, block x1",
                    {**ALL, "corrections": [{**C1, "blocks": {"x1": TEST}}]},
                    None,
                ),
            ],
            "each with its attempt",
        ),
        (
            [
                *FILLED,
                (
                    "docs: Commits corrected, block x1",
                    {**ALL, "corrections": [{**C1, "blocks": {"x1": {**ONE, "attempt": 0}}}]},
                    None,
                ),
            ],
            "each with its attempt",
        ),
        (
            [
                *FILLED,
                (
                    "docs: Commits corrected, block x1",
                    {**ALL, "corrections": [{**C1, "by": 1}]},
                    None,
                ),
            ],
            "each with its attempt",
        ),
        (
            # Block s, whose name is a letter of "Commits": a word of the subject, not a substring.
            [
                *FILLED,
                (
                    "docs: Commits corrected, block x1",
                    {**ALL, "corrections": [{**C1, "blocks": {"x1": ONE, "s": ONE}}]},
                    None,
                ),
            ],
            "every block it touches",
        ),
        (
            [
                *FILLED,
                (
                    "docs: Withdrawn c9",
                    {**ALL, "withdrawn": [{"correction": "c9", "why": "x"}]},
                    None,
                ),
            ],
            "a withdrawal names a correction on record",
        ),
        (
            [
                *FILLED,
                ("docs: Commits corrected, block x1", {**ALL, "corrections": [C1]}, None),
                (
                    "docs: c1 out",
                    {**ALL, "corrections": [C1], "withdrawn": [{"correction": "c1", "why": "x"}]},
                    None,
                ),
            ],
            "names no 'Withdrawn'",
        ),
        (
            [
                *FILLED,
                (
                    "docs: Commits corrected, block x1",
                    {**ALL, "corrections": [{**C1, "R": "not a sha"}]},
                    None,
                ),
            ],
            "entry",
        ),
        (
            [
                *FILLED,
                (
                    "docs: Commits corrected, block x1",
                    {**ALL, "corrections": [C1]},
                    {"README.md": "y\n"},
                ),
            ],
            "touches",
        ),
    ],
    ids=[
        "before-set-filled",
        "a-subject-naming-no-block",
        "a-subject-naming-no-correction",
        "commits-filled-changed",
        "two-corrections-at-once",
        "an-earlier-correction-changed",
        "a-subject-naming-not-every-block",
        "an-id-used-twice",
        "an-entry-touching-no-block",
        "an-entry-whose-test-is-no-test",
        "an-entry-whose-block-names-no-attempt",
        "an-entry-whose-attempt-is-not-one-or-more",
        "an-entry-with-a-key-of-its-own",
        "a-subject-naming-block-s-only-inside-a-word",
        "a-withdrawal-of-no-correction-on-record",
        "a-withdrawal-whose-subject-names-no-withdrawn",
        "a-malformed-entry",
        "another-path-touched",
    ],
)
def test_a_correction_s_history_is_held(
    tmp_path: Path, steps: list[tuple[str, dict[str, Any], dict[str, str] | None]], why: str
) -> None:
    with pytest.raises(common.RefusedError, match=why):
        common.fills_on(fills_repo(tmp_path, steps), "HEAD")


def test_the_fills_record_is_read_when_each_fill_came_in_its_own_named_commit(
    tmp_path: Path,
) -> None:
    repo = fills_repo(
        tmp_path,
        [
            ("docs(r-pg-03): Commits filled", {"commits": COMMITS}, None),
            ("docs(r-pg-03): Sheet filled", {"commits": COMMITS, "sheet": SHEET}, None),
            ("docs(r-pg-03): Set filled", {"commits": COMMITS, "sheet": SHEET, "sets": SETS}, None),
        ],
    )
    assert common.fills_on(repo, "HEAD") == {"commits": COMMITS, "sheet": SHEET, "sets": SETS}


@pytest.mark.parametrize(
    ("steps", "why"),
    [
        ([("docs(r-pg-03): Commits filled", {"commits": COMMITS, "sheet": SHEET}, None)], "one"),
        (
            [("docs(r-pg-03): Commits filled", {"commits": COMMITS}, {"README.md": "y\n"})],
            "touches",
        ),
        ([("docs(r-pg-03): the commits", {"commits": COMMITS}, None)], "names"),
        ([("docs(r-pg-03): Sheet filled", {"sheet": SHEET}, None)], "order"),
        (
            [
                ("docs(r-pg-03): Commits filled", {"commits": COMMITS}, None),
                (
                    "docs(r-pg-03): Sheet filled",
                    {"commits": {**COMMITS, "R": "e" * 40}, "sheet": SHEET},
                    None,
                ),
            ],
            "changes",
        ),
    ],
    ids=[
        "two-fills-at-once",
        "another-path-touched",
        "a-subject-naming-no-fill",
        "out-of-order",
        "an-earlier-fill-changed",
    ],
)
def test_the_fills_record_s_history_is_held(
    tmp_path: Path, steps: list[tuple[str, dict[str, Any], dict[str, str] | None]], why: str
) -> None:
    repo = fills_repo(tmp_path, steps)
    with pytest.raises(common.RefusedError, match=why):
        common.fills_on(repo, "HEAD")


# ---- README: the freeze's bytes and one appended section -------------------------------------


FROZEN_README = subprocess.run(
    ["git", "-C", str(common.REPO), "cat-file", "blob", common.FROZEN_BLOBS[README]],
    capture_output=True,
    text=True,
    check=True,
).stdout
SECTION = "\n## Readings disclosed\n\nOne reading.\n"


def test_the_readme_holds_the_freeze_s_bytes_and_one_appended_section(r_k: Any) -> None:  # noqa: ANN401
    r, k, rs, ks = r_k("readme-held", r_extra={README: FROZEN_README + SECTION})
    found = ck.commits(r, k, {"commits": {"R": rs, "R_K": ks}}, master_ref=rs)
    assert found[f"R's {README}"] == "the freeze's bytes and one appended section"


@pytest.mark.parametrize(
    ("text", "why"),
    [
        # The same length, so the frozen part's own check is the one that refuses.
        (FROZEN_README.replace("Three arms", "Three ARMS") + SECTION, "frozen part is not"),
        (FROZEN_README + SECTION + "\n## More\n\nx\n", "one appended section"),
        (FROZEN_README, "one appended section"),
        (FROZEN_README + "\n## Something else\n", "one appended section"),
        (FROZEN_README + SECTION + "\n# A title\n", "more than the one appended section"),
    ],
    ids=[
        "an-edit-inside-the-frozen-part",
        "a-second-section",
        "no-section",
        "another-section",
        "a-top-level-heading-after-it",
    ],
)
def test_a_readme_other_than_the_freeze_s_bytes_and_its_one_section_is_refused(
    r_k: Any,
    text: str,
    why: str,  # noqa: ANN401
) -> None:
    r, k, rs, ks = r_k(f"readme-{why[:5]}-{len(text)}", r_extra={README: text})
    with pytest.raises(ck.RefusedError, match=why):
        ck.commits(r, k, {"commits": {"R": rs, "R_K": ks}}, master_ref=rs)


def test_a_master_readme_other_than_r_s_is_refused(r_k: Any) -> None:  # noqa: ANN401
    r, k, rs, ks = r_k("readme-master", r_extra={README: FROZEN_README + SECTION})
    other = git(common.REPO, "rev-parse", "HEAD")  # its README is not R's
    with pytest.raises(ck.RefusedError, match="the master ref's .*README.md is not R's"):
        ck.commits(r, k, {"commits": {"R": rs, "R_K": ks}}, master_ref=other)


# ---- §11's corrected commit -------------------------------------------------------------------


def touched(
    runs: Path,
    block: str = "x1",
    valid: bool = False,
    route: str = "instrument defect",
    correction: str = "c1",
) -> dict[str, Any]:
    """Block ``block``'s first attempt, classified on ``route``, its classification beside it.

    A deviation (``valid`` false), or a valid attempt a correction touches. An instrument defect
    names its correction's id and the test the correction names for the block.
    """
    launch = runs / "blocks" / f"{block}-1"
    launch.mkdir(parents=True)
    row: dict[str, Any] = {**att(block, valid), "launch": str(launch), "void_causes": []}
    said: dict[str, Any] = {"block": block, "attempt": 1, "route": route}
    if not valid:
        row["deviation"] = {"causes": ["a crashed or killed process"]}
    row["classified"] = {"route": route, "recorded_utc": "2026-11-06T00:00:00Z"}
    if route == "instrument defect":
        row["classified"]["correction"] = correction
        said.update(correction=correction, test=TEST)
    (launch / "classification.json").write_text(json.dumps(said))
    return row


def classified(runs: Path, route: str = "instrument defect", block: str = "x1") -> Path:
    """Block ``block``'s first attempt, a deviation classified on ``route``; its classification."""
    row = touched(runs, block, route=route)
    blocks(runs, [row])
    return Path(row["launch"]) / "classification.json"


def correction(r: str, r_k: str, *touches: str, cid: str = "c1") -> dict[str, Any]:
    """A correction's entry: its id, R' and R_K', each block it touches with attempt and test."""
    return {"id": cid, "R": r, "R_K": r_k, "blocks": {b: ONE for b in touches or ("x1",)}}


def corrected_pair(
    r_k: Any,  # noqa: ANN401
    name: str,
    k_commits: int = 1,
    extra: dict[str, str] | None = None,
) -> tuple[Path, Path, str, str, str]:
    """R (the head), and R' one commit above it with R_K' above R'."""
    head = git(common.REPO, "rev-parse", "HEAD")
    gitignore = (common.REPO / ".gitignore").read_text()
    r, k, rs, ks = r_k(
        name,
        r_extra={".gitignore": gitignore + "# a correction\n", **(extra or {})},
        k_commits=k_commits,
    )
    return r, k, rs, ks, head


def checked(runs: Path, *entries: Any) -> None:  # noqa: ANN401
    """Each entry's passing correction-check record, as correction-check keeps it."""
    for entry in entries:
        out = runs / "corrections" / entry["id"]
        out.mkdir(parents=True, exist_ok=True)
        said = {"passed": True, "entry": entry, "checked_utc": "2026-11-06T00:00:00Z"}
        (out / "check.json").write_text(json.dumps(said))


#: A correction's test, as the owner would write one, in both its modes: on its own fixtures it
#: fails until the fix (here, a marker R' adds); on a block's records (RP3_BLOCK_RECORDS) it fails
#: exactly when the defect shows in them (here, a file the fixture's attempt holds).
PROBE = "experiments/R-PG-03/test_correction_probe.py"
PROBE_TEXT = """import os
from pathlib import Path


def test_the_defect_does_not_show() -> None:
    records = os.environ.get("RP3_BLOCK_RECORDS")
    if records:
        assert not (Path(records) / "defect.txt").exists()
    else:
        import physgate  # the checkout's own code, never the running one's

        here = Path(__file__).resolve().parents[2]
        assert Path(physgate.__file__).resolve().is_relative_to(here)
        assert (Path(__file__).parent / "fixed.txt").exists()
"""
FIXED = {PROBE: PROBE_TEXT, "experiments/R-PG-03/fixed.txt": "fixed\n"}


def test_a_block_whose_deviation_is_an_instrument_defect_runs_at_its_corrected_commit(
    r_k: Any,
    runs_dir: Path,  # noqa: ANN401
) -> None:
    r, k, rs, ks, head = corrected_pair(r_k, "corrected")
    classified(runs_dir)
    fills: dict[str, Any] = {
        "commits": {"R": head, "R_K": "0" * 40},
        "corrections": [correction(rs, ks)],
    }
    # "Commits filled"'s trees describe R: they are not held at the corrected R'.
    fills["commits"]["trees"] = {"src/physgate/gate": "0" * 40}
    checked(runs_dir, *fills["corrections"])
    found = holds(lambda: ck.commits(r, k, fills, master_ref=rs, block="x1"))
    assert found["corrected"] == correction(rs, ks)
    # Every other block stays at R, the commit "Commits filled" records.
    with pytest.raises(ck.RefusedError, match="R is"):
        ck.commits(r, k, fills, master_ref=rs, block="y1")


def test_every_block_a_correction_names_runs_at_its_corrected_commit_a_valid_one_too(
    r_k: Any,
    runs_dir: Path,  # noqa: ANN401
) -> None:
    r, k, rs, ks, head = corrected_pair(r_k, "touched")
    rows = [touched(runs_dir, "x1", valid=True), touched(runs_dir, "y1", valid=True)]
    blocks(runs_dir, [*rows, att("z1", True)])
    fills = {
        "commits": {"R": head, "R_K": "0" * 40},
        "corrections": [correction(rs, ks, "x1", "y1")],
    }
    checked(runs_dir, *fills["corrections"])
    for block in ("x1", "y1"):
        assert ck.commits(r, k, fills, master_ref=rs, block=block)["corrected"]["id"] == "c1"
    # No other block: z1, which the correction does not name, stays at R.
    with pytest.raises(ck.RefusedError, match="R is"):
        ck.commits(r, k, fills, master_ref=rs, block="z1")


NAMED_NOT_CLASSIFIED = (
    r"named by the corrections \['c1'\], and its attempts are classified with \[\]"
)
CLASSIFIED_NOT_NAMED = (
    r"named by the corrections \[\], and its attempts are classified with \['c1'\]"
)


def test_a_correction_that_names_a_block_without_its_classification_is_refused(
    runs_dir: Path, tmp_path: Path
) -> None:
    classified(runs_dir, route="anything else impossible as specified")
    fills = {"commits": {"R": "a" * 40, "R_K": "b" * 40}, "corrections": [C1]}

    def l2() -> object:
        return ck.commits(tmp_path, tmp_path, fills, master_ref="HEAD", block="x1")

    fx.refuses(common.RefusedError, NAMED_NOT_CLASSIFIED, l2)
    # The refusal names the remedy: the check before the commit, then the classification.
    fx.refuses(
        common.RefusedError, r"Its exit: checks.py classify --correction <id>.*withdrawal", l2
    )
    # A valid attempt the correction names is refused alike until it is classified with it.
    blocks(runs_dir, [att("x1", True)])
    fx.refuses(common.RefusedError, NAMED_NOT_CLASSIFIED, l2)


def test_an_instrument_defect_whose_correction_does_not_name_the_block_is_refused(
    runs_dir: Path, tmp_path: Path
) -> None:
    classified(runs_dir)
    fills: dict[str, Any] = {"commits": {"R": "a" * 40, "R_K": "b" * 40}}

    def l2() -> object:
        return ck.commits(tmp_path, tmp_path, fills, master_ref="HEAD", block="x1")

    fx.refuses(common.RefusedError, CLASSIFIED_NOT_NAMED, l2)
    fills["corrections"] = [{**C1, "blocks": {"y1": ONE}}]
    fx.refuses(common.RefusedError, CLASSIFIED_NOT_NAMED, l2)


def test_a_correction_that_names_r_itself_is_refused(r_k: Any, runs_dir: Path) -> None:  # noqa: ANN401
    r, k, rs, ks = r_k("r-itself")
    classified(runs_dir)
    fills = {"commits": {"R": rs, "R_K": ks}, "corrections": [correction(rs, ks)]}
    checked(runs_dir, *fills["corrections"])
    with pytest.raises(ck.RefusedError, match="R itself"):
        ck.commits(r, k, fills, master_ref=rs, block="x1")


def test_a_corrected_commit_that_does_not_descend_from_r_is_refused(
    r_k: Any,
    runs_dir: Path,  # noqa: ANN401
) -> None:
    r, k, rs, ks = r_k("not-down")
    classified(runs_dir)
    fills = {"commits": {"R": rs, "R_K": ks}, "corrections": [correction(common.R_FLOOR, ks)]}
    checked(runs_dir, *fills["corrections"])
    with pytest.raises(ck.RefusedError, match="descend"):
        ck.commits(r, k, fills, master_ref=rs, block="x1")


def test_a_corrected_r_k_more_than_one_commit_above_r_prime_is_refused(
    r_k: Any,
    runs_dir: Path,  # noqa: ANN401
) -> None:
    r, k, rs, ks, head = corrected_pair(r_k, "corr-two", k_commits=2)
    classified(runs_dir)
    fills = {"commits": {"R": head, "R_K": "0" * 40}, "corrections": [correction(rs, ks)]}
    checked(runs_dir, *fills["corrections"])
    with pytest.raises(ck.RefusedError, match="R_K's parent"):
        ck.commits(r, k, fills, master_ref=rs, block="x1")


@pytest.mark.parametrize(
    ("key", "value"),
    [
        ("correction", "c2"),
        ("test", "experiments/R-PG-03/test_launch.py"),
        ("route", "something else"),
        ("block", "y1"),
        ("attempt", 2),
        ("entry", 2),
        (None, None),
    ],
    ids=[
        "another-correction",
        "another-test",
        "not-a-defect",
        "another-block",
        "another-attempt",
        "the-entry-s-another-attempt",
        "none-written",
    ],
)
def test_a_classification_other_than_the_correction_s_for_the_block_is_refused(
    runs_dir: Path, tmp_path: Path, key: str | None, value: str | int | None
) -> None:
    path = classified(runs_dir)
    fills = {"commits": {"R": "a" * 40, "R_K": "b" * 40}, "corrections": [C1]}
    if key is None:
        path.unlink()
    elif key == "entry":  # the classification and the attempt agree; the entry names another
        fills["corrections"] = [{**C1, "blocks": {"x1": {**ONE, "attempt": value}}}]
    else:
        path.write_text(json.dumps({**json.loads(path.read_text()), key: value}))
    with pytest.raises(ck.RefusedError, match="classification next to block x1's attempt 1"):
        ck.commits(tmp_path, tmp_path, fills, master_ref="HEAD", block="x1")


def test_a_block_a_correction_touches_runs_again_until_its_corrected_attempt_is_valid(
    runs_dir: Path,
) -> None:
    first = touched(runs_dir, "y1", valid=True)
    blocks(runs_dir, [att("x1", True), first])
    assert holds(lambda: ck.order("y1", now=AFTER))["attempt"] == 2
    # No other block: x1's valid attempt is no correction's.
    with pytest.raises(ck.RefusedError, match="block x1 already has a valid attempt$"):
        ck.order("x1", now=AFTER)
    # A void corrected attempt is re-attempted whole, as any void is (§11).
    void = {**att("y1", False), "attempt": 2, "void_causes": ["usage limit"]}
    blocks(runs_dir, [att("x1", True), first, void])
    assert holds(lambda: ck.order("y1", now=AFTER))["attempt"] == 3
    # Once one is valid, the block is not run again.
    blocks(runs_dir, [att("x1", True), first, void, {**att("y1", True), "attempt": 3}])
    with pytest.raises(ck.RefusedError, match="y1 already has a valid attempt at its corrected"):
        ck.order("y1", now=AFTER)


def test_the_blocks_after_a_touched_one_wait_for_its_corrected_attempt(runs_dir: Path) -> None:
    first = touched(runs_dir, "y1", valid=True)
    blocks(runs_dir, [att("x1", True), first])
    with pytest.raises(ck.RefusedError, match="block y1 comes first"):
        ck.order("z1", now=AFTER)
    blocks(runs_dir, [att("x1", True), first, {**att("y1", True), "attempt": 2}])
    assert ck.order("z1", now=AFTER)["attempt"] == 1


def test_the_owner_classifies_a_valid_attempt_a_correction_touches_with_its_id(
    runs_dir: Path,
) -> None:
    launch = runs_dir / "blocks" / "x1-1"
    launch.mkdir(parents=True)
    row = {**att("x1", True), "launch": str(launch), "void_causes": [], "deviation": None}
    void = {**att("y1", False), "void_causes": ["usage limit"], "deviation": None}
    blocks(runs_dir, [row, void])
    # The corrections on the master ref: c1 and c2 name x1's attempt 1, c3 names y1's.
    fills = {"corrections": [C1, {**C1, "id": "c2"}, {**C1, "id": "c3", "blocks": {"y1": ONE}}]}
    other = "experiments/R-PG-03/test_launch.py"
    bad: list[tuple[str, str | None, str | None, str]] = [
        ("anything else impossible as specified", None, None, "no deviation"),
        ("instrument defect", TEST, None, "names the correction"),
        ("anything else impossible as specified", None, "c1", "for an instrument defect alone"),
        # A correction is committed first: an id the master ref does not hold for this attempt
        # and test is refused, so a typo can never lock the block.
        ("instrument defect", TEST, "c1-typo", "no correction c1-typo on the master ref"),
        ("instrument defect", other, "c1", "no correction c1 on the master ref"),
    ]
    for route, test, cid, why in bad:
        with pytest.raises(ck.RefusedError, match=why):
            ck.classify("x1", 1, route, test, cid, fills)
    with pytest.raises(ck.RefusedError, match="no correction c1 on the master ref"):
        ck.classify("x1", 1, "instrument defect", TEST, "c1", None)
    # A void attempt is re-attempted whole, never classified.
    with pytest.raises(ck.RefusedError, match="no deviation"):
        ck.classify("y1", 1, "instrument defect", TEST, "c3", fills)
    got = ck.classify("x1", 1, "instrument defect", TEST, "c1", fills)
    said = json.loads((launch / "classification.json").read_text())
    assert (said["route"], said["correction"], said["test"]) == ("instrument defect", "c1", TEST)
    assert said == got and ck.read_blocks()["attempts"][0]["classified"]["correction"] == "c1"
    with pytest.raises(ck.RefusedError, match="classified already"):
        ck.classify("x1", 1, "instrument defect", TEST, "c2", fills)
    # The block record holds the classification too, its file gone.
    (launch / "classification.json").unlink()
    with pytest.raises(ck.RefusedError, match="classified already"):
        ck.classify("x1", 1, "instrument defect", TEST, "c2", fills)


def test_a_correction_s_id_classifies_the_one_attempt_of_a_block_it_names(runs_dir: Path) -> None:
    first = touched(runs_dir, "x1")
    launch = runs_dir / "blocks" / "x1-2"
    launch.mkdir(parents=True)
    pending = {
        "causes": ["a crashed or killed process"],
    }
    second = {**att("x1", False), "attempt": 2, "launch": str(launch), "deviation": pending}
    blocks(runs_dir, [first, second])
    c2 = {**C1, "id": "c2", "blocks": {"x1": {**ONE, "attempt": 2}}}
    with pytest.raises(ck.RefusedError, match="no correction c1 on the master ref"):
        ck.classify("x1", 2, "instrument defect", TEST, "c1", {"corrections": [C1, c2]})
    got = ck.classify("x1", 2, "instrument defect", TEST, "c2", {"corrections": [C1, c2]})
    assert got["correction"] == "c2"


def test_l2_needs_the_correction_s_passing_check_record_and_names_the_remedy(
    runs_dir: Path, tmp_path: Path
) -> None:
    classified(runs_dir)
    fills = {"commits": {"R": "a" * 40, "R_K": "b" * 40}, "corrections": [C1]}

    def l2() -> object:
        return ck.commits(tmp_path, tmp_path, fills, master_ref="HEAD", block="x1")

    fx.refuses(
        common.RefusedError, "no passing correction-check record.*correction-check --entry", l2
    )
    checked(runs_dir, {**C1, "R_K": "d" * 40})  # a record of another entry under that id
    fx.refuses(common.RefusedError, "no passing correction-check record", l2)


def entry_file(tmp: Path, entry: dict[str, Any]) -> Path:
    path = tmp / "entry.json"
    path.write_text(json.dumps(entry))
    return path


def defect_attempts(runs: Path) -> list[dict[str, Any]]:
    """x1's valid attempt and y1's unclassified deviation, each whose records show the defect."""
    rows = []
    for block, valid in (("x1", True), ("y1", False)):
        launch = runs / "blocks" / f"{block}-1"
        launch.mkdir(parents=True)
        (launch / "defect.txt").write_text("shown\n")
        row = {**att(block, valid), "launch": str(launch), "void_causes": []}
        if not valid:
            row["deviation"] = {
                "causes": ["a run that is not whole"],
            }
        rows.append(row)
    blocks(runs, rows)
    return rows


def test_a_correction_is_checked_before_its_commit_and_its_record_kept(
    r_k: Any,  # noqa: ANN401
    runs_dir: Path,
    tmp_path: Path,
) -> None:
    r, k, rs, ks, head = corrected_pair(r_k, "checked", extra=FIXED)
    defect_attempts(runs_dir)
    test = {"attempt": 1, "test": PROBE}
    entry = {"id": "c1", "R": rs, "R_K": ks, "blocks": {"x1": test, "y1": test}}
    fills: dict[str, Any] = {"commits": {"R": head, "R_K": "0" * 40}}
    got = holds(lambda: ck.correction_check(entry_file(tmp_path, entry), r, k, fills, rs))
    # It fails at R and passes at R' on its fixtures, and fails on each named attempt's records.
    assert got["tests"] == {PROBE: {"R": "fails", "R'": "passes", "x1": "fails", "y1": "fails"}}
    record = json.loads((runs_dir / "corrections" / "c1" / "check.json").read_text())
    assert record["passed"] is True and record["entry"] == entry
    listed = json.loads((runs_dir / "corrections" / "c1" / "code_changes.json").read_text())
    assert (listed["R"], listed["R_K"]) == (rs, ks)
    assert [g["from"] for g in listed["ranges"]] == [head, rs]  # R to R', then R' to R_K'
    # Its tests on a later block's records, from the R' checkout: touched or not.
    fills["corrections"] = [entry]
    clean, shown = runs_dir / "blocks" / "z1-1", runs_dir / "blocks" / "z2-1"
    clean.mkdir()
    shown.mkdir()
    (shown / "defect.txt").write_text("shown\n")
    blocks(
        runs_dir,
        [
            {**att("z1", True), "launch": str(clean)},
            {**att("z2", True), "launch": str(shown)},
            {**att("y2", None), "launch": str(clean)},
        ],
    )
    got = holds(lambda: ck.touched("z1", 1, r, fills))
    assert got["corrections"]["c1"]["tests"] == {PROBE: "passes"}
    assert holds(lambda: ck.touched("z2", 1, r, fills))["corrections"]["c1"]["tests"] == {
        PROBE: "fails"
    }
    saved = json.loads((shown / "touched.json").read_text())
    assert saved["c1"]["tests"] == {PROBE: "fails"}
    fx.refuses(ck.RefusedError, "has not closed", lambda: ck.touched("y2", 1, r, fills))
    fx.refuses(ck.RefusedError, "correction's R'", lambda: ck.touched("z1", 1, k, fills))


@pytest.mark.parametrize(
    ("change", "why"),
    [
        ("open", "records no deviation"),
        ("void", "records no deviation"),
        ("classified", "is classified already"),
        ("missing", "records no deviation"),
        ("on-master", "on the master ref already"),
    ],
)
def test_a_correction_check_refuses_an_attempt_it_cannot_name(
    runs_dir: Path, tmp_path: Path, change: str, why: str
) -> None:
    rows = defect_attempts(runs_dir)
    test = {"attempt": 1, "test": PROBE}
    entry = {"id": "c1", "R": "f" * 40, "R_K": "e" * 40, "blocks": {"x1": test}}
    fills: dict[str, Any] = {"commits": {"R": "a" * 40, "R_K": "b" * 40}}
    if change == "open":
        rows[0]["valid"] = None
    elif change == "void":
        rows[0].update(valid=False, void_causes=["usage limit"])
    elif change == "classified":
        rows[0]["classified"] = {
            "route": "instrument defect",
            "correction": "c0",
            "recorded_utc": "x",
        }
    elif change == "missing":
        entry["blocks"] = {"x1": {**test, "attempt": 2}}
    else:
        fills["corrections"] = [{**entry, "blocks": {"y1": test}}]
    blocks(runs_dir, rows)
    path = entry_file(tmp_path, entry)
    fx.refuses(ck.RefusedError, why, lambda: ck.correction_check(path, tmp_path, tmp_path, fills))


@pytest.mark.parametrize(
    ("change", "why"),
    [
        ("not-at-r-prime", "^R is [0-9a-f]+, not"),
        ("dirty", "the R checkout is not clean"),
        ("r-itself", "names R itself"),
        ("does-not-run", "neither passed nor failed on an assertion"),
        ("fails-at-r-by-an-error", "neither passed nor failed on an assertion"),
        ("r-k-two-above", "R_K's parent"),
        ("not-descending", "does not descend"),
        ("untracked", "not tracked at R'"),
        ("passes-at-r", r"must fail at R .*'R': 'passes'"),
        ("not-on-the-records", r"must fail at R .*'x1': 'passes'"),
    ],
)
def test_a_correction_check_refuses_commits_or_a_test_that_do_not_show_the_defect(
    r_k: Any,  # noqa: ANN401
    runs_dir: Path,
    tmp_path: Path,
    change: str,
    why: str,
) -> None:
    extra = dict(FIXED)
    if change == "passes-at-r":  # on its own fixtures it passes whatever the tree
        extra[PROBE] = PROBE_TEXT.replace('(Path(__file__).parent / "fixed.txt").exists()', "True")
    if change == "does-not-run":  # pytest cannot collect it: neither a pass nor a fail
        extra[PROBE] = "def test_nothing( -> None:\n"
    if change == "fails-at-r-by-an-error":  # at R it errors, it shows no defect
        old = 'assert (Path(__file__).parent / "fixed.txt").exists()'
        extra[PROBE] = PROBE_TEXT.replace(
            old, old.replace(".exists()", '.read_text() == "fixed\\n"')
        )
    if change == "r-itself":  # R' is R: R_K' sits right above R
        r, k, rs, ks = r_k(f"cc-{change}")
        head = rs
    else:
        r, k, rs, ks, head = corrected_pair(
            r_k, f"cc-{change}", k_commits=2 if change == "r-k-two-above" else 1, extra=extra
        )
    if change == "dirty":
        (r / "stray.txt").write_text("x\n")
    defect_attempts(runs_dir)
    if change == "not-on-the-records":
        (runs_dir / "blocks" / "x1-1" / "defect.txt").unlink()
    test = {
        "attempt": 1,
        "test": "experiments/R-PG-03/test_none.py" if change == "untracked" else PROBE,
    }
    entry = {"id": "c1", "R": rs, "R_K": ks, "blocks": {"x1": test}}
    fills = {"commits": {"R": ks if change == "not-descending" else head}}
    where = k if change == "not-at-r-prime" else r
    path = entry_file(tmp_path, entry)
    fx.refuses(ck.RefusedError, why, lambda: ck.correction_check(path, where, k, fills, rs))
    assert not (runs_dir / "corrections" / "c1" / "check.json").exists()


# ---- No single act or commit stops the run (§11, README 24) --------------------------------------

OLD = "2026-10-01T00:00:00Z"  # before any check record these tests write
LATE = "2026-12-01T00:00:00Z"  # after every one


def ok(block: str, attempt: int = 1, ended: str = OLD, **kw: Any) -> dict[str, Any]:  # noqa: ANN401
    """A valid attempt that ended and passed its stream check."""
    row = {"block": block, "attempt": attempt, "valid": True, "ended_utc": ended}
    return {**row, "stream_check": {"cut": 0}, "void_causes": [], **kw}


def withdraw(fills: dict[str, Any], what: dict[str, str]) -> dict[str, Any]:
    """The fills with one more withdrawal, as its own commit adds it."""
    return {**fills, "withdrawn": [*fills.get("withdrawn", []), {**what, "why": "a mistake"}]}


@pytest.mark.parametrize("block", ["y1", "s"])
def test_after_three_void_attempts_the_block_is_declared_impossible_and_the_run_goes_on(
    runs_dir: Path, block: str
) -> None:
    voids = [
        {**att(block, False), "attempt": n, "void_causes": ["usage limit"], "ended_utc": OLD}
        for n in (1, 2, 3)
    ]
    later = common.BLOCKS[common.BLOCKS.index(block) + 1]
    blocks(runs_dir, [*(ok(b) for b in common.BLOCKS if b not in (block, later)), *voids])
    exit_ = f"checks.py classify --block {block} --attempt <its last void attempt>"
    fx.refuses(ck.RefusedError, exit_, lambda: ck.order(block, now=AFTER))
    fx.refuses(ck.RefusedError, f"block {block} comes first", lambda: ck.order(later, now=AFTER))
    fx.refuses(
        ck.RefusedError,
        "records no deviation",
        lambda: ck.classify(block, 2, "anything else impossible as specified", None, None, {}),
    )
    ck.classify(block, 3, "anything else impossible as specified", None, None, {})
    assert common.not_taken(ck.read_blocks()["attempts"], set()) == {block: 3}
    assert holds(lambda: ck.order(later, now=AFTER))["attempt"] == 1
    fx.refuses(ck.RefusedError, "not attempted again", lambda: ck.order(block, now=AFTER))


def test_an_impossible_classification_of_an_attempt_a_correction_names_is_refused(
    runs_dir: Path,
) -> None:
    launch = runs_dir / "blocks" / "x1-1"
    launch.mkdir(parents=True)
    dev = {"causes": ["a run that is not whole"]}
    x1 = {**att("x1", False), "launch": str(launch), "void_causes": [], "deviation": dev}
    blocks(runs_dir, [{**x1, "ended_utc": OLD}, *(ok(b) for b in common.BLOCKS if b != "x1")])
    fills = {"corrections": [C1]}
    checked(runs_dir, C1)
    # Refused before it is recorded, naming its exit; then classified as the correction says.
    impossible = "anything else impossible as specified"
    fx.refuses(
        ck.RefusedError,
        "a correction names block x1's attempt 1",
        lambda: ck.classify("x1", 1, impossible, None, None, fills),
    )
    assert "classified" not in ck.read_blocks()["attempts"][0]
    holds(lambda: ck.classify("x1", 1, "instrument defect", TEST, "c1", fills))
    # Had it been recorded, the tally skips a block not taken before it asks for corrections.
    rec = ck.read_blocks()
    rec["attempts"][0]["classified"] = {"route": impossible, "recorded_utc": "x"}
    ck.write_blocks(rec)
    assert "x1" not in holds(lambda: t3.blocks_record(runs_dir, {"corrections": []}))["chosen"]


def test_a_correction_committed_before_its_check_is_withdrawn_and_the_run_goes_on(
    runs_dir: Path, tmp_path: Path
) -> None:
    launch = runs_dir / "blocks" / "x1-1"
    launch.mkdir(parents=True)
    blocks(runs_dir, [{**ok("x1"), "launch": str(launch)}, *(ok(b) for b in common.BLOCKS[1:])])
    fills = {"commits": {"R": "a" * 40, "R_K": "b" * 40}, "corrections": [C1]}
    ck.classify("x1", 1, "instrument defect", TEST, "c1", fills)
    rec = ck.read_blocks()
    rec["attempts"].append(ok("x1", 2, LATE, commit=C1["R"]))  # it ran at c1's R'
    ck.write_blocks(rec)
    # Its check can no more be made; the refusal names the exit, its withdrawal.
    path = entry_file(tmp_path, C1)
    fx.refuses(
        ck.RefusedError,
        "Its exit.*its withdrawal",
        lambda: ck.correction_check(path, tmp_path, tmp_path, fills),
    )
    fx.refuses(
        common.RefusedError, "Its exit.*withdrawal", lambda: ck.run_pins(tmp_path, fills, "x1")
    )
    # Withdrawn: x1's attempt at c1's R' is set aside, and the run goes on at R.
    fills = withdraw(fills, {"correction": "c1"})
    assert holds(lambda: ck.run_pins(tmp_path, fills, "x1")) == (
        {"R": "a" * 40, "R_K": "b" * 40},
        None,
    )
    got = holds(lambda: t3.blocks_record(runs_dir, fills))
    assert got["chosen"]["x1"]["attempt"] == 1 and got["aside"] == [["x1", 2]]


def test_a_correction_that_names_a_block_wrongly_is_withdrawn_after_its_corrected_attempt_ran(
    runs_dir: Path,
) -> None:
    # c1 names x1 rightly and y2 wrongly; x1's corrected attempt has run at c1's R'.
    launch = runs_dir / "blocks" / "x1-1"
    launch.mkdir(parents=True)
    rows = [{**ok("x1"), "launch": str(launch)}, *(ok(b) for b in common.BLOCKS[1:])]
    blocks(runs_dir, rows)
    c1 = {**C1, "blocks": {"x1": ONE, "y2": ONE}}
    fills: dict[str, Any] = {"commits": {"R": "a" * 40, "R_K": "b" * 40}, "corrections": [c1]}
    ck.classify("x1", 1, "instrument defect", TEST, "c1", fills)
    rec = ck.read_blocks()
    rec["attempts"].append(ok("x1", 2, LATE, commit=c1["R"]))
    ck.write_blocks(rec)
    fx.refuses(
        common.RefusedError,
        "y2 is named by the corrections",
        lambda: ck.run_pins(Path("."), fills, "y2"),
    )
    # Withdrawn before any tally: x1's attempt that ran under it is set aside, y2 runs at R, and
    # x1 is owed its attempt again under the record that now stands.
    fills = withdraw(fills, {"correction": "c1"})
    assert holds(lambda: ck.run_pins(Path("."), fills, "y2"))[1] is None
    c2 = {**C1, "id": "c2", "R": "d" * 40}
    fills["corrections"] = [c1, c2]
    holds(lambda: ck.classify("x1", 1, "instrument defect", TEST, "c2", fills))
    assert (
        launch / f"classification-{rec['attempts'][0]['classified']['recorded_utc']}.json"
    ).is_file()
    assert holds(lambda: ck.order("x1", now=AFTER, fills=fills))["attempt"] == 3
    got = common.standing(ck.read_blocks()["attempts"], fills, {"c1"})
    assert [a["attempt"] for a in got if a["block"] == "x1"] == [1]


def test_an_attempt_at_a_withdrawn_correction_s_r_prime_stands_if_a_standing_one_shares_it() -> (
    None
):
    c2 = {**C1, "id": "c2"}  # the same R' as c1's
    fills = {"corrections": [C1, c2]}
    rows = [ok("x1"), ok("x1", 2, commit=C1["R"])]
    assert common.standing(rows, fills, {"c1"}) == rows
    assert common.standing(rows, {"corrections": [C1]}, {"c1"}) == rows[:1]


def test_a_withdrawal_recorded_after_the_first_tally_is_refused_and_says_why(
    runs_dir: Path,
) -> None:
    fills = withdraw({"corrections": [C1]}, {"correction": "c1"})
    assert common.withdrawn(fills, runs_dir) == ({"c1"}, [])
    (runs_dir / common.TALLIES).write_text(json.dumps({"withdrawn": 0}) + "\n")
    gone, refused = common.withdrawn(fills, runs_dir)
    assert gone == set() and refused == [fills["withdrawn"][0]]
    rows = [ok(b) for b in common.BLOCKS]
    blocks(
        runs_dir,
        [
            {
                **rows[0],
                "classified": {
                    "route": "instrument defect",
                    "correction": "c1",
                    "recorded_utc": "x",
                },
            },
            ok("x1", 2),
            *rows[1:],
        ],
    )
    checked(runs_dir, C1)
    got = holds(lambda: t3.blocks_record(runs_dir, fills))
    assert got["late"] == [
        {**fills["withdrawn"][0], "refused": "recorded after the first tally output (R8)"}
    ]


def test_a_fills_commit_that_cannot_be_taken_is_named_and_released_by_its_withdrawal(
    tmp_path: Path,
) -> None:
    taken = {**ALL}
    bad = {**ALL, "corrections": [C1]}
    steps = [*FILLED, ("fills: correct block x1", bad, None)]  # not "Commits corrected"
    repo = fills_repo(tmp_path, steps)
    sha = git(repo, "rev-parse", "HEAD")
    fx.refuses(
        common.RefusedError,
        f"{sha[:7]} cannot be taken.*Its exit.*Withdrawn",
        lambda: common.fills_on(repo, "HEAD"),
    )
    where = repo / common.EXPERIMENT / common.FILLS_NAME
    ident = ("-c", "user.email=t@example.invalid", "-c", "user.name=t")
    # A withdrawal that keeps the bad record is no withdrawal.
    where.write_text(json.dumps({**bad, "withdrawn": [{"commit": sha, "why": "its subject"}]}))
    git(repo, *ident, "commit", "-qam", f"fills: Withdrawn {sha[:7]}")
    fx.refuses(
        common.RefusedError, f"{sha[:7]} cannot be taken", lambda: common.fills_on(repo, "HEAD")
    )
    # The record taken last, plus the withdrawal of each commit not taken since, releases it.
    later = git(repo, "rev-parse", "HEAD")
    gone = [{"commit": sha, "why": "its subject"}, {"commit": later, "why": "kept the record"}]
    where.write_text(json.dumps({**taken, "withdrawn": gone}))
    git(repo, *ident, "commit", "-qam", "fills: Withdrawn")
    assert holds(lambda: common.fills_on(repo, "HEAD"))["withdrawn"] == gone
    where.write_text(json.dumps({**taken, "withdrawn": gone, "corrections": [C1]}))
    git(repo, *ident, "commit", "-qam", "fills: Commits corrected, block x1")
    assert holds(lambda: common.fills_on(repo, "HEAD"))["corrections"] == [C1]


def test_a_correction_l2_would_refuse_is_refused_by_its_check_before_it_is_recorded(
    r_k: Any,  # noqa: ANN401
    runs_dir: Path,
    tmp_path: Path,
) -> None:
    # R_K' keeps one of the fix's promotion lines: R' plus the five paths, but not K's content.
    head = git(common.REPO, "rev-parse", "HEAD")
    gitignore = (common.REPO / ".gitignore").read_text()
    r, k, rs, ks = r_k(
        "r3-promotions",
        r_extra={".gitignore": gitignore + "# a correction\n", **FIXED},
        drop_promotion=3,
    )
    defect_attempts(runs_dir)
    entry = {"id": "c1", "R": rs, "R_K": ks, "blocks": {"x1": {"attempt": 1, "test": PROBE}}}
    fills = {"commits": {"R": head, "R_K": "0" * 40}}
    path = entry_file(tmp_path, entry)
    fx.refuses(
        ck.RefusedError,
        "R_K's promotions, line for line",
        lambda: ck.correction_check(path, r, k, fills, rs),
    )
    assert not (runs_dir / "corrections" / "c1" / "check.json").exists()


BROAD = PROBE_TEXT.replace(
    'assert not (Path(records) / "defect.txt").exists()',
    'assert (Path(records) / "defect.txt").read_text() == "never"',
)


def test_a_test_that_errors_gives_no_answer_and_an_attempt_at_its_r_prime_is_not_asked(
    r_k: Any,  # noqa: ANN401
    runs_dir: Path,
    tmp_path: Path,
) -> None:
    # Its records mode errors on records without the defect's file (no assertion fails).
    extra = {**FIXED, PROBE: BROAD}
    r, k, rs, ks, head = corrected_pair(r_k, "r3-broad", extra=extra)
    defect_attempts(runs_dir)
    entry = {"id": "c1", "R": rs, "R_K": ks, "blocks": {"x1": {"attempt": 1, "test": PROBE}}}
    fills: dict[str, Any] = {"commits": {"R": head, "R_K": "0" * 40}}
    assert holds(lambda: ck.correction_check(entry_file(tmp_path, entry), r, k, fills, rs))[
        "passed"
    ]
    fills["corrections"] = [entry]
    ck.classify("x1", 1, "instrument defect", PROBE, "c1", fills, repo=r)
    again = runs_dir / "blocks" / "x1-2"
    again.mkdir(parents=True)
    rec = ck.read_blocks()
    rec["attempts"] = [
        {**rec["attempts"][0], "ended_utc": OLD, "stream_check": {"cut": 0}},
        {**ok("x1", 2, LATE), "launch": str(again), "commit": rs},
        *(ok(b) for b in common.BLOCKS[1:]),
    ]
    ck.write_blocks(rec)
    fx.refuses(
        ck.RefusedError,
        "neither passed nor failed on an assertion",
        lambda: ck.touched("x1", 2, r, fills),
    )
    # Run at a commit that carries c1's fix, x1's corrected attempt is not asked for c1's result.
    assert holds(lambda: t3.blocks_record(runs_dir, fills))["chosen"]["x1"]["attempt"] == 2


def test_run_test_runs_the_checkout_s_own_code_and_ignores_records_named_in_the_owner_s_shell(
    r_k: Any,  # noqa: ANN401
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    r, k, rs, ks, head = corrected_pair(r_k, "r3-env", extra=FIXED)
    shown = tmp_path / "shown"
    shown.mkdir()
    (shown / "defect.txt").write_text("shown\n")
    monkeypatch.setenv(ck.BLOCK_RECORDS, str(shown))  # left in the shell: fixture mode is asked
    assert ck.run_test(r, PROBE) is True
    assert ck.run_test(r, PROBE, shown) is False


def test_touched_keeps_each_correction_s_result_beside_the_others(
    r_k: Any,  # noqa: ANN401
    runs_dir: Path,
) -> None:
    r, k, rs, ks, head = corrected_pair(r_k, "r3-merge", extra=FIXED)
    clean = runs_dir / "blocks" / "z1-1"
    clean.mkdir(parents=True)
    (clean / "touched.json").write_text(
        json.dumps({"c0": {"tests": {TEST: "passes"}, "utc": LATE}})
    )
    blocks(runs_dir, [{**ok("z1"), "launch": str(clean)}])
    entry = {"id": "c1", "R": rs, "R_K": ks, "blocks": {"x1": {"attempt": 1, "test": PROBE}}}
    holds(lambda: ck.touched("z1", 1, r, {"corrections": [entry]}))
    assert sorted(json.loads((clean / "touched.json").read_text())) == ["c0", "c1"]


# ---- R3 ------------------------------------------------------------------------------------------


def test_r3_refuses_a_review_root_inside_a_set_or_a_checkout(tmp_path: Path) -> None:
    sets = fx.write_sets(tmp_path / "sets", ["fresh-v2-x1"])
    inside = sets / "fresh-v2-x1" / "artefacts" / "root"
    with pytest.raises(ck.RefusedError):
        ck.r3(common.REPO, [inside], sets, [], None)
    with pytest.raises(ck.RefusedError):
        ck.r3(common.REPO, [common.REPO / "review-root"], sets, [], None)


def test_r3_never_opens_r_pg_01_s_corpus_and_holds_it_by_placement(tmp_path: Path) -> None:
    sets = fx.write_sets(tmp_path / "sets", ["fresh-v2-x1"])
    root = Path("/tmp") / f"rp3r3-{tmp_path.name[-8:]}" / "root"
    found = ck.r3(common.REPO, [root], sets, [], None)
    assert "v1" not in found["sets_read"] and "fresh-v2-x1" in found["sets_read"]


# ---- the attempt's end ---------------------------------------------------------------------------


@pytest.fixture(scope="module")
def ended(tmp_path_factory: pytest.TempPathFactory) -> dict[str, Any]:
    base = tmp_path_factory.mktemp("after")
    sets = fx.write_sets(base / "sets", ["fresh-v2-x1"])
    runs = {arm: fx.real_run(sets / "fresh-v2-x1", base / arm, 53, arm, {}) for arm in common.ARMS}
    return {"base": base, "sets": sets, "runs": runs}


def end(
    ended: dict[str, Any],
    tmp: Path,
    monkeypatch: pytest.MonkeyPatch,
    *,
    exits: dict[str, int] | None = None,
    watcher: str = "",
    first_minute: bool = False,
) -> dict[str, Any]:
    monkeypatch.setenv("RP3_RUNS", str(tmp / "runs"))
    monkeypatch.setitem(common.BLOCK_ITEMS, "x1", 4)
    launch = tmp / "launch"
    launch.mkdir()
    (launch / "exits.json").write_text(json.dumps(exits or dict.fromkeys(common.ARMS, 0)))
    (launch / "watcher.log").write_text(watcher)
    if first_minute:
        (launch / "first_minute.txt").write_text("A1 stopped within its first minute\n")
    runs = {
        "runs": {a: str(p) for a, p in ended["runs"].items()},
        "scratch": {a: str(p.parent / "scratch") for a, p in ended["runs"].items()},
    }
    ck.start("x1", 1, runs)
    assert ck.read_blocks()["attempts"][-1]["commit"] == git(common.REPO, "rev-parse", "HEAD")
    sheet = json.dumps({"label": "x", "rows": {"R11.04": {"quantity": "q"}}}).encode()
    return ck.after("x1", 1, launch, sheet, ended["sets"])


def test_a_whole_attempt_is_valid_and_r6_and_the_lanes_hold(
    ended: dict[str, Any], tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    found = end(ended, tmp_path, monkeypatch)
    assert found["valid"] and found["void_causes"] == [] and found["deviations"] == []
    rec = json.loads((tmp_path / "runs" / "blocks.json").read_text())
    assert rec["attempts"][0]["valid"] is True and rec["attempts"][0]["stream_check"] == {"cut": 0}


@pytest.mark.parametrize(
    ("kw", "cause"),
    [
        ({"watcher": "ABORT 2026-11-05: usage_limit_reached files 1"}, "usage limit"),
        ({"first_minute": True}, "an arm stopped in its first minute"),
    ],
)
def test_each_void_cause_voids_the_attempt(
    ended: dict[str, Any],
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    kw: dict[str, Any],
    cause: str,
) -> None:
    found = end(ended, tmp_path, monkeypatch, **kw)
    assert not found["valid"] and cause in found["void_causes"]


def test_a_review_line_with_another_arm_s_rubric_digest_voids_the_attempt(
    ended: dict[str, Any], tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    b = fx.copy_run(ended["runs"]["B"], tmp_path / "b")
    text = (b / "events.jsonl").read_text()
    for role in common.ROLES:
        text = text.replace(common.RUBRIC_SHA256["B"][role], common.RUBRIC_SHA256["A1"][role])
    (b / "events.jsonl").write_text(text)
    found = end({**ended, "runs": {**ended["runs"], "B": b}}, tmp_path, monkeypatch)
    assert "a review line's rubric digest is not its arm's" in found["void_causes"]


@pytest.mark.parametrize(
    "exits", [{"A2": 0, "A1": 143, "B": 0}, {"A2": 0, "B": 0}], ids=["killed", "no-exit"]
)
def test_a_crashed_or_killed_process_is_a_deviation_never_a_void(
    ended: dict[str, Any], tmp_path: Path, monkeypatch: pytest.MonkeyPatch, exits: dict[str, int]
) -> None:
    # §11's void list is closed; anything else impossible as specified is a deviation.
    found = end(ended, tmp_path, monkeypatch, exits=exits)
    assert not found["valid"] and found["void_causes"] == []
    assert "a crashed or killed process" in found["deviation"]["causes"]
    row = json.loads((tmp_path / "runs" / "blocks.json").read_text())["attempts"][0]
    assert "classified" not in row and row["launch"] == str(tmp_path / "launch")


def test_a_run_that_is_not_whole_is_a_deviation_never_a_void(
    ended: dict[str, Any], tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    b = fx.copy_run(ended["runs"]["B"], tmp_path / "b")
    rows = (b / "results.jsonl").read_text().splitlines()
    (b / "results.jsonl").write_text("\n".join(rows[:-1]) + "\n")
    found = end({**ended, "runs": {**ended["runs"], "B": b}}, tmp_path, monkeypatch)
    assert found["void_causes"] == [] and "a run that is not whole" in found["deviation"]["causes"]


def test_a_deviation_holds_the_block_until_the_owner_classifies_it(runs_dir: Path) -> None:
    launch = runs_dir / "blocks" / "x1-1"
    launch.mkdir(parents=True)
    pending = {
        "causes": ["a crashed or killed process"],
    }
    row = {**att("x1", False), "launch": str(launch), "void_causes": [], "deviation": pending}
    blocks(runs_dir, [row])
    with pytest.raises(ck.RefusedError, match="classif"):
        ck.order("x1", now=AFTER)
    test = TEST
    bad: list[tuple[str, str | None, str]] = [
        ("instrument defect", None, "test"),
        ("instrument defect", "experiments/R-PG-03/checks.py", "test"),
        ("instrument defect", "experiments/R-PG-03/test_nothing.py", "tracked"),
        ("something else", None, "route"),
    ]
    for route, path, why in bad:
        with pytest.raises(ck.RefusedError, match=why):
            ck.classify("x1", 1, route, path, "c1")
    with pytest.raises(ck.RefusedError, match="names the correction"):
        ck.classify("x1", 1, "instrument defect", test, None)
    with pytest.raises(ck.RefusedError, match="no deviation"):
        ck.classify("x1", 2, "anything else impossible as specified", None)
    got = ck.classify("x1", 1, "instrument defect", test, "c1", {"corrections": [C1]})
    assert got["test_blob"] == git(common.REPO, "rev-parse", f"HEAD:{test}")
    assert json.loads((launch / "classification.json").read_text())["route"] == "instrument defect"
    with pytest.raises(ck.RefusedError, match="already"):
        ck.classify("x1", 1, "anything else impossible as specified", None)
    assert ck.order("x1", now=AFTER)["attempt"] == 2  # re-run at the corrected commit
    # A deviation is no void attempt: three voids are still needed for the owner's declaration.
    marked = {"route": "instrument defect", "correction": "c1", "recorded_utc": "x"}
    blocks(runs_dir, [{**row, "classified": marked}] * 3)
    assert holds(lambda: ck.order("x1", now=AFTER))["attempt"] == 4


def test_a_deviation_classified_impossible_as_specified_is_never_attempted_again(
    runs_dir: Path,
) -> None:
    launch = runs_dir / "blocks" / "x1-1"
    launch.mkdir(parents=True)
    pending = {
        "causes": ["a run that is not whole"],
    }
    blocks(
        runs_dir,
        [{**att("x1", False), "launch": str(launch), "void_causes": [], "deviation": pending}],
    )
    ck.classify("x1", 1, "anything else impossible as specified", None)
    with pytest.raises(ck.RefusedError, match="not taken"):
        ck.order("x1", now=AFTER)


def test_a_block_classified_impossible_is_marked_not_taken_and_the_later_blocks_run(
    runs_dir: Path,
) -> None:
    # §11: the decisions it feeds are not taken; nothing else stops.
    launch = runs_dir / "blocks" / "y1-1"
    launch.mkdir(parents=True)
    pending = {
        "causes": ["a run that is not whole"],
    }
    row = {**att("y1", False), "launch": str(launch), "void_causes": [], "deviation": pending}
    blocks(runs_dir, [att("x1", True), row])
    with pytest.raises(ck.RefusedError, match="block y1 comes first"):
        ck.order("z1", now=AFTER)
    ck.classify("y1", 1, "anything else impossible as specified", None)
    marked = common.not_taken(ck.read_blocks()["attempts"], set())
    assert marked == {"y1": 1}
    assert holds(lambda: ck.order("z1", now=AFTER))["attempt"] == 1


def test_an_incomplete_run_is_a_crashed_process(tmp_path: Path) -> None:
    run = tmp_path / "run"
    (run / "controls").mkdir(parents=True)
    (run / "results.jsonl").write_text('{"artefact": "a01"}\n{"half')
    assert not ck.complete(run, 1)["holds"]


# ---- processes and credentials -------------------------------------------------------------------


def test_only_claude_and_inject_processes_count_as_live_sessions() -> None:
    procs = [
        (1, ["/home/u/pinned/claude-2.1.301", "-p"]),
        (2, ["python", "/x/.venv/bin/physgate", "inject", "--corpus", "c"]),
        (3, ["python", "physgate", "hooks"]),
        (4, ["bash", "claude-notes.sh"]),
    ]
    assert ck.live_sessions(procs) == [1, 2]


@pytest.mark.skipif(platform.system() == "Linux", reason="on the run machine it would signal")
def test_stopping_sessions_off_the_run_machine_is_refused(tmp_path: Path) -> None:
    with pytest.raises(ck.RefusedError, match="run machine alone"):
        ck.stop_sessions([tmp_path / "rp3-x1-1-a2"])


def test_a_login_file_left_under_a_review_root_is_found(tmp_path: Path) -> None:
    d = tmp_path / fx.session_of(1) / "session" / "config"
    d.mkdir(parents=True)
    (d / ".credentials.json").write_text("{}")
    assert ck.login_files(tmp_path)["left"] == 1
    assert common.remove_inside(tmp_path, (fx.session_of(1), "session", "config")) == "removed"
    assert ck.login_files(tmp_path)["left"] == 0


def test_a_packet_with_another_arm_s_knowledge_voids_the_attempt(
    ended: dict[str, Any], tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    run = fx.copy_run(ended["runs"]["A2"], tmp_path / "a2" / "run")
    scratch = tmp_path / "a2" / "scratch"
    line = next(
        json.loads(x)
        for x in (run / "events.jsonl").read_text().splitlines()
        if '"review_ran"' in x
    )
    packet = scratch / "lane-0" / line["result"]["session_id"] / "packet.json"
    packet.parent.mkdir(parents=True)
    packet.write_text(json.dumps({"knowledge_sha256": {"knowledge/cross/standards.md": "0" * 64}}))
    found = end({**ended, "runs": {**ended["runs"], "A2": run}}, tmp_path, monkeypatch)
    assert "a review's knowledge digests are not its arm's" in found["void_causes"]


def on_the_run_machine(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(platform, "system", lambda: "Linux")
    monkeypatch.setattr(platform, "machine", lambda: "aarch64")


def recorded_session(scratch: Path, n: int, pid: int) -> Path:
    """A session under a review root whose process record names ``pid``, still running."""
    sid = fx.session_of(n)
    d = scratch / "lane-0" / sid / "session"
    (d / "config").mkdir(parents=True)
    (d / "config" / ".credentials.json").write_text("{}")
    (d / "process.json").write_text(json.dumps({"pid": pid, "started": "t", "session_id": sid}))
    return d


@pytest.mark.parametrize("leads", [True, False])
def test_stop_sessions_signals_only_a_session_that_leads_its_own_group(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, leads: bool
) -> None:
    on_the_run_machine(monkeypatch)
    from physgate.orchestrator import dispatch, processes

    signalled: list[tuple[int, int]] = []
    monkeypatch.setattr(os, "killpg", lambda pid, sig: signalled.append((pid, sig)))
    monkeypatch.setattr(processes, "is_session", lambda pid, started, sid: not signalled)
    monkeypatch.setattr(dispatch, "process_group_of", lambda pid: pid if leads else 1)
    scratch = tmp_path / "rp3-x1-1-a2"
    recorded_session(scratch, 1, 424242)
    got = ck.stop_sessions([scratch])
    assert signalled == ([(424242, signal.SIGTERM)] if leads else [])
    assert got["stopped"] == int(leads) and got["login_files_left"] == 0


def test_stop_sessions_refuses_a_review_root_that_is_a_symlink(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    on_the_run_machine(monkeypatch)
    real = tmp_path / "elsewhere"
    recorded_session(real, 1, 424242)
    (tmp_path / "rp3-x1-1-a2").symlink_to(real)
    fx.refuses(
        ck.RefusedError, "not a review root", lambda: ck.stop_sessions([tmp_path / "rp3-x1-1-a2"])
    )


def test_the_host_check_refuses_a_login_file_it_cannot_confirm_removed(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    on_the_run_machine(monkeypatch)
    monkeypatch.setattr(ck, "own_processes", lambda: [])
    monkeypatch.setattr(ck, "HOME", tmp_path)
    root = tmp_path / common.SCRATCH_NAME / "rp3-x1-1-a2"
    root.mkdir(parents=True)
    assert ck.host()["login_files_left"] == 0
    (tmp_path / "elsewhere").mkdir()
    (root / fx.session_of(1)).symlink_to(tmp_path / "elsewhere")  # a session reached by a link
    with pytest.raises(ck.RefusedError, match="not confirmed"):
        ck.host()
