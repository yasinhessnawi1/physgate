"""The raw arm's setup is the harness run's record, pin by pin: nothing is taken from elsewhere."""

from __future__ import annotations

import json
from pathlib import Path

import baseline_fixtures  # noqa: F401 - puts the arms' task fixtures on the path
import pytest
from task_fixtures import own_task

from physgate.evaluation.baseline.runner import BaselineError, setup_from_run
from physgate.evaluation.per_role.arms.compare import _expected, _held, _same
from physgate.evaluation.per_role.arms.raw import pins
from physgate.evaluation.tiers.task import parse_task
from physgate.orchestrator.credentials import Credential
from physgate.orchestrator.run_config import RunConfig
from physgate.oslayer.probe import Present
from physgate.toolenv.record import Distribution, ToolEnvironment

EXAMPLES = Path(__file__).parents[4] / "src/physgate/orchestrator/examples"
LAYER = Present(mechanism="bubblewrap", claude_version="2.1.301")
TASK = parse_task(json.dumps(own_task()).encode())
#: A tool environment and servers as a run records them; fixture values, no real install.
ENVIRONMENT = ToolEnvironment(
    interpreter="/opt/tools/env/bin/python3",
    resolved="/opt/tools/env/bin/python3.12",
    python_version="3.12.9",
    prefix="/opt/tools/env",
    distributions=(Distribution(name="control", version="0.10.1"),),
    native_tools=(),
    roots=("/opt/tools/env",),
    manifest_digest="a" * 64,
    entries=1,
    total_bytes=0,
).model_dump(mode="json")
SERVERS = {
    "profiles": {"role": ["control"], "baseline": ["control"]},
    "max_output_tokens": 25000,
    "register_sha256": "b" * 64,
}


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
        binary={"sha256": "d" * 64, "platform": "linux-x64"},
        account={"name": params["account"], "token_sha256_prefix": "e" * 12},
        os_layer=LAYER.model_dump(),
        network="none",
        network_enforced=True,
        tool_servers=None,
        tool_search="denied",
        python_bytecode="not_written",
        held_out=["/store/control/withheld"],
        held_out_sha256=["d" * 64],
        held_out_canaries=["c" * 32],
        effort="medium",
        max_output_tokens=32000,
    )
    params["models"]["roles"]["control"] = "claude-fable-5-2"
    params.update(changes)
    return RunConfig.model_validate_json(json.dumps(params))


def _setup(config: RunConfig, base_url: str | None = None) -> object:
    return setup_from_run(
        config,
        "control",
        binary="claude",
        credential=Credential(mode="subscription", secret="x"),
        install_bin=Path("/i/bin/physgate"),
        os_layer=LAYER,
        role_python=None,
        base_url=base_url,
        harness=None,
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


def test_the_endpoint_is_the_operator_s_never_the_record_s() -> None:
    """A credential goes where the operator says; the record's endpoint is only compared."""
    recorded = _setup(_config(endpoint="http://127.0.0.1:8080"))
    assert recorded.base_url is None  # type: ignore[attr-defined]
    given = _setup(_config(endpoint="http://127.0.0.1:8080"), "http://127.0.0.1:8080")
    assert given.base_url == "http://127.0.0.1:8080"  # type: ignore[attr-defined]


def test_a_run_that_pinned_no_model_for_the_role_is_refused() -> None:
    config = _config()
    roles = {k: v for k, v in config.models.roles.items() if k != "control"}
    models = config.models.model_copy(update={"roles": roles})
    with pytest.raises(BaselineError, match="no model for the role"):
        _setup(config.model_copy(update={"models": models}))


def test_a_run_with_tools_gives_the_raw_arm_its_environment_and_servers() -> None:
    config = _config(tool_environment=ENVIRONMENT, tool_servers=SERVERS)
    setup = _setup(config)
    assert setup.tool_environment == config.tool_environment  # type: ignore[attr-defined]
    assert setup.tool_servers == config.tool_servers  # type: ignore[attr-defined]


def test_the_raw_arm_set_up_from_a_run_with_tools_is_held_equal_to_it_on_them() -> None:
    """What the raw arm records for its tools is what the comparison holds the run's to."""
    config = _config(tool_environment=ENVIRONMENT, tool_servers=SERVERS)
    recorded = pins(TASK, _setup(config))  # type: ignore[arg-type]
    expected = _expected(config, "control", TASK)
    for name in ("tool_environment", "tool_servers"):
        assert _same(name, _held(name, expected[name]), _held(name, recorded[name])), name


def test_a_run_that_named_no_tool_environment_gives_the_raw_arm_none() -> None:
    setup = _setup(_config())
    assert setup.tool_environment is None  # type: ignore[attr-defined]
    assert setup.tool_servers is None  # type: ignore[attr-defined]
