"""Run one real Claude Code session under generated hooks, against the scripted API.

The session is started exactly as the settings generator says a role session
must be: no settings sources at all, the generated file by flag, and a scratch
Claude configuration directory. It also gets a scratch home and an environment
built from nothing, so nothing on the machine running the tests — no user
settings, no plugin, no credential — takes part.

Three things are checked on every run, not left to the test that uses it:

- the binary is the pinned version, because the hook contract this layer relies
  on was measured on that version and a different one proves nothing about it;
- the scripted API was actually used, and no request carried any credential
  other than the dummy key, so a silent fallback to the real API cannot happen
  (and with no credential present it would fail loudly anyway);
- each event ran exactly one hook command, the generated one, so no hook from
  anywhere else fired.
"""

from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
from collections import Counter
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from fake_messages_api import DUMMY_KEY, FakeMessagesApi, Script, serving

from physgate.hooks.registry import REGISTRY
from physgate.hooks.runtime import HookSpec
from physgate.hooks.settings import Installed, InstallRequest, install

#: The Claude Code version the hook contract was measured on.
PINNED_VERSION = "2.1.272"


class HarnessError(AssertionError):
    """The harness could not produce a run whose result means anything."""


def claude_binary() -> str:
    """The Claude Code binary to run, refusing any version but the pinned one."""
    binary = os.environ.get("PHYSGATE_CLAUDE_BIN") or shutil.which("claude")
    if not binary:
        msg = "no Claude Code binary found (set PHYSGATE_CLAUDE_BIN)"
        raise HarnessError(msg)
    out = subprocess.run(
        [binary, "--version"], capture_output=True, text=True, check=False, timeout=60
    ).stdout
    if out.split(" ", 1)[0].strip() != PINNED_VERSION:
        msg = (
            f"{binary} reports {out.strip()!r}; the hook contract was measured on {PINNED_VERSION}"
        )
        raise HarnessError(msg)
    return binary


@dataclass
class SessionRun:
    """Everything one session left behind."""

    exit_code: int
    api: FakeMessagesApi
    stream: list[dict[str, Any]]
    hook_log: list[dict[str, Any]]
    installed: Installed
    worktree: Path
    stderr: str

    def told_after(self, results: int) -> str:
        """What the agent was told back after its ``results``-th tool call."""
        for request in self.api.requests:
            if request.thread == "main" and request.tool_results == results:
                return request.last_user
        return ""

    def hook_commands_started(self) -> Counter[str]:
        """How many hook commands started, per event and tool."""
        return Counter(
            e.get("hook_name", "")
            for e in self.stream
            if e.get("type") == "system" and e.get("subtype") == "hook_started"
        )


def make_worktree(root: Path, files: dict[str, str] | None = None) -> Path:
    """A git repository standing in for a role session's worktree."""
    worktree = root / "worktree"
    worktree.mkdir(parents=True)
    for rel, content in (files or {"README.md": "a worktree\n"}).items():
        path = worktree / rel
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(content)
    env = {
        "PATH": "/usr/bin:/bin",
        "HOME": str(root),
        "GIT_AUTHOR_NAME": "t",
        "GIT_AUTHOR_EMAIL": "t@example.invalid",
        "GIT_COMMITTER_NAME": "t",
        "GIT_COMMITTER_EMAIL": "t@example.invalid",
    }
    for argv in (
        ["git", "init", "-q", "-b", "subtask/electrical-1"],
        ["git", "add", "-A"],
        ["git", "commit", "-q", "-m", "fixture"],
    ):
        subprocess.run(argv, cwd=worktree, env=env, check=True)
    return worktree


