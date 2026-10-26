"""Tests of checks.py: the block order and dates, the owner, R and R_K, R3, and an attempt's end.

Run explicitly, from the repository root: ``uv run pytest -q experiments/R-PG-03``.

R and R_K are this checkout's HEAD and a commit made in a temporary worktree that restores the
five paths to K's state, never pushed; the runs are the fixture's.
"""

from __future__ import annotations

import json
import platform
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
    assert ck.owner("x1", 1, [])["window_confirmed_utc"] == "2026-11-05T07:00:00Z"
    later = [{"kind": "authoring", "started_utc": "2026-11-05T07:30:00Z"}]
    with pytest.raises(ck.RefusedError, match="nothing else runs"):
        ck.owner("x1", 1, later)
    blocks(runs_dir, [att("x1", True)])
    owner_file(
        runs_dir,
        "block-y1-1.json",
        {"account_label": "a", "no_other_session_on_the_run_account": True},
    )
    assert ck.owner("y1", 1, later)["first_block"] is False


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
        name: str, extra: dict[str, str] | None = None, drop_promotion: int = 4
    ) -> tuple[Path, Path, str, str]:
        r = base / f"{name}-r"
        k = base / f"{name}-k"
        for d in (r, k):
            git(common.REPO, "worktree", "add", "-q", "--detach", str(d), head)
            made.append(d)
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
        return r, k, head, git(k, "rev-parse", "HEAD")

    yield make
    for d in made:
        subprocess.run(
            ["git", "-C", str(common.REPO), "worktree", "remove", "--force", str(d)], check=False
        )


def test_r_and_r_k_hold_section_3_2(r_k: Any) -> None:  # noqa: ANN401
    r, k, rs, ks = r_k("ok")
    found = ck.commits(r, k, {"commits": {"R": rs, "R_K": ks}})
    assert found["the paths R_K differs from R in"] == sorted(common.R_K_PATHS)


def test_r_k_with_a_sixth_path_is_refused(r_k: Any) -> None:  # noqa: ANN401
    r, k, rs, ks = r_k("six", extra={"README.md": "changed\n"})
    with pytest.raises(ck.RefusedError, match="paths R_K differs"):
        ck.commits(r, k, {"commits": {"R": rs, "R_K": ks}})


def test_r_k_s_promotions_are_compared_by_content_line_for_line(r_k: Any) -> None:  # noqa: ANN401
    r, k, rs, ks = r_k("three", drop_promotion=3)
    with pytest.raises(ck.RefusedError, match="promotions"):
        ck.commits(r, k, {"commits": {"R": rs, "R_K": ks}})


def test_commits_filled_must_be_on_record_and_be_the_checkouts(r_k: Any) -> None:  # noqa: ANN401
    r, k, rs, ks = r_k("fills")
    with pytest.raises(common.RefusedError, match="Commits filled"):
        ck.commits(r, k, {})
    with pytest.raises(ck.RefusedError, match="R is"):
        ck.commits(r, k, {"commits": {"R": "0" * 40, "R_K": ks}})
    with pytest.raises(ck.RefusedError, match="tree"):
        ck.commits(
            r, k, {"commits": {"R": rs, "R_K": ks, "trees": {"src/physgate/gate": "0" * 40}}}
        )


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
        ({"exits": {"A2": 0, "A1": 143, "B": 0}}, "a crashed or killed process"),
        ({"exits": {"A2": 0, "B": 0}}, "a crashed or killed process"),
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
