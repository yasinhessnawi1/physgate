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

AFTER = ck._seconds("2026-11-06T09:00:00Z")


@pytest.fixture
def runs_dir(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    monkeypatch.setenv("RP3_RUNS", str(tmp_path / "runs"))
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
    assert ck.order("x1", now=AFTER, ledger=[before])["earliest"] == ck.EARLIEST


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
ACCOUNT = {"account_label": "the run account", "weekly_reset_utc": "2026-10-29T07:00:00Z"}
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
    got = ck.ff_status({"round-1": tmp_path / "round-1", "repeat-K": tmp_path / "repeat-K"})
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
            git(r, "-c", "user.email=t@example.invalid", "-c", "user.name=t", "commit", "-qam", "R")
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


C1 = {"block": "x1", "R": "f" * 40, "R_K": "e" * 40, "classification": "/r/blocks/x1-2/c.json"}
C2 = {**C1, "block": "y1"}
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
        ("docs(r-pg-03): Commits corrected, block y1", {**ALL, "corrections": [C1, C2]}, None),
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
                    "docs: Commits corrected, block y1",
                    {**ALL, "corrections": [{**C1, "R": "d" * 40}, C2]},
                    None,
                ),
            ],
            "changes",
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
        (FROZEN_README.replace("Three arms", "Four arms") + SECTION, "frozen part"),
        (FROZEN_README + SECTION + "\n## More\n\nx\n", "one appended section"),
        (FROZEN_README, "one appended section"),
        (FROZEN_README + "\n## Something else\n", "one appended section"),
    ],
    ids=["an-edit-inside-the-frozen-part", "a-second-section", "no-section", "another-section"],
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


def classified(runs: Path, route: str = "instrument defect", block: str = "x1") -> Path:
    """Block x1's first attempt, a deviation classified on ``route``; its classification's path."""
    launch = runs / "blocks" / f"{block}-1"
    launch.mkdir(parents=True)
    deviation = {"causes": ["a crashed or killed process"], "classification": route}
    row = {**att(block, False), "launch": str(launch), "void_causes": [], "deviation": deviation}
    blocks(runs, [row])
    path = launch / "classification.json"
    path.write_text(json.dumps({"block": block, "attempt": 1, "route": route}))
    return path


def correction(r: str, r_k: str, path: Path, block: str = "x1") -> dict[str, str]:
    return {"block": block, "R": r, "R_K": r_k, "classification": str(path)}


def corrected_pair(r_k: Any, name: str, k_commits: int = 1) -> tuple[Path, Path, str, str, str]:  # noqa: ANN401
    """R (the head), and R' one commit above it with R_K' above R'."""
    head = git(common.REPO, "rev-parse", "HEAD")
    gitignore = (common.REPO / ".gitignore").read_text()
    r, k, rs, ks = r_k(
        name, r_extra={".gitignore": gitignore + "# a correction\n"}, k_commits=k_commits
    )
    return r, k, rs, ks, head


def test_a_block_whose_deviation_is_an_instrument_defect_runs_at_its_corrected_commit(
    r_k: Any,
    runs_dir: Path,  # noqa: ANN401
) -> None:
    r, k, rs, ks, head = corrected_pair(r_k, "corrected")
    path = classified(runs_dir)
    fills: dict[str, Any] = {
        "commits": {"R": head, "R_K": "0" * 40},
        "corrections": [correction(rs, ks, path)],
    }
    # "Commits filled"'s trees describe R: they are not held at the corrected R'.
    fills["commits"]["trees"] = {"src/physgate/gate": "0" * 40}
    found = ck.commits(r, k, fills, master_ref=rs, block="x1")
    assert found["corrected"] == {"block": "x1", "R": rs, "R_K": ks, "classification": str(path)}
    # Every other block stays at R, the commit "Commits filled" records.
    with pytest.raises(ck.RefusedError, match="R is"):
        ck.commits(r, k, fills, master_ref=rs, block="y1")


def test_a_correction_for_a_block_whose_deviation_is_no_instrument_defect_is_refused(
    r_k: Any,
    runs_dir: Path,  # noqa: ANN401
) -> None:
    r, k, rs, ks, head = corrected_pair(r_k, "no-defect")
    path = classified(runs_dir, route="anything else impossible as specified")
    fills = {"commits": {"R": head, "R_K": "0" * 40}, "corrections": [correction(rs, ks, path)]}
    with pytest.raises(ck.RefusedError, match="no deviation classified an instrument defect"):
        ck.commits(r, k, fills, master_ref=rs, block="x1")


def test_an_instrument_defect_without_its_corrected_commit_is_refused(
    r_k: Any,
    runs_dir: Path,  # noqa: ANN401
) -> None:
    r, k, rs, ks = r_k("no-correction")
    classified(runs_dir)
    with pytest.raises(ck.RefusedError, match="corrected commit"):
        ck.commits(r, k, {"commits": {"R": rs, "R_K": ks}}, master_ref=rs, block="x1")


