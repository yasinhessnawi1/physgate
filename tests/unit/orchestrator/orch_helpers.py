"""Builders shared by the orchestrator's tests."""

from __future__ import annotations

import itertools
from collections.abc import Callable, Iterator
from datetime import UTC, datetime, timedelta
from typing import Any

from physgate.orchestrator.managed import EMPTY_OVERRIDE_SHA256
from physgate.orchestrator.run_config import ModelStrings, RunBounds, RunConfig

SCRIPTED_BOUNDS = RunBounds(
    binary_max_retries=0,
    session_wall_clock_s=120.0,
    session_max_turns=20,
    infra_retry_delays_s=(),
)


def make_config(**overrides: Any) -> RunConfig:
    """A complete, valid run configuration, with any field replaced."""
    fields: dict[str, Any] = {
        "run_id": "run-1",
        "seed": 7,
        "brief_sha256": "a" * 64,
        "gate_mode": "on",
        "models": ModelStrings(
            decomposition="claude-sonnet-5",
            roles={"electrical": "claude-sonnet-5"},
            reviewers={"electrical": "claude-opus-5-5"},
        ),
        "bounds": SCRIPTED_BOUNDS,
        "token_ceiling": 100_000,
        "claude_version": "2.1.272",
        "target_head": "b" * 40,
        "endpoint": "default",
        "auth": "api_key",
        "managed_override_sha256": EMPTY_OVERRIDE_SHA256,
    }
    fields.update(overrides)
    return RunConfig(**fields)


def ticking_clock(start: datetime | None = None) -> Callable[[], datetime]:
    """A clock that moves one millisecond per call, so timestamps are deterministic."""
    base = start or datetime(2026, 9, 26, 12, 0, tzinfo=UTC)
    counter: Iterator[int] = itertools.count()
    return lambda: base + timedelta(milliseconds=next(counter))
