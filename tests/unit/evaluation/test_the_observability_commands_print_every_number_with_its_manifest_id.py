"""The observability commands, through the ``physgate`` command itself.

Every number a command prints carries the manifest id of the run it came from;
a refusal prints its reason and context on standard error and exits 2.
"""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any

import pytest
from observe_rig import fake_driver, fake_run, target_repo

from physgate.cli import main
from physgate.evaluation.observe.cost import read_trend
from physgate.evaluation.observe.manifest import read_manifest

BRIEF = "Build two modules.\n"


def run_of(tmp_path: Path, run_id: str = "run-a", **overrides: Any) -> Path:  # noqa: ANN401
    digest = hashlib.sha256(BRIEF.encode()).hexdigest()
    repo = tmp_path / "target"
    if not repo.exists():
        target_repo(tmp_path)
    return fake_run(tmp_path, run_id, repo, overrides={"brief_sha256": digest, **overrides})


def printed(capsys: pytest.CaptureFixture[str], argv: list[str]) -> dict[str, Any]:
    assert main(argv) == 0, capsys.readouterr().err
    out: dict[str, Any] = json.loads(capsys.readouterr().out)
    return out


def refused(capsys: pytest.CaptureFixture[str], argv: list[str]) -> dict[str, Any]:
    assert main(argv) == 2
    err: dict[str, Any] = json.loads(capsys.readouterr().err)
    return err


def test_the_help_lists_every_observability_command(capsys: pytest.CaptureFixture[str]) -> None:
    with pytest.raises(SystemExit):
        main(["--help"])
    listing = capsys.readouterr().out
    for command in ("manifest", "trace", "cost", "rerun", "variance", "compare"):
        assert command in listing


def test_manifest_and_trace_print_the_run_s_manifest_id(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    run = run_of(tmp_path)
    manifest_id = read_manifest(run).manifest_id
    shown = printed(capsys, ["manifest", "--run-dir", str(run)])
    assert shown["manifest_id"] == manifest_id and shown["config"]["run_id"] == "run-a"
    traced = printed(capsys, ["trace", "--run-dir", str(run)])
    assert traced["manifest_id"] == manifest_id and len(traced["sessions"]) == 2


def test_cost_prints_its_line_and_appends_it_to_the_trend(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    run = run_of(tmp_path, auth="subscription")
    trend = tmp_path / "trend.jsonl"
    line = printed(
        capsys, ["cost", "--run-dir", str(run), "--prices", "2026-09-27", "--append", str(trend)]
    )
    assert line["manifest_id"] == read_manifest(run).manifest_id
    assert line["basis"] == "list_price_estimate" and "not billed" in line["basis_label"]
    assert line["prices_date"] == "2026-09-27" and line["appended_to"] == str(trend)
    (kept,) = read_trend(trend)
    assert kept.manifest_id == line["manifest_id"] and str(kept.usd) == line["usd"]
    again = refused(
        capsys, ["cost", "--run-dir", str(run), "--prices", "2026-09-27", "--append", str(trend)]
    )
    assert "already holds" in again["error"]
    assert (
        "no price sheet"
        in refused(capsys, ["cost", "--run-dir", str(run), "--prices", "2020-01-01"])["error"]
    )


def test_variance_prints_n_and_each_run_s_manifest_id(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    runs = [run_of(tmp_path, f"run-{k}") for k in "abc"]
    report = printed(capsys, ["variance", "--runs", *map(str, runs)])
    assert report["n"] == 3 and report["ordering_variance"] == "0"
    assert [r["manifest_id"] for r in report["runs"]] == [
        read_manifest(r).manifest_id for r in runs
    ]
    missing = refused(capsys, ["variance", "--repeat", str(runs[0])])
    assert missing["missing"] == "n,brief,target,install,runs_dir,review_root"


def test_compare_prints_both_manifest_ids_or_refuses_across_drift(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    base, cand = run_of(tmp_path, "base"), run_of(tmp_path, "cand")
    side = printed(capsys, ["compare", str(base), str(cand)])
    assert side["baseline"]["manifest_id"] == read_manifest(base).manifest_id
    assert side["candidate"]["manifest_id"] == read_manifest(cand).manifest_id
    drifted = run_of(tmp_path, "drifted", endpoint="default")
    assert refused(capsys, ["compare", str(base), str(drifted)])["drifted"] == "endpoint"


def test_a_rerun_refused_before_anything_runs_exits_two(
    tmp_path: Path, capsys: pytest.CaptureFixture[str], monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("ANTHROPIC_BASE_URL", "http://127.0.0.1:9")
    run = run_of(tmp_path)
    other = tmp_path / "other.md"
    other.write_text("Something else.\n")
    common = ["--run-id", "run-r", "--run-dir", str(tmp_path / "run-r")]
    where = [
        "--target",
        str(tmp_path / "target"),
        "--install",
        str(tmp_path / "install"),
        "--review-root",
        str(tmp_path / "review-scratch"),
    ]
    error = refused(capsys, ["rerun", str(run), "--brief", str(other), *common, *where])
    assert "brief" in error["error"] and not (tmp_path / "run-r").exists()


def test_a_rerun_that_parts_exits_one_and_prints_its_rule_and_first_divergence(
    tmp_path: Path, capsys: pytest.CaptureFixture[str], monkeypatch: pytest.MonkeyPatch
) -> None:
    import physgate.evaluation.observe.cli as observe_cli

    monkeypatch.setenv("ANTHROPIC_BASE_URL", "http://127.0.0.1:9")
    run = run_of(tmp_path)
    brief = tmp_path / "brief.md"
    brief.write_text(BRIEF)
    elsewhere = tmp_path / "elsewhere"
    driver = fake_driver(elsewhere, tmp_path / "target", bare={1})
    monkeypatch.setattr(observe_cli, "through_the_command", lambda _registrations: driver)
    argv = ["rerun", str(run), "--brief", str(brief), "--run-id", "run-r"]
    where = ["--run-dir", str(elsewhere / "run-r"), "--target", str(tmp_path / "target")]
    assert (
        main(
            [
                *argv,
                *where,
                "--install",
                str(tmp_path / "install"),
                "--review-root",
                str(tmp_path / "review-scratch"),
            ]
        )
        == 1
    )
    shown = json.loads(capsys.readouterr().out)
    assert (shown["reproduced"], shown["rule"]) == (False, "exact")
    assert (shown["first"]["record"], shown["first"]["field"]) == ("events", "attempt_commit")
    assert shown["recorded_manifest_id"] == read_manifest(run).manifest_id
