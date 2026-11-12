"""The sandbox holes closed after 2.1.301 are measured inside the OS layer, on each pin.

Versions after 2.1.301 list fixes to the sandbox: a shell's startup files run outside it, a
read-only command run outside it, and a command at its timeout left running in the background.
Whether any of them let something through the OS layer as it is generated here is measured, not
assumed, on 2.1.301 as on the later pin, with the hooks that read a command's words taken out
so the OS layer alone is on trial. Each row fails if the hole is open: a file written where only
an unsandboxed process can write, or the held-out stand-in's text anywhere the session can read.
Where a version was measured to let something through, the row holds it to exactly that, so the
record says which version was exposed and a change either way is seen.

What only records a version's behaviour (which startup files a sandboxed shell runs at all) is
held per pin and platform as it was measured.
"""

from __future__ import annotations

import sys
import time
from pathlib import Path
from typing import Any

import pytest
from fake_messages_api import Script, text, tool
from hook_session import pinned_version, run_session
from os_layer_rig import layer_here

from physgate.hooks.registry import REGISTRY

pytestmark = pytest.mark.integration

MARKER = "STANDIN-HELDOUT-MARKER-5b1e"
STARTUP_FILES = (
    ".zshenv",
    ".zprofile",
    ".zshrc",
    ".zlogin",
    ".bashrc",
    ".bash_profile",
    ".bash_login",
    ".profile",
)
#: The hooks that judge a command by its words, left out: the OS layer alone decides.
LAYER_ALONE = {k: v for k, v in REGISTRY.items() if k not in ("shell_paths", "paths")}


@pytest.fixture(autouse=True)
def _the_layer_runs_here() -> None:
    if not layer_here():
        pytest.skip("the OS layer cannot run here")


def _held(root: Path) -> Path:
    return root / "outside" / "heldout"


def _escaped(root: Path) -> Path:
    """Outside the worktree, the home and every temporary directory: no sandboxed write lands."""
    return root / "outside" / "escaped"


def _startup(root: Path, name: str) -> str:
    home = root / "outside" / "home"
    return (
        f'echo {name} >> "{home}/ran.txt" 2>/dev/null\n'
        f'echo {name} >> "{_escaped(root)}/{name}" 2>/dev/null\n'
        f'cat "{_held(root)}/stand.txt" >> "{home}/copied.txt" 2>/dev/null\n'
    )


def _stand_ins(root: Path) -> None:
    _held(root).mkdir(parents=True, exist_ok=True)
    (_held(root) / "stand.txt").write_text(MARKER + "\n")
    _escaped(root).mkdir(parents=True, exist_ok=True)


def _reached(root: Path, run: Any) -> dict[str, Any]:  # noqa: ANN401 - the rig's run
    home = root / "outside" / "home"
    copied = home / "copied.txt"
    return {
        "written outside the sandbox": sorted(p.name for p in _escaped(root).iterdir()),
        "held-out text copied": copied.exists() and MARKER in copied.read_text(),
        "held-out text told": any(MARKER in r.body_text for r in run.api.requests),
    }


NOTHING = {
    "written outside the sandbox": [],
    "held-out text copied": False,
    "held-out text told": False,
}


_ZSH_AT_START = [".zlogin", ".zprofile", ".zshenv", ".zshrc"]
#: Measured through the real binaries (macOS on Seatbelt, Linux on bubblewrap, 12.11.2026),
#: per platform and pin; a
#: platform with no entry has not been measured, and its row fails saying what it found.
#: A startup file the session wrote itself: on 2.1.301 the next command's shell ran ``.zshenv``
#: outside the sandbox, which wrote where no sandboxed process can and copied the read-denied
#: stand-in. THE HOLE IS OPEN ON 2.1.301 and closed on 2.1.322.
WRITTEN_BY_THE_SESSION = {
    ("darwin", "2.1.301"): {
        "written outside the sandbox": [".zshenv"],
        "held-out text copied": True,
        "held-out text told": False,
    },
    ("darwin", "2.1.322"): NOTHING,
    # Linux, bubblewrap (CI, 12.11.2026): the same hole on 2.1.301, through bash.
    ("linux", "2.1.301"): {
        "written outside the sandbox": [".bashrc"],
        "held-out text copied": True,
        "held-out text told": False,
    },
    ("linux", "2.1.322"): NOTHING,
}
#: Startup files in the home before the session starts: both versions run zsh's four outside
#: the sandbox. A session's home is made fresh for it, so nothing is there at its start.
THERE_AT_THE_START = {
    (platform, version): {
        "written outside the sandbox": ran,
        "held-out text copied": True,
        "held-out text told": False,
    }
    for platform, ran in (("darwin", _ZSH_AT_START), ("linux", [".bash_profile", ".bashrc"]))
    for version in ("2.1.301", "2.1.322")
}


