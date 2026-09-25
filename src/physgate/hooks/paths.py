"""No agent tool writes a protected path (ARCH-081, ARCH-090).

This hook covers the tools that name a file: Write, Edit and NotebookEdit, and
Read for the held-out tier, which nothing may read before measurement
(ARCH-141). Shell commands are a separate check, and a sentinel behind both
catches what either misses.

**What is protected is data, not code.** The session configuration lists
protected roots with the reason an agent is given, the experiment rule, and the
held-out paths. An experiment directory is frozen whole once a result file
exists anywhere beneath it, and a criteria file is frozen wherever it is and
whether or not a result exists yet. Nothing else under the experiments
directory is: code evolves, and only what the thesis's measurements rest on is
held still.

**A path is compared by what it reaches, not by how it is spelt.** Two tests,
either of which protects:

- the string test: the path made absolute against the call's working
  directory, normalised, and case-folded, against each root case-folded. This
  is the one that still works for a root that does not exist yet, such as the
  gate directory before its first file. Case is folded always: on the
  development machine's volume ``GATE/CHECK.PY`` reaches ``gate/check.py``,
  and ``os.path.realpath`` does not fold it (measured). On a case-sensitive
  volume a case variant is refused needlessly, which costs nothing a session
  needs.
- the inode test: the device and inode of the path, or of its nearest existing
  parent, and of every directory above that, against those of each existing
  root. This follows symlinks, ``..`` and any spelling the string test did not
  anticipate.

An existing file with more than one link is refused as well. A hard link gives
a protected file a second name anywhere on the volume, and nothing in the name
being written says so.
"""

from __future__ import annotations

import os
from collections.abc import Iterator
from pathlib import Path

from physgate.hooks.config import SessionConfig
from physgate.hooks.runtime import ALLOW, Decision, HookInput, HookSpec, refuse

HELD_OUT_REASON = (
    "it is the held-out evaluation tier, which nothing reads or writes before "
    "measurement (ARCH-141)"
)
FROZEN_RESULT = (
    "it belongs to an experiment with a published result, which is frozen; an amendment "
    "is a new experiment"
)
FROZEN_CRITERIA = (
    "it is an experiment's pre-registered criteria, which are frozen from the commit that "
    "introduced them"
)
HARD_LINKED = (
    "the file has more than one name on disk, so writing it could change a protected file "
    "through its other name"
)
REFUSED = "{path} is protected: {reason}. The {tool} call is refused."

_PATH_KEYS = {"Write": "file_path", "Edit": "file_path", "NotebookEdit": "notebook_path"}
_READERS = {"Read": "file_path"}


def _absolute(path: str, cwd: str) -> str:
    return os.path.normpath(path if os.path.isabs(path) else os.path.join(cwd, path))


def _folded_under(path: str, root: str) -> bool:
    p, r = path.casefold(), root.rstrip("/").casefold()
    return p == r or p.startswith(r + "/")


def _spellings(path: str) -> set[str]:
    return {path, os.path.realpath(path)}


def _existing_chain(path: str) -> Iterator[os.stat_result]:
    """Stat results for the path's nearest existing ancestor and every directory above it."""
    current = Path(path)
    while not current.exists() and current != current.parent:
        current = current.parent
    current = Path(os.path.realpath(current))
    while True:
        try:
            yield os.stat(current)
        except OSError:
            return
        if current == current.parent:
            return
        current = current.parent


def _chain_ids(path: str) -> frozenset[tuple[int, int]]:
    return frozenset((st.st_dev, st.st_ino) for st in _existing_chain(path))


def _reaches(path: str, root: str, chain: frozenset[tuple[int, int]]) -> bool:
    """True if ``path`` is ``root`` or lies beneath it, however either is spelt.

    ``chain`` is the device and inode of the path's nearest existing ancestor and
    of every directory above it, computed once per call.
    """
    for spelling in _spellings(path):
        for root_spelling in _spellings(root):
            if _folded_under(spelling, root_spelling):
                return True
    try:
        root_stat = os.stat(root)
    except OSError:
        return False
    return (root_stat.st_dev, root_stat.st_ino) in chain


def _experiment_reason(
    path: str, root: str, marker: str, always: str, chain: frozenset[tuple[int, int]]
) -> str | None:
    if not _reaches(path, root, chain):
        return None
    if os.path.basename(path).casefold() == always.casefold():
        return FROZEN_CRITERIA
    for spelling in _spellings(path):
        for root_spelling in _spellings(root):
            base = root_spelling.rstrip("/")
            if not _folded_under(spelling, base) or len(spelling) <= len(base) + 1:
                continue
            first = spelling[len(base) + 1 :].split("/", 1)[0]
            experiment = Path(base) / first
            if experiment.is_dir() and any(
                name.casefold() == marker.casefold()
                for _, _, files in os.walk(experiment)
                for name in files
            ):
                return FROZEN_RESULT
    return None


def protection(path: str, cwd: str, config: SessionConfig, *, writing: bool) -> str | None:
    """Why ``path`` may not be touched this way, or ``None`` if it may."""
    absolute = _absolute(path, cwd)
    chain = _chain_ids(absolute)
    for held in config.held_out:
        if _reaches(absolute, held, chain) and (writing or config.profile in ("role", "reviewer")):
            return HELD_OUT_REASON
    if not writing:
        return None
    for root in config.protected_roots:
        if _reaches(absolute, root.path, chain):
            return root.reason
    for rule in config.experiments:
        reason = _experiment_reason(
            absolute, rule.root, rule.frozen_marker, rule.always_frozen_name, chain
        )
        if reason is not None:
            return reason
    try:
        st = os.lstat(absolute)
    except OSError:
        return None
    if os.path.isfile(absolute) and st.st_nlink > 1:
        return HARD_LINKED
    return None


def pre_tool_use(hook_input: HookInput, config: SessionConfig) -> Decision:
    """Refuse a file tool whose target is protected."""
    tool = hook_input.tool_name or ""
    key = _PATH_KEYS.get(tool) or _READERS.get(tool)
    if key is None:
        return ALLOW
    target = (hook_input.tool_input or {}).get(key)
    if not isinstance(target, str) or not target:
        return refuse(f"A {tool} call without a {key} cannot be checked, so it is refused.")
    reason = protection(target, hook_input.cwd, config, writing=tool in _PATH_KEYS)
    if reason is None:
        return ALLOW
    return refuse(REFUSED.format(path=target, reason=reason, tool=tool))


HOOK = HookSpec("paths", {"PreToolUse": pre_tool_use})
