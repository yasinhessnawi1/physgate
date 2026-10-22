"""The harness runs one git, at 2.42 or later, found once and recorded with the run.

git before 2.42 ignores ``GIT_ATTR_SOURCE`` without a word, so a committed ``.gitattributes``
would choose how the harness diffs, merges and adds. The harness therefore resolves one git
binary per process: the first ``git`` on its PATH, then in ``/usr/bin``, whose version is 2.42 or
later. Every harness git command executes that path; none looks git up on PATH itself. A run
does not start without one, and the run records which one it was. A resume is held to the floor
only, never to the recorded binary.

The stand-in gits here are shell scripts that print a version line and do nothing else.
"""

from __future__ import annotations

import json
import os
import subprocess
from collections.abc import Iterator
from pathlib import Path

import pytest
from loop_fakes import FakeGate, FakeReviewer
from orch_helpers import make_config

import physgate.orchestrator.cli as orchestrator_cli
from physgate.cli import main
from physgate.orchestrator import git as orchestrator_git
from physgate.orchestrator.exceptions import GitError
from physgate.orchestrator.git import GitBinary, harness_git, resolve_git
from physgate.orchestrator.run_config import (
    RunConfig,
    harness_state,
    load_run_config,
    write_run_config,
)


def _shim(directory: Path, line: str) -> Path:
    """A stand-in ``git`` in ``directory`` that prints ``line`` and does nothing else."""
    directory.mkdir(parents=True, exist_ok=True)
    script = directory / "git"
    script.write_text(f"#!/bin/sh\nprintf '%s\\n' '{line}'\n")
    script.chmod(0o755)
    return script


@pytest.fixture
def last_directory(tmp_path: Path) -> Iterator[Path]:
    """``/usr/bin`` stood in for by a directory holding an old git, restored afterwards."""
    old = tmp_path / "usr-bin"
    _shim(old, "git version 2.39.3 (Apple Git-146)")
    saved = orchestrator_git._LAST_DIRECTORY
    orchestrator_git._LAST_DIRECTORY = str(old)
    try:
        yield old
    finally:
        orchestrator_git._LAST_DIRECTORY = saved


@pytest.fixture
def no_qualifying_git(last_directory: Path) -> Iterator[Path]:
    """A process whose PATH and last directory hold only a git older than 2.42.

    The cache is cleared so the next harness git command resolves afresh, and the suite's own
    resolution is restored afterwards.
    """
    saved = os.environ.get("PATH", "")
    os.environ["PATH"] = str(last_directory)
    harness_git.cache_clear()
    try:
        yield last_directory
    finally:
        os.environ["PATH"] = saved
        harness_git.cache_clear()
        harness_git()


def test_the_first_git_at_or_above_the_floor_is_chosen_and_an_older_one_skipped(
    tmp_path: Path, last_directory: Path
) -> None:
    old = _shim(tmp_path / "a", "git version 2.41.9")
    first = _shim(tmp_path / "b", "git version 2.42.0")
    _shim(tmp_path / "c", "git version 2.54.0")
    found = resolve_git(os.pathsep.join(str(p) for p in (old.parent, first.parent, tmp_path / "c")))
    assert found == GitBinary(path=str(first), version="2.42.0")


def test_a_version_is_compared_as_numbers_not_as_text(tmp_path: Path, last_directory: Path) -> None:
    _shim(tmp_path / "a", "git version 2.9.5")  # "2.9" sorts after "2.42" as text
    newer = _shim(tmp_path / "b", "git version 2.100.1")
    found = resolve_git(f"{tmp_path / 'a'}{os.pathsep}{tmp_path / 'b'}")
    assert found.path == str(newer)


