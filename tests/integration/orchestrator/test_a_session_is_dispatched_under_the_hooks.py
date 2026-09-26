"""The dispatcher, with the real 2.1.272 binary against the scripted endpoint.

A session runs in its subtask's worktree under settings generated from the
read-only installation, with the key through a helper and not in its
environment. Its reading is read back from the hook layer's own records; the
wall clock and the turn limit are infrastructure outcomes with their cause; a
binary that no longer reports the recorded version is refused before any spawn.
No real model is called.
"""

from __future__ import annotations

import json
import os
import shutil
import sys
from pathlib import Path
from typing import Any

import pytest
from git_rig import config, run_layout
from scripted_endpoint import (  # noqa: E402
    DUMMY_KEY,
    DUMMY_OAUTH_TOKEN,
    Script,
    serving,
    text,
    tool,
)

from physgate.orchestrator.credentials import Credential  # noqa: E402
from physgate.orchestrator.dispatch import ClaudeDispatcher  # noqa: E402
from physgate.orchestrator.exceptions import InvocationError  # noqa: E402
from physgate.orchestrator.git import commit_all, git  # noqa: E402
from physgate.orchestrator.install import prepare_install  # noqa: E402
from physgate.orchestrator.invocation import claude_binary  # noqa: E402
from physgate.orchestrator.managed import system_managed_paths  # noqa: E402
from physgate.orchestrator.merge import RunGit  # noqa: E402
from physgate.orchestrator.ports import SessionRequest  # noqa: E402
from physgate.orchestrator.run_config import RunConfig  # noqa: E402
from physgate.state.store import Store  # noqa: E402

pytestmark = [
    pytest.mark.integration,
    pytest.mark.skipif(
        not (os.environ.get("PHYSGATE_CLAUDE_BIN") or shutil.which("claude")),
        reason="no Claude Code binary on this machine",
    ),
]

SPEC = ".physgate/specs/s1.md"
PROPOSAL: dict[str, Any] = {
    "id": "electrical.driver",
    "kind": "component",
    "domain": "electrical",
    "owner_role": "electrical",
    "quantities": {
        "current": {"value": 1.5, "unit": "A", "source": "datasheet", "written_by": "electrical"}
    },
    "requirements": [],
    "constrains": [],
    "model": None,
    "geometry_hash": "sha256:0",
    "updated": "2026-09-26T00:00:00Z",
}


@pytest.fixture(scope="module")
def install_bin(tmp_path_factory: pytest.TempPathFactory) -> Path:
    root = Path(__file__).resolve().parents[3]
    return prepare_install(tmp_path_factory.mktemp("install") / "hooks", root)


def layout(root: Path) -> tuple[RunGit, Path]:
    run = run_layout(root)
    (run.integration / ".physgate" / "specs").mkdir(parents=True)
    (run.integration / SPEC).write_text("Size the driver.\n")
    commit_all(run.integration, "specifications\n")
    store_root = run.run_dir / "store"
    store = Store(store_root)
    store.close()
    return run, store_root


def request(cfg: RunConfig) -> SessionRequest:
    return SessionRequest(
        subtask_id="s1",
        attempt=1,
        assigned_role="electrical",
        spec_path=SPEC,
        module_dir="modules/power",
        model="claude-sonnet-5",
        repair_instruction=None,
        bounds=cfg.bounds,
    )


def dispatch(
    root: Path,
    install_bin: Path,
    steps: list[dict[str, Any]],
    cfg: RunConfig | None = None,
    answer_as: str | None = None,
    credential: Credential | None = None,
) -> tuple[Any, Any, RunGit]:
    run, store_root = layout(root)
    cfg = cfg or config()
    with serving(Script(main=steps, answer_as=answer_as)) as (api, url):
        dispatcher = ClaudeDispatcher(
            config=cfg,
            run=run,
            store_root=store_root,
            install_bin=install_bin,
            binary=claude_binary(),
            base_url=url,
            credential=credential or Credential("api_key", DUMMY_KEY),
        )
        report = dispatcher.run(request(cfg))
        facts = dispatcher.environment()
    return api, (report, facts), run


