"""The always-loaded and required-reading sets per role (ARCH-020, ARCH-023).

``knowledge/`` at the repository root holds the curated content: one standards
file and one skill file per role's domain, under ``knowledge/<role>/``, plus
``knowledge/cross/standards.md``, which every role reads regardless of its own
domain (ARCH-051, "what every role reads"). Always loaded is exactly these
three files (ARCH-023); required reading additionally names the module
specification and any interface contracts touching the module (ARCH-020).

This module only names files, as paths relative to a knowledge root a caller
resolves against the worktree actually being dispatched to — the
orchestrator's own checkout and a role session's subtask worktree are
different directories, and only the latter is where a real session's Read
tool operates. It does no filesystem access and no existence-checking of its
own: ``physgate.hooks.reading``/``token_ceiling`` already do that from a real
session's configuration, and a second check here could drift from theirs.

A path this returns for a role whose domain has no curated content yet
correctly does not exist on disk. That is not a gap in this module — it is
ARCH-101's own acceptance test (dispatch of a role with a missing standards
file is refused), enforced by the reading hook once something dispatches that
role, not by anything here.
"""

from __future__ import annotations

import re
from pathlib import Path

from physgate.knowledge.exceptions import RoleNameError

#: A role name becomes a directory name under the knowledge root, so it is held
#: to the same safe-identifier pattern an ablation flag's name already uses
#: (:data:`physgate.flags.Flag.name`) — short, lower-case, no separator that
#: could walk outside that directory.
_ROLE_PATTERN = re.compile(r"^[a-z][a-z0-9_]*$")

#: ``knowledge/cross/standards.md``'s domain name: every role reads it,
#: regardless of its own domain (ARCH-051).
CROSS = "cross"

STANDARDS_NAME = "standards.md"
SKILL_NAME = "skill.md"

#: Where the curated content lives, relative to a worktree root. A caller joins
#: this against the specific worktree being dispatched to; nothing in this
#: module resolves it against the orchestrator's own checkout.
DEFAULT_ROOT = Path("knowledge")

#: Directories beneath the knowledge root that are not a role's: candidates
#: awaiting promotion, and the tree only reviewers read. A role by either name
#: would put its always-loaded files inside one of them, so neither is a role.
RESERVED = frozenset({"staging", "reviewers"})


def _role_dir(role: str, root: Path) -> Path:
    """``root / role``, after checking ``role`` is safe to build a path from.

    Raises:
        RoleNameError: ``role`` is empty, upper-case, holds a character
            (``/``, ``.``, whitespace) that could name something other than a
            single directory directly under ``root``, or is a reserved name.
    """
    if not _ROLE_PATTERN.fullmatch(role):
        msg = "a role name must be a safe, lower-case directory name to build a knowledge path from"
        raise RoleNameError(msg, role=role)
    if role in RESERVED:
        msg = "this name is a directory of the knowledge root that no role's files may live in"
        raise RoleNameError(msg, role=role)
    return root / role


def always_loaded(role: str, *, root: Path = DEFAULT_ROOT) -> tuple[Path, ...]:
    """The always-loaded set for ``role`` (ARCH-023): cross's standards, then the role's own pair.

    ``role == "cross"`` returns just the one file — the cross role has no
    further domain of its own to read on top of what every role already reads.

    Raises:
        RoleNameError: ``role`` is not a safe directory name.
    """
    cross_standards = _role_dir(CROSS, root) / STANDARDS_NAME
    if role == CROSS:
        return (cross_standards,)
    own = _role_dir(role, root)
    return (cross_standards, own / STANDARDS_NAME, own / SKILL_NAME)


def required_reading(
    role: str,
    module_spec: Path,
    *,
    interfaces: tuple[Path, ...] = (),
    root: Path = DEFAULT_ROOT,
) -> tuple[Path, ...]:
    """The required-reading set for ``role`` (ARCH-020): always-loaded, the spec, interfaces.

    Deduplicated and sorted, so a caller passing the spec twice, or two roles
    sharing ``cross/standards.md``, does not double the reading hook's list.

    Raises:
        RoleNameError: ``role`` is not a safe directory name.
    """
    everything = {*always_loaded(role, root=root), Path(module_spec), *interfaces}
    return tuple(sorted(everything))
