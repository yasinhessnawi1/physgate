"""What later versions changed around a shell command is measured on each pin, not assumed.

Versions after 2.1.301 changed four things around a role session's shell commands, and each
is measured here through the real binary on every pin, inside the OS layer where the layer
is what is on trial:

- **A background call.** A command asked to run in the background is refused by the shell
  hook on 2.1.301. Where background tasks are switched off, as every session of the harness
  on a later pin has them, the binary refuses the call itself before any hook. With the
  hooks that read a command's words taken out, what such a call can reach is the OS layer's
  alone to stop.
- **A command at its timeout.** A later version's notes say such a command is kept "running
  in the background". The controls run each pin without the switch that turns background
  tasks off, inside the OS layer and with no layer at all, and say whether the command then
  goes on to write, and where.
- **The session's temporary directory.** A path of up to 32 characters is taken as the
  commands' own; a longer one is replaced by a directory the binary picks. The installer
  refuses a longer one, and that guard is only as good as the limit it holds.
- **The shell prefix.** The survivor reaper is named by the prefix, which a version puts in
  front of every shell command and of every hook command. How many times it runs for one
  command, and with how many arguments, is what the reaper's front was written against.

Each table is per platform and pin, as measured; a platform or pin with no entry has not
been measured, and its row fails saying what it found.
"""

from __future__ import annotations

import os
import secrets
import shutil
import sys
import time
from collections.abc import Iterator
from pathlib import Path
from typing import Any

import hook_session
import pytest
from fake_messages_api import Script, text, tool
from hook_session import _run_session, pinned_version, run_session, session_switches
from os_layer_rig import layer_here

from physgate.hooks.registry import REGISTRY
from physgate.hooks.settings import OS_LAYER_TEMP_LIMIT

pytestmark = pytest.mark.integration

MARKER = "STANDIN-HELDOUT-MARKER-7c2d"
BACKGROUND_SWITCH = "CLAUDE_CODE_DISABLE_BACKGROUND_TASKS"
#: The hooks that judge a command by its words, left out: the OS layer alone decides.
LAYER_ALONE = {k: v for k, v in REGISTRY.items() if k not in ("shell_paths", "paths")}


def _here() -> tuple[str, str]:
    return ("linux" if sys.platform.startswith("linux") else sys.platform, pinned_version())


def _held_to(table: dict[tuple[str, str], Any], found: Any) -> None:  # noqa: ANN401
    measured = table.get(_here())
    assert measured is not None, f"not measured on {_here()} yet; found {found}"
    assert found == measured, _here()


@pytest.fixture
def layer() -> None:
    if not layer_here():
        pytest.skip("the OS layer cannot run here")


def _stand_ins(root: Path) -> tuple[Path, Path, Path]:
    """The session's home, a read-denied stand-in, and a place no sandboxed write lands."""
    home = root / "outside" / "home"
    held = root / "outside" / "heldout"
    escaped = root / "outside" / "escaped"
    held.mkdir(parents=True, exist_ok=True)
    (held / "stand.txt").write_text(MARKER + "\n")
    escaped.mkdir(parents=True, exist_ok=True)
    return home, held, escaped


def _reaching(home: Path, held: Path, escaped: Path, name: str, wait: int) -> str:
    """A command that waits, writes in the home and outside it, and copies the stand-in."""
    return (
        f"sleep {wait}; echo {name} > {home}/{name}.txt; "
        f"echo {name} > {escaped}/{name}.txt 2>/dev/null; "
        f"cat {held}/stand.txt > {home}/copied.txt 2>/dev/null; true"
    )


def _reached(home: Path, escaped: Path, name: str, run: Any) -> dict[str, bool]:  # noqa: ANN401
    copied = home / "copied.txt"
    return {
        "ran": (home / f"{name}.txt").exists(),
        "wrote outside the sandbox": (escaped / f"{name}.txt").exists(),
        "copied the read-denied text": copied.exists() and MARKER in copied.read_text(),
        "the read-denied text was told": any(MARKER in r.body_text for r in run.api.requests),
    }


NOTHING = {
    "ran": False,
    "wrote outside the sandbox": False,
    "copied the read-denied text": False,
    "the read-denied text was told": False,
}
INSIDE_ONLY = {**NOTHING, "ran": True}

