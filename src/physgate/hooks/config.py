"""What a hook knows about the session it guards.

The configuration is written by the spawner, outside the session's worktree,
next to a settings file that Claude Code reads once at start and does not
re-read. Every hook command line in that settings file carries the sha256 of
the configuration's bytes, and a hook refuses when the file no longer matches.

That arrangement is measured, not assumed. With a settings file inside the
worktree loaded, a single write of ``disableAllHooks`` into it switched every
hook off for the rest of the session, and an ``env`` block written the same way
changed the environment every hook saw. With no worktree settings loaded and the
hooks in a file passed by flag, neither write changed anything. So nothing that
decides a refusal is read from the worktree or from a variable the session can
set.
"""

from __future__ import annotations

import hashlib
import hmac
import os
from typing import Annotated, Any, Literal, Self

from pydantic import BaseModel, ConfigDict, Field, StringConstraints, model_validator

from physgate.hooks.exceptions import SessionConfigMismatchError

#: A session is spawned as one of these. ``role`` is a domain agent writing one
#: module; ``reviewer`` judges and does not write; ``orchestrator`` is a harness
#: session run by the orchestrator itself. None of the three writes the gate.
Profile = Literal["role", "reviewer", "orchestrator"]

#: Claude Code's own timeout must fire later than the hook's watchdog, and with
#: room to spare: when Claude Code's timeout fires first, the tool runs.
WATCHDOG_MARGIN_SECONDS = 10

AbsolutePath = Annotated[str, StringConstraints(min_length=2, pattern=r"^/")]


class Installation(BaseModel):
    """Where the hook code runs from. Outside every worktree, and protected.

    ``base_prefix`` is the interpreter's own installation, standard library
    included. A virtual environment's interpreter is a link to it, and every hook
    imports from it, so a session that could edit it could run code inside every
    hook. It is not a theoretical path: on the development machine that library
    was measured to be writable by the user the sessions run as.
    """

    model_config = ConfigDict(frozen=True, extra="forbid", strict=True)

    interpreter: AbsolutePath
    package_dir: AbsolutePath
    environment_root: AbsolutePath
    base_prefix: AbsolutePath


#: How the sentinel treats a protected root after a call:
#: ``revert`` puts back anything that changed; ``journal`` checks that the bytes
#: already there are unchanged and leaves appends to the store's own guard,
#: because the orchestrator appends legitimately while sessions run; ``halt``
#: refuses every later call, because the code the hooks run from changed and
#: nothing it decides can be trusted; ``log`` records a change that another
#: process may make legitimately; ``none`` leaves the root to the layers that
#: refuse writes before they happen, because the hooks or Claude Code write it.
Watch = Literal["revert", "journal", "halt", "log", "none"]


class ProtectedRoot(BaseModel):
    """A path no agent tool may write, the reason the agent is given, and how it is watched."""

    model_config = ConfigDict(frozen=True, extra="forbid", strict=True)

    path: AbsolutePath
    reason: Annotated[str, StringConstraints(min_length=1)]
    watch: Watch


class ExperimentRule(BaseModel):
    """Which files under an experiments directory are frozen.

    A whole experiment directory is frozen once a result file exists anywhere
    beneath it, and a criteria file is frozen from the moment it exists. Nothing
    else under the directory is: code evolves, and only what the thesis's
    measurements rest on is held still.
    """

    model_config = ConfigDict(frozen=True, extra="forbid", strict=True)

    root: AbsolutePath
    frozen_marker: Annotated[str, StringConstraints(min_length=1)]
    always_frozen_name: Annotated[str, StringConstraints(min_length=1)]


class SessionConfig(BaseModel):
    """Everything a hook needs to decide, fixed for the life of the session."""

    model_config = ConfigDict(frozen=True, extra="forbid", strict=True)

    profile: Profile
    role: str | None
    worktree: AbsolutePath
    own_branch: str | None
    store_root: AbsolutePath | None
    state_dir: AbsolutePath
    protected_roots: tuple[ProtectedRoot, ...]
    experiments: tuple[ExperimentRule, ...]
    held_out: tuple[AbsolutePath, ...]
    required_reading: tuple[AbsolutePath, ...]
    always_loaded: tuple[AbsolutePath, ...]
    token_ceiling: Annotated[int, Field(gt=0)]
    tools_allowed: tuple[str, ...]
    installation: Installation
    watchdog_seconds: Annotated[int, Field(gt=0)]
    hook_timeout_seconds: Annotated[int, Field(gt=0)]

    @model_validator(mode="after")
    def _coherent(self) -> Self:
        if self.profile == "role" and not self.role:
            msg = "a role session must name its role"
            raise ValueError(msg)
        if self.watchdog_seconds + WATCHDOG_MARGIN_SECONDS > self.hook_timeout_seconds:
            msg = (
                f"the watchdog ({self.watchdog_seconds} s) must fire at least "
                f"{WATCHDOG_MARGIN_SECONDS} s before Claude Code's hook timeout "
                f"({self.hook_timeout_seconds} s); otherwise a hung hook lets the tool run"
            )
            raise ValueError(msg)
        return self


def digest(data: bytes) -> str:
    """The sha256 of ``data``, as the hook command line carries it."""
    return hashlib.sha256(data).hexdigest()


def load_config(path: str, expected_sha256: str) -> SessionConfig:
    """Read the session configuration, refusing a file that was changed.

    The file is opened read-only and read once, so the bytes that are checked
    are the bytes that are parsed.

    Raises:
        SessionConfigMismatchError: the file's digest is not the expected one.
        pydantic.ValidationError: the file is not a valid configuration.
    """
    fd = os.open(path, os.O_RDONLY)
    try:
        chunks = []
        while chunk := os.read(fd, 1 << 16):
            chunks.append(chunk)
    finally:
        os.close(fd)
    data = b"".join(chunks)
    if not hmac.compare_digest(digest(data), expected_sha256):
        msg = "the session configuration was changed after the session started"
        raise SessionConfigMismatchError(msg, path=path)
    return SessionConfig.model_validate_json(data)


Event = Literal[
    "SessionStart", "PreToolUse", "PostToolUse", "PostToolUseFailure", "Stop", "SessionEnd"
]


class HookInput(BaseModel):
    """The part of Claude Code's event description the hooks rely on: the schema.

    Unknown fields are ignored rather than refused. This is the one boundary in
    the package that does not forbid extras, deliberately: the description is a
    vendor contract that gains fields between versions, and refusing an unknown
    field would turn a routine upgrade into a refusal of every tool call. The
    fields that are relied on are typed and required where the decision needs
    them.

    The hot path validates with :mod:`physgate.hooks.lean` instead, which a test
    holds to exactly this model.
    """

    model_config = ConfigDict(frozen=True, extra="ignore")

    session_id: Annotated[str, StringConstraints(pattern=r"^[A-Za-z0-9_-]{1,128}$")]
    cwd: str
    hook_event_name: Event
    tool_name: str | None = None
    # Any: the shape of a tool's input and response is the tool's, and each
    # hook validates the part it reads.
    tool_input: dict[str, Any] | None = None
    tool_response: Any = None
    agent_id: str | None = None
