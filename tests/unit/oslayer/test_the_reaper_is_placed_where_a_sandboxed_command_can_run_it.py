"""The survivor reaper reaches a session: written, named by the shell prefix, given its canary.

On macOS with the OS layer, the installer writes the reaper and its shell front into the
session's settings directory, opens that directory to the sandbox for reads, and names the
front in ``CLAUDE_CODE_SHELL_PREFIX`` with the shell pinned. Elsewhere nothing changes. The
held spawn exports its own pid, which the binary keeps, as the canary.
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

from physgate.hooks.registry import REGISTRY
from physgate.hooks.settings import InstallRequest, install
from physgate.orchestrator.dispatch import HELD
from physgate.oslayer import reaper, reaper_install
from physgate.oslayer.reaper import CANARY_ENV, SHELL


def _request(tmp_path: Path, temp: str | None, *, canary: bool = True) -> InstallRequest:
    worktree = tmp_path / "worktree"
    worktree.mkdir(parents=True, exist_ok=True)
    out = tmp_path / "outside"
    return InstallRequest(
        profile="role",
        role="electrical",
        worktree=str(worktree),
        own_branch="subtask/e-1",
        store_root=str(out / "store"),
        state_dir=str(out / "state"),
        target_dir=str(out / "session"),
        claude_config_dir=str(out / "config"),
        user_home=str(out / "home"),
        token_ceiling=1000,
        os_layer_temp_dir=temp,
        # As the run's ``sessions/`` is for a dispatched session: kept from its shell.
        extra_protected_refuse_only=(str(out),),
        spawns_with_canary=canary,
    )


def test_on_macos_with_the_layer_the_prefix_names_a_readable_reaper(
    outside_tmp: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(reaper_install, "wanted", lambda: True)
    done = install(_request(outside_tmp, "/tmp/pg-0123456789ab"), REGISTRY)
    front = Path(done.spawn_env["CLAUDE_CODE_SHELL_PREFIX"])
    assert front == outside_tmp / "outside" / "session" / "reaper" / "reaper"
    assert done.spawn_env["CLAUDE_CODE_SHELL"] == SHELL
    assert os.access(front, os.X_OK)
    program = front.with_name("reaper.py")
    assert program.read_bytes() == Path(reaper_install.__file__).with_name("reaper.py").read_bytes()
    text = front.read_text()
    assert f"'{program}'" in text and f"'{Path(sys.base_prefix) / 'bin' / 'python3'}'" in text
    # The sandbox reads the reaper's directory although the run's sessions are kept from it.
    settings = json.loads(done.settings_path.read_text())
    assert str(front.parent) in json.dumps(settings["sandbox"])
    # The front passes a command through only where it can read the session's settings,
    # which the sandbox denies every command.
    assert f"[ -r '{done.settings_path}' ]" in text
    config = json.loads(done.config_path.read_text())
    assert config["survivor_reaper"] is True
    sessions = [r for r in config["protected_roots"] if r["path"] == str(front.parent.parent)]
    assert [r["reads"] for r in sessions] == ["shell_denied"]


def test_a_spawner_that_does_not_export_the_canary_is_refused(
    outside_tmp: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(reaper_install, "wanted", lambda: True)
    with pytest.raises(ValueError, match="must be spawned with its canary exported"):
        install(_request(outside_tmp, "/tmp/pg-0123456789ab", canary=False), REGISTRY)


def test_without_the_layer_or_off_macos_nothing_is_named(
    outside_tmp: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    done = install(_request(outside_tmp / "a", None, canary=False), REGISTRY)
    assert "CLAUDE_CODE_SHELL_PREFIX" not in done.spawn_env
    assert json.loads(done.config_path.read_text())["survivor_reaper"] is False
    monkeypatch.setattr(reaper_install, "wanted", lambda: False)
    done = install(_request(outside_tmp / "b", "/tmp/pg-0123456789ab"), REGISTRY)
    assert "CLAUDE_CODE_SHELL_PREFIX" not in done.spawn_env
    assert not (outside_tmp / "b" / "outside" / "session" / "reaper").exists()


@pytest.mark.parametrize(
    ("platform", "present", "shell"),
    [
        ("darwin", set(), "/bin/zsh"),
        ("darwin", {"/bin/bash", "/bin/sh"}, "/bin/zsh"),
        ("linux", {"/bin/bash", "/bin/sh", "/bin/zsh"}, "/bin/bash"),
        ("linux", {"/usr/bin/bash", "/bin/sh"}, "/usr/bin/bash"),
        ("linux", {"/bin/sh"}, "/bin/sh"),
        ("linux", set(), "/bin/sh"),
    ],
    ids=[
        "macos",
        "macos-with-bash",
        "linux-with-bash-and-zsh",
        "linux-with-bash-elsewhere",
        "linux-without-bash",
        "linux-with-nothing-found",
    ],
)
def test_the_command_shell_is_zsh_on_macos_and_bash_or_sh_elsewhere(
    platform: str, present: set[str], shell: str
) -> None:
    """Never a shell the machine may not have: zsh is macOS's, and Linux hosts may lack it."""
    assert reaper.command_shell(platform, usable=present.__contains__) == shell


