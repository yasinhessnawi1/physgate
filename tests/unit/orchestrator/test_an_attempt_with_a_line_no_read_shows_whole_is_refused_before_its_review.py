"""An attempt whose diff holds a line no read shows whole is refused before its review, and counted.

The reviewer reads an attempt's diff in parts of at most ``PART_MAX_BYTES`` bytes, cut at line
breaks, so one line longer than a part cannot be issued at all. Such an attempt used to pass the
gate and then end its review ``unprepared``: no verdict, an escalation forced at once, and a person
asked to decide work no reviewer had read, after one attempt. A formatting property of one file
(a single-line export of numbers, in the run that found it) is something the next attempt can
fix. So the change check refuses it, before the gate and before any review token is spent: the
finding names the file, the line and the limit, the attempt is counted like any other refusal,
and only an attempt end with no attempt left goes to a person.

What is held:

- through real git, a 23 kB one-line file is refused by the change check, naming the file, its
  line and the limit; a line removed from the base is named as it stood before the attempt;
- the check refuses exactly the lines the review's parts cannot hold, one byte either side;
- through the real loop, change check and merger with a stand-in session, the refused attempt is
  rejected and repaired, never handed to the reviewer; the fixed one is reviewed and merges;
- three such attempts end in the exhausted budget's escalation, never an unavailable review;
- the log replays, and a rejection for a long line with no such refusal before it does not.
"""

from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "evaluation"))
from observe_rig import Reviewer, fake_run, target_repo  # noqa: E402

from physgate.orchestrator.apply import GitChangeChecker, too_long  # noqa: E402
from physgate.orchestrator.events import (  # noqa: E402
    AttemptRejected,
    Escalated,
    EscalationDecided,
    Merged,
    ProposalsChecked,
    ReviewRan,
    ReviewUnavailable,
    read_events,
)
from physgate.orchestrator.exceptions import CorruptEventLogError  # noqa: E402
from physgate.orchestrator.merge import RunGit, commit_attempt  # noqa: E402
from physgate.orchestrator.repair import repair_instruction  # noqa: E402
from physgate.orchestrator.replay import replay  # noqa: E402
from physgate.reviewers.exceptions import ReviewError  # noqa: E402
from physgate.reviewers.packet import (  # noqa: E402
    PART_MAX_BYTES,
    LongLine,
    first_long_line,
    split_parts,
)

#: Run 7's line: 23 475 bytes on one line, a number export written without a line break.
LONG = b"x = '" + b"9" * 23_469 + b"'\n"
MODULE = "modules/control"

_ENV = {
    "PATH": "/usr/bin:/bin",
    "HOME": os.devnull,
    "GIT_CONFIG_GLOBAL": os.devnull,
    "GIT_CONFIG_NOSYSTEM": "1",
    "GIT_AUTHOR_NAME": "t",
    "GIT_AUTHOR_EMAIL": "t@example.invalid",
    "GIT_COMMITTER_NAME": "t",
    "GIT_COMMITTER_EMAIL": "t@example.invalid",
}


def _git(cwd: Path, *args: str) -> str:
    done = subprocess.run(
        ["git", "-c", "commit.gpgsign=false", *args],
        cwd=cwd,
        env=_ENV,
        capture_output=True,
        text=True,
        check=True,
    )
    return done.stdout.strip()


def _attempt(
    tmp_path: Path, files: dict[str, bytes], base: dict[str, bytes] | None = None
) -> tuple[RunGit, str]:
    """A run whose control subtask committed ``files`` over a target that holds ``base``."""
    repo = tmp_path / "target"
    (repo / MODULE).mkdir(parents=True)
    (repo / MODULE / "keep.txt").write_text("0\n")
    for path, data in (base or {}).items():
        (repo / path).write_bytes(data)
    _git(repo, "init", "-q", "-b", "main")
    _git(repo, "add", "-A")
    _git(repo, "commit", "-q", "-m", "start")
    run = RunGit(repo=repo, run_dir=tmp_path / "run", run_id="r1")
    run.open_run_branch(_git(repo, "rev-parse", "HEAD"))
    worktree = run.open_subtask("control-1")
    for path, data in files.items():
        if data:
            (worktree / path).write_bytes(data)
        else:
            (worktree / path).unlink()
    return run, commit_attempt(worktree, "control-1", 1, "sess-1", repo=run.repo)


