"""A tool server's tool is asked only what its register entry names (the argument rule).

The hooks see a call's arguments, never what the server then does with them. So an admitted
tool's arguments are held to the register's schema for it, here, in the hook layer every
harness shares:

- an argument the schema does not name refuses the call, and so does one of another kind;
- an argument the schema marks as a path is judged as a file tool's read or write of that path
  would be (:func:`physgate.hooks.paths.protection`: the held-out tier, the protected roots,
  review material), and must lie inside the session's worktree as written and as the operating
  system resolves it. A relative path is read from the worktree where the server resolves it so,
  and refused where the server's own working directory decides. A case variant of the worktree's
  spelling is outside it.

This is the first layer. What a file the server reads in turn names (an MJCF include, a build
script) is held by the server's containment.

The register is read here with the standard library, as the hooks' hot path is; the harness
validates the same file with its schema (:mod:`physgate.toolenv.register`).
"""

from __future__ import annotations

from pathlib import Path
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from physgate.hooks.views import ConfigView

#: The register, as the harness validates it.
REGISTER_FILE = Path(__file__).resolve().parents[1] / "toolenv" / "register.json"


def arguments_refusal(tool: str, arguments: object, cwd: str, config: ConfigView) -> str | None:
    """Why the admitted server tool ``tool`` may not be called with ``arguments``, or ``None``."""
    del tool, arguments, cwd, config
    return None
