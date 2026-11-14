"""Every tool a role session is offered beyond its closed list is refused, on each pin.

Newer binaries offer tools 2.1.301 did not (the Monitor tool when traffic is off, tool search
behind a custom API address, fork subagents), and a tool the list never names is one a hook
might never see. Here the binary's own list is read twice, from its first stream event and
from the tools its first request offers, under the pin's own environment; each pin's list is
recorded as measured; and a session that calls every offered tool beyond the role's list, one
after another, through the real tool path, is told each time by the closed-list hook that the
tool is not available.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest
from fake_messages_api import Script, text, tool
from hook_session import RIG_SWITCHES_2_1_301, pinned_version, run_session

from physgate.hooks.settings import PROFILE_TOOLS

pytestmark = pytest.mark.integration

ROLE = set(PROFILE_TOOLS["role"])
REFUSED = "is not available to a role session"
#: How the binary itself answers a call it refuses before any hook: its own check of the input.
INPUT_REFUSED = "<tool_use_error>"

#: Measured on CI (linux-x64, 12.11.2026): what each pin offers a role session beyond its list,
#: under the pin's own switches, and under the traffic-off switches 2.1.301's sessions carry.
#: The two web tools are no longer among them on either pin: a session's settings now deny
#: both, and a tool the settings deny is not offered. The settings deny the binary's search tool
#: too (14.11.2026), so 2.1.322 no longer offers it or its placeholder for deferred tools, and
#: sends every tool's schema with the request (measured on macOS, to be confirmed on CI).
_BEYOND_2_1_301 = [
    "Agent", "CronCreate", "CronDelete", "CronList", "EnterWorktree", "ExitWorktree",
    "ListAgents", "ReportFindings", "ScheduleWakeup", "SendMessage", "Skill", "Task",
    "TaskStop", "Workflow",
]  # fmt: skip
_NEW_SINCE_2_1_301 = ["Monitor"]
_ONLY_WITH_TRAFFIC = ["DesignSync", "PushNotification"]
OFFERED_BEYOND: dict[str, list[str]] = {
    "2.1.301": _BEYOND_2_1_301,
    "2.1.322": sorted([*_BEYOND_2_1_301, *_NEW_SINCE_2_1_301, *_ONLY_WITH_TRAFFIC]),
}
OFFERED_BEYOND_TRAFFIC_OFF: dict[str, list[str]] = {
    "2.1.301": _BEYOND_2_1_301,
    "2.1.322": sorted([*_BEYOND_2_1_301, *_NEW_SINCE_2_1_301]),
}
#: Per pin, the tools whose call with a minimal input the binary refuses itself, before any hook
#: is asked (an input its own check rejects, a job or skill that does not exist, no such tool).
REFUSED_BY_INPUT_CHECK: dict[str, list[str]] = {
    "2.1.301": [
        "CronCreate", "CronDelete", "ExitWorktree", "Skill", "Task", "TaskStop", "WebFetch",
        "WebSearch", "Workflow",
    ],
    "2.1.322": [
        "CronCreate", "CronDelete", "ExitWorktree", "Monitor", "Skill", "Task", "TaskStop",
        "Workflow",
    ],
}  # fmt: skip


def _offered(
    tmp_path: Path, switches: dict[str, str] | None = None
) -> tuple[list[str], dict[str, Any]]:
    run = run_session(tmp_path, Script(main=[text("end")]), switches=switches)
    assert run.exit_code == 0, run.stderr
    (init,) = [e for e in run.stream if e.get("type") == "system" and e.get("subtype") == "init"]
    first = run.api.requests[0]
    names = set(init.get("tools") or []) | set(first.offered_tools)
    return sorted(names - ROLE), first.tool_schemas


def _minimal(schema: Any) -> dict[str, Any]:  # noqa: ANN401 - a JSON schema
    """An input with each required field filled with the simplest value of its type."""
    if not isinstance(schema, dict):
        return {}
    props = schema.get("properties") or {}
    filled: dict[str, Any] = {}
    for name in schema.get("required") or []:
        spec = props.get(name) or {}
        kind = spec.get("type")
        if "enum" in spec:
            filled[name] = spec["enum"][0]
        elif kind in ("integer", "number"):
            filled[name] = 1
        elif kind == "boolean":
            filled[name] = False
        elif kind == "array":
            filled[name] = []
        elif kind == "object":
            filled[name] = {}
        else:
            filled[name] = "x"
    return filled


def test_each_pin_offers_a_role_session_what_was_measured_beyond_its_list(tmp_path: Path) -> None:
    version = pinned_version()
    beyond, _ = _offered(tmp_path / "own")
    off, _ = _offered(tmp_path / "off", dict(RIG_SWITCHES_2_1_301))
    measured = {"own": beyond, "traffic off": off}
    expected = {"own": OFFERED_BEYOND[version], "traffic off": OFFERED_BEYOND_TRAFFIC_OFF[version]}
    assert measured == expected, json.dumps({version: measured})


def test_every_tool_offered_beyond_the_list_is_refused_by_the_closed_list_hook(
    tmp_path: Path,
) -> None:
    beyond, schemas = _offered(tmp_path / "offered")
    assert beyond, "nothing beyond the list was offered, so nothing here was tested"
    calls = [tool(name, **_minimal(schemas.get(name))) for name in beyond]
    run = run_session(tmp_path / "called", Script(main=[*calls, text("end")]))
    outcome: dict[str, str] = {}
    said: dict[str, Any] = {}
    for i, name in enumerate(beyond, start=1):
        told = run.told_after(i)
        if REFUSED in told:
            outcome[name] = "refused by the hook"
        elif told.startswith(INPUT_REFUSED):
            outcome[name] = "refused by the binary's input check"
            said[name] = {"told": told[:300], "schema": schemas.get(name)}
        else:
            outcome[name] = f"told: {told[:200]}"
    # Every call is refused before its tool runs: by the closed-list hook, or, where a minimal
    # input fails the binary's own check, by that check before any hook is asked.
    version = pinned_version()
    expected = {
        name: "refused by the binary's input check"
        if name in REFUSED_BY_INPUT_CHECK[version]
        else "refused by the hook"
        for name in beyond
    }
    assert outcome == expected, json.dumps({version: outcome, "input check": said})


#: A valid input for each tool new since 2.1.301, so the call passes the binary's own check and
#: reaches the hooks. The fields are the ones the binary's own check named as required (CI,
#: 11.11.2026, when 2.1.322 still deferred these tools and sent no schema for them).
VALID_INPUT: dict[str, dict[str, Any]] = {
    "Monitor": {"command": "true", "description": "x"},
    "DesignSync": {"method": "list_projects"},
    "PushNotification": {"message": "x"},
}
NEW_TOOLS = ("Monitor", "DesignSync", "PushNotification")


def test_each_tool_new_since_2_1_301_given_a_valid_input_is_refused_by_the_closed_list_hook(
    tmp_path: Path,
) -> None:
    beyond, schemas = _offered(tmp_path / "offered")
    offered = [name for name in NEW_TOOLS if name in beyond]
    if pinned_version() == "2.1.301":
        assert offered == []  # none of them exists on 2.1.301
        return
    assert offered == list(NEW_TOOLS), offered
    calls = [tool(name, **VALID_INPUT.get(name, {})) for name in offered]
    run = run_session(tmp_path / "called", Script(main=[*calls, text("end")]))
    told = {name: run.told_after(i) for i, name in enumerate(offered, start=1)}
    # The refusal's words are the closed-list hook's own: PreToolUse ran for the tool.
    outcome = {name: REFUSED in said for name, said in told.items()}
    shown = {name: {"told": said[:900], "schema": schemas.get(name)} for name, said in told.items()}
    assert outcome == dict.fromkeys(offered, True), json.dumps(shown)
