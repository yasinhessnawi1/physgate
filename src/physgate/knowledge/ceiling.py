"""Measuring a candidate always-loaded set against the hook layer's own token ceiling (ARCH-023).

This does not decide a real session's fate — :mod:`physgate.hooks.token_ceiling`
already does that, from the session's own configuration, at every tool call.
This module exists for everyone else who needs the same answer before a
session runs: curating a standards file and asking whether it now fits under a
proposed ceiling, and a test that a fixture over the ceiling fails and one
under it passes.

It reuses the hook layer's estimator through the exact function a real session
is measured by, rather than building a second one that could drift from the
first. ``ConfigView`` is a structural ``Protocol``, so calling it needs an
object with every one of its members, not only the two this measurement reads
— :class:`physgate.hooks.config.SessionConfig` is that Protocol's own
production implementation, so a real (not partial) instance of it, with
placeholder values for the fields this check never reads, is what is built
here.
"""

from __future__ import annotations

import sys
from collections.abc import Sequence
from pathlib import Path

from physgate.hooks.config import Installation, SessionConfig
from physgate.hooks.token_ceiling import measure as _hook_measure

#: Fields `token_ceiling.measure` never reads, held to harmless, valid values so
#: a `SessionConfig` can be built without a real session's directories existing.
_PLACEHOLDER_ROOT = "/knowledge-ceiling-check"


def _shim(paths: Sequence[Path], ceiling: int, role: str) -> SessionConfig:
    """A complete, valid ``SessionConfig`` whose load-bearing fields for this call are real."""
    return SessionConfig(
        profile="role",
        role=role,
        worktree=_PLACEHOLDER_ROOT,
        own_branch=None,
        store_root=None,
        state_dir=_PLACEHOLDER_ROOT + "-state",
        protected_roots=(),
        experiments=(),
        held_out=(),
        answer_keys=(),
        required_reading=(),
        always_loaded=tuple(str(Path(p)) for p in paths),
        token_ceiling=ceiling,
        tools_allowed=(),
        installation=Installation(
            interpreter=sys.executable,
            package_dir=sys.prefix,
            environment_root=sys.prefix,
            base_prefix=sys.base_prefix,
        ),
        watchdog_seconds=5,
        hook_timeout_seconds=30,
    )


def fits(paths: Sequence[Path], ceiling: int, *, role: str = "knowledge") -> bool:
    """Whether the total size of ``paths`` is within ``ceiling``, by the same estimator."""
    return _hook_measure(_shim(paths, ceiling, role)).allow


def breach_reason(paths: Sequence[Path], ceiling: int, *, role: str = "knowledge") -> str | None:
    """The hook layer's own refusal text if ``paths`` breaches ``ceiling``; ``None`` if it fits.

    The text names each file, largest first, exactly as a real session over its
    ceiling would be told, since it comes from the same call.
    """
    decision = _hook_measure(_shim(paths, ceiling, role))
    return None if decision.allow else decision.reason
