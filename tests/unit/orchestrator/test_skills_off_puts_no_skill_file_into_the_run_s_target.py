"""Under ``skills: off`` no role's skill file is put into the run's target, by any route.

A role session reads its curated content in its own worktree, which checks out the run branch;
the run branch starts at the specification commit, which decomposition writes with the curated
library in it. Under ``skills: off`` decomposition puts only the standards files there, so no
worktree of the run, no checkout of the orchestrator's integration worktree and no object the run
writes holds a skill file. A target that already holds one is refused before anything is written,
with its own reason: a role session's shell reads files, and the store's objects are files. Judged
by path in every commit any ref, reflog entry or stash reaches, the start commit's history among
them; by presence for a tree or blob a ref names directly and for any object none of those
reaches; by content for the library's bytes; and in every working tree of the target, its own and
each linked one, by where a file sits, whatever git tracks or ignores there.

The specification commit then differs between the arms by exactly the skill files. The plan's
bytes are the same under both, and ``skills: on`` puts into the target what it always put there.
"""

from __future__ import annotations

import json
import subprocess
from pathlib import Path
from typing import Any

import pytest
from design_review_rig import ROLES, config, outcome, target_repo
from knowledge_fixture import FIXTURE_ROLES, fixture_text, write_fixture
from orch_helpers import CLEAN_HARNESS

from physgate.knowledge import loader
from physgate.orchestrator.decompose import start_run
from physgate.orchestrator.exceptions import DecompositionError
from physgate.orchestrator.merge import RunGit
from physgate.orchestrator.run_config import load_run_config

#: Where the series writer goes, beside the library, in every run.
SERIES_WRITER = ".physgate/lib/series_writer.py"
#: The words the refusal of a target that already holds a skill file says, under the arm.
REFUSAL = "under skills: off"


def _git(cwd: Path, *argv: str, stdin: str | None = None) -> str:
    done = subprocess.run(
        ["git", "-c", "user.email=t@example.invalid", "-c", "user.name=t", *argv],
        cwd=cwd,
        input=stdin,
        check=True,
        capture_output=True,
        text=True,
    )
    return done.stdout


def _arm(skills: str) -> dict[str, Any]:
    return {"skills": skills, "ablation": skills == "off", "harness": CLEAN_HARNESS}


def _library(root: Path) -> Path:
    library = root / "library"
    write_fixture(library, (*FIXTURE_ROLES, *ROLES))
    return library


def _start(root: Path, skills: str, repo: Path | None = None) -> tuple[Path, Path, Path]:
    """A run started from the rig's plan under ``skills``: its directory, target and library."""
    repo = repo or target_repo(root)
    library = _library(root)
    run_dir = root / "run"
    start_run(
        outcome(run_dir),
        config=config(repo, "off", **_arm(skills)),
        run_dir=run_dir,
        target_repo=repo,
        library=library,
    ).close()
    return run_dir, repo, library


def _decomposed(run_dir: Path) -> dict[str, Any]:
    for raw in (run_dir / "events.jsonl").read_text().splitlines():
        line = json.loads(raw)
        if line["kind"] == "decomposed":
            return dict(line)
    raise AssertionError("the run recorded no decomposition")


def _tree(repo: Path, commit: str) -> dict[str, tuple[str, str]]:
    """Every file of ``commit``, by path: its mode and its object id."""
    entries: dict[str, tuple[str, str]] = {}
    for item in _git(repo, "ls-tree", "-r", "-z", "--full-tree", commit).split("\0"):
        if item:
            meta, name = item.split("\t", 1)
            mode, _, oid = meta.split()
            entries[name] = (mode, oid)
    return entries


def _skills_of(roles: tuple[str, ...]) -> set[str]:
    return {(loader.DEFAULT_ROOT / role / loader.SKILL_NAME).as_posix() for role in roles}


def _skill_files_in(directory: Path) -> list[Path]:
    return sorted(p for p in directory.rglob(loader.SKILL_NAME) if ".git" not in p.parts)


def _subtasks(run_dir: Path) -> list[str]:
    return [json.loads(raw)["id"] for raw in (run_dir / "ledger.jsonl").read_text().splitlines()]


def _blob_id(repo: Path, path: Path) -> str:
    return _git(repo, "hash-object", "--no-filters", str(path)).strip()


def _in_store(repo: Path, oid: str) -> bool:
    listed = _git(repo, "cat-file", "--batch-check", stdin=oid + "\n")
    return not listed.strip().endswith("missing")


# -- what the run writes ----------------------------------------------------------------------


def test_under_skills_off_the_specification_commit_holds_the_standards_and_no_skill_file(
    tmp_path: Path,
) -> None:
    run_dir, repo, library = _start(tmp_path, "off")
    tree = _tree(repo, _decomposed(run_dir)["spec_commit"])
    held = sorted(name for name in tree if Path(name).name == loader.SKILL_NAME)
    assert held == [], f"under skills: off the specification commit holds {held}"
    for role in ROLES:
        for relative in loader.always_loaded(role)[:2]:
            assert tree[relative.as_posix()][1] == _blob_id(repo, library / relative), relative


