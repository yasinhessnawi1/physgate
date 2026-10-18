"""Through the real binary: ordinary agent commands do the same with the OS layer as without it.

The commands are the 123 gathered to check the shell layer for false refusals
(``os_layer_commands.json``): builds, tests, git, heredocs, loops, interpreters,
temporary files. Each arm runs all of them, in order, in one role session over the
same fixture worktree (a module with a script, parameters, results, makefiles and a
small CMake project), with the hooks on in both. A command is refused by the OS
layer if, with the layer on, it ends differently (its exit status) and either what it
was told carries the sandbox's denial or it succeeded without the layer; anything else
that differs is reported, not judged.

The cost is measured beside it: sessions of ``true`` commands, the two arms
interleaved, so the per-command difference is a same-day comparison on one machine.

Set ``PHYSGATE_OSLAYER_REPORT`` to a directory to keep both reports as JSON.
"""

from __future__ import annotations

import json
import os
import re
import statistics
import sys
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path
from typing import Any

import pytest
from fake_messages_api import tool
from os_layer_rig import Layout, layer_here, make_layout, run_session

from physgate.oslayer.abort import OS_LAYER_ABORTED, is_abort

pytestmark = pytest.mark.integration

COMMANDS: list[str] = json.loads((Path(__file__).parent / "os_layer_commands.json").read_text())[
    "commands"
]

#: What the sandbox says when it refuses an access, on macOS and on Linux.
DENIALS = ("operation not permitted", "read-only file system")

_EXIT = re.compile(r"^Exit code (\d+)")

FIXTURE = {
    "results.json": '{"a": 1, "items": [1, 2]}\n',
    "a.py": "print(1)\n",
    "b.py": "print(2)\n",
    "req.txt": "",
    "Makefile": "all:\n\t@echo built\ntest:\n\t@echo tested\nhtml:\n\t@echo html\n",
    "CMakeLists.txt": (
        "cmake_minimum_required(VERSION 3.10)\nproject(p C)\nenable_testing()\n"
        "add_executable(p main.c)\nadd_test(NAME p COMMAND p)\n"
    ),
    "main.c": "int main(void) { return 0; }\n",
    "build/Makefile": "all:\n\t@echo built\ntest:\n\t@echo tested\n",
    "tests/test_x.py": "def test_x():\n    assert 1\n",
    "modules/control/sim.py": "import sys\nprint('sim', sys.argv[1:])\n",
    "modules/control/params.json": '{"kp": {"value": 1.2, "unit": "1"}}\n',
    "modules/control/config.json": '{"items": [1, 2, 3]}\n',
    "modules/control/Makefile": "all:\n\t@echo built\ntest:\n\t@echo tested\n",
    "sim.py": "print('sim')\n",
    "runs/.keep": "",
    "out/.keep": "",
}


@pytest.fixture
def layer() -> None:
    if not layer_here():
        pytest.skip("the OS layer cannot run here")


@contextmanager
def _fixture(tmp_path: Path) -> Iterator[Layout]:
    with make_layout(tmp_path) as made:
        for rel, content in FIXTURE.items():
            path = made.worktree / rel
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(content)
        yield made


def _told(layout: Layout, steps: list[dict[str, object]], *, on: bool) -> list[str]:
    # An aborted command is reported in its own column first, then fails the test below.
    told = run_session(layout, steps, layer=on, timeout=1800, aborts_fail=False)["told"]
    assert isinstance(told, list)
    return [str(t) for t in told]


def _seconds(layout: Layout, steps: list[dict[str, object]], *, on: bool) -> float:
    seconds = run_session(layout, steps, layer=on)["seconds"]
    assert isinstance(seconds, float)
    return seconds


def _ended(told: str) -> tuple[int, bool]:
    """A command's exit status, and whether it was told of a sandbox denial."""
    match = _EXIT.match(told)
    return (int(match.group(1)) if match else 0), any(d in told.casefold() for d in DENIALS)


