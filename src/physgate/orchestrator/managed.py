"""The managed-settings tier: the one settings source ``--setting-sources ""`` does not govern.

Claude Code applies managed settings above every other source. They reach a
session two ways, and neither is written by the agent under test:

- **Remote managed settings**, fetched for an eligible account from the
  provider's API and cached as ``remote-settings.json`` in the session's
  configuration directory. Measured on 2.1.272 against the real API: fetched
  and written even with non-essential traffic switched off, and not replaced by
  ``CLAUDE_CODE_REMOTE_SETTINGS_PATH`` (an override named there left the
  binary's own init report unchanged and the fetch still happened), so nothing
  here tries to prevent them.
- **System managed files**, read from fixed paths outside every directory this
  package owns. They are recorded, never created, changed or removed here.

What this package does is detect: every session starts from a fresh
configuration directory, and after every invocation a non-empty remote-settings
cache, or a system managed path that changed, is drift, which halts the run.
The harness cannot stop a managed-policy change pushed from outside; it halts on
one.
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


def drift(config_dir: Path, system_before: tuple[SystemManagedFile, ...]) -> str | None:
    """What the managed tier held or changed during an invocation, or ``None``."""
    found: list[str] = []
    cache = Path(config_dir) / REMOTE_CACHE
    if cache.exists():
        try:
            empty = json.loads(cache.read_text() or "{}") == {}
        except json.JSONDecodeError:
            empty = False
        if not empty:
            found.append(f"remote managed settings were delivered into {cache}")
    after = system_managed_facts(tuple(Path(f.path) for f in system_before))
    for before, current in zip(system_before, after, strict=True):
        if before != current:
            found.append(f"the system managed path {before.path} changed")
    return "; ".join(found) or None
