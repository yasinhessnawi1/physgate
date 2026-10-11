"""The review packet runs the harness's one git, by its path, with attributes from the empty tree.

The packet used to run whichever ``git`` came first on ``PATH=/usr/bin:/bin``: on a machine whose
system git is older than 2.42, a git that ignores the attribute source. It now executes the
binary ``harness_git`` resolved, and passes ``--attr-source`` and ``GIT_ATTR_SOURCE`` naming the
empty tree of the store's object format (the format read itself runs outside any repository and
names the SHA-1 one).
"""

from __future__ import annotations

import subprocess
from pathlib import Path
from typing import Any

import pytest
from packet_fixture import SPEC, make_attempt, stream

from physgate.orchestrator.git import EMPTY_TREES, harness_git
from physgate.reviewers import packet
from physgate.reviewers.packet import _diff, _export, issued_spec_sha256


@pytest.mark.parametrize("object_format", ["sha1", "sha256"])
def test_every_packet_git_call_runs_the_resolved_git_with_the_matching_empty_tree(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, object_format: str
) -> None:
    attempt = make_attempt(tmp_path, stream(), object_format)
    repo = attempt.worktree
    calls: list[tuple[list[str], dict[str, str]]] = []
    real_run = subprocess.run

    def recording_run(argv: list[str], **kwargs: Any) -> Any:  # noqa: ANN401
        calls.append((list(argv), dict(kwargs.get("env") or {})))
        return real_run(argv, **kwargs)

    monkeypatch.setattr(subprocess, "run", recording_run)
    # The store is cached per process; start afresh so its creation is recorded too.
    packet._object_store.cache_clear()
    _diff(repo, attempt.spec_commit, attempt.attempt_commit)
    _export(repo, attempt.attempt_commit, tmp_path / "export")
    issued_spec_sha256(repo, attempt.spec_commit, SPEC)

    assert calls
    exe = harness_git().path
    own, sha1 = EMPTY_TREES[object_format], EMPTY_TREES["sha1"]
    kinds = set()
    for argv, env in calls:
        assert argv[0] == exe, argv
        kind = "config" if "config" in argv else "init" if "init" in argv else "read"
        kinds.add(kind)
        tree = sha1 if kind == "config" else own
        assert argv[1] == f"--attr-source={tree}", argv
        assert env.get("GIT_ATTR_SOURCE") == tree, argv
    assert kinds == {"config", "init", "read"}
