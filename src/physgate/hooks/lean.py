"""The hot path's validators: the same rules as the pydantic schema, without pydantic.

Every agent tool call starts a hook process, and a hook has 200 ms. Importing
the validation library and building its models cost several times that on the
development machine, so on this one path the session configuration and the
event description are validated here, with the standard library only.

**The pydantic models in** :mod:`physgate.hooks.config` **stay the schema.** The
generator validates the configuration with them when it writes it, and the
configuration is then protected by its digest. This module must accept and
refuse exactly the inputs they do; a test compares the two on the existing
cases and on thousands of generated ones, and a change to either that makes
them disagree fails it. Two validators drifting apart is the class of defect
the state package's reviews kept finding, which is why this one is held to the
other by a test and not by care.
"""

from __future__ import annotations

import hashlib
import hmac
import json
import os
import re
from typing import TYPE_CHECKING

from physgate.hooks.exceptions import HookError, SessionConfigMismatchError

if TYPE_CHECKING:
    from collections.abc import Mapping
    from typing import Any

EVENTS = (
    "SessionStart",
    "PreToolUse",
    "PostToolUse",
    "PostToolUseFailure",
    "Stop",
    "SessionEnd",
)
PROFILES = ("role", "reviewer", "orchestrator")
WATCHES = ("revert", "journal", "halt", "log", "none")
WATCHDOG_MARGIN_SECONDS = 10
_SESSION_ID = re.compile(r"[A-Za-z0-9_-]{1,128}")
_SURROGATE = re.compile("[\ud800-\udfff]")
_SURROGATE_ESCAPE = re.compile(r"\\u[dD][89a-fA-F]")


class LeanValidationError(HookError):
    """The configuration or the event description is not valid."""


def _fail(where: str, why: str) -> LeanValidationError:
    return LeanValidationError(f"{where}: {why}")


def _object(
    value: object, where: str, fields: tuple[str, ...], optional: tuple[str, ...] = ()
) -> dict[str, Any]:
    if not isinstance(value, dict):
        raise _fail(where, "must be an object")
    extra = set(value) - set(fields) - set(optional)
    if extra:
        raise _fail(where, f"unknown field {sorted(extra)[0]!r}")
    missing = [f for f in fields if f not in value]
    if missing:
        raise _fail(where, f"missing field {missing[0]!r}")
    return value


def _string(value: object, where: str, *, min_length: int = 0) -> str:
    if not isinstance(value, str):
        raise _fail(where, "must be a string")
    if len(value) < min_length:
        raise _fail(where, f"must be at least {min_length} characters")
    return value


def _absolute(value: object, where: str) -> str:
    text = _string(value, where, min_length=2)
    if not text.startswith("/"):
        raise _fail(where, "must be an absolute path")
    return text


def _optional(value: object, where: str, check: Any) -> Any:  # noqa: ANN401 - mirrors the check
    return None if value is None else check(value, where)


def _positive_int(value: object, where: str) -> int:
    # Strict: a boolean is not an integer and a float is not one either.
    if isinstance(value, bool) or not isinstance(value, int):
        raise _fail(where, "must be an integer")
    if value <= 0:
        raise _fail(where, "must be greater than 0")
    return value


def _choice(value: object, where: str, choices: tuple[str, ...]) -> str:
    if not isinstance(value, str) or value not in choices:
        raise _fail(where, f"must be one of {', '.join(choices)}")
    return value


def _strings(value: object, where: str, check: Any) -> tuple[Any, ...]:  # noqa: ANN401
    if not isinstance(value, list):
        raise _fail(where, "must be an array")
    return tuple(check(item, f"{where}[{n}]") for n, item in enumerate(value))


class LeanRoot:
    """A protected root."""

    __slots__ = ("path", "reason", "watch")

    def __init__(self, raw: object, where: str) -> None:
        """Validate one root."""
        data = _object(raw, where, ("path", "reason", "watch"))
        self.path: str = _absolute(data["path"], f"{where}.path")
        self.reason: str = _string(data["reason"], f"{where}.reason", min_length=1)
        self.watch: str = _choice(data["watch"], f"{where}.watch", WATCHES)


class LeanExperiment:
    """The frozen-experiment rule."""

    __slots__ = ("always_frozen_name", "frozen_marker", "root")

    def __init__(self, raw: object, where: str) -> None:
        """Validate one rule."""
        data = _object(raw, where, ("root", "frozen_marker", "always_frozen_name"))
        self.root: str = _absolute(data["root"], f"{where}.root")
        self.frozen_marker: str = _string(
            data["frozen_marker"], f"{where}.frozen_marker", min_length=1
        )
        self.always_frozen_name: str = _string(
            data["always_frozen_name"], f"{where}.always_frozen_name", min_length=1
        )


