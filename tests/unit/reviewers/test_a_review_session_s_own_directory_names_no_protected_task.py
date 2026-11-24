"""A review session's own directory names no protected task: its record's protected part lies apart.

A reviewer is installed with the run's held-out roots, which it may not read, so its sentinel
records, at its first hook, every entry beneath them: a held-out task's directory (its id) and
file, with the file's digest. A review's directory lies beneath the review root, where a review
is read and can be handed on, so the part of the record that names those entries is kept in a
place apart under the review root: beside every review's directory, never in one, outside the
reviewer's read allowance, private to the user, refused to every read and write of the session.
The review's own directory then holds no protected path, file name or digest. What a check
catches is unchanged.

Installed here by the real installer from the reviewer's own arguments, and checked by the real
sentinel through the configuration that install wrote.
"""

from __future__ import annotations

import hashlib
import json
import shutil
import stat
from dataclasses import replace
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest
from test_a_reviewer_s_compaction_follows_the_run_s_parameter import _setup

import physgate.reviewers.claude as claude
from physgate.hooks import cli, paths, sentinel
from physgate.hooks.config import HookInput, SessionConfig
from physgate.hooks.reasons import SENTINEL_APART_REASON
from physgate.hooks.settings import CONFIG_NAME
from physgate.oslayer.session_temp import make_session_temp
from physgate.reviewers.claude import ClaudeReviewer
from physgate.reviewers.packet import WORKTREE_NAME
from physgate.reviewers.places import READ_DIRNAME, SESSION_DIRNAME
from physgate.reviewers.rubric import Rubric

ROLE = "electrical"
REVIEW_ID = "r0123456789ab"
SESSION_ID = "6a1b2c3d-4e5f-4061-8273-94a5b6c7d8e9"
TASK_ID = "control.held-out-stand-in-a4c2e9"
FILE_NAME = "brief-0d3f61.json"
BYTES = b'{"stand-in": "a held-out brief"}\n'
DIGEST = hashlib.sha256(BYTES).hexdigest()


def _holders(where: Path) -> list[str]:
    """Every file under ``where`` that names the protected task, its file or its digest."""
    found = []
    for path in sorted(where.rglob("*")):
        if any(m in path.name for m in (TASK_ID, FILE_NAME)):
            found.append(str(path))
        elif path.is_file() and not path.is_symlink():
            data = path.read_bytes()
            if any(m.encode() in data for m in (TASK_ID, FILE_NAME, DIGEST)):
                found.append(str(path))
    return found


def _installed(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, *, strip_place: bool = False
) -> tuple[SessionConfig, list[str]]:
    """The reviewer's own install arguments, run through the real installer: its configuration."""
    held_out = tmp_path / "tier" / "held_out"
    (held_out / TASK_ID).mkdir(parents=True)
    (held_out / TASK_ID / FILE_NAME).write_bytes(BYTES)
    asked: list[list[str]] = []

    def installer(argv: list[str], **_: object) -> Any:  # noqa: ANN401 - a completed process
        asked.append(argv)
        printed = {"settings": "s", "config": "c", "spawn_args": [], "spawn_env": {}}
        return SimpleNamespace(returncode=0, stdout=json.dumps(printed), stderr="")

    monkeypatch.setattr(claude, "subprocess", SimpleNamespace(run=installer))
    setup = replace(
        _setup(tmp_path, tmp_path / "bin" / "claude", "off"),
        models={ROLE: "claude-sonnet-5"},
        held_out=(str(held_out),),
    )
    reviewer = ClaudeReviewer(
        role=ROLE, setup=setup, rubric=Rubric(role=ROLE, text="r", sha256="0" * 64)
    )
    review = tmp_path / "rs" / REVIEW_ID
    read = review / READ_DIRNAME
    (read / WORKTREE_NAME).mkdir(parents=True)
    (read / WORKTREE_NAME / "README.md").write_text("readme\n")
    sdir = review / SESSION_DIRNAME
    sdir.mkdir()
    packet = SimpleNamespace(read_root=str(read), required_reading=())
    temp = make_session_temp()
    try:
        reviewer._install(packet, sdir, temp)  # type: ignore[arg-type]  # noqa: SLF001
        monkeypatch.undo()
        (argv,) = asked
        if strip_place:
            at = [i for i, w in enumerate(argv) if w == "--sentinel-apart"]
            argv = [w for i, w in enumerate(argv) if not any(i in (j, j + 1) for j in at)]
        assert cli.main(argv[1:]) == 0, "the real installer refused the reviewer's arguments"
    finally:
        shutil.rmtree(temp, ignore_errors=True)
    config = SessionConfig.model_validate_json((sdir / "settings" / CONFIG_NAME).read_bytes())
    return config, argv


def _check(config: SessionConfig, name: str) -> str:
    hook_input = HookInput.model_validate(
        {
            "session_id": SESSION_ID,
            "cwd": config.worktree,
            "hook_event_name": name,
            "tool_name": "Bash",
            "tool_input": {"command": "x", "description": "x"},
        }
    )
    decision = sentinel.check(hook_input, config)
    return "allow" if decision.allow else decision.reason


def _places(config: SessionConfig) -> list[str]:
    return [r.path for r in config.protected_roots if r.reason == SENTINEL_APART_REASON]


def test_a_review_session_s_own_directory_names_no_protected_task_after_its_start_and_end(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    config, _argv = _installed(tmp_path, monkeypatch)
    for event in ("SessionStart", "PostToolUse", "SessionEnd"):
        assert _check(config, event) == "allow", event
    # Not vacuous: the protected entries were recorded, beneath the review root.
    assert _holders(tmp_path / "rs"), "the sentinel recorded no protected entry"
    review = tmp_path / "rs" / REVIEW_ID
    assert _holders(review) == [], "the review's own directory names a protected task"


def test_the_review_s_place_apart_is_under_the_review_root_beside_every_review_and_private(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    config, _argv = _installed(tmp_path, monkeypatch)
    places = _places(config)
    assert len(places) == 1, f"the reviewer is installed with no single place apart: {places}"
    (place,) = (Path(p) for p in places)
    root = (tmp_path / "rs").resolve()
    assert place.parent == root, f"the place apart is not beside the reviews: {place}"
    assert not place.is_relative_to(root / REVIEW_ID), place
    assert all(not place.is_relative_to(Path(r)) for r in config.read_roots), config.read_roots
    assert stat.S_IMODE(place.stat().st_mode) == 0o700
    assert paths.read_refused(str(place / f"{SESSION_ID}.json"), config)
    assert _check(config, "SessionStart") == "allow"
    assert _holders(place), "the place apart holds no part of the record"


def test_a_held_out_file_changed_beside_a_review_is_still_caught(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    config, _argv = _installed(tmp_path, monkeypatch)
    assert _check(config, "SessionStart") == "allow"
    (tmp_path / "tier" / "held_out" / TASK_ID / FILE_NAME).write_bytes(b"changed\n")
    reason = _check(config, "SessionEnd")
    assert "could not be put back" in reason, reason
    assert _check(config, "PostToolUse") == reason


def test_a_review_installed_before_the_place_apart_keeps_its_record_whole_and_still_checks(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    config, argv = _installed(tmp_path, monkeypatch, strip_place=True)
    assert "--sentinel-apart" not in argv
    assert _places(config) == []
    assert _check(config, "SessionStart") == "allow"
    assert _holders(tmp_path / "rs" / REVIEW_ID), "not a record taken as before: it is not whole"
    assert _check(config, "SessionEnd") == "allow"
