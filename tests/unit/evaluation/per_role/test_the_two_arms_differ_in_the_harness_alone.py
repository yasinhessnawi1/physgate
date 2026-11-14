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
from typing import Any, get_args

import pytest
from pydantic import BaseModel
from task_fixtures import own_task

from physgate.evaluation.per_role.arms.compare import (
    RAW_PINS,
    RUN_FIELDS,
    ComparisonError,
    _expected,
    differences,
    harness_total,
)
from physgate.evaluation.tiers.task import parse_task
from physgate.hooks.settings import CONFIG_NAME, PROFILE_TOOLS
from physgate.orchestrator.budget import REPAIR_BUDGET
from physgate.orchestrator.events import (
    RESUMABLE_HALTS,
    EventLog,
    Halted,
    IntegrationGateSkipped,
    LeftoverRead,
    RunStarted,
    SessionSpawned,
    SubtaskPlanned,
    TokensUsed,
)
from physgate.orchestrator.protocols import Usage
from physgate.orchestrator.role_python import RolePython
from physgate.orchestrator.run_config import ModelStrings, RunBounds, RunConfig
from physgate.orchestrator.usage_limit import UsageLimit
from physgate.oslayer.probe import Absent, Present

TASK = parse_task(json.dumps(own_task()).encode())
MODEL = "claude-opus-5-5"
LAYER = Present(mechanism="bubblewrap", claude_version="2.1.301")
EXAMPLES = Path(__file__).parents[4] / "src/physgate/orchestrator/examples"
#: A fixture canary, built here; it stands for no real task.
CANARY = hashlib.sha256(b"a fixture task's canary").hexdigest()[:32]
_PYTHON = RolePython(
    path="/opt/py/bin/python3",
    resolved="/opt/py/bin/python3.12",
    version="3.12.9",
    prefix="/opt/py",
    distributions=(),
)


def _digest(canaries: list[str]) -> str:
    return hashlib.sha256("\n".join(sorted(canaries)).encode()).hexdigest()


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
        # A fair pair's harness run is one whose numbers may be reported.
        reportable=True,
        harness={"commit": "c" * 40, "clean": True, "uncommitted_sha256": None},
        git_binary=None,
        os_layer=LAYER.model_dump(),
        network="none",
        network_enforced=True,
        # As the command records them: the bytes it measured, and the account by its name
        # and the fingerprint of the credential it was given.
        binary={"sha256": "d" * 64, "platform": "linux-x64"},
        account={"name": params["account"], "token_sha256_prefix": "e" * 12},
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


def _nothing_planned(log: EventLog) -> None:
    log.append(IntegrationGateSkipped(**log.envelope(), reason="nothing_planned", subtasks=()))


def _harness_run(
    tmp_path: Path,
    *,
    config: RunConfig | None = None,
    tools: list[str] | None = None,
    spend: Callable[[EventLog], None] = _spend_1000,
    end: Callable[[EventLog], None] | None = _nothing_planned,
) -> Path:
    """A harness run directory: its configuration, its log, one control session's settings.

    The log is a run's that ended (``end`` writes its last line); ``end=None`` leaves the
    run where ``spend`` left it.
    """
    run_dir = tmp_path / "run"
    run_dir.mkdir()
    (run_dir / "run.json").write_text((config or _config()).model_dump_json())
    log = EventLog(run_dir / "events.jsonl", run_id="r", gate_mode="on")
    log.append(RunStarted(**log.envelope(), config_sha256="0" * 64))
    spend(log)
    if end is not None:
        end(log)
    log.close()
    _settings(
        run_dir / "sessions" / "role-1" / "session",
        "role",
        "control",
        tools if tools is not None else list(PROFILE_TOOLS["role"]),
    )
    return run_dir


def _bounds(**changes: Any) -> dict[str, Any]:
    """The bounds the raw arm records: the harness's retries, its turns and clock multiplied."""
    bounds = _config().bounds
    recorded: dict[str, Any] = {
        "binary_max_retries": bounds.binary_max_retries,
        "infra_retry_delays_s": list(bounds.infra_retry_delays_s),
        "session_max_turns": bounds.session_max_turns * REPAIR_BUDGET,
        "session_wall_clock_s": bounds.session_wall_clock_s * REPAIR_BUDGET,
    }
    recorded.update(changes)
    return recorded


