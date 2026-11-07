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
cache, or a system managed path that changed, is drift, which halts the run. So
are policy limits that differ from the ones the run's decomposition call received:
the account's side can change them, and they are applied without a trace in any
file the hooks see. A session no model answered before it ended for infrastructure ran
no tool under any limits: its missing limits are recorded, not judged.
The harness cannot stop a managed-policy change pushed from outside; it halts on
one.
"""

from __future__ import annotations

import getpass
import hashlib
import json
import os
import re
import stat
import sys
from collections.abc import Iterable
from pathlib import Path
from typing import Annotated, Final, Literal

from pydantic import BaseModel, ConfigDict, Field, StringConstraints, model_validator

from physgate.orchestrator.budget import SessionEnd
from physgate.reviewers.transcript import SYNTHETIC_MODEL

#: Where the binary caches fetched remote settings, inside its configuration directory.
REMOTE_CACHE = "remote-settings.json"

#: Where the binary writes the account's policy limits it fetched and applied. Measured
#: on the real API (2.1.272): fetched and applied on every invocation from a fresh
#: configuration directory, non-essential traffic off or not; never written against a
#: third-party endpoint. The stamp file beside it carries a timestamp and is not read.
POLICY_LIMITS = "policy-limits.json"


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


class TrafficSettings(BaseModel):
    """The session-environment settings that keep the binary's remote catalog and flags off.

    Measured on the real subscription path (2.1.272, 27.09.2026): with non-essential
    traffic disabled the served model catalog stays off, and with telemetry disabled so
    do the remote feature flags. Either could otherwise change what a request carries
    while the binary's version stays the same.
    """

    model_config = ConfigDict(frozen=True, extra="forbid", strict=True)

    nonessential_traffic: Literal["disabled", "enabled"]
    telemetry: Literal["disabled", "enabled"]
    measured: str = (
        "served model catalog and remote feature flags measured off under these settings on "
        "Claude Code 2.1.272, 27.09.2026, on the real subscription path"
    )


#: What the decomposition call's own debug log says; a closed vocabulary, so nothing the
#: log holds besides these words (a credential included) can reach the record.
Observed = Literal["off", "not reported off"]

#: The feature flags' state on a version whose debug log never says it: off by the
#: documented setting the session carried, not seen. A distinct value, so a record
#: never shows a documented state as an observed one.
FLAGS_OFF_BY_SETTING: Final = "off by setting (documented), not reported by this version"

#: Versions whose debug log does not report the feature flags' state. On 2.1.272 and
#: 2.1.283 the words "GrowthBook is off for this session" appear, inside another
#: debug line; 2.1.301 writes no such line, with or without ``DISABLE_GROWTHBOOK``
#: (compared side by side at the scripted endpoint, 16.10.2026). For these the
#: session carries ``DISABLE_GROWTHBOOK=1``, which the provider's environment-variable
#: reference (read 16.10.2026) documents as disabling the flag fetch and using code
#: defaults for every flag.
FLAGS_SILENT_VERSIONS = frozenset({"2.1.301"})

#: The setting a session on a silent version carries, and the value it carries.
FLAGS_SETTING = ("DISABLE_GROWTHBOOK", "1")

FeatureFlags = Literal[
    "off", "off by setting (documented), not reported by this version", "not reported off"
]


def flags_off_by_setting(claude_version: str, env: dict[str, str]) -> bool:
    """Whether a session's flags count as off by setting: a silent version that carried it."""
    name, value = FLAGS_SETTING
    return claude_version in FLAGS_SILENT_VERSIONS and env.get(name) == value


class ObservedTraffic(BaseModel):
    """The state of the binary's served model catalog and remote feature flags, as observed."""

    model_config = ConfigDict(frozen=True, extra="forbid", strict=True)

    served_catalog: Observed
    #: The reason the log gave for an off catalog (``essential_traffic``), if one.
    served_catalog_reason: Annotated[str, StringConstraints(pattern=r"^[a-z_]{1,40}$")] | None
    feature_flags: FeatureFlags

    def all_off(self) -> bool:
        """Whether both are off, the only state a run proceeds under.

        The catalog must be seen off; the flags may be off by the documented setting
        on a version that never reports them.
        """
        return self.served_catalog == "off" and self.feature_flags in ("off", FLAGS_OFF_BY_SETTING)


_SERVED = re.compile(r"\[servedCatalog\] (\S+)(?: \(([a-z_]{1,40})\))?")
_FLAGS_OFF = "GrowthBook is off for this session"


