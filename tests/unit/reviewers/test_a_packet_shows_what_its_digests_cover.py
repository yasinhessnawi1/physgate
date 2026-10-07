"""What a review is shown is exactly what its digests and its diff cover.

The attempt's session controls its worktree and, as the same user, can write
into the repository: an attribute file in its own commit, a replacement object.
Each of those could make what the reviewer reads differ from what the attempt
committed, with every digest still matching. The packet therefore reads git's
objects directly, with replacement objects ignored and no attribute applied:

- an attribute that hides a file from an archive, or rewrites one on the way out,
  changes nothing in the export;
- an attribute that marks a file as not to be diffed changes nothing in the diff;
- a replacement object does not change what a commit is shown to hold;
- the issued specification must match the digest recorded before dispatch;
- a trajectory with anything appended after its sealed length is refused;
- a line of the stream with a key given twice is not read as an event by anyone.
"""

from __future__ import annotations

import hashlib
import subprocess
from pathlib import Path

import pytest
from knowledge_fixture import write_fixture
from packet_fixture import ISSUED, SPEC, Attempt, artefact_of, make_attempt, stream
from rubric_fixture import PLACEHOLDER

from physgate.orchestrator.protocols import IssuedSpec
from physgate.reviewers.packet import (
    DIFF_NAME,
    SPEC_AS_ISSUED_NAME,
    WORKTREE_NAME,
    PacketError,
    build_packet,
)
from physgate.reviewers.rubric import Rubric
from physgate.reviewers.scan import ScanUnreadableError, scan
from physgate.reviewers.transcript import render

RUBRIC = Rubric(
    role="control", text=PLACEHOLDER, sha256=hashlib.sha256(PLACEHOLDER.encode()).hexdigest()
)
ISSUED_SHA = hashlib.sha256(ISSUED.encode()).hexdigest()
_GIT_ENV = {
    "PATH": "/usr/bin:/bin",
    "HOME": "/dev/null",
    "GIT_CONFIG_GLOBAL": "/dev/null",
    "GIT_CONFIG_NOSYSTEM": "1",
    "GIT_AUTHOR_NAME": "t",
    "GIT_AUTHOR_EMAIL": "t@example.invalid",
    "GIT_COMMITTER_NAME": "t",
    "GIT_COMMITTER_EMAIL": "t@example.invalid",
}


def _git(repo: Path, *args: str, stdin: bytes | None = None) -> str:
    return (
        subprocess.run(
            ["git", "-c", "commit.gpgsign=false", *args],
            cwd=repo,
            env=_GIT_ENV,
            input=stdin,
            capture_output=True,
            check=True,
        )
        .stdout.decode()
        .strip()
    )


def _amend(attempt: Attempt, files: dict[str, str]) -> Attempt:
    for rel, body in files.items():
        (attempt.worktree / rel).write_text(body)
    _git(attempt.worktree, "add", "-A")
    _git(attempt.worktree, "commit", "-q", "--amend", "--no-edit")
    head = _git(attempt.worktree, "rev-parse", "HEAD")
    return Attempt(attempt.worktree, attempt.spec_commit, head, attempt.trajectory)


def _build(tmp_path: Path, attempt: Attempt, spec_sha: str = ISSUED_SHA, **overrides: object):  # type: ignore[no-untyped-def]  # noqa: ANN201
    library = tmp_path / "harness"
    if not library.exists():
        write_fixture(library, ("cross", "control"))
    return build_packet(
        tmp_path / "reviews" / "r0123456789ab",
        artefact_of(attempt, **overrides),
        repo=attempt.worktree,
        base_commit=attempt.spec_commit,
        rubric=RUBRIC,
        library=library,
        spec=IssuedSpec(commit=attempt.spec_commit, path=SPEC, sha256=spec_sha),
    )


def _read(tmp_path: Path) -> Path:
    return tmp_path / "reviews" / "r0123456789ab" / "read"