def _check(tmp_path: Path, run: RunGit, commit: str) -> tuple[str | None, str | None, str | None]:
    store = tmp_path / "store"
    store.mkdir(exist_ok=True)
    checker = GitChangeChecker(run, store, {"control-1": MODULE})
    check = checker.check("control-1", commit, "control")
    return check.refused_by, check.reason, check.subject


# ── through real git ─────────────────────────────────────────────────────────


def test_a_23_kb_one_line_file_is_refused_naming_the_file_its_line_and_the_limit(
    tmp_path: Path,
) -> None:
    path = f"{MODULE}/bode_export.py"
    run, commit = _attempt(tmp_path, {path: b"a = 1\nb = 2\n" + LONG + b"c = 3\n"})
    refused_by, reason, subject = _check(tmp_path, run, commit)
    assert refused_by == "long_line", reason
    assert reason is not None
    assert f"line 3 of {path} is {len(LONG) - 1} bytes long" in reason
    assert f"parts of at most {PART_MAX_BYTES} bytes" in reason
    assert f"no line longer than {PART_MAX_BYTES - 2} bytes" in reason
    assert subject == path


def test_a_long_line_the_attempt_removes_is_named_as_it_stood_before_the_attempt(
    tmp_path: Path,
) -> None:
    path = f"{MODULE}/old.txt"
    run, commit = _attempt(tmp_path, {path: b""}, base={path: b"keep\n" + LONG})
    refused_by, reason, subject = _check(tmp_path, run, commit)
    assert refused_by == "long_line", reason
    assert reason is not None
    assert f"line 2 of {path}, as it stood before this attempt," in reason
    assert subject == path


@pytest.mark.parametrize(
    ("base", "now", "said"),
    [
        (b"a\nb\nc\n", b"a\nb\nc\nd\n" + LONG, "line 5 of {path} is"),
        (b"a\nb\nc\n" + LONG, b"a\nb\nc\n", "line 4 of {path}, as it stood before this attempt,"),
    ],
    ids=["added after unchanged lines", "removed after unchanged lines"],
)
def test_the_line_is_counted_in_its_file_past_the_lines_the_diff_shows_unchanged(
    tmp_path: Path, base: bytes, now: bytes, said: str
) -> None:
    path = f"{MODULE}/table.txt"
    run, commit = _attempt(tmp_path, {path: now}, base={path: base})
    refused_by, reason, _ = _check(tmp_path, run, commit)
    assert refused_by == "long_line", reason
    assert reason is not None
    assert said.format(path=path) in reason


def test_a_header_line_no_part_holds_is_named_as_the_diff_s_own() -> None:
    """A path can make a header line too long only in a crafted diff; it is still named."""
    name = "m/" + "p" * PART_MAX_BYTES
    diff = f"diff --git a/{name} b/{name}\n--- a/{name}\n+++ b/{name}\n@@ -1 +1 @@\n-a\n+b\n"
    found = first_long_line(diff.encode())
    header = len(f"diff --git a/{name} b/{name}")
    assert found == LongLine(path=name, line=None, before=False, bytes=header)
    assert too_long(found).startswith(f"a header line of the diff for {name} is ")


def test_the_check_refuses_exactly_the_lines_the_review_s_parts_cannot_hold(
    tmp_path: Path,
) -> None:
    """One byte either side of the limit: the check and the packet's own cut agree."""
    path = f"{MODULE}/edge.txt"
    refused, cut = [], []
    for length in (PART_MAX_BYTES - 3, PART_MAX_BYTES - 2, PART_MAX_BYTES - 1):
        where = tmp_path / str(length)
        run, commit = _attempt(where, {path: b"y" * length + b"\n"})
        refused.append(_check(where, run, commit)[0] == "long_line")
        diff = subprocess.run(
            ["git", "diff", "--no-color", "--text", "main", commit],
            cwd=run.repo,
            env=_ENV,
            capture_output=True,
            check=True,
        ).stdout
        try:
            split_parts(diff, "diff-{n:02d}-of-{total:02d}.patch")
            cut.append(False)
        except ReviewError:
            cut.append(True)
    assert refused == cut == [False, False, True]