def observe_traffic(debug_log: str, *, flags_off_by_setting: bool = False) -> ObservedTraffic:
    """Read the served-catalog and feature-flag state from one invocation's debug log.

    Either reads ``not reported off`` unless the log says off, and says nothing else:
    a line in another form, a second line saying anything but off, or no line at all.
    The one exception is the flags on a version that never reports them
    (``flags_off_by_setting``): they read as off by setting, a value of its own.
    """
    served = [m for line in debug_log.splitlines() if (m := _SERVED.search(line))]
    off = bool(served) and all(m.group(1) == "off" for m in served)
    reasons = {m.group(2) for m in served if m.group(2)}
    return ObservedTraffic(
        served_catalog="off" if off else "not reported off",
        served_catalog_reason=reasons.pop() if off and len(reasons) == 1 else None,
        feature_flags=_flags(debug_log, by_setting=flags_off_by_setting),
    )


def _flags(debug_log: str, *, by_setting: bool) -> FeatureFlags:
    if _FLAGS_OFF in debug_log:
        return "off"
    return FLAGS_OFF_BY_SETTING if by_setting else "not reported off"


def policy_limits_digest(config_dir: Path) -> str | None:
    """The sha256 of the policy limits an invocation left, or ``None`` if it left none."""
    path = Path(config_dir) / POLICY_LIMITS
    return hashlib.sha256(path.read_bytes()).hexdigest() if path.is_file() else None


def model_answered(answered: Iterable[str]) -> bool:
    """Whether a model answered a session at least once, from the models its stream names.

    The binary names the messages it writes itself, an API error's among them, as
    ``<synthetic>``: no model's answer. It writes its ``init`` line before any request
    (measured on a live run whose retry dropped before its first request: the init line
    was there, and only the binary's own error message after it), so that line is no sign
    the session reached the API. A model's answer is: before one, no tool has run.
    """
    return any(model != SYNTHETIC_MODEL for model in answered)


def policy_limits_unjudged(end: SessionEnd, *, answered: bool, now: str | None) -> str | None:
    """Why an invocation's missing policy limits are not held to the run's first, or ``None``.

    Only a session that ended for infrastructure before any model answered it, and left no
    limits: a connection that dropped before the binary fetched them. No tool ran under any
    limits, so nothing is judged; the session is retried as the infrastructure failure it is,
    and its missing file is recorded. Limits it did leave are judged as every session's are.
    """
    if end.outcome != "infrastructure" or answered or now is not None:
        return None
    return (
        f"the session ended {end.cause} before any model answered it and left no policy "
        "limits: recorded, not held to the decomposition call's"
    )


def policy_limits_change(baseline: str | None, now: str | None) -> str | None:
    """How an invocation's policy limits differ from the run's first, or ``None``.

    Every invocation starts from an empty configuration directory, so the limits
    are fetched afresh each time, and the run's decomposition call is the first
    one: what it received is what every later session must receive. A file that
    appears or disappears is a change like any other.
    """
    if now == baseline:
        return None
    if baseline is None:
        return f"policy limits appeared ({now}) where the decomposition call received none"
    if now is None:
        return f"no policy limits arrived where the decomposition call received {baseline}"
    return f"the policy limits changed from {baseline} to {now}"


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


#: The key the account's restrictions sit under, and the flag each restriction carries.
RESTRICTIONS = "restrictions"
ALLOWED = "allowed"
#: The most entries one resolution records; a change past it is counted, and never the rule's.
MAX_ENTRIES = 200


class PolicyEntry(BaseModel):
    """One key whose value differs between two sets of policy limits, as the record shows it.

    ``path`` is the key, outermost first. A value is shown as written when it is a flag, a number
    or null, and otherwise only by its kind and size: these files hold flags, and nothing in them
    that is not one is ever copied into the record or printed. ``None``: the key is not there.
    """

    model_config = ConfigDict(frozen=True, extra="forbid", strict=True)

    path: Annotated[
        tuple[Annotated[str, StringConstraints(max_length=256)], ...],
        Field(min_length=1, max_length=16),
    ]
    before: Annotated[str, StringConstraints(min_length=1, max_length=64)] | None
    after: Annotated[str, StringConstraints(min_length=1, max_length=64)] | None

    @model_validator(mode="after")
    def _one_side_at_least(self) -> PolicyEntry:
        if self.before is None and self.after is None:
            msg = "an entry names a key on one side at least"
            raise ValueError(msg)
        return self


def shown(value: object) -> str:
    """``value`` as the record shows it: a flag, number or null as written, else kind and size."""
    if value is None or isinstance(value, bool | int | float):
        return json.dumps(value)
    if isinstance(value, str):
        return f"a string of {len(value)} characters"
    if isinstance(value, list):
        return f"a list of {len(value)} entries"
    return "an empty object" if value == {} else "an object"


