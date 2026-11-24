"""A round goes on only on the code, the client and the tools it began with.

The harness checkout (its commit, and anything not committed) and every field the census holds
equal across a tier's runs that the command measures afresh for each run (the client binary's
bytes and platform, its version, the git, the role sessions' interpreter, the tool environment
and its servers, the endpoint, the tool search) are measured as the round starts, recorded in its
ledger's first line, and measured again at every restart: a restart on anything else is refused
before any step, naming what differs, and not after the round is spent at the census. The census's
other fields are the parameters', held by their digest, or the trial's own. A run continued on
other code is two runs under one name, and so is a round. A round is refused before anything is
written on a checkout that is not clean.
"""

from __future__ import annotations

import inspect
import json
from pathlib import Path
from typing import Any

import pytest
from round_rig import SCORED, Killed, Rig, StandInDriver, make_rig

from physgate.evaluation import harness_round
from physgate.evaluation.harness_round import (
    HARNESS_ROUNDS,
    LEDGER,
    ROUND_RECORD,
    RoundError,
    run_round,
)
from physgate.evaluation.tiers.store import withheld_root


def _score(_task: Any, _answer: Path) -> dict[str, Any]:  # noqa: ANN401
    return dict(SCORED)


def _round(rig: Rig, driver: StandInDriver, *, resume: bool = False) -> Any:  # noqa: ANN401
    return run_round(
        rig.inputs(trials=2), driver=driver, scorer=_score, resume=resume, sleep=lambda _: None
    )


def _place(rig: Rig) -> Path:
    summary = json.loads((rig.root / "out" / ROUND_RECORD).read_bytes())
    return withheld_root(rig.made.store, "control") / HARNESS_ROUNDS / str(summary["round"])


def _first_line(rig: Rig) -> dict[str, Any]:
    return dict(json.loads((_place(rig) / LEDGER).read_bytes().splitlines()[0]))


def _killed_once(rig: Rig) -> bytes:
    with pytest.raises(Killed):
        _round(rig, rig.driver(killed={2}))
    return (_place(rig) / LEDGER).read_bytes()


def test_the_round_records_the_code_and_client_it_began_with(tmp_path: Path) -> None:
    rig = make_rig(tmp_path)
    driver = rig.driver()
    _round(rig, driver)
    assert _first_line(rig).get("pins") == driver.pins(rig.inputs(trials=2))


@pytest.mark.parametrize(
    ("change", "named"),
    [
        (lambda p: p["harness"].update(commit="d" * 40), "harness.commit"),
        (lambda p: p["harness"].update(clean=False, uncommitted_sha256="e" * 64), "harness.clean"),
        (lambda p: p["binary"].update(sha256="f" * 64), "binary.sha256"),
        (lambda p: p.update(claude_version="2.1.999"), "claude_version"),
        (
            lambda p: p.update(git_binary={"path": "/usr/bin/git", "version": "2.50.0"}),
            "git_binary",
        ),
        (lambda p: p.update(role_python={"path": "/opt/py/bin/python3"}), "role_python"),
        (lambda p: p.update(tool_environment={"manifest_sha256": "a" * 64}), "tool_environment"),
        (lambda p: p.update(tool_servers={"register_sha256": "b" * 64}), "tool_servers"),
        (lambda p: p.update(endpoint="custom"), "endpoint"),
        (lambda p: p.update(tool_search="offered"), "tool_search"),
    ],
)
def test_a_restart_on_other_code_or_another_client_is_refused_naming_what_differs(
    tmp_path: Path, change: Any, named: str
) -> None:  # noqa: ANN401
    rig = make_rig(tmp_path)
    held = _killed_once(rig)
    later = rig.driver()
    change(later.pin_record)
    with pytest.raises(RoundError) as refused:
        _round(rig, later, resume=True)
    assert refused.value.context["refused_because"] == "harness_differs"
    assert named in refused.value.context["fields"].split(",")
    assert later.decomposed == [] and later.drives == []
    assert (_place(rig) / LEDGER).read_bytes() == held


def test_a_restart_on_the_same_code_and_client_goes_on(tmp_path: Path) -> None:
    rig = make_rig(tmp_path)
    _killed_once(rig)
    status, _ = _round(rig, rig.driver(), resume=True)
    assert status == "done"


