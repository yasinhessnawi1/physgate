"""What a stand-in for the hook installer must give a session's spawn, as the real one does.

The held spawn refuses an environment without a ``ZDOTDIR`` that is an empty directory outside
the session's home. A test that replaces the installer gives its session this one.
"""

from __future__ import annotations

import atexit
import shutil
import tempfile


def stand_in_spawn_env() -> dict[str, str]:
    """A spawn environment with an empty ``ZDOTDIR`` of its own, removed when the tests end."""
    where = tempfile.mkdtemp(prefix="pg-zdotdir-")
    atexit.register(shutil.rmtree, where, ignore_errors=True)
    return {"ZDOTDIR": where}
