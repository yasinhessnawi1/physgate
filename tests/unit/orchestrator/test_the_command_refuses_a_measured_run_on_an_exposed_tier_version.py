"""The command refuses a measured run on an exposed tier version at decompose, run and resume.

Every requirement is shown the run's resolved directory, at each of the three, so the
evaluation can hold a measured run to the run roots its register scans. The refusal comes
through the command as every other requirement's does, before any session is made.
"""

from __future__ import annotations

import hashlib
import json
import subprocess
import sys
from pathlib import Path

import pytest

EXPOSURE_TESTS = Path(__file__).resolve().parents[1] / "evaluation" / "exposure"
if str(EXPOSURE_TESTS) not in sys.path:
    sys.path.insert(0, str(EXPOSURE_TESTS))

from exposure_fixtures import StandInStore, api, stand_in_store  # noqa: E402
from orch_helpers import CLEAN_HARNESS  # noqa: E402
from test_a_role_session_runs_only_inside_the_os_layer_unless_allowed import (  # noqa: E402
    PRESENT,
    _recorded,
    _through_the_command,
)
from test_the_physgate_command_starts_and_decides import (  # noqa: E402
    PARAMS,
    _decompose_args,
    fake_binary,
)

import physgate.evaluation.requirements as evaluation_requirements  # noqa: E402
from physgate.cli import main  # noqa: E402
from physgate.evaluation.tiers.heldout import tier_digest  # noqa: E402
from physgate.orchestrator import cli  # noqa: E402
from physgate.orchestrator.requirements import RunFacts  # noqa: E402

EXPOSURE = "physgate.evaluation.tiers.exposure"


def _seen(monkeypatch: pytest.MonkeyPatch) -> list[RunFacts]:
    seen: list[RunFacts] = []

    def stop(facts: RunFacts) -> str | None:
        seen.append(facts)
        return "stopped to look at what a requirement is shown"

    monkeypatch.setattr(evaluation_requirements, "REQUIREMENTS", (stop,))
    return seen


def _decompose(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, params: dict[str, object]
) -> list[str]:
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-ant-test-dummy-not-a-credential")
    monkeypatch.setenv("PHYSGATE_CLAUDE_BIN", str(fake_binary(tmp_path, "2.1.272")))
    # The harness and the target as a checkout with a commit, wherever the suite runs from (a
    # copy of the tree without its history, too).
    monkeypatch.setattr(cli, "harness_state", lambda _root: CLEAN_HARNESS)
    args = _decompose_args(tmp_path, params)
    args[args.index("--run-dir") + 1] = str(tmp_path / "runs" / "run")
    args[args.index("--target") + 1] = str(_target(tmp_path / "target"))
    return args


def _target(repo: Path) -> Path:
    """A target repository with one commit."""
    repo.mkdir()
    env = {
        "PATH": "/usr/bin:/bin",
        "HOME": str(repo),
        "GIT_AUTHOR_NAME": "t",
        "GIT_AUTHOR_EMAIL": "t@example.invalid",
        "GIT_COMMITTER_NAME": "t",
        "GIT_COMMITTER_EMAIL": "t@example.invalid",
    }
    (repo / "README.md").write_text("a target\n")
    for argv in (["git", "init", "-q", "-b", "main"], ["git", "add", "-A"]):
        subprocess.run(argv, cwd=repo, env=env, check=True)
    subprocess.run(["git", "commit", "-q", "-m", "fixture"], cwd=repo, env=env, check=True)
    return repo