def read_spec(run: RunGit) -> dict[str, Any]:
    return tool("Read", file_path=str(run.subtask_worktree("s1") / SPEC))


def test_a_session_reads_works_and_proposes_under_the_generated_settings(
    tmp_path: Path, install_bin: Path
) -> None:
    worktree = tmp_path / "run" / "worktrees" / "s1"
    steps = [
        tool("Read", file_path=str(worktree / SPEC)),
        tool("Bash", command="env > modules/power/env.txt; echo 'x = 2' > modules/power/a.py"),
        tool(
            "Write",
            file_path=str(worktree / ".physgate" / "proposals" / "electrical.driver.json"),
            content=json.dumps(PROPOSAL),
        ),
        text("done"),
    ]
    api, (report, facts), run = dispatch(tmp_path, install_bin, steps)
    assert report.end.outcome == "completed", report
    assert report.reading_verified and not report.node_files_halted
    files = git(run.repo, "show", "--name-only", "--format=", str(report.attempt_commit)).split()
    assert "modules/power/a.py" in files
    assert ".physgate/proposals/electrical.driver.json" in files
    env_seen = (worktree / "modules" / "power" / "env.txt").read_text()
    assert "ANTHROPIC_API_KEY" not in env_seen and DUMMY_KEY not in env_seen
    # Through the helper the binary sends the key in both headers (measured: both
    # carry the helper's key) and no OAuth header; nothing else could supply one:
    # no key in the environment, a scratch home.
    assert all(r.carried_dummy_key and not r.carried_other_credential for r in api.requests)
    assert not any(r.carried_oauth_login for r in api.requests)
    trajectory = Path(str(report.trajectory))
    assert trajectory.exists() and DUMMY_KEY not in trajectory.read_text()
    sdir = trajectory.parent
    assert not (sdir / "state" / "key").exists() and not (sdir / "state" / "key-helper.sh").exists()
    record = json.loads((sdir / "process.json").read_text())
    assert record["session_id"] == report.session_id
    spawn_args = record["installer_spawn_args"]
    at = record["argv"].index(spawn_args[0])
    assert record["argv"][at : at + len(spawn_args)] == spawn_args  # exactly what it printed
    assert spawn_args[:2] == ["--setting-sources", ""] and spawn_args[2] == "--settings"
    assert not Path(spawn_args[3]).is_relative_to(worktree)
    assert DUMMY_KEY not in json.dumps(record)
    assert len({u.message_id for u in report.usage}) == len(report.usage) == len(api.requests)
    assert facts.files_with_write_bits == 0 and facts.files_with_second_links == 0
    assert facts.owner_is_session_user  # the same user could make it writable again
    # The system tier is recorded as it is.
    assert [f.path for f in facts.system_managed] == [str(p) for p in system_managed_paths()]
    assert report.managed_drift is None


def test_the_first_tool_but_read_is_refused_until_the_reading_is_done(
    tmp_path: Path, install_bin: Path
) -> None:
    worktree = tmp_path / "run" / "worktrees" / "s1"
    steps = [
        tool("Bash", command="echo early > modules/power/early.py"),
        tool("Read", file_path=str(worktree / SPEC)),
        text("done"),
    ]
    api, (report, _), run = dispatch(tmp_path, install_bin, steps)
    assert report.reading_verified
    assert not (worktree / "modules" / "power" / "early.py").exists()
    assert "Required reading is not complete" in api.requests[1].last_user


def test_a_session_that_never_reads_is_reported_as_unread(
    tmp_path: Path, install_bin: Path
) -> None:
    _, (report, _), _ = dispatch(tmp_path, install_bin, [text("done without reading")])
    assert report.end.outcome == "completed" and not report.reading_verified


