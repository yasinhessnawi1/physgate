from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any

import pytest
from task_fixtures import own_task

from physgate.evaluation.per_role.arms.compare import differences
from physgate.evaluation.per_role.task import parse_task
from physgate.hooks.settings import PROFILE_TOOLS
from physgate.orchestrator.run_config import RunConfig

TASK = parse_task(json.dumps(own_task()).encode())


def _config() -> RunConfig:
    params = json.loads(
        (
            Path(__file__).parents[4]
            / "src/physgate/orchestrator/examples/params.subscription.json"
        ).read_text()
    )
    params.update(
        run_id="r",
        seed=1,
        brief_sha256=hashlib.sha256(TASK.brief.encode()).hexdigest(),
        target_head="b" * 40,
        claude_version="2.1.301",
        endpoint="default",
        harness={"commit": None, "clean": False, "uncommitted_sha256": None},
        git_binary=None,
        os_layer=None,
        network="none",
        network_enforced=None,
    )
    return RunConfig.model_validate_json(json.dumps(params))


def _record(**pins: Any) -> dict[str, Any]:
    config = _config()
    base = {
        "model": "claude-opus-5-5",
        "claude_version": config.claude_version,
        "effort": config.effort,
        "max_output_tokens": config.max_output_tokens,
        "thinking_display": config.thinking_display,
        "tools": sorted(PROFILE_TOOLS["baseline"]),
        "role_python": None,
        "network": "none",
        "os_layer": None,
        "brief_sha256": hashlib.sha256(TASK.brief.encode()).hexdigest(),
        "answer": TASK.answer.model_dump(),
    }
    base.update(pins)
    return {"pins": base, "cap": 1000}


def test_arms_pinned_alike_with_the_harness_s_total_as_cap_differ_in_nothing() -> None:
    assert differences(_config(), _record(), role="control", total=1000) == []


@pytest.mark.parametrize(
    "pin",
    [
        {"model": "claude-sonnet-5"},
        {"effort": "low"},
        {"max_output_tokens": 1000},
        {"thinking_display": "omitted"},
        {"tools": ["Bash", "Read"]},
        {"network": "open"},
        {"brief_sha256": "0" * 64},
        {"claude_version": "2.1.283"},
    ],
    ids=lambda p: next(iter(p)),
)
def test_any_pin_that_differs_is_named(pin: dict[str, Any]) -> None:
    found = differences(_config(), _record(**pin), role="control", total=1000)
    assert len(found) == 1 and found[0].startswith(next(iter(pin)))


def test_a_cap_that_is_not_the_harness_s_total_is_named() -> None:
    found = differences(_config(), _record(), role="control", total=2000)
    assert found == ["cap: the harness spent 2000 tokens, the raw arm was capped at 1000"]
