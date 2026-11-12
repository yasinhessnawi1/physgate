"""The run's tool environment is read and run by a session, and written by none.

Its roots reach the session's hooks as roots of their own kind: every file tool's write is
refused, every shell command that names one and is not a plain read is refused, and reads stay
open, because the session's commands run the interpreter and import the libraries there. The
tree is far too large to put back after a write, so nothing watches it: the hooks refuse before
the write, the OS layer denies it where it runs, and the dispatcher refuses the next session if
an entry changed all the same.

A write whose path only running the command decides is out of this layer's reach, as it is for
every root that is refused and never put back; it is a strict expected failure here, so the day
a text layer closes it the test says so.
"""

from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
from pathlib import Path

import pytest
from hook_helpers import bash, event

# A role session's settings without the OS layer are written only for a run whose recorded
# configuration allows that; the orchestrator's test helpers build one.
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "orchestrator"))
from orch_helpers import make_config  # noqa: E402

from physgate.hooks import paths, shell_paths  # noqa: E402
from physgate.hooks.config import HookInput, SessionConfig  # noqa: E402
from physgate.hooks.reasons import TOOL_ENVIRONMENT_REASON  # noqa: E402
from physgate.hooks.settings import InstallRequest, build_config, current_installation  # noqa: E402
from physgate.orchestrator.run_config import write_run_config  # noqa: E402
from physgate.oslayer.policy import sandbox_policy  # noqa: E402
from physgate.oslayer.session_temp import make_session_temp  # noqa: E402


@pytest.fixture
def environment(tmp_path: Path) -> Path:
    root = Path(os.path.realpath(tmp_path)) / "tools" / "env"
    (root / "bin").mkdir(parents=True)
    (root / "lib" / "control").mkdir(parents=True)
    (root / "bin" / "python3").write_text("#!/bin/sh\n")
    (root / "lib" / "control" / "margins.py").write_text("def margin(): return 1\n")
    return root


def _request(tmp_path: Path, roots: tuple[str, ...]) -> InstallRequest:
    worktree = Path(os.path.realpath(tmp_path)) / "run" / "wt"
    (worktree / "modules" / "control").mkdir(parents=True, exist_ok=True)
    return InstallRequest(
        profile="role",
        role="control",
        worktree=str(worktree),
        own_branch="b",
        store_root=None,
        state_dir=str(tmp_path / "state"),
        target_dir=str(tmp_path / "target"),
        claude_config_dir=str(tmp_path / "config"),
        user_home=str(tmp_path / "home"),
        token_ceiling=40960,
        tool_environment_roots=roots,
    )


@pytest.fixture
def config(tmp_path: Path, environment: Path) -> SessionConfig:
    return build_config(_request(tmp_path, (str(environment),)), current_installation())


def _tool(config: SessionConfig, tool: str, path: str) -> str:
    key = "notebook_path" if tool == "NotebookEdit" else "file_path"
    hook_input = HookInput.model_validate(
        event(
            tool_name=tool,
            cwd=config.worktree,
            tool_input={key: path, "content": "x", "old_string": "a", "new_string": "b"},
        )
    )
    decision = paths.pre_tool_use(hook_input, config)
    return "allow" if decision.allow else decision.reason


def _bash(config: SessionConfig, command: str) -> str:
    hook_input = HookInput.model_validate(bash(command, cwd=config.worktree))
    decision = shell_paths.pre_tool_use(hook_input, config)
    return "allow" if decision.allow else decision.reason


def test_each_root_is_refused_never_put_back_and_open_to_reads(
    config: SessionConfig, environment: Path
) -> None:
    roots = {r.path: r for r in config.protected_roots}
    assert str(environment) in roots, sorted(roots)
    root = roots[str(environment)]
    assert root.watch == "none"
    assert root.reads == "open"
    assert root.shell_writes == "denied"
    assert root.reason == TOOL_ENVIRONMENT_REASON


def test_a_session_given_no_environment_has_no_such_root(tmp_path: Path, environment: Path) -> None:
    without = build_config(_request(tmp_path, ()), current_installation())
    assert str(environment) not in {r.path for r in without.protected_roots}
    assert TOOL_ENVIRONMENT_REASON not in {r.reason for r in without.protected_roots}


@pytest.mark.parametrize("tool", ["Write", "Edit", "NotebookEdit"])
@pytest.mark.parametrize(
    "path",
    [
        "{e}/lib/control/margins.py",
        "{e}/lib/control/new.py",
        "{e}",
        "{e}/bin/../lib/control/margins.py",
        "{e}/./bin//python3",
    ],
)
def test_no_file_tool_writes_into_it(
    config: SessionConfig, environment: Path, tool: str, path: str
) -> None:
    assert TOOL_ENVIRONMENT_REASON in _tool(config, tool, path.format(e=environment))