def _report(name: str, data: dict[str, Any]) -> None:
    where = os.environ.get("PHYSGATE_OSLAYER_REPORT")
    if where:
        Path(where).mkdir(parents=True, exist_ok=True)
        (Path(where) / f"{name}-{sys.platform}.json").write_text(json.dumps(data, indent=1))


@pytest.mark.usefixtures("layer")
def test_no_ordinary_command_is_refused_by_the_os_layer(tmp_path: Path) -> None:
    steps = [tool("Bash", command=c, description=f"command {n}") for n, c in enumerate(COMMANDS)]
    arms: dict[str, list[str]] = {}
    for arm, layer_on in (("off", False), ("on", True)):
        with _fixture(tmp_path / arm) as layout:
            arms[arm] = _told(layout, steps, on=layer_on)
    rows = []
    for n, command in enumerate(COMMANDS):
        told_off, told_on = arms["off"][n], arms["on"][n]
        (exit_off, denied_off), (exit_on, denied_on) = _ended(told_off), _ended(told_on)
        # A possible abort: the result carries bubblewrap's own line. A command could print
        # it, so it is a column beside the others and changes none of them; any one fails
        # the test, since a command no layer judged says nothing about the layer.
        aborted = is_abort(told_on)
        # Refused by the layer: it ends otherwise with the layer, and either it was told of
        # the sandbox's denial (which it was not told without the layer) or it succeeded
        # without the layer and fails with it.
        refused = exit_on != exit_off and ((denied_on and not denied_off) or exit_off == 0)
        rows.append(
            {
                "n": n,
                "command": command,
                "exit_off": exit_off,
                "exit_on": exit_on,
                "denied_on": denied_on,
                OS_LAYER_ABORTED: aborted,
                "refused_by_layer": refused,
                "told_on": told_on[:400] if refused or aborted or exit_on != exit_off else "",
            }
        )
    refused_rows = [r for r in rows if r["refused_by_layer"]]
    aborted_rows = [r for r in rows if r[OS_LAYER_ABORTED]]
    _report(
        "commands",
        {
            "commands": len(COMMANDS),
            "refused_by_layer": len(refused_rows),
            OS_LAYER_ABORTED: len(aborted_rows),
            "ended_differently": sum(r["exit_on"] != r["exit_off"] for r in rows),
            "rows": rows,
        },
    )
    # The shared temporary directories are writable (and Claude Code's own one in them is
    # not), so the commands that write there by name are not refused.
    known: set[int] = set()
    assert {r["n"] for r in refused_rows} == known, [(r["n"], r["command"]) for r in refused_rows]
    # No command may have gone unjudged: an abort says nothing about the layer either way.
    assert aborted_rows == [], [(r["n"], r["told_on"]) for r in aborted_rows]


@pytest.mark.usefixtures("layer")
def test_the_os_layer_s_cost_per_command_is_measured(tmp_path: Path) -> None:
    n_commands, rounds = 40, 3
    steps = [tool("Bash", command="true", description="t") for _ in range(n_commands)]
    seconds: dict[str, list[float]] = {"off": [], "on": []}
    for r in range(rounds):
        for arm, on in (
            (("off", False), ("on", True)) if r % 2 == 0 else (("on", True), ("off", False))
        ):
            with _fixture(tmp_path / f"{arm}{r}") as layout:
                seconds[arm].append(_seconds(layout, steps, on=on))
    per_command_ms = {
        arm: [1000 * s / n_commands for s in values] for arm, values in seconds.items()
    }
    difference = statistics.median(per_command_ms["on"]) - statistics.median(per_command_ms["off"])
    _report(
        "cost",
        {
            "commands_per_session": n_commands,
            "rounds": rounds,
            "session_seconds": seconds,
            "per_command_ms": per_command_ms,
            "median_difference_ms_per_command": difference,
        },
    )
    assert all(len(v) == rounds for v in seconds.values())
