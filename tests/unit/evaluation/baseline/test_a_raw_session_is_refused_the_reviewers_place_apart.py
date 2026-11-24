"""A raw session is refused the reviewers' place apart: the key for labels and every record there.

A reviewer's sentinel keeps the part of its record that names the held-out entries in the review
root's place apart, beside every review's directory, with the key that maps every label back.
A reviewer is refused that place by its own configuration, and a role session by being withheld
the whole review root. A raw baseline session, set up from the harness run's record where that run
names a held-out tier, is given the standing review root as review material, refused on every
layer, so it is refused that place too.
"""

from __future__ import annotations

import argparse
import json
import subprocess
from pathlib import Path
from typing import Any

import baseline_fixtures
import pytest
from startup_stand_in import stand_in_spawn_env

from physgate.evaluation.per_role.arms import raw
from physgate.hooks import paths
from physgate.hooks.cli import add_parser
from physgate.hooks.config import SessionConfig
from physgate.orchestrator.dispatch import SENTINEL_APART_DIR
from physgate.oslayer.session_temp import session_temps_root
from physgate.reviewers.places import standing_root

SESSION_ID = "0f1e2d3c-4b5a-6978-8796-a5b4c3d2e1f0"


def _installed(
    root: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> SessionConfig:
    """The raw session's configuration, set up from the harness run's record and installed."""
    made = baseline_fixtures.stand_in_store(root / "u", checked=False)
    task = made.tasks["visible"][0]
    setup = baseline_fixtures.setup_for(baseline_fixtures.config(task, made), task.role)
    seen: list[list[str]] = []

    def fake_run(argv: list[str], **_kw: Any) -> subprocess.CompletedProcess[str]:  # noqa: ANN401
        seen.append(argv)
        out = {"settings": "s", "config": "c", "spawn_args": [], "spawn_env": stand_in_spawn_env()}
        return subprocess.CompletedProcess(argv, 0, json.dumps(out), "")

    worktree, sdir = root / "worktree", root / "session"
    worktree.mkdir()
    monkeypatch.setattr(subprocess, "run", fake_run)
    # A session's own temporary directory as the raw arm names one; named only, never made.
    own_temp = Path(session_temps_root()) / "0123456789"
    raw._install(setup, worktree, sdir, None, own_temp=own_temp)
    monkeypatch.undo()
    parser = argparse.ArgumentParser()
    add_parser(parser.add_subparsers(dest="command"))
    args = parser.parse_args(seen[0][1:])
    assert args.func(args) == 0
    printed = json.loads(capsys.readouterr().out)
    return SessionConfig.model_validate_json(Path(printed["config"]).read_text())


@pytest.mark.parametrize("name", ["labels.key", f"{SESSION_ID}.json"])
def test_a_raw_session_is_refused_a_read_of_the_reviewers_place_apart(
    outside_tmp: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    name: str,
) -> None:
    config = _installed(outside_tmp, monkeypatch, capsys)
    kept = standing_root(Path.home()) / SENTINEL_APART_DIR / name
    assert paths.read_refused(str(kept), config), f"a raw session may read {kept}"
