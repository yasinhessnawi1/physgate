"""Two more ways past a write deny, each fixed after 2.1.301, measured inside the OS layer.

Versions after 2.1.301 list fixes for writes that got past the sandbox: one where the
binary's own configuration directory was reached through a link, and one where, on Linux, a
write deny no longer held once a command started in the background had outlived its
session. Whether either lets a write through the OS layer as it is generated here is
measured on every pin, with commands whose words name nothing the hooks' text check reads,
so the layer alone decides. Each row fails if the write lands. Each has its control without
the layer, where the same command lands its write, which shows the probe works.

A third fix was for a file named to the binary as its MCP configuration, which sandboxed
commands could change. No session of the harness is given one: that is held where the
arguments are built, and here on what the installer hands a spawn.

What only records a version's behaviour (whether a detached command outlives a session that
has no survivor reaper in front of it) is held per platform and pin as it was measured.
"""

from __future__ import annotations

import sys
import time
from collections.abc import Iterator
from pathlib import Path

import pytest
from fake_messages_api import Script, text, tool
from hook_session import pinned_version
from hook_session import run_session as run_hook_session
from os_layer_rig import Layout, layer_here, make_layout, python, run_session
from test_a_shell_command_cannot_write_the_proposals_inside_the_os_layer import (
    LANDED,
    _landed,
    _staged_file,
)

from physgate.hooks import graph

pytestmark = pytest.mark.integration


@pytest.fixture
def layer() -> None:
    if not layer_here():
        pytest.skip("the OS layer cannot run here")


@pytest.fixture
def layout(tmp_path: Path) -> Iterator[Layout]:
    with make_layout(tmp_path) as made:
        yield made


def _here() -> tuple[str, str]:
    return ("linux" if sys.platform.startswith("linux") else sys.platform, pinned_version())


#: Two writes into the session's own configuration directory: by its name from the
#: environment, and through a link to it made in the worktree first.
INTO_THE_CONFIGURATION = python(
    "import os\n"
    "top = os.environ['CLAUDE_' + 'CONFIG_DIR']\n"
    "for name, into in (('direct', top), ('linked', 'cfg')):\n"
    "    try:\n"
    "        if into == 'cfg':\n"
    "            os.symlink(top, 'cfg')\n"
    "        with open(os.path.join(into, 'planted-' + name + '.json'), 'w') as out:\n"
    "            out.write('{}')\n"
    "    except OSError as exc:\n"
    "        print(name, 'refused', exc.errno)\n"
)


def _planted(layout: Layout) -> list[str]:
    return sorted(p.name for p in (layout.sdir / "config").glob("planted-*"))


@pytest.mark.usefixtures("layer")
def test_with_the_layer_nothing_is_written_into_the_configuration_directory_by_name_or_link(
    layout: Layout,
) -> None:
    run_session(layout, [tool("Bash", command=INTO_THE_CONFIGURATION)], layer=True)
    assert _planted(layout) == [], pinned_version()


@pytest.mark.usefixtures("layer")
def test_without_the_layer_both_writes_land_which_shows_the_probe_works(layout: Layout) -> None:
    run_session(layout, [tool("Bash", command=INTO_THE_CONFIGURATION)], layer=False)
    assert _planted(layout) == ["planted-direct.json", "planted-linked.json"]


#: A command that starts a process of its own session and returns at once. The process
#: waits past the session's end, marks in the home that it lived, and then copies the
#: staged cross node into the proposals.
OUTLIVING = python(
    "import subprocess, sys\n"
    "later = (\n"
    "    'import os, shutil, time\\n'\n"
    "    'time.sleep(40)\\n'\n"
    '    \'open(os.path.join(os.path.expanduser(chr(126)), "outlived.txt"), "w").close()\\n\'\n'
    '    \'d = os.path.join(".phys" + "gate", "propo" + "sals")\\n\'\n'
    f'    \'shutil.copy("staged.txt", os.path.join(d, "{LANDED}"))\\n\'\n'
    ")\n"
    "subprocess.Popen(\n"
    "    [sys.executable, '-c', later],\n"
    "    start_new_session=True,\n"
    "    stdin=subprocess.DEVNULL,\n"
    "    stdout=subprocess.DEVNULL,\n"
    "    stderr=subprocess.DEVNULL,\n"
    ")\n"
)

#: Whether the detached process outlives a session that has no survivor reaper in front of
#: its commands, per platform and pin (measured). Where it does, the write deny is all that
#: stands between it and the proposals once the session is gone.
#: macOS (Seatbelt, 12.11.2026): it outlives the session on both pins, still inside the
#: sandbox it was started in, and lands nothing. Linux (bubblewrap, CI, 12.11.2026): it
#: does not outlive the session on either pin, so nothing is left to write.
OUTLIVES_THE_SESSION: dict[tuple[str, str], bool] = {
    ("darwin", "2.1.301"): True,
    ("darwin", "2.1.322"): True,
    ("linux", "2.1.301"): False,
    ("linux", "2.1.322"): False,
}


def _after_the_session(layout: Layout, *, layer: bool) -> dict[str, bool]:
    (layout.worktree / graph.PROPOSALS_DIR).mkdir(parents=True, exist_ok=True)
    started = time.monotonic()
    run_session(
        layout, [_staged_file(layout), tool("Bash", command=OUTLIVING)], layer=layer, reaper=False
    )
    ended = time.monotonic() - started
    # The process was started during the session, so its write is due before this is over.
    time.sleep(46.0)
    return {
        "the session ended before the write was due": ended < 40.0,
        "outlived": (layout.sdir / "home" / "outlived.txt").exists(),
        "landed": _landed(layout),
    }


@pytest.mark.usefixtures("layer")
def test_a_command_that_outlives_its_session_still_lands_nothing_in_the_proposals(
    layout: Layout,
) -> None:
    found = _after_the_session(layout, layer=True)
    assert found["the session ended before the write was due"], found
    assert found["landed"] is False, (_here(), found)
    measured = OUTLIVES_THE_SESSION.get(_here())
    assert measured is not None, f"not measured on {_here()} yet; found {found}"
    assert found["outlived"] is measured, (_here(), found)


@pytest.mark.usefixtures("layer")
def test_without_the_layer_the_same_command_lands_one_which_shows_the_probe_works(
    layout: Layout,
) -> None:
    found = _after_the_session(layout, layer=False)
    assert found == {
        "the session ended before the write was due": True,
        "outlived": True,
        "landed": True,
    }, _here()


def test_what_the_installer_hands_a_spawn_names_no_mcp_configuration(tmp_path: Path) -> None:
    run = run_hook_session(tmp_path, Script(main=[text("end")]))
    handed = [
        *run.installed.spawn_args,
        *run.installed.spawn_env,
        *run.installed.spawn_env.values(),
    ]
    assert not [word for word in handed if "mcp" in word.lower()], handed
