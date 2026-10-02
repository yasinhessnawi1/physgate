"""Firmware (ARCH-050): drivers, the real-time loop, the HAL, on-target test.

First slice: automated.
"""

from __future__ import annotations

from physgate.roles.role import Role

FIRMWARE = Role(name="firmware", domain="firmware", architecture="ARCH-050")