def test_the_wall_clock_stops_a_session_and_is_its_cause(tmp_path: Path, install_bin: Path) -> None:
    cfg = config()
    cfg = cfg.model_copy(
        update={"bounds": cfg.bounds.model_copy(update={"session_wall_clock_s": 4.0})}
    )
    worktree = tmp_path / "run" / "worktrees" / "s1"
    marker = f"sleep 31.{os.getpid()}"
    steps = [
        tool("Read", file_path=str(worktree / SPEC)),
        tool("Bash", command=marker),
        text("x"),
    ]
    _, (report, _), _ = dispatch(tmp_path, install_bin, steps, cfg)
    assert report.end.outcome == "infrastructure" and report.end.cause == "wall_clock"
    assert report.attempt_commit is None
    assert _running(marker) == [], "the stopped session left its tool running"


def test_the_turn_limit_is_an_infrastructure_outcome(tmp_path: Path, install_bin: Path) -> None:
    cfg = config()
    cfg = cfg.model_copy(update={"bounds": cfg.bounds.model_copy(update={"session_max_turns": 1})})
    worktree = tmp_path / "run" / "worktrees" / "s1"
    steps = [tool("Read", file_path=str(worktree / SPEC)), text("x")]
    _, (report, _), _ = dispatch(tmp_path, install_bin, steps, cfg)
    assert report.end.cause == "turn_limit"


def test_a_binary_that_is_not_the_recorded_version_is_refused_before_any_spawn(
    tmp_path: Path, install_bin: Path
) -> None:
    cfg = config().model_copy(update={"claude_version": "2.1.271"})
    with pytest.raises(InvocationError, match="not the version this run recorded"):
        dispatch(tmp_path, install_bin, [text("never")], cfg)
    assert not (tmp_path / "run" / "sessions").exists()


@pytest.mark.parametrize("mode", ["api_key", "subscription"])
def test_a_credential_that_reaches_the_stream_anyway_is_redacted_before_anything_reads_it(
    tmp_path: Path, install_bin: Path, mode: str
) -> None:
    # The helper or the login file keeps the secret out of the environment; this is
    # the second layer, for a secret that reaches the stream some other way, here in
    # the model's words.
    secret = DUMMY_KEY if mode == "api_key" else DUMMY_OAUTH_TOKEN
    worktree = tmp_path / "run" / "worktrees" / "s1"
    steps = [tool("Read", file_path=str(worktree / SPEC)), text(f"the secret is {secret}")]
    credential = Credential(mode, secret)  # type: ignore[arg-type]
    _, (report, _), _ = dispatch(tmp_path, install_bin, steps, credential=credential)
    captured = Path(str(report.trajectory)).read_text()
    assert secret not in captured and "[redacted: the credential]" in captured


def test_a_session_answered_by_a_model_other_than_the_pinned_one_is_refused(
    tmp_path: Path, install_bin: Path
) -> None:
    worktree = tmp_path / "run" / "worktrees" / "s1"
    steps = [tool("Read", file_path=str(worktree / SPEC)), text("done")]
    with pytest.raises(InvocationError, match="other than the pinned one") as caught:
        dispatch(tmp_path, install_bin, steps, answer_as="claude-haiku-4-5-20251001")
    assert caught.value.context == {
        "asked": "claude-sonnet-5",
        "answered": "claude-haiku-4-5-20251001",
    }


def _running(marker: str) -> list[str]:
    import subprocess

    out = subprocess.run(["ps", "-axo", "pid=,command="], capture_output=True, text=True).stdout
    return [line for line in out.splitlines() if marker in line and "ps -axo" not in line]


