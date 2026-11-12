"""The two arms held equal: everything the raw arm is pinned to, against the harness run's.

The comparison is fair only if the raw arm differs from the harness arm in the harness
alone. Every pin is compared with what the harness run recorded, and the raw arm's token
cap with the harness run's own total on the same task and trial. Any difference is named.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from physgate.hooks.settings import PROFILE_TOOLS
from physgate.orchestrator.accounting import TokenAccount
from physgate.orchestrator.events import read_events
from physgate.orchestrator.run_config import RunConfig


def harness_total(run_dir: Path) -> int:
    """Every token the harness run spent, each message once: roles, reviewers, decomposition."""
    return TokenAccount.from_events(read_events(run_dir / "events.jsonl")).total().total()


def differences(
    config: RunConfig, raw_record: dict[str, Any], *, role: str, total: int
) -> list[str]:
    """Each way the raw arm's recorded pins differ from the harness run's; none is fair."""
    pins = raw_record["pins"]
    expected: dict[str, Any] = {
        "model": config.models.roles.get(role),
        "claude_version": config.claude_version,
        "effort": config.effort,
        "max_output_tokens": config.max_output_tokens,
        "thinking_display": config.thinking_display,
        "tools": sorted(PROFILE_TOOLS["role"]),
        "role_python": None if config.role_python is None else config.role_python.model_dump(),
        "network": config.network,
        "os_layer": None if config.os_layer is None else config.os_layer.model_dump(),
        "brief_sha256": config.brief_sha256,
    }
    found = [
        f"{name}: the harness ran with {want!r}, the raw arm with {pins.get(name)!r}"
        for name, want in expected.items()
        if pins.get(name) != want
    ]
    if raw_record["cap"] != total:
        found.append(
            f"cap: the harness spent {total} tokens, the raw arm was capped at {raw_record['cap']}"
        )
    return found
