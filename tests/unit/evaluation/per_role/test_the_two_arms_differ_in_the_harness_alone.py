"""The two arms differ in the harness alone, read from what each left on disk.

Each fixture lays out a harness run directory and a raw arm's directory as the code that
writes them does: the run's configuration and event log and its role sessions' generated
settings; the raw arm's record, stream and generated settings. A fair pair differs in
nothing; each change below is one way it could differ, and is named.
"""

from __future__ import annotations

import hashlib
import json
from collections.abc import Callable
from pathlib import Path
from typing import Any

import pytest
from task_fixtures import own_task

from physgate.evaluation.per_role.arms.compare import (
    RAW_PINS,
    RUN_FIELDS,
    ComparisonError,
    differences,
    harness_total,
)
from physgate.evaluation.tiers.task import parse_task
from physgate.hooks.settings import CONFIG_NAME, PROFILE_TOOLS
from physgate.orchestrator.events import (
    EventLog,
    LeftoverRead,
    RunStarted,
    SessionSpawned,
    TokensUsed,
)
from physgate.orchestrator.protocols import Usage
from physgate.orchestrator.role_python import RolePython
from physgate.orchestrator.run_config import RunConfig
from physgate.oslayer.probe import Present

TASK = parse_task(json.dumps(own_task()).encode())
MODEL = "claude-opus-5-5"
LAYER = Present(mechanism="bubblewrap", claude_version="2.1.301")
EXAMPLES = Path(__file__).parents[4] / "src/physgate/orchestrator/examples"


def _usage(input_tokens: int, output: int, cache_read: int, cache_write: int) -> Usage:
    return Usage(
        input_tokens=input_tokens,
        output_tokens=output,
        cache_read_input_tokens=cache_read,
        cache_creation_input_tokens=cache_write,
    )


def _config(**changes: Any) -> RunConfig:
    params = json.loads((EXAMPLES / "params.subscription.json").read_text())
    params.update(
        run_id="r",
        seed=1,
        brief_sha256=hashlib.sha256(TASK.brief.encode()).hexdigest(),
        target_head="b" * 40,
        claude_version="2.1.301",
        endpoint="default",
        harness={"commit": None, "clean": False, "uncommitted_sha256": None},
        git_binary=None,
        os_layer=LAYER.model_dump(),
        network="none",
        network_enforced=True,
    )
    params.update(changes)
    return RunConfig.model_validate_json(json.dumps(params))


def _settings(path: Path, profile: str, role: str | None, tools: list[str]) -> None:
    path.mkdir(parents=True)
    body = {"profile": profile, "role": role, "tools_allowed": tools}
    (path / CONFIG_NAME).write_text(json.dumps(body))


def _spend_1000(log: EventLog) -> None:
    log.append(
        TokensUsed(
            **log.envelope(),
            attribution="session:role-1",
            message_id="m1",
            usage=_usage(100, 200, 600, 100),
        )
    )


def _harness_run(
    tmp_path: Path,
    *,
    config: RunConfig | None = None,
    tools: list[str] | None = None,
    spend: Callable[[EventLog], None] = _spend_1000,
) -> Path:
    """A harness run directory: its configuration, its log, one control session's settings."""
    run_dir = tmp_path / "run"
    run_dir.mkdir()
    (run_dir / "run.json").write_text((config or _config()).model_dump_json())
    log = EventLog(run_dir / "events.jsonl", run_id="r", gate_mode="on")
    log.append(RunStarted(**log.envelope(), config_sha256="0" * 64))
    spend(log)
    log.close()
    _settings(
        run_dir / "sessions" / "role-1" / "session",
        "role",
        "control",
        tools if tools is not None else list(PROFILE_TOOLS["role"]),
    )
    return run_dir


def _pins(**changes: Any) -> dict[str, Any]:
    """The pins the raw arm records for a session run as the harness's role sessions were."""
    config = _config()
    pins = {
        "advisor": None,
        "answer": TASK.answer.model_dump(mode="json"),
        "auth": "subscription",
        "brief_sha256": hashlib.sha256(TASK.brief.encode()).hexdigest(),
        "claude_version": "2.1.301",
        "effort": config.effort,
        "endpoint": "default",
        "held_out": [],
        "max_output_tokens": config.max_output_tokens,
        "model": MODEL,
        "network": "none",
        "os_layer": LAYER.model_dump(mode="json"),
        "role_python": None,
        "thinking_display": config.thinking_display,
    }
    pins.update(changes)
    return pins


