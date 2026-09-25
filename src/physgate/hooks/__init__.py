"""The hook layer: the enforced surface of ARCH-090, as Claude Code hooks.

Before a tool call runs, these hooks refuse what the architecture says no agent
session may do, and after a shell call a sentinel checks that nothing protected
moved.
"""

from __future__ import annotations