def _leaves(value: object, path: tuple[str, ...] = ()) -> dict[tuple[str, ...], object]:
    """Every key under ``value`` that holds no object of keys, by its path."""
    if isinstance(value, dict) and value and len(path) < 16:
        found: dict[tuple[str, ...], object] = {}
        for key, inner in value.items():
            found |= _leaves(inner, (*path, str(key)))
        return found
    return {path: value} if path else {}


def policy_diff(
    before: dict[str, object] | None, after: dict[str, object] | None
) -> tuple[tuple[PolicyEntry, ...], int]:
    """Every key whose value differs from ``before`` to ``after``, sorted, and how many more do.

    ``None`` is no file: every key of the other side differs. Values are compared as read, and
    recorded as :func:`shown` shows them.
    """
    old, new = _leaves(before or {}), _leaves(after or {})
    differ = sorted(
        p
        for p in old.keys() | new.keys()
        if p not in old or p not in new or (old[p] != new[p] or type(old[p]) is not type(new[p]))
    )
    entries = tuple(
        PolicyEntry(
            path=tuple(key[:256] for key in path),
            before=shown(old[path]) if path in old else None,
            after=shown(new[path]) if path in new else None,
        )
        for path in differ[:MAX_ENTRIES]
    )
    return entries, max(0, len(differ) - MAX_ENTRIES)


def stricter_only(entries: tuple[PolicyEntry, ...], omitted: int) -> bool:
    """The owner's one rule: the change only adds restrictions, each set to ``allowed: false``.

    Nothing removed, nothing else changed, and at least one restriction added. Any other change,
    stricter or not, waits for a person at a terminal.
    """
    return (
        omitted == 0
        and bool(entries)
        and all(
            entry.before is None
            and entry.after == "false"
            and len(entry.path) == 3
            and entry.path[0] == RESTRICTIONS
            and entry.path[2] == ALLOWED
            for entry in entries
        )
    )


def diff_lines(entries: tuple[PolicyEntry, ...], omitted: int) -> list[str]:
    """The change as a person reads it, a line per key: ``+`` added, ``-`` gone, ``~`` changed."""
    lines = []
    for entry in entries:
        key = ".".join(entry.path)
        if entry.before is None:
            lines.append(f"+ {key}: {entry.after}")
        elif entry.after is None:
            lines.append(f"- {key}: {entry.before}")
        else:
            lines.append(f"~ {key}: {entry.before} -> {entry.after}")
    if omitted:
        lines.append(f"and {omitted} more keys that differ")
    return lines


def read_limits(path: Path, sha256: str) -> dict[str, object] | None:
    """The policy limits at ``path``, held to ``sha256``; ``None`` unless the file is exactly that.

    A file whose bytes are not the recorded digest, or that is not one JSON object, is no
    evidence of what a session received.
    """
    path = Path(path)
    if not path.is_file() or path.is_symlink():
        return None
    data = path.read_bytes()
    if hashlib.sha256(data).hexdigest() != sha256:
        return None
    try:
        limits = json.loads(data)
    except (json.JSONDecodeError, UnicodeDecodeError):
        return None
    return limits if isinstance(limits, dict) else None


#: Where a run keeps each session's configuration directory, and the decomposition call's:
#: ``<run>/sessions/<session id>/config`` and ``<run>/decomposition/config``.
SESSIONS_DIR = "sessions"
DECOMPOSITION_DIR = "decomposition"
CONFIG_DIR = "config"


def session_limits(run_dir: Path, session_id: str) -> Path:
    """Where the session ``session_id`` of the run in ``run_dir`` was left its policy limits."""
    return Path(run_dir) / SESSIONS_DIR / session_id / CONFIG_DIR / POLICY_LIMITS


def limits_with(run_dir: Path, sha256: str) -> dict[str, object] | None:
    """The policy limits some invocation of the run received whose digest is ``sha256``.

    The decomposition call's first, then each session's in name order; each file is held to the
    digest, so whichever is found is exactly what the record names. ``None`` if none is.
    """
    run_dir = Path(run_dir)
    sessions = run_dir / SESSIONS_DIR
    places = [run_dir / DECOMPOSITION_DIR / CONFIG_DIR / POLICY_LIMITS]
    if sessions.is_dir() and not sessions.is_symlink():
        places += sorted(p / CONFIG_DIR / POLICY_LIMITS for p in sessions.iterdir())
    for place in places:
        limits = read_limits(place, sha256)
        if limits is not None:
            return limits
    return None
