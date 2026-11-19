"""``skills: off`` is an ablation run's arm: it leaves out the role's skill file and nothing else.

A run takes ``skills: off`` only as an ablation run: a run that is not one is refused at its
configuration by a rule that names the arm, so the product can never set it and no reportable
number is measured without the skill library.

Under the arm every role session of the run is installed as under ``skills: on`` but for the
role's skill file: it leaves the files the session must read before it acts and the always-loaded
set. It is not withheld, since no worktree of the run holds it (decomposition puts none into the
target), so the installation gains nothing in its place. The cross standards file and the role's
own standards file stay in both sets, so the reading rule still refuses every call until they are
read, and the ceiling is measured on them. Nothing else of the installation moves, so the arm
differs from the full harness in the skill file alone, and under ``skills: on`` every session is
installed exactly as before the switch existed.
"""

from __future__ import annotations

import json
import subprocess
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest
from design_review_rig import outcome_of
from orch_helpers import CLEAN_HARNESS, SCRIPTED_BOUNDS, make_config

import physgate.flags as flags
from physgate.knowledge import loader
from physgate.orchestrator import dispatch, run_config
from physgate.orchestrator.credentials import Credential
from physgate.orchestrator.dispatch import ClaudeDispatcher
from physgate.orchestrator.ports import SessionRequest
from physgate.orchestrator.run_config import RunConfig

ROLE = "control"
SPEC = ".physgate/specs/s1.md"


def _config(**fields: Any) -> Any:  # noqa: ANN401 - a configuration, or why there is none
    return outcome_of(lambda: make_config(**({"harness": CLEAN_HARNESS} | fields)))


def test_both_values_of_the_skills_switch_are_built() -> None:
    assert run_config.BUILT["skills"] == flags.SKILLS.values


def test_an_ablation_run_takes_skills_off() -> None:
    config = _config(skills="off", ablation=True)
    assert isinstance(config, RunConfig), config
    assert config.skills == "off"
    assert b'"skills":"off"' in config.canonical_bytes()


@pytest.mark.parametrize("reportable", [False, True])
def test_a_run_that_is_not_an_ablation_is_refused_skills_off_by_a_rule_that_names_it(
    reportable: bool,
) -> None:
    refused = _config(skills="off", ablation=False, reportable=reportable)
    assert not isinstance(refused, RunConfig), refused
    assert "skills: off is an ablation arm" in str(refused)
    # The same run with the skill library is a run.
    assert isinstance(_config(ablation=False, reportable=reportable), RunConfig)


def test_the_register_says_which_runs_take_skills_off() -> None:
    meaning = flags.SKILLS.meanings["off"]
    assert "only an ablation run takes it" in meaning
    assert "until the arm is built" not in meaning


def _given(skills: str) -> Any:  # noqa: ANN401 - what a role session is given to read
    reading = getattr(loader, "session_reading", None)
    assert reading is not None, "the loader names no session's reading by the skills switch"
    return reading(ROLE, Path(SPEC), skills=skills)


def test_with_skills_on_a_session_reads_exactly_what_it_always_read() -> None:
    given = _given("on")
    assert given.required == loader.required_reading(ROLE, Path(SPEC))
    assert given.always_loaded == loader.always_loaded(ROLE)


def test_a_session_s_reading_names_what_it_reads_and_nothing_to_withhold() -> None:
    # One mechanism for the arm: the file is left out of the target, never withheld in place.
    assert loader.SessionReading._fields == ("required", "always_loaded")


def test_with_skills_off_only_the_skill_file_leaves_what_is_read() -> None:
    on, off = _given("on"), _given("off")
    skill = loader.DEFAULT_ROOT / ROLE / loader.SKILL_NAME
    standards = (
        loader.DEFAULT_ROOT / loader.CROSS / loader.STANDARDS_NAME,
        loader.DEFAULT_ROOT / ROLE / loader.STANDARDS_NAME,
    )
    assert skill not in off.required, "the skill file is still required reading under skills: off"
    assert skill not in off.always_loaded, "the skill file is still always loaded under skills: off"
    assert off.always_loaded == standards
    assert set(off.required) == set(on.required) - {skill}
    assert Path(SPEC) in off.required


def test_the_cross_role_has_no_skill_file_so_skills_off_changes_nothing_it_reads() -> None:
    reading = getattr(loader, "session_reading", None)
    assert reading is not None, "the loader names no session's reading by the skills switch"
    on = reading(loader.CROSS, Path(SPEC), skills="on")
    off = reading(loader.CROSS, Path(SPEC), skills="off")
    assert off == on


