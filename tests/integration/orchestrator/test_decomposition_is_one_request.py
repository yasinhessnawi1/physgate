"""The run's one model call, through the real binary against the scripted endpoint.

Criterion: ``decompose`` makes exactly one model call, writes at least one interface
node and one ledger line per subtask, and a second run with the same seed and
pinned model produces the same ledger ids. Counted at the endpoint as well as in
the account, because a call is one invocation and the binary could have sent more
than one request inside it.
"""

from __future__ import annotations

import os
import shutil
import sys
from pathlib import Path
from typing import Any

import pytest
from git_rig import config, target_repo

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "hooks"))
from fake_messages_api import DUMMY_KEY, Script, serving, text, tool  # noqa: E402

from physgate.orchestrator.accounting import TokenAccount  # noqa: E402
from physgate.orchestrator.decompose import call, start_run  # noqa: E402
from physgate.orchestrator.events import Decomposed, Halted, read_events  # noqa: E402
from physgate.orchestrator.git import head_of  # noqa: E402
from physgate.state.store import Store  # noqa: E402
from physgate.state.task_ledger import TaskLedger  # noqa: E402

pytestmark = pytest.mark.integration

if not (os.environ.get("PHYSGATE_CLAUDE_BIN") or shutil.which("claude")):
    pytest.skip("no Claude Code binary on this machine", allow_module_level=True)

NODE: dict[str, Any] = {
    "id": "power.bus",
    "kind": "interface",
    "domain": "electrical",
    "owner_role": "electrical",
    "quantities": {
        "voltage": {"value": 12, "unit": "V", "source": "brief", "written_by": "electrical"}
    },
    "requirements": [],
    "constrains": [],
    "model": None,
    "geometry_hash": "sha256:0",
    "updated": "2026-09-26T00:00:00Z",
}
PLAN: dict[str, Any] = {
    "modules": [
        {
            "name": "power",
            "role": "electrical",
            "module_dir": "modules/power",
            "spec": "Size the supply.",
        },
        {
            "name": "drive",
            "role": "electrical",
            "module_dir": "modules/drive",
            "spec": "Drive the motors.",
        },
    ],
    "interface_nodes": [NODE],
}


def decompose_once(root: Path, seed: int, steps: list[dict[str, Any]]) -> tuple[Any, Any, Path]:
    repo = target_repo(root)
    cfg = config().model_copy(update={"seed": seed, "target_head": head_of(repo, "master")})
    with serving(Script(main=steps)) as (api, url):
        outcome = call(
            "Build a self-balancing robot.",
            config=cfg,
            workdir=root / "run" / "decomposition",
            base_url=url,
            api_key=DUMMY_KEY,
        )
    record = start_run(outcome, config=cfg, run_dir=root / "run", target_repo=repo)
    record.close()
    return api, outcome, root / "run"


def test_one_call_one_request_one_ledger_line_per_subtask_and_an_interface_node(
    tmp_path: Path,
) -> None:
    api, outcome, run_dir = decompose_once(tmp_path, 7, [tool("StructuredOutput", **PLAN)])
    assert outcome.ok, outcome.detail
    assert len(api.requests) == 1
    assert api.requests[0].offered_tools == ("StructuredOutput",)
    assert all(r.carried_dummy_key and not r.carried_other_credential for r in api.requests)
    events = read_events(run_dir / "events.jsonl")
    account = TokenAccount.from_events(events)
    assert account.decomposition_invocations() == 1
    assert set(account.by_kind()) >= {"decomposition"}
    assert account.by_kind()["decomposition"].total() > 0
    account.assert_no_routing()
    (decomposed,) = [e for e in events if isinstance(e, Decomposed)]
    assert decomposed.interface_nodes == ("power.bus",) and decomposed.subtasks == 2
    lines = TaskLedger(run_dir / "ledger.jsonl").read_all()
    assert [line.attempt_count for line in lines] == [0, 0]
    store = Store(run_dir / "store")
    assert store.read_node("power.bus")["kind"] == "interface"
    store.close()
    spec = run_dir / "worktrees" / "_integration" / lines[0].spec_path
    assert spec.read_text() == "Size the supply.\n"


def test_the_same_seed_gives_the_same_ids_and_another_seed_does_not(tmp_path: Path) -> None:
    ids = []
    for name, seed in (("a", 7), ("b", 7), ("c", 8)):
        _, outcome, run_dir = decompose_once(
            tmp_path / name, seed, [tool("StructuredOutput", **PLAN)]
        )
        assert outcome.ok
        ids.append([line.id for line in TaskLedger(run_dir / "ledger.jsonl").read_all()])
    assert ids[0] == ids[1]
    assert ids[0] != ids[2]


@pytest.mark.parametrize(
    ("steps", "cause"),
    [
        ([text("here is a plan in prose")], "turn_limit"),
        (
            [
                tool(
                    "StructuredOutput",
                    **{**PLAN, "interface_nodes": [{**NODE, "kind": "component"}]},
                )
            ],
            "invalid_plan",
        ),
        ([tool("StructuredOutput", modules=[], interface_nodes=[NODE])], "turn_limit"),
    ],
    ids=["a prose answer", "a plan with no interface", "a schema-violating answer"],
)
def test_a_call_that_produced_no_usable_plan_fails_the_run_after_one_request(
    tmp_path: Path, steps: list[dict[str, Any]], cause: str
) -> None:
    api, outcome, run_dir = decompose_once(tmp_path, 7, steps)
    assert not outcome.ok and outcome.cause == cause
    assert len(api.requests) == 1
    events = read_events(run_dir / "events.jsonl")
    (halt,) = [e for e in events if isinstance(e, Halted)]
    assert halt.reason == "decomposition_failed" and halt.detail.startswith(cause)
    assert TaskLedger(run_dir / "ledger.jsonl").read_all() == []
    assert not (run_dir / "store").exists()


def test_the_decompose_command_twice_with_one_seed_gives_one_set_of_ids(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    import json

    from physgate.cli import main

    params = config().model_dump(include={"gate_mode", "models", "bounds", "token_ceiling"})
    (tmp_path / "params.json").write_text(json.dumps(params))
    (tmp_path / "brief.md").write_text("Build a self-balancing robot.\n")
    printed = []
    with serving(Script(main=[tool("StructuredOutput", **PLAN)])) as (api, url):
        monkeypatch.setenv("ANTHROPIC_BASE_URL", url)
        monkeypatch.setenv("ANTHROPIC_API_KEY", DUMMY_KEY)
        for name in ("a", "b", "a"):
            repo = tmp_path / name / "target"
            if not repo.exists():
                target_repo(tmp_path / name)
            code = main(
                [
                    "decompose",
                    str(tmp_path / "brief.md"),
                    "--seed",
                    "7",
                    "--run-id",
                    "run-1",
                    "--params",
                    str(tmp_path / "params.json"),
                    "--target",
                    str(repo),
                    "--run-dir",
                    str(tmp_path / name / "run"),
                ]
            )
            out = capsys.readouterr()
            printed.append((code, out.out, out.err))
    assert printed[0][0] == 0 and printed[1][0] == 0
    first, second = json.loads(printed[0][1]), json.loads(printed[1][1])
    assert first["subtasks"] == second["subtasks"] and len(first["subtasks"]) == 2
    assert printed[2][0] == 2 and "already holds a run" in printed[2][2]
    assert len(api.requests) == 2
