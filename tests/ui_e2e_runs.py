"""Build the runs the operator UI's browser tests read, under one root, and print that root.

Three runs made by the real loop with stand-in sessions and no model: gated on, observed and
clean (see ``ui_rig.real_runs``). The browser tests start ``physgate ui`` over the root this
prints, so what they check is the real server reading real records.

Usage: ``uv run python tests/ui_e2e_runs.py <directory>``. The directory is emptied first.
"""

from __future__ import annotations

import shutil
import sys
from pathlib import Path

from ui_rig import real_runs


def main(argv: list[str]) -> int:
    """Build the runs under ``argv[1]`` and print the root that holds them."""
    out = Path(argv[1])
    shutil.rmtree(out, ignore_errors=True)
    out.mkdir(parents=True)
    print(real_runs(out), flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
