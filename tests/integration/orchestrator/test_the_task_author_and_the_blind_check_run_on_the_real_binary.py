"""The authoring runner and the blind check against the real binary, on the scripted endpoint.

No model is called. The scripted author copies twenty-four prepared tasks into its worktree
after trying to read what lies in another role's root, which it is refused; the runner then
writes them as a version of the tier-set store. The scripted checker writes its booleans on
a version's held-out tier, after trying to write anywhere else in the store, which it is
refused. Runs in the evaluation environment, since the runner holds every task to the
control scorer: on the development machine, and in CI's OS-layer job, which installs it.
"""

from __future__ import annotations

import dataclasses
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
from physgate.evaluation.tiers.store import check_roots, work_root, write_version  # noqa: E402
from physgate.evaluation.tiers.task import canonical_json  # noqa: E402
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
    """Twenty-four tasks as an author would leave them, to be copied by the scripted session."""
    for n in range(24):
        d = root / f"control.case{n:02d}"
        (d / "references" / "good").mkdir(parents=True)
        (d / "references" / "bad_unstable").mkdir(parents=True)
        (d / "task.json").write_text(json.dumps(_task(d.name, "abcdefghijklmnopqrstuvwx"[n])))
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
    """Two sessions on one root: the first pools twelve tasks, the second completes the tiers.

    The second session is the regression for the 80 M-token run: the first session's
    evidence (its stream, its home, its interpreter link) now lies under the protected
    root, and the second session must still be allowed every tool call.
    """
    store = tmp_path / "private" / "store"
    root = store / "control"
    other = store / "firmware" / "withheld" / "item.json"
    other.parent.mkdir(parents=True)
    other.write_text(json.dumps({"item": OTHER_TIER}))
    prepared = _prepared(tmp_path / "prepared")
    halves = [sorted(prepared.iterdir())[:12], sorted(prepared.iterdir())[12:]]
    (tmp_path / "scratch").mkdir()
    outs = []
    for n, half in enumerate(halves):
        plan = AuthoringPlan(
            role="control",
            implementer_model="claude-opus-5-5",
            work=tmp_path / "scratch" / f"author{n}",
            store=store,
            seed=3,
            cap=8_000_000,
            id_prefix=f"b{n + 1}.",
        )
        worktree = plan.work / "worktree"
        copies = " && ".join(f"cp -R {d} {worktree}/" for d in half)
        steps = [
            tool("Bash", command=f"cat {other}", description="x"),
            tool("Read", file_path=str(other)),
            tool("Bash", command=copies, description="x"),
            text("done"),
        ]
        with serving(Script(main=steps)) as (api, url):
            out = author(plan, _setup(install_bin, url, store))
            told = " ".join(r.last_user for r in api.requests)
        assert OTHER_TIER not in told
        assert f'beginning with "b{n + 1}."' in api.requests[0].last_user
        # The scripted session copies its tasks and ends within seconds, so the checkpoint
        # sees some of them before the end; a real author takes minutes over each.
        assert out["held"] == 12 and out["pooled"] == 12 and 0 <= out["held_while_running"] <= 12
        assert out["session"]["end"] == "ended" and out["session"]["tokens"] > 0
        assert not plan.work.exists()
        outs.append(out)
    assert outs[0]["status"] == "pooled" and outs[0]["pool"] == 12
    assert outs[1]["status"] == "split" and outs[1]["pool"] == 0
    assert outs[1]["held_out_count"] == 8 and outs[1]["held_out_check"]["references_held"] == 8
    assert not (root / "withheld" / "pool").exists()
    assert (root / outs[1]["version"] / "tierset.json").is_file()
    streams = sorted(
        (root / "withheld" / "author").glob("*/stdout.jsonl"), key=lambda p: p.stat().st_mtime
    )
    assert len(streams) == 2
    for stream in streams:
        text_ = stream.read_text()
        assert OTHER_TIER not in text_
        # The reads of the tier were refused as such; the tripwire, which refuses every
        # call once anything under the root has a second name, never spoke.
        assert "hook error" in text_
        assert "has a second name, changed, or cannot be checked" not in text_
    linked = [
        p for p in root.rglob("*") if p.is_symlink() or p.is_file() and p.stat().st_nlink != 1
    ]
    assert not linked


def test_a_blind_check_answers_in_booleans_on_its_tasks_file(
    tmp_path: Path, install_bin: Path
) -> None:
    store = tmp_path / "private" / "store"
    root = store / "control"
    root.mkdir(parents=True)
    (store / "firmware" / "withheld").mkdir(parents=True)
    (store / "firmware" / "withheld" / "item.json").write_text(json.dumps({"item": OTHER_TIER}))
    prepared = _prepared(tmp_path / "prepared")
    manifest, _ = write_version(
        root,
        sorted(prepared.iterdir()),
        role="control",
        seed=3,
        model="claude-sonnet-5",
        runtime="2.1.301",
        provenance=canonical_json({"sessions": []}),
    )
    tier = root / manifest.version / "held_out"
    # Each protected tier's list lies inside it, as the split leaves it; the check looks for
    # every canary they name.
    canaries = tuple(
        c
        for name in ("validation", "held_out")
        for c in json.loads((root / manifest.version / name / "canaries.json").read_text())
    )
    keys = sorted(bundle(tier))
    answers = {k: dict.fromkeys(QUESTIONS, True) for k in keys}
    answers[keys[0]]["answerable_as_asked"] = False
    # The check works in the role's work root, and withholds all of the store but it.
    work = work_root(store, "control") / "check"
    held = tuple(str(p) for p in check_roots(store, "control", work))
    planted = [
        root / "planted_tool.json",
        work_root(store, "control") / "copy.json",
        store / "planted.json",
        store / "firmware" / "planted.json",
    ]
    steps = [
        tool("Read", file_path=str(work / "worktree" / "tasks.json")),
        tool("Read", file_path=str(store / "firmware" / "withheld" / "item.json")),
        *[tool("Write", file_path=str(p), content='{"a": "copy"}') for p in planted],
        tool("Bash", command=f"cp {work}/worktree/tasks.json {root}/planted.sh", description="x"),
        tool(
            "Write", file_path=str(work / "worktree" / "answers.json"), content=json.dumps(answers)
        ),
        text("done"),
    ]
    with serving(Script(main=steps)) as (api, url):
        out = blind_check(
            store,
            "control",
            manifest.version,
            dataclasses.replace(
                _setup(install_bin, url, root), held_out=held, held_out_canaries=canaries
            ),
            work,
            implementer_model="claude-opus-5-5",
            cap=10**9,
        )
        argv_prompt = api.requests[0].last_user if api.requests else ""
        told = " ".join(r.last_user for r in api.requests)
    assert out["answered"] and out["tasks"] == 8 and out["flagged"] == [keys[0]]
    assert "Hold the unstable plant" not in argv_prompt
    assert OTHER_TIER not in told, "the check read another role's root"
    assert not [p for p in [*planted, root / "planted.sh"] if p.exists()], (
        "the check's session wrote in the store outside its own work"
    )
    assert not work.exists()
