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


# The generators above change values inside a well-formed document, so they
# never reach the parser's own rules. These pieces do: escapes, surrogates,
# number spellings, control characters, a byte-order mark. Character-level
# mutation with them found three disagreements the value-level generators
# could not: bytes in UTF-16, bytes after a byte-order mark, and lone
# surrogates, all accepted by the standard library and refused by the schema.
TEXT_PIECES: list[str] = [
    *'{}[]":,\\/ \t\n\r0123456789-+.eEtrufalsn',
    "\\u0041", "\\ud800", "\\udc00", "\\ud83d\\ude00", "\\ude00\\ud83d", "\\\\ud800",
    "é", "\x00", "\x1f", "\x7f", "﻿", "\udc80", "1e400", "-0", "1.0", "NaN",
    "Infinity", "-Infinity", "true", "null",
]  # fmt: skip


def _mutate_text(text: str, rng: random.Random) -> str:
    chars = list(text)
    for _ in range(rng.randint(1, 3)):
        where, piece, action = rng.randrange(len(chars)), rng.choice(TEXT_PIECES), rng.random()
        if action < 0.4:
            chars[where] = piece
        elif action < 0.7:
            chars.insert(where, piece)
        else:
            del chars[where]
    return "".join(chars)


def _same(value: object) -> str:
    # NaN is not equal to itself, and a tool's input may hold one; compare text.
    return json.dumps(value, sort_keys=True, default=str)


def _schema_config_python(data: bytes) -> str | None:
    try:
        return _same(SessionConfig.model_validate_json(data).model_dump())
    except ValidationError:
        return None


def _lean_config_python(data: bytes) -> str | None:
    lean_ = _lean_config(data)
    return None if lean_ is None else _same(lean_)


def _schema_input_python(text: str) -> str | None:
    try:
        return _same(HookInput.model_validate_json(text).model_dump())
    except ValidationError:
        return None


def _lean_input_python(text: str) -> str | None:
    lean_ = _lean_input(text)
    return None if lean_ is None else _same(lean_)


def test_thousands_of_documents_mutated_character_by_character_are_decided_the_same(
    tmp_path: Path,
) -> None:
    rng = random.Random(20260927)
    config_text = json.dumps(
        config_dict(
            tmp_path,
            experiments=[{"root": "/e", "frozen_marker": "RESULT.md", "always_frozen_name": "C"}],
            held_out=["/h"],
        )
    )
    event_text = json.dumps(
        event("PreToolUse", tool_name="Bash", tool_input={"command": "ls", "n": 1.5}, agent_id="a")
    )
    outcomes = {"configuration": [0, 0], "event": [0, 0]}
    for n in range(6000):
        if n % 2:
            text = _mutate_text(config_text, rng)
            data = text.encode("utf-8", "surrogatepass")
            schema, lean_ = _schema_config_python(data), _lean_config_python(data)
            kind = "configuration"
        else:
            text = _mutate_text(event_text, rng)
            schema, lean_ = _schema_input_python(text), _lean_input_python(text)
            kind = "event"
        assert (schema is None) == (lean_ is None), (kind, schema is not None, text)
        assert schema == lean_, (kind, text)
        outcomes[kind][schema is None] += 1
    # Both kinds must reach both outcomes, or one side was compared on one answer.
    assert all(accepted > 100 and refused > 100 for accepted, refused in outcomes.values()), (
        outcomes
    )


def _encoded(tmp_path: Path) -> list[tuple[str, bytes]]:
    text = json.dumps(config_dict(tmp_path))
    with_role = text.replace('"role": "electrical"', '"role": "\\ud800"')
    return [
        ("utf-8", text.encode()),
        ("utf-16", text.encode("utf-16")),
        ("utf-16-le", text.encode("utf-16-le")),
        ("utf-32", text.encode("utf-32")),
        ("byte-order mark", b"\xef\xbb\xbf" + text.encode()),
        ("escaped lone surrogate", with_role.encode()),
        (
            "raw lone surrogate",
            with_role.replace("\\ud800", "\ud800").encode("utf-8", "surrogatepass"),
        ),
        ("escaped pair", text.replace('"electrical"', '"\\ud83d\\ude00"', 1).encode()),
        ("escaped backslash", text.replace('"electrical"', '"\\\\ud800"', 1).encode()),
    ]


