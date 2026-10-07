"""Every request of a run carries the effort level and output-token limit its record names.

The binary puts an effort level and a ``max_tokens`` in every request. Left to
itself it takes both from a model catalog that can change while its version
stays the same, so the run names them, records them, and passes them to every
invocation: the decomposition call and every role session. The same holds for the display of
a role session's reasoning, which only role sessions are given. Measured here at the
scripted endpoint, which sees each request as the binary sent it, with values
that differ from the binary's own defaults (``high`` and 64000), so a value that
only happened to match could not pass.
"""

from __future__ import annotations

import json
import os
import shutil
from pathlib import Path
from typing import Any

import pytest
from git_rig import PARAMS, Gate, Reviewer, config, target_repo
from scripted_endpoint import DUMMY_KEY, Script, serving, text, tool

from physgate.cli import main
from physgate.orchestrator.cli import Registrations
from physgate.orchestrator.decompose import mint_id
from physgate.orchestrator.install import prepare_install

pytestmark = [
    pytest.mark.integration,
    pytest.mark.skipif(
        not (os.environ.get("PHYSGATE_CLAUDE_BIN") or shutil.which("claude")),
        reason="no Claude Code binary on this machine",
    ),
]

INTERFACE: dict[str, Any] = {
    "id": "iface.power_bus",
    "kind": "interface",
    "domain": "electrical",
    "owner_role": "electrical",
    "quantities": {"v": {"value": 12, "unit": "V", "source": "brief", "written_by": "electrical"}},
    "requirements": [],
    "constrains": [],
    "model": None,
    "geometry_hash": "sha256:0",
    "updated": "2026-09-26T00:00:00Z",
}
PLAN: dict[str, Any] = {
    "modules": [
        {"name": "power", "role": "electrical", "module_dir": "modules/power", "spec": "Size it."}
    ],
    "interface_nodes": [INTERFACE],
}


def test_the_decomposition_and_every_session_request_carry_the_recorded_pins(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    repo = target_repo(tmp_path)
    run_dir = tmp_path / "run"
    install = tmp_path / "install"
    prepare_install(install, Path(__file__).resolve().parents[3])
    params = {**config().model_dump(include=PARAMS), "effort": "low", "max_output_tokens": 1000}
    (tmp_path / "params.json").write_text(json.dumps(params))
    (tmp_path / "brief.md").write_text("Build a self-balancing robot.\n")
    monkeypatch.setenv("ANTHROPIC_API_KEY", DUMMY_KEY)
    with serving(Script(main=[tool("StructuredOutput", **PLAN)])) as (api, url):
        monkeypatch.setenv("ANTHROPIC_BASE_URL", url)
        args = ["--seed", "7", "--run-id", "run-1", "--params", str(tmp_path / "params.json")]
        where = ["--target", str(repo), "--run-dir", str(run_dir)]
        assert main(["decompose", str(tmp_path / "brief.md"), *args, *where]) == 0
        capsys.readouterr()
        recorded = json.loads((run_dir / "run.json").read_text())
        assert (recorded["effort"], recorded["max_output_tokens"]) == ("low", 1000)
        decomposition = list(api.requests)
        subtask = mint_id(7, 0, "power")
        spec = run_dir / "worktrees" / subtask / ".physgate" / "specs" / f"{subtask}.md"
        api.script = Script(main=[tool("Read", file_path=str(spec)), text("done")])
        common = [
            "--run-dir",
            str(run_dir),
            "--target",
            str(repo),
            "--install",
            str(install),
            "--review-root",
            str(tmp_path / "rs"),
        ]
        registrations = Registrations(gate=Gate(), reviewers={"electrical": Reviewer()})
        main(["run", *common], registrations)
        capsys.readouterr()
        session = api.requests[len(decomposition) :]
    assert len(decomposition) == 1 and len(session) >= 2  # the call, then a read and an answer
    for request in [*decomposition, *session]:
        assert (request.effort, request.max_tokens) == ("low", 1000), request.path
    # Every role session request carries the run's thinking display; the one
    # decomposition call is not a role session and keeps the binary's own.
    assert recorded["thinking_display"] == "summarized"
    assert all((r.thinking or {}).get("display") == "summarized" for r in session), [
        r.thinking for r in session
    ]
    assert (decomposition[0].thinking or {}).get("display") != "summarized"
    # The specification as issued is digested at dispatch, before the session runs.
    import hashlib
    import subprocess

    from physgate.orchestrator.events import Decomposed, SessionEnded, read_events

    events = read_events(run_dir / "events.jsonl")
    issued_by = next(e.spec_commit for e in events if isinstance(e, Decomposed))
    spec_path = f".physgate/specs/{subtask}.md"
    issued = subprocess.run(
        ["git", "cat-file", "blob", f"{issued_by}:{spec_path}"],
        cwd=repo,
        capture_output=True,
        check=True,
    ).stdout
    ended = [e for e in events if isinstance(e, SessionEnded)]
    assert ended and all(e.issued_spec_sha256 == hashlib.sha256(issued).hexdigest() for e in ended)
    assert "StructuredOutput" in decomposition[0].offered_tools
    assert all("Read" in r.offered_tools for r in session)
