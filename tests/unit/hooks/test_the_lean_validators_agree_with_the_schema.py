"""The hot path's validators accept and refuse exactly what the pydantic schema does.

Every hook validates its configuration and its event with the standard library,
because importing the validation library costs more than a hook's whole time
budget. The pydantic models stay the schema. Two validators that drift apart
are the defect the state package's reviews kept finding, so this test holds
them together: on every case the configuration's own tests use, and on
thousands of generated variants, both must accept or both must refuse, and
where both accept, every field must come out the same.
"""

from __future__ import annotations

import copy
import json
import random
from pathlib import Path
from typing import Any

import pytest
from hook_helpers import config_dict, event
from pydantic import ValidationError

from physgate.hooks import lean
from physgate.hooks.config import HookInput, SessionConfig

ODD_VALUES: list[Any] = [
    None, "", "x", "/", "/a", "relative/path", " /leading-space", 0, -1, 1, 5, 15, 25, 30,
    10**12, 1.0, 2.5, True, False, [], {}, ["/a"], ["x"], [1], [None], {"path": "/a"},
    "role", "reviewer", "orchestrator", "developer", "revert", "journal", "halt", "log", "none",
    "sometimes", "\n", "/a\n", "é", "/é",
]  # fmt: skip

ID_VALUES: list[Any] = [
    "abc", "a" * 128, "a" * 129, "", "abc\n", "\nabc", "a b", "../x", "a/b", "ABC_def-09",
    "é", 123, None, True, ["abc"],
]  # fmt: skip


def _schema_config(data: bytes) -> dict[str, Any] | None:
    try:
        return SessionConfig.model_validate_json(data).model_dump(mode="json")
    except ValidationError:
        return None


def _lean_config(data: bytes) -> dict[str, Any] | None:
    try:
        config = lean.parse_config(data)
    except lean.LeanValidationError:
        return None
    out: dict[str, Any] = {name: getattr(config, name) for name in lean.LeanConfig.__slots__}
    out["protected_roots"] = [
        {"path": r.path, "reason": r.reason, "watch": r.watch} for r in config.protected_roots
    ]
    out["experiments"] = [
        {
            "root": e.root,
            "frozen_marker": e.frozen_marker,
            "always_frozen_name": e.always_frozen_name,
        }
        for e in config.experiments
    ]
    out["installation"] = {
        name: getattr(config.installation, name) for name in lean.LeanInstallation.__slots__
    }
    for name in ("held_out", "required_reading", "always_loaded", "tools_allowed"):
        out[name] = list(out[name])
    return out


def _schema_input(text: str) -> dict[str, Any] | None:
    try:
        return HookInput.model_validate_json(text).model_dump(mode="json")
    except ValidationError:
        return None


def _lean_input(text: str) -> dict[str, Any] | None:
    try:
        parsed = lean.parse_input(text)
    except lean.LeanValidationError:
        return None
    return {name: getattr(parsed, name) for name in lean.LeanInput.__slots__}


def _paths(value: Any, prefix: tuple[Any, ...] = ()) -> list[tuple[Any, ...]]:  # noqa: ANN401
    """Every location inside a JSON value, so a mutation can land anywhere."""
    out = [prefix] if prefix else []
    if isinstance(value, dict):
        for key, inner in value.items():
            out += _paths(inner, (*prefix, key))
    elif isinstance(value, list):
        for n, inner in enumerate(value):
            out += _paths(inner, (*prefix, n))
    return out


def _mutate(data: dict[str, Any], rng: random.Random, values: list[Any]) -> dict[str, Any]:
    data = copy.deepcopy(data)
    for _ in range(rng.randint(1, 3)):
        where = rng.choice(_paths(data))
        parent: Any = data
        for step in where[:-1]:
            parent = parent[step]
        key = where[-1]
        action = rng.random()
        if action < 0.25 and isinstance(parent, dict):
            del parent[key]
        elif action < 0.35 and isinstance(parent, dict):
            parent["unexpected_" + str(rng.randint(0, 9))] = rng.choice(values)
        else:
            parent[key] = copy.deepcopy(rng.choice(values))
    return data