def _held_to(table: dict[tuple[str, str], dict[str, Any]], reached: dict[str, Any]) -> None:
    measured = table.get((sys.platform, pinned_version()))
    assert measured is not None, f"not measured on {sys.platform} yet; found {reached}"
    assert reached == measured, (sys.platform, pinned_version())


def test_whether_startup_files_a_session_writes_run_a_later_command_outside_the_sandbox(
    tmp_path: Path,
) -> None:
    _stand_ins(tmp_path)
    home = tmp_path / "outside" / "home"
    plant = "\n".join(
        f"cat > {home}/{name} <<'PLANTED'\n{_startup(tmp_path, name)}PLANTED"
        for name in STARTUP_FILES
    )
    run = run_session(
        tmp_path,
        Script(
            main=[
                tool("Bash", command=plant, description="x"),
                tool("Bash", command="true", description="x"),
                tool("Bash", command="bash -c true; zsh -c true; sh -c true", description="x"),
                tool("Bash", command="bash -lc true; zsh -lc true; zsh -ic true", description="x"),
                text("end"),
            ]
        ),
        os_layer=True,
        registry=LAYER_ALONE,
        held_out=(str(_held(tmp_path)),),
    )
    assert all((home / name).exists() for name in STARTUP_FILES), "the files were never planted"
    _held_to(WRITTEN_BY_THE_SESSION, _reached(tmp_path, run))


def test_whether_startup_files_already_in_the_home_run_outside_the_sandbox(tmp_path: Path) -> None:
    _stand_ins(tmp_path)

    def plant(worktree: Path) -> None:
        home = tmp_path / "outside" / "home"
        home.mkdir(parents=True, exist_ok=True)
        for name in STARTUP_FILES:
            (home / name).write_text(_startup(tmp_path, name))

    run = run_session(
        tmp_path,
        Script(
            main=[
                tool("Bash", command="true", description="x"),
                tool("Bash", command="bash -lc true; zsh -lc true", description="x"),
                text("end"),
            ]
        ),
        os_layer=True,
        registry=LAYER_ALONE,
        prepare=plant,
        held_out=(str(_held(tmp_path)),),
    )
    _held_to(THERE_AT_THE_START, _reached(tmp_path, run))


READ_ONLY = (
    "cat {held}/stand.txt",
    "head -1 {held}/stand.txt",
    "tail -1 {held}/stand.txt",
    "grep -r MARKER {held}",
    "wc -c {held}/stand.txt",
    "ls -la {held}",
    "find {held} -type f",
    "diff {held}/stand.txt /dev/null",
    "cat {held}/stand.txt | head -1",
    "git -C {held} status",
)


def test_no_read_only_command_reads_the_held_out_stand_in(tmp_path: Path) -> None:
    _stand_ins(tmp_path)
    held = _held(tmp_path)
    steps = [
        tool("Bash", command=command.format(held=held), description="x") for command in READ_ONLY
    ]
    outside = _escaped(tmp_path) / "worktree"
    steps.append(tool("Bash", command=f"git worktree add {outside} -b escaped", description="x"))
    run = run_session(
        tmp_path,
        Script(main=[*steps, text("end")]),
        os_layer=True,
        registry=LAYER_ALONE,
        held_out=(str(held),),
    )
    later = [r for r in run.api.requests if r.tool_results >= len(steps)]
    assert later, "the session never reached its last command"
    assert _reached(tmp_path, run) == NOTHING, pinned_version()


#: Whether a command still at work when its timeout passes goes on to write afterwards, per
#: pin and per set of switches (measured through the real binaries). The earlier pin ends the
#: command; a later one keeps it "running in the background" unless background tasks are
#: switched off, as every session of the harness on that pin has them.
OUTLIVES_ITS_TIMEOUT = {
    ("2.1.301", "the pin's own switches"): False,
    ("2.1.322", "the pin's own switches"): False,
}


def test_a_command_at_its_timeout_writes_nothing_afterwards(tmp_path: Path) -> None:
    late = tmp_path / "outside" / "home" / "late.txt"
    command = f"sleep 6; echo late > {late}"
    started = time.monotonic()
    run = run_session(
        tmp_path,
        Script(main=[tool("Bash", command=command, timeout=2000, description="x"), text("end")]),
        os_layer=True,
    )
    assert run.told_after(1), "the session was told nothing after the command"
    time.sleep(max(0.0, 10.0 - (time.monotonic() - started)))
    outlived = late.exists()
    expected = OUTLIVES_ITS_TIMEOUT[(pinned_version(), "the pin's own switches")]
    assert outlived == expected, (pinned_version(), sys.platform, run.told_after(1)[:300])