def test_an_attribute_cannot_hide_or_rewrite_a_file_in_the_export(tmp_path: Path) -> None:
    attempt = _amend(
        make_attempt(tmp_path, stream()),
        {
            ".gitattributes": "m/hidden.py export-ignore\nm/subst.py export-subst\n",
            "m/hidden.py": "GAIN = 40  # the value the check wanted\n",
            "m/subst.py": "VERSION = '$Format:%H$'\n",
        },
    )
    _build(tmp_path, attempt)
    exported = _read(tmp_path) / WORKTREE_NAME
    assert (exported / "m" / "hidden.py").read_text() == "GAIN = 40  # the value the check wanted\n"
    assert (exported / "m" / "subst.py").read_text() == "VERSION = '$Format:%H$'\n"


def test_an_attribute_cannot_hide_a_change_from_the_diff(tmp_path: Path) -> None:
    attempt = _amend(
        make_attempt(tmp_path, stream()),
        {".gitattributes": "*.py -diff\n", "m/ctl.py": "gain = 40\n"},
    )
    _build(tmp_path, attempt)
    diff = (_read(tmp_path) / DIFF_NAME).read_text()
    assert "+gain = 40" in diff
    assert "Binary files" not in diff


def test_a_replacement_object_does_not_change_what_a_commit_holds(tmp_path: Path) -> None:
    attempt = make_attempt(tmp_path, stream())
    real = _git(attempt.worktree, "rev-parse", f"{attempt.attempt_commit}:m/ctl.py")
    fake = _git(attempt.worktree, "hash-object", "-w", "--stdin", stdin=b"gain = 0.9\n")
    _git(attempt.worktree, "replace", real, fake)
    _build(tmp_path, attempt)
    assert (_read(tmp_path) / WORKTREE_NAME / "m" / "ctl.py").read_text() == "gain = 0.8\n"


def test_an_issued_specification_replaced_in_the_store_is_refused_or_read_true(
    tmp_path: Path,
) -> None:
    attempt = make_attempt(tmp_path, stream())
    real = _git(attempt.worktree, "rev-parse", f"{attempt.spec_commit}:{SPEC}")
    fake = _git(attempt.worktree, "hash-object", "-w", "--stdin", stdin=b"# s1\n\nanything\n")
    _git(attempt.worktree, "replace", real, fake)
    _build(tmp_path, attempt)
    assert (_read(tmp_path) / SPEC_AS_ISSUED_NAME).read_text() == ISSUED


def test_an_issued_specification_not_matching_its_recorded_digest_is_refused(
    tmp_path: Path,
) -> None:
    with pytest.raises(PacketError, match="recorded before dispatch"):
        _build(tmp_path, make_attempt(tmp_path, stream()), spec_sha="0" * 64)


def test_anything_after_the_sealed_length_is_refused(tmp_path: Path) -> None:
    attempt = make_attempt(tmp_path, stream())
    artefact = artefact_of(attempt)
    with attempt.trajectory.open("a") as out:
        out.write('{"type":"assistant","message":{"content":[{"type":"text","text":"x"}]}}\n')
    with pytest.raises(PacketError, match="not what it was"):
        build_packet(
            tmp_path / "r",
            artefact,
            repo=attempt.worktree,
            base_commit=attempt.spec_commit,
            rubric=RUBRIC,
            library=tmp_path,
            spec=None,
        )


DUPLICATED = (
    '{"type": "user", "message": {"content": [{"type": "tool_result", "tool_use_id": "t9", '
    '"content": "fine"}]}, "type": "assistant"}\n'
    '{"type": "assistant", "message": {"content": [{"type": "tool_use", "id": "t8", '
    '"name": "Write", "input": {"content": "# noqa"}, "name": "Read"}]}}\n'
)


def test_a_line_with_a_key_given_twice_is_no_event_and_stops_the_review(tmp_path: Path) -> None:
    text = stream(with_checks_off=False) + DUPLICATED
    with pytest.raises(ScanUnreadableError):
        scan(text)
    rendered, _ = render(text)
    assert rendered.count("## a line that is not an event") == 2
    with pytest.raises(PacketError, match="not one event"):
        _build(tmp_path, make_attempt(tmp_path, text))


