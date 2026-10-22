"""Integration (ARCH-051): interface satisfaction, and the only role that may declare completion.

It runs last, checks every interface between the modules that share one and the
system as a whole, and proposes that a module is complete. Merged is not complete:
only an accepted integration attempt can make it so. It has no domain, and is not
given one.
"""

from __future__ import annotations

from physgate.roles.role import CrossCuttingRole

INTEGRATION = CrossCuttingRole(name="integration", architecture="ARCH-051", owns="completion")
