"""The orchestrator's git work on a real repository: scope, merge, conflict, a crash."""

from __future__ import annotations

import os
from pathlib import Path

import pytest
from git_rig import (
    DispatchPort,
    EmptyGraph,
    Gate,
    GitDispatcher,
    Reviewer,
    ScopeChecker,
    config,
    plan_entry,
    run_layout,
    sh,
)

from physgate.orchestrator.events import GateRan, Incident, Merged, Resumed, read_events
from physgate.orchestrator.exceptions import GitError, MergeConflictError, MergeRefusedError
from physgate.orchestrator.git import head_of
from physgate.orchestrator.loop import Loop
from physgate.orchestrator.merge import (
    GitMerger,
    RunGit,
    commit_attempt,
    merge_message,
    write_scope_violations,
)
from physgate.state.task_ledger import TaskLedger

pytestmark = pytest.mark.integration


def attempt_with(run: RunGit, subtask: str, files: dict[str, str | None]) -> tuple[str, str]:
    """Write ``files`` (None deletes) in the subtask's worktree; return (base, commit)."""
    worktree = run.open_subtask(subtask)
    base = head_of(worktree, "HEAD")
    for rel, content in files.items():
        path = worktree / rel
        if content is None:
            path.unlink()
        else:
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(content)
    return base, commit_attempt(worktree, subtask, 1, "sess-1")


def test_changes_inside_the_module_and_proposals_are_in_scope(tmp_path: Path) -> None:
    run = run_layout(tmp_path)
    base, commit = attempt_with(
        run,
        "s1",
        {
            "modules/power/driver.py": "z = 2\n",
            "modules/power/base.py": None,
            ".physgate/proposals/motor.left.json": "{}\n",
        },
    )
    assert write_scope_violations(run.repo, base, commit, "modules/power") == []


@pytest.mark.parametrize(
    "files",
    [
        {"README.md": "changed\n"},
        {"modules/control/base.py": "y = 2\n"},
        {"modules/powerx/a.py": "near miss\n"},
        {"modules/control/base.py": None},
        {".physgate/specs/s1.md": "a spec rewritten\n"},
        {".physgate/proposals/not-a-node-id.json": "{}\n"},
    ],
    ids=[
        "a file at the root",
        "another module",
        "a sibling with a shared prefix",
        "a deletion outside",
        "the subtask's own specification",
        "a proposal file whose name is no node id",
    ],
)
def test_a_change_outside_the_module_is_a_violation(
    tmp_path: Path, files: dict[str, str | None]
) -> None:
    run = run_layout(tmp_path)
    base, commit = attempt_with(run, "s1", files)
    assert write_scope_violations(run.repo, base, commit, "modules/power") != []


def test_a_symbolic_link_is_out_of_scope_even_inside_the_module(tmp_path: Path) -> None:
    run = run_layout(tmp_path)
    worktree = run.open_subtask("s1")
    base = head_of(worktree, "HEAD")
    os.symlink("../../README.md", worktree / "modules" / "power" / "link.md")
    commit = commit_attempt(worktree, "s1", 1, "sess-1")
    found = write_scope_violations(run.repo, base, commit, "modules/power")
    assert found == ["modules/power/link.md (not a regular file)"]


@pytest.mark.parametrize("module_dir", ["../outside", "/abs/path", "", "."])
def test_a_module_directory_that_leaves_the_repository_is_refused(
    tmp_path: Path, module_dir: str
) -> None:
    run = run_layout(tmp_path)
    base, commit = attempt_with(run, "s1", {"modules/power/a.py": "a\n"})
    with pytest.raises(GitError):
        write_scope_violations(run.repo, base, commit, module_dir)


def test_the_orchestrator_commits_even_an_attempt_that_changed_nothing(tmp_path: Path) -> None:
    run = run_layout(tmp_path)
    base, commit = attempt_with(run, "s1", {})
    assert commit != base
    message = sh(run.repo, "log", "-1", "--format=%an%n%B", commit)
    assert message.startswith("physgate orchestrator\nAttempt 1 of subtask s1")


