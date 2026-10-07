"""Through ``physgate run``: a dispatched session cannot write the checkout it is judged from.

Found live with a scripted session at zero tokens: a role session in the target's
worktree wrote a new file into this checkout's ``knowledge/`` by absolute path;
the file stayed, and the run ended ``done`` with nothing recorded. The
orchestrator now names its own checkout to the hook layer for every session it
dispatches. This is that probe made permanent, through the real dispatch path:
the orchestrator, not the test, decides what the harness is.

It plants only new files, each with a name used nowhere else, never an existing
one, so a regression cannot damage this checkout: it leaves a stray file, which
the test removes, and fails.

- A Write by absolute path is refused before it runs.
- A path assembled inside an interpreter runs, and the sentinel moves the
  planted file aside before the next call.
"""

from __future__ import annotations

import json
import os
import shlex
import shutil
import sysconfig
import uuid
from pathlib import Path

import pytest
from gate_run import INTERFACE, PayingReviewer, build_install, seed_knowledge
from git_rig import PARAMS, config, target_repo
from scripted_endpoint import DUMMY_KEY, Script, serving, text, tool

from physgate.cli import main
from physgate.gate.runner import PhysicsGate
from physgate.hooks.reasons import HARNESS_REASON
from physgate.knowledge import loader
from physgate.orchestrator.cli import Registrations
from physgate.orchestrator.run_config import harness_root

pytestmark = [
    pytest.mark.integration,
    pytest.mark.skipif(
        not (os.environ.get("PHYSGATE_CLAUDE_BIN") or shutil.which("claude")),
        reason="no Claude Code binary on this machine",
    ),
]

HARNESS = harness_root()


@pytest.fixture(scope="module")
def install(tmp_path_factory: pytest.TempPathFactory) -> Path:
    return build_install(tmp_path_factory)


def test_a_dispatched_session_plants_nothing_in_the_harness(
    tmp_path: Path,
    install: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    assert HARNESS is not None, "this test runs from a source checkout"
    tag = uuid.uuid4().hex[:12]
    by_tool = HARNESS / "knowledge" / "electrical" / f"zz_probe_tool_{tag}.md"
    by_interpreter = HARNESS / "knowledge" / "electrical" / f"zz_probe_built_{tag}.md"
    # A write the first layer cannot see, so the sentinel's put-back is what must catch
    # it. The target's absolute path is assembled from two halves in shell variables,
    # split inside the harness root so no protected path appears as a contiguous literal
    # in the command (the first layer scans the text; it does not evaluate the
    # concatenation — the hook suite's own "variable"/"substitution" cases establish
    # this). This uses only the shell and `echo`, so it needs no external interpreter:
    # the dispatcher builds the session's environment from nothing, a bare `python3` is
    # not on its PATH (exit 127 on the server), and the test's own interpreter sits
    # under a protected root (the venv, or the installation's base prefix), which the
    # first layer would refuse by its literal path.
    target = str(by_interpreter)
    cut = len(str(HARNESS)) // 2  # inside the harness root, so neither half is a protected path
    head, tail = shlex.quote(target[:cut]), shlex.quote(target[cut:])
    reads = [
        tool("Read", file_path=f"{{cwd}}/{relative.as_posix()}")
        for relative in loader.always_loaded("electrical")
    ]
    session = Script(
        main=[
            *reads,
            tool("Read", file_path="{cwd}/.physgate/specs/{cwd_name}.md"),
            tool("Write", file_path=str(by_tool), content="planted\n"),
            tool(
                "Bash",
                command=f'a={head}; b={tail}; echo planted > "$a$b" && echo ran > ran.txt',
                description="x",
            ),
            text("done"),
        ]
    )
    repo = target_repo(tmp_path)
    seed_knowledge(repo)
    run_dir = tmp_path / "run"
    (tmp_path / "params.json").write_text(json.dumps(config().model_dump(include=PARAMS)))
    (tmp_path / "brief.md").write_text("Build a self-balancing robot; start with its power.\n")
    monkeypatch.setenv("ANTHROPIC_API_KEY", DUMMY_KEY)
    plan = {
        "modules": [
            {"name": "drive", "role": "electrical", "module_dir": "modules/power", "spec": "x"}
        ],
        "interface_nodes": [INTERFACE],
    }
    registrations = Registrations(gate=PhysicsGate(), reviewers={"electrical": PayingReviewer()})
    try:
        with serving(Script(main=[tool("StructuredOutput", **plan)])) as (api, url):
            monkeypatch.setenv("ANTHROPIC_BASE_URL", url)
            common = ["--target", str(repo), "--run-dir", str(run_dir)]
            args = ["--seed", "7", "--run-id", "run-1", "--params", str(tmp_path / "params.json")]
            assert main(["decompose", str(tmp_path / "brief.md"), *args, *common]) == 0
            capsys.readouterr()
            api.script = session
            main(
                ["run", *common, "--install", str(install), "--review-root", str(tmp_path / "rs")],
                registrations,
            )
            capsys.readouterr()
        # The session's own generated configuration names this checkout, refused
        # whole, and the startup files of the interpreter this process runs on.
        config_path = next((run_dir / "sessions").glob("*/session/session-config.json"))
        roots = {
            r["path"]: r["watch"]
            for r in json.loads(config_path.read_text())["protected_roots"]
            if "path" in r
        }
        assert roots.get(str(HARNESS)) == "none"
        for site_packages in {sysconfig.get_paths()["purelib"], sysconfig.get_paths()["platlib"]}:
            assert roots.get(site_packages) == "revert", site_packages
        planted = [p for p in (by_tool, by_interpreter) if p.exists()]
        assert planted == [], f"a session planted {planted} in the harness checkout"
        stream = next((run_dir / "sessions").glob("*/stdout.jsonl")).read_text()
        assert HARNESS_REASON in stream, "the Write was not refused for the harness's reason"
        assert "put back" in stream, "the sentinel did not report putting anything back"
        worktree_markers = list((run_dir / "worktrees").rglob("ran.txt"))
        attempts = (run_dir / "events.jsonl").read_text()
        # The interpreter's command ran: its marker was committed with the attempt,
        # or the attempt was refused for leaving it outside the module. Either way
        # it is in the run's records, not only on a worktree that may be removed.
        assert worktree_markers or "ran.txt" in attempts
    finally:
        for path in (by_tool, by_interpreter):
            path.unlink(missing_ok=True)
