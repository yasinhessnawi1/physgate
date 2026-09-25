"""Every hook module, by name. The settings generator wires exactly these.

A module is a hook module when it defines a module-level ``HOOK``. A test walks
the package and fails if a module defining one is missing here, so a hook that
exists but is never wired cannot pass unnoticed.
"""

from __future__ import annotations

from collections.abc import Mapping

from physgate.hooks import git_ops, paths, reading, token_ceiling, tools
from physgate.hooks.runtime import HookSpec

REGISTRY: Mapping[str, HookSpec] = {
    spec.name: spec
    for spec in (
        tools.HOOK,
        paths.HOOK,
        git_ops.HOOK,
        reading.HOOK,
        token_ceiling.HOOK,
    )
}
