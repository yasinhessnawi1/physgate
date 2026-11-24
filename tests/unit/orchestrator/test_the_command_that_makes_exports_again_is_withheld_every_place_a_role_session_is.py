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
from typing import Any

import pytest
import test_a_role_session_s_own_directory_names_no_protected_task as held_out_rig
from loop_fakes import Rig
from orch_helpers import make_config
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
from physgate.orchestrator.run_config import RunConfig
from physgate.oslayer.containment import ContainmentError, server_read_denied
from physgate.reviewers.places import standing_review_material

__all__ = ["leftovers"]

REPO = Path(__file__).resolve().parents[3]


def _within(path: str, place: str) -> bool:
    path, place = os.path.realpath(path), os.path.realpath(place)
    return path == place or path.startswith(place.rstrip("/") + "/")


def _whole(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """A run root withheld whole beside the run, as a measured run on a tier-set store names one."""
    root = tmp_path / "earlier-runs"
    (root / "an-earlier-run").mkdir(parents=True)

    def with_root(**fields: Any) -> RunConfig:  # noqa: ANN401
        return make_config(**fields, withheld_whole=(str(root),))

    monkeypatch.setattr(held_out_rig, "make_config", with_root)
    return root


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


@pytest.mark.parametrize("platform", ["linux", "darwin"])
def test_a_run_root_withheld_whole_from_its_sessions_is_withheld_from_the_command(
    platform: str, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A measured run's sessions are withheld its store's run roots whole: so is the command."""
    root = _whole(tmp_path, monkeypatch)
    run, config = _installed(tmp_path, monkeypatch)
    denied = server_read_denied(config, platform)
    # Not vacuous: the session is withheld the root, and the standing review root as material.
    assert any(_within(str(root), place) for place in denied), denied
    standing = standing_review_material((str(run.held_out),))
    assert standing and any(_within(standing[0], place) for place in denied), denied
    withheld = run.dispatcher(monkeypatch).regeneration_withheld()
    uncovered = [p for p in denied if not any(_within(p, place) for place in withheld)]
    assert uncovered == [], f"withheld from the session, not from the command: {uncovered}"
    assert os.path.realpath(root) in withheld, withheld


def test_each_place_a_session_s_layers_name_is_in_the_set_by_its_own_name(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The harness checkout, the hooks' installation and the target repository: each, whole.

    The covering row's session has no read denial inside these three (its protection is off
    there), so each is held here by name: one of them left out of the set would leave its place
    open to the command.
    """
    run = HeldOutRun(tmp_path, "writes-module")
    dispatcher = run.dispatcher(monkeypatch)
    # Named here, so the row holds wherever the code it runs lies, in a checkout or not.
    harness = tmp_path / "harness"
    monkeypatch.setattr(dispatch, "harness_root", lambda: harness)
    withheld = dispatcher.regeneration_withheld()
    forbidden = dispatcher._forbidden()  # noqa: SLF001 - the places the set is built from
    assert forbidden["the harness checkout"] == harness
    for name in ("the harness checkout", "the hooks' installation", "the target repository"):
        assert str(forbidden[name]) in withheld, (name, withheld)
    assert str(run.run.repo) in withheld, withheld
    assert str(run.run.run_dir) in withheld, withheld


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
