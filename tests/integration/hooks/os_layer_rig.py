"""A role session installed as the dispatcher installs one, with or without the OS layer.

Shared by the tests that run real sessions under the OS layer: a run repository with a
linked worktree (as a role session's is), the session's own directories, an inert
held-out stand-in and a refuse-only decisions file, and the session run against the
scripted endpoint with the generated settings, arguments and environment.
"""

from __future__ import annotations

import json
import os
import secrets
import shutil
import subprocess
import sys
import time
from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import dataclass
from pathlib import Path
from typing import Literal

from fake_messages_api import DUMMY_KEY, Script, serving, text
from hook_session import claude_binary

from physgate.hooks.registry import REGISTRY
from physgate.hooks.settings import InstallRequest, install
from physgate.oslayer.abort import ABORT_PREFIX
from physgate.oslayer.probe import Present, gather_facts, judge
from physgate.oslayer.reaper_install import with_canary

MARKER = "STANDIN-HELDOUT-MARKER"
SEARCH_PATH = "/usr/bin:/bin:/usr/sbin:/sbin"


def layer_here() -> bool:
    """Whether the OS layer runs on this machine, for the pinned binary the tests are given."""
    binary = claude_binary()
    version = subprocess.run(
        [binary, "--version"], capture_output=True, text=True, check=False
    ).stdout.split(" ", 1)[0]
    path = f"{Path(binary).parent}:{SEARCH_PATH}"
    return isinstance(judge(gather_facts(claude_version=version, search_path=path)), Present)


@dataclass
class Layout:
    root: Path
    worktree: Path
    common: Path
    sdir: Path
    held: Path
    decisions: Path
    outside: Path
    temp: Path


@contextmanager
def make_layout(tmp_path: Path) -> Iterator[Layout]:
    """A run repository with a linked worktree, a session's directories and stand-ins."""
    env = {
        "PATH": "/usr/bin:/bin",
        "HOME": str(tmp_path),
        "GIT_AUTHOR_NAME": "t",
        "GIT_AUTHOR_EMAIL": "t@example.invalid",
        "GIT_COMMITTER_NAME": "t",
        "GIT_COMMITTER_EMAIL": "t@example.invalid",
    }
    run = tmp_path / "run"
    repo = run / "repo"
    repo.mkdir(parents=True)
    (repo / "README.md").write_text("a run repository\n")
    for argv in (["git", "init", "-q", "-b", "main"], ["git", "add", "-A"]):
        subprocess.run(argv, cwd=repo, env=env, check=True)
    subprocess.run(["git", "commit", "-q", "-m", "fixture"], cwd=repo, env=env, check=True)
    worktree = run / "worktrees" / "sub1"
    subprocess.run(
        ["git", "worktree", "add", "-q", "-b", "subtask/sub1", str(worktree)],
        cwd=repo,
        env=env,
        check=True,
    )
    sdir = run / "sessions" / "s1"
    for name in ("state", "session", "config", "home"):
        (sdir / name).mkdir(parents=True)
    held = tmp_path / "outside" / "heldout"
    held.mkdir(parents=True)
    (held / "stand.txt").write_text(MARKER + "\n")
    decisions = run / "queue_decisions.jsonl"
    decisions.write_text("")
    temp = Path("/tmp") / f"pg-{secrets.token_hex(6)}"
    temp.mkdir(mode=0o700)
    try:
        yield Layout(
            tmp_path,
            worktree,
            repo / ".git",
            sdir,
            held,
            decisions,
            tmp_path / "outside",
            temp,
        )
    finally:
        shutil.rmtree(temp, ignore_errors=True)


def python(program: str) -> str:
    """A command the first layer allows: a program on stdin builds its path at run time."""
    return f"python3 - <<'EOF'\n{program}\nEOF"