# ── through the real loop ─────────────────────────────────────────────────────


def _run(tmp_path: Path, long_calls: set[int]) -> tuple[Path, Reviewer]:
    repo = target_repo(tmp_path)
    reviewer = Reviewer()
    content = {call: LONG.decode() for call in long_calls}
    run_dir = fake_run(
        tmp_path, "r-long", repo, session_content=content, reviewers={"electrical": reviewer}
    )
    return run_dir, reviewer


def test_the_refused_attempt_is_repaired_never_reviewed_and_the_fixed_one_merges(
    tmp_path: Path,
) -> None:
    run_dir, reviewer = _run(tmp_path, {1})
    events = read_events(run_dir / "events.jsonl")
    assert not [e for e in events if isinstance(e, ReviewUnavailable)]
    rejected = [e for e in events if isinstance(e, AttemptRejected)]
    assert [(e.attempt, e.finding.source) for e in rejected] == [(1, "long_line")]
    first = rejected[0]
    assert first.finding.subject is not None
    assert first.finding.subject.endswith("/impl.py")
    assert "line 1 of" in first.finding.text
    told = repair_instruction(1, first.finding)
    assert "rejected by the review's read limit" in told
    assert f"line 1 of {first.finding.subject} is {len(LONG) - 1} bytes long" in told
    # The reviewer was never handed the refused attempt; its next attempt was.
    seen = [a.attempt for a in reviewer.seen if a.subtask_id == first.subtask_id]
    assert seen == [2]
    merged = [e for e in events if isinstance(e, Merged) and e.subtask_id == first.subtask_id]
    assert len(merged) == 1


def test_three_long_line_attempts_end_in_the_exhausted_budget_s_escalation(tmp_path: Path) -> None:
    run_dir, reviewer = _run(tmp_path, {1, 2, 3})
    events = read_events(run_dir / "events.jsonl")
    assert not [e for e in events if isinstance(e, ReviewUnavailable)]
    rejected = [e for e in events if isinstance(e, AttemptRejected)]
    assert [(e.attempt, e.finding.source) for e in rejected] == [
        (1, "long_line"),
        (2, "long_line"),
        (3, "long_line"),
    ]
    subtask = rejected[0].subtask_id
    assert [e.repeats_previous for e in rejected] == [False, True, True]
    decided = [e for e in events if isinstance(e, EscalationDecided) and e.subtask_id == subtask]
    assert [(d.attempt, d.decision.forced) for d in decided] == [(1, False), (2, False), (3, True)]
    assert [e.subtask_id for e in events if isinstance(e, Escalated)] == [subtask]
    assert not [a for a in reviewer.seen if a.subtask_id == subtask]
    assert not [e for e in events if isinstance(e, ReviewRan) and e.subtask_id == subtask]


def test_the_log_replays_and_a_long_line_rejection_with_no_refusal_before_it_does_not(
    tmp_path: Path,
) -> None:
    run_dir, _ = _run(tmp_path, {1})
    events = read_events(run_dir / "events.jsonl")
    checked = [e for e in events if isinstance(e, ProposalsChecked) and e.refused_by == "long_line"]
    assert len(checked) == 1, "no change check refused the long line"
    # The refusal comes last, so the line still names what the attempt proposed.
    assert checked[0].proposed != ()
    replay(events)
    forged = [
        e.model_copy(update={"refused_by": None, "reason": None, "subject": None})
        if e is checked[0]
        else e
        for e in events
    ]
    with pytest.raises(CorruptEventLogError):
        replay(forged)
