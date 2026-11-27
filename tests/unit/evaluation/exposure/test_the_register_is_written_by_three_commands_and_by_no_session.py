"""The register is written by four commands, and by no session.

What holds a session off is the place: the register and the run roots lie beneath the role's
withheld root, which every run that names anything under the role's root withholds. A role
session's file tool and its shell refuse both files to it and every writer's command, which
names that root, and the OS layer denies writes beneath it (shown here in the generated
policy; through the real binary in the integration rows). Each writer also refuses inside a
harness session's environment, as defence in depth: a session controls its own environment.
A hand mark asks for a terminal and a name, a second measure for the person who makes it,
never what stops a session; so does a settle, which is a command of its own and marks no
version (a hand mark settles nothing, and says which command does). A run root that would make
every later scan refuse is not added. A round's prepared target is checked by a command of its
own, which writes nothing.
No command removes a line, so nothing unmarks a version. ``tiers status`` shows an exposed
version as stale, and lists each settle with its directory's path as typed and as resolved.
"""

from __future__ import annotations

import importlib
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
    try:
        code = main(["tiers", *args])
    except SystemExit:
        pytest.fail(f"tiers has no command {args[0]} taking these arguments")
    out = capsys.readouterr().out.strip().splitlines()
    assert out, "the command printed nothing"
    return code, json.loads(out[-1])


def _at_a_terminal(monkeypatch: pytest.MonkeyPatch, *, yes: bool) -> None:
    monkeypatch.setattr(sys.stdin, "isatty", lambda: yes)
    monkeypatch.setattr(sys.stdout, "isatty", lambda: yes)