def test_a_session_left_running_by_a_killed_orchestrator_is_stopped_with_its_tools(
    tmp_path: Path, install_bin: Path
) -> None:
    import signal
    import subprocess
    import time

    run, store_root = layout(tmp_path)
    worktree = run.subtask_worktree("s1")
    marker = f"sleep 23.{os.getpid()}"
    late = worktree / "modules" / "power" / "late.py"
    steps = [
        tool("Read", file_path=str(worktree / SPEC)),
        tool("Bash", command=f"{marker} ; echo late > modules/power/late.py"),
        text("done"),
    ]
    cfg = config()
    with serving(Script(main=steps)) as (_, url):
        spec = {
            "config": cfg.model_dump(mode="json"),
            "repo": str(run.repo),
            "run_dir": str(run.run_dir),
            "store_root": str(store_root),
            "install_bin": str(install_bin),
            "base_url": url,
            "credential": {"mode": "api_key", "secret": DUMMY_KEY},
            "request": request(cfg).model_dump(mode="json"),
        }
        (tmp_path / "standin.json").write_text(json.dumps(spec))
        standin = subprocess.Popen(
            [
                sys.executable,
                str(Path(__file__).with_name("dispatch_standin.py")),
                str(tmp_path / "standin.json"),
            ]
        )
        deadline = time.monotonic() + 60
        while not _running(marker) and time.monotonic() < deadline:
            time.sleep(0.1)
        assert _running(marker), "the session's tool never started"
        standin.send_signal(signal.SIGKILL)
        standin.wait()
        time.sleep(1)
        (record_path,) = (run.run_dir / "sessions").glob("*/process.json")
        record = json.loads(record_path.read_text())
        from physgate.orchestrator.processes import started_at

        assert started_at(record["pid"]) == record["started"], "the orphaned session kept running"
        dispatcher = ClaudeDispatcher(
            config=cfg,
            run=run,
            store_root=store_root,
            install_bin=install_bin,
            binary=claude_binary(),
            base_url=url,
            credential=Credential("api_key", DUMMY_KEY),
        )
        assert (record_path.parent / "state" / "key").exists()
        stopped = dispatcher.stop_leftovers()
    assert [(s.session_id, s.pid, s.stopped) for s in stopped] == [
        (record["session_id"], record["pid"], True)
    ]
    # It had made requests before the orchestrator died; what they spent is returned,
    # partial, since a stopped session's stream has no result.
    (left,) = stopped
    assert left.usage and not left.complete
    assert all(u.usage.output_tokens > 0 for u in left.usage)
    # The killed orchestrator never removed the key; the resume did.
    assert not (record_path.parent / "state" / "key").exists()
    assert not (record_path.parent / "state" / "key-helper.sh").exists()
    time.sleep(25)
    assert started_at(record["pid"]) is None
    assert _running(marker) == []
    assert not late.exists(), "a tool of the stopped session wrote after the stop"


def _files_holding(root: Path, secret: str) -> list[str]:
    return [str(p) for p in root.rglob("*") if p.is_file() and secret.encode() in p.read_bytes()]


def test_a_subscription_token_reaches_the_binary_as_a_login_and_nothing_else_holds_it(
    tmp_path: Path, install_bin: Path
) -> None:
    worktree = tmp_path / "run" / "worktrees" / "s1"
    steps = [
        tool("Read", file_path=str(worktree / SPEC)),
        tool("Bash", command="env > modules/power/env.txt; echo 'x = 2' > modules/power/a.py"),
        text("done"),
    ]
    credential = Credential("subscription", DUMMY_OAUTH_TOKEN)
    api, (report, _), _ = dispatch(tmp_path, install_bin, steps, credential=credential)
    assert report.end.outcome == "completed", report
    # As the binary's own login: a bearer token with the OAuth header, never as a key.
    assert api.requests and all(r.carried_oauth_login for r in api.requests)
    assert all(r.credential_headers == ("authorization",) for r in api.requests)
    assert not any(r.carried_other_credential for r in api.requests)
    env_seen = (worktree / "modules" / "power" / "env.txt").read_text()
    assert "CLAUDE_CODE_OAUTH_TOKEN" not in env_seen and DUMMY_OAUTH_TOKEN not in env_seen
    sdir = Path(str(report.trajectory)).parent
    assert not (sdir / "config" / ".credentials.json").exists()
    assert not (sdir / "state" / "key").exists()
    assert _files_holding(tmp_path, DUMMY_OAUTH_TOKEN) == []


