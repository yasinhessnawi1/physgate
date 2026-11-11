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

from pathlib import Path
from typing import Any

import pytest
from fake_messages_api import Script, text, tool
from hook_session import pinned_version, run_session

from physgate.hooks.settings import PROFILE_TOOLS

pytestmark = pytest.mark.integration

ROLE = set(PROFILE_TOOLS["role"])
REFUSED = "is not available to a role session"

#: What each pin offers a role session beyond its list, measured under the pin's own environment.
OFFERED_BEYOND: dict[str, list[str]] = {"2.1.301": [], "2.1.322": []}


def _offered(tmp_path: Path) -> tuple[list[str], dict[str, Any]]:
    run = run_session(tmp_path, Script(main=[text("end")]))
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
    beyond, _ = _offered(tmp_path)
    assert beyond == OFFERED_BEYOND[version], (version, beyond)


def test_every_tool_offered_beyond_the_list_is_refused_by_the_closed_list_hook(
    tmp_path: Path,
) -> None:
    beyond, schemas = _offered(tmp_path / "offered")
    assert beyond, "nothing beyond the list was offered, so nothing here was tested"
    calls = [tool(name, **_minimal(schemas.get(name))) for name in beyond]
    run = run_session(tmp_path / "called", Script(main=[*calls, text("end")]))
    outcome = {}
    for i, name in enumerate(beyond, start=1):
        told = run.told_after(i)
        outcome[name] = "refused by the hook" if REFUSED in told else f"told: {told[:160]!r}"
    assert outcome == dict.fromkeys(beyond, "refused by the hook"), outcome
