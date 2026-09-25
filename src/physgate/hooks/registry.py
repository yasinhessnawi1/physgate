"""Every hook module, by name. The settings generator wires exactly these.

A module is a hook module when it defines a module-level ``HOOK``. A test walks
the package and fails if a module defining one is missing here, so a hook that
exists but is never wired cannot pass unnoticed.
"""

from __future__ import annotations

from collections.abc import Mapping

from physgate.hooks.runtime import HookSpec

REGISTRY: Mapping[str, HookSpec] = {}