class LeanInstallation:
    """Where the hook code runs from."""

    __slots__ = ("base_prefix", "environment_root", "interpreter", "package_dir")

    def __init__(self, raw: object, where: str) -> None:
        """Validate the installation."""
        fields = ("interpreter", "package_dir", "environment_root", "base_prefix")
        data = _object(raw, where, fields)
        self.interpreter: str = _absolute(data["interpreter"], f"{where}.interpreter")
        self.package_dir: str = _absolute(data["package_dir"], f"{where}.package_dir")
        self.environment_root: str = _absolute(
            data["environment_root"], f"{where}.environment_root"
        )
        self.base_prefix: str = _absolute(data["base_prefix"], f"{where}.base_prefix")


_CONFIG_FIELDS = (
    "profile", "role", "worktree", "own_branch", "store_root", "state_dir", "protected_roots",
    "experiments", "held_out", "required_reading", "always_loaded", "token_ceiling",
    "tools_allowed", "installation", "watchdog_seconds", "hook_timeout_seconds",
)  # fmt: skip


class LeanConfig:
    """The session configuration, validated with the same rules as the schema."""

    __slots__ = _CONFIG_FIELDS

    def __init__(self, raw: object) -> None:
        """Validate a parsed configuration."""
        data = _object(raw, "configuration", _CONFIG_FIELDS)
        self.profile: str = _choice(data["profile"], "profile", PROFILES)
        self.role: str | None = _optional(data["role"], "role", _string)
        self.worktree: str = _absolute(data["worktree"], "worktree")
        self.own_branch: str | None = _optional(data["own_branch"], "own_branch", _string)
        self.store_root: str | None = _optional(data["store_root"], "store_root", _absolute)
        self.state_dir: str = _absolute(data["state_dir"], "state_dir")
        self.protected_roots: tuple[LeanRoot, ...] = _strings(
            data["protected_roots"], "protected_roots", LeanRoot
        )
        self.experiments: tuple[LeanExperiment, ...] = _strings(
            data["experiments"], "experiments", LeanExperiment
        )
        self.held_out: tuple[str, ...] = _strings(data["held_out"], "held_out", _absolute)
        self.required_reading: tuple[str, ...] = _strings(
            data["required_reading"], "required_reading", _absolute
        )
        self.always_loaded: tuple[str, ...] = _strings(
            data["always_loaded"], "always_loaded", _absolute
        )
        self.token_ceiling: int = _positive_int(data["token_ceiling"], "token_ceiling")
        self.tools_allowed: tuple[str, ...] = _strings(
            data["tools_allowed"], "tools_allowed", _string
        )
        self.installation: LeanInstallation = LeanInstallation(data["installation"], "installation")
        self.watchdog_seconds: int = _positive_int(data["watchdog_seconds"], "watchdog_seconds")
        self.hook_timeout_seconds: int = _positive_int(
            data["hook_timeout_seconds"], "hook_timeout_seconds"
        )
        if self.profile == "role" and not self.role:
            raise _fail("role", "a role session must name its role")
        if self.watchdog_seconds + WATCHDOG_MARGIN_SECONDS > self.hook_timeout_seconds:
            raise _fail(
                "watchdog_seconds",
                f"must fire at least {WATCHDOG_MARGIN_SECONDS} s before Claude Code's hook "
                "timeout; otherwise a hung hook lets the tool run",
            )


class LeanInput:
    """The part of Claude Code's event description the hooks rely on.

    Unknown fields are ignored, as in the schema: the description is a vendor
    contract that gains fields between versions.
    """

    __slots__ = (
        "agent_id", "cwd", "hook_event_name", "session_id", "tool_input", "tool_name",
        "tool_response",
    )  # fmt: skip

    def __init__(self, raw: object) -> None:
        """Validate a parsed event description."""
        if not isinstance(raw, dict):
            raise _fail("event", "must be an object")
        for name in ("session_id", "cwd", "hook_event_name"):
            if name not in raw:
                raise _fail("event", f"missing field {name!r}")
        session_id = _string(raw["session_id"], "session_id")
        if not _SESSION_ID.fullmatch(session_id):
            raise _fail("session_id", "is not a plain identifier")
        self.session_id: str = session_id
        self.cwd: str = _string(raw["cwd"], "cwd")
        self.hook_event_name: str = _choice(raw["hook_event_name"], "hook_event_name", EVENTS)
        self.tool_name: str | None = _optional(raw.get("tool_name"), "tool_name", _string)
        tool_input = raw.get("tool_input")
        if tool_input is not None and not isinstance(tool_input, dict):
            raise _fail("tool_input", "must be an object")
        self.tool_input: Mapping[str, Any] | None = tool_input
        self.tool_response: Any = raw.get("tool_response")
        self.agent_id: str | None = _optional(raw.get("agent_id"), "agent_id", _string)