def test_the_specification_commit_differs_between_the_arms_by_exactly_the_skill_files(
    tmp_path: Path,
) -> None:
    on_dir, on_repo, _ = _start(tmp_path / "on", "on")
    off_dir, off_repo, _ = _start(tmp_path / "off", "off")
    on = _tree(on_repo, _decomposed(on_dir)["spec_commit"])
    off = _tree(off_repo, _decomposed(off_dir)["spec_commit"])
    assert set(on) - set(off) == _skills_of(ROLES), "the arms differ by more than the skill files"
    assert set(off) <= set(on), "skills: off puts a file into the target that on does not"
    assert {name: on[name] for name in off} == off, "a file both arms hold differs between them"


def test_with_skills_on_the_specification_commit_holds_every_planned_role_s_library(
    tmp_path: Path,
) -> None:
    run_dir, repo, library = _start(tmp_path, "on")
    tree = _tree(repo, _decomposed(run_dir)["spec_commit"])
    curated = {p for role in ROLES for p in loader.always_loaded(role)}
    for relative in curated:
        assert tree[relative.as_posix()] == ("100644", _blob_id(repo, library / relative))
    knowledge = {name for name in tree if name.startswith(f"{loader.DEFAULT_ROOT.as_posix()}/")}
    assert knowledge == {p.as_posix() for p in curated}
    assert SERIES_WRITER in tree


def test_the_plan_and_its_specifications_are_the_same_bytes_under_both_arms(
    tmp_path: Path,
) -> None:
    on_dir, on_repo, _ = _start(tmp_path / "on", "on")
    off_dir, off_repo, _ = _start(tmp_path / "off", "off")
    on, off = _decomposed(on_dir), _decomposed(off_dir)
    assert on["plan_sha256"] == off["plan_sha256"]
    assert on["interface_nodes"] == off["interface_nodes"]
    assert (on_dir / "ledger.jsonl").read_bytes() == (off_dir / "ledger.jsonl").read_bytes()
    on_tree, off_tree = _tree(on_repo, on["spec_commit"]), _tree(off_repo, off["spec_commit"])
    specs = [name for name in on_tree if name.startswith(".physgate/")]
    assert specs, "the specification commit holds no specification"
    assert [on_tree[n] for n in specs] == [off_tree.get(n) for n in specs]


# -- no copy in any worktree, checkout or object -------------------------------------------------


def test_under_skills_off_no_worktree_of_the_run_holds_a_skill_file(tmp_path: Path) -> None:
    run_dir, repo, _ = _start(tmp_path, "off")
    run = RunGit(repo=repo, run_dir=run_dir, run_id="run-1")
    first, second = _subtasks(run_dir)
    opened = [run.integration, run.open_subtask(first), run.open_subtask(second)]
    # A sibling of the first subtask's own, as a reopen makes one.
    opened.append(run.open_subtask(first, reopen=1))
    for worktree in opened:
        found = _skill_files_in(worktree)
        assert found == [], f"under skills: off the worktree {worktree.name} holds {found}"


def test_under_skills_off_no_object_of_the_target_holds_a_skill_file_s_bytes(
    tmp_path: Path,
) -> None:
    run_dir, repo, library = _start(tmp_path, "off")
    RunGit(repo=repo, run_dir=run_dir, run_id="run-1").open_subtask(_subtasks(run_dir)[0])
    for name in sorted(_skills_of(ROLES)):
        oid = _blob_id(repo, library / name)
        assert not _in_store(repo, oid), f"under skills: off the target's store holds {name}"


def test_with_skills_on_the_store_holds_the_skill_file_as_it_always_did(tmp_path: Path) -> None:
    _, repo, library = _start(tmp_path, "on")
    for name in sorted(_skills_of(ROLES)):
        assert _in_store(repo, _blob_id(repo, library / name)), name


def test_a_resumed_skills_off_run_puts_no_skill_file_back(tmp_path: Path) -> None:
    run_dir, repo, _ = _start(tmp_path, "off")
    first, second = _subtasks(run_dir)
    RunGit(repo=repo, run_dir=run_dir, run_id="run-1").open_subtask(first)
    # The process is gone. A resume reads the run from its records alone: its configuration says
    # the arm, and its worktrees are opened again, or for the first time, from the run branch.
    recorded = load_run_config(run_dir / "run.json")
    assert recorded.skills == "off"
    again = RunGit(repo=repo, run_dir=run_dir, run_id=recorded.run_id)
    opened = [again.open_subtask(first), again.open_subtask(second), again.open_subtask(first, 1)]
    for worktree in [again.integration, *opened]:
        assert _skill_files_in(worktree) == [], f"a resume put a skill file into {worktree.name}"
    spec = Path(json.loads((run_dir / "ledger.jsonl").read_text().splitlines()[0])["spec_path"])
    given = loader.session_reading("control", spec, skills=recorded.skills)
    skill = loader.DEFAULT_ROOT / "control" / loader.SKILL_NAME
    assert skill not in given.required and skill not in given.always_loaded


# -- a target that already holds one ------------------------------------------------------------


def _target_with(root: Path, write: Any, *, keep: bool = True) -> Path:  # noqa: ANN401
    """The rig's target, with a commit of ``write`` on it; deleted again unless ``keep``."""
    repo = target_repo(root)
    names = write(repo)
    _git(repo, "add", "-A")
    _git(repo, "commit", "-q", "-m", "the target's own content")
    if not keep:
        _git(repo, "rm", "-q", *names)
        _git(repo, "commit", "-q", "-m", "removed again")
        # And a commit after it, so the start commit itself touches no skill file.
        (repo / "README.md").write_text("target, later\n")
        _git(repo, "commit", "-q", "-am", "later")
    return repo