def run_session(
    layout: Layout,
    steps: list[dict[str, object]],
    *,
    layer: bool,
    timeout: float = 300,
    aborts_fail: bool = True,
    network: Literal["open", "none"] = "open",
    reaper: bool = True,
) -> dict[str, object]:
    """Install a role session for ``layout``, with or without the OS layer, and run it.

    A step whose result carries bubblewrap's own words (``bwrap:``) never ran: the
    sandbox failed before the command started. It fails the test, because a refusal
    test would otherwise pass on a command no layer judged. ``aborts_fail`` off leaves
    that to the caller, which is shown the aborted steps under ``aborted``.

    The session is spawned as the dispatcher spawns one, its pid exported as the survivor
    reaper's canary. ``reaper`` off leaves the reaper out of the session's environment: the
    red control of the test that it stops what a command left running.
    """
    request = InstallRequest(
        profile="role",
        role="electrical",
        worktree=str(layout.worktree),
        own_branch="subtask/sub1",
        store_root=str(layout.root / "run" / "store"),
        state_dir=str(layout.sdir / "state"),
        target_dir=str(layout.sdir / "session"),
        claude_config_dir=str(layout.sdir / "config"),
        user_home=str(layout.sdir / "home"),
        token_ceiling=100_000,
        held_out=(str(layout.held),),
        extra_protected=(str(layout.common),),
        extra_protected_refuse_only=(str(layout.root / "run" / "sessions"), str(layout.decisions)),
        os_layer_temp_dir=str(layout.temp.resolve()) if layer else None,
        os_layer_network=network,
        spawns_with_canary=True,
    )
    installed = install(request, REGISTRY)
    binary = claude_binary()
    with serving(Script(main=[*steps, text("end")])) as (api, url):
        env = {
            "HOME": str(layout.sdir / "home"),
            "PATH": f"{Path(binary).parent}:{SEARCH_PATH}:{os.path.dirname(sys.executable)}",
            "TERM": "dumb",
            "ANTHROPIC_BASE_URL": url,
            "ANTHROPIC_API_KEY": DUMMY_KEY,
            "CLAUDE_CODE_DISABLE_NONESSENTIAL_TRAFFIC": "1",
            "DISABLE_AUTOUPDATER": "1",
            "DISABLE_TELEMETRY": "1",
            "DISABLE_ERROR_REPORTING": "1",
            "CLAUDE_CODE_MAX_RETRIES": "0",
            **installed.spawn_env,
        }
        if not reaper:
            env.pop("CLAUDE_CODE_SHELL_PREFIX", None)
        started = time.monotonic()
        done = subprocess.run(
            with_canary(
                [
                    binary,
                    "-p",
                    "go",
                    *installed.spawn_args,
                    "--output-format",
                    "stream-json",
                    "--verbose",
                    "--model",
                    "claude-sonnet-4-5",
                    "--permission-mode",
                    "bypassPermissions",
                ]
            ),
            cwd=layout.worktree,
            env=env,
            capture_output=True,
            text=True,
            check=False,
            timeout=timeout,
        )
    told = {r.tool_results: r.last_user for r in api.requests if r.thread == "main"}
    stream = [json.loads(line) for line in done.stdout.splitlines() if line.startswith("{")]
    result = next((e for e in reversed(stream) if e.get("type") == "result"), None)
    said = [told.get(n, "") for n in range(1, len(steps) + 1)]
    aborted = [n for n, text in enumerate(said) if ABORT_PREFIX in text]
    if aborted and aborts_fail:
        shown = "; ".join(f"step {n}: {said[n][:200]!r}" for n in aborted)
        msg = f"bubblewrap aborted {len(aborted)} step(s) before they ran: {shown}"
        raise AssertionError(msg)
    return {
        "told": said,
        "aborted": aborted,
        "result": result,
        "exit": done.returncode,
        "settings": json.loads(installed.settings_path.read_text()),
        "stderr": done.stderr,
        "seconds": time.monotonic() - started,
    }
