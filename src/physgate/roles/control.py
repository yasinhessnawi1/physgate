"""Control (ARCH-050): plant model, controller, stability.

First slice: automated, with a human sign-off on stability margin named by the
architecture table — not yet a mechanism anything here builds (this role's
first subtasks make no stability-margin claim; tracked for whichever later
work adds the approval-queue path for it).
"""

from __future__ import annotations

from physgate.roles.role import Role

CONTROL = Role(name="control", domain="control", architecture="ARCH-050")
