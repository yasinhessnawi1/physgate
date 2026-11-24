"""A role session in a run root withheld whole reaches its worktree and what it is given, no more.

A measured run withholds every run root of its store whole from its sessions, by rule: the
earlier runs made there hold every canary of the store, the plans written from their briefs and
their answers. A role session's worktree lies in its own run's directory, inside one of those
roots, so the run's directory is the session's own place there. The session then reaches, of
the root, its worktree (read and write), and read only what it is given there: the directory of
its interpreter, and the files it is given to read in its own session directory (integration's
issued state, the parts record), exactly the set the session directories' own carve opens to it.
Nothing else of the root: not another file of its own session directory, not its home's files
for its tools, not its run's records, not an earlier run beside it.

A second run root of the store, which holds none of the session's, is withheld whole with nothing
opened, on the hook layer and in both OS-layer profiles. A place given with no root around the
worktree, and a root that lies in the session's own place, are refused.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from physgate.hooks import paths, shell_paths
from physgate.hooks.config import SessionConfig
from physgate.hooks.settings import InstallRequest, build_config
from physgate.hooks.settings import current_installation as installation
from physgate.hooks.shell import parse
from physgate.oslayer.policy import sandbox_policy

MARK = "marked.txt"


@pytest.fixture
def rig(tmp_path: Path) -> Path:
    root = tmp_path.resolve()
    run = root / "runs" / "run-b"
    sdir = run / "sessions" / "s1"
    for d in ("worktrees/m1", "decomposition", "sessions/s0"):
        (run / d).mkdir(parents=True)
    for d in ("state", "session", "config", "home", "bin"):
        (sdir / d).mkdir(parents=True)
    (run / "worktrees" / "m1" / "spec.md").write_text("the module's own\n")
    (sdir / "issued.json").write_text("the issued state it is given\n")
    (sdir / "other.json").write_text("its own, not given\n")
    (sdir / "home" / "given.json").write_text("in its home\n")
    (run / "run.json").write_text("the run's record\n")
    (run / "sessions" / "s0" / MARK).write_text("another session's\n")
    earlier = root / "runs" / "run-a"
    earlier.mkdir()
    (earlier / "run.json").write_text("an earlier run's record\n")
    second = root / "older-runs" / "run-z"
    second.mkdir(parents=True)
    (second / "run.json").write_text("a run under the store's other run root\n")
    return root


def _fields(root: Path, **changes: object) -> dict[str, object]:
    run = root / "runs" / "run-b"
    sdir = run / "sessions" / "s1"
    return {
        "profile": "role",
        "role": "control",
        "worktree": str(run / "worktrees" / "m1"),
        "own_branch": None,
        "store_root": None,
        "state_dir": str(sdir / "state"),
        "target_dir": str(sdir / "session"),
        "claude_config_dir": str(sdir / "config"),
        "user_home": str(sdir / "home"),
        "token_ceiling": 1000,
        "sessions_root": str(run / "sessions"),
        "required_reading": (
            str(run / "worktrees" / "m1" / "spec.md"),
            str(sdir / "issued.json"),
            str(sdir / "home" / "given.json"),
        ),
        "os_layer_readable": (str(sdir / "bin"),),
        "temp_dir": str(root / "temps" / "own"),
        "session_temps": str(root / "temps"),
        "shared_claude_temp": (str(root / "claude-temp"),),
        "withheld_whole": (str(root / "runs"), str(root / "older-runs")),
        "own_place": str(run),
    } | changes


def _config(root: Path, **changes: object) -> SessionConfig:
    return build_config(InstallRequest(**_fields(root, **changes)), installation())  # type: ignore[arg-type]


def _reads(config: SessionConfig, target: Path) -> bool:
    return paths.protection(str(target), config.worktree, config, writing=False) is None


def _shell_reads(config: SessionConfig, target: Path) -> bool:
    return not shell_paths.check(parse(f"cat {target}")[0], config.worktree, config)


def test_the_worktree_is_read_and_written(rig: Path) -> None:
    config = _config(rig)
    own = rig / "runs" / "run-b" / "worktrees" / "m1" / "spec.md"
    assert _reads(config, own) and _shell_reads(config, own)
    assert paths.protection(str(own), config.worktree, config, writing=True) is None


def test_what_it_is_given_to_read_in_its_session_directory_is_read_by_its_file_tools(
    rig: Path,
) -> None:
    config = _config(rig)
    sdir = rig / "runs" / "run-b" / "sessions" / "s1"
    assert _reads(config, sdir / "issued.json")
    # Read only: the carve opens a read, never a write.
    assert paths.protection(str(sdir / "issued.json"), config.worktree, config, writing=True)


def test_nothing_else_of_its_session_directory_or_its_home_is_read(rig: Path) -> None:
    config = _config(rig)
    sdir = rig / "runs" / "run-b" / "sessions" / "s1"
    for refused in (sdir / "other.json", sdir / "home" / "given.json", sdir / "state"):
        assert not _reads(config, refused), refused


@pytest.mark.parametrize(
    "where",
    ["runs/run-b/run.json", "runs/run-b/sessions/s0/marked.txt", "runs/run-a/run.json"],
    ids=["its run's record", "another session's file", "an earlier run's record"],
)
def test_the_rest_of_its_run_root_is_refused_to_every_route(rig: Path, where: str) -> None:
    config = _config(rig)
    target = rig / where
    assert not _reads(config, target) and not _shell_reads(config, target)


def test_a_run_root_that_holds_none_of_the_session_s_is_refused_with_nothing_opened(
    rig: Path,
) -> None:
    config = _config(rig)
    target = rig / "older-runs" / "run-z" / "run.json"
    assert not _reads(config, target) and not _shell_reads(config, target)
    (other,) = [r for r in config.protected_roots if r.path == str(rig / "older-runs")]
    assert other.read_exceptions == () and other.exceptions == () and other.watch == "none"


@pytest.mark.parametrize("platform", ["darwin", "linux"])
def test_the_os_layer_denies_both_roots_and_opens_the_worktree_alone(
    rig: Path, platform: str
) -> None:
    config = _config(rig)
    home = rig / "runs" / "run-b" / "sessions" / "s1" / "home"
    fs = sandbox_policy(
        config, home=str(home), temp_dir=str(rig / "temps" / "own"), platform=platform
    ).settings["sandbox"]["filesystem"]

    def covered(path: Path, listed: list[str]) -> bool:
        return any(str(path) == p or str(path).startswith(p.rstrip("/") + "/") for p in listed)

    for denied in ("runs/run-a/run.json", "older-runs/run-z/run.json", "runs/run-b/run.json"):
        assert covered(rig / denied, fs["denyRead"]) and not covered(rig / denied, fs["allowRead"])
    issued = rig / "runs" / "run-b" / "sessions" / "s1" / "issued.json"
    assert not covered(issued, fs["allowRead"]), "the shell is given none of its session directory"
    assert covered(rig / "runs" / "run-b" / "worktrees" / "m1" / "x", fs["allowRead"])


def _refused(root: Path, **changes: object) -> str:
    with pytest.raises(ValueError) as raised:
        _config(root, **changes)
    return str(raised.value)


def test_a_place_given_with_no_root_around_the_worktree_is_refused(rig: Path) -> None:
    assert "no root withheld whole holds" in _refused(
        rig, withheld_whole=(str(rig / "older-runs"),)
    )


def test_a_root_around_the_worktree_without_the_place_is_refused(rig: Path) -> None:
    assert "own place is not given" in _refused(rig, own_place=None)


def test_a_root_in_the_session_s_own_place_is_refused(rig: Path) -> None:
    inside = str(rig / "runs" / "run-b" / "decomposition")
    assert "own place or lies in it" in _refused(rig, withheld_whole=(str(rig / "runs"), inside))


def test_a_root_that_holds_none_of_the_session_s_needs_no_place(rig: Path) -> None:
    config = _config(rig, withheld_whole=(str(rig / "older-runs"),), own_place=None)
    assert not _reads(config, rig / "older-runs" / "run-z" / "run.json")
    assert _reads(config, rig / "runs" / "run-b" / "worktrees" / "m1" / "spec.md")


def test_its_own_records_in_the_root_are_kept_by_digest_only(rig: Path) -> None:
    """The sentinel keeps no byte of what lies in the root but the worktree, its own files too.

    Without the root its settings and its home's shell startup files lie only in the session
    directories, whose own files the sentinel keeps the bytes of and puts back. Inside a root
    withheld whole they are kept by their digest alone, as a withheld record is: one changed past
    every layer that refuses its write is not put back but halts the session (``UNRESTORABLE``).
    """
    sdir = rig / "runs" / "run-b" / "sessions" / "s1"
    own = (sdir / "session" / "settings.json", sdir / "home" / ".bashrc")
    whole, before = _config(rig), _config(rig, withheld_whole=(), own_place=None)
    for path in own:
        assert paths.read_refused(str(path), whole), path
        assert not paths.read_refused(str(path), before), path
    # The worktree stays readable, so its bytes are kept as ever.
    assert not paths.read_refused(str(rig / "runs" / "run-b" / "worktrees" / "m1" / "x"), whole)


def test_a_file_given_to_read_in_its_run_outside_the_session_directories_stays_refused(
    rig: Path,
) -> None:
    """The opening for what it is given stops at the run's session directories."""
    run = rig / "runs" / "run-b"
    plan = run / "decomposition" / "plan.md"
    plan.write_text("the run's plan, written from the brief\n")
    given = (*_fields(rig)["required_reading"], str(plan))  # type: ignore[misc]
    config = _config(rig, required_reading=given)
    assert not _reads(config, plan) and not _shell_reads(config, plan)