def _pins(**changes: Any) -> dict[str, Any]:
    """The pins the raw arm records for a session run as the harness's role sessions were."""
    config = _config()
    pins: dict[str, Any] = {
        "advisor": None,
        "answer": TASK.answer.model_dump(mode="json"),
        "auth": "subscription",
        "bounds": _bounds(),
        "brief_sha256": hashlib.sha256(TASK.brief.encode()).hexdigest(),
        "claude_version": "2.1.301",
        "effort": config.effort,
        "endpoint": "default",
        "held_out": [],
        "held_out_carved": None,
        "held_out_canaries_sha256": _digest([]),
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


def _models_in(annotation: Any) -> list[type[BaseModel]]:
    if isinstance(annotation, type) and issubclass(annotation, BaseModel):
        return [annotation]
    return [model for arg in get_args(annotation) for model in _models_in(arg)]


def _paths(model: type[BaseModel], prefix: str = "") -> set[str]:
    """Every field of ``model`` by its path, and every field of every model nested in it."""
    found = set()
    for name, field in model.model_fields.items():
        found.add(prefix + name)
        for inner in _models_in(field.annotation):
            found |= _paths(inner, f"{prefix}{name}.")
    return found


def test_every_run_field_and_every_raw_pin_has_a_decision() -> None:
    """The census both ways, nested fields too: a new one fails here before any comparison."""
    assert set(RUN_FIELDS) == _paths(RunConfig)
    compared = {name.split(".")[0] for name, kind in RUN_FIELDS.items() if kind == "compared"}
    # Each compared run field has its raw pin (``models.roles`` is read for the role, as
    # ``model``, and the canaries are compared as their digest).
    pin = {"models": "model", "held_out_canaries": "held_out_canaries_sha256"}
    assert {pin.get(name, name) for name in compared} <= RAW_PINS


def test_the_models_a_run_may_call_are_classed_one_by_one() -> None:
    """The role's model is compared; the reviewers' and the decomposition's are the harness."""
    assert {name: RUN_FIELDS.get(f"models.{name}") for name in ModelStrings.model_fields} == {
        "decomposition": "harness",
        "roles": "compared",
        "reviewers": "harness",
    }


class _AdvisedModels(ModelStrings):
    advisor: str | None = None


class _AdvisedConfig(RunConfig):
    models: _AdvisedModels


class _HeldBounds(RunBounds):
    session_max_tools: int = 0


class _HeldConfig(RunConfig):
    bounds: _HeldBounds


class _VenvPython(RolePython):
    venv: str | None = None


class _VenvConfig(RunConfig):
    role_python: _VenvPython | None


@pytest.mark.parametrize(
    ("config", "path"),
    [
        (_AdvisedConfig, "models.advisor"),
        (_HeldConfig, "bounds.session_max_tools"),
        (_VenvConfig, "role_python.venv"),
    ],
    ids=["an advisor model", "a new bound", "inside an optional model"],
)
def test_a_nested_run_field_with_no_decision_is_named(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, config: type[RunConfig], path: str
) -> None:
    """A field added inside a nested model is named as one added at the top level is."""
    from physgate.evaluation.per_role.arms import compare

    monkeypatch.setattr(compare, "RunConfig", config)
    assert _found(tmp_path) == [
        f"run.json field {path!r}: no decision says how it bears on the raw arm"
    ]


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


@pytest.mark.parametrize(
    ("changes", "named"),
    [
        ({"reportable": False}, ["reportable"]),
        ({"reportable": False, "ablation": True}, ["ablation", "reportable"]),
        (
            {
                "reportable": False,
                "harness": {"commit": "c" * 40, "clean": False, "uncommitted_sha256": "d" * 64},
            },
            ["harness", "reportable"],
        ),
        (
            {
                "reportable": False,
                "harness": {"commit": None, "clean": False, "uncommitted_sha256": None},
            },
            ["harness", "reportable"],
        ),
    ],
    ids=["not reportable", "ablation", "dirty checkout", "no checkout"],
)
def test_a_harness_run_that_is_not_clean_or_not_reportable_is_named(
    tmp_path: Path, changes: dict[str, Any], named: list[str]
) -> None:
    """A development run is no arm to hold a baseline to, however alike the two ran."""
    run = _harness_run(tmp_path, config=_config(**changes))
    found = differences(run, _raw_dir(tmp_path), role="control", task=TASK)
    assert sorted(f.split(":", 1)[0] for f in found) == named


def test_both_arms_canaries_are_compared_as_digests(tmp_path: Path) -> None:
    """The raw arm looked for the canaries the harness run looked for, or the pair is named."""
    run = _harness_run(tmp_path, config=_config(held_out_canaries=[CANARY]))
    same = _raw_dir(tmp_path, pins=_pins(held_out_canaries_sha256=_digest([CANARY])))
    assert differences(run, same, role="control", task=TASK) == []
    other = tmp_path / "other"
    other.mkdir()
    none = _raw_dir(other, pins=_pins())
    assert differences(run, none, role="control", task=TASK) == [
        f"held_out_canaries_sha256: the harness ran with {_digest([CANARY])!r}, "
        f"the raw arm with {_digest([])!r}"
    ]


@pytest.mark.parametrize(
    "bounds",
    [
        _bounds(binary_max_retries=2),
        _bounds(session_max_turns=_config().bounds.session_max_turns),
        _bounds(session_wall_clock_s=_config().bounds.session_wall_clock_s),
    ],
    ids=[
        "the binary's retries",
        "turns not multiplied",
        "clock not multiplied",
    ],
)
def test_bounds_other_than_the_harness_s_are_named(tmp_path: Path, bounds: dict[str, Any]) -> None:
    """Only the turns and the wall clock differ, and only by the repair budget."""
    found = _found(tmp_path, pins=_pins(bounds=bounds))
    assert [f.split(":", 1)[0] for f in found] == ["bounds"]
    assert found[0].startswith("bounds: the harness ran with ")


def _halted(log: EventLog) -> None:
    log.append(Halted(**log.envelope(), reason="incident", detail="held_out_read"))


@pytest.mark.parametrize("end", [_nothing_planned, _halted], ids=["integration skipped", "halted"])
def test_a_harness_total_is_taken_from_a_run_that_ended(
    tmp_path: Path, end: Callable[[EventLog], None]
) -> None:
    assert harness_total(_harness_run(tmp_path, end=end)) == 1000


def _planned_then_spend(log: EventLog) -> None:
    log.append(
        SubtaskPlanned(
            **log.envelope(),
            subtask_id="s",
            spec_path="specs/s.md",
            assigned_role="control",
            module_dir="modules/s",
        )
    )
    _spend_1000(log)


@pytest.mark.parametrize(
    "spend",
    [_spend_1000, _planned_then_spend],
    ids=["killed before its plan", "killed with a subtask open (a review, between sessions)"],
)
def test_a_harness_total_of_a_run_that_never_ended_is_refused(
    tmp_path: Path, spend: Callable[[EventLog], None]
) -> None:
    """Reviewer and decomposition calls spawn no session: the run's own end is what counts."""
    run = _harness_run(tmp_path, spend=spend, end=None)
    with pytest.raises(ComparisonError, match="has not ended"):
        harness_total(run)
    with pytest.raises(ComparisonError, match="has not ended"):
        differences(run, _raw_dir(tmp_path), role="control", task=TASK)


def test_a_harness_total_of_an_empty_log_is_refused(tmp_path: Path) -> None:
    run = _harness_run(tmp_path)
    (run / "events.jsonl").write_bytes(b"")
    with pytest.raises(ComparisonError, match="empty"):
        harness_total(run)


@pytest.mark.parametrize("reason", sorted(RESUMABLE_HALTS))
def test_a_harness_total_of_a_run_halted_for_a_resume_is_refused(
    tmp_path: Path, reason: str
) -> None:
    """A resume continues the same attempt and spends more: the halt is no end of its spending."""
    # A halt on the usage limit carries the limit it met, and no other halt does.
    limit = UsageLimit(resets="1:20pm (Europe/Oslo)") if reason == "usage_limit" else None

    def halted(log: EventLog) -> None:
        log.append(
            Halted(**log.envelope(), reason=reason, detail="x", usage_limit=limit)  # type: ignore[arg-type]
        )

    run = _harness_run(tmp_path, end=halted)
    with pytest.raises(ComparisonError, match="halted for a resume"):
        harness_total(run)


def test_the_retry_delays_are_not_held_against_the_raw_arm(tmp_path: Path) -> None:
    """The raw session makes no infrastructure retry; its delays decide nothing it does."""
    assert RUN_FIELDS["bounds.infra_retry_delays_s"] == "not_compared"
    assert _found(tmp_path, pins=_pins(bounds=_bounds(infra_retry_delays_s=[60.0]))) == []


def _schema_paths(schema: dict[str, Any], node: dict[str, Any], prefix: str = "") -> set[str]:
    """Every field's path, read from the model's JSON schema: another reading than the code's.

    The schema is pydantic's own description of the model, so a field the comparison's walk of
    the model's annotations would miss (in a union, a container, an optional) is still here.
    """
    found: set[str] = set()
    for name, prop in node.get("properties", {}).items():
        found.add(prefix + name)
        for ref in _refs(prop):
            target = schema["$defs"][ref.rsplit("/", 1)[-1]]
            found |= _schema_paths(schema, target, f"{prefix}{name}.")
    return found


def _refs(node: Any) -> list[str]:  # noqa: ANN401 - any part of a JSON schema
    if isinstance(node, dict):
        own = [node["$ref"]] if "$ref" in node else []
        return own + [r for key, value in node.items() if key != "$ref" for r in _refs(value)]
    if isinstance(node, list):
        return [r for item in node for r in _refs(item)]
    return []


def test_the_census_is_every_field_the_run_s_schema_names() -> None:
    """The census is held to the schema of the record, not to a copy of the code's own walk."""
    schema = RunConfig.model_json_schema()
    assert set(RUN_FIELDS) == _schema_paths(schema, schema)


def test_every_required_field_is_one_the_comparison_checks() -> None:
    """A field classed as required has a check behind it, named by a row above."""
    assert {name for name, kind in RUN_FIELDS.items() if kind == "required"} == {
        "harness",
        "harness.clean",
        "reportable",
    }


@pytest.mark.parametrize(
    "parent",
    sorted(
        {
            p.split(".")[0]
            for p in RUN_FIELDS
            if "." in p and RUN_FIELDS[p.split(".")[0]] == "compared"
        }
    ),
)
def test_each_compared_nested_field_is_in_what_the_raw_arm_is_held_to(parent: str) -> None:
    """A nested field classed compared is a key of the expected pin, so it is compared in fact.

    Read over a run with each form a nested model may take (the OS layer present and absent),
    so every member of a union is seen.
    """
    configs = [
        _config(role_python=_PYTHON.model_dump(mode="json")),
        _config(
            os_layer=Absent(reason="none here", no_os_protection=False).model_dump(),
            network_enforced=False,
            reportable=False,
        ),
    ]
    keys = {key for config in configs for key in _expected(config, "control", TASK)[parent] or {}}
    compared = {
        p.split(".", 1)[1]
        for p, kind in RUN_FIELDS.items()
        if p.startswith(f"{parent}.") and kind == "compared"
    }
    assert compared and compared <= keys, (parent, compared, keys)


class _HeldBoundsCompared(RunBounds):
    session_max_tools: int = 9


class _HeldCompared(RunConfig):
    bounds: _HeldBoundsCompared


def test_a_new_bound_classed_compared_is_compared(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Built from the bounds' own fields: a bound added and classed is held, never skipped."""
    from physgate.evaluation.per_role.arms import compare

    monkeypatch.setattr(compare, "RunConfig", _HeldCompared)
    # The run's record read as one whose bounds hold the new field, at its default.
    monkeypatch.setattr(
        compare,
        "load_run_config",
        lambda path: _HeldCompared.model_validate_json(path.read_bytes()),
    )
    monkeypatch.setattr(
        compare, "RUN_FIELDS", {**compare.RUN_FIELDS, "bounds.session_max_tools": "compared"}
    )
    assert [f.split(":", 1)[0] for f in _found(tmp_path)] == ["bounds"]


def test_a_nested_pin_no_decision_names_is_a_difference(tmp_path: Path) -> None:
    """A bound the raw arm recorded that no run field classes is kept, so it is named."""
    found = _found(tmp_path, pins=_pins(bounds=_bounds(session_max_tools=9)))
    assert [f.split(":", 1)[0] for f in found] == ["bounds"]