def test_the_merger_refuses_a_commit_other_than_the_checked_one(tmp_path: Path) -> None:
    run = run_layout(tmp_path)
    _, checked = attempt_with(run, "s1", {"modules/power/a.py": "a\n"})
    _, later = attempt_with(run, "s1", {"modules/power/b.py": "b\n"})
    before = head_of(run.repo, run.run_branch)
    with pytest.raises(MergeRefusedError):
        GitMerger(run, removal_timeout_s=60.0).merge(
            "s1", 1, checked, merge_message("s1", 1, checked, "pass", "pass")
        )
    assert head_of(run.repo, run.run_branch) == before
    merged = GitMerger(run, removal_timeout_s=60.0).merge(
        "s1", 1, later, merge_message("s1", 1, later, "pass", "pass")
    )
    assert sh(run.repo, "log", "-1", "--format=%P", merged).split()[1] == later


def test_a_merge_is_made_once_however_often_it_is_asked_for(tmp_path: Path) -> None:
    run = run_layout(tmp_path)
    _, commit = attempt_with(run, "s1", {"modules/power/a.py": "a\n"})
    text = merge_message("s1", 1, commit, "pass", "pass")
    first = GitMerger(run, removal_timeout_s=60.0).merge("s1", 1, commit, text)
    second = GitMerger(run, removal_timeout_s=60.0).merge("s1", 1, commit, text)
    assert first == second
    merges = sh(run.repo, "log", "--merges", "--format=%H", run.run_branch).split()
    assert merges == [first]


def test_a_conflict_is_aborted_and_leaves_the_run_branch_as_it_was(tmp_path: Path) -> None:
    run = run_layout(tmp_path)
    _, commit = attempt_with(run, "s1", {"modules/power/base.py": "x = 2\n"})
    (run.integration / "modules" / "power" / "base.py").write_text("x = 3\n")
    sh(run.integration, "commit", "-q", "-am", "a write the plan never made")
    before = head_of(run.repo, run.run_branch)
    with pytest.raises(MergeConflictError):
        GitMerger(run, removal_timeout_s=60.0).merge(
            "s1", 1, commit, merge_message("s1", 1, commit, "pass", "pass")
        )
    assert head_of(run.repo, run.run_branch) == before
    assert sh(run.integration, "status", "--porcelain") == ""


def _loop(run: RunGit, dispatcher: GitDispatcher, gate: Gate, merger: object) -> Loop:
    modules = {"s1": "modules/power", "s2": "modules/control"}
    return Loop(
        config=config(),
        run_dir=run.run_dir,
        gate=gate,
        reviewers={"electrical": Reviewer()},
        dispatcher=DispatchPort(dispatcher),
        changes=ScopeChecker(run, modules),
        merger=merger,  # type: ignore[arg-type]
        graph=EmptyGraph(),
        sleep=lambda _: None,
    )


def test_an_accepted_attempt_is_merged_and_a_rejected_worktree_stays_for_the_repair(
    tmp_path: Path,
) -> None:
    run = run_layout(tmp_path)
    dispatcher = GitDispatcher(run)
    loop = _loop(
        run, dispatcher, Gate(verdicts=["pass", "fail"]), GitMerger(run, removal_timeout_s=60.0)
    )
    loop.start([plan_entry("s1", "modules/power"), plan_entry("s2", "modules/control")])
    assert loop.run().kind == "done"
    loop.close()
    ledger = TaskLedger(run.run_dir / "ledger.jsonl")
    s1, s2 = ledger.find("s1"), ledger.find("s2")
    assert s1 is not None and s2 is not None and s1.merge_commit and s2.merge_commit
    assert s2.attempt_count == 2
    parents = sh(run.repo, "log", "-1", "--format=%P", s1.merge_commit).split()
    checked = [
        e.attempt_commit for e in read_events(run.run_dir / "events.jsonl") if isinstance(e, Merged)
    ]
    assert parents[1] == checked[0]
    # The rejected first attempt of s2 was never merged, and its worktree carried
    # into the repair: the second session saw the first attempt's file.
    merged_seconds = sh(run.repo, "log", "--merges", "--format=%P", run.run_branch).split()
    first_s2 = [r for r in dispatcher.requests if r.subtask_id == "s2"]
    assert len(first_s2) == 2
    # The worktree itself is gone once s2 is done; its branch keeps what it held.
    second = sh(run.repo, "show", f"{run.subtask_branch('s2')}:modules/control/attempt2.py")
    assert "attempt1.py" in second
    assert not run.subtask_worktree("s2").exists()
    assert len(sh(run.repo, "log", "--merges", "--format=%H", run.run_branch).split()) == 2
    assert checked[1] in merged_seconds


