"""The command refuses a measured run on an exposed tier version at decompose, run and resume.

Every requirement is shown the run's resolved directory, at each of the three, so the
evaluation can hold a measured run to the run roots its register scans. The refusal comes
through the command as every other requirement's does, before any session is made.
"""

from __future__ import annotations

import hashlib
import json
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
    args = _decompose_args(tmp_path, params)
    args[args.index("--run-dir") + 1] = str(tmp_path / "runs" / "run")
    return args


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