def _agree(schema: dict[str, Any] | None, lean_: dict[str, Any] | None, raw: object) -> None:
    assert (schema is None) == (lean_ is None), (
        f"schema {'refused' if schema is None else 'accepted'} and lean "
        f"{'refused' if lean_ is None else 'accepted'}: {raw!r}"
    )
    if schema is not None:
        assert schema == lean_, raw


def test_a_valid_configuration_comes_out_the_same(tmp_path: Path) -> None:
    data = json.dumps(config_dict(tmp_path)).encode()
    schema, lean_ = _schema_config(data), _lean_config(data)
    assert schema is not None
    _agree(schema, lean_, data)


@pytest.mark.parametrize(
    "override",
    [
        {"role": None},
        {"role": ""},
        {"watchdog_seconds": 25},
        {"watchdog_seconds": 20},
        {"worktree": "relative/path"},
        {"token_ceiling": 0},
        {"token_ceiling": True},
        {"token_ceiling": 1000.0},
        {"token_ceiling": "1000"},
        {"profile": "developer"},
        {"profile": "reviewer", "role": None},
        {"surprise": 1},
        {"store_root": None},
        {"protected_roots": [{"path": "/a", "reason": "r", "watch": "sometimes"}]},
        {"protected_roots": [{"path": "/a", "reason": "", "watch": "revert"}]},
        {"protected_roots": [{"path": "/a", "reason": "r", "watch": "revert", "x": 1}]},
        {"experiments": [{"root": "/e", "frozen_marker": "", "always_frozen_name": "C"}]},
        {"held_out": "/one/path"},
    ],
)
def test_the_configurations_own_cases_are_decided_the_same(
    tmp_path: Path, override: dict[str, Any]
) -> None:
    data = json.dumps(config_dict(tmp_path, **override)).encode()
    _agree(_schema_config(data), _lean_config(data), override)


def test_thousands_of_generated_configurations_are_decided_the_same(tmp_path: Path) -> None:
    rng = random.Random(20260925)
    base = config_dict(
        tmp_path,
        experiments=[{"root": "/e", "frozen_marker": "RESULT.md", "always_frozen_name": "C.md"}],
        held_out=["/h"],
        required_reading=["/r"],
        always_loaded=["/l"],
    )
    accepted = refused = 0
    for _ in range(4000):
        variant = _mutate(base, rng, ODD_VALUES)
        data = json.dumps(variant).encode()
        schema = _schema_config(data)
        _agree(schema, _lean_config(data), variant)
        accepted, refused = accepted + (schema is not None), refused + (schema is None)
    # The generator must reach both outcomes, or the comparison saw only one side.
    assert accepted > 100 and refused > 100, (accepted, refused)


def test_malformed_bytes_are_refused_by_both(tmp_path: Path) -> None:
    for data in (b"", b"not json", b"[]", b"null", b'{"profile": "role"', b"\xff\xfe"):
        _agree(_schema_config(data), _lean_config(data), data)


def test_thousands_of_generated_events_are_decided_the_same() -> None:
    rng = random.Random(20260926)
    base = event(
        "PreToolUse",
        tool_name="Bash",
        tool_input={"command": "ls", "description": "x"},
        agent_id="a1",
        tool_response={"stdout": ""},
    )
    accepted = refused = 0
    for n in range(4000):
        variant = _mutate(base, rng, ODD_VALUES + ["PreToolUse", "Stop", "PreCompact"])
        if n % 4 == 0:
            variant["session_id"] = rng.choice(ID_VALUES)
        text = json.dumps(variant)
        schema = _schema_input(text)
        _agree(schema, _lean_input(text), variant)
        accepted, refused = accepted + (schema is not None), refused + (schema is None)
    assert accepted > 100 and refused > 100, (accepted, refused)


@pytest.mark.parametrize("session_id", ID_VALUES)
def test_every_session_identifier_shape_is_decided_the_same(session_id: object) -> None:
    text = json.dumps(event("PreToolUse", session_id=session_id))
    _agree(_schema_input(text), _lean_input(text), session_id)