def test_an_attempt_out_of_scope_is_rejected_before_the_gate(tmp_path: Path) -> None:
    run = run_layout(tmp_path)
    gate = Gate()
    # The first session writes outside its module; the repair session puts it back.
    # The change stays on the subtask's branch until a later attempt undoes it.
    dispatcher = GitDispatcher(run, outside={1}, repair={2})
    loop = _loop(run, dispatcher, gate, GitMerger(run, removal_timeout_s=60.0))
    loop.start([plan_entry("s1", "modules/power")])
    loop.run()
    loop.close()
    assert gate.calls == 1  # only the second, in-scope attempt reached the gate
    second = dispatcher.requests[1].repair_instruction
    assert second is not None and "write-scope check" in second and "README.md" in second


class _KilledAfterMerge(GitMerger):
    """Makes the real merge, then dies before the loop can record it."""

    def merge(self, subtask_id: str, attempt: int, attempt_commit: str, message: str) -> str:
        super().merge(subtask_id, attempt, attempt_commit, message)
        raise KeyboardInterrupt


def test_a_kill_between_the_merge_and_its_record_resumes_to_exactly_one_merge(
    tmp_path: Path,
) -> None:
    run = run_layout(tmp_path)
    dispatcher = GitDispatcher(run)
    gate = Gate()
    loop = _loop(run, dispatcher, gate, _KilledAfterMerge(run, removal_timeout_s=60.0))
    loop.start([plan_entry("s1", "modules/power")])
    with pytest.raises(KeyboardInterrupt):
        loop.run()
    loop.close()
    assert len(sh(run.repo, "log", "--merges", "--format=%H", run.run_branch).split()) == 1

    again = _loop(run, dispatcher, gate, GitMerger(run, removal_timeout_s=60.0))
    assert again.resume().kind == "done"
    again.close()
    events = read_events(run.run_dir / "events.jsonl")
    (merged,) = [e for e in events if isinstance(e, Merged)]
    (merge_line,) = sh(run.repo, "log", "--merges", "--format=%H %P", run.run_branch).splitlines()
    merge_sha, _, second_parent = merge_line.split()
    assert (merge_sha, second_parent) == (merged.merge_commit, merged.attempt_commit)
    (resumed,) = [e for e in events if isinstance(e, Resumed)]
    assert (resumed.attempt, resumed.point) == (1, "verify_reading")
    assert [e.attempt for e in events if isinstance(e, GateRan)] == [1, 1]
    assert len(dispatcher.requests) == 1
    line = TaskLedger(run.run_dir / "ledger.jsonl").find("s1")
    assert line is not None and line.attempt_count == 1 and line.merge_commit == merged.merge_commit


def test_a_branch_moved_after_the_check_halts_the_run_as_an_incident(tmp_path: Path) -> None:
    run = run_layout(tmp_path)

    class Moving(GitMerger):
        def merge(self, subtask_id: str, attempt: int, attempt_commit: str, message: str) -> str:
            worktree = run.subtask_worktree(subtask_id)
            (worktree / "modules" / "power" / "late.py").write_text("late\n")
            commit_attempt(worktree, subtask_id, attempt, "late")
            return super().merge(subtask_id, attempt, attempt_commit, message)

    before = head_of(run.repo, run.run_branch)
    loop = _loop(run, GitDispatcher(run), Gate(), Moving(run, removal_timeout_s=60.0))
    loop.start([plan_entry("s1", "modules/power")])
    assert loop.run().kind == "halted"
    loop.close()
    (incident,) = [e for e in read_events(run.run_dir / "events.jsonl") if isinstance(e, Incident)]
    assert incident.cause == "merge_refused"
    assert head_of(run.repo, run.run_branch) == before


