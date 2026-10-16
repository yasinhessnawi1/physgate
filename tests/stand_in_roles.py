"""The suite's stand-in roles, registered for tests only.

The suite and the runs the browser tests read plan ``electrical`` and ``mechanical``
stand-ins. The shipped role register holds control and firmware alone, and a run
refuses any other role at its start, so whatever builds such runs registers the
stand-ins first: ``conftest`` for the length of a test session, and a script outside
pytest (``ui_e2e_runs.py``) for the length of its process.
"""

from __future__ import annotations

from physgate import roles


def stand_in_roles() -> dict[str, roles.Role]:
    """Each stand-in role, by name."""
    return {
        "electrical": roles.Role(name="electrical", domain="electrical", architecture="ARCH-050"),
        "mechanical": roles.Role(name="mechanical", domain="mechanical", architecture="ARCH-050"),
    }


def register() -> None:
    """Register the stand-ins in this process's role register."""
    roles.ROLES.update(stand_in_roles())