#: Who refuses a background call under the full hook set, per pin: the shell hook where the
#: binary offers the parameter, the binary's own input check where background tasks are off.
BACKGROUND_REFUSED_BY: dict[tuple[str, str], str] = {
    (platform, version): who
    for platform in ("darwin", "linux")
    for version, who in (
        ("2.1.301", "the shell hook"),
        ("2.1.322", "the binary's input check"),
    )
}
#: What a background call reaches with the hooks that read a command's words taken out.
#: On 2.1.301 the command runs, in the background and inside the sandbox: it writes in the
#: session's home and nowhere else, and reads nothing read-denied. On 2.1.322 it never runs.
BACKGROUND_REACHES: dict[tuple[str, str], dict[str, bool]] = {
    (platform, version): reached
    for platform in ("darwin", "linux")
    for version, reached in (("2.1.301", INSIDE_ONLY), ("2.1.322", NOTHING))
}


def _who_refused(told: str) -> str:
    if "InputValidationError" in told:
        return "the binary's input check"
    if "hook" in told.lower() and "background" in told.lower():
        return "the shell hook"
    return f"no one: {told[:200]!r}"


@pytest.mark.usefixtures("layer")
def test_a_background_call_under_the_full_hook_set_is_refused_and_runs_nothing(
    tmp_path: Path,
) -> None:
    home, held, escaped = _stand_ins(tmp_path)
    command = f"sleep 1; echo bg > {home}/bg.txt; echo bg > {escaped}/bg.txt"
    call = tool("Bash", command=command, run_in_background=True, description="x")
    run = run_session(tmp_path, Script(main=[call, text("end")]), os_layer=True)
    time.sleep(4)
    assert not (home / "bg.txt").exists() and not (escaped / "bg.txt").exists()
    _held_to(BACKGROUND_REFUSED_BY, _who_refused(run.told_after(1)))


