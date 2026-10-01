"""Driving a whole run through the ``physgate`` command, for the physics gate's tests.

`physgate decompose`, then `physgate run`, with the real binary against the
scripted endpoint: every session reads its specification and writes the node
proposals it is given, under the hooks, as a model's tool calls would. No model
is called and no key is real. When ``PHYSGATE_EVIDENCE_DIR`` is set, each run's
event log, its configuration, its printed outcome and the output of
``physgate gate-events`` are copied there.
"""

from __future__ import annotations

import json
import os
import shutil
from pathlib import Path
from typing import Any

import pytest
from git_rig import PARAMS, Reviewer, config, target_repo
from scripted_endpoint import DUMMY_KEY, Script, serving, text, tool

from physgate.cli import main
from physgate.gate.runner import PhysicsGate
from physgate.knowledge import loader
from physgate.orchestrator.accounting import TokenAccount
from physgate.orchestrator.cli import Registrations
from physgate.orchestrator.events import read_events
from physgate.orchestrator.git import commit_all
from physgate.orchestrator.install import prepare_install
from physgate.orchestrator.protocols import MessageUsage, ReviewResult, Usage

#: Every module this file plans is role ``electrical`` (below); the reading
#: hook now requires that role's curated content before any other tool, so a
#: worktree derived from ``target_repo`` needs it committed, and every session
#: script needs to read it (ARCH-020, ARCH-023).
_KNOWLEDGE_READS = [
    tool("Read", file_path=f"{{cwd}}/{relative.as_posix()}")
    for relative in loader.always_loaded("electrical")
]


def seed_knowledge(repo: Path) -> None:
    """Commit fixture-only curated content for the ``electrical`` role into ``repo``.

    Exported: every test that builds its own ``target_repo`` rather than going
    through ``drive_run`` (below) needs this too, since any role it dispatches
    is now held to the same required reading a real session is.
    """
    for relative in loader.always_loaded("electrical"):
        path = repo / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(
            f"# {relative.name}\n\nFixture content for the gate's command-level tests.\n"
        )
    commit_all(repo, "curated knowledge fixture\n")


BRIEF = "Build a self-balancing robot; start with its power.\n"

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


class PayingReviewer(Reviewer):
    """A reviewer reporting the tokens a real one would, so a zero means it never ran."""

    def review(self, artefact: Any) -> ReviewResult:
        result = super().review(artefact)
        usage = Usage(
            input_tokens=40,
            output_tokens=9,
            cache_read_input_tokens=0,
            cache_creation_input_tokens=0,
        )
        message = MessageUsage(message_id=f"r{self.calls}", usage=usage)
        return result.model_copy(update={"usage": (message,)})


def build_install(tmp_path_factory: pytest.TempPathFactory) -> Path:
    """A copied, read-only installation of this package, built once per module."""
    path = tmp_path_factory.mktemp("install") / "install"
    prepare_install(path, Path(__file__).resolve().parents[3])
    return path


def session(*payloads: dict[str, Any]) -> Script:
    """What every session does: read its curated content and spec, write its proposals, stop."""
    writes = [
        tool(
            "Write",
            file_path=f"{{cwd}}/.physgate/proposals/{p['id']}.json",
            content=json.dumps(p),
        )
        for p in payloads
    ]
    return Script(
        main=[
            *_KNOWLEDGE_READS,
            tool("Read", file_path="{cwd}/.physgate/specs/{cwd_name}.md"),
            *writes,
            text("done"),
        ]
    )


def drive_run(
    tmp_path: Path,
    install: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    modules: list[tuple[str, str]],
    payloads: tuple[dict[str, Any], ...],
    label: str,
    gate_mode: str = "on",
    brief: str = BRIEF,
) -> tuple[dict[str, Any], list[Any], PayingReviewer, list[dict[str, Any]]]:
    """Decompose and run one plan.

    Returns the printed outcome, the events, the reviewer and the gate events.
    """
    repo = target_repo(tmp_path)
    seed_knowledge(repo)
    run_dir = tmp_path / "run"
    params = config().model_dump(include=PARAMS)
    params["gate_mode"] = gate_mode
    (tmp_path / "params.json").write_text(json.dumps(params))
    (tmp_path / "brief.md").write_text(brief)
    monkeypatch.setenv("ANTHROPIC_API_KEY", DUMMY_KEY)
    plan = {
        "modules": [
            {"name": n, "role": "electrical", "module_dir": d, "spec": "Size the power."}
            for n, d in modules
        ],
        "interface_nodes": [INTERFACE],
    }
    reviewer = PayingReviewer()
    registrations = Registrations(gate=PhysicsGate(), reviewers={"electrical": reviewer})
    with serving(Script(main=[tool("StructuredOutput", **plan)])) as (api, url):
        monkeypatch.setenv("ANTHROPIC_BASE_URL", url)
        args = ["--seed", "7", "--run-id", "run-1", "--params", str(tmp_path / "params.json")]
        code = main(
            [
                "decompose",
                str(tmp_path / "brief.md"),
                *args,
                "--target",
                str(repo),
                "--run-dir",
                str(run_dir),
            ]
        )
        assert code == 0, capsys.readouterr().err
        capsys.readouterr()
        api.script = session(*payloads)
        common = ["--run-dir", str(run_dir), "--target", str(repo), "--install", str(install)]
        main(["run", *common], registrations)
        out = capsys.readouterr()
    printed = json.loads(out.out) if out.out.strip() else {"error": out.err}
    assert "error" not in printed, out.err
    assert main(["gate-events", "--run-dir", str(run_dir)]) == 0
    gate_lines = [json.loads(x) for x in capsys.readouterr().out.splitlines()]
    events = read_events(run_dir / "events.jsonl")
    evidence = os.environ.get("PHYSGATE_EVIDENCE_DIR")
    if evidence:
        target = Path(evidence) / label
        target.mkdir(parents=True, exist_ok=True)
        shutil.copy(run_dir / "events.jsonl", target / "events.jsonl")
        shutil.copy(run_dir / "run.json", target / "run.json")
        shutil.copy(tmp_path / "brief.md", target / "brief.md")
        (target / "run_output.json").write_text(json.dumps(printed, indent=1, sort_keys=True))
        (target / "gate_events.jsonl").write_text(
            "".join(json.dumps(x, sort_keys=True) + "\n" for x in gate_lines)
        )
    return printed, events, reviewer, gate_lines


def reviewer_tokens(events: list[Any]) -> int:
    return TokenAccount.from_events(events).by_kind()["reviewer"].total()