def test_encodings_and_surrogates_are_decided_the_same(tmp_path: Path) -> None:
    cases = _encoded(tmp_path)
    for name, data in cases:
        schema, lean_ = _schema_config_python(data), _lean_config_python(data)
        assert (schema is None) == (lean_ is None), name
        assert schema == lean_, name
    # The named cases reach both outcomes, or they prove nothing about either.
    decided = {_schema_config_python(data) is None for _, data in cases}
    assert decided == {True, False}


@pytest.mark.parametrize(
    "fragment",
    [
        '"\\ud800"',
        '"\\udc00x"',
        '"\\ude00\\ud83d"',
        '"\\ud83d\\ude00"',
        '"\\\\ud800"',
        '"é"',
        # Raw, as a hook's standard input decodes undecodable bytes.
        '"\udc80"',
    ],
)
def test_a_surrogate_anywhere_in_an_event_is_decided_the_same(fragment: str) -> None:
    base = json.dumps(event("PreToolUse", tool_name="Bash", tool_input={"command": "ls"}))
    for text in (
        base.replace('"ls"', fragment),
        base[:-1] + f", {fragment}: 1}}",
        base[:-1] + f', "ignored": {fragment}}}',
    ):
        schema, lean_ = _schema_input_python(text), _lean_input_python(text)
        assert (schema is None) == (lean_ is None), text
        assert schema == lean_, text


def _chain(depth: int, rng: random.Random) -> object:
    """``depth`` nested arrays and objects around a random innermost value."""
    value: object = rng.choice([1, "s", None, [], {}, True, 1.5])
    for _ in range(depth):
        if rng.random() < 0.5:
            value = [value] if rng.random() < 0.7 else [1, value, "x"]
        else:
            value = {"k": value} if rng.random() < 0.7 else {"a": 1, "k": value}
    return value


@pytest.mark.parametrize("depth", [198, 199, 200, 201, 202])
@pytest.mark.parametrize("where", ["tool_input", "tool_response", "extra"])
@pytest.mark.parametrize("shape", ["arrays", "objects", "arrays around a value"])
def test_nesting_at_the_schemas_limit_is_decided_the_same(
    depth: int, where: str, shape: str
) -> None:
    # The schema's parser has a nesting limit and the standard library's does
    # not, below its own recursion limit. The first disagreement found was 200
    # arrays deep inside a tool's input.
    inner = {
        "arrays": "[" * depth + "]" * depth,
        "objects": '{"a":' * depth + "1" + "}" * depth,
        "arrays around a value": "[" * depth + "1" + "]" * depth,
    }[shape]
    base = json.dumps(event("PreToolUse", tool_name="Bash", tool_input={"command": "ls"}))
    text = {
        "tool_input": base.replace('{"command": "ls"}', '{"command": "ls", "x": ' + inner + "}"),
        "tool_response": base[:-1] + ', "tool_response": ' + inner + "}",
        "extra": base[:-1] + ', "zz": ' + inner + "}",
    }[where]
    schema, lean_ = _schema_input_python(text), _lean_input_python(text)
    assert (schema is None) == (lean_ is None), (depth, where, shape)
    assert schema == lean_


def test_thousands_of_generated_deep_documents_are_decided_the_same(tmp_path: Path) -> None:
    rng = random.Random(20260928)
    outcomes = [0, 0]
    config = config_dict(tmp_path)
    for n in range(1500):
        chain = _chain(rng.randint(190, 215), rng)
        if n % 3 == 0:
            data = json.dumps({**config, "surprise": chain}).encode()
            schema, lean_ = _schema_config_python(data), _lean_config_python(data)
            doc: object = data
        else:
            ev = event("PreToolUse", tool_name="Bash", tool_input={"command": "ls", "x": chain})
            if n % 3 == 1:
                ev = event("Stop", zz=chain)
            text = json.dumps(ev)
            schema, lean_ = _schema_input_python(text), _lean_input_python(text)
            doc = text[:120]
        assert (schema is None) == (lean_ is None), doc
        assert schema == lean_
        outcomes[schema is None] += 1
    assert outcomes[0] > 100 and outcomes[1] > 100, outcomes


def test_a_document_nested_past_the_standard_librarys_own_limit_is_refused_by_both() -> None:
    # Deep enough that the standard library's parser gives up with a recursion
    # error (it parsed 5,000 levels on CPython 3.12 and failed at 100,000), which
    # must become a refusal, not an exception out of the validator.
    deep = "[" * 100_000 + "]" * 100_000
    text = json.dumps(event("Stop"))[:-1] + ', "zz": ' + deep + "}"
    assert _schema_input_python(text) is None
    assert _lean_input_python(text) is None