@pytest.mark.usefixtures("layer")
def test_what_a_background_call_reaches_with_the_os_layer_alone(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    # Where the call runs, its end is told to the session, which may then stop a second
    # time: the harness's check that only the generated hook commands started is kept, but
    # for that one further stop.
    check = hook_session.check_the_run_means_something

    def but_for_a_second_stop(run: Any) -> None:  # noqa: ANN401 - the rig's run
        try:
            check(run)
        except hook_session.HarnessError as exc:
            if not str(exc).endswith("{'Stop': 2}"):
                raise

    monkeypatch.setattr(hook_session, "check_the_run_means_something", but_for_a_second_stop)
    home, held, escaped = _stand_ins(tmp_path)
    call = tool(
        "Bash",
        command=_reaching(home, held, escaped, "bg", 1),
        run_in_background=True,
        description="x",
    )
    run = run_session(
        tmp_path,
        Script(main=[call, tool("Bash", command="sleep 4", description="x"), text("end")]),
        os_layer=True,
        registry=LAYER_ALONE,
        held_out=(str(held),),
    )
    time.sleep(3)
    _held_to(BACKGROUND_REACHES, _reached(home, escaped, "bg", run))


#: What a command still at work at its timeout goes on to do when background tasks are not
#: switched off, with the hooks that read a command's words taken out.
#: Measured: on neither pin does the command go on. Each ends it at its timeout (the session
#: is told ``Command timed out``), with the switch or without, so the later version's
#: "still running in the background" was not produced in a session run as the harness runs
#: one. The switch stays set on the later pin all the same.
_ENDED = {**NOTHING, "told it runs on in the background": False}
AT_ITS_TIMEOUT_WITHOUT_THE_SWITCH: dict[tuple[str, str], dict[str, bool]] = {
    (platform, version): _ENDED
    for platform in ("darwin", "linux")
    for version in ("2.1.301", "2.1.322")
}


@pytest.mark.usefixtures("layer")
def test_what_a_command_at_its_timeout_does_where_background_tasks_are_not_switched_off(
    tmp_path: Path,
) -> None:
    home, held, escaped = _stand_ins(tmp_path)
    own = session_switches(pinned_version())
    without = {name: value for name, value in own.items() if name != BACKGROUND_SWITCH}
    started = time.monotonic()
    call = tool(
        "Bash", command=_reaching(home, held, escaped, "late", 6), timeout=2000, description="x"
    )
    run = run_session(
        tmp_path,
        # The session stays alive past the moment the command would write.
        Script(main=[call, tool("Bash", command="sleep 8", description="x"), text("end")]),
        os_layer=True,
        registry=LAYER_ALONE,
        held_out=(str(held),),
        switches=without,
    )
    told = run.told_after(1)
    assert told, "the session was told nothing after the command"
    time.sleep(max(0.0, 12.0 - (time.monotonic() - started)))
    found = {
        **_reached(home, escaped, "late", run),
        "told it runs on in the background": "background" in told.lower(),
    }
    assert "timed out" in told, told[:300]
    _held_to(AT_ITS_TIMEOUT_WITHOUT_THE_SWITCH, found)


#: The same without the OS layer, so with no sandbox and no survivor reaper in front of the
#: command: whether the command went on to write, and whether the session was told it runs on.
AT_ITS_TIMEOUT_WITH_NO_LAYER_AND_NO_SWITCH: dict[tuple[str, str], dict[str, bool]] = {
    (platform, version): {"ran on": False, "told it runs on in the background": False}
    for platform in ("darwin", "linux")
    for version in ("2.1.301", "2.1.322")
}


def test_what_a_command_at_its_timeout_does_with_no_layer_and_no_switch(tmp_path: Path) -> None:
    home, held, escaped = _stand_ins(tmp_path)
    own = session_switches(pinned_version())
    without = {name: value for name, value in own.items() if name != BACKGROUND_SWITCH}
    started = time.monotonic()
    command = f"sleep 6; echo late > {home}/late.txt"
    run = run_session(
        tmp_path,
        Script(
            main=[
                tool("Bash", command=command, timeout=2000, description="x"),
                tool("Bash", command="sleep 8", description="x"),
                text("end"),
            ]
        ),
        switches=without,
    )
    told = run.told_after(1)
    assert told, "the session was told nothing after the command"
    time.sleep(max(0.0, 12.0 - (time.monotonic() - started)))
    found = {
        "ran on": (home / "late.txt").exists(),
        "told it runs on in the background": "background" in told.lower(),
    }
    assert "timed out" in told, told[:300]
    _held_to(AT_ITS_TIMEOUT_WITH_NO_LAYER_AND_NO_SWITCH, found)


def test_the_background_switch_is_one_of_the_later_pin_s_own_and_not_of_2_1_301_s() -> None:
    assert BACKGROUND_SWITCH not in session_switches("2.1.301")
    assert session_switches("2.1.322")[BACKGROUND_SWITCH] == "1"


@pytest.fixture
def temp_of() -> Iterator[Any]:
    """A private temporary directory whose path is exactly as long as asked, removed after."""
    made: list[Path] = []

    def make(length: int) -> Path:
        stem = f"{Path('/tmp').resolve()}/pg-"
        token = secrets.token_hex(32)[: length - len(stem)]
        path = Path(stem + token)
        assert len(str(path)) == length, (length, path)
        path.mkdir(mode=0o700)
        made.append(path)
        return path

    yield make
    for path in made:
        shutil.rmtree(path, ignore_errors=True)


#: Whether a sandboxed command's own temporary directory is the one the session was given,
#: by the length of that directory's path.
#: Measured: 33 characters are still taken and 34 are not, on both pins. The installer's
#: limit of 32 is inside what every pin takes.
TEMP_TAKEN: dict[tuple[str, str], dict[int, bool]] = {
    (platform, version): {32: True, 33: True, 34: False, 48: False}
    for platform in ("darwin", "linux")
    for version in ("2.1.301", "2.1.322")
}


def _temp_seen(root: Path, given: Path, installed_with: Path) -> str:
    """``$TMPDIR`` as a sandboxed command sees it when the session is given ``given``."""
    overridden: dict[str, str] = {}

    def spawn_with(installed: Any, _settings: dict[str, Any]) -> None:  # noqa: ANN401
        # The installer refuses a path past its limit, so the longer one is put into the
        # spawn's environment after it: what is measured is the binary, not the guard.
        if given != installed_with:
            installed.spawn_env["CLAUDE_CODE_TMPDIR"] = str(given)
        overridden.update(installed.spawn_env)

    run = _run_session(
        root,
        Script(
            main=[tool("Bash", command='echo "TMPDIR=[$TMPDIR]"', description="x"), text("end")]
        ),
        files=None,
        outside_files=None,
        prepare=None,
        registry=None,
        api_url_override=None,
        setting_sources=None,
        unpin_disable=False,
        check_installed=spawn_with,
        request_fields={"os_layer_temp_dir": str(installed_with)},
    )
    assert overridden.get("CLAUDE_CODE_TMPDIR") == str(given)
    told = run.told_after(1)
    assert "TMPDIR=[" in told, told[:300]
    return told.split("TMPDIR=[", 1)[1].split("]", 1)[0]


@pytest.mark.usefixtures("layer")
def test_the_longest_temporary_directory_a_sandboxed_command_is_given_is_the_limit_held(
    tmp_path: Path, temp_of: Any
) -> None:
    short = temp_of(OS_LAYER_TEMP_LIMIT - 4)
    taken: dict[int, bool] = {}
    for n, length in enumerate((OS_LAYER_TEMP_LIMIT, OS_LAYER_TEMP_LIMIT + 1, 34, 48)):
        given = temp_of(length)
        installed_with = given if length <= OS_LAYER_TEMP_LIMIT else short
        seen = _temp_seen(tmp_path / str(n), given, installed_with)
        taken[length] = Path(seen).resolve().is_relative_to(given.resolve()) if seen else False
    _held_to(TEMP_TAKEN, taken)
    # The guard's limit is the longest length every measured pin takes.
    assert taken[OS_LAYER_TEMP_LIMIT] is True


#: How the shell prefix is run for one shell command of a session with the full hook set:
#: how many times in front of the command itself, in front of how many hook commands, and
#: with how many arguments each time.
#: Measured: once in front of the command and once in front of each hook command, the two
#: at the session's end included, always with the whole command as its one argument.
PREFIX_RUNS: dict[tuple[str, str], dict[str, object]] = {
    (platform, version): {
        "in front of the command": 1,
        "in front of the hook commands of": [
            "PostToolUse",
            "PreToolUse",
            "SessionEnd",
            "SessionStart",
            "Stop",
        ],
        "arguments": ["1"],
    }
    for platform in ("darwin", "linux")
    for version in ("2.1.301", "2.1.322")
}

_FRONT = """\
#!/bin/sh
printf '%s\\t%s\\n' "$#" "$1" | tr '\\n' ' ' >> {log}
printf '\\n' >> {log}
exec /bin/sh -c "$1"
"""


def test_the_shell_prefix_fronts_the_command_and_every_hook_command_with_one_argument(
    tmp_path: Path,
) -> None:
    log = tmp_path / "prefix.log"
    front = tmp_path / "front"
    front.write_text(_FRONT.format(log=log))
    front.chmod(0o700)
    switches = {**session_switches(pinned_version()), "CLAUDE_CODE_SHELL_PREFIX": str(front)}
    run = run_session(
        tmp_path,
        Script(main=[tool("Bash", command="echo PREFIX-PROBE-91", description="x"), text("end")]),
        switches=switches,
    )
    assert "PREFIX-PROBE-91" in run.told_after(1)
    lines = [line.split("\t", 1) for line in log.read_text().splitlines() if "\t" in line]
    commands = [what for _, what in lines if "PREFIX-PROBE-91" in what]
    hooks = [what for _, what in lines if "PREFIX-PROBE-91" not in what]
    assert all("physgate.hooks " in what for what in hooks), hooks
    # Every hook command the stream shows starting was fronted (one more runs at the end).
    assert len(hooks) >= sum(run.hook_commands_started().values()) > 0
    found = {
        "in front of the command": len(commands),
        "in front of the hook commands of": sorted(
            what.split("physgate.hooks ", 1)[1].split(" ", 1)[0] for what in hooks
        ),
        "arguments": sorted({count for count, _ in lines}),
    }
    _held_to(PREFIX_RUNS, found)
    assert os.access(front, os.X_OK)
