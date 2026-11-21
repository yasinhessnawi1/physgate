"""What later versions changed around a shell command is measured on each pin, not assumed.

Versions after 2.1.301 changed four things around a role session's shell commands, and each
is measured here through the real binary on every pin, inside the OS layer where the layer
is what is on trial:

- **A background call.** The installer switches background tasks off for every session, so
  the binary refuses a command asked to run in the background itself, before any hook. With
  that switch taken out of a session's environment, for the measurement only, the shell
  hook refuses the call; and with the hooks that read a command's words taken out as well,
  what such a call can reach is the OS layer's alone to stop.
- **A command at its timeout.** A later version's notes say such a command is kept "running
  in the background". The controls run each pin with the switch taken out, inside the OS
  layer and with no layer at all, and say whether the command then goes on to write, and
  where.
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
from hook_session import pinned_version, run_session, session_switches
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


def _held_to(table: dict[Any, Any], found: Any, *more: str) -> None:  # noqa: ANN401
    key = (*_here(), *more)
    measured = table.get(key)
    assert measured is not None, f"not measured on {key} yet; found {found}"
    assert found == measured, key


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

SWITCHED_OFF, SWITCH_TAKEN_OUT = "background tasks switched off", "the switch taken out"
_BOTH = [(p, v) for p in ("darwin", "linux") for v in ("2.1.301", "2.1.322")]

#: Who refuses a background call under the full hook set: the binary's own input check where
#: background tasks are switched off, as the installer has them for every session, and the
#: shell hook where the binary still offers the parameter.
BACKGROUND_REFUSED_BY: dict[tuple[str, str, str], str] = {
    **{(*here, SWITCHED_OFF): "the binary's input check" for here in _BOTH},
    **{(*here, SWITCH_TAKEN_OUT): "the shell hook" for here in _BOTH},
}
#: What a background call reaches with the hooks that read a command's words taken out. As
#: installed it never runs. With the switch taken out too it runs, in the background and
#: inside the sandbox: it writes in the session's home and nowhere else, and reads nothing
#: read-denied.
BACKGROUND_REACHES: dict[tuple[str, str, str], dict[str, bool]] = {
    **{(*here, SWITCHED_OFF): NOTHING for here in _BOTH},
    **{(*here, SWITCH_TAKEN_OUT): INSIDE_ONLY for here in _BOTH},
}


def _spawned(arrangement: str) -> dict[str, Any]:
    """How a session is spawned for ``arrangement``: as installed, or with the switch taken out.

    The switch comes from the installer and, on a later pin, from the pin's own switches
    too; taking it out is a measurement's doing, and nothing a session reaches does it.
    """
    if arrangement == SWITCHED_OFF:
        return {}

    def take_it_out(installed: Any, _settings: dict[str, Any]) -> None:  # noqa: ANN401
        assert installed.spawn_env.pop(BACKGROUND_SWITCH) == "1"

    own = session_switches(pinned_version())
    without = {name: value for name, value in own.items() if name != BACKGROUND_SWITCH}
    return {"check_installed": take_it_out, "switches": without}


def _shown(run: Any) -> str:  # noqa: ANN401 - the rig's run
    """Whether the session's own shell had the switch, read back from the spawn."""
    return SWITCHED_OFF if BACKGROUND_SWITCH in run.installed.spawn_env else SWITCH_TAKEN_OUT


def _who_refused(told: str) -> str:
    if "InputValidationError" in told:
        return "the binary's input check"
    if "hook" in told.lower() and "background" in told.lower():
        return "the shell hook"
    return f"no one: {told[:200]!r}"


@pytest.mark.usefixtures("layer")
@pytest.mark.parametrize("arrangement", [SWITCHED_OFF, SWITCH_TAKEN_OUT])
def test_a_background_call_under_the_full_hook_set_is_refused_and_runs_nothing(
    tmp_path: Path, arrangement: str
) -> None:
    home, held, escaped = _stand_ins(tmp_path)
    command = f"sleep 1; echo bg > {home}/bg.txt; echo bg > {escaped}/bg.txt"
    call = tool("Bash", command=command, run_in_background=True, description="x")
    run = run_session(
        tmp_path, Script(main=[call, text("end")]), os_layer=True, **_spawned(arrangement)
    )
    time.sleep(4)
    assert _shown(run) == arrangement
    assert not (home / "bg.txt").exists() and not (escaped / "bg.txt").exists()
    _held_to(BACKGROUND_REFUSED_BY, _who_refused(run.told_after(1)), arrangement)