def _the_library_s_skill_file(repo: Path) -> list[str]:
    name = f"knowledge/{ROLES[0]}/skill.md"
    (repo / name).parent.mkdir(parents=True)
    write_fixture(repo, (ROLES[0],))
    return [name]


def _another_skill_file(repo: Path) -> list[str]:
    name = "knowledge/elsewhere/skill.md"
    (repo / name).parent.mkdir(parents=True)
    (repo / name).write_text("a skill file of the target's own\n")
    return [name]


def _a_skill_file_by_another_case(repo: Path) -> list[str]:
    name = "Knowledge/Control/Skill.md"
    (repo / name).parent.mkdir(parents=True)
    (repo / name).write_text("the same file, on a file system that ignores case\n")
    return [name]


def _refused(root: Path, repo: Path) -> str:
    with pytest.raises(DecompositionError) as caught:
        _start(root, "off", repo)
    return str(caught.value)


def _nothing_written(root: Path, repo: Path) -> None:
    assert not (root / "run" / "run.json").exists(), "a refused run left its record"
    assert not (root / "run" / "worktrees").exists(), "a refused run left a worktree"
    assert "physgate/" not in _git(repo, "branch", "--list", "physgate/*")


@pytest.mark.parametrize(
    "write",
    [_the_library_s_skill_file, _another_skill_file, _a_skill_file_by_another_case],
    ids=lambda f: f.__name__[1:],
)
def test_under_skills_off_a_target_whose_start_commit_holds_a_skill_file_is_refused(
    tmp_path: Path, write: Any
) -> None:
    repo = _target_with(tmp_path, write)
    said = _refused(tmp_path, repo)
    assert REFUSAL in said, f"the refusal does not say why: {said}"
    _nothing_written(tmp_path, repo)


def test_under_skills_off_a_target_whose_history_held_a_skill_file_is_refused(
    tmp_path: Path,
) -> None:
    repo = _target_with(tmp_path, _another_skill_file, keep=False)
    assert _skill_files_in(repo) == []  # gone from the commit the run starts from
    assert REFUSAL in _refused(tmp_path, repo)
    _nothing_written(tmp_path, repo)


def test_under_skills_off_a_target_whose_store_holds_the_library_s_skill_bytes_is_refused(
    tmp_path: Path,
) -> None:
    # An earlier run's branch, or any other: its objects are files a session's shell reads.
    repo = target_repo(tmp_path)
    _git(repo, "checkout", "-q", "-b", "elsewhere")
    _the_library_s_skill_file(repo)
    _git(repo, "add", "-A")
    _git(repo, "commit", "-q", "-m", "another branch's content")
    _git(repo, "checkout", "-q", "master")
    assert _skill_files_in(repo) == []
    assert REFUSAL in _refused(tmp_path, repo)
    _nothing_written(tmp_path, repo)


#: Skill content of no version the library holds: what an earlier run, or a person, could have
#: left in the target. Its bytes match no blob id the check could compute in advance.
OTHER_BYTES = "an older version of a role's skill, of no bytes the library holds now\n"
OTHER_NAME = f"knowledge/{ROLES[0]}/skill.md"


def _write_other(repo: Path, name: str = OTHER_NAME) -> None:
    (repo / name).parent.mkdir(parents=True, exist_ok=True)
    (repo / name).write_text(OTHER_BYTES)


def _refusal(root: Path, repo: Path) -> DecompositionError:
    with pytest.raises(DecompositionError) as caught:
        _start(root, "off", repo)
    assert REFUSAL in str(caught.value), f"the refusal does not say why: {caught.value}"
    return caught.value


def _nowhere_at_the_start(repo: Path) -> None:
    """The start commit's own history holds no skill file: only another route reaches one."""
    assert _skill_files_in(repo) == []
    history = _git(repo, "log", "--format=%H", "master", "--", ":(icase)knowledge/*/skill.md")
    assert history.strip() == "", "the row's start commit already reaches a skill file"


def test_under_skills_off_a_skill_file_of_other_bytes_on_a_side_branch_is_refused(
    tmp_path: Path,
) -> None:
    repo = target_repo(tmp_path)
    _git(repo, "checkout", "-q", "-b", "elsewhere")
    _write_other(repo)
    _git(repo, "add", "-A")
    _git(repo, "commit", "-q", "-m", "another branch's content")
    _git(repo, "checkout", "-q", "master")
    _nowhere_at_the_start(repo)
    refused = _refusal(tmp_path, repo)
    assert refused.context.get("where") == "refs", refused.context
    _nothing_written(tmp_path, repo)


def test_under_skills_off_a_skill_file_under_another_ref_namespace_is_refused(
    tmp_path: Path,
) -> None:
    # As an earlier run's own branches would be, under a namespace no branch listing shows.
    repo = target_repo(tmp_path)
    _write_other(repo, "Knowledge/Other/SKILL.md")
    _git(repo, "add", "-A")
    _git(repo, "commit", "-q", "-m", "an earlier run's content")
    _git(repo, "update-ref", "refs/runs/earlier/subtask", "HEAD")
    _git(repo, "reset", "-q", "--hard", "HEAD~1")
    _git(repo, "reflog", "expire", "--expire=now", "--all")
    _nowhere_at_the_start(repo)
    refused = _refusal(tmp_path, repo)
    assert refused.context.get("where") == "refs", refused.context