def test_this_machine_s_command_shell_is_there_and_runs_a_command() -> None:
    assert reaper.command_shell() == SHELL
    done = subprocess.run([SHELL, "-c", 'echo "$0"; exit 7'], capture_output=True, text=True)
    assert (done.returncode, done.stdout.strip()) == (7, SHELL)


@pytest.mark.parametrize(
    ("platform", "usable", "shell"),
    [
        ("darwin", "", "/bin/zsh"),
        ("linux", "/bin/sh", "/bin/sh"),
        ("linux", "/bin/bash", "/bin/bash"),
    ],
)
def test_the_reaper_s_own_copy_chooses_its_shell_where_it_runs(
    tmp_path: Path, platform: str, usable: str, shell: str
) -> None:
    """As a session runs it: a copy, alone, under the base interpreter, choosing on import."""
    copy = tmp_path / "reaper.py"
    copy.write_bytes(Path(reaper.__file__).read_bytes())
    script = (
        f"import os, sys; sys.platform = {platform!r}; "
        f"os.access = lambda path, mode: path == {usable!r}; "
        f"sys.path.insert(0, {str(tmp_path)!r}); import reaper; print(reaper.SHELL)"
    )
    done = subprocess.run(
        [sys.executable, "-I", "-S", "-c", script], capture_output=True, text=True, check=True
    )
    assert done.stdout.strip() == shell


def test_only_macos_is_wanted() -> None:
    assert reaper_install.wanted("darwin")
    assert not reaper_install.wanted("linux")


def test_a_prefix_claude_code_would_split_is_refused(tmp_path: Path) -> None:
    target = tmp_path / "a -b"
    target.mkdir()
    with pytest.raises(ValueError, match="would split"):
        reaper_install.place(target, sys.base_prefix, target / "settings.json")
    with pytest.raises(ValueError, match="no base interpreter"):
        reaper_install.place(tmp_path, str(tmp_path / "nowhere"), tmp_path / "settings.json")


def _front(tmp_path: Path) -> tuple[Path, Path]:
    settings = tmp_path / "settings.json"
    settings.write_text("{}")
    return reaper_install.place(
        tmp_path, sys.base_prefix, settings
    ) / reaper_install.FRONT, settings


def test_the_front_runs_a_hook_command_itself_when_the_canary_takes_its_signal(
    tmp_path: Path,
) -> None:
    # Unsandboxed, as a hook command is: signal 0 to the canary (this test's own process)
    # is delivered and the settings can be read, so the front runs the command with the
    # hook shell, no interpreter started.
    front, _ = _front(tmp_path)
    env = {"PATH": "/usr/bin:/bin", CANARY_ENV: str(os.getpid())}
    done = subprocess.run(
        [str(front), 'echo "$0"; exit 5'], env=env, capture_output=True, text=True, check=False
    )
    assert (done.returncode, done.stdout.strip()) == (5, reaper_install.HOOK_SHELL)


def test_the_front_hands_over_when_the_settings_cannot_be_read(tmp_path: Path) -> None:
    # As inside the sandbox, which read-denies them: even with the canary taking its
    # signal, the reaper runs the command (here unsandboxed, so it only runs it, in the
    # command shell), never the front's silent pass-through.
    front, settings = _front(tmp_path)
    settings.chmod(0)
    env = {"PATH": "/usr/bin:/bin", CANARY_ENV: str(os.getpid())}
    done = subprocess.run(
        [str(front), 'echo "$0"; exit 5'], env=env, capture_output=True, text=True, check=False
    )
    assert (done.returncode, done.stdout.strip()) == (5, SHELL)


def test_the_front_hands_over_without_a_canary(tmp_path: Path) -> None:
    front, _ = _front(tmp_path)
    done = subprocess.run(
        [str(front), 'echo "$0"; exit 6'],
        env={"PATH": "/usr/bin:/bin"},
        capture_output=True,
        text=True,
        check=False,
    )
    assert (done.returncode, done.stdout.strip(), done.stderr) == (6, SHELL, "")


def test_the_held_spawn_exports_the_pid_the_binary_keeps() -> None:
    script = 'echo "$' + CANARY_ENV + ' $$"'
    held = subprocess.Popen(  # noqa: S603 - the dispatcher's own held shell
        [*HELD, "/bin/sh", "-c", script],
        stdin=subprocess.PIPE,
        stdout=subprocess.PIPE,
        text=True,
    )
    out, _ = held.communicate("go\n", timeout=10)
    canary, pid = out.split()
    assert canary == pid == str(held.pid)


def test_a_spawner_s_helper_gives_the_same() -> None:
    script = 'echo "$' + CANARY_ENV + ' $$"'
    proc = subprocess.Popen(  # noqa: S603
        reaper_install.with_canary(["/bin/sh", "-c", script]), stdout=subprocess.PIPE, text=True
    )
    out, _ = proc.communicate(timeout=10)
    assert out.split() == [str(proc.pid)] * 2
