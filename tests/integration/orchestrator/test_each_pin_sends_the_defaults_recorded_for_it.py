"""What each pinned binary sends that no run setting pins is what the manifest records for it.

A run's manifest carries its binary's own request defaults (the thinking field, context
management, the beta flags), measured once per version at the scripted endpoint on the
subscription-shaped path. Recorded once and never checked again, an entry could stop being true
while the version stays the same, and a new version has no entry until one is measured. Here the
decomposition call and a role session run through the command on the pinned binary under test,
and every request they send is held to that version's entry.

At the scripted endpoint the binary talks to a custom base URL, and since 2.1.304 that alone
turns its tool search on, so what it sends here may differ from what it sends to the real API.
The entry records the scripted endpoint's measurement and says so.
"""

from __future__ import annotations

import json
import os
import shutil
from pathlib import Path
from typing import Any

import pytest
from git_rig import Gate, Reviewer, config, run_params, target_repo
from scripted_endpoint import DUMMY_OAUTH_TOKEN, Recorded, Script, serving, text, tool
from test_every_request_carries_the_run_s_effort_and_token_limit import PLAN

from physgate.cli import main
from physgate.evaluation.observe.manifest import BINARY_DEFAULTS, BinaryDefaults
from physgate.orchestrator.cli import Registrations
from physgate.orchestrator.decompose import binary_version, mint_id
from physgate.orchestrator.install import prepare_install

pytestmark = [
    pytest.mark.integration,
    pytest.mark.skipif(
        not (os.environ.get("PHYSGATE_CLAUDE_BIN") or shutil.which("claude")),
        reason="no Claude Code binary on this machine",
    ),
]


def _models(model: str) -> dict[str, Any]:
    """The decomposition and the role on ``model``; the reviewer on another, as separation asks."""
    reviewer = "claude-sonnet-5" if model != "claude-sonnet-5" else "claude-opus-5-5"
    return {
        "decomposition": model,
        "roles": {"electrical": model},
        "reviewers": {"electrical": reviewer},
    }


def _sent(request: Recorded, *, keep_display: bool) -> dict[str, Any]:
    thinking = dict(request.thinking or {})
    if not keep_display:
        # A role session's display is the run's own setting, recorded in its configuration.
        thinking.pop("display", None)
    return {
        "thinking": thinking,
        "context_management": request.context_management,
        "anthropic_beta": list(request.anthropic_beta),
    }


def _expected(defaults: BinaryDefaults, *, decomposition: bool) -> dict[str, Any]:
    differs = defaults.decomposition if decomposition else None
    return {
        "thinking": differs.thinking if differs else defaults.thinking,
        "context_management": defaults.context_management,
        "anthropic_beta": sorted(differs.anthropic_beta if differs else defaults.anthropic_beta),
    }


def test_the_decomposition_and_a_role_session_send_what_their_pin_s_entry_records(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    """Once for every model the binary's version has an entry for: the entry is per model."""
    version = binary_version()
    models = sorted(m for v, m in BINARY_DEFAULTS if v == version)
    assert models, f"no defaults are recorded for {version} on any model"
    for model in models:
        _measure(tmp_path / model, monkeypatch, capsys, version, model)


def _measure(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    version: str,
    model: str,
) -> None:
    tmp_path.mkdir(parents=True)
    repo = target_repo(tmp_path)
    run_dir = tmp_path / "run"
    install = tmp_path / "install"
    prepare_install(install, Path(__file__).resolve().parents[3])
    # The entry's own model: the beta flags a request carries depend on its model as well as on
    # the binary's version.
    params = {**run_params(config()), "auth": "subscription", "models": _models(model)}
    (tmp_path / "params.json").write_text(json.dumps(params))
    (tmp_path / "brief.md").write_text("Build a self-balancing robot.\n")
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    monkeypatch.setenv("CLAUDE_CODE_OAUTH_TOKEN", DUMMY_OAUTH_TOKEN)
    with serving(Script(main=[tool("StructuredOutput", **PLAN)])) as (api, url):
        monkeypatch.setenv("ANTHROPIC_BASE_URL", url)
        args = ["--seed", "7", "--run-id", "run-1", "--params", str(tmp_path / "params.json")]
        where = ["--target", str(repo), "--run-dir", str(run_dir)]
        assert main(["decompose", str(tmp_path / "brief.md"), *args, *where]) == 0
        capsys.readouterr()
        decomposition = list(api.requests)
        subtask = mint_id(7, 0, "power")
        spec = run_dir / "worktrees" / subtask / ".physgate" / "specs" / f"{subtask}.md"
        api.script = Script(main=[tool("Read", file_path=str(spec)), text("done")])
        common = ["--run-dir", str(run_dir), "--target", str(repo), "--install", str(install)]
        reviewer = _models(model)["reviewers"]["electrical"]
        registrations = Registrations(
            gate=Gate(), reviewers={"electrical": Reviewer(model=reviewer)}
        )
        code = main(["run", *common, "--review-root", str(tmp_path / "rs")], registrations)
        out = capsys.readouterr()
        assert code == 0, out.err
        session = api.requests[len(decomposition) :]
    assert len(decomposition) == 1 and len(session) >= 2  # the call, then a read and an answer
    assert all(r.carried_oauth_login for r in [*decomposition, *session])
    measured = {
        "decomposition": _sent(decomposition[0], keep_display=True),
        "sessions": sorted(
            {json.dumps(_sent(r, keep_display=False), sort_keys=True) for r in session}
        ),
    }
    defaults = BINARY_DEFAULTS.get((version, model))
    assert defaults is not None, f"no defaults for {version} on {model}; it sends {measured}"
    assert measured["decomposition"] == _expected(defaults, decomposition=True), measured
    sessions = [json.loads(s) for s in measured["sessions"]]
    assert sessions == [_expected(defaults, decomposition=False)], measured