def test_under_skills_off_a_skill_file_only_in_the_reflog_is_refused(tmp_path: Path) -> None:
    repo = target_repo(tmp_path)
    _write_other(repo)
    _git(repo, "add", "-A")
    _git(repo, "commit", "-q", "-m", "committed, then taken back")
    _git(repo, "reset", "-q", "--hard", "HEAD~1")
    _nowhere_at_the_start(repo)
    assert "taken back" in _git(repo, "log", "-g", "--format=%s", "master")
    refused = _refusal(tmp_path, repo)
    assert refused.context.get("where") == "refs", refused.context


@pytest.mark.parametrize("older", [False, True], ids=["the latest stash", "an older stash"])
def test_under_skills_off_a_skill_file_in_a_stash_is_refused(tmp_path: Path, older: bool) -> None:
    repo = target_repo(tmp_path)
    _write_other(repo)
    _git(repo, "add", "-A")
    _git(repo, "stash", "push", "-q", "-m", "a skill file put aside")
    if older:
        # Another stash on top: the skill's is then in the stash's reflog only.
        (repo / "README.md").write_text("target, changed\n")
        _git(repo, "stash", "push", "-q", "-m", "something else")
    _nowhere_at_the_start(repo)
    refused = _refusal(tmp_path, repo)
    assert refused.context.get("where") == "refs", refused.context


def test_under_skills_off_skill_content_in_an_object_no_ref_reaches_is_refused(
    tmp_path: Path,
) -> None:
    # A loose object nothing names: its path is gone, so only its presence can be judged.
    repo = target_repo(tmp_path)
    _git(repo, "hash-object", "-w", "--stdin", stdin=OTHER_BYTES)
    _nowhere_at_the_start(repo)
    refused = _refusal(tmp_path, repo)
    assert refused.context.get("where") == "unreachable objects", refused.context
    _nothing_written(tmp_path, repo)


def test_under_skills_off_a_dropped_stash_holding_a_skill_file_is_refused(tmp_path: Path) -> None:
    repo = target_repo(tmp_path)
    _write_other(repo)
    _git(repo, "add", "-A")
    _git(repo, "stash", "push", "-q", "-m", "put aside")
    _git(repo, "stash", "drop", "-q")
    _nowhere_at_the_start(repo)
    refused = _refusal(tmp_path, repo)
    assert refused.context.get("where") == "unreachable objects", refused.context


def test_under_skills_off_the_library_s_skill_bytes_under_another_path_are_refused(
    tmp_path: Path,
) -> None:
    # A renamed copy of the skill as the library holds it now: no path says what it is, its
    # bytes do.
    repo = target_repo(tmp_path)
    copy = repo / "notes" / "copied.md"
    copy.parent.mkdir()
    copy.write_text(fixture_text(loader.DEFAULT_ROOT / ROLES[0] / loader.SKILL_NAME))
    _git(repo, "add", "-A")
    _git(repo, "commit", "-q", "-m", "a note")
    refused = _refusal(tmp_path, repo)
    assert refused.context.get("where") == "object store", refused.context


def test_under_skills_off_a_fresh_clone_of_a_target_with_history_starts(tmp_path: Path) -> None:
    # A target with branches, a stash and a history of its own, none of it a skill file, cloned
    # without sharing its object files: nothing is refused.
    source = target_repo(tmp_path / "source")
    (source / "modules" / "note.md").write_text("a note\n")
    _git(source, "add", "-A")
    _git(source, "commit", "-q", "-m", "a second commit")
    _git(source, "branch", "side", "HEAD~1")
    _git(tmp_path, "clone", "-q", "--no-local", str(source), str(tmp_path / "target"))
    repo = tmp_path / "target"
    (repo / "README.md").write_text("target, changed\n")
    _git(repo, "stash", "push", "-q", "-m", "an ordinary stash")
    run_dir, _, _ = _start(tmp_path, "off", repo)
    assert _decomposed(run_dir)["subtasks"] == len(ROLES)


def test_under_skills_on_a_target_holding_the_library_s_own_bytes_starts_as_it_always_did(
    tmp_path: Path,
) -> None:
    repo = _target_with(tmp_path, _the_library_s_skill_file)
    run_dir, _, _ = _start(tmp_path, "on", repo)
    assert _decomposed(run_dir)["subtasks"] == len(ROLES)


