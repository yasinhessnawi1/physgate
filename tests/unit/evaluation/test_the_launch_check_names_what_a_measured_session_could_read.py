"""The launch check prints the machine's state a measured round may not start on, by name.

A stand-in for the operator's home, a store with a registered run root, and a source repository
trials are cloned from: each finding the rulings list is planted alone, the check names it and
exits non-zero; on the clean stand-in it finds nothing and exits zero. Nothing real is read.
"""

from __future__ import annotations

import contextlib
import io
import json
import os
import subprocess
from pathlib import Path
from types import SimpleNamespace

import pytest

from physgate.cli import main
from physgate.evaluation.launch_check import launch_findings
from physgate.evaluation.tiers.exposure import add_run_root
from physgate.evaluation.tiers.store import make_role_root, role_root

GIT_ENV = {
    "PATH": "/usr/bin:/bin",
    "HOME": os.devnull,
    "GIT_AUTHOR_NAME": "t",
    "GIT_AUTHOR_EMAIL": "t@example.invalid",
    "GIT_COMMITTER_NAME": "t",
    "GIT_COMMITTER_EMAIL": "t@example.invalid",
}


def _git(cwd: Path, *args: str) -> str:
    return subprocess.run(
        ["git", *args], cwd=cwd, env=GIT_ENV, check=True, capture_output=True, text=True
    ).stdout


def _stand_in(base: Path) -> SimpleNamespace:
    home = base / "home"
    (home / "notes").mkdir(parents=True)
    (home / "notes" / "a.txt").write_text("a\n")
    store = home / "store"
    store.mkdir()
    make_role_root(role_root(store, "control"))
    runs = home / "runs"
    runs.mkdir()
    add_run_root(store, "control", runs)
    source = home / "source"
    source.mkdir()
    _git(source, "init", "-q", "-b", "main")
    (source / "README.md").write_text("a target\n")
    _git(source, "add", "-A")
    _git(source, "commit", "-q", "-m", "fixture")
    return SimpleNamespace(home=home, store=store, runs=runs, source=source)


def _check(s: SimpleNamespace) -> tuple[int, list[str]]:
    out = io.StringIO()
    argv = ["tiers", "launch-check", "--store", str(s.store), "--source", str(s.source)]
    with contextlib.redirect_stdout(out):
        code = main([*argv, "--home", str(s.home)])
    return code, out.getvalue().splitlines()


def _kinds(s: SimpleNamespace) -> set[str]:
    found = launch_findings(store=s.store, source=s.source, home=s.home)
    return {f.kind for f in found}


@pytest.fixture
def s(outside_tmp: Path, monkeypatch: pytest.MonkeyPatch) -> SimpleNamespace:
    # The stand-in home alone: the machine's own places are not this row's to walk.
    monkeypatch.setattr("physgate.evaluation.launch_check.MACHINE_PLACES", ())
    return _stand_in(Path(os.path.realpath(outside_tmp)))


def test_a_clean_machine_has_nothing_to_say_and_exits_zero(s: SimpleNamespace) -> None:
    code, lines = _check(s)
    assert code == 0, lines
    assert lines[-1] == "launch check: nothing found"


@pytest.mark.parametrize(
    "name", ["run.json", "raw.json", "params_source.json", "round.json", "baseline.json"]
)
def test_another_run_s_material_left_where_a_session_reads_is_named(
    s: SimpleNamespace, name: str
) -> None:
    left = s.home / "old" / "run-7"
    left.mkdir(parents=True)
    (left / name).write_text("{}\n")
    code, lines = _check(s)
    assert code == 1
    assert f"finding: run_material_readable: {left}: it holds {name}" in lines


def test_material_beneath_a_registered_run_root_or_the_store_is_no_finding(
    s: SimpleNamespace,
) -> None:
    for where in (s.runs / "run-1", s.store / "control" / "work" / "t1"):
        where.mkdir(parents=True)
        (where / "raw.json").write_text("{}\n")
    assert "run_material_readable" not in _kinds(s)