def test_a_correction_that_names_r_itself_is_refused(r_k: Any, runs_dir: Path) -> None:  # noqa: ANN401
    r, k, rs, ks = r_k("r-itself")
    path = classified(runs_dir)
    fills = {"commits": {"R": rs, "R_K": ks}, "corrections": [correction(rs, ks, path)]}
    with pytest.raises(ck.RefusedError, match="R itself"):
        ck.commits(r, k, fills, master_ref=rs, block="x1")


def test_a_corrected_commit_that_does_not_descend_from_r_is_refused(
    r_k: Any,
    runs_dir: Path,  # noqa: ANN401
) -> None:
    r, k, rs, ks = r_k("not-down")
    path = classified(runs_dir)
    fills = {"commits": {"R": rs, "R_K": ks}, "corrections": [correction(common.R_FLOOR, ks, path)]}
    with pytest.raises(ck.RefusedError, match="descend"):
        ck.commits(r, k, fills, master_ref=rs, block="x1")


def test_a_corrected_r_k_more_than_one_commit_above_r_prime_is_refused(
    r_k: Any,
    runs_dir: Path,  # noqa: ANN401
) -> None:
    r, k, rs, ks, head = corrected_pair(r_k, "corr-two", k_commits=2)
    path = classified(runs_dir)
    fills = {"commits": {"R": head, "R_K": "0" * 40}, "corrections": [correction(rs, ks, path)]}
    with pytest.raises(ck.RefusedError, match="R_K's parent"):
        ck.commits(r, k, fills, master_ref=rs, block="x1")


def test_a_correction_naming_another_classification_than_the_block_s_defect_is_refused(
    r_k: Any,
    runs_dir: Path,  # noqa: ANN401
) -> None:
    r, k, rs, ks, head = corrected_pair(r_k, "other-cls")
    path = classified(runs_dir)
    elsewhere = runs_dir / "elsewhere.json"
    elsewhere.write_text(path.read_text())
    fills = {
        "commits": {"R": head, "R_K": "0" * 40},
        "corrections": [correction(rs, ks, elsewhere)],
    }
    with pytest.raises(ck.RefusedError, match="classification"):
        ck.commits(r, k, fills, master_ref=rs, block="x1")
    path.write_text(json.dumps({"block": "x1", "attempt": 1, "route": "something else"}))
    fills["corrections"] = [correction(rs, ks, path)]
    with pytest.raises(ck.RefusedError, match="classification"):
        ck.commits(r, k, fills, master_ref=rs, block="x1")


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
    assert row["deviation"]["classification"] is None and row["launch"] == str(tmp_path / "launch")


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
    pending = {"causes": ["a crashed or killed process"], "classification": None}
    row = {**att("x1", False), "launch": str(launch), "void_causes": [], "deviation": pending}
    blocks(runs_dir, [row])
    with pytest.raises(ck.RefusedError, match="classif"):
        ck.order("x1", now=AFTER)
    test = "experiments/R-PG-03/test_checks.py"
    bad: list[tuple[str, str | None, str]] = [
        ("instrument defect", None, "test"),
        ("instrument defect", "experiments/R-PG-03/checks.py", "test"),
        ("instrument defect", "experiments/R-PG-03/test_nothing.py", "tracked"),
        ("something else", None, "route"),
    ]
    for route, path, why in bad:
        with pytest.raises(ck.RefusedError, match=why):
            ck.classify("x1", 1, route, path)
    with pytest.raises(ck.RefusedError, match="no deviation"):
        ck.classify("x1", 2, "anything else impossible as specified", None)
    got = ck.classify("x1", 1, "instrument defect", test)
    assert got["test_blob"] == git(common.REPO, "rev-parse", f"HEAD:{test}")
    assert json.loads((launch / "classification.json").read_text())["route"] == "instrument defect"
    with pytest.raises(ck.RefusedError, match="already"):
        ck.classify("x1", 1, "anything else impossible as specified", None)
    assert ck.order("x1", now=AFTER)["attempt"] == 2  # re-run at the corrected commit
    # A deviation is no void attempt: three voids are still needed for the owner's declaration.
    blocks(runs_dir, [{**row, "deviation": {**pending, "classification": "instrument defect"}}] * 3)
    assert ck.order("x1", now=AFTER)["attempt"] == 4


def test_a_deviation_classified_impossible_as_specified_is_never_attempted_again(
    runs_dir: Path,
) -> None:
    launch = runs_dir / "blocks" / "x1-1"
    launch.mkdir(parents=True)
    pending = {"causes": ["a run that is not whole"], "classification": None}
    blocks(
        runs_dir,
        [{**att("x1", False), "launch": str(launch), "void_causes": [], "deviation": pending}],
    )
    ck.classify("x1", 1, "anything else impossible as specified", None)
    with pytest.raises(ck.RefusedError, match="not taken"):
        ck.order("x1", now=AFTER)


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
    with pytest.raises(ck.RefusedError, match="not a review root"):
        ck.stop_sessions([tmp_path / "rp3-x1-1-a2"])


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
