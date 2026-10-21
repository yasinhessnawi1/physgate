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
from physgate.oslayer import reaper_install
from physgate.oslayer.reaper import CANARY_ENV


def _request(tmp_path: Path, temp: str | None) -> InstallRequest:
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
    )


def test_on_macos_with_the_layer_the_prefix_names_a_readable_reaper(
    outside_tmp: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(reaper_install, "wanted", lambda: True)
    done = install(_request(outside_tmp, "/tmp/pg-0123456789ab"), REGISTRY)
    front = Path(done.spawn_env["CLAUDE_CODE_SHELL_PREFIX"])
    assert front == outside_tmp / "outside" / "session" / "reaper" / "reaper"
    assert done.spawn_env["CLAUDE_CODE_SHELL"] == "/bin/zsh"
    assert os.access(front, os.X_OK)
    program = front.with_name("reaper.py")
    assert program.read_bytes() == Path(reaper_install.__file__).with_name("reaper.py").read_bytes()
    text = front.read_text()
    assert f"'{program}'" in text and f"'{Path(sys.base_prefix) / 'bin' / 'python3'}'" in text
    # The sandbox reads the reaper's directory although the run's sessions are kept from it.
    settings = json.loads(done.settings_path.read_text())
    assert str(front.parent) in json.dumps(settings["sandbox"])


def test_without_the_layer_or_off_macos_nothing_is_named(
    outside_tmp: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    done = install(_request(outside_tmp / "a", None), REGISTRY)
    assert "CLAUDE_CODE_SHELL_PREFIX" not in done.spawn_env
    monkeypatch.setattr(reaper_install, "wanted", lambda: False)
    done = install(_request(outside_tmp / "b", "/tmp/pg-0123456789ab"), REGISTRY)
    assert "CLAUDE_CODE_SHELL_PREFIX" not in done.spawn_env
    assert not (outside_tmp / "b" / "outside" / "session" / "reaper").exists()


def test_only_macos_is_wanted() -> None:
    assert reaper_install.wanted("darwin")
    assert not reaper_install.wanted("linux")


def test_a_prefix_claude_code_would_split_is_refused(tmp_path: Path) -> None:
    target = tmp_path / "a -b"
    target.mkdir()
    with pytest.raises(ValueError, match="would split"):
        reaper_install.place(target, sys.base_prefix)
    with pytest.raises(ValueError, match="no base interpreter"):
        reaper_install.place(tmp_path, str(tmp_path / "nowhere"))


def test_the_front_runs_a_hook_command_itself_when_the_canary_takes_its_signal(
    tmp_path: Path,
) -> None:
    # Unsandboxed, as a hook command is: signal 0 to the canary (this test's own process)
    # is delivered, so the front runs the command with the hook shell, no interpreter started.
    front = reaper_install.place(tmp_path, sys.base_prefix) / reaper_install.FRONT
    env = {"PATH": "/usr/bin:/bin", CANARY_ENV: str(os.getpid())}
    done = subprocess.run(
        [str(front), 'echo "$0"; exit 5'], env=env, capture_output=True, text=True, check=False
    )
    assert (done.returncode, done.stdout.strip()) == (5, reaper_install.HOOK_SHELL)
    # Without a canary the reaper runs and, unsandboxed, only runs the command too.
    done = subprocess.run(
        [str(front), "exit 6"], env={"PATH": "/usr/bin:/bin"}, capture_output=True, check=False
    )
    assert (done.returncode, done.stderr) == (6, b"")


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
