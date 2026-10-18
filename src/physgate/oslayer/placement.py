"""Where a sandboxed session's worktree may lie: outside every place the OS layer makes writable.

On Linux, while a sandboxed command runs, the sandbox holds Claude Code's protected
names (``.mcp.json``, ``.claude/settings.json``, ...) with an empty read-only
placeholder in every ancestor of the working directory that lies inside a writable
place, and removes them when the command ends. The shared temporary directories are
writable for every session, so two sessions whose worktrees share an ancestor there
share those placeholders: one removes a placeholder the other's bubblewrap still
names, and that command aborts before it runs (measured on the Oracle VM, 18.10.2026).
A worktree outside every writable place gets placeholders in itself alone.

So a sandboxed session is refused a worktree inside the shared temporary
directories, Claude Code's own temporary directory inside them, or any other place
its sandbox makes writable. The judgement is the R-HK-03 runner's, for its scratch
roots: by spelling, as given and as resolved, and by identity, ancestor by ancestor.
"""

from __future__ import annotations

import os
from collections.abc import Iterable
from pathlib import Path

from physgate.oslayer.probe import claude_temp_dirs, shared_temp_dirs


def machine_writable() -> tuple[str, ...]:
    """The places on this machine no sandboxed session's worktree may lie in.

    The shared temporary directories, which the OS layer lets every session write, and
    Claude Code's own temporary directory inside them, which it denies both ways but
    which every session of the user shares.
    """
    return (*shared_temp_dirs(), *claude_temp_dirs())


def _same_place(path: Path, place: str) -> bool:
    try:
        return os.path.samefile(path, place)
    except OSError:
        return False


def placement_refusal(worktree: Path, writable: Iterable[str]) -> str | None:
    """Why ``worktree`` may not hold a sandboxed session; ``None`` where it lies outside them all.

    Judged where an access lands, as the sandbox judges it: by spelling, on the path
    as given and as resolved (``/tmp`` is ``/private/tmp`` on macOS), and by identity,
    each existing ancestor of either against each place. Identity catches what no
    spelling shows: a case variant on a volume that ignores case, and a second path
    to the same directory (``/System/Volumes/Data`` on macOS).
    """
    places = list(writable)
    refusal = (
        f"the worktree {worktree} lies inside {{place}}, a place the OS layer makes "
        "writable; sandboxed sessions there can abort each other's commands"
    )
    resolved = Path(os.path.realpath(worktree))
    for spelling in {Path(str(worktree)), resolved}:
        for place in places:
            for spelled in {Path(place), Path(os.path.realpath(place))}:
                if spelling == spelled or spelling.is_relative_to(spelled):
                    return refusal.format(place=place)
        for ancestor in (spelling, *spelling.parents):
            if not os.path.lexists(ancestor):
                continue
            for place in places:
                if _same_place(ancestor, place):
                    return refusal.format(place=place)
    return None
