"""Run the AVR simulator rig's own JavaScript from a test: Node, the rig's sources, JSON back.

The rows that need no simulator (the scenario reader, the sensor models, the launcher) run on
any Node on the search path, since none of them loads avr8js; CI's unit job has one.
"""

from __future__ import annotations

import json
import shutil
import subprocess
from pathlib import Path
from typing import Any

import pytest

REPO = Path(__file__).resolve().parents[3]
RIG = REPO / "toolenv" / "avrsim"
SOURCES = RIG / "src"


def node() -> str:
    """A Node to run the rig's modules with."""
    found = shutil.which("node")
    if found is None:
        pytest.fail("the simulator rig's rows need a Node on the search path")
    return found


def evaluate(script: str) -> Any:
    """Run ``script`` as an ES module with ``SRC`` naming the rig's sources; its JSON print.

    The script prints one JSON value with ``out(value)``.
    """
    prelude = (
        f"const SRC = {json.dumps(SOURCES.as_uri())};\n"
        "const out = (v) => console.log(JSON.stringify(v));\n"
    )
    done = subprocess.run(
        [node(), "--input-type=module", "-"],
        input=prelude + script,
        capture_output=True,
        text=True,
        timeout=60,
        check=False,
    )
    assert done.returncode == 0, done.stderr
    return json.loads(done.stdout.strip().splitlines()[-1])