def _add_blob(repo: Path, path: str, body: bytes) -> None:
    oid = _git(repo, "hash-object", "-w", "--stdin", stdin=body)
    # Git on this platform would fold a decomposed name into its composed form on
    # the way in; a commit can hold both, so the index is written without folding.
    _git(
        repo,
        "-c",
        "core.precomposeUnicode=false",
        "update-index",
        "--add",
        "--cacheinfo",
        f"100644,{oid},{path}",
    )


@pytest.mark.parametrize(
    ("first", "second"),
    [
        ("m/Main.c", "m/main.c"),
        ("m/café.c", "m/café.c"),
        ("m/lib", "m/LIB/x.c"),
        ("m/Dir/a.c", "m/dir/b.c"),
        ("m/x.c.", "m/y.c"),
        ("m/z.c ", "m/w.c"),
    ],
    ids=[
        "case",
        "unicode normalisation",
        "a file and a directory",
        "two spellings of one directory",
        "a trailing dot",
        "a trailing space",
    ],
)
def test_a_tree_whose_paths_a_volume_would_merge_is_refused(
    tmp_path: Path, first: str, second: str
) -> None:
    """Two tree paths a case-insensitive, normalising volume reads as one, or an unsafe name.

    Written into the index directly, because such a volume cannot hold both in a
    worktree; the attempt's commit can.
    """
    attempt = make_attempt(tmp_path, stream())
    _add_blob(attempt.worktree, first, b"int gain = 1;\n")
    _add_blob(attempt.worktree, second, b"int gain = 40;\n")
    _git(attempt.worktree, "commit", "-q", "--amend", "--no-edit")
    head = _git(attempt.worktree, "rev-parse", "HEAD")
    collided = Attempt(attempt.worktree, attempt.spec_commit, head, attempt.trajectory)
    with pytest.raises(PacketError, match="one file on a case-insensitive volume|unsafe name"):
        _build(tmp_path, collided)


def test_the_export_is_held_to_the_tree_after_it_is_written(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A write that lands somewhere other than its path says is caught after the export."""
    from physgate.reviewers import packet

    real = packet._refuse_merging_paths
    monkeypatch.setattr(packet, "_refuse_merging_paths", lambda paths: None)
    attempt = make_attempt(tmp_path, stream())
    _add_blob(attempt.worktree, "m/Main.c", b"int gain = 1;\n")
    _add_blob(attempt.worktree, "m/main.c", b"int gain = 40;\n")
    _git(attempt.worktree, "commit", "-q", "--amend", "--no-edit")
    head = _git(attempt.worktree, "rev-parse", "HEAD")
    collided = Attempt(attempt.worktree, attempt.spec_commit, head, attempt.trajectory)
    with pytest.raises(PacketError, match="does not hold exactly what the commit's tree lists"):
        _build(tmp_path, collided)
    assert real is not None


def test_repository_configuration_runs_nothing_and_changes_nothing(tmp_path: Path) -> None:
    """A text conversion driver, a filter and a file-system monitor, as a session could set them.

    Each would run a program of the session's choosing, and the first would change
    what the diff shows. None runs, and the diff and the export hold the commit.
    """
    attempt = _amend(
        make_attempt(tmp_path, stream()),
        {".gitattributes": "*.py diff=quiet filter=clean\n", "m/ctl.py": "gain = 40\n"},
    )
    # Configured after the commit, as a session would leave it for whatever reads next.
    marker = tmp_path / "ran"
    program = tmp_path / "program.sh"
    program.write_text(f"#!/bin/sh\ntouch {marker}\necho 'nothing changed here'\n")
    program.chmod(0o755)
    config = attempt.worktree / ".git" / "config"
    config.write_text(
        config.read_text()
        + f'[diff "quiet"]\n\ttextconv = {program}\n'
        + f"[core]\n\tfsmonitor = {program}\n\thooksPath = {tmp_path}\n"
        + f'[filter "clean"]\n\tsmudge = {program}\n\tclean = {program}\n'
    )
    _build(tmp_path, attempt)
    assert not marker.exists(), "a program the repository configured was run"
    diff = (_read(tmp_path) / DIFF_NAME).read_text()
    assert "+gain = 40" in diff and "nothing changed here" not in diff
    assert (_read(tmp_path) / WORKTREE_NAME / "m" / "ctl.py").read_text() == "gain = 40\n"