def test_a_hook_script_in_the_target_repository_never_runs(tmp_path: Path) -> None:
    run = run_layout(tmp_path)
    hooks = run.repo / ".git" / "hooks"
    marker = tmp_path / "hook-ran"
    for name in ("pre-commit", "commit-msg", "pre-merge-commit", "post-merge"):
        script = hooks / name
        script.write_text(f"#!/bin/sh\ntouch {marker}\nexit 1\n")
        script.chmod(0o755)
    _, commit = attempt_with(run, "s1", {"modules/power/a.py": "a\n"})
    GitMerger(run, removal_timeout_s=60.0).merge(
        "s1", 1, commit, merge_message("s1", 1, commit, "pass", "pass")
    )
    assert not marker.exists()


def test_asking_again_after_later_merges_returns_the_original_merge(tmp_path: Path) -> None:
    # Git alone would answer "already up to date" and leave HEAD on the latest
    # merge, which is another subtask's. The merger must name the merge of this
    # commit, not whatever the run branch points at now.
    run = run_layout(tmp_path)
    _, one = attempt_with(run, "s1", {"modules/power/a.py": "a\n"})
    first = GitMerger(run, removal_timeout_s=60.0).merge(
        "s1", 1, one, merge_message("s1", 1, one, "pass", "pass")
    )
    worktree = run.open_subtask("s2")
    (worktree / "modules" / "control" / "b.py").write_text("b\n")
    two = commit_attempt(worktree, "s2", 1, "sess-2")
    later = GitMerger(run, removal_timeout_s=60.0).merge(
        "s2", 1, two, merge_message("s2", 1, two, "pass", "pass")
    )
    again = GitMerger(run, removal_timeout_s=60.0).merge(
        "s1", 1, one, merge_message("s1", 1, one, "pass", "pass")
    )
    assert again == first != later
    assert len(sh(run.repo, "log", "--merges", "--format=%H", run.run_branch).split()) == 2


def test_a_worktree_is_removed_without_force_and_its_branch_kept(tmp_path: Path) -> None:
    run = run_layout(tmp_path)
    attempt_with(run, "s1", {"modules/power/a.py": "a\n"})
    done = GitMerger(run, removal_timeout_s=60.0).remove_worktree("s1")
    assert done.outcome == "removed" and not run.subtask_worktree("s1").exists()
    assert sh(run.repo, "branch", "--list", run.subtask_branch("s1")).strip()
    again = GitMerger(run, removal_timeout_s=60.0).remove_worktree("s1")
    assert again.outcome == "absent"


def test_a_removal_git_refuses_is_reported_and_the_worktree_left(tmp_path: Path) -> None:
    run = run_layout(tmp_path)
    attempt_with(run, "s1", {"modules/power/a.py": "a\n"})
    (run.subtask_worktree("s1") / "modules" / "power" / "untracked.py").write_text("u\n")
    refused = GitMerger(run, removal_timeout_s=60.0).remove_worktree("s1")
    assert refused.outcome == "refused" and refused.detail
    assert (run.subtask_worktree("s1") / "modules" / "power" / "untracked.py").exists()


