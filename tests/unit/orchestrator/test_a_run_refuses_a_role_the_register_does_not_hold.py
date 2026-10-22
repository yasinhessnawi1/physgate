"""A run refuses, at its start, any role the role register does not hold.

Curated content and a promoted reviewer rubric exist for roles the loop must not yet
dispatch unsupervised: a mechanical design session owes a person's sign-off on its
sizing, and nothing builds that sign-off yet. Content existing is not a role being
ready, so a run is held to the register (``physgate.roles.ROLES``): decomposition
refuses before its one model call, and the run, its resume and the loop refuse before
anything is dispatched. Reviewing is not dispatching: the injected-error instrument
dispatches no role session, so its reviewers are not held to the register.

The suite plans ``electrical`` and ``mechanical`` stand-ins throughout, so ``conftest``
registers both for every test; the tests here take them out again.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from orch_helpers import make_config

from physgate import roles
from physgate.cli import main
from physgate.orchestrator.exceptions import RoleNotRegisteredError
from physgate.orchestrator.loop import refuse_unregistered

EXAMPLES = Path(__file__).resolve().parents[3] / "src" / "physgate" / "orchestrator" / "examples"


@pytest.fixture
def shipped(monkeypatch: pytest.MonkeyPatch) -> None:
    """The register as it ships: the suite's stand-in roles taken out."""
    for name in ("electrical", "mechanical"):
        monkeypatch.delitem(roles.ROLES, name, raising=False)


def test_the_register_ships_the_control_and_firmware_roles_only(shipped: None) -> None:
    # Read from what the module ships, not from the register this suite has added to.
    assert [role.name for role in roles.SHIPPED] == ["control", "firmware"]
    assert set(roles.ROLES) == {"control", "firmware"}


def test_an_unregistered_role_is_refused_by_name(shipped: None) -> None:
    with pytest.raises(RoleNotRegisteredError) as refused:
        roles.require_registered(["control", "mechanical", "electrical"])
    assert refused.value.context["roles"] == "electrical,mechanical"


def test_registered_roles_pass(shipped: None) -> None:
    roles.require_registered(["control", "firmware"])


def test_the_run_s_start_check_refuses_before_any_reviewer_is_looked_at(shipped: None) -> None:
    base = make_config(gate_mode="off")
    roles_with = {**base.models.roles, "mechanical": "m-implementer"}
    config = base.model_copy(
        update={"models": base.models.model_copy(update={"roles": roles_with})}
    )
    # No reviewer at all: the register is checked first, so its refusal is the one raised.
    with pytest.raises(RoleNotRegisteredError):
        refuse_unregistered(config, None, {})


def test_decomposition_refuses_before_its_model_call(
    shipped: None,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    params = json.loads((EXAMPLES / "params.api_key.json").read_text())
    assert "mechanical" in params["models"]["roles"]
    # The stand-in binary below predates the OS layer's pin: allowed absent, for development.
    params["os_layer_absent"] = "allow"
    (tmp_path / "params.json").write_text(json.dumps(params))
    (tmp_path / "brief.md").write_text("a brief\n")
    # A binary that answers only its version, the one the configuration's check accepts.
    binary = tmp_path / "bin" / "claude"
    binary.parent.mkdir()
    binary.write_text('#!/bin/sh\necho "2.1.283 (Claude Code)"\n')
    binary.chmod(0o755)
    monkeypatch.setenv("PHYSGATE_CLAUDE_BIN", str(binary))
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-not-a-key")

    def no_call(*_args: object, **_kwargs: object) -> None:
        pytest.fail("decomposition made its model call for a run it should refuse")

    monkeypatch.setattr("physgate.orchestrator.cli.call", no_call)
    code = main(
        [
            "decompose",
            str(tmp_path / "brief.md"),
            "--seed",
            "1",
            "--run-id",
            "r1",
            "--params",
            str(tmp_path / "params.json"),
            "--target",
            str(Path(__file__).resolve().parents[3]),
            "--run-dir",
            str(tmp_path / "run"),
        ]
    )
    assert code != 0
    assert "register" in capsys.readouterr().err
    assert not (tmp_path / "run").exists()
