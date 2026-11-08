"""A dispatched role session, with the real binary, reads nothing of its own hook state.

The session's hook state directory lies under the run directory, beside its home, and holds what
the sentinel kept at the session's start. A Read of a file the sentinel kept there is refused by
the hooks, and after the session no file under the run directory that holds a canary or a byte of
the held-out tier is open to the session's reads. No real model is called.
"""

from __future__ import annotations

import os
import shutil
from pathlib import Path
from typing import Any

import pytest
from git_rig import config
from scripted_endpoint import DUMMY_KEY, Script, serving, text, tool
from test_a_session_is_dispatched_under_the_hooks import (
    install_bin,  # noqa: F401 - the module's fixture, used by name
    knowledge_reads,
    layout,
    read_spec,
    request,
)

from physgate.hooks import paths, shell_paths
from physgate.hooks.config import SessionConfig
from physgate.hooks.settings import CONFIG_NAME
from physgate.hooks.shell import parse
from physgate.orchestrator.credentials import Credential
from physgate.orchestrator.dispatch import ClaudeDispatcher
from physgate.orchestrator.invocation import claude_binary
from physgate.orchestrator.run_config import write_run_config

pytestmark = [
    pytest.mark.integration,
    pytest.mark.skipif(
        not (os.environ.get("PHYSGATE_CLAUDE_BIN") or shutil.which("claude")),
        reason="no Claude Code binary on this machine",
    ),
]

CANARIES = ("ab" * 16, "ef" * 16)
HELD_BYTES = b"held-out stand-in 3e7a91c0, scenario one\n"


def _packs(run_dir: Path) -> list[Path]:
    return sorted((run_dir / "sessions").glob("*/state/sessions/*/sentinel/blobs/pack-*"))


def test_a_read_of_what_the_sentinel_kept_is_refused_and_no_readable_file_holds_a_canary(
    tmp_path: Path,
    install_bin: Path,  # noqa: F811 - the fixture imported above
) -> None:
    held = tmp_path / "tiers" / "v1"
    held.mkdir(parents=True)
    (held / "scenario.json").write_bytes(HELD_BYTES)
    run, store_root = layout(tmp_path)
    cfg = config().model_copy(
        update={
            "held_out": (str(held),),
            "held_out_canaries": CANARIES,
            "held_out_sha256": ("0" * 64,),
        }
    )
    write_run_config(run.run_dir / "run.json", cfg)
    worktree = run.subtask_worktree("s1")
    steps: list[dict[str, Any]] = [*knowledge_reads(worktree), read_spec(run)]
    asked: list[str] = []

    def on_request(thread: str, _cwd: str, done: int) -> dict[str, Any] | None:
        # Once the scripted reading is done, a Read of a file the sentinel kept, found as the
        # session itself could find it: its name is random, so it is looked up at that moment.
        if thread != "main" or done != len(steps):
            return None
        packs = _packs(run.run_dir)
        assert packs, "the sentinel kept nothing by the time the session ran"
        asked.append(str(packs[0]))
        return tool("Read", file_path=str(packs[0]))

    with serving(Script(main=[*steps, text("placeholder"), text("done")])) as (api, url):
        api.on_request = on_request
        dispatcher = ClaudeDispatcher(
            config=cfg,
            run=run,
            store_root=store_root,
            install_bin=install_bin,
            binary=claude_binary(),
            base_url=url,
            credential=Credential("api_key", DUMMY_KEY),
            review_root=Path("/nonexistent/review-scratch"),
        )
        report = dispatcher.run(request(cfg))
    assert report.end.outcome == "completed", report
    assert len(asked) == 1, asked
    told = next(r.last_user for r in api.requests if r.tool_results == len(steps) + 1)
    # The hooks' refusal, naming the file and why; never the file's bytes.
    assert asked[0] in told and "hook layer's own records" in told, told
    assert all(c not in told for c in CANARIES), told

    sdir = Path(str(report.trajectory)).parent
    session = SessionConfig.model_validate_json((sdir / "session" / CONFIG_NAME).read_bytes())
    secrets = (*(c.encode() for c in CANARIES), HELD_BYTES)
    holding = sorted(
        path
        for path in (*run.run_dir.rglob("*"), *held.rglob("*"))
        if path.is_file()
        and not path.is_symlink()
        and any(secret in path.read_bytes() for secret in secrets)
    )
    assert {"run.json", "scenario.json"} <= {p.name for p in holding}, holding
    assert _packs(run.run_dir), "the session's state is gone"
    for path in holding:
        assert paths.protection(str(path), str(worktree), session, writing=False) is not None, path
        command = parse(f"cat {path}")[0]
        assert shell_paths.check(command, str(worktree), session) is not None, path


def test_a_read_of_a_sibling_session_s_login_is_refused_and_the_session_still_runs(
    tmp_path: Path,
    install_bin: Path,  # noqa: F811 - the fixture imported above
) -> None:
    # An earlier session of the run left its directory, its login among it. This session's own
    # binary still reads its own configuration, which no tool does, so the session runs.
    token = "sk-ant-oat01-not-a-credential-5e2f"
    sibling = tmp_path / "run" / "sessions" / "0b1c2d3e-sibling" / "config"

    def with_a_sibling(run: Any) -> None:  # noqa: ANN401 - the run's git, as the rig gives it
        sibling.mkdir(parents=True)
        (sibling / ".credentials.json").write_text(
            '{"claudeAiOauth": {"accessToken": "' + token + '"}}\n'
        )

    run, store_root = layout(tmp_path)
    with_a_sibling(run)
    cfg = config()
    write_run_config(run.run_dir / "run.json", cfg)
    worktree = run.subtask_worktree("s1")
    login = sibling / ".credentials.json"
    steps = [*knowledge_reads(worktree), read_spec(run), tool("Read", file_path=str(login))]
    with serving(Script(main=[*steps, text("done")])) as (api, url):
        dispatcher = ClaudeDispatcher(
            config=cfg,
            run=run,
            store_root=store_root,
            install_bin=install_bin,
            binary=claude_binary(),
            base_url=url,
            credential=Credential("api_key", DUMMY_KEY),
            review_root=Path("/nonexistent/review-scratch"),
        )
        report = dispatcher.run(request(cfg))
    assert report.end.outcome == "completed", report
    told = next(r.last_user for r in api.requests if r.tool_results == len(steps))
    assert str(login) in told and token not in told, told
    assert "session" in told and "protected" in told.lower(), told
