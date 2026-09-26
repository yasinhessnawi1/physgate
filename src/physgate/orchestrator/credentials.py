"""The credential a run's model calls carry, in one of two modes, and where it is put.

The mode is a run parameter, recorded in the run configuration; the secret never
is. Both are read from the orchestrator's own environment, and a run whose mode
has no secret there is refused before anything is written or spawned.

- ``api_key``: ``ANTHROPIC_API_KEY``. A role session gets it through an
  ``apiKeyHelper`` script its settings name, not through its environment.
- ``subscription``: the long-lived token ``claude setup-token`` produces, read
  from ``CLAUDE_CODE_OAUTH_TOKEN``. A session gets it as the binary's own login
  file in the session's scratch configuration directory. Measured on 2.1.272
  against a local endpoint: the binary then sends it as an OAuth bearer token
  with the OAuth beta header, and it is in neither the agent's environment nor
  any process environment. The helper route sends it as an API key with no OAuth
  header, and the environment-variable route leaves it in the binary's own
  process environment, which the same user can list on macOS.

Either way the secret is in a file the session's own user can read while the
session runs; it is removed when the session ends, by a later resume if the
orchestrator was killed first, and replaced in the captured stream if it ever
appears there. A credential the API refuses ends the session with HTTP 401 or
403, which halts the run for a person to replace it.
"""

from __future__ import annotations

import json
import os
from collections.abc import Mapping
from dataclasses import dataclass, field
from pathlib import Path

from physgate.orchestrator.common import AuthMode
from physgate.orchestrator.exceptions import InvocationError

#: Where each mode's secret is read from, in the orchestrator's own environment.
SECRET_VARIABLE: dict[AuthMode, str] = {
    "api_key": "ANTHROPIC_API_KEY",
    "subscription": "CLAUDE_CODE_OAUTH_TOKEN",
}

#: The binary's login file, inside its configuration directory.
LOGIN_FILE = ".credentials.json"

#: What a secret found in a captured stream is replaced with.
REDACTED_TEXT = "[redacted: the credential]"

#: The api_key mode's files, inside a session's hook state directory.
KEY_FILE = "key"
KEY_HELPER = "key-helper.sh"


@dataclass(frozen=True)
class Credential:
    """A mode and its secret. The secret is kept out of every repr."""

    mode: AuthMode
    secret: str = field(repr=False)

    @property
    def variable(self) -> str:
        """The environment variable the secret was read from."""
        return SECRET_VARIABLE[self.mode]


def credential_for(mode: AuthMode, environ: Mapping[str, str]) -> Credential:
    """The run's credential, read from ``environ`` for ``mode``.

    Raises:
        InvocationError: the mode's variable is unset or empty.
    """
    variable = SECRET_VARIABLE[mode]
    secret = environ.get(variable, "")
    if not secret:
        msg = f"{variable} is not set; a run in auth mode {mode} needs it"
        raise InvocationError(msg, auth=mode, variable=variable)
    return Credential(mode=mode, secret=secret)


def _write_private(path: Path, data: str, mode: int) -> None:
    fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, mode)
    try:
        os.write(fd, data.encode())
    finally:
        os.close(fd)
    path.chmod(mode)


def write_key_helper(state_dir: Path, key: str) -> Path:
    """The api_key mode: an owner-only key file, and the helper script that prints it."""
    secret = state_dir / KEY_FILE
    _write_private(secret, key, 0o600)
    helper = state_dir / KEY_HELPER
    _write_private(helper, f"#!/bin/sh\ncat '{secret}'\n", 0o700)
    return helper


def write_login(config_dir: Path, token: str) -> Path:
    """The subscription mode: the token as the binary's own login file, owner-only."""
    config_dir.mkdir(parents=True, exist_ok=True)
    path = config_dir / LOGIN_FILE
    login = {"claudeAiOauth": {"accessToken": token, "scopes": ["user:inference"]}}
    _write_private(path, json.dumps(login), 0o600)
    return path


def remove_secrets(state_dir: Path, config_dir: Path) -> None:
    """Remove every file a session's credential was put in, whichever mode wrote it."""
    for path in (state_dir / KEY_FILE, state_dir / KEY_HELPER, config_dir / LOGIN_FILE):
        path.unlink(missing_ok=True)