def _raw_dir(
    tmp_path: Path,
    *,
    pins: dict[str, Any] | None = None,
    cap: int = 1000,
    answered: str = MODEL,
    profile: str = "baseline",
    tools: list[str] | None = None,
    task: str | None = None,
) -> Path:
    """A raw arm's directory: its record, its stream and its generated settings."""
    raw_dir = tmp_path / "raw"
    (raw_dir / "session").mkdir(parents=True)
    record = {"task": task or TASK.id, "cap": cap, "pins": pins if pins is not None else _pins()}
    (raw_dir / "raw.json").write_text(json.dumps(record))
    line = {"type": "assistant", "message": {"id": "m", "model": answered, "usage": {}}}
    (raw_dir / "session" / "stdout.jsonl").write_text(json.dumps(line) + "\n")
    _settings(
        raw_dir / "session" / "session",
        profile,
        None,
        tools if tools is not None else list(PROFILE_TOOLS["baseline"]),
    )
    return raw_dir


def _found(tmp_path: Path, **raw: Any) -> list[str]:
    return differences(_harness_run(tmp_path), _raw_dir(tmp_path, **raw), role="control", task=TASK)


def test_arms_pinned_alike_with_the_harness_s_total_as_cap_differ_in_nothing(
    tmp_path: Path,
) -> None:
    assert _found(tmp_path) == []


@pytest.mark.parametrize(
    "pin",
    [
        {"model": "claude-sonnet-5"},
        {"effort": "low"},
        {"max_output_tokens": 1000},
        {"thinking_display": "omitted"},
        {"network": "open"},
        {"brief_sha256": "0" * 64},
        {"claude_version": "2.1.283"},
        {"advisor": "claude-fable-5-2"},
        {"auth": "api_key"},
        {"endpoint": "http://127.0.0.1:8080"},
        {"held_out": ["/elsewhere/held-out"]},
        {"answer": {"path": "other.json", "format": "lti_tf"}},
        {
            "role_python": RolePython(
                path="/opt/py/bin/python3",
                resolved="/opt/py/bin/python3.12",
                version="3.12.9",
                prefix="/opt/py",
                distributions=(),
            ).model_dump(mode="json")
        },
        {"os_layer": Present(mechanism="seatbelt", claude_version="2.1.301").model_dump()},
    ],
    ids=lambda p: next(iter(p)),
)
def test_any_pin_that_differs_is_named(tmp_path: Path, pin: dict[str, Any]) -> None:
    name = next(iter(pin))
    assert [f.split(":", 1)[0] for f in _found(tmp_path, pins=_pins(**pin))] == [name]


def test_a_harness_run_given_another_brief_is_named(tmp_path: Path) -> None:
    """Both arms recorded the same brief, and it is not this task's: no pair of this task."""
    other = "1" * 64
    run = _harness_run(tmp_path, config=_config(brief_sha256=other))
    found = differences(
        run, _raw_dir(tmp_path, pins=_pins(brief_sha256=other)), role="control", task=TASK
    )
    assert found == ["brief: the harness run was not given this task's brief"]


def test_a_pin_the_comparison_does_not_know_is_named(tmp_path: Path) -> None:
    """A pin added to the raw arm without a decision here is a difference, not a pass."""
    assert _found(tmp_path, pins=_pins(tool_servers="none")) == [
        "tool_servers: the raw arm recorded a pin no comparison knows"
    ]


def test_a_pin_the_raw_record_lacks_is_named(tmp_path: Path) -> None:
    pins = _pins()
    del pins["advisor"]
    assert _found(tmp_path, pins=pins) == ["advisor: the raw arm's record does not carry this pin"]


def test_every_run_field_and_every_raw_pin_has_a_decision() -> None:
    """The census both ways: a new run field or raw pin fails here before any comparison."""
    assert set(RUN_FIELDS) == set(RunConfig.model_fields)
    compared = {name for name, kind in RUN_FIELDS.items() if kind == "compared"}
    # Each compared run field has its raw pin (``models`` is read for the role, as ``model``).
    assert {("model" if name == "models" else name) for name in compared} <= RAW_PINS