def test_the_last_directory_is_looked_in_after_the_path(tmp_path: Path) -> None:
    last = _shim(tmp_path / "last", "git version 2.43.1")
    _shim(tmp_path / "a", "git version 2.30.0")
    saved = orchestrator_git._LAST_DIRECTORY
    orchestrator_git._LAST_DIRECTORY = str(last.parent)
    try:
        assert resolve_git(str(tmp_path / "a")) == GitBinary(path=str(last), version="2.43.1")
    finally:
        orchestrator_git._LAST_DIRECTORY = saved


def test_a_relative_entry_and_a_program_that_is_not_git_are_skipped(
    tmp_path: Path, last_directory: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _shim(tmp_path / "rel", "git version 2.50.0")
    _shim(tmp_path / "other", "not a git at all")
    good = _shim(tmp_path / "good", "git version 2.45.2")
    monkeypatch.chdir(tmp_path)
    found = resolve_git(os.pathsep.join(["", "rel", str(tmp_path / "other"), str(good.parent)]))
    assert found.path == str(good)


def test_no_git_at_or_above_the_floor_is_refused(tmp_path: Path, last_directory: Path) -> None:
    old = _shim(tmp_path / "a", "git version 2.41.0")
    with pytest.raises(GitError) as caught:
        resolve_git(str(old.parent))
    assert "2.42" in str(caught.value)
    assert str(old) in caught.value.context["found"]
    assert str(last_directory / "git") in caught.value.context["found"]


def test_the_binary_is_resolved_once_per_process(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, no_qualifying_git: Path
) -> None:
    good = _shim(tmp_path / "good", "git version 2.44.0")
    os.environ["PATH"] = str(good.parent)
    probes: list[list[str]] = []
    real_run = subprocess.run

    def recording_run(argv: list[str], **kwargs: object) -> object:
        probes.append(list(argv))
        return real_run(argv, **kwargs)  # type: ignore[call-overload]

    monkeypatch.setattr(subprocess, "run", recording_run)
    assert harness_git() == GitBinary(path=str(good), version="2.44.0")
    assert harness_git() is harness_git()
    assert probes == [[str(good), "--version"]]


def test_the_suite_s_git_is_absolute_and_at_or_above_the_floor() -> None:
    found = harness_git()
    assert Path(found.path).is_absolute()
    major, minor = (int(part) for part in found.version.split(".")[:2])
    assert (major, minor) >= (2, 42)


# --- a run records it -----------------------------------------------------------------------


def test_a_config_records_the_path_and_the_version(tmp_path: Path) -> None:
    config = make_config(git_binary=GitBinary(path="/opt/git/bin/git", version="2.54.0"))
    write_run_config(tmp_path / "run.json", config)
    recorded = json.loads((tmp_path / "run.json").read_text())
    assert recorded["git_binary"] == {"path": "/opt/git/bin/git", "version": "2.54.0"}
    assert load_run_config(tmp_path / "run.json") == config


def test_a_run_recorded_before_the_field_loads_and_keeps_its_bytes(tmp_path: Path) -> None:
    older = make_config()
    legacy = json.loads(older.model_dump_json())
    del legacy["git_binary"]
    del legacy["role_python"]  # left out of the bytes as None, as every older run has it
    del legacy["os_layer"]  # likewise
    for later in (
        "held_out",
        "held_out_canaries",
        "held_out_sha256",
        "network",
        "network_enforced",
        "queue_decisions",
        "os_layer_absent",
    ):  # recorded before these too
        del legacy[later]
    legacy_bytes = json.dumps(legacy, separators=(",", ":")).encode() + b"\n"
    # What a run recorded before the field existed holds: no mention of it at all.
    assert older.canonical_bytes() == legacy_bytes
    assert b"git_binary" not in legacy_bytes
    (tmp_path / "run.json").write_bytes(legacy_bytes)
    loaded = load_run_config(tmp_path / "run.json")
    assert loaded.git_binary is None
    assert loaded.canonical_bytes() == legacy_bytes
    assert loaded.sha256() == older.sha256()


def test_a_path_that_is_not_absolute_is_not_a_record() -> None:
    with pytest.raises(ValueError, match="git_binary"):
        RunConfig.model_validate_json(
            json.dumps(
                {
                    **json.loads(make_config().model_dump_json()),
                    "git_binary": {"path": "git", "version": "2.54.0"},
                }
            )
        )


def _checkout(root: Path) -> Path:
    root.mkdir(parents=True, exist_ok=True)
    env = {
        "PATH": "/usr/bin:/bin",
        "HOME": os.devnull,
        "GIT_CONFIG_GLOBAL": os.devnull,
        "GIT_CONFIG_NOSYSTEM": "1",
        "GIT_AUTHOR_NAME": "t",
        "GIT_AUTHOR_EMAIL": "t@example.invalid",
        "GIT_COMMITTER_NAME": "t",
        "GIT_COMMITTER_EMAIL": "t@example.invalid",
    }
    (root / "a.py").write_text("x = 1\n")
    for args in (["init", "-q", "-b", "master"], ["add", "-A"], ["commit", "-q", "-m", "one"]):
        subprocess.run(["git", "-c", "commit.gpgsign=false", *args], cwd=root, env=env, check=True)
    return root


def _refusing_claude(tmp_path: Path) -> Path:
    """A stand-in Claude Code binary that answers ``--version`` and refuses anything else."""
    script = tmp_path / "bin" / "claude"
    script.parent.mkdir(parents=True, exist_ok=True)
    calls = tmp_path / "calls.txt"
    script.write_text(
        '#!/bin/sh\nif [ "$1" = "--version" ]; then echo "2.1.272 (Claude Code)"; exit 0; fi\n'
        f'echo called >> "{calls}"\nexit 1\n'
    )
    script.chmod(0o755)
    return script


def _decompose_args(tmp_path: Path, **extra: object) -> list[str]:
    params = {
        "auth": "api_key",
        "gate_mode": "on",
        "models": {
            "decomposition": "claude-sonnet-5",
            "roles": {"electrical": "claude-sonnet-5"},
            "reviewers": {"electrical": "claude-opus-5-5"},
        },
        "bounds": {
            "binary_max_retries": 0,
            "session_wall_clock_s": 120.0,
            "session_max_turns": 20,
            "infra_retry_delays_s": [],
        },
        "token_ceiling": 100000,
        "reportable": False,
        "effort": "high",
        "max_output_tokens": 64000,
        "thinking_display": "summarized",
        "role_python": None,
        "escalation_backend": "rules",
        "queue_decisions": "record",
        # The stand-in binary predates the layer's pin: allowed absent, for development.
        "os_layer_absent": "allow",
        "held_out": [],
        "held_out_canaries": [],
        "held_out_sha256": [],
        "network": "open",
        **extra,
    }
    (tmp_path / "brief.md").write_text("Build a robot.\n")
    (tmp_path / "params.json").write_text(json.dumps(params))
    target = _checkout(tmp_path / "target")
    return [
        "decompose",
        str(tmp_path / "brief.md"),
        "--seed",
        "7",
        "--run-id",
        "run-1",
        "--params",
        str(tmp_path / "params.json"),
        "--target",
        str(target),
        "--run-dir",
        str(tmp_path / "run"),
    ]


def test_decompose_records_the_resolved_git_not_the_parameters_file_s(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    harness = _checkout(tmp_path / "harness")
    monkeypatch.setattr(orchestrator_cli, "_harness_root", lambda: harness)
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-ant-test-dummy-not-a-credential")
    monkeypatch.setenv("PHYSGATE_CLAUDE_BIN", str(_refusing_claude(tmp_path)))
    # A parameters file cannot name the git: it is measured and overrules this.
    named = {"path": "/elsewhere/git", "version": "9.9.9"}
    main(_decompose_args(tmp_path, git_binary=named))  # the call itself fails: no model here
    capsys.readouterr()
    recorded = json.loads((tmp_path / "run" / "run.json").read_text())
    assert recorded["git_binary"] == harness_git().model_dump()
    assert recorded["git_binary"] != named


def test_decompose_refuses_to_start_a_run_without_a_git_at_the_floor(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    no_qualifying_git: Path,
) -> None:
    args = _decompose_args(tmp_path)
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-ant-test-dummy-not-a-credential")
    monkeypatch.setenv("PHYSGATE_CLAUDE_BIN", str(_refusing_claude(tmp_path)))
    assert main(args) == 2
    error = json.loads(capsys.readouterr().err)
    assert error["error"].startswith("no git at 2.42 or later was found")
    assert "2.39.3" in error["found"]
    assert not (tmp_path / "run").exists()
    assert not (tmp_path / "calls.txt").exists()


def _drive_args(tmp_path: Path, command: str, run_dir: Path) -> list[str]:
    return [
        command,
        "--run-dir",
        str(run_dir),
        "--target",
        str(tmp_path / "t"),
        "--install",
        str(tmp_path / "install"),
        "--review-root",
        str(tmp_path / "rs"),
    ]


@pytest.mark.parametrize("command", ["run", "resume"])
def test_run_and_resume_refuse_without_a_git_at_the_floor(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    command: str,
) -> None:
    harness = _checkout(tmp_path / "harness")
    run_dir = tmp_path / "run"
    run_dir.mkdir()
    write_run_config(run_dir / "run.json", make_config(harness=harness_state(harness)))
    monkeypatch.setattr(orchestrator_cli, "_harness_root", lambda: harness)
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-ant-test-dummy-not-a-credential")
    monkeypatch.delenv("ANTHROPIC_BASE_URL", raising=False)
    registrations = orchestrator_cli.Registrations(
        gate=FakeGate(), reviewers={"electrical": FakeReviewer()}
    )
    old = _shim(tmp_path / "old", "git version 2.41.0")
    saved_path, saved_last = os.environ.get("PATH", ""), orchestrator_git._LAST_DIRECTORY
    os.environ["PATH"] = str(old.parent)
    orchestrator_git._LAST_DIRECTORY = str(old.parent)
    harness_git.cache_clear()
    try:
        code = main(_drive_args(tmp_path, command, run_dir), registrations)
    finally:
        os.environ["PATH"] = saved_path
        orchestrator_git._LAST_DIRECTORY = saved_last
        harness_git.cache_clear()
        harness_git()
    assert code == 2
    error = json.loads(capsys.readouterr().err)
    assert error["error"].startswith("no git at 2.42 or later was found")
    assert not (tmp_path / "install").exists() and not (run_dir / "events.jsonl").exists()


@pytest.mark.parametrize("command", ["run", "resume"])
def test_a_run_recorded_with_another_git_is_not_refused_for_it(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    command: str,
) -> None:
    harness = _checkout(tmp_path / "harness")
    run_dir = tmp_path / "run"
    run_dir.mkdir()
    elsewhere = GitBinary(path="/some/other/place/bin/git", version="2.42.0")
    assert elsewhere != harness_git()
    write_run_config(
        run_dir / "run.json",
        make_config(harness=harness_state(harness), git_binary=elsewhere),
    )
    monkeypatch.setattr(orchestrator_cli, "_harness_root", lambda: harness)
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-ant-test-dummy-not-a-credential")
    monkeypatch.delenv("ANTHROPIC_BASE_URL", raising=False)
    registrations = orchestrator_cli.Registrations(
        gate=FakeGate(), reviewers={"electrical": FakeReviewer()}
    )
    assert main(_drive_args(tmp_path, command, run_dir), registrations) == 2
    # Past the floor and the harness check, the run is stopped by the next guard in order:
    # it was never decomposed. Nothing names the git.
    error = json.loads(capsys.readouterr().err)
    assert error["error"] == "the run was never started; decompose it first"
    assert load_run_config(run_dir / "run.json").git_binary == elsewhere
