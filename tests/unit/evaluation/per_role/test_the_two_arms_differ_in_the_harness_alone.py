from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any

import pytest
from task_fixtures import own_task

from physgate.evaluation.per_role.arms.compare import differences, harness_total
from physgate.evaluation.tiers.task import parse_task
from physgate.hooks.settings import PROFILE_TOOLS
from physgate.orchestrator.events import EventLog, RunStarted, TokensUsed
from physgate.orchestrator.protocols import Usage
from physgate.orchestrator.role_python import RolePython
from physgate.orchestrator.run_config import RunConfig
from physgate.oslayer.probe import Present

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
        # The harness recorded neither (both None in the fixture); a raw arm that ran
        # with an interpreter or under an OS layer differs from it all the same.
        {
            "role_python": RolePython(
                path="/opt/py/bin/python3",
                resolved="/opt/py/bin/python3.12",
                version="3.12.9",
                prefix="/opt/py",
                distributions=(),
            ).model_dump()
        },
        {"os_layer": Present(mechanism="bubblewrap", claude_version="2.1.301").model_dump()},
    ],
    ids=lambda p: next(iter(p)),
)
def test_any_pin_that_differs_is_named(pin: dict[str, Any]) -> None:
    found = differences(_config(), _record(**pin), role="control", total=1000)
    assert len(found) == 1 and found[0].startswith(next(iter(pin)))


def test_a_cap_that_is_not_the_harness_s_total_is_named() -> None:
    found = differences(_config(), _record(), role="control", total=2000)
    assert found == ["cap: the harness spent 2000 tokens, the raw arm was capped at 1000"]


def _usage(input_tokens: int, output: int, cache_read: int, cache_write: int) -> Usage:
    return Usage(
        input_tokens=input_tokens,
        output_tokens=output,
        cache_read_input_tokens=cache_read,
        cache_creation_input_tokens=cache_write,
    )


def test_the_harness_total_is_every_class_of_every_message_counted_once(tmp_path: Path) -> None:
    """The raw arm's cap: decomposition, sessions and reviewers, all four token classes.

    A cap built from output tokens alone, or without the cache reads that dominate a long
    session, would hand the raw arm a fraction of the harness's budget: it would lose for
    the wrong reason. A message the stream reports twice is still one message.
    """
    log = EventLog(tmp_path / "events.jsonl", run_id="r", gate_mode="on")
    log.append(RunStarted(**log.envelope(), config_sha256="0" * 64))
    spent = [
        ("decomposition:plan", "m1", _usage(100, 20, 0, 50)),
        ("session:control-1", "m2", _usage(10, 30, 4000, 200)),
        ("session:control-1", "m2", _usage(10, 30, 4000, 200)),
        ("reviewer:control-1", "m3", _usage(7, 5, 900, 0)),
    ]
    for attribution, message_id, usage in spent:
        log.append(
            TokensUsed(
                **log.envelope(), attribution=attribution, message_id=message_id, usage=usage
            )
        )
    log.close()
    assert harness_total(tmp_path) == (100 + 20 + 50) + (10 + 30 + 4000 + 200) + (7 + 5 + 900)
