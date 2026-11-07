"""The raw arm against the real binary, driven by the scripted endpoint: no model is called.

One session answers on its brief and is scored on what it left; one tries to read the
held-out tier and is refused; one is stopped by the token cap while a command runs. The
OS layer is used wherever it runs on the machine, as in a real run.
"""

from __future__ import annotations

import json
import time
from pathlib import Path

import pytest
from scripted_endpoint import DUMMY_KEY, Script, serving, text, tool

from physgate.evaluation.per_role.arms.raw import RawSetup, run_raw
from physgate.evaluation.per_role.task import parse_task
from physgate.orchestrator.credentials import Credential
from physgate.orchestrator.decompose import binary_version
from physgate.orchestrator.install import prepare_install
from physgate.orchestrator.invocation import claude_binary, session_search_path
from physgate.orchestrator.run_config import RunBounds
from physgate.oslayer.probe import judge_here

pytestmark = pytest.mark.integration

HELD = "the held-out answer of scenario 07"
ANSWER = {"form": "lti_tf", "gain": {"value": 2.0, "unit": "1"}, "num": [], "den": []}


@pytest.fixture(scope="module")
def install_bin(tmp_path_factory: pytest.TempPathFactory) -> Path:
    return prepare_install(
        tmp_path_factory.mktemp("install") / "hooks", Path(__file__).resolve().parents[3]
    )


def _task() -> object:
    task = {
        "id": "control.raw_probe",
        "role": "control",
        "tier": "visible",
        "source": {"kind": "own"},
        "brief": "Write a controller to answer.json in the directory you work in.",
        "answer": {"path": "answer.json", "form": "lti_tf"},
        "specs": [
            {
                "name": "a",
                "metric": "max_real_pole",
                "op": "<",
                "bound": {"value": 0, "unit": "1/s"},
                "composes": ["x"],
            },
            {
                "name": "b",
                "metric": "phase_margin",
                "op": ">=",
                "bound": {"value": 30, "unit": "deg"},
                "composes": ["y"],
            },
        ],
        "scorer": {"id": "control", "version": "1.1.0"},
    }
    return parse_task(json.dumps(task).encode())


def _setup(install_bin: Path, url: str, held: Path) -> RawSetup:
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
        held_out=(str(held),),
        held_out_canaries=("e" * 32,),
        network="none",
        os_layer=judge_here(claude_version=version, search_path=session_search_path(binary)),
    )


def _held(tmp_path: Path) -> Path:
    held = tmp_path / "private" / "heldout"
    held.mkdir(parents=True)
    (held / "scenario.json").write_text(json.dumps({"answer": HELD, "canary": "e" * 32}))
    return held


def test_a_raw_session_answers_on_its_brief_and_is_recorded(
    tmp_path: Path, install_bin: Path
) -> None:
    work = tmp_path / "work"
    held = _held(tmp_path)
    steps = [
        tool("Write", file_path=str(work / "worktree" / "answer.json"), content=json.dumps(ANSWER)),
        text("done"),
    ]
    with serving(Script(main=steps)) as (_, url):
        record = run_raw(_task(), _setup(install_bin, url, held), work, cap=10**9)  # type: ignore[arg-type]
    assert record["end"] == "ended" and record["answer"] == "found"
    assert json.loads((work / "answer" / "answer.json").read_text()) == ANSWER
    assert record["tokens"] > 0 and record["pins"]["tools"]
    assert json.loads((work / "raw.json").read_text())["task"] == "control.raw_probe"


@pytest.mark.parametrize(
    "step",
    [
        lambda held: tool("Read", file_path=str(held / "scenario.json")),
        lambda held: tool("Bash", command=f"cat {held}/scenario.json", description="x"),
    ],
    ids=["read tool", "shell"],
)
def test_a_raw_session_is_refused_the_held_out_tier(
    tmp_path: Path, install_bin: Path, step: object
) -> None:
    held = _held(tmp_path)
    work = tmp_path / "work"
    with serving(Script(main=[step(held), text("done")])) as (api, url):  # type: ignore[operator]
        record = run_raw(_task(), _setup(install_bin, url, held), work, cap=10**9)  # type: ignore[arg-type]
        told = " ".join(r.last_user for r in api.requests)
    assert HELD not in told
    assert HELD not in (work / "session" / "stdout.jsonl").read_text()
    assert record["held_out_seen"] is False


def test_the_token_cap_stops_a_raw_session_mid_command(tmp_path: Path, install_bin: Path) -> None:
    held = _held(tmp_path)
    work = tmp_path / "work"
    steps = [tool("Bash", command="sleep 30", description="x"), text("done")]
    began = time.monotonic()
    with serving(Script(main=steps)) as (_, url):
        record = run_raw(_task(), _setup(install_bin, url, held), work, cap=1)  # type: ignore[arg-type]
    assert record["end"] == "budget_exhausted"
    assert record["tokens"] > 1
    assert time.monotonic() - began < 25
