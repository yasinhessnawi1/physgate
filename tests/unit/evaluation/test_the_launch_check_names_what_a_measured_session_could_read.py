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


@pytest.mark.parametrize("how", ["untracked", "ignored", "both"])
def test_files_git_does_not_track_or_ignores_in_the_source_s_own_directory_are_counted(
    s: SimpleNamespace, how: str
) -> None:
    # Every session reads the source's own directory, not only what a clone of it holds.
    if how in ("untracked", "both"):
        (s.source / "left.py").write_text("an earlier run's work, never committed\n")
        (s.source / "notes").mkdir()
        (s.source / "notes" / "a.txt").write_text("x\n")
    if how in ("ignored", "both"):
        (s.source / ".gitignore").write_text(".physgate/\n")
        _git(s.source, "add", ".gitignore")
        _git(s.source, "commit", "-q", "-m", "ignore")
        (s.source / ".physgate").mkdir()
        (s.source / ".physgate" / "scratch.txt").write_text("a session's leftover\n")
    code, lines = _check(s)
    assert code == 1, lines
    said = [line for line in lines if line.startswith("finding: source_files:")]
    assert len(said) == 1, lines
    if how in ("untracked", "both"):
        assert "2 files git does not track" in said[0], said
    if how in ("ignored", "both"):
        assert "1 file git ignores" in said[0], said
    # By kind and count alone: no file's name, nor anything it holds.
    for word in ("left.py", "a.txt", "scratch.txt", "earlier run", "leftover"):
        assert word not in "\n".join(lines), lines


def test_a_tracked_file_changed_in_the_source_is_counted_and_the_check_writes_nothing_there(
    s: SimpleNamespace,
) -> None:
    (s.source / "README.md").write_text("an earlier run's change\n")
    index = s.source / ".git" / "index"
    before = (index.read_bytes(), index.stat().st_mtime_ns)
    code, lines = _check(s)
    assert code == 1
    assert any(
        line.startswith("finding: source_files:") and "1 file the branch tracks, changed" in line
        for line in lines
    ), lines
    assert (index.read_bytes(), index.stat().st_mtime_ns) == before, "the check wrote the index"


def test_a_review_root_s_record_left_where_a_session_reads_is_named(s: SimpleNamespace) -> None:
    left = s.home / "old-reviews"
    left.mkdir()
    (left / "review_root.json").write_text("{}\n")
    code, lines = _check(s)
    assert code == 1
    assert f"finding: run_material_readable: {left}: it holds review_root.json" in lines


def test_a_linked_worktree_of_the_source_is_named(s: SimpleNamespace, outside_tmp: Path) -> None:
    # Detached: no second branch, so the worktree is the one finding.
    _git(s.source, "worktree", "add", "-q", "--detach", str(Path(outside_tmp) / "linked"))
    assert _kinds(s) == {"source_worktrees"}


@pytest.mark.parametrize("ref", ["a stash", "a note", "a remote branch"])
def test_a_reference_that_is_neither_a_branch_nor_a_tag_is_named(
    s: SimpleNamespace, ref: str
) -> None:
    if ref == "a stash":
        (s.source / "README.md").write_text("changed, then stashed\n")
        _git(s.source, "stash", "-q")
        named = "refs/stash"
    elif ref == "a note":
        _git(s.source, "notes", "add", "-m", "an earlier run's note")
        named = "refs/notes/commits"
    else:
        _git(s.source, "update-ref", "refs/remotes/origin/main", "HEAD")
        named = "refs/remotes/origin/main"
    code, lines = _check(s)
    assert code == 1
    assert any(line.endswith(f"it holds {named}") for line in lines), lines


def test_a_run_that_withholds_one_of_two_run_roots_is_named(
    s: SimpleNamespace, monkeypatch: pytest.MonkeyPatch
) -> None:
    from physgate.evaluation import launch_check

    other = s.home / "more-runs"
    other.mkdir()
    run = s.runs / "half-run"
    run.mkdir()
    (run / "run.json").write_text("{}\n")
    both = s.runs / "whole-run"
    both.mkdir()
    (both / "run.json").write_text("{}\n")
    named = {str(run): [str(s.runs)], str(both): [str(s.runs), str(other)]}
    monkeypatch.setattr(
        "physgate.orchestrator.run_config.load_run_config",
        lambda path: SimpleNamespace(withheld_whole=named[str(path.parent)]),
    )
    registered = {os.path.realpath(s.runs), os.path.realpath(other)}
    found = launch_check.withholding_findings([s.runs, other], registered)
    assert [(f.kind, f.place) for f in found] == [("run_not_withholding", str(run))]


def test_a_walk_past_its_bound_says_what_it_found_is_not_established(
    s: SimpleNamespace, monkeypatch: pytest.MonkeyPatch
) -> None:
    for n in range(20):
        (s.home / "many" / f"d{n}").mkdir(parents=True)
    monkeypatch.setattr("physgate.evaluation.launch_check.MAX_ENTRIES", 10)
    code, lines = _check(s)
    assert code == 1
    assert any(line.startswith("finding: not_established:") for line in lines), lines


@pytest.mark.skipif(os.geteuid() == 0, reason="root lists a folder of any mode")
def test_a_folder_the_walk_cannot_list_is_named_as_not_established(s: SimpleNamespace) -> None:
    locked = s.home / "locked"
    (locked / "run-8").mkdir(parents=True)
    (locked / "run-8" / "run.json").write_text("{}\n")
    locked.chmod(0)
    try:
        code, lines = _check(s)
    finally:
        locked.chmod(0o700)
    assert code == 1
    assert f"finding: not_established: {locked}: it cannot be listed by this user" in lines, lines


def test_material_beneath_the_standing_review_root_is_no_finding(s: SimpleNamespace) -> None:
    from physgate.reviewers.places import standing_root

    left = standing_root(s.home) / "r0123456789ab"
    left.mkdir(parents=True)
    (left / "review_root.json").write_text("{}\n")
    assert "run_material_readable" not in _kinds(s)


def test_run_material_in_the_machine_s_other_place_is_named(
    s: SimpleNamespace, outside_tmp: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    machine = Path(os.path.realpath(outside_tmp)) / "var-tmp"
    (machine / "left-run").mkdir(parents=True)
    (machine / "left-run" / "run.json").write_text("{}\n")
    monkeypatch.setattr("physgate.evaluation.launch_check.MACHINE_PLACES", (machine,))
    code, lines = _check(s)
    assert code == 1
    assert f"finding: run_material_readable: {machine / 'left-run'}: it holds run.json" in lines


def test_a_folder_at_the_store_s_top_outside_every_role_s_root_is_walked(
    s: SimpleNamespace, outside_tmp: Path
) -> None:
    # A measured session is refused its roles' roots in the store, not the store: a stray folder
    # at its top is read like any other place.
    stray = s.store / "notes" / "run-6"
    stray.mkdir(parents=True)
    (stray / "run.json").write_text("{}\n")
    code, lines = _check(s)
    assert code == 1
    assert f"finding: run_material_readable: {stray}: it holds run.json" in lines, lines
    # The same, with the store outside the home: walked as a place of its own.
    away = Path(os.path.realpath(outside_tmp)) / "store-away"
    s.store.rename(away)
    s.store = away
    code, lines = _check(s)
    assert f"finding: run_material_readable: {away / 'notes' / 'run-6'}: it holds run.json" in lines
