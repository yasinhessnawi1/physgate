"""The authoring runner and the blind check against the real binary, on the scripted endpoint.

No model is called. The scripted author copies sixteen prepared tasks into its worktree
after trying to read a held-out tier already inside the protected root, which it is
refused; the runner then splits them. The scripted checker writes its booleans. Runs in
the evaluation environment, since the runner holds every task to the control scorer.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

pytest.importorskip("control")

from scripted_endpoint import DUMMY_KEY, Script, serving, text, tool  # noqa: E402

from physgate.evaluation.per_role.arms.raw import RawSetup  # noqa: E402
from physgate.evaluation.per_role.author_session import (  # noqa: E402
    QUESTIONS,
    AuthoringPlan,
    author,
    blind_check,
    bundle,
)
from physgate.orchestrator.credentials import Credential  # noqa: E402
from physgate.orchestrator.decompose import binary_version  # noqa: E402
from physgate.orchestrator.install import prepare_install  # noqa: E402
from physgate.orchestrator.invocation import claude_binary, session_search_path  # noqa: E402
from physgate.orchestrator.run_config import RunBounds  # noqa: E402
from physgate.oslayer.probe import judge_here  # noqa: E402

pytestmark = pytest.mark.integration

OTHER_TIER = "an item of another held-out tier, never to be read"
PLANT = {"num": [10.0], "den": [1.0, -2.0, 3.0]}
GOOD = {
    "form": "lti_tf",
    "gain": {"value": 1.0, "unit": "1"},
    "num": [
        {"value": 1.02, "unit": "s**2"},
        {"value": 2.04, "unit": "s"},
        {"value": 4.0, "unit": "1"},
    ],
    "den": [
        {"value": 0.01, "unit": "s**2"},
        {"value": 1.0, "unit": "s"},
        {"value": 0.0, "unit": "1"},
    ],
}
UNSTABLE = {
    "form": "lti_tf",
    "gain": {"value": 0.1, "unit": "1"},
    "num": [{"value": 1.0, "unit": "1"}],
    "den": [{"value": 1.0, "unit": "1"}],
}


@pytest.fixture(scope="module")
def install_bin(tmp_path_factory: pytest.TempPathFactory) -> Path:
    return prepare_install(
        tmp_path_factory.mktemp("install") / "hooks", Path(__file__).resolve().parents[3]
    )


def _task(task_id: str, letter: str) -> dict[str, object]:
    units = ["s**2", "s", "1"]
    inputs = [{"name": "plant_num_0", "value": 10.0, "unit": "1"}] + [
        {"name": f"plant_den_{i}", "value": v, "unit": units[i]} for i, v in enumerate(PLANT["den"])
    ]
    spec = {"counts": "headline"}
    return {
        "id": task_id,
        "role": "control",
        "tier": "visible",
        "source": {"kind": "own"},
        "brief": f"Hold the unstable plant, case {letter}. Write answer.json as asked.",
        "inputs": inputs,
        "answer": {"path": "answer.json", "form": "lti_tf"},
        "specs": [
            {
                **spec,
                "name": "stable",
                "metric": "max_real_pole",
                "op": "<",
                "bound": {"value": 0, "unit": "1/s"},
                "composes": ["hold"],
            },
            {
                **spec,
                "name": "settling",
                "metric": "settling_time",
                "op": "in",
                "bound": [{"value": 0.05, "unit": "s"}, {"value": 3.0, "unit": "s"}],
                "composes": ["respond"],
            },
        ],
        "scorer": {"id": "control", "version": "1.1.0"},
    }


def _prepared(root: Path) -> Path:
    """Sixteen tasks as an author would leave them, to be copied by the scripted session."""
    for n in range(16):
        d = root / f"control.case{n:02d}"
        (d / "references" / "good").mkdir(parents=True)
        (d / "references" / "bad_unstable").mkdir(parents=True)
        (d / "task.json").write_text(json.dumps(_task(d.name, "abcdefghijklmnop"[n])))
        (d / "references" / "good" / "answer.json").write_text(json.dumps(GOOD))
        (d / "references" / "bad_unstable" / "answer.json").write_text(json.dumps(UNSTABLE))
        (d / "references" / "bad_unstable" / "expect.json").write_text('{"fails": "stable"}')
    return root


def _setup(install_bin: Path, url: str, root: Path) -> RawSetup:
    binary = claude_binary()
    version = binary_version(binary)
    return RawSetup(
        binary=binary,
        claude_version=version,
        model="claude-sonnet-5",
        effort="high",
        max_output_tokens=4000,
        thinking_display="summarized",
        bounds=RunBounds(
            binary_max_retries=0,
            session_wall_clock_s=60.0,
            session_max_turns=10,
            infra_retry_delays_s=(),
        ),
        credential=Credential("api_key", DUMMY_KEY),
        base_url=url,
        install_bin=install_bin,
        role_python=None,
        held_out=(str(root),),
        held_out_canaries=(),
        network="none",
        os_layer=judge_here(claude_version=version, search_path=session_search_path(binary)),
    )


def test_an_authoring_session_is_refused_the_protected_root_and_its_tasks_are_split(
    tmp_path: Path, install_bin: Path
) -> None:
    root = tmp_path / "private" / "v1"
    (root / "firmware").mkdir(parents=True)
    (root / "firmware" / "item.json").write_text(json.dumps({"item": OTHER_TIER}))
    prepared = _prepared(tmp_path / "prepared")
    plan = AuthoringPlan(
        role="control",
        implementer_model="claude-opus-5-5",
        work=tmp_path / "scratch" / "author",
        visible=tmp_path / "repo" / "visible",
        held_out_root=root,
        seed=3,
        cap=10**9,
    )
    (tmp_path / "scratch").mkdir()
    worktree = plan.work / "worktree"
    steps = [
        tool("Bash", command=f"cat {root}/firmware/item.json", description="x"),
        tool("Read", file_path=str(root / "firmware" / "item.json")),
        tool("Bash", command=f"cp -R {prepared}/. {worktree}/", description="x"),
        text("done"),
    ]
    with serving(Script(main=steps)) as (api, url):
        out = author(plan, _setup(install_bin, url, root))
        told = " ".join(r.last_user for r in api.requests)
    assert OTHER_TIER not in told
    assert out["status"] == "split" and out["held"] == 16 and out["held_out_count"] == 8
    assert out["held_out_check"]["references_held"] == 8
    assert out["session"]["end"] == "ended" and out["session"]["tokens"] > 0
    streams = list((root / "control.author").glob("*/stdout.jsonl"))
    assert len(streams) == 1 and OTHER_TIER not in streams[0].read_text()
    assert not plan.work.exists()


def test_a_blind_check_answers_in_booleans_on_its_tasks_file(
    tmp_path: Path, install_bin: Path
) -> None:
    root = tmp_path / "private" / "v1"
    tier = root / "control"
    tier.mkdir(parents=True)
    prepared = _prepared(tmp_path / "prepared")
    for d in sorted(prepared.iterdir())[:8]:
        task = json.loads((d / "task.json").read_text())
        task.update(tier="held_out", canary="c" * 32)
        (d / "task.json").write_text(json.dumps(task))
        d.rename(tier / d.name)
    keys = sorted(bundle(tier))
    answers = {k: dict.fromkeys(QUESTIONS, True) for k in keys}
    answers[keys[0]]["answerable_as_asked"] = False
    work = tmp_path / "scratch" / "check"
    (tmp_path / "scratch").mkdir()
    steps = [
        tool("Read", file_path=str(work / "worktree" / "tasks.json")),
        tool(
            "Write", file_path=str(work / "worktree" / "answers.json"), content=json.dumps(answers)
        ),
        text("done"),
    ]
    with serving(Script(main=steps)) as (api, url):
        out = blind_check(
            tier,
            _setup(install_bin, url, root),
            work,
            implementer_model="claude-opus-5-5",
            cap=10**9,
            evidence=root / "control.check",
        )
        argv_prompt = api.requests[0].last_user if api.requests else ""
    assert out["answered"] and out["tasks"] == 8 and out["flagged"] == [keys[0]]
    assert "Hold the unstable plant" not in argv_prompt
    assert not work.exists()
