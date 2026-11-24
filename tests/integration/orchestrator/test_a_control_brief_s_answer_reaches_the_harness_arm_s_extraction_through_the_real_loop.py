"""A single-role brief's answer reaches the harness arm's extraction through the real loop.

``physgate decompose`` on a control task's brief, then ``physgate run``, with the real binary
against the scripted endpoint and no model called: the plan gives the one control module a
directory directly under ``modules/``, its session reads its required reading and writes the
answer file of the task's answer contract in its module's directory, the review passes, the
attempt merges, and the run ends as the loop's rules end it (a control module owes its
stability-margin sign-off after the merge, which a run that records decisions leaves open). The
harness arm's extraction then reads the answer from the run branch: ``found``, its bytes the
session wrote.

The other row is the same run with the plan's module directory in another layout (not directly
under ``modules/``): the session writes the answer where it is told to, the attempt merges, and
the extraction finds no answer file (``contract_lost``), the harness's own fail. Nothing is
changed here to read it; what that layout costs is said in the row.
"""

from __future__ import annotations

import json
import os
import shutil
import sys
from pathlib import Path
from typing import Any

import pytest
from gate_run import INTERFACE, build_install
from git_rig import Gate, Reviewer, config, run_params, target_repo
from knowledge_fixture import build_fixture_library, fixture_text
from scripted_endpoint import DUMMY_KEY, Script, serving, text, tool

PER_ROLE_TESTS = Path(__file__).resolve().parents[2] / "unit" / "evaluation" / "per_role"
if str(PER_ROLE_TESTS) not in sys.path:
    sys.path.insert(0, str(PER_ROLE_TESTS))

from task_fixtures import controller, own_task  # noqa: E402

from physgate.cli import main  # noqa: E402
from physgate.evaluation.per_role.arms.compare import ENDED_STEPS, harness_total  # noqa: E402
from physgate.evaluation.per_role.arms.harness import extract  # noqa: E402
from physgate.evaluation.tiers.task import parse_task  # noqa: E402
from physgate.knowledge import loader  # noqa: E402
from physgate.orchestrator.cli import Registrations  # noqa: E402
from physgate.orchestrator.git import commit_all  # noqa: E402
from physgate.orchestrator.run_config import ModelStrings  # noqa: E402

pytestmark = [
    pytest.mark.integration,
    pytest.mark.skipif(
        not (os.environ.get("PHYSGATE_CLAUDE_BIN") or shutil.which("claude")),
        reason="no Claude Code binary on this machine",
    ),
]

TASK = parse_task(json.dumps(own_task()).encode())
#: The plan's interface node, owned by the run's one role: a node of a role no module has is
#: refused as a plan.
INTERFACE_NODE: dict[str, Any] = {
    **INTERFACE,
    "domain": "control",
    "owner_role": "control",
    "quantities": {
        name: {**quantity, "written_by": "control"}
        for name, quantity in INTERFACE["quantities"].items()
    },
}
ANSWER = json.dumps(controller())


@pytest.fixture(scope="module")
def install(tmp_path_factory: pytest.TempPathFactory) -> Path:
    return build_install(tmp_path_factory)


def _run(
    tmp_path: Path,
    install: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    module_dir: str,
) -> tuple[Path, Path, dict[str, Any]]:
    """Decompose and run the control brief with its module at ``module_dir``; what it printed."""
    library = build_fixture_library(tmp_path / "lib")
    monkeypatch.setattr("physgate.orchestrator.cli._library_root", lambda: library)
    repo = target_repo(tmp_path)
    reading = loader.always_loaded("control")
    for relative in reading:
        (repo / relative).parent.mkdir(parents=True, exist_ok=True)
        (repo / relative).write_text(fixture_text(relative))
    commit_all(repo, "curated knowledge fixture\n")
    models = ModelStrings(
        decomposition="claude-sonnet-5",
        roles={"control": "claude-sonnet-5"},
        reviewers={"control": "claude-opus-5-5"},
    )
    params = run_params(config().model_copy(update={"models": models}))
    (tmp_path / "params.json").write_text(json.dumps(params))
    (tmp_path / "brief.md").write_bytes(TASK.brief.encode())
    monkeypatch.setenv("ANTHROPIC_API_KEY", DUMMY_KEY)
    spec = f"Design the controller the brief asks for. {TASK.brief}"
    plan = {
        "modules": [{"name": "ctl", "role": "control", "module_dir": module_dir, "spec": spec}],
        "interface_nodes": [INTERFACE_NODE],
    }
    session = Script(
        main=[
            *(tool("Read", file_path=f"{{cwd}}/{r.as_posix()}") for r in reading),
            tool("Read", file_path="{cwd}/.physgate/specs/{cwd_name}.md"),
            tool("Read", file_path=f"{{cwd}}/.physgate/interfaces/{INTERFACE['id']}.json"),
            tool("Write", file_path=f"{{cwd}}/{module_dir}/{TASK.answer.path}", content=ANSWER),
            text("done"),
        ]
    )
    run_dir = tmp_path / "run"
    with serving(Script(main=[tool("StructuredOutput", **plan)])) as (api, url):
        monkeypatch.setenv("ANTHROPIC_BASE_URL", url)
        args = ["--seed", "7", "--run-id", "run-1", "--params", str(tmp_path / "params.json")]
        where = ["--target", str(repo), "--run-dir", str(run_dir)]
        assert main(["decompose", str(tmp_path / "brief.md"), *args, *where]) == 0
        capsys.readouterr()
        api.script = session
        common = [*where, "--install", str(install), "--review-root", str(tmp_path / "rs")]
        registrations = Registrations(gate=Gate(), reviewers={"control": Reviewer()})
        main(["run", *common], registrations)
        out = capsys.readouterr()
    printed = json.loads(out.out) if out.out.strip() else {"error": out.err}
    assert "error" not in printed, out.err
    return repo, run_dir, printed


def test_a_control_brief_s_answer_is_found_on_the_run_branch_where_the_harness_arm_reads_it(
    tmp_path: Path,
    install: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    repo, run_dir, printed = _run(tmp_path, install, monkeypatch, capsys, "modules/ctl")
    # Merged, and ended as the loop's rules end such a run: nothing left for it to do.
    assert printed["subtasks"] and set(printed["subtasks"].values()) == {"done"}, printed
    assert printed["step"] in ENDED_STEPS, printed
    got = extract(repo, "run-1", TASK.answer.path, tmp_path / "answer" / TASK.answer.path)
    assert got.status == "found", got
    assert got.paths == (f"modules/ctl/{TASK.answer.path}",)
    assert (tmp_path / "answer" / TASK.answer.path).read_text() == ANSWER
    # And the run gives the raw arm its cap.
    assert harness_total(run_dir) > 0


def test_a_module_directory_in_another_layout_leaves_the_answer_where_the_arm_never_reads(
    tmp_path: Path,
    install: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    """Reported, not changed: the plan check takes this layout, and the extraction finds nothing.

    The planner is asked for ``modules/<name>`` and nothing holds it to that form, so a plan
    whose module lies elsewhere runs as any other, and its answer, written where the session is
    told to write, is not where the extraction looks (directly inside a ``modules/`` directory).
    The trial counts as the harness's own fail.
    """
    repo, _, printed = _run(tmp_path, install, monkeypatch, capsys, "control/ctl")
    assert printed["subtasks"] and set(printed["subtasks"].values()) == {"done"}, printed
    got = extract(repo, "run-1", TASK.answer.path, tmp_path / "answer" / TASK.answer.path)
    assert got.status == "contract_lost", got
    assert not (tmp_path / "answer").exists()