def test_a_requirement_is_shown_the_run_s_directory_at_decompose(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    seen = _seen(monkeypatch)
    assert main(_decompose(tmp_path, monkeypatch, PARAMS)) == 2
    assert len(seen) == 1, f"the requirements were not asked once: {capsys.readouterr().err}"
    (facts,) = seen
    assert getattr(facts, "run_dir", None) == (tmp_path / "runs" / "run").resolve()


@pytest.mark.parametrize("command", ["run", "resume"])
def test_a_requirement_is_shown_the_run_s_directory_at_run_and_resume(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, command: str
) -> None:
    seen = _seen(monkeypatch)
    _recorded(tmp_path, os_layer=PRESENT)
    code, spawned = _through_the_command(tmp_path, monkeypatch, command, PRESENT)
    assert code == 2 and spawned == []
    assert len(seen) == 1, "the requirements were not asked once"
    (facts,) = seen
    assert getattr(facts, "run_dir", None) == (tmp_path / "run").resolve()


def _exposed(tmp_path: Path) -> StandInStore:
    made = stand_in_store(tmp_path / "s")
    api(f"{EXPOSURE}.mark_exposed")(
        made.store, "control", made.version, by="a person", reason="opened the tier by hand"
    )
    return made


def _held(made: StandInStore) -> dict[str, tuple[str, ...]]:
    return {
        "held_out": made.held_out,
        "held_out_sha256": tuple(tier_digest(Path(root)) for root in made.held_out),
        "held_out_canaries": made.canaries,
    }


def test_a_new_run_on_an_exposed_version_is_refused_before_anything_is_written(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    made = _exposed(tmp_path)
    (tmp_path / "runs").mkdir()
    api(f"{EXPOSURE}.add_run_root")(made.store, "control", tmp_path / "runs")
    monkeypatch.setattr(cli, "harness_state", lambda _root: CLEAN_HARNESS)
    monkeypatch.setattr(cli, "judge_here", lambda **_: PRESENT)
    held = {name: list(value) for name, value in _held(made).items()}
    params = {**PARAMS, "reportable": True, "os_layer_absent": "refuse", **held}
    args = _decompose(tmp_path, monkeypatch, params)
    (tmp_path / "brief.md").write_text(made.tasks["visible"][0].brief)
    assert main(args) == 2
    error = json.loads(capsys.readouterr().err.strip().splitlines()[-1])
    assert "(version_exposed)" in str(error.get("requirements")), error
    assert not (tmp_path / "runs" / "run").exists()


@pytest.mark.parametrize("command", ["run", "resume"])
def test_a_recorded_run_on_an_exposed_version_is_refused_before_any_session(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    command: str,
) -> None:
    made = _exposed(tmp_path)
    monkeypatch.setattr(cli, "harness_state", lambda _root: CLEAN_HARNESS)
    brief = hashlib.sha256(made.tasks["visible"][0].brief.encode()).hexdigest()
    events = _recorded(
        tmp_path,
        reportable=True,
        harness=CLEAN_HARNESS,
        os_layer=PRESENT,
        brief_sha256=brief,
        **_held(made),
    )
    api(f"{EXPOSURE}.add_run_root")(made.store, "control", tmp_path / "run")
    code, spawned = _through_the_command(tmp_path, monkeypatch, command, PRESENT)
    error = json.loads(capsys.readouterr().err.strip().splitlines()[-1])
    assert code == 2 and spawned == []
    assert error.get("error") == "the run may not continue"
    assert "(version_exposed)" in str(error.get("requirements")), error
    assert (tmp_path / "run" / "events.jsonl").read_bytes() == events
    assert not (tmp_path / "run" / "sessions").exists()


def _prepared_trial(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, made: StandInStore
) -> tuple[list[str], Path]:
    """A measured decompose into a trial the round driver prepared: its target's clone inside."""
    (tmp_path / "runs").mkdir()
    api(f"{EXPOSURE}.add_run_root")(made.store, "control", tmp_path / "runs")
    monkeypatch.setattr(cli, "harness_state", lambda _root: CLEAN_HARNESS)
    monkeypatch.setattr(cli, "judge_here", lambda **_: PRESENT)
    held = {name: list(value) for name, value in _held(made).items()}
    params = {**PARAMS, "reportable": True, "os_layer_absent": "refuse", **held}
    args = _decompose(tmp_path, monkeypatch, params)
    (tmp_path / "brief.md").write_text(made.tasks["visible"][0].brief)
    trial = tmp_path / "runs" / "round-a" / "0000-1"
    trial.mkdir(parents=True)
    given = args[args.index("--target") + 1]
    subprocess.run(
        ["git", "clone", "--quiet", "--no-hardlinks", "--", given, str(trial / "target")],
        check=True,
    )
    (trial / "review").mkdir()
    args[args.index("--target") + 1] = str(trial / "target")
    args[args.index("--run-dir") + 1] = str(trial)
    return args, trial / "target"


@pytest.mark.parametrize(
    "how", ["as a round prepares it", "nested deeper than the check allows", "holding run.json"]
)
def test_a_measured_decompose_meets_its_own_prepared_trial_as_the_target_check_says(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    how: str,
) -> None:
    made = stand_in_store(tmp_path / "s")
    args, target = _prepared_trial(tmp_path, monkeypatch, made)
    if how == "nested deeper than the check allows":
        (target / ".git" / "a" / "b" / "c" / "d" / "e" / "f").mkdir(parents=True)
    elif how == "holding run.json":
        (target / ".git" / "old").mkdir()
        (target / ".git" / "old" / "run.json").write_text("{}")
    checked = api(f"{EXPOSURE}.prepared_target_refusal")(target)
    main(args)
    lines = capsys.readouterr().err.strip().splitlines()
    told = str(json.loads(lines[-1]).get("requirements")) if lines else ""
    # The version refusal reads the register before the decomposition's first record, so it
    # walks the trial, clone and all: the check a launch calls says beforehand what it meets.
    if how == "as a round prepares it":
        assert checked is None
        assert "(register_unreadable)" not in told and "tier version" not in told, told
    else:
        assert checked is not None
        assert "(register_unreadable)" in told, told
