"""The command Claude Code runs: ``python -I -m physgate.hooks <event> ...``.

Imports happen inside the guard, so a hook package that fails to import refuses
the call instead of exiting with a status Claude Code would read as permission.
"""

from __future__ import annotations

import sys


def _run() -> int:
    try:
        stdin_text = sys.stdin.read()
        from physgate.hooks.registry import REGISTRY
        from physgate.hooks.runtime import main
    except BaseException as exc:  # noqa: BLE001 - every failure must become a refusal
        # Its kind, never its text, which can name a file it met (``runtime.failure``).
        kind = type(exc).__name__
        if isinstance(exc, ImportError) and isinstance(exc.name, str):
            kind += f", module {exc.name}"
        sys.stderr.write(f"The hook package could not load ({kind}), so the call is refused.\n")
        return 2
    return main(sys.argv[1:], stdin_text, REGISTRY)


if __name__ == "__main__":
    raise SystemExit(_run())