def test_a_removal_past_its_bound_is_recorded_and_left(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    import physgate.orchestrator.merge as merge_module

    run = run_layout(tmp_path)
    attempt_with(run, "s1", {"modules/power/a.py": "a\n"})
    asked: list[float] = []

    def slow(cwd: Path, *args: str, timeout: float) -> tuple[int | None, str, float]:
        asked.append(timeout)
        return None, "", timeout  # what git_timed returns when the bound passes

    monkeypatch.setattr(merge_module, "git_timed", slow)
    late = GitMerger(run, removal_timeout_s=2.5).remove_worktree("s1")
    assert (late.outcome, late.seconds, asked) == ("timed_out", 2.5, [2.5])
    assert late.detail == "no answer within 2.5 s"


def _forge_run_ref(run: RunGit, packed: bool) -> str:
    """Move the run branch to a commit nobody merged, as a session's shell could."""
    head = head_of(run.repo, run.run_branch)
    tree = sh(run.repo, "rev-parse", f"{head}^{{tree}}").strip()
    forged = sh(run.repo, "commit-tree", "-p", head, "-m", "forged", tree).strip()
    if packed:
        # Only in packed-refs: no loose ref file to protect or to watch.
        sh(run.repo, "pack-refs", "--all")
        packed_refs = run.repo / ".git" / "packed-refs"
        old = head_of(run.repo, run.run_branch)
        packed_refs.write_text(packed_refs.read_text().replace(old, forged))
    else:
        sh(run.repo, "update-ref", f"refs/heads/{run.run_branch}", forged)
    assert head_of(run.repo, run.run_branch) == forged
    return forged


@pytest.mark.parametrize("packed", [False, True], ids=["loose ref", "packed-refs"])
def test_a_run_branch_moved_between_merges_is_an_incident_before_the_next_merge(
    tmp_path: Path, packed: bool
) -> None:
    run = run_layout(tmp_path)
    forged: list[str] = []
    dispatcher = GitDispatcher(
        run, during={2: lambda _: forged.append(_forge_run_ref(run, packed))}
    )
    loop = _loop(run, dispatcher, Gate(), GitMerger(run, removal_timeout_s=60.0))
    loop.start([plan_entry("s1", "modules/power"), plan_entry("s2", "modules/control")])
    assert loop.run().kind == "halted"
    loop.close()
    events = read_events(run.run_dir / "events.jsonl")
    (incident,) = [e for e in events if isinstance(e, Incident)]
    assert incident.cause == "run_branch_moved" and incident.subtask_id == "s2"
    assert forged[0] in incident.detail
    assert [e.subtask_id for e in events if isinstance(e, Merged)] == ["s1"]
    assert head_of(run.repo, run.run_branch) == forged[0]  # nothing merged onto it


class _ForgedError(Exception):
    pass


def test_a_run_branch_moved_while_the_orchestrator_was_down_is_an_incident_at_resume(
    tmp_path: Path,
) -> None:
    run = run_layout(tmp_path)

    def forge_and_die(_: Path) -> None:
        _forge_run_ref(run, packed=False)
        raise _ForgedError

    dispatcher = GitDispatcher(run, during={2: forge_and_die})
    loop = _loop(run, dispatcher, Gate(), GitMerger(run, removal_timeout_s=60.0))
    loop.start([plan_entry("s1", "modules/power"), plan_entry("s2", "modules/control")])
    with pytest.raises(_ForgedError):
        loop.run()
    loop.close()
    killed_at = len(read_events(run.run_dir / "events.jsonl"))
    fresh = GitDispatcher(run)
    again = _loop(run, fresh, Gate(), GitMerger(run, removal_timeout_s=60.0))
    assert again.resume().kind == "halted"
    again.close()
    events = read_events(run.run_dir / "events.jsonl")
    (incident,) = [e for e in events if isinstance(e, Incident)]
    assert incident.cause == "run_branch_moved"
    assert [e.subtask_id for e in events if isinstance(e, Merged)] == ["s1"]
    # Caught at the resume itself, before anything else of the run happens.
    assert fresh.requests == []
    assert [e.kind for e in events[killed_at:]] == ["incident", "halted"]


def test_the_merge_a_killed_process_made_and_never_recorded_is_where_the_run_left_its_branch(
    tmp_path: Path,
) -> None:
    # s1 merged and recorded; s2 merged, then the process died before recording it.
    # At the resume the branch is one merge past the last recorded one, a merge of
    # exactly s2's checked commit: that is not a moved branch.
    run = run_layout(tmp_path)

    class KilledAtSecondMerge(GitMerger):
        def merge(self, subtask_id: str, attempt: int, attempt_commit: str, message: str) -> str:
            done = super().merge(subtask_id, attempt, attempt_commit, message)
            if subtask_id == "s2":
                raise KeyboardInterrupt
            return done

    dispatcher = GitDispatcher(run)
    loop = _loop(run, dispatcher, Gate(), KilledAtSecondMerge(run, removal_timeout_s=60.0))
    loop.start([plan_entry("s1", "modules/power"), plan_entry("s2", "modules/control")])
    with pytest.raises(KeyboardInterrupt):
        loop.run()
    loop.close()
    again = _loop(run, dispatcher, Gate(), GitMerger(run, removal_timeout_s=60.0))
    assert again.resume().kind == "done"
    again.close()
    events = read_events(run.run_dir / "events.jsonl")
    assert not [e for e in events if isinstance(e, Incident)]
    assert [e.subtask_id for e in events if isinstance(e, Merged)] == ["s1", "s2"]