def _install_argv(tmp_path: Path, monkeypatch: pytest.MonkeyPatch, config: RunConfig) -> list[str]:
    seen: list[list[str]] = []

    def fake_run(argv: list[str], **_kw: Any) -> subprocess.CompletedProcess[str]:  # noqa: ANN401
        seen.append(argv)
        out = {"settings": "s", "config": "c", "spawn_args": [], "spawn_env": {}}
        return subprocess.CompletedProcess(argv, 0, json.dumps(out), "")

    monkeypatch.setattr(subprocess, "run", fake_run)
    monkeypatch.setattr(dispatch, "session_protected_roots", lambda *_a: ((), ()))
    monkeypatch.setattr(dispatch, "harness_protection", lambda: [])
    dispatcher = ClaudeDispatcher(
        config=config,
        run=SimpleNamespace(  # type: ignore[arg-type]
            subtask_branch=lambda subtask, _reopen=0: f"b/{subtask}", run_dir=tmp_path / "run"
        ),
        store_root=tmp_path / "store",
        install_bin=tmp_path / "install" / "bin" / "physgate",
        binary="claude",
        base_url=None,
        credential=Credential(mode="api_key", secret="not-a-key"),
        review_root=tmp_path / "reviews",
    )
    request = SessionRequest(
        subtask_id="s1",
        attempt=1,
        assigned_role=ROLE,
        spec_path=SPEC,
        module_dir="modules/control",
        model="claude-opus-5-5",
        repair_instruction=None,
        bounds=SCRIPTED_BOUNDS,
    )
    temp = Path("/var/tmp/pgs/0123456789")
    dispatcher._install(request, tmp_path / "worktree", tmp_path / "sdir", temp, own_temp=temp)
    return seen[0]


def _values(argv: list[str], flag: str) -> list[str]:
    return [argv[i + 1] for i, arg in enumerate(argv) if arg == flag]


def _without(argv: list[str], pairs: set[tuple[str, str]]) -> list[str]:
    """``argv`` with each named option and its value taken out."""
    out: list[str] = []
    skip = False
    for i, arg in enumerate(argv):
        if skip:
            skip = False
            continue
        if i + 1 < len(argv) and (arg, argv[i + 1]) in pairs:
            skip = True
            continue
        out.append(arg)
    return out


def _skills(value: str) -> RunConfig:
    # The configuration as the run recorded it; its own rows above judge the arm.
    return make_config().model_copy(update={"skills": value, "ablation": value == "off"})


def test_with_skills_on_every_role_session_reads_exactly_what_it_read_before_the_switch(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    argv = _install_argv(tmp_path, monkeypatch, _skills("on"))
    worktree = tmp_path / "worktree"
    skill = str(worktree / "knowledge" / ROLE / "skill.md")
    # The installer is given what the loader's two sets have always named, in their order.
    assert _values(argv, "--reading") == [
        str(worktree / p) for p in loader.required_reading(ROLE, Path(SPEC))
    ]
    assert _values(argv, "--always-loaded") == [
        str(worktree / p) for p in loader.always_loaded(ROLE)
    ]
    assert skill not in _values(argv, "--withheld")


def test_with_skills_off_every_role_session_reads_the_standards_and_is_withheld_nothing_more(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    argv = _install_argv(tmp_path, monkeypatch, _skills("off"))
    worktree = tmp_path / "worktree"
    skill = str(worktree / "knowledge" / ROLE / "skill.md")
    standards = [
        str(worktree / "knowledge" / "cross" / "standards.md"),
        str(worktree / "knowledge" / ROLE / "standards.md"),
    ]
    assert skill not in _values(argv, "--reading"), "the skill file is still required reading"
    assert skill not in _values(argv, "--always-loaded"), "the skill file is still always loaded"
    assert skill not in _values(argv, "--withheld"), "the skill file is withheld in place"
    assert _values(argv, "--always-loaded") == standards
    assert set(standards) | {str(worktree / SPEC)} <= set(_values(argv, "--reading"))
    # The run's own withheld records stay withheld beside it.
    assert str(tmp_path / "run" / "run.json") in _values(argv, "--withheld")


def test_skills_off_changes_nothing_else_a_role_session_is_installed_with(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    on = _install_argv(tmp_path / "on", monkeypatch, _skills("on"))
    off = _install_argv(tmp_path / "off", monkeypatch, _skills("off"))
    skill_on = str(tmp_path / "on" / "worktree" / "knowledge" / ROLE / "skill.md")
    skill_off = str(tmp_path / "off" / "worktree" / "knowledge" / ROLE / "skill.md")
    rest_on = _without(on, {("--reading", skill_on), ("--always-loaded", skill_on)})
    assert len(rest_on) == len(on) - 4
    assert skill_off not in off, "skills: off names the skill file to the installer"
    assert [a.replace(str(tmp_path / "on"), "@") for a in rest_on] == [
        a.replace(str(tmp_path / "off"), "@") for a in off
    ], "skills: off installs a role session otherwise than on does, beyond the skill file"
