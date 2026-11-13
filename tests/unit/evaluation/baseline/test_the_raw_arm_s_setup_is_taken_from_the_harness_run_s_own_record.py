"""The raw arm's setup is the harness run's record, pin by pin: nothing is taken from elsewhere."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from physgate.evaluation.baseline.runner import BaselineError, setup_from_run
from physgate.orchestrator.credentials import Credential
from physgate.orchestrator.run_config import RunConfig
from physgate.oslayer.probe import Present

EXAMPLES = Path(__file__).parents[4] / "src/physgate/orchestrator/examples"
LAYER = Present(mechanism="bubblewrap", claude_version="2.1.301")


def _config(**changes: object) -> RunConfig:
    params = json.loads((EXAMPLES / "params.subscription.json").read_text())
    params.update(
        run_id="r",
        seed=1,
        brief_sha256="a" * 64,
        target_head="b" * 40,
        claude_version="2.1.301",
        endpoint="default",
        harness={"commit": None, "clean": False, "uncommitted_sha256": None},
        git_binary=None,
        os_layer=LAYER.model_dump(),
        network="none",
        network_enforced=True,
        held_out=["/store/control/withheld"],
        held_out_sha256=["d" * 64],
        held_out_canaries=["c" * 32],
        effort="medium",
        max_output_tokens=32000,
    )
    params["models"]["roles"]["control"] = "claude-fable-5-2"
    params.update(changes)
    return RunConfig.model_validate_json(json.dumps(params))


def _setup(config: RunConfig) -> object:
    return setup_from_run(
        config,
        "control",
        binary="claude",
        credential=Credential(mode="subscription", secret="x"),
        install_bin=Path("/i/bin/physgate"),
        os_layer=LAYER,
        role_python=None,
    )


def test_every_pin_the_run_recorded_is_the_raw_arm_s() -> None:
    config = _config()
    setup = _setup(config)
    assert setup.model == "claude-fable-5-2"  # type: ignore[attr-defined]
    assert setup.claude_version == "2.1.301"  # type: ignore[attr-defined]
    assert (setup.effort, setup.max_output_tokens) == ("medium", 32000)  # type: ignore[attr-defined]
    assert setup.thinking_display == config.thinking_display  # type: ignore[attr-defined]
    assert setup.bounds == config.bounds  # type: ignore[attr-defined]
    assert setup.held_out == ("/store/control/withheld",)  # type: ignore[attr-defined]
    assert setup.held_out_canaries == ("c" * 32,)  # type: ignore[attr-defined]
    assert setup.network == "none" and setup.base_url is None  # type: ignore[attr-defined]


def test_a_run_recorded_against_another_endpoint_is_answered_there() -> None:
    setup = _setup(_config(endpoint="http://127.0.0.1:8080"))
    assert setup.base_url == "http://127.0.0.1:8080"  # type: ignore[attr-defined]


def test_a_run_that_pinned_no_model_for_the_role_is_refused() -> None:
    config = _config()
    roles = {k: v for k, v in config.models.roles.items() if k != "control"}
    models = config.models.model_copy(update={"roles": roles})
    with pytest.raises(BaselineError, match="no model for the role"):
        _setup(config.model_copy(update={"models": models}))
