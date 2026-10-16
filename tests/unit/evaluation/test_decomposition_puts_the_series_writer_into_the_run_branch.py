"""Decomposition puts the series writer into the run branch, byte for byte, beside the library.

Every role session's worktree branches from the run branch, so this is how a script finds
the writer at ``.physgate/lib/series_writer.py``. A target that already holds other bytes
there is refused before anything is written, as it is for a curated file.
"""

from __future__ import annotations

import subprocess
from pathlib import Path

import pytest
from observe_rig import git, start, target_repo

from physgate.orchestrator.exceptions import DecompositionError
from physgate.series.collect import WRITER_PATH, writer_source


def test_the_spec_commit_holds_the_writer_the_harness_ships(tmp_path: Path) -> None:
    repo = target_repo(tmp_path)
    start(tmp_path, "run-writer", repo)
    branch = "physgate/run-writer/run"
    held = subprocess.run(
        ["git", "show", f"{branch}:{WRITER_PATH}"], cwd=repo, capture_output=True, check=True
    ).stdout
    assert held == writer_source()
    listed = git(repo, "ls-tree", "-r", "--name-only", branch).splitlines()
    assert str(WRITER_PATH) in listed


def test_a_target_holding_other_bytes_where_the_writer_goes_is_refused(tmp_path: Path) -> None:
    repo = target_repo(tmp_path)
    (repo / WRITER_PATH).parent.mkdir(parents=True)
    (repo / WRITER_PATH).write_text("# not the harness's writer\n")
    git(repo, "-c", "user.email=t@example.invalid", "-c", "user.name=t", "add", "-A")
    git(repo, "-c", "user.email=t@example.invalid", "-c", "user.name=t", "commit", "-q", "-m", "w")
    with pytest.raises(DecompositionError, match="different file"):
        start(tmp_path, "run-other", repo)
    assert not (tmp_path / "run-other" / "events.jsonl").exists()