def test_each_message_is_counted_once_at_its_final_usage_and_matches_the_binary(
    tmp_path: Path, install_bin: Path
) -> None:
    # The earlier measurement again, with the endpoint sending usage as the real
    # API does: a message with a text block and a tool call is two assistant events
    # of one id, each with the usage it started with (1 output token); the final
    # usage (9) is in its message_delta.
    worktree = tmp_path / "run" / "worktrees" / "s1"
    reading = tool("Read", file_path=str(worktree / SPEC))
    reading["pre_text"] = "I will read the specification."
    api, (report, _), _ = dispatch(tmp_path, install_bin, [reading, text("done")])
    assert report.end.outcome == "completed", report
    events = [json.loads(line) for line in Path(str(report.trajectory)).read_text().splitlines()]
    per_event = [e["message"]["id"] for e in events if e.get("type") == "assistant"]
    assert len(per_event) == len(api.requests) + 1  # the two-block message twice
    assert len(report.usage) == len(api.requests) == 2
    assert all(u.usage.output_tokens == 9 and u.usage.input_tokens == 5 for u in report.usage)


def test_an_account_that_differs_from_the_binary_s_totals_is_an_error(
    tmp_path: Path, install_bin: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    import physgate.orchestrator.dispatch as dispatch_module
    from physgate.orchestrator.exceptions import AccountingError

    real = dispatch_module.read_stream  # type: ignore[attr-defined]

    def losing_a_message(text: str) -> Any:  # noqa: ANN401
        result, usages, models = real(text)
        return result, usages[:-1], models

    monkeypatch.setattr(dispatch_module, "read_stream", losing_a_message)
    worktree = tmp_path / "run" / "worktrees" / "s1"
    steps = [tool("Read", file_path=str(worktree / SPEC)), text("done")]
    with pytest.raises(AccountingError, match="differs from the binary's own totals"):
        dispatch(tmp_path, install_bin, steps)


def test_remote_settings_delivered_during_a_session_are_reported_as_drift(
    tmp_path: Path, install_bin: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    real = ClaudeDispatcher._install

    def delivering(self: Any, request: Any, worktree: Path, sdir: Path) -> Any:  # noqa: ANN401
        installed = real(self, request, worktree, sdir)
        (sdir / "config").mkdir(parents=True, exist_ok=True)
        (sdir / "config" / "remote-settings.json").write_text('{"disableAllHooks": true}')
        return installed

    monkeypatch.setattr(ClaudeDispatcher, "_install", delivering)
    worktree = tmp_path / "run" / "worktrees" / "s1"
    steps = [tool("Read", file_path=str(worktree / SPEC)), text("done")]
    _, (report, _), _ = dispatch(tmp_path, install_bin, steps)
    assert report.managed_drift is not None
    assert "remote managed settings were delivered" in report.managed_drift


def test_the_hook_installation_is_the_source_as_it_is_now(install_bin: Path) -> None:
    # The hooks a session runs under are the installation's copy, not the source.
    # uv's cache of a local project is keyed on its project file, so a cached
    # build could be an earlier hook layer; the installation is built without it.
    source = Path(__file__).resolve().parents[3] / "src" / "physgate"
    (installed,) = install_bin.parent.parent.glob("lib/python*/site-packages/physgate")
    for path in sorted(source.rglob("*.py")):
        copy = installed / path.relative_to(source)
        assert copy.read_bytes() == path.read_bytes(), f"stale in the installation: {copy}"