def test_a_round_on_a_checkout_that_is_not_clean_is_refused_before_anything_is_written(
    tmp_path: Path,
) -> None:
    rig = make_rig(tmp_path)
    driver = rig.driver()
    driver.pin_record["harness"].update(clean=False, uncommitted_sha256="e" * 64)
    with pytest.raises(RoundError) as refused:
        _round(rig, driver)
    assert refused.value.context["refused_because"] == "harness_not_clean"
    assert not (rig.root / "out").exists() and list(rig.run_root.iterdir()) == []
    assert driver.decomposed == []


def test_every_field_the_census_holds_equal_is_pinned_or_held_by_the_parameters_or_the_trial() -> (
    None
):
    from physgate.evaluation.observe.compare import DRIFT

    pinned = set(getattr(harness_round, "PINNED", ()))
    by_parameters = set(getattr(harness_round, "FROM_THE_PARAMETERS", ()))
    by_trial = set(getattr(harness_round, "THE_TRIAL_S_OWN", ()))
    assert pinned | by_parameters | by_trial == set(DRIFT)
    assert not (pinned & by_parameters) and not (pinned & by_trial)
    assert not (by_parameters & by_trial)
    for measured in ("git_binary", "role_python", "tool_environment", "tool_servers"):
        assert measured in pinned
    for measured in ("endpoint", "tool_search", "binary", "claude_version"):
        assert measured in pinned


class _Measured:
    """What a stood-in measurement gives: a record that dumps as its field's name."""

    def __init__(self, name: str) -> None:
        self.name = name

    def model_dump(self, mode: str = "python") -> dict[str, str]:  # noqa: ARG002
        return {"measured": self.name}


def _measurements_stood_in(monkeypatch: pytest.MonkeyPatch) -> dict[str, Any]:
    """Every measurement the command makes for a run, stood in where it is defined."""
    seen: dict[str, Any] = {}

    def measured(name: str) -> Any:  # noqa: ANN401
        def measure(*args: Any, **kwargs: Any) -> _Measured:  # noqa: ANN401
            seen[name] = (args, kwargs)
            return _Measured(name)

        return measure

    for where, name in (
        ("physgate.orchestrator.binaries.measure", "binary"),
        ("physgate.orchestrator.git.harness_git", "git_binary"),
        ("physgate.orchestrator.role_python.measure", "role_python"),
        ("physgate.orchestrator.tool_environment.measure_named", "tool_environment"),
        ("physgate.orchestrator.tool_environment.recorded_servers", "tool_servers"),
        ("physgate.orchestrator.run_config.harness_state", "harness"),
    ):
        monkeypatch.setattr(where, measured(name))
    monkeypatch.setattr("physgate.orchestrator.invocation.claude_binary", lambda: "/bin/claude")
    monkeypatch.setattr("physgate.orchestrator.decompose.binary_version", lambda _b: "2.1.322")
    monkeypatch.setattr("physgate.orchestrator.run_config.endpoint_of", lambda _u: "default")
    monkeypatch.setattr("physgate.hooks.settings.session_tool_search", lambda: "denied")
    return seen


def test_the_command_driver_measures_every_pinned_field_as_the_command_does(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from physgate.evaluation.harness_round import CommandDriver

    assert "inputs" in inspect.signature(CommandDriver.pins).parameters, "pins reads no inputs"
    rig = make_rig(tmp_path)
    fields = json.loads(rig.params.read_bytes())
    fields.update(role_python="/opt/py/bin/python3", tool_environment={"interpreter": "/x"})
    rig.params.write_text(json.dumps(fields))
    seen = _measurements_stood_in(monkeypatch)
    pins = CommandDriver().pins(rig.inputs())
    assert set(pins) == {"harness", *harness_round.PINNED}
    assert pins["claude_version"] == "2.1.322"
    assert pins["endpoint"] == "default" and pins["tool_search"] == "denied"
    for name in ("harness", "binary", "git_binary", "role_python", "tool_environment"):
        assert pins[name] == {"measured": name}
    assert pins["tool_servers"] == {"measured": "tool_servers"}
    assert seen["role_python"][0] == ("/opt/py/bin/python3",)
    assert seen["tool_environment"][0] == ({"interpreter": "/x"},)


def test_a_round_whose_parameters_name_no_tools_pins_them_as_none(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from physgate.evaluation.harness_round import CommandDriver

    assert "inputs" in inspect.signature(CommandDriver.pins).parameters, "pins reads no inputs"
    rig = make_rig(tmp_path)
    seen = _measurements_stood_in(monkeypatch)
    pins = CommandDriver().pins(rig.inputs())
    assert (pins["role_python"], pins["tool_environment"], pins["tool_servers"]) == (
        None,
        None,
        None,
    )
    assert not {"role_python", "tool_environment", "tool_servers"} & set(seen)