def test_the_command_refuses_such_a_target_before_the_one_model_call(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    from test_the_physgate_command_starts_and_decides import (  # noqa: PLC0415
        PARAMS,
        _decompose_args,
    )

    from physgate.cli import main  # noqa: PLC0415
    from physgate.orchestrator import cli  # noqa: PLC0415
    from physgate.oslayer.probe import Present  # noqa: PLC0415

    repo = _target_with(tmp_path, _another_skill_file)
    layer = Present(mechanism="seatbelt", claude_version="2.1.301")
    the_config = config(repo, "off", **_arm("off"), os_layer=layer)
    # The run's own measurements and requirements are other rows' to judge: this row is the
    # target's. No binary is on the path, so a model call would fail on another reason.
    monkeypatch.setattr(cli, "_config", lambda *_a: the_config)
    monkeypatch.setattr(cli, "refusals", lambda *_a: [])
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-ant-test-dummy-not-a-credential")
    monkeypatch.setenv("PATH", "/nonexistent")
    monkeypatch.delenv("PHYSGATE_CLAUDE_BIN", raising=False)
    argv = _decompose_args(tmp_path, PARAMS)
    argv[argv.index("--target") + 1] = str(repo)
    assert main(argv) == 2
    said = json.loads(capsys.readouterr().err.strip().splitlines()[-1])
    assert REFUSAL in said["error"], f"the command did not refuse the target first: {said}"
    assert not (tmp_path / "run").exists(), "the command wrote a run for a refused target"


# -- tags, and what a ref names that is no commit ------------------------------------------------


def _starts(root: Path, repo: Path, why: str) -> None:
    """The run starts under ``skills: off``; a refusal fails on an assertion that says ``why``."""
    try:
        run_dir, _, _ = _start(root, "off", repo)
    except DecompositionError as exc:
        raise AssertionError(f"{why}: {exc} {exc.context}") from None
    assert _decomposed(run_dir)["subtasks"] == len(ROLES)


def _annotated(repo: Path) -> None:
    _git(repo, "tag", "-a", "v1", "-m", "a release")


def _a_tag_of_a_tag(repo: Path) -> None:
    _git(repo, "tag", "-a", "v1", "-m", "a release")
    _git(repo, "tag", "-a", "v1-signed-off", "-m", "the release, tagged again", "v1")


def _retagged_with_its_reflog(repo: Path) -> None:
    # A tag moved, its old object kept by the tag's own reflog: git writes one for a tag only
    # when every ref update is logged.
    _git(repo, "config", "core.logAllRefUpdates", "always")
    _git(repo, "tag", "-a", "v1", "-m", "a release")
    _git(repo, "tag", "-a", "-f", "v1", "-m", "the release, tagged again")


@pytest.mark.parametrize(
    "tag",
    [_annotated, _a_tag_of_a_tag, _retagged_with_its_reflog],
    ids=lambda f: f.__name__[1:],
)
def test_under_skills_off_an_annotated_tag_on_a_clean_target_starts(
    tmp_path: Path, tag: Any
) -> None:
    repo = target_repo(tmp_path)
    tag(repo)
    _starts(tmp_path, repo, "a tag object a ref names is judged as an object no ref reaches")


def test_under_skills_off_an_annotated_tag_does_not_hide_an_object_no_ref_reaches(
    tmp_path: Path,
) -> None:
    repo = target_repo(tmp_path)
    _annotated(repo)
    _git(repo, "hash-object", "-w", "--stdin", stdin=OTHER_BYTES)
    refused = _refusal(tmp_path, repo)
    assert refused.context.get("where") == "unreachable objects", refused.context
    _nothing_written(tmp_path, repo)


def _tree_holding(repo: Path, name: str, data: str) -> str:
    """A tree, written to the store and named by no commit, holding ``data`` at ``name``."""
    oid = _git(repo, "hash-object", "-w", "--stdin", stdin=data).strip()
    *dirs, leaf = name.split("/")
    entry = f"100644 blob {oid}\t{leaf}\n"
    for directory in reversed(dirs):
        oid = _git(repo, "mktree", stdin=entry).strip()
        entry = f"040000 tree {oid}\t{directory}\n"
    return _git(repo, "mktree", stdin=entry).strip()


#: A tag names its object as annotated or as lightweight: both are refs to judge by.
TAG_KINDS = {
    "annotated": ("tag", "-a", "-m", "a tree, tagged"),
    "lightweight": ("tag",),
}


@pytest.mark.parametrize("kind", sorted(TAG_KINDS))
def test_under_skills_off_a_tag_naming_a_tree_that_holds_a_skill_file_is_refused(
    tmp_path: Path, kind: str
) -> None:
    repo = target_repo(tmp_path)
    tree = _tree_holding(repo, "Knowledge/Other/Skill.md", OTHER_BYTES)
    _git(repo, *TAG_KINDS[kind], "a-tree", tree)
    _nowhere_at_the_start(repo)
    refused = _refusal(tmp_path, repo)
    assert refused.context.get("where") == "a tree a ref names", refused.context
    _nothing_written(tmp_path, repo)


def _refused_for(root: Path, repo: Path, rule: str) -> DecompositionError:
    """The target's refusal under ``skills: off``; a start fails on an assertion of ``rule``."""
    try:
        _start(root, "off", repo)
    except DecompositionError as exc:
        assert REFUSAL in str(exc), f"the refusal does not say why: {exc}"
        return exc
    raise AssertionError(f"under skills: off {rule}, and the run started")


#: The rule for a tree a ref names: it has no path of its own, so it is refused whatever it holds.
TREE_RULE = "a tree a ref names directly is refused, since it has no path to judge it by"


@pytest.mark.parametrize("kind", sorted(TAG_KINDS))
def test_under_skills_off_a_tag_naming_a_tree_with_a_skill_file_at_its_root_is_refused(
    tmp_path: Path, kind: str
) -> None:
    # The tree is a role's directory itself: skill.md at its own root, no knowledge/ above it.
    repo = target_repo(tmp_path)
    tree = _tree_holding(repo, "skill.md", OTHER_BYTES)
    _git(repo, *TAG_KINDS[kind], "a-tree", tree)
    _nowhere_at_the_start(repo)
    refused = _refused_for(tmp_path, repo, TREE_RULE)
    assert refused.context.get("where") == "a tree a ref names", refused.context
    _nothing_written(tmp_path, repo)


@pytest.mark.parametrize("kind", sorted(TAG_KINDS))
def test_under_skills_off_a_tag_naming_a_tree_of_harmless_files_is_refused_too(
    tmp_path: Path, kind: str
) -> None:
    # Pinned: the rule judges no tree a ref names by what it holds, so a harmless one is refused.
    repo = target_repo(tmp_path)
    tree = _tree_holding(repo, "notes/plan.md", "a plan\n")
    _git(repo, *TAG_KINDS[kind], "a-tree", tree)
    refused = _refused_for(tmp_path, repo, TREE_RULE)
    assert refused.context.get("where") == "a tree a ref names", refused.context
    _nothing_written(tmp_path, repo)


def test_under_skills_off_a_ref_naming_the_start_commit_s_own_tree_is_judged_with_it(
    tmp_path: Path,
) -> None:
    # A ref to the root tree of a commit another ref names is judged by that commit's paths.
    repo = target_repo(tmp_path)
    _git(repo, "tag", "root-tree", "HEAD^{tree}")
    _starts(tmp_path, repo, "a ref to the start commit's own tree is refused")


@pytest.mark.parametrize("kind", sorted(TAG_KINDS))
def test_under_skills_off_a_tag_naming_a_file_s_content_is_refused(
    tmp_path: Path, kind: str
) -> None:
    # A blob a ref names directly has no path, so its content cannot be told from a skill file.
    repo = target_repo(tmp_path)
    blob = _git(repo, "hash-object", "-w", "--stdin", stdin=OTHER_BYTES).strip()
    _git(repo, *TAG_KINDS[kind], "a-blob", blob)
    _nowhere_at_the_start(repo)
    refused = _refusal(tmp_path, repo)
    assert refused.context.get("where") == "a blob a ref names", refused.context
    _nothing_written(tmp_path, repo)


# -- the target's working trees --------------------------------------------------------------------


#: The rule for a working tree: a session can read the target's working directory, so a file there
#: is judged by where it sits, tracked or not, ignored or not.
WORKING_RULE = (
    "a working tree of the target holding a skill file, or a link where one goes, is refused"
)


def _untracked(repo: Path, name: str = "knowledge/elsewhere/skill.md") -> None:
    (repo / name).parent.mkdir(parents=True, exist_ok=True)
    (repo / name).write_text("a skill file no commit holds\n")


def _in_working_tree(refused: DecompositionError, path: str) -> None:
    assert refused.context.get("where") == "a working tree", refused.context
    assert refused.context.get("path") == path, refused.context


def test_under_skills_off_an_untracked_skill_file_in_the_target_is_refused(
    tmp_path: Path,
) -> None:
    repo = target_repo(tmp_path)
    _untracked(repo)
    assert "knowledge/" in _git(repo, "status", "--porcelain", "--untracked-files=all")
    refused = _refused_for(tmp_path, repo, WORKING_RULE)
    _in_working_tree(refused, "knowledge/elsewhere/skill.md")
    _nothing_written(tmp_path, repo)


def test_under_skills_off_an_ignored_skill_file_of_another_letter_case_is_refused(
    tmp_path: Path,
) -> None:
    repo = target_repo(tmp_path)
    (repo / ".gitignore").write_text("knowledge/\n")
    _git(repo, "add", "-A")
    _git(repo, "commit", "-q", "-m", "ignore the knowledge directory")
    _untracked(repo, "knowledge/control/Skill.MD")
    # git itself reports nothing there: only a walk that honours no ignore rule finds it.
    assert _git(repo, "status", "--porcelain", "--untracked-files=all").strip() == ""
    refused = _refused_for(tmp_path, repo, WORKING_RULE)
    _in_working_tree(refused, "knowledge/control/Skill.MD")


def _link_at_the_skill_file(repo: Path, outside: Path) -> str:
    (repo / "knowledge" / "control").mkdir(parents=True)
    (repo / "knowledge" / "control" / "skill.md").symlink_to(outside / "notes.md")
    return "knowledge/control/skill.md"


def _link_at_a_role_s_directory(repo: Path, outside: Path) -> str:
    (repo / "knowledge").mkdir()
    (repo / "knowledge" / "control").symlink_to(outside, target_is_directory=True)
    return "knowledge/control"


def _link_at_the_knowledge_directory(repo: Path, outside: Path) -> str:
    (repo / "knowledge").symlink_to(outside, target_is_directory=True)
    return "knowledge"


@pytest.mark.parametrize(
    "link",
    [_link_at_the_skill_file, _link_at_a_role_s_directory, _link_at_the_knowledge_directory],
    ids=lambda f: f.__name__[1:],
)
def test_under_skills_off_a_link_where_a_skill_file_or_its_directory_goes_is_refused(
    tmp_path: Path, link: Any
) -> None:
    # A link could name a skill file anywhere; what it names now holds none, and is not followed.
    outside = tmp_path / "outside"
    outside.mkdir()
    (outside / "notes.md").write_text("notes\n")
    repo = target_repo(tmp_path)
    path = link(repo, outside)
    refused = _refused_for(tmp_path, repo, WORKING_RULE)
    _in_working_tree(refused, path)


def test_under_skills_off_a_skill_file_in_a_linked_worktree_of_the_target_is_refused(
    tmp_path: Path,
) -> None:
    repo = target_repo(tmp_path)
    other = tmp_path / "other"
    _git(repo, "worktree", "add", "-q", "-b", "other", str(other))
    _untracked(other)
    assert _skill_files_in(repo) == []
    refused = _refused_for(tmp_path, repo, WORKING_RULE)
    _in_working_tree(refused, "knowledge/elsewhere/skill.md")
    assert Path(refused.context.get("worktree", "")).resolve() == other.resolve(), refused.context


def test_under_skills_off_a_working_tree_with_standards_files_only_starts(tmp_path: Path) -> None:
    repo = target_repo(tmp_path)
    _untracked(repo, f"knowledge/{ROLES[0]}/standards.md")
    _untracked(repo, "knowledge/README.md")
    (repo / "notes" / "skill.md").parent.mkdir()
    (repo / "notes" / "skill.md").write_text("a skill file outside the knowledge directory\n")
    _starts(tmp_path, repo, "a working tree with standards files only is refused")


def test_under_skills_off_a_skill_file_s_backup_copy_in_a_working_tree_starts(
    tmp_path: Path,
) -> None:
    # Pinned: skill.md.bak is not knowledge/*/skill.md, so the rule does not match it; a limit.
    repo = target_repo(tmp_path)
    _untracked(repo, "knowledge/control/skill.md.bak")
    _starts(tmp_path, repo, "a file that only begins with a skill file's name is refused")


def test_under_skills_off_the_run_s_own_worktrees_pass_the_check_and_the_run_resumes(
    tmp_path: Path,
) -> None:
    from physgate.knowledge.library import read_library, skill_files  # noqa: PLC0415
    from physgate.orchestrator import decompose  # noqa: PLC0415

    run_dir, repo, library = _start(tmp_path, "off")
    first, second = _subtasks(run_dir)
    run = RunGit(repo=repo, run_dir=run_dir, run_id="run-1")
    opened = [run.integration, run.open_subtask(first), run.open_subtask(second)]
    listed = _git(repo, "worktree", "list", "--porcelain")
    for worktree in opened:
        assert f"worktree {worktree.resolve()}" in listed, (
            f"{worktree} is no worktree of the target"
        )
    skills = skill_files(read_library(library, ROLES))
    head = _git(repo, "rev-parse", "master").strip()

    def accepted(why: str) -> None:
        try:
            decompose.require_no_skill_file(repo, head, skills)
        except DecompositionError as exc:
            raise AssertionError(f"{why}: {exc} {exc.context}") from None

    accepted("the check refuses the run's own worktrees")
    # The process is gone; a resume opens the run's worktrees again from its records alone.
    recorded = load_run_config(run_dir / "run.json")
    again = RunGit(repo=repo, run_dir=run_dir, run_id=recorded.run_id)
    again.open_subtask(first)
    again.open_subtask(first, 1)
    accepted("the check refuses the worktrees a resume opened")
    # And a second run of the arm starts on the same target, through start_run, the first's
    # worktrees still there.
    later = tmp_path / "later"
    try:
        start_run(
            outcome(later),
            config=config(repo, "off", **_arm("off"), run_id="run-2"),
            run_dir=later,
            target_repo=repo,
            library=library,
        ).close()
    except DecompositionError as exc:
        raise AssertionError(f"a second off run is refused: {exc} {exc.context}") from None
    assert _decomposed(later)["subtasks"] == len(ROLES)


# -- a target that is not a complete repository with a working tree ------------------------------


def _source(root: Path) -> Path:
    """A target with two commits, served by file transport with filters allowed."""
    source = target_repo(root / "source")
    (source / "modules" / "note.md").write_text("a note\n")
    _git(source, "add", "-A")
    _git(source, "commit", "-q", "-m", "a second commit")
    (source / "modules" / "note.md").write_text("a note, changed\n")
    _git(source, "commit", "-q", "-am", "a third commit")
    _git(source, "config", "uploadpack.allowFilter", "true")
    return source


def _incomplete(root: Path, *clone: str) -> Path:
    source = _source(root)
    _git(root, "clone", "-q", "--no-local", *clone, f"file://{source}", str(root / "target"))
    return root / "target"


def test_under_skills_off_a_bare_target_is_refused_with_what_to_do(tmp_path: Path) -> None:
    repo = _incomplete(tmp_path, "--bare")
    refused = _refusal(tmp_path, repo)
    assert refused.context.get("where") == "a bare repository", refused.context
    assert "git clone --no-local" in str(refused), str(refused)


def test_under_skills_off_a_shallow_target_is_refused_with_what_to_do(tmp_path: Path) -> None:
    repo = _incomplete(tmp_path, "--depth", "1")
    refused = _refusal(tmp_path, repo)
    assert refused.context.get("where") == "a shallow clone", refused.context
    assert "git clone --no-local" in str(refused), str(refused)
    _nothing_written(tmp_path, repo)


def test_under_skills_off_a_partial_target_is_refused_without_fetching(tmp_path: Path) -> None:
    repo = _incomplete(tmp_path, "--filter=blob:none")
    # Any fetch from the promisor remote would run this program first, and leave its mark.
    mark = tmp_path / "fetched"
    script = tmp_path / "upload-pack"
    script.write_text(f'#!/bin/sh\ntouch "{mark}"\nexec git-upload-pack "$@"\n')
    script.chmod(0o755)
    _git(repo, "config", "remote.origin.uploadpack", str(script))
    refused = _refusal(tmp_path, repo)
    assert refused.context.get("where") == "a partial clone", refused.context
    assert "git clone --no-local" in str(refused), str(refused)
    assert not mark.exists(), "judging a partial target fetched from its promisor remote"
    _nothing_written(tmp_path, repo)


def test_every_git_command_of_the_check_runs_with_every_transport_refused(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from physgate.knowledge.library import read_library, skill_files  # noqa: PLC0415
    from physgate.orchestrator import decompose  # noqa: PLC0415

    repo = target_repo(tmp_path)
    _git(repo, "branch", "side")
    skills = skill_files(read_library(_library(tmp_path), ROLES))
    head = _git(repo, "rev-parse", "HEAD").strip()
    ran: list[list[str]] = []
    real = subprocess.run

    def recorded(argv: Any, *args: Any, **kwargs: Any) -> Any:  # noqa: ANN401
        ran.append([str(a) for a in argv])
        return real(argv, *args, **kwargs)

    monkeypatch.setattr(subprocess, "run", recorded)
    decompose.require_no_skill_file(repo, head, skills)
    monkeypatch.undo()
    # A config read as a file, from outside any repository, and the making of an empty store
    # open no repository and no remote: every other command is the check's reading of the target.
    commands = [
        argv
        for argv in ran
        if Path(argv[0]).name == "git" and "--file" not in argv and "init" not in argv
    ]
    assert commands, "the check ran no git"
    open_ = [" ".join(argv[-6:]) for argv in commands if "protocol.allow=never" not in argv]
    assert open_ == [], f"a git command of the check may reach a remote: {open_}"


# -- what a run leaves in its target ---------------------------------------------------------


def _off_overrides() -> dict[str, Any]:
    return {"skills": "off", "ablation": True, "harness": CLEAN_HARNESS}


def test_a_second_skills_off_run_starts_on_the_target_a_finished_one_used(tmp_path: Path) -> None:
    # Through the real loop, git, merger and store, with a stand-in session and gate: one
    # attempt refused by the gate, the next merged, the other subtask merged, the run finished.
    from ui_rig import evaluation_rig  # noqa: PLC0415

    from physgate.orchestrator.events import (  # noqa: PLC0415
        AttemptRejected,
        IntegrationGateRan,
        Merged,
        WorktreeRemoved,
        read_events,
    )

    rig = evaluation_rig()
    repo = rig.target_repo(tmp_path)
    runs = tmp_path / "runs"
    first = rig.fake_run(
        runs, "run-1", repo, gate=rig.Gate(fail_on={1}), overrides=_off_overrides()
    )
    events = read_events(first / "events.jsonl")
    kinds = {type(e) for e in events}
    assert {AttemptRejected, Merged, IntegrationGateRan, WorktreeRemoved} <= kinds, kinds
    try:
        second = rig.start(runs, "run-2", repo, **_off_overrides())
    except DecompositionError as exc:
        raise AssertionError(f"the arm refused its own second run: {exc} {exc.context}") from None
    assert second.skills == "off"


def test_after_a_merge_the_harness_aborted_the_next_off_run_needs_a_fresh_clone(
    tmp_path: Path,
) -> None:
    # The harness aborts a merge that does not apply cleanly; git has written the merge's
    # objects by then, and no ref reaches them. The arm then refuses the target, and says how
    # to start: from a fresh clone of it.
    repo = target_repo(tmp_path)
    _git(repo, "checkout", "-q", "-b", "side")
    (repo / "README.md").write_text("target, on the side\n")
    _git(repo, "commit", "-q", "-am", "side")
    _git(repo, "checkout", "-q", "master")
    (repo / "README.md").write_text("target, on master\n")
    _git(repo, "commit", "-q", "-am", "master")
    conflicted = subprocess.run(
        ["git", "-c", "user.email=t@example.invalid", "-c", "user.name=t", "merge", "side"],
        cwd=repo,
        capture_output=True,
        check=False,
    )
    assert conflicted.returncode != 0, "the row's merge applied cleanly"
    _git(repo, "merge", "--abort")
    _git(repo, "branch", "-D", "side")
    _git(repo, "reflog", "expire", "--expire=now", "--all")
    refused = _refusal(tmp_path, repo)
    assert refused.context.get("where") == "unreachable objects", refused.context
    assert "git clone --no-local" in str(refused), str(refused)
    assert "fresh clone" in str(refused), str(refused)
    fresh = tmp_path / "fresh"
    _git(tmp_path, "clone", "-q", "--no-local", str(repo), str(fresh))
    _starts(tmp_path / "again", fresh, "a fresh clone of the target is refused")


# -- a target with very many refs ----------------------------------------------------------


#: A command line longer than this is refused here, as the system refuses a longer one than its
#: own limit: the row's stand-in for a target whose tips outgrow the real one.
ARGUMENT_LIMIT = 8192


def test_under_skills_off_a_target_with_very_many_refs_is_judged_whole(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    import errno  # noqa: PLC0415

    repo = target_repo(tmp_path)
    head = _git(repo, "rev-parse", "HEAD").strip()
    # Branches of distinct commits, each its own tip: more than the limit holds as arguments.
    stream = "".join(
        f"commit refs/heads/b{i}\ncommitter t <t@example.invalid> {1_700_000_000 + i} +0000\n"
        f"data 0\nfrom {head}\n\n"
        for i in range(400)
    )
    _git(repo, "fast-import", "--quiet", stdin=stream)
    real = subprocess.run

    def limited(argv: Any, *args: Any, **kwargs: Any) -> Any:  # noqa: ANN401
        if sum(len(str(a)) + 1 for a in argv) > ARGUMENT_LIMIT:
            raise OSError(errno.E2BIG, "Argument list too long")
        return real(argv, *args, **kwargs)

    monkeypatch.setattr(subprocess, "run", limited)
    try:
        _start(tmp_path, "off", repo)
    except OSError as exc:
        raise AssertionError(f"the target's tips went to git as arguments: {exc}") from None
