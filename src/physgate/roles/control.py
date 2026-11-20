"""Control (ARCH-050): plant model, controller, stability.

First slice: automated, with a human sign-off on stability margin named by the
architecture table (ARCH-130). The sign-off is owed by this role, as the rule table in
``orchestrator/sign_off.py`` names it: code raises an approval-queue item at the merge, and
the module is not complete until a person's approve of the values it shows acts.
"""

from __future__ import annotations

from physgate.roles.role import Role

CONTROL = Role(name="control", domain="control", architecture="ARCH-050")
