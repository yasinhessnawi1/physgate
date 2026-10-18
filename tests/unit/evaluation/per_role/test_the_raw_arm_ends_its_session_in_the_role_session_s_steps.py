"""The raw arm ends its session with the role session's own steps, in the role session's order.

The role session's end is read from the dispatcher's source (the order its end steps are
called in), the raw arm's from a run of it with each step spied on. The raw arm may only add
scrubbing (it scrubs its error output as well as its stream); it may not drop, reorder or
replace a step.
"""

from __future__ import annotations

import ast
import inspect
import json
import textwrap
from pathlib import Path
from typing import Any

import pytest
from task_fixtures import own_task
from test_the_raw_arm_s_credential_is_handled_as_a_role_session_s import LEAKY, _script, _setup

from physgate.evaluation.per_role.arms import raw
from physgate.evaluation.per_role.task import parse_task
from physgate.orchestrator.dispatch import ClaudeDispatcher

END_STEPS = ("check_after_stop", "remove_secrets", "redact")


def _role_order() -> list[str]:
    source = textwrap.dedent(inspect.getsource(ClaudeDispatcher._run_session))
    calls = [
        node
        for node in ast.walk(ast.parse(source))
        if isinstance(node, ast.Call)
        and isinstance(node.func, ast.Name)
        and node.func.id in END_STEPS
    ]
    return [c.func.id for c in sorted(calls, key=lambda c: (c.lineno, c.col_offset))]  # type: ignore[attr-defined]


def test_the_raw_arm_takes_the_role_session_s_end_steps_in_order(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    role = _role_order()
    assert role == ["check_after_stop", "remove_secrets", "redact"]
    seen: list[str] = []
    for name in END_STEPS:
        real = getattr(raw, name)

        def spy(*a: Any, _real: Any = real, _name: str = name, **k: Any) -> Any:  # noqa: ANN401
            seen.append(_name)
            return _real(*a, **k)

        monkeypatch.setattr(raw, name, spy)
    task = parse_task(json.dumps(own_task()).encode())
    raw.run_raw(
        task, _setup(tmp_path, _script(tmp_path / "claude", LEAKY)), tmp_path / "w", cap=10**9
    )
    assert seen[: len(role)] == role
    assert set(seen[len(role) :]) <= {"redact"}
