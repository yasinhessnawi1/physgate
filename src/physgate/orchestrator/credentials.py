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
session runs; it is removed when the session ends, before the orchestrator ends on a
stop signal (``stop_signals``), by a later resume if the orchestrator was killed
first, and replaced in the captured stream if it ever appears there. A credential
the API refuses ends the session with HTTP 401 or 403, which halts the run for a
person to replace it.
"""

from __future__ import annotations

import hashlib
import json
import os
import re
import stat
from collections.abc import Iterator, Mapping
from contextlib import contextmanager
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


#: How many hexadecimal characters of the secret's sha256 name its account in a run's record.
FINGERPRINT_LENGTH = 12


def fingerprint(credential: Credential) -> str:
    """The first characters of the secret's sha256: enough to tell run accounts apart.

    Recorded with the run, so a resume on another account's credential is refused. A prefix of
    a digest of a long random secret says nothing usable about the secret itself.
    """
    return hashlib.sha256(credential.secret.encode()).hexdigest()[:FINGERPRINT_LENGTH]


#: Every file this process put a credential in, or a session of its may hold one in, by its
#: directory, until the session's removal has run: what a stop signal removes before the process
#: ends (:func:`remove_held_secrets`).
_held: dict[Path, frozenset[str]] = {}


def _hold(directory: Path, names: tuple[str, ...]) -> None:
    _held[directory] = _held.get(directory, frozenset()) | frozenset(names)


def hold_login(config_dir: Path) -> None:
    """Hold a spawned session's login file for a stop signal, whoever writes it: the binary too."""
    _hold(config_dir, (LOGIN_FILE,))


def remove_held_secrets() -> int:
    """Remove every file :data:`_held` names, by name, as :func:`remove_secrets` does.

    For a process about to end on a stop signal: nothing is raised, and one directory that
    cannot be reached leaves every other one's files removed. A configuration directory's debug
    logs and the binary's messaging keys go with its login file. Returns how many removals
    failed (a count, so a stop can say so without naming or printing a file).
    """
    failed = 0
    for directory, names in list(_held.items()):
        try:
            _unlink_in(directory, tuple(sorted(names)))
        except (OSError, InvocationError):
            failed += 1
        if LOGIN_FILE not in names:
            continue
        try:
            remove_debug_logs(directory)
        except (OSError, InvocationError):
            failed += 1
        try:
            remove_messaging_keys(directory)
        except (OSError, InvocationError):
            failed += 1
    return failed


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
    _hold(state_dir, (KEY_FILE, KEY_HELPER))
    _write_private(secret, key, 0o600)
    helper = state_dir / KEY_HELPER
    _write_private(helper, f"#!/bin/sh\ncat '{secret}'\n", 0o700)
    return helper


def write_login(config_dir: Path, token: str) -> Path:
    """The subscription mode: the token as the binary's own login file, owner-only."""
    config_dir.mkdir(parents=True, exist_ok=True)
    path = config_dir / LOGIN_FILE
    _hold(config_dir, (LOGIN_FILE,))
    login = {"claudeAiOauth": {"accessToken": token, "scopes": ["user:inference"]}}
    _write_private(path, json.dumps(login), 0o600)
    return path


def open_in_session(directory: Path) -> int | None:
    """A descriptor on ``directory``, reached from its session's directory without a link.

    ``directory`` is ``<session dir>/<name>`` or the session directory itself. The session
    directory's parent is the orchestrator's own (the run's ``sessions`` directory, a review's
    directory, a decomposition's work directory) and is opened as named; the session directory
    and everything below it is opened without following a link, so a link a session's process
    planted there is never followed out of it. ``None`` if the directory does not exist.

    Raises:
        InvocationError: a component is a link, or not a directory.
    """
    flags = os.O_RDONLY | os.O_DIRECTORY
    try:
        top = os.open(directory.parent.parent, flags)
    except FileNotFoundError:
        return None
    try:
        names = [directory.parent.name, directory.name]
        fd = top
        for name in names:
            try:
                nxt = os.open(name, flags | os.O_NOFOLLOW, dir_fd=fd)
            except FileNotFoundError:
                if fd != top:
                    os.close(fd)
                return None
            except OSError as exc:
                if fd != top:
                    os.close(fd)
                msg = "a session's directory is a link or not a directory; it is not followed"
                raise InvocationError(msg, path=str(directory), error=repr(exc)) from exc
            if fd != top:
                os.close(fd)
            fd = nxt
        return fd
    finally:
        os.close(top)


#: What a session's debug log is named by, in its configuration directory: every file whose name
#: starts with it is removed with the credential, since a debug log may hold the credential.
DEBUG_LOG_PREFIX = "debug"


