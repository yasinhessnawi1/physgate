"""A review's packet reads a SHA-256 repository as readily as a SHA-1 one.

The packet reads the attempt's objects through a throwaway bare store reached by alternates. A
store of one hash cannot read an object of the other, so the store is created with the attempt's
object format. That format is read from the repository's config file as data, by git run outside
the repository: the packet never runs git inside the attempt's repository.
"""

from __future__ import annotations

import hashlib
import subprocess
from pathlib import Path
from typing import Any

import pytest
from packet_fixture import EDITED, ISSUED, SPEC, make_attempt, stream

from physgate.reviewers.packet import _diff, _export, _object_format, issued_spec_sha256


@pytest.mark.parametrize("object_format", ["sha1", "sha256"])
def test_the_packet_s_reads_work_on_a_repository_of_either_format(
    tmp_path: Path, object_format: str
) -> None:
    attempt = make_attempt(tmp_path, stream(), object_format)
    assert len(attempt.attempt_commit) == {"sha1": 40, "sha256": 64}[object_format]
    repo = attempt.worktree
    # The specification as issued, the attempt's tree and the diff: every git read a packet makes.
    issued = issued_spec_sha256(repo, attempt.spec_commit, SPEC)
    assert issued == hashlib.sha256(ISSUED.encode()).hexdigest()
    exported = tmp_path / "export"
    assert _export(repo, attempt.attempt_commit, exported) == 3
    assert (exported / SPEC).read_text() == EDITED
    assert (exported / "m" / "ctl.py").read_text() == "gain = 0.8\n"
    diff = _diff(repo, attempt.spec_commit, attempt.attempt_commit).decode()
    assert "+2. A loop gain of 40 is accepted" in diff


@pytest.mark.parametrize("object_format", ["sha1", "sha256"])
def test_the_packet_reads_the_format_without_running_git_inside_the_repository(
    tmp_path: Path, object_format: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    repo = make_attempt(tmp_path, stream(), object_format).worktree
    calls: list[tuple[list[str], Any, dict[str, str]]] = []
    real_run = subprocess.run

    def recording_run(argv: list[str], **kwargs: Any) -> Any:  # noqa: ANN401
        calls.append((list(argv), kwargs.get("cwd"), dict(kwargs.get("env") or {})))
        return real_run(argv, **kwargs)

    monkeypatch.setattr(subprocess, "run", recording_run)
    assert _object_format(repo) == object_format
    assert calls, "the format was not read through git"
    inside = repo.resolve()
    for argv, cwd, env in calls:
        assert cwd is not None and not Path(cwd).resolve().is_relative_to(inside), cwd
        for flag in ("--git-dir", "-C", "--work-tree"):
            if flag in argv:
                assert not Path(argv[argv.index(flag) + 1]).resolve().is_relative_to(inside)
        assert "GIT_DIR" not in env and "GIT_WORK_TREE" not in env
