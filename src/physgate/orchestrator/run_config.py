"""A run's configuration: every input that decides what the run does, written once.

Nothing here has a default. A seed, a model string, a bound or the gate mode read
from a default inside a function is an input nobody chose and nobody recorded, so
a run that lacks one does not start. The file is written once, before the first
action, and a resumed run refuses to continue under a configuration that is not
byte-for-byte the recorded one (ARCH-145: any run is reproducible from its
recorded configuration).
"""

from __future__ import annotations

import hashlib
import os
import re
from pathlib import Path
from typing import Annotated

from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    StringConstraints,
    ValidationError,
)

from physgate.orchestrator.common import (
    AuthMode,
    GateMode,
    ModelString,
    NonEmptyStr,
    first_problem,
)
from physgate.orchestrator.exceptions import RunConfigError


class _Frozen(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid", strict=True)


class ModelStrings(_Frozen):
    """Every model a run may call, by what calls it."""

    decomposition: ModelString
    roles: dict[NonEmptyStr, ModelString]
    reviewers: dict[NonEmptyStr, ModelString]


class RunBounds(_Frozen):
    """The limits a session runs under. Required, like the seed; none has a default.

    Values proposed when the orchestrator was designed: on the scripted endpoint
    0 retries, 120 s, 20 turns and no infrastructure retries; for a real model 0
    retries, 1800 s, 150 turns and delays of 60 s then 300 s. The retry count of
    0 is measured (the binary's own retries hid requests from the count and held
    one session open for minutes). **The real-model wall clock, turn limit and
    retry delays are judgement** until a real run's recorded durations replace
    them. An experiment that reads these numbers freezes its own values.
    """

    binary_max_retries: Annotated[int, Field(ge=0)]
    session_wall_clock_s: Annotated[float, Field(gt=0)]
    session_max_turns: Annotated[int, Field(ge=1)]
    infra_retry_delays_s: tuple[Annotated[float, Field(ge=0)], ...]


#: The endpoint the run's model calls go to: ``default`` for the binary's own, or
#: an http(s) URL with no credentials, query or fragment in it.
Endpoint = Annotated[
    str, StringConstraints(pattern=r"^(default|https?://[^/?#@\s]+(/[^?#@\s]*)?)$")
]


#: An http(s) URL, taken apart without a network library (the orchestrator imports
#: none): scheme, optional userinfo (dropped), host, optional port, optional path,
#: then anything from ``?`` or ``#`` on (dropped).
_URL = re.compile(
    r"^(?P<scheme>https?)://(?:[^@/?#]*@)?"
    r"(?P<host>\[[0-9A-Fa-f:.]+\]|[^:/?#@\[\]\s]+)"
    r"(?::(?P<port>[0-9]{1,5}))?(?P<path>/[^?#\s]*)?(?:[?#]\S*)?$",
    re.IGNORECASE,
)


def endpoint_of(base_url: str | None) -> str:
    """The endpoint a run records for ``ANTHROPIC_BASE_URL``: never the secret, always the place.

    Which provider answered (the default, a proxy, the scripted local endpoint)
    decides what a run's numbers mean, so it is recorded like a model string.
    Userinfo, query and fragment are dropped, since a key can travel in any of
    them; an unset or empty value is ``default``.

    Raises:
        RunConfigError: the value is not an http(s) URL with a host.
    """
    if not base_url:
        return "default"
    found = _URL.match(base_url)
    if not found:
        msg = "ANTHROPIC_BASE_URL is not an http(s) URL with a host"
        raise RunConfigError(msg)
    port = f":{found['port']}" if found["port"] else ""
    path = (found["path"] or "").rstrip("/")
    return f"{found['scheme'].lower()}://{found['host'].lower()}{port}{path}"


def require_endpoint(config: RunConfig, base_url: str | None) -> None:
    """Refuse to drive a run against an endpoint other than the one it recorded.

    Raises:
        RunConfigError: the endpoint differs, or the value is not a URL.
    """
    now = endpoint_of(base_url)
    if now != config.endpoint:
        msg = "the endpoint differs from the one this run recorded"
        raise RunConfigError(msg, recorded=config.endpoint, now=now)


class RunConfig(_Frozen):
    """Everything a run is reproduced from."""

    run_id: Annotated[str, StringConstraints(pattern=r"^[A-Za-z0-9_-]{1,64}$")]
    seed: int
    brief_sha256: Annotated[str, StringConstraints(pattern=r"^[0-9a-f]{64}$")]
    gate_mode: GateMode
    models: ModelStrings
    bounds: RunBounds
    token_ceiling: Annotated[int, Field(gt=0)]
    claude_version: NonEmptyStr
    target_head: Annotated[str, StringConstraints(pattern=r"^[0-9a-f]{40}$")]
    endpoint: Endpoint
    auth: AuthMode

    def canonical_bytes(self) -> bytes:
        """The recorded form: stable key order, so equal configs are equal bytes."""
        return self.model_dump_json(indent=None).encode() + b"\n"

    def sha256(self) -> str:
        """Digest of the recorded form, carried on the run's first event."""
        return hashlib.sha256(self.canonical_bytes()).hexdigest()


def write_run_config(path: Path, config: RunConfig) -> None:
    """Write ``config`` to ``path``, once, synced.

    Raises:
        RunConfigError: a configuration is already recorded there.
    """
    try:
        fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o644)
    except FileExistsError:
        msg = "a run configuration is already recorded; a run's configuration is written once"
        raise RunConfigError(msg, path=str(path)) from None
    try:
        os.write(fd, config.canonical_bytes())
        os.fsync(fd)
    finally:
        os.close(fd)


def load_run_config(path: Path) -> RunConfig:
    """Read the recorded configuration back.

    Raises:
        RunConfigError: there is none, or it is not a valid configuration.
    """
    try:
        raw = Path(path).read_bytes()
    except FileNotFoundError:
        msg = "no run configuration is recorded"
        raise RunConfigError(msg, path=str(path)) from None
    try:
        return RunConfig.model_validate_json(raw)
    except ValidationError as exc:
        msg = "the recorded run configuration is not valid"
        raise RunConfigError(msg, path=str(path), reason=first_problem(exc)) from None


def require_recorded(path: Path, config: RunConfig) -> RunConfig:
    """Return the recorded configuration if ``config`` is exactly it.

    What a resume calls before anything else: a run continued under different
    inputs is a different run wearing the first one's name.

    Raises:
        RunConfigError: nothing is recorded, or ``config`` differs from it; the
            message names every field that differs.
    """
    recorded = load_run_config(path)
    if recorded.canonical_bytes() != config.canonical_bytes():
        mine, theirs = config.model_dump(), recorded.model_dump()
        changed = sorted(key for key in theirs if theirs[key] != mine.get(key))
        msg = "the configuration differs from the one this run recorded"
        raise RunConfigError(msg, path=str(path), changed=",".join(changed))
    return recorded