def remove_debug_logs(config_dir: Path) -> None:
    """Remove every debug log in a session's configuration directory.

    Reached as the credential's files are (:func:`open_in_session`), never through a link; a
    link at a log's name is itself removed. A directory under such a name is left: no log can be
    written where a directory stands.
    """
    fd = open_in_session(config_dir)
    if fd is None:
        return
    try:
        for name in os.listdir(fd):
            if not name.startswith(DEBUG_LOG_PREFIX):
                continue
            try:
                if stat.S_ISDIR(os.stat(name, dir_fd=fd, follow_symlinks=False).st_mode):
                    continue
                os.unlink(name, dir_fd=fd)
            except FileNotFoundError:
                continue
    finally:
        os.close(fd)


#: Where the binary keeps its per-process messaging keys, in its configuration directory.
MESSAGING_DIR = "sessions"
#: A messaging key, as the binary names it: ``<pid>.<sha256 of its socket's path>.key``, which
#: holds the token a peer process must show it, and the temporary file it is written through,
#: ``<that name>.tmp.<hex>``. Matched by the name alone, in that one directory.
MESSAGING_KEY = re.compile(r"^[0-9]+\.[0-9a-f]{64}\.key(?:\.tmp\.[0-9a-f]+)?$")


def remove_messaging_keys(config_dir: Path) -> None:
    """Remove the binary's messaging keys from a session's configuration directory.

    Reached as the credential's files are (:func:`open_in_session`), and the keys' directory
    without following a link; only names :data:`MESSAGING_KEY` matches are removed, one level
    down and never recursively, and a link at such a name is itself removed. A directory under
    such a name is left: no key is written where a directory stands.

    A name that will not go (any error but "not found") does not stop the others: the rest are
    removed first, and then the failure is raised, by count and never by name or content.

    Raises:
        InvocationError: the keys' directory is a link, or not a directory; or a key was left.
    """
    fd = open_in_session(config_dir)
    if fd is None:
        return
    try:
        try:
            keys = os.open(MESSAGING_DIR, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW, dir_fd=fd)
        except FileNotFoundError:
            return
        except OSError as exc:
            msg = "a session's messaging keys' directory is a link or not a directory"
            raise InvocationError(
                msg, path=str(config_dir / MESSAGING_DIR), error=repr(exc)
            ) from exc
        left = 0
        try:
            for name in os.listdir(keys):
                if MESSAGING_KEY.fullmatch(name) is None:
                    continue
                try:
                    if stat.S_ISDIR(os.stat(name, dir_fd=keys, follow_symlinks=False).st_mode):
                        continue
                    os.unlink(name, dir_fd=keys)
                except FileNotFoundError:
                    continue
                except OSError:
                    left += 1
        finally:
            os.close(keys)
        if left:
            msg = "a session's messaging keys could not all be removed"
            raise InvocationError(msg, path=str(config_dir / MESSAGING_DIR), left=left)
    finally:
        os.close(fd)


@contextmanager
def debug_logs_removed_on_failure(config_dir: Path) -> Iterator[None]:
    """On any failure inside, a session's debug logs are removed before it propagates.

    For the spawn: a session that never started properly may still have written one.
    """
    try:
        yield
    except BaseException:
        remove_debug_logs(config_dir)
        raise


def remove_secrets(state_dir: Path, config_dir: Path) -> None:
    """Remove every file a session's credential was put in, whichever mode wrote it.

    Each file is unlinked through a descriptor on its directory, reached without following a
    link (:func:`open_in_session`): a link planted at the directory's name or the file's own
    is never followed, so nothing outside the session's own directory is removed. A link at a
    file's name is itself removed, which removes nothing it points at.

    Raises:
        InvocationError: a directory on the way is a link, or not a directory; the credential
            may still be on disk where the session's process moved it.
    """
    # Each directory in its own step, so a refusal on one never leaves the other's files.
    try:
        _unlink_in(state_dir, (KEY_FILE, KEY_HELPER))
    finally:
        try:
            _unlink_in(config_dir, (LOGIN_FILE,))
        finally:
            try:
                # A session's debug log may hold the credential: it goes with it.
                remove_debug_logs(config_dir)
            finally:
                # So do the binary's messaging keys, each a token a peer must show.
                remove_messaging_keys(config_dir)
    # Removed: a stop signal has nothing more of this session's to remove.
    _held.pop(state_dir, None)
    _held.pop(config_dir, None)


def _unlink_in(directory: Path, names: tuple[str, ...]) -> None:
    fd = open_in_session(directory)
    if fd is None:
        return
    try:
        for name in names:
            try:
                os.unlink(name, dir_fd=fd)
            except FileNotFoundError:
                continue
    finally:
        os.close(fd)
