"""The command that makes a role's exports again is withheld every place a role session is.

At the change check the harness makes a role's committed circuit exports again from the committed
schematic, inside the tool containment. It runs for a role's file, so it is withheld at least
what the role's session was: the change check's runner is given the dispatcher's
``regeneration_withheld``, and every place a role session of the run may not read lies inside
one of its places. The set is the dispatcher's own, read from the run and never from a session's
files, which are the session's user's to write by its end; it holds at a resume as before one.

The rig is the one the held records' rows use: a stand-in session that runs the real hook chain,
installed by the dispatcher's own installer, with a held-out root holding one stand-in task. The
session's read denials are the OS layer's own (``server_read_denied``, the outbox whole, as a
tool server of the session is denied them), on Linux and on macOS.
"""

from __future__ import annotations

import ast
import os
from pathlib import Path

import pytest
from loop_fakes import Rig
from test_a_role_session_s_own_directory_names_no_protected_task import HeldOutRun
from test_a_session_s_hooks_never_fork_the_run_s_own_records import leftovers
from test_committed_exports_are_regenerated_from_their_committed_schematic import (
    FAILING,
    PLANNED,
    attempt,
    made,
    recorded,
    stand_in_root,
)

from physgate.hooks.config import SessionConfig
from physgate.hooks.settings import CONFIG_NAME
from physgate.orchestrator import dispatch
from physgate.orchestrator.apply import GitChangeChecker
from physgate.orchestrator.exceptions import RunStateError
from physgate.oslayer.containment import ContainmentError, server_read_denied

__all__ = ["leftovers"]

REPO = Path(__file__).resolve().parents[3]


def _within(path: str, place: str) -> bool:
    path, place = os.path.realpath(path), os.path.realpath(place)
    return path == place or path.startswith(place.rstrip("/") + "/")


def _installed(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> tuple[HeldOutRun, SessionConfig]:
    run = HeldOutRun(tmp_path, "writes-module")
    loop = Rig(run.run.run_dir).open()
    try:
        run.dispatcher(monkeypatch).run(run.request(), loop._spawned)
    finally:
        loop.close()
    config = run.session_dir() / "session" / CONFIG_NAME
    return run, SessionConfig.model_validate_json(config.read_bytes())


@pytest.mark.parametrize("platform", ["linux", "darwin"])
def test_every_place_a_role_session_may_not_read_lies_inside_one_the_command_is_withheld(
    platform: str, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    run, config = _installed(tmp_path, monkeypatch)
    denied = server_read_denied(config, platform)
    # Not vacuous: the session is withheld the held-out tier and places in the run's directory.
    assert any(_within(str(run.held_out), place) for place in denied), denied
    assert any(_within(place, str(run.run.run_dir)) for place in denied), denied
    withheld = run.dispatcher(monkeypatch).regeneration_withheld()
    uncovered = [p for p in denied if not any(_within(p, place) for place in withheld)]
    assert uncovered == [], f"withheld from the session, not from the command: {uncovered}"


def test_the_set_is_read_from_the_run_and_holds_after_a_resume(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A dispatcher that installed no session gives the same set: a resume judges such attempts."""
    run, _config = _installed(tmp_path, monkeypatch)
    after_the_session = run.dispatcher(monkeypatch).regeneration_withheld()
    fresh = run.dispatcher(monkeypatch).regeneration_withheld()
    assert fresh == after_the_session
    assert str(run.held_out) in fresh
    assert str(run.run.run_dir) in fresh


def test_a_run_whose_parameters_file_is_not_known_refuses_in_words_that_name_no_place(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    run = HeldOutRun(tmp_path, "writes-module")
    dispatcher = run.dispatcher(monkeypatch)

    def unknown(_run_dir: Path) -> tuple[Path, ...]:
        raise RunStateError("no record", run_dir=str(run.run.run_dir))

    monkeypatch.setattr(dispatch, "withheld_paths", unknown)
    with pytest.raises(ContainmentError) as caught:
        dispatcher.regeneration_withheld()
    assert str(tmp_path) not in str(caught.value), caught.value


def test_the_run_s_parameters_file_is_withheld_wherever_it_lies(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A run started from a parameters file outside its directory: the file is withheld too."""
    run = HeldOutRun(tmp_path, "writes-module")
    dispatcher = run.dispatcher(monkeypatch)
    params = tmp_path / "elsewhere" / "params.json"
    monkeypatch.setattr(dispatch, "withheld_paths", lambda run_dir: (run_dir / "run.json", params))
    withheld = dispatcher.regeneration_withheld()
    assert str(params) in withheld, withheld


def test_a_change_check_given_no_withheld_places_refuses_a_set_and_starts_nothing(
    tmp_path: Path,
) -> None:
    """Its default runner refuses every regeneration, on every platform, before any wrapper."""
    run, commit = attempt(tmp_path, made(FAILING))
    record = recorded(stand_in_root(tmp_path))
    store = tmp_path / "store"
    store.mkdir()
    changes = GitChangeChecker(run, store, dict(PLANNED), environment=lambda: record)
    found = changes.check("s1", commit, "control")
    assert found.refused_by == "exports", (found.refused_by, found.reason)
    assert found.reason is not None and "no places withheld" in found.reason, found.reason
    assert found.exports_regenerated == 0


def test_the_run_s_change_check_is_given_the_dispatcher_s_set() -> None:
    """The one change check a run builds is handed the set, beside the held tool environment."""
    tree = ast.parse((REPO / "src" / "physgate" / "orchestrator" / "cli.py").read_text("utf-8"))
    built = [
        node
        for node in ast.walk(tree)
        if isinstance(node, ast.Call)
        and isinstance(node.func, ast.Name)
        and node.func.id == "GitChangeChecker"
    ]
    assert len(built) == 1, "the run builds one change check"
    given = {k.arg: ast.unparse(k.value) for k in built[0].keywords}
    assert given.get("withheld") == "dispatcher.regeneration_withheld", given
    assert given.get("environment") == "dispatcher.held_tool_environment", given
