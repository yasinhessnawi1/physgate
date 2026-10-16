"""A stand-in worktree holding the series writer where a run puts it, and a way to run scripts.

Scripts run as real processes. They use ``-E -s`` (no ``PYTHON*`` variables, no user
site-packages) and not ``-I``, because a role session runs ``python3 script.py`` with its
own empty home and the script's own directory on the path, which ``-I`` would remove. The
user site is kept out because on a developer machine it loads code (measured: setuptools'
``_distutils_hack``) that a role session's empty home never would.
"""

from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

import physgate.series.writer as writer_module

WRITER_SOURCE = Path(writer_module.__file__).read_bytes()

#: A script that simulates nothing: it imports a sibling module and records made-up numbers,
#: labelled as such, through the writer.
SCRIPT = """
import os, sys
here = os.path.dirname(os.path.abspath(__file__))
while not os.path.isfile(os.path.join(here, ".physgate", "lib", "series_writer.py")):
    here = os.path.dirname(here)
sys.path.insert(0, os.path.join(here, ".physgate", "lib"))
import series_writer
import helper
{extra}
path = series_writer.record(
    "{record_id}",
    title="Fixture step, not a simulation result",
    axis="time",
    x=("time", "s", [0.0, 0.01, 0.02]),
    traces=[("position", "m", [0.0, helper.GAIN * 0.01, 0.05])],
    inputs={{"seed": (7, "dimensionless")}},
    group="step",
)
print(path)
"""


def worktree(root: Path) -> Path:
    """A worktree with the writer at its place, a module with a helper, and no outbox yet."""
    base = Path(os.path.realpath(root)) / "worktree"
    lib = base / ".physgate" / "lib"
    lib.mkdir(parents=True)
    (lib / "series_writer.py").write_bytes(WRITER_SOURCE)
    module = base / "modules" / "control"
    module.mkdir(parents=True)
    (module / "helper.py").write_text("GAIN = 2.0\n")
    return base


def write_script(
    base: Path, name: str = "sim.py", record_id: str = "step_nominal", extra: str = ""
) -> Path:
    """A script under the module directory that writes one record."""
    path = base / "modules" / "control" / name
    path.write_text(SCRIPT.format(record_id=record_id, extra=extra))
    return path


def run(script: Path, interpreter: str = sys.executable) -> subprocess.CompletedProcess[str]:
    """Run ``script`` the way a role session would, from the worktree."""
    base = script.parents[2]
    return subprocess.run(
        [interpreter, "-E", "-s", str(script)],
        cwd=base,
        capture_output=True,
        text=True,
        timeout=60,
        env={"PATH": "/usr/bin:/bin", "HOME": str(base / ".home")},
        check=False,
    )