def test_a_file_tool_reads_it_and_writes_the_module(
    config: SessionConfig, environment: Path
) -> None:
    assert _tool(config, "Read", str(environment / "lib" / "control" / "margins.py")) == "allow"
    assert _tool(config, "Write", os.path.join(config.worktree, "modules/control/x.py")) == "allow"


REFUSED = [
    "echo x > {e}/lib/control/margins.py",
    "echo x >> {e}/lib/control/margins.py",
    "cp modules/control/x.py {e}/lib/control/margins.py",
    "mv modules/control/x.py {e}/lib/control/",
    "rm {e}/lib/control/margins.py",
    "rm -rf {e}",
    "sed -i -e s/1/2/ {e}/lib/control/margins.py",
    "tee {e}/lib/control/margins.py < modules/control/x.py",
    "ln -sf /etc/hosts {e}/bin/python3",
    "chmod 777 {e}/bin/python3",
    "touch {e}/lib/control/margins.py",
    "python3 -c \"open('{e}/lib/control/margins.py', 'w').write('x')\"",
    "dd if=/dev/zero of={e}/bin/python3 count=1",
    "cd {e}/lib && echo x > control/margins.py",
    "echo x > {e}/bin/../lib/control/margins.py",
    "pip install --target {e}/lib control",
]


@pytest.mark.parametrize("command", REFUSED)
def test_a_command_that_names_it_and_is_not_a_plain_read_is_refused(
    config: SessionConfig, environment: Path, command: str
) -> None:
    said = _bash(config, command.format(e=environment))
    assert said != "allow" and str(environment) in said, said


ALLOWED = [
    "cat {e}/lib/control/margins.py",
    "ls -la {e}/bin",
    "grep -rn margin {e}/lib",
    "python3 modules/control/margins.py",
    "pio run",
]


@pytest.mark.parametrize("command", ALLOWED)
def test_a_plain_read_of_it_and_a_tool_run_by_name_are_allowed(
    config: SessionConfig, environment: Path, command: str
) -> None:
    assert _bash(config, command.format(e=environment)) == "allow"


@pytest.mark.xfail(strict=True, reason="a path built at run time is no text layer's to see")
def test_a_path_only_running_the_command_decides_is_out_of_this_layer_s_reach(
    config: SessionConfig, environment: Path
) -> None:
    built = f"python3 - <<'EOF'\nimport os\nopen(os.sep.join({str(environment).split(os.sep)!r}"
    built += " + ['lib', 'control', 'margins.py']), 'w').write('x')\nEOF"
    assert _bash(config, built) != "allow"


def test_the_os_layer_denies_every_write_into_it_and_no_read(
    tmp_path: Path, config: SessionConfig, environment: Path
) -> None:
    home, temp = tmp_path / "home", tmp_path / "temp"
    home.mkdir(exist_ok=True)
    temp.mkdir()
    fs = sandbox_policy(config, home=str(home), temp_dir=str(temp)).settings["sandbox"][
        "filesystem"
    ]
    assert str(environment) in fs["denyWrite"]
    assert not [path for path in fs["denyRead"] if path.startswith(str(environment))]
    assert not [path for path in fs["allowWrite"] if path.startswith(str(environment))]


def test_the_installer_s_command_takes_each_root_and_writes_it_into_the_session_s_configuration(
    tmp_path: Path, environment: Path
) -> None:
    (tmp_path / "worktree").mkdir()
    store = environment.parent / "store"
    store.mkdir()
    run_config = tmp_path / "run.json"
    write_run_config(run_config, make_config(os_layer_absent="allow"))
    temp = make_session_temp()
    try:
        proc = subprocess.run(
            [
                "uv",
                "run",
                "--no-sync",
                "physgate",
                "hooks",
                "install",
                "--profile=role",
                "--role=control",
                f"--worktree={tmp_path / 'worktree'}",
                f"--state-dir={tmp_path / 'state'}",
                f"--target={tmp_path / 'session'}",
                f"--claude-config-dir={tmp_path / 'cfg'}",
                f"--user-home={tmp_path / 'home'}",
                "--ceiling=8000",
                f"--sessions-root={tmp_path / 'sessions'}",
                f"--temp={temp}",
                f"--run-config={run_config}",
                f"--tool-environment-root={environment}",
                f"--tool-environment-root={store}",
            ],
            capture_output=True,
            text=True,
            check=False,
        )
    finally:
        shutil.rmtree(temp, ignore_errors=True)
    assert proc.returncode == 0, proc.stderr
    written = json.loads(Path(json.loads(proc.stdout)["config"]).read_text())
    held = {
        r["path"]: r
        for r in written["protected_roots"]
        if r["path"].startswith(str(environment.parent))
    }
    assert sorted(held) == [str(environment), str(store)]
    for root in held.values():
        assert (root["watch"], root["reads"]) == ("none", "open")
        assert root["reason"] == TOOL_ENVIRONMENT_REASON