def _mark(made: StandInStore, reason: str = "opened the tier by hand") -> list[str]:
    return [
        "mark-exposed",
        "--withheld",
        str(withheld_root(made.store, "control")),
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


def test_a_hand_mark_naming_a_directory_to_settle_is_refused_and_names_the_command_that_does(
    tmp_path: Path,
    made: StandInStore,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    _at_a_terminal(monkeypatch, yes=True)
    code, said = _tiers(capsys, *_mark(made), "--settles", str(tmp_path))
    assert code != 0 and said.get("refused_because") == "settles_is_its_own_command"
    assert "physgate tiers settle" in said.get("error", ""), said
    assert api(f"{EXPOSURE}.register_lines")(made.store, "control") == []


def _settle_argv(made: StandInStore, directory: Path) -> list[str]:
    return [
        "settle",
        "--withheld",
        str(withheld_root(made.store, "control")),
        "--directory",
        str(directory),
        "--by",
        "a person",
        "--reason",
        "looked at the directory",
    ]


def _refusing(made: StandInStore, runs: Path) -> Path:
    """A directory beneath the run roots the register refuses: its parameters record is torn."""
    directory = runs / "cut"
    directory.mkdir()
    (directory / "params_source.json").write_text("{")
    with pytest.raises(api(f"{EXPOSURE}.ExposureError")):
        api(f"{EXPOSURE}.exposed_versions")(made.store, "control")
    return directory


def test_a_settle_is_refused_away_from_a_terminal(
    tmp_path: Path,
    made: StandInStore,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    directory = _refusing(made, with_run_root(made, tmp_path / "runs"))
    _at_a_terminal(monkeypatch, yes=False)
    code, said = _tiers(capsys, *_settle_argv(made, directory))
    assert code != 0 and said.get("refused_because") == "not_at_a_terminal"
    assert api(f"{EXPOSURE}.register_lines")(made.store, "control") == []


def test_a_settle_at_a_terminal_is_one_line_that_marks_no_version(
    tmp_path: Path,
    made: StandInStore,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    directory = _refusing(made, with_run_root(made, tmp_path / "runs"))
    _at_a_terminal(monkeypatch, yes=True)
    code, said = _tiers(capsys, *_settle_argv(made, directory))
    assert code == 0, said
    (line,) = api(f"{EXPOSURE}.register_lines")(made.store, "control")
    assert (line.kind, line.by, line.reason) == ("settle", "a person", "looked at the directory")
    assert api(f"{EXPOSURE}.exposed_versions")(made.store, "control") == frozenset()
    # Settled, it refuses nothing more: a second settle is refused.
    code, said = _tiers(capsys, *_settle_argv(made, directory))
    assert code != 0 and said.get("refused_because") == "settle_refuses_nothing"


def test_a_settle_keeps_the_path_as_typed_and_as_resolved_and_the_status_lists_it(
    tmp_path: Path,
    made: StandInStore,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    runs = with_run_root(made, tmp_path / "runs")
    directory = _refusing(made, runs)
    (tmp_path / "alias").symlink_to(runs)
    monkeypatch.chdir(tmp_path)
    typed = "alias/./cut/"
    _at_a_terminal(monkeypatch, yes=True)
    argv = _settle_argv(made, directory)
    argv[argv.index("--directory") + 1] = typed
    code, said = _tiers(capsys, *argv)
    assert code == 0, said
    (line,) = api(f"{EXPOSURE}.register_lines")(made.store, "control")
    assert (line.given_path, line.resolved_path) == (typed, str(directory.resolve()))
    _, status = _tiers(capsys, "status", "--store", str(made.store))
    assert len(status["settles"]) == 1, status
    (listed,) = status["settles"]
    assert listed["role"] == "control" and listed["key"] == line.key, listed
    assert (listed["given_path"], listed["resolved_path"]) == (typed, str(directory.resolve()))
    assert (listed["by"], listed["reason"], listed["date"]) == (line.by, line.reason, line.date)


def test_a_settle_of_a_directory_outside_the_run_roots_is_refused_at_the_command(
    tmp_path: Path,
    made: StandInStore,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    with_run_root(made, tmp_path / "runs")
    elsewhere = tmp_path / "elsewhere"
    elsewhere.mkdir()
    _at_a_terminal(monkeypatch, yes=True)
    code, said = _tiers(capsys, *_settle_argv(made, elsewhere))
    assert code != 0 and said.get("refused_because") == "settle_outside_the_run_roots"


@pytest.mark.parametrize(
    ("how", "reason"),
    [
        ("as a round prepares it", None),
        ("nested six deep", "target_too_deep"),
        ("holding run.json", "target_holds_a_record"),
        ("holding raw.json", "target_holds_a_record"),
        ("holding params_source.json", "target_holds_a_record"),
    ],
)
def test_a_round_s_prepared_target_is_checked_by_a_command_of_its_own(
    tmp_path: Path, capsys: pytest.CaptureFixture[str], how: str, reason: str | None
) -> None:
    target = tmp_path / "target"
    (target / ".git" / "refs" / "heads").mkdir(parents=True)
    (target / "README.md").write_text("a target")
    if how == "nested six deep":
        (target / ".git" / "a" / "b" / "c" / "d" / "e").mkdir(parents=True)
    elif how.startswith("holding"):
        (target / "docs").mkdir()
        (target / "docs" / how.split()[-1]).write_text("{}")
    code, said = _tiers(capsys, "check-target", "--path", str(target))
    if reason is None:
        assert code == 0 and said.get("checked") == str(target), said
    else:
        assert code != 0 and said.get("refused_because") == reason, said
    # It writes nothing.
    assert not (target / "params_source.json").exists() or how.endswith("params_source.json")


def test_the_scan_and_the_run_roots_are_written_by_their_commands_and_counted(
    tmp_path: Path, made: StandInStore, capsys: pytest.CaptureFixture[str]
) -> None:
    runs = tmp_path / "runs"
    runs.mkdir()
    store = ["--withheld", str(withheld_root(made.store, "control"))]
    code, said = _tiers(capsys, "add-run-root", *store, "--path", str(runs))
    assert code == 0 and said.get("added") is True
    code, said = _tiers(capsys, "add-run-root", *store, "--path", str(runs))
    assert code == 0 and said.get("added") is False
    incident_in(harness_run(runs, made.tasks["visible"][1], made, ended=False))
    code, said = _tiers(capsys, "scan-exposures", *store)
    assert code == 0 and (said.get("added"), said.get("already")) == (1, 0)
    code, said = _tiers(capsys, "scan-exposures", *store)
    assert code == 0 and (said.get("added"), said.get("already")) == (0, 1)


@pytest.mark.parametrize("writer", ["scan-exposures", "add-run-root"])
def test_a_writer_given_anything_but_a_role_s_withheld_root_is_refused(
    tmp_path: Path, made: StandInStore, capsys: pytest.CaptureFixture[str], writer: str
) -> None:
    runs = tmp_path / "runs"
    runs.mkdir()
    extra = ["--path", str(runs)] if writer == "add-run-root" else []
    code, said = _tiers(capsys, writer, "--withheld", str(made.store / "control" / "work"), *extra)
    assert code != 0 and said.get("refused_because") == "not_a_withheld_root"
    # The logs a version is written with hold no line.
    assert api(f"{EXPOSURE}.register_lines")(made.store, "control") == []
    assert api(f"{EXPOSURE}.run_roots")(made.store, "control") == []


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
    for command in ("status", "scan-exposures", "mark-exposed", "settle", "add-run-root"):
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
    for command in ("scan-exposures", "mark-exposed", "settle", "add-run-root"):
        typed = f"physgate tiers {command} --withheld {withheld}"
        assert shell_paths.check(parse(typed)[0], wt, config), (
            f"a role session's shell may run {command} on the role's withheld root"
        )
        assert _covered(str(withheld), filesystem["denyWrite"]), (
            f"the OS layer would let {command} write beneath the withheld root"
        )


HOOK_TESTS = Path(__file__).resolve().parents[2] / "hooks"


@pytest.mark.parametrize("profile", ["role", "baseline"])
def test_every_role_and_baseline_session_carries_a_marker_the_writers_refuse(
    tmp_path: Path, profile: str
) -> None:
    if str(HOOK_TESTS) not in sys.path:
        sys.path.insert(0, str(HOOK_TESTS))
    from test_install_writes_the_sessions_settings_file import REGISTRY, _request

    from physgate.hooks.settings import install

    fields: dict[str, Any] = {"profile": profile}
    if profile == "baseline":
        fields.update(role=None, own_branch=None, store_root=None)
    done = install(_request(tmp_path, **fields), REGISTRY)
    markers = set(api(f"{EXPOSURE}.SESSION_MARKERS"))
    assert markers & set(done.spawn_env), f"a {profile} session carries no marker: {done.spawn_env}"


def _the_writers(made: StandInStore, runs: Path) -> dict[str, Any]:
    return {
        "scan": lambda: api(f"{EXPOSURE}.record_scan")(made.store, "control"),
        "mark": lambda: api(f"{EXPOSURE}.mark_exposed")(
            made.store, "control", made.version, by="a person", reason="opened the tier by hand"
        ),
        "settle": lambda: api(f"{EXPOSURE}.settle_directory")(
            made.store, "control", runs, by="a person", reason="looked at the directory"
        ),
        "root": lambda: api(f"{EXPOSURE}.add_run_root")(made.store, "control", runs),
    }


@pytest.mark.parametrize("marker", ["CLAUDE_CODE_DISABLE_BACKGROUND_TASKS", "CLAUDE_CODE_TMPDIR"])
@pytest.mark.parametrize("writer", ["scan", "mark", "settle", "root"])
def test_each_writer_refuses_inside_a_harness_session_and_appends_nothing(
    tmp_path: Path, made: StandInStore, monkeypatch: pytest.MonkeyPatch, marker: str, writer: str
) -> None:
    runs = tmp_path / "runs"
    runs.mkdir()
    error = api(f"{EXPOSURE}.ExposureError")
    monkeypatch.setenv(marker, "1")
    with pytest.raises(error) as refused:
        _the_writers(made, runs)[writer]()
    assert refused.value.context.get("refused_because") == "inside_a_session"
    # The logs a version is written with hold no line.
    assert api(f"{EXPOSURE}.register_lines")(made.store, "control") == []
    assert api(f"{EXPOSURE}.run_roots")(made.store, "control") == []


def _bad_root(tmp_path: Path, how: str, monkeypatch: pytest.MonkeyPatch) -> Path:
    try:
        exposure = importlib.import_module(EXPOSURE)
    except ImportError:
        pytest.fail(f"{EXPOSURE} is not built")
    root = tmp_path / "root"
    if how == "missing":
        return root
    if how == "a file":
        root.write_text("not a directory")
        return root
    if how == "a link":
        (tmp_path / "real").mkdir()
        root.symlink_to(tmp_path / "real")
        return root
    root.mkdir()
    if how == "unreadable":
        root.chmod(0)
    elif how == "too deep":
        monkeypatch.setattr(exposure, "MOST_DEPTH", 2)
        (root / "a" / "b" / "c" / "d").mkdir(parents=True)
    elif how == "too many entries":
        monkeypatch.setattr(exposure, "MOST_ENTRIES", 5)
        for i in range(10):
            (root / f"e{i}").mkdir()
    else:
        (root / "broken").mkdir()
        (root / "broken" / "run.json").write_text("not a run's configuration")
    return root


@pytest.mark.parametrize(
    ("how", "reason"),
    [
        ("missing", "run_root_not_a_directory"),
        ("a file", "run_root_not_a_directory"),
        ("a link", "run_root_not_a_directory"),
        ("unreadable", "run_root_unreadable"),
        ("too deep", "run_root_would_refuse_the_scan"),
        ("too many entries", "run_root_would_refuse_the_scan"),
        ("a broken run", "run_root_would_refuse_the_scan"),
    ],
)
def test_a_run_root_the_scan_could_not_read_whole_is_refused_and_nothing_is_appended(
    tmp_path: Path, made: StandInStore, monkeypatch: pytest.MonkeyPatch, how: str, reason: str
) -> None:
    root = _bad_root(tmp_path, how, monkeypatch)
    error = api(f"{EXPOSURE}.ExposureError")
    try:
        with pytest.raises(error) as refused:
            api(f"{EXPOSURE}.add_run_root")(made.store, "control", root)
    finally:
        if how == "unreadable":
            root.chmod(0o700)
    assert refused.value.context.get("refused_because") == reason
    assert api(f"{EXPOSURE}.run_roots")(made.store, "control") == []
    withheld = withheld_root(made.store, "control")
    # The log the version was written with holds nothing.
    assert (withheld / "run-roots.jsonl").read_bytes() == b""