def test_the_installer_switches_background_tasks_off_for_every_session(tmp_path: Path) -> None:
    run = run_session(tmp_path, Script(main=[text("end")]))
    assert run.installed.spawn_env.get(BACKGROUND_SWITCH) == "1"


@pytest.mark.usefixtures("layer")
@pytest.mark.parametrize("arrangement", [SWITCHED_OFF, SWITCH_TAKEN_OUT])
def test_what_a_background_call_reaches_with_the_os_layer_alone(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, arrangement: str
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
        **_spawned(arrangement),
    )
    time.sleep(3)
    assert _shown(run) == arrangement
    _held_to(BACKGROUND_REACHES, _reached(home, escaped, "bg", run), arrangement)


#: What a command still at work at its timeout goes on to do when background tasks are not
#: switched off, with the hooks that read a command's words taken out.
#: Measured: on neither pin does the command go on. Each ends it at its timeout (the session
#: is told ``Command timed out``), with the switch or without, so the later version's
#: "still running in the background" was not produced in a session run as the harness runs
#: one. The switch stays set for every session all the same.
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
        **_spawned(SWITCH_TAKEN_OUT),
    )
    assert _shown(run) == SWITCH_TAKEN_OUT
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
        **_spawned(SWITCH_TAKEN_OUT),
    )
    assert _shown(run) == SWITCH_TAKEN_OUT
    told = run.told_after(1)
    assert told, "the session was told nothing after the command"
    time.sleep(max(0.0, 12.0 - (time.monotonic() - started)))
    found = {
        "ran on": (home / "late.txt").exists(),
        "told it runs on in the background": "background" in told.lower(),
    }
    assert "timed out" in told, told[:300]
    _held_to(AT_ITS_TIMEOUT_WITH_NO_LAYER_AND_NO_SWITCH, found)


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
#: Measured, alike on both pins: 32 characters are taken everywhere and 34 nowhere. One more
#: than 32 is still taken on macOS and is not on Linux, so the installer's limit of 32 is
#: the longest path every pin takes on every platform. (The installer takes only the
#: directory it is given beneath the sessions' one parent, so each path measured here is put
#: into the spawn's environment after the install.)
TEMP_TAKEN: dict[tuple[str, str], dict[int, bool]] = {
    (platform, version): {32: True, 33: platform == "darwin", 34: False, 48: False}
    for platform in ("darwin", "linux")
    for version in ("2.1.301", "2.1.322")
}


def _temp_seen(root: Path, given: Path | None) -> tuple[str, str]:
    """The session's own temporary directory, and ``$TMPDIR`` as a sandboxed command sees it.

    The session is installed as the dispatcher installs one, with a directory of its own.
    With ``given``, that path is put into the spawn's environment after the install, for
    the measurement only: the installer takes no other directory, and what is measured is
    the binary.
    """
    spawned: dict[str, str] = {}

    def spawn_with(installed: Any, _settings: dict[str, Any]) -> None:  # noqa: ANN401
        spawned["own"] = installed.spawn_env["CLAUDE_CODE_TMPDIR"]
        if given is not None:
            installed.spawn_env["CLAUDE_CODE_TMPDIR"] = str(given)

    run = run_session(
        root,
        Script(
            main=[tool("Bash", command='echo "TMPDIR=[$TMPDIR]"', description="x"), text("end")]
        ),
        os_layer=True,
        check_installed=spawn_with,
    )
    told = run.told_after(1)
    assert "TMPDIR=[" in told, told[:300]
    return spawned["own"], told.split("TMPDIR=[", 1)[1].split("]", 1)[0]


def _within(seen: str, directory: str | Path) -> bool:
    return bool(seen) and Path(seen).resolve().is_relative_to(Path(directory).resolve())


@pytest.mark.usefixtures("layer")
def test_the_directory_a_session_is_given_is_within_the_limit_and_is_its_commands_own(
    tmp_path: Path,
) -> None:
    own, seen = _temp_seen(tmp_path, None)
    assert len(own) <= OS_LAYER_TEMP_LIMIT, own
    assert _within(seen, own), (own, seen)


@pytest.mark.usefixtures("layer")
def test_the_longest_temporary_directory_a_sandboxed_command_is_given_is_the_limit_held(
    tmp_path: Path, temp_of: Any
) -> None:
    taken: dict[int, bool] = {}
    for n, length in enumerate((OS_LAYER_TEMP_LIMIT, OS_LAYER_TEMP_LIMIT + 1, 34, 48)):
        given = temp_of(length)
        _, seen = _temp_seen(tmp_path / str(n), given)
        taken[length] = _within(seen, given)
    _held_to(TEMP_TAKEN, taken)
    # The installer's limit is a length every measured pin takes.
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
