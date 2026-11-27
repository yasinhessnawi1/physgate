"""Every place a session's credential is written is found and cleared after a kill.

A session's credential is a file in its own place for as long as it runs, and the session's end
removes it; a stop signal removes it too. A process killed outright removes nothing, so the next
command on the run, or the next start of its round, clears the place of every session nothing
runs as any more. That sweep used to visit the run's role sessions and its reviewers alone: a
decomposition killed outright while its planner's call ran left the planner's login file in the
decomposition's call directory (round one's, its retry's, a later round's), and nothing removed
it, since a cut decomposition's directory is never decomposed again. Now one function finds every
place of every kind, and every clean-up after a kill clears what it finds.

Every credential here is a dummy, and no file's content is read but to see that it is gone.
"""

from __future__ import annotations

import os
import subprocess
import sys
import time
import uuid
from pathlib import Path

import pytest

from physgate.cli import main
from physgate.evaluation import harness_round
from physgate.orchestrator import credentials
from physgate.orchestrator.cli import Registrations
from physgate.orchestrator.credentials import LOGIN_FILE, write_login
from physgate.orchestrator.design_rounds import retry_dir, round_dir
from physgate.orchestrator.stop_signals import remove_left_credentials

DUMMY = "dummy-not-a-credential"


def _logins(top: Path) -> list[str]:
    """Every login file beneath ``top``, by its path beneath it."""
    return sorted(str(p.relative_to(top)) for p in top.rglob(LOGIN_FILE))


def _planner_places(run_dir: Path) -> list[Path]:
    """The call directories a decomposition's planner runs in: round one's, retries, round two's."""
    return [
        round_dir(run_dir, 1),
        retry_dir(run_dir, 1),
        round_dir(run_dir, 2),
        retry_dir(run_dir, 2),
    ]


def _killed_decomposition(base: Path) -> Path:
    """A decomposition's directory as a kill inside each of its planner's calls leaves it."""
    run_dir = base / "runs" / "round-a" / "0001-1"
    for place in _planner_places(run_dir):
        write_login(place / "config", DUMMY)
    (run_dir / "review").mkdir()
    return run_dir


def _next_command(base: Path, run_dir: Path, command: str) -> None:
    """What comes after the kill: the round's restart, or a command a person types."""
    if command == "the round's restart":
        harness_round._deal_with(base / "place", 1, 1, run_dir)
        return
    if command == "decompose":
        argv = ["decompose", str(base / "brief.md"), "--seed", "1", "--run-id", "r"]
        argv += ["--params", str(base / "p.json"), "--target", str(base / "t")]
        argv += ["--review-root", str(run_dir / "review")]
    else:
        argv = [command, "--run-dir", str(run_dir), "--target", str(base / "target")]
        argv += ["--install", str(base / "install"), "--review-root", str(run_dir / "review")]
    # Each refuses the directory for its own reason (no parameters, no run): the sweep runs first.
    main([*argv, "--run-dir", str(run_dir)] if command == "decompose" else argv, Registrations())


@pytest.mark.parametrize("command", ["the round's restart", "run", "resume", "decompose"])
def test_a_decomposition_killed_while_its_planner_ran_leaves_no_credential_after_the_next_command(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, command: str
) -> None:
    monkeypatch.setattr(credentials, "_held", {})
    base = Path(os.path.realpath(tmp_path))
    run_dir = _killed_decomposition(base)
    assert len(_logins(run_dir)) == 4
    _next_command(base, run_dir, command)
    assert _logins(run_dir) == [], f"{command}: the planner's login file was left"


def test_a_planner_still_running_after_its_decompose_was_killed_is_stopped_and_its_login_removed(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(credentials, "_held", {})
    base = Path(os.path.realpath(tmp_path))
    run_dir = _killed_decomposition(base)
    workdir = round_dir(run_dir, 2)
    # The planner as its call starts it: its own settings and its id on its command line. Its
    # decompose was killed outright, so nothing will read its answer, and it runs on.
    planner = subprocess.Popen(
        [sys.executable, "-c", "import time; time.sleep(600)", "--settings"]
        + [str(workdir / "settings.json"), "--session-id", str(uuid.uuid4())]
    )
    try:
        remove_left_credentials(run_dir, run_dir / "review")
        deadline = time.monotonic() + 30
        while planner.poll() is None and time.monotonic() < deadline:
            time.sleep(0.05)
        assert planner.poll() is not None, "the planner a killed decompose left still runs"
        assert _logins(run_dir) == [], "the login file of a planner a kill left stays"
    finally:
        if planner.poll() is None:
            planner.kill()
        planner.wait()
