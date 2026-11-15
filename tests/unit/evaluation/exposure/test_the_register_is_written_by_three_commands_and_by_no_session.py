"""The register is written by three commands, a hand mark only at a terminal, and by no session.

The register and the run roots lie beneath the role's withheld root, which every run that names
anything under the role's root withholds: a role session's file tool, its shell and the OS
layer refuse both files to it, so it can neither read them nor write them, and a writer it
started would be refused the write. A hand mark is made by a person at a terminal, naming who
and why. No command removes a line, so nothing unmarks a version. ``tiers status`` shows an
exposed version as stale.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import Any

import pytest
from exposure_fixtures import (
    StandInStore,
    api,
    harness_run,
    incident_in,
    stand_in_store,
    with_run_root,
)

from physgate.cli import main
from physgate.evaluation.tiers.store import withheld_root
from physgate.hooks import paths, shell_paths
from physgate.hooks.settings import InstallRequest, build_config, current_installation
from physgate.hooks.shell import parse
from physgate.oslayer.policy import sandbox_policy

EXPOSURE = "physgate.evaluation.tiers.exposure"


@pytest.fixture
def made(tmp_path: Path) -> StandInStore:
    return stand_in_store(tmp_path / "s")


def _tiers(capsys: pytest.CaptureFixture[str], *args: str) -> tuple[int, dict[str, Any]]:
    code = main(["tiers", *args])
    out = capsys.readouterr().out.strip().splitlines()
    assert out, "the command printed nothing"
    return code, json.loads(out[-1])


def _at_a_terminal(monkeypatch: pytest.MonkeyPatch, *, yes: bool) -> None:
    monkeypatch.setattr(sys.stdin, "isatty", lambda: yes)
    monkeypatch.setattr(sys.stdout, "isatty", lambda: yes)


def _mark(made: StandInStore, reason: str = "opened the tier by hand") -> list[str]:
    return [
        "mark-exposed",
        "--store",
        str(made.store),
        "--role",
        "control",
        "--version",
        made.version,
        "--by",
        "a person",
        "--reason",
        reason,
    ]


def test_a_hand_mark_is_refused_away_from_a_terminal(
    made: StandInStore, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    _at_a_terminal(monkeypatch, yes=False)
    code, said = _tiers(capsys, *_mark(made))
    assert code != 0 and said.get("refused_because") == "not_at_a_terminal"
    assert api(f"{EXPOSURE}.register_lines")(made.store, "control") == []


def test_a_hand_mark_at_a_terminal_is_recorded_with_who_and_why(
    made: StandInStore, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    _at_a_terminal(monkeypatch, yes=True)
    code, said = _tiers(capsys, *_mark(made))
    assert code == 0, said
    (line,) = api(f"{EXPOSURE}.register_lines")(made.store, "control")
    assert (line.source, line.version, line.by, line.reason) == (
        "hand",
        made.version,
        "a person",
        "opened the tier by hand",
    )


def test_a_hand_mark_without_a_reason_is_refused_at_the_command_too(
    made: StandInStore, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    _at_a_terminal(monkeypatch, yes=True)
    code, said = _tiers(capsys, *_mark(made, reason="opened"))
    assert code != 0 and said.get("refused_because") == "hand_mark_without_a_reason"


def test_the_scan_and_the_run_roots_are_written_by_their_commands_and_counted(
    tmp_path: Path, made: StandInStore, capsys: pytest.CaptureFixture[str]
) -> None:
    runs = tmp_path / "runs"
    runs.mkdir()
    store = ["--store", str(made.store), "--role", "control"]
    code, said = _tiers(capsys, "add-run-root", *store, "--path", str(runs))
    assert code == 0 and said.get("added") is True
    code, said = _tiers(capsys, "add-run-root", *store, "--path", str(runs))
    assert code == 0 and said.get("added") is False
    incident_in(harness_run(runs, made.tasks["visible"][1], made, ended=False))
    code, said = _tiers(capsys, "scan-exposures", *store)
    assert code == 0 and (said.get("added"), said.get("already")) == (1, 0)
    code, said = _tiers(capsys, "scan-exposures", *store)
    assert code == 0 and (said.get("added"), said.get("already")) == (0, 1)


def test_a_run_root_in_the_store_or_holding_it_is_refused(
    tmp_path: Path, made: StandInStore
) -> None:
    add = api(f"{EXPOSURE}.add_run_root")
    error = api(f"{EXPOSURE}.ExposureError")
    for root in (made.store / "control" / "work", tmp_path):
        with pytest.raises(error):
            add(made.store, "control", root)
    assert api(f"{EXPOSURE}.run_roots")(made.store, "control") == []


def test_no_command_removes_a_line(capsys: pytest.CaptureFixture[str]) -> None:
    with pytest.raises(SystemExit):
        main(["tiers", "--help"])
    shown = capsys.readouterr().out
    for command in ("status", "scan-exposures", "mark-exposed", "add-run-root"):
        assert command in shown, f"tiers has no {command}"
    for word in ("unmark", "remove", "delete", "clear", "reset"):
        assert word not in shown, f"tiers has a command that may take a line away: {word}"


def test_tiers_status_shows_an_exposed_version_as_stale_and_why(
    tmp_path: Path, made: StandInStore, capsys: pytest.CaptureFixture[str]
) -> None:
    runs = with_run_root(made, tmp_path / "runs")
    incident_in(harness_run(runs, made.tasks["visible"][1], made, ended=False))
    main(["tiers", "status", "--store", str(made.store)])
    (version,) = json.loads(capsys.readouterr().out.strip().splitlines()[-1])["versions"]
    assert version["state"] == "stale"
    assert "held_out" in version["stale_tiers"] and "exposed" in version["because"]


def _role_config(base: Path, made: StandInStore) -> Any:  # noqa: ANN401
    for d in ("wt", "outside/state", "outside/session", "outside/config", "outside/home"):
        (base / d).mkdir(parents=True, exist_ok=True)
    request = InstallRequest(
        profile="role",
        role="control",
        worktree=str(base / "wt"),
        own_branch=None,
        store_root=None,
        state_dir=str(base / "outside" / "state"),
        target_dir=str(base / "outside" / "session"),
        claude_config_dir=str(base / "outside" / "config"),
        user_home=str(base / "outside" / "home"),
        token_ceiling=40960,
        held_out=made.held_out,
    )
    return build_config(request, current_installation())


def _covered(place: str, listed: list[str]) -> bool:
    return any(place == d or place.startswith(d.rstrip("/") + "/") for d in listed)


def test_a_role_session_of_a_run_on_the_store_cannot_read_or_write_the_register_or_its_roots(
    tmp_path: Path, made: StandInStore, monkeypatch: pytest.MonkeyPatch
) -> None:
    runs = with_run_root(made, tmp_path / "runs")
    _at_a_terminal(monkeypatch, yes=True)
    api(f"{EXPOSURE}.mark_exposed")(
        made.store, "control", made.version, by="a person", reason="opened the tier by hand"
    )
    assert runs.is_dir()
    base = tmp_path.resolve() / "session"
    config = _role_config(base, made)
    wt = str(base / "wt")
    policy = sandbox_policy(config, home=str(base / "outside" / "home"), temp_dir="/tmp/pg-reg")
    filesystem = policy.settings["sandbox"]["filesystem"]
    withheld = withheld_root(made.store, "control")
    files = sorted(p for p in withheld.iterdir() if p.name.startswith(("register", "run-roots")))
    assert {p.name for p in files} >= {
        "register.jsonl",
        "register.head",
        "run-roots.jsonl",
        "run-roots.head",
    }
    for found in files:
        target = str(found)
        for writing in (False, True):
            assert paths.protection(target, wt, config, writing=writing), (
                f"a role session's file tool may {'write' if writing else 'read'} {found.name}"
            )
        for command in (f"cat {target}", f"printf x >> {target}", f": > {target}"):
            assert shell_paths.check(parse(command)[0], wt, config), (
                f"a role session's shell may run {command!r}"
            )
        assert _covered(target, filesystem["denyRead"]), f"the OS layer lets {found.name} be read"
        assert _covered(target, filesystem["denyWrite"]), (
            f"the OS layer lets {found.name} be written"
        )
    # A writer a session started would write beneath the withheld root, which its commands may
    # not write, whatever names it was given.
    for command in ("scan-exposures", "mark-exposed", "add-run-root"):
        typed = f"physgate tiers {command} --store {made.store} --role control"
        refused_by_the_shell = bool(shell_paths.check(parse(typed)[0], wt, config))
        assert refused_by_the_shell or _covered(str(withheld), filesystem["denyWrite"]), (
            f"a role session could run {command} and have it write the register"
        )
