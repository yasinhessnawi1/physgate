"""A reviewer is given its reading in its own read root, and nothing under the harness checkout.

The path hook refuses every file tool's read of the checkout the orchestrator runs from, for every
profile. A reviewer reads the role's skill and standards, and the rubric, so its packet copies
them out of the curated library, the checkout's own, into its read root before the review. Built
here as a review builds it, from this checkout's library, and installed by the real installer from
the reviewer's own arguments: every file it must read lies in its read root, outside the checkout,
and passes the read check; the checkout's own copy of the same skill file is refused.
"""

from __future__ import annotations

import hashlib
import json
import shutil
from dataclasses import replace
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest
from packet_fixture import ISSUED, SPEC, artefact_of, make_attempt, stream
from rubric_fixture import PLACEHOLDER
from test_a_reviewer_s_compaction_follows_the_run_s_parameter import _setup

import physgate.reviewers.claude as claude
from physgate.hooks import cli
from physgate.hooks.config import SessionConfig
from physgate.hooks.paths import protection
from physgate.hooks.reasons import HARNESS_REASON
from physgate.hooks.settings import CONFIG_NAME
from physgate.knowledge import loader
from physgate.orchestrator.protocols import IssuedSpec
from physgate.orchestrator.run_config import harness_root
from physgate.oslayer.session_temp import make_session_temp
from physgate.reviewers.claude import ClaudeReviewer
from physgate.reviewers.packet import build_packet
from physgate.reviewers.rubric import Rubric

ROLE = "control"


def test_a_reviewer_s_required_reading_lies_in_its_read_root_and_none_under_the_checkout(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    harness = harness_root()
    assert harness is not None, "the tests run from a source checkout, which is the harness"
    rubric = Rubric(
        role=ROLE, text=PLACEHOLDER, sha256=hashlib.sha256(PLACEHOLDER.encode()).hexdigest()
    )
    attempt = make_attempt(tmp_path, stream())
    packet = build_packet(
        tmp_path / "reviews" / "r0123456789ab",
        artefact_of(attempt),
        repo=attempt.worktree,
        base_commit=attempt.spec_commit,
        rubric=rubric,
        library=harness,
        spec=IssuedSpec(
            commit=attempt.spec_commit,
            path=SPEC,
            sha256=hashlib.sha256(ISSUED.encode()).hexdigest(),
        ),
    )
    asked: list[list[str]] = []

    def installer(argv: list[str], **_: object) -> Any:  # noqa: ANN401 - a completed process
        asked.append(argv)
        printed = {"settings": "s", "config": "c", "spawn_args": [], "spawn_env": {}}
        return SimpleNamespace(returncode=0, stdout=json.dumps(printed), stderr="")

    monkeypatch.setattr(claude, "subprocess", SimpleNamespace(run=installer))
    setup = replace(
        _setup(tmp_path, tmp_path / "bin" / "claude", "off"),
        library=harness,
        models={ROLE: "claude-sonnet-5"},
    )
    reviewer = ClaudeReviewer(role=ROLE, setup=setup, rubric=rubric)
    sdir = tmp_path / "review-session"
    sdir.mkdir()
    temp = make_session_temp()
    try:
        reviewer._install(packet, sdir, temp)  # noqa: SLF001 - the thing under test
        monkeypatch.undo()
        (argv,) = asked
        assert "--harness" in argv, "the reviewer is installed without the checkout protected"
        # The reviewer's own arguments, handed to the real installer.
        assert cli.main(argv[1:]) == 0
    finally:
        shutil.rmtree(temp, ignore_errors=True)
    written = SessionConfig.model_validate_json((sdir / "settings" / CONFIG_NAME).read_bytes())

    given = sorted({*written.required_reading, *written.always_loaded})
    assert len(given) >= 2, given
    under = [p for p in given if Path(p).resolve().is_relative_to(harness.resolve())]
    assert under == [], f"a reviewer is given a file to read from the harness checkout: {under}"
    worktree = str(Path(packet.read_root) / "worktree")
    refused = {p: protection(p, worktree, written, writing=False) for p in given}
    assert refused == dict.fromkeys(given), f"a file the reviewer must read is refused: {refused}"
    own = str(harness / loader.DEFAULT_ROOT / ROLE / loader.SKILL_NAME)
    assert protection(own, worktree, written, writing=False) == HARNESS_REASON