def run_session(
    root: Path,
    script: Script,
    *,
    files: dict[str, str] | None = None,
    outside_files: dict[str, str] | None = None,
    prepare: Callable[[Path], None] | None = None,
    registry: Mapping[str, HookSpec] | None = None,
    api_url_override: str | None = None,
    setting_sources: str | None = None,
    **request_fields: Any,  # noqa: ANN401 - forwarded to the install request
) -> SessionRun:
    """Install hooks for a fresh worktree under ``root`` and run one scripted session."""
    binary = claude_binary()
    worktree = make_worktree(root, files)
    outside = root / "outside"
    for rel, content in (outside_files or {}).items():
        path = outside / rel
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(content)
    if prepare is not None:
        prepare(worktree)
    fields: dict[str, Any] = {
        "profile": "role",
        "role": "electrical",
        "worktree": str(worktree),
        "own_branch": "subtask/electrical-1",
        "store_root": str(outside / "store"),
        "state_dir": str(outside / "state"),
        "target_dir": str(outside / "session"),
        "claude_config_dir": str(outside / "claude-config"),
        "user_home": str(outside / "home"),
        "token_ceiling": 100_000,
    }
    fields.update(request_fields)
    # A test may wire a reduced set of hooks, to show one layer working alone.
    # This is a parameter of the generator, reachable only by whoever writes the
    # settings file; nothing inside a session can change which hooks it runs.
    installed = install(InstallRequest(**fields), registry or REGISTRY)
    home = Path(fields["user_home"])
    home.mkdir(parents=True, exist_ok=True)
    with serving(script) as (api, base_url):
        env = {
            "HOME": str(home),
            # The system's own directories first, so where the machine has a
            # python3 of its own the session uses it; then the test interpreter's,
            # so a machine without one (the server) still runs the attempts that
            # write through a script, instead of reporting them as never run.
            "PATH": f"/usr/bin:/bin:/usr/sbin:/sbin:{os.path.dirname(sys.executable)}",
            "TERM": "dumb",
            "ANTHROPIC_BASE_URL": api_url_override or base_url,
            "ANTHROPIC_API_KEY": DUMMY_KEY,
            "CLAUDE_CODE_DISABLE_NONESSENTIAL_TRAFFIC": "1",
            "DISABLE_AUTOUPDATER": "1",
            "DISABLE_TELEMETRY": "1",
            "DISABLE_ERROR_REPORTING": "1",
            # A session that cannot reach the scripted API fails at once instead
            # of retrying with backoff for minutes.
            "CLAUDE_CODE_MAX_RETRIES": "0",
            **installed.spawn_env,
        }
        proc = subprocess.run(
            [
                binary,
                "-p",
                "go",
                *_spawn_args(installed, setting_sources),
                "--output-format",
                "stream-json",
                "--verbose",
                "--include-hook-events",
                "--model",
                "claude-sonnet-4-5",
                "--permission-mode",
                "bypassPermissions",
            ],
            cwd=worktree,
            env=env,
            capture_output=True,
            text=True,
            check=False,
            timeout=300,
        )
    stream = [json.loads(line) for line in proc.stdout.splitlines() if line.startswith("{")]
    log_path = Path(fields["state_dir"]) / "hooks.log.jsonl"
    hook_log = (
        [json.loads(line) for line in log_path.read_text().splitlines()]
        if log_path.exists()
        else []
    )
    run = SessionRun(proc.returncode, api, stream, hook_log, installed, worktree, proc.stderr)
    check_the_run_means_something(run)
    return run


def _spawn_args(installed: Installed, setting_sources: str | None) -> tuple[str, ...]:
    """The generated spawn arguments, or, for a control only, with other setting sources.

    A test that shows what the pinned arguments are worth has to run the same
    session without them; nothing else changes them.
    """
    args = installed.spawn_args
    if setting_sources is None:
        return args
    assert args[0] == "--setting-sources", args
    return (args[0], setting_sources, *args[2:])


def check_the_run_means_something(run: SessionRun) -> None:
    """Raise unless the run used the scripted API, no other credential, and only our hooks."""
    scripted = [r for r in run.api.requests if r.served is not None]
    if not scripted:
        msg = f"the scripted API served nothing; the session did not use it:\n{run.stderr[-2000:]}"
        raise HarnessError(msg)
    if any(r.carried_other_credential or not r.carried_dummy_key for r in run.api.requests):
        msg = "a request carried a credential other than the dummy key"
        raise HarnessError(msg)
    per_event = run.hook_commands_started()
    if not per_event:
        msg = "no hook command started at all; the generated settings were not loaded"
        raise HarnessError(msg)
    extra = {name: n for name, n in per_event.items() if n > _expected_starts(run, name)}
    if extra:
        msg = f"more hook commands started than the generated ones: {extra}"
        raise HarnessError(msg)


def _expected_starts(run: SessionRun, name: str) -> int:
    """One generated command per event, once per tool call for tool events."""
    event, _, tool_name = name.partition(":")
    if event in {"PreToolUse", "PostToolUse", "PostToolUseFailure"}:
        return sum(
            1
            for r in run.api.requests
            if r.thread == "main" and r.served and r.served.get("tool") == tool_name
        ) + sum(
            1
            for r in run.api.requests
            if r.thread == "sub" and r.served and r.served.get("tool") == tool_name
        )
    return 1


def volume_is_case_insensitive(directory: Path) -> bool:
    """True if ``directory`` is on a volume where a case variant names the same file.

    The case-variant attempts depend on the volume, not on the operating system:
    macOS can mount a case-sensitive volume, and CI ran one on Linux. So the
    condition is probed where the test actually runs.
    """
    probe = directory / "Case-Probe"
    probe.parent.mkdir(parents=True, exist_ok=True)
    probe.write_text("")
    try:
        return (directory / "case-probe").exists()
    finally:
        probe.unlink()