def _json(data: bytes | str) -> object:
    """Parse a JSON document the way the schema's parser does, or refuse it.

    Three differences from :func:`json.loads` had to be closed, all found by
    generated inputs: bytes are read as UTF-8 and nothing else (the standard
    library guesses UTF-16 and UTF-32, and skips a byte-order mark); a lone
    surrogate anywhere in the document, raw or escaped, in a key or a value, is
    refused rather than kept as text; and a document nested deeper than the
    schema's parser goes is refused (:data:`MAX_DEPTH`).
    """
    try:
        text = data.decode("utf-8") if isinstance(data, bytes) else data
        if _SURROGATE.search(text):
            raise _fail("json", "the document holds a lone surrogate, which is not text")
        parsed = json.loads(text)
    except ValueError as exc:
        raise _fail("json", str(exc)) from None
    except RecursionError:
        # Far past the schema's own limit; the standard library gives up first.
        raise _fail("json", "the document is nested too deeply") from None
    # A value that deep needs that many brackets before it, so a document with
    # fewer is not walked at all, which is every ordinary event.
    if text.count("[") + text.count("{") >= MAX_DEPTH and _depth(parsed) > MAX_DEPTH:
        raise _fail("json", f"the document is nested more than {MAX_DEPTH} values deep")
    # An escaped surrogate survives parsing only when it is unpaired; a pair
    # becomes one character. The walk runs only when an escape that could be
    # one is present at all, which a tool input almost never holds.
    if _SURROGATE_ESCAPE.search(text) and _holds_a_surrogate(parsed):
        raise _fail("json", "the document holds a lone surrogate, which is not text")
    return parsed


#: The deepest value the schema's parser accepts, the document itself at depth 1:
#: pydantic-core 2.46.5 refuses a document holding a value at depth 202, whether
#: that value is a container, empty or not, or a scalar. Found by probing, not
#: assumed: 3,000 random chains of arrays and objects, 190 to 215 deep, in every
#: part of an event, were decided by this rule exactly as the schema decides them.
MAX_DEPTH = 201


def _depth(value: object) -> int:
    """The depth of the deepest value in ``value``, which itself is at depth 1."""
    deepest = 0
    stack = [(value, 1)]
    while stack:
        item, depth = stack.pop()
        deepest = max(deepest, depth)
        if isinstance(item, dict):
            stack.extend((inner, depth + 1) for inner in item.values())
        elif isinstance(item, list):
            stack.extend((inner, depth + 1) for inner in item)
    return deepest


def _holds_a_surrogate(value: object) -> bool:
    stack = [value]
    while stack:
        item = stack.pop()
        if isinstance(item, str):
            if _SURROGATE.search(item):
                return True
        elif isinstance(item, dict):
            stack.extend(item)
            stack.extend(item.values())
        elif isinstance(item, list):
            stack.extend(item)
    return False


def parse_config(data: bytes) -> LeanConfig:
    """Validate configuration bytes, as the schema would."""
    return LeanConfig(_json(data))


def parse_input(text: str) -> LeanInput:
    """Validate an event description, as the schema would."""
    return LeanInput(_json(text))


def load_config(path: str, expected_sha256: str) -> LeanConfig:
    """Read the session configuration, refusing a file that was changed after the spawn.

    Raises:
        SessionConfigMismatchError: the file's digest is not the expected one.
        LeanValidationError: the file is not a valid configuration.
    """
    fd = os.open(path, os.O_RDONLY)
    try:
        chunks = []
        while chunk := os.read(fd, 1 << 16):
            chunks.append(chunk)
    finally:
        os.close(fd)
    data = b"".join(chunks)
    if not hmac.compare_digest(hashlib.sha256(data).hexdigest(), expected_sha256):
        msg = "the session configuration was changed after the session started"
        raise SessionConfigMismatchError(msg, path=path)
    return parse_config(data)
