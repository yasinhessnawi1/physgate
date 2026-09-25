"""Reasons an agent is given for protected roots that more than one module names.

Kept apart so the hooks on the hot path can use them without importing the
settings generator, which imports the validation library.
"""

from __future__ import annotations

HELD_OUT_REASON = (
    "it is the held-out evaluation tier, which nothing reads or writes before "
    "measurement (ARCH-141)"
)
GATE_REASON = "it holds the physics gate, which no agent session writes (ARCH-081)"
STORE_REASON = (
    "it is the design-state graph's own store: its journal is the only authority, and a "
    "line appended to it is replayed as genuine, so no agent tool writes any file in it"
)
