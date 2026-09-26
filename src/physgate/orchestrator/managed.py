"""The managed-settings tier: the one settings source ``--setting-sources ""`` does not govern.

Claude Code applies managed settings above every other source. They reach a
session two ways:

- **Remote managed settings**, fetched for an eligible account from the
  provider's API and cached as ``remote-settings.json`` in the configuration
  directory. Measured on 2.1.272 against the real API: fetched and written even
  with non-essential traffic switched off. The binary skips the fetch when
  ``CLAUDE_CODE_REMOTE_SETTINGS_PATH`` names a file, and uses that file instead.
  Every invocation this package makes names the run's own override file,
  written by the orchestrator, read-only, with its sha256 recorded in the run
  configuration and checked before every spawn.
- **System managed files**, read from fixed paths outside every directory this
  package owns. They are recorded, never created, changed or removed here, and a
  change to one during an invocation is an incident.

After every invocation the configuration directory's ``remote-settings.json``
must be absent or empty, the override unchanged, and the system files as they
were at the start; anything else is reported as drift.
"""

from __future__ import annotations

import getpass
import hashlib
import json
import os
import stat
import sys
from pathlib import Path

from pydantic import BaseModel, ConfigDict

from physgate.orchestrator.exceptions import InvocationError

#: The run's override file, in the run directory.
OVERRIDE_NAME = "managed-settings-override.json"
#: What a run's override holds: no managed settings at all.
EMPTY_OVERRIDE = b"{}\n"
EMPTY_OVERRIDE_SHA256 = hashlib.sha256(EMPTY_OVERRIDE).hexdigest()
#: The variable the binary reads the override's path from.
OVERRIDE_VARIABLE = "CLAUDE_CODE_REMOTE_SETTINGS_PATH"
#: Where the binary caches fetched remote settings, inside its configuration directory.
REMOTE_CACHE = "remote-settings.json"


class SystemManagedFile(BaseModel):
    """One system path the managed tier is read from, as it is on this machine."""

    model_config = ConfigDict(frozen=True, extra="forbid", strict=True)

    path: str
    exists: bool
    owner_uid: int | None = None
    mode: str | None = None
    #: A file's content digest; for a directory, the digest of its files' names and digests.
    sha256: str | None = None


def system_managed_paths(platform: str | None = None, user: str | None = None) -> tuple[Path, ...]:
    """The fixed paths the binary (2.1.272) reads the managed tier from, per platform."""
    platform = platform or sys.platform
    if platform == "darwin":
        root = Path("/Library/Application Support/ClaudeCode")
        name = user if user is not None else getpass.getuser()
        preferences = Path("/Library/Managed Preferences")
        plist = "com.anthropic.claudecode.plist"
        extra: tuple[Path, ...] = (preferences / name / plist, preferences / plist)
    else:
        root = Path("/etc/claude-code")
        extra = ()
    files = ("managed-settings.json", "managed-settings.d", "managed-mcp.json")
    return (*(root / f for f in files), *extra)


def _digest(path: Path) -> str:
    if path.is_dir():
        entries = sorted(
            (str(p.relative_to(path)), _digest(p)) for p in path.rglob("*") if p.is_file()
        )
        return hashlib.sha256(json.dumps(entries).encode()).hexdigest()
    return hashlib.sha256(path.read_bytes()).hexdigest()


def system_managed_facts(
    paths: tuple[Path, ...] | None = None,
) -> tuple[SystemManagedFile, ...]:
    """What each system managed path is now. Read only; nothing is created or changed."""
    facts = []
    for path in paths if paths is not None else system_managed_paths():
        try:
            info = os.lstat(path)
        except FileNotFoundError:
            facts.append(SystemManagedFile(path=str(path), exists=False))
            continue
        try:
            digest: str | None = _digest(path)
        except OSError:
            digest = None  # present but unreadable to this user: recorded as such
        facts.append(
            SystemManagedFile(
                path=str(path),
                exists=True,
                owner_uid=info.st_uid,
                mode=oct(stat.S_IMODE(info.st_mode)),
                sha256=digest,
            )
        )
    return tuple(facts)


def override_path(run_dir: Path) -> Path:
    """Where a run's override file lives."""
    return Path(run_dir) / OVERRIDE_NAME


def write_override(run_dir: Path, content: bytes = EMPTY_OVERRIDE) -> Path:
    """Write the run's override file, read-only; an identical one already there is kept.

    Raises:
        InvocationError: a different override is already there.
    """
    path = override_path(run_dir)
    if path.exists():
        if path.read_bytes() != content:
            msg = "the run already holds a different managed-settings override"
            raise InvocationError(msg, path=str(path))
        return path
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(content)
    path.chmod(0o444)
    return path


def require_override(path: Path, sha256: str) -> None:
    """Refuse to spawn unless the override is the one the run recorded.

    Raises:
        InvocationError: it is missing or its content changed.
    """
    try:
        found = hashlib.sha256(path.read_bytes()).hexdigest()
    except FileNotFoundError:
        found = "missing"
    if found != sha256:
        msg = "the managed-settings override is not the one this run recorded"
        raise InvocationError(msg, path=str(path), recorded=sha256, found=found)


def drift(
    config_dir: Path,
    override: Path,
    sha256: str,
    system_before: tuple[SystemManagedFile, ...],
) -> str | None:
    """What changed in the managed tier during an invocation, or ``None``."""
    found: list[str] = []
    cache = Path(config_dir) / REMOTE_CACHE
    if cache.exists():
        try:
            empty = json.loads(cache.read_text() or "{}") == {}
        except json.JSONDecodeError:
            empty = False
        if not empty:
            found.append(f"remote managed settings were delivered into {cache}")
    try:
        now = hashlib.sha256(override.read_bytes()).hexdigest()
    except FileNotFoundError:
        now = "missing"
    if now != sha256:
        found.append(f"the override {override} changed")
    after = system_managed_facts(tuple(Path(f.path) for f in system_before))
    for before, current in zip(system_before, after, strict=True):
        if before != current:
            found.append(f"the system managed path {before.path} changed")
    return "; ".join(found) or None