def test_a_run_field_with_no_decision_is_named(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from physgate.evaluation.per_role.arms import compare

    unclassed = dict(compare.RUN_FIELDS)
    del unclassed["network"]
    monkeypatch.setattr(compare, "RUN_FIELDS", unclassed)
    assert _found(tmp_path) == [
        "run.json field 'network': no decision says how it bears on the raw arm"
    ]


def test_a_raw_arm_answered_by_another_model_is_named(tmp_path: Path) -> None:
    """Read from the stream: an endpoint answering as another model, whatever the pins say."""
    assert _found(tmp_path, answered="claude-sonnet-5") == [
        "answered_by: the harness pinned 'claude-opus-5-5', "
        "the raw arm was answered by ['claude-sonnet-5']"
    ]


def test_the_tools_are_the_lists_each_arm_was_installed_with(tmp_path: Path) -> None:
    """Read from each arm's generated settings, not from a constant either arm shares."""
    assert [f.split(":", 1)[0] for f in _found(tmp_path, tools=["Bash", "Read"])] == ["tools"]
    other = tmp_path / "other"
    other.mkdir()
    run = _harness_run(other, tools=["Bash", "Read"])
    found = differences(run, _raw_dir(other), role="control", task=TASK)
    assert [f.split(":", 1)[0] for f in found] == ["tools"]


def test_a_harness_run_with_no_session_settings_for_the_role_is_named(tmp_path: Path) -> None:
    found = differences(_harness_run(tmp_path), _raw_dir(tmp_path), role="firmware", task=TASK)
    assert "tools: no firmware session of the harness run left its installed tool list" in found


def test_a_raw_arm_installed_under_another_profile_is_named(tmp_path: Path) -> None:
    assert _found(tmp_path, profile="role") == [
        "profile: the raw arm was installed as 'role', not 'baseline'"
    ]


def test_a_raw_record_of_another_task_is_named(tmp_path: Path) -> None:
    assert _found(tmp_path, task="another-task") == [
        f"task: the raw arm's record is of 'another-task', not {TASK.id!r}"
    ]


def test_a_cap_that_is_not_the_harness_s_total_is_named(tmp_path: Path) -> None:
    assert _found(tmp_path, cap=2000) == [
        "cap: the harness spent 1000 tokens, the raw arm was capped at 2000"
    ]


def test_the_harness_total_is_every_class_of_every_message_counted_once(tmp_path: Path) -> None:
    """The raw arm's cap: decomposition, sessions and reviewers, all four token classes.

    A cap built from output tokens alone, or without the cache reads that dominate a long
    session, would hand the raw arm a fraction of the harness's budget: it would lose for
    the wrong reason. A message the stream reports twice is still one message.
    """

    def spend(log: EventLog) -> None:
        for attribution, message_id, usage in [
            ("decomposition:plan", "m1", _usage(100, 20, 0, 50)),
            ("session:control-1", "m2", _usage(10, 30, 4000, 200)),
            ("session:control-1", "m2", _usage(10, 30, 4000, 200)),
            ("reviewer:control-1", "m3", _usage(7, 5, 900, 0)),
        ]:
            log.append(
                TokensUsed(
                    **log.envelope(), attribution=attribution, message_id=message_id, usage=usage
                )
            )

    run = _harness_run(tmp_path, spend=spend)
    assert harness_total(run) == (100 + 20 + 50) + (10 + 30 + 4000 + 200) + (7 + 5 + 900)


def _partial(log: EventLog) -> None:
    log.append(
        TokensUsed(
            **log.envelope(),
            attribution="session:left-1",
            message_id="m",
            usage=_usage(10, 0, 0, 0),
            partial=True,
        )
    )


def _incomplete(log: EventLog) -> None:
    log.append(
        LeftoverRead(
            **log.envelope(),
            session_id="left-1",
            stopped=True,
            complete=False,
            trajectory_seal=None,
        )
    )


def _unended(log: EventLog) -> None:
    log.append(SessionSpawned(**log.envelope(), session_id="role-2", pid=7, started="x"))


@pytest.mark.parametrize(
    ("spend", "says"),
    [(_partial, "partial"), (_incomplete, "incomplete"), (_unended, "never ended")],
    ids=["partial usage", "incomplete leftover", "spawned, never ended"],
)
def test_a_harness_total_that_cannot_count_every_token_is_refused(
    tmp_path: Path, spend: Callable[[EventLog], None], says: str
) -> None:
    run = _harness_run(tmp_path, spend=spend)
    with pytest.raises(ComparisonError, match=says):
        harness_total(run)
    with pytest.raises(ComparisonError, match=says):
        differences(run, _raw_dir(tmp_path), role="control", task=TASK)


def test_a_harness_log_that_ends_in_a_cut_off_line_is_refused(tmp_path: Path) -> None:
    run = _harness_run(tmp_path)
    with (run / "events.jsonl").open("ab") as log:
        log.write(b'{"seq": 2, "kind": "tokens_us')
    with pytest.raises(ComparisonError, match="cut-off line"):
        harness_total(run)