def test_a_link_is_never_followed_by_the_walk(s: SimpleNamespace) -> None:
    (s.runs / "run-1").mkdir()
    (s.runs / "run-1" / "raw.json").write_text("{}\n")
    (s.home / "a-link-to-the-runs").symlink_to(s.runs)
    assert "run_material_readable" not in _kinds(s)


def test_a_source_with_a_second_branch_a_tag_or_a_stash_is_named(s: SimpleNamespace) -> None:
    _git(s.source, "branch", "physgate/run-1")
    _git(s.source, "tag", "v1")
    code, lines = _check(s)
    assert code == 1
    assert any(line.startswith("finding: source_branches:") for line in lines), lines
    assert any("it holds refs/tags/v1" in line for line in lines), lines


def test_an_object_no_branch_reaches_in_the_source_is_named(s: SimpleNamespace) -> None:
    (s.source / "work.py").write_text("an earlier run's work\n")
    _git(s.source, "add", "-A")
    _git(s.source, "commit", "-q", "-m", "earlier work")
    _git(s.source, "reset", "-q", "--hard", "HEAD~1")
    kinds = _kinds(s)
    assert "source_objects" in kinds and "source_branches" not in kinds


def test_a_run_beneath_the_run_roots_that_does_not_withhold_them_is_named(
    s: SimpleNamespace, monkeypatch: pytest.MonkeyPatch
) -> None:
    from physgate.evaluation import launch_check

    run = s.runs / "dev-run"
    run.mkdir()
    (run / "run.json").write_text("{}\n")
    withholding = s.runs / "measured-run"
    withholding.mkdir()
    (withholding / "run.json").write_text("{}\n")
    named = {str(run): [], str(withholding): [str(s.runs)]}

    def load(path: Path) -> SimpleNamespace:
        return SimpleNamespace(withheld_whole=named[str(path.parent)])

    monkeypatch.setattr("physgate.orchestrator.run_config.load_run_config", load)
    found = launch_check.withholding_findings([s.runs], {os.path.realpath(s.runs)})
    assert [(f.kind, f.place) for f in found] == [("run_not_withholding", str(run))]


def test_every_finding_is_one_line_and_the_last_line_counts_them(s: SimpleNamespace) -> None:
    (s.home / "left" / "x").mkdir(parents=True)
    (s.home / "left" / "x" / "round.json").write_text(json.dumps({}))
    _git(s.source, "tag", "v2")
    code, lines = _check(s)
    findings = [line for line in lines if line.startswith("finding: ")]
    assert code == 1 and len(findings) == 2
    assert lines[-1] == "launch check: 2 finding(s)"


def test_a_run_holding_another_record_beside_its_run_json_is_still_judged(
    s: SimpleNamespace, monkeypatch: pytest.MonkeyPatch
) -> None:
    from physgate.evaluation import launch_check

    run = s.runs / "dev-run"
    run.mkdir()
    for name in ("run.json", "params_source.json"):
        (run / name).write_text("{}\n")
    monkeypatch.setattr(
        "physgate.orchestrator.run_config.load_run_config",
        lambda path: SimpleNamespace(withheld_whole=[]),
    )
    found = launch_check.withholding_findings([s.runs], {os.path.realpath(s.runs)})
    assert [(f.kind, f.place) for f in found] == [("run_not_withholding", str(run))]


def test_a_place_deeper_than_any_bound_is_walked_whole(s: SimpleNamespace) -> None:
    deep = s.home / "deep"
    for n in range(12):
        deep = deep / f"d{n}"
    deep.mkdir(parents=True)
    (deep / "raw.json").write_text("{}\n")
    left = s.home / "left-run"
    left.mkdir()
    (left / "run.json").write_text("{}\n")
    found = launch_findings(store=s.store, source=s.source, home=s.home)
    places = {(f.kind, f.place) for f in found}
    assert ("run_material_readable", str(deep)) in places
    assert ("run_material_readable", str(left)) in places
    assert "not_established" not in {f.kind for f in found}
