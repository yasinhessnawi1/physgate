"""No session of a measured run reads an earlier run made beside it under the store's run roots.

Two harness runs on one version, under one registered run root: run A has ended, run B is
dispatching. A's directory holds what a later session must never see: its recorded configuration
(every canary of the store, which the round looks for), its plan and specifications (written from
its held-out brief), its module's worktree with the answer, and its sessions' streams. Each is
asked of the three kinds of session that come after it: a role session of B, a raw baseline
session on B's task, and a reviewer of B's work.

Each session is installed through its own real installer command line (the dispatcher's, the raw
arm's, the reviewer's), and each read is judged at the layer that enforces it: the file tool's
hook decision, the shell's hook decision, and the OS layer's policy for a shell read. (The OS
layer itself is exercised on the real binary in CI's OS-layer job.) What the session's own run
gives it stays readable: its worktree.
"""

from __future__ import annotations

import contextlib
import dataclasses
import io
import json
import shutil
import subprocess
import sys
from collections.abc import Iterator
from dataclasses import dataclass
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest
from exposure_fixtures import StandInStore, stand_in_store, with_run_root

ORCHESTRATOR_TESTS = Path(__file__).resolve().parents[2] / "orchestrator"
if str(ORCHESTRATOR_TESTS) not in sys.path:
    sys.path.insert(0, str(ORCHESTRATOR_TESTS))

from baseline_fixtures import config, harness_run, setup_for  # noqa: E402
from orch_helpers import SCRIPTED_BOUNDS  # noqa: E402

from physgate.evaluation.per_role.arms import raw  # noqa: E402
from physgate.evaluation.tiers.exposure import run_roots  # noqa: E402
from physgate.evaluation.tiers.store import work_root  # noqa: E402
from physgate.hooks import cli as hooks_cli  # noqa: E402
from physgate.hooks import paths, shell_paths  # noqa: E402
from physgate.hooks import settings as hooks_settings  # noqa: E402
from physgate.hooks.config import SessionConfig  # noqa: E402
from physgate.hooks.settings import InstallRequest, build_config, current_installation  # noqa: E402
from physgate.hooks.shell import parse  # noqa: E402
from physgate.orchestrator import dispatch  # noqa: E402
from physgate.orchestrator.credentials import Credential  # noqa: E402
from physgate.orchestrator.dispatch import ClaudeDispatcher  # noqa: E402
from physgate.orchestrator.ports import SessionRequest  # noqa: E402
from physgate.oslayer.policy import sandbox_policy  # noqa: E402
from physgate.oslayer.session_temp import make_session_temp  # noqa: E402
from physgate.reviewers.packet import WORKTREE_NAME  # noqa: E402

#: What run A left that a later session must not read, by what it is.
READS = ("record", "specification", "answer", "stream")
ANSWER_MARK = "the answer run A gave"


@dataclass
class Siblings:
    made: StandInStore
    root: Path
    #: Run A's files, by what each is.
    a: dict[str, Path]
    b: Path
    task_b: Any


def _withheld(made: StandInStore) -> dict[str, Any]:
    """What a measured run on the store withholds beyond its held-out roots: its run roots, whole."""
    roots = run_roots(made.store, "control")
    return {"withheld_whole": [str(root) for root in roots]}


@pytest.fixture
def siblings(tmp_path: Path) -> Siblings:
    base = tmp_path.resolve()
    made = stand_in_store(base / "s")
    root = with_run_root(made, base / "runs")
    task_a, task_b = made.tasks["held_out"][:2]
    run_a = harness_run(root, task_a, made, **_withheld(made))
    spec = run_a / "decomposition" / "round-1" / "spec.md"
    spec.parent.mkdir(parents=True)
    spec.write_text(f"Specification written from the brief: {task_a.brief}\n")
    answer = run_a / "worktrees" / "m1" / "modules" / "m1" / task_a.answer.path
    answer.parent.mkdir(parents=True)
    answer.write_text(ANSWER_MARK + "\n")
    stream = run_a / "sessions" / "role-1" / "stdout.jsonl"
    stream.write_text(json.dumps({"type": "assistant", "text": ANSWER_MARK}) + "\n")
    files = dict(zip(READS, (run_a / "run.json", spec, answer, stream), strict=True))
    run_b = root / "run-b"
    (run_b / "worktrees" / "m1").mkdir(parents=True)
    (run_b / "run.json").write_text(config(task_b, made, **_withheld(made)).model_dump_json())
    return Siblings(made, root, files, run_b, task_b)


def _capture(monkeypatch: pytest.MonkeyPatch) -> list[list[str]]:
    """The installer's command lines, answered as the installer answers; nothing else runs."""
    seen: list[list[str]] = []

    def fake_run(argv: list[str], **_kw: Any) -> subprocess.CompletedProcess[str]:  # noqa: ANN401
        seen.append(list(argv))
        out = {"settings": "s", "config": "c", "spawn_args": [], "spawn_env": {}}
        return subprocess.CompletedProcess(argv, 0, json.dumps(out), "")

    monkeypatch.setattr(subprocess, "run", fake_run)
    return seen


def _temp() -> Path:
    """A session's own temporary directory, where the dispatcher makes one; removed after."""
    temp = make_session_temp()
    _LEFT.append(temp)
    return temp


#: The temporary directories the rows made, removed when each row ends.
_LEFT: list[Path] = []


@pytest.fixture(autouse=True)
def _remove_temps() -> Iterator[None]:
    yield
    while _LEFT:
        shutil.rmtree(_LEFT.pop(), ignore_errors=True)


def _installed(argv: list[str], monkeypatch: pytest.MonkeyPatch) -> SessionConfig:
    """The session configuration the real installer writes for ``argv``, run in this process."""
    monkeypatch.undo()
    # The rows' trees lie in pytest's temporary directories, which the OS layer makes writable:
    # no session runs here, so where the worktree lies is not what is asked.
    monkeypatch.setattr(hooks_settings, "machine_writable", lambda: ())
    words = argv[argv.index("hooks") :]
    printed = io.StringIO()
    with contextlib.redirect_stdout(printed):
        assert hooks_cli.main(words) == 0, "the installer refused the session"
    path = Path(json.loads(printed.getvalue())["config"])
    return SessionConfig.model_validate_json(path.read_bytes())


def _role_session(siblings: Siblings, monkeypatch: pytest.MonkeyPatch, tmp: Path) -> SessionConfig:
    """A role session of run B, installed as the dispatcher installs one inside the OS layer."""
    run_b = siblings.b
    seen = _capture(monkeypatch)
    monkeypatch.setattr(dispatch, "session_protected_roots", lambda *_a: ((), ()))
    monkeypatch.setattr(dispatch, "harness_protection", lambda: [])
    dispatcher = ClaudeDispatcher(
        config=config(siblings.task_b, siblings.made, **_withheld(siblings.made)),
        run=SimpleNamespace(  # type: ignore[arg-type]
            subtask_branch=lambda subtask, _reopen=0: f"b/{subtask}", run_dir=run_b
        ),
        store_root=tmp / "graph",
        install_bin=tmp / "install" / "bin" / "physgate",
        binary="claude",
        base_url=None,
        credential=Credential(mode="api_key", secret="not-a-key"),
        review_root=tmp / "reviews",
    )
    request = SessionRequest(
        subtask_id="m1",
        attempt=1,
        assigned_role="control",
        spec_path=".physgate/specs/m1.md",
        module_dir="modules/m1",
        model="claude-opus-5-5",
        repair_instruction=None,
        bounds=SCRIPTED_BOUNDS,
    )
    temp = _temp()
    dispatcher._install(
        request, run_b / "worktrees" / "m1", run_b / "sessions" / "s-b", temp, own_temp=temp
    )
    (argv,) = [a for a in seen if a[1:3] == ["hooks", "install"]]
    return _installed(argv, monkeypatch)


def _raw_session(siblings: Siblings, monkeypatch: pytest.MonkeyPatch, tmp: Path) -> SessionConfig:
    """A raw session on B's task, in a protected trial's place in the work root."""
    made = siblings.made
    place = work_root(made.store, "control") / "baseline-r-0000-1" / "place"
    (place / "worktree").mkdir(parents=True)
    (place.parent / "harness").mkdir()
    out = tmp / "round"
    out.mkdir()
    harness = config(siblings.task_b, made, **_withheld(made))
    setup = dataclasses.replace(
        setup_for(harness, "control"),
        install_bin=tmp / "install" / "bin" / "physgate",
        held_out_carved=str(place),
        held_out_also=(str(out),),
    )
    seen = _capture(monkeypatch)
    temp = _temp()
    raw._install(setup, place / "worktree", place / "session", temp)
    (argv,) = [a for a in seen if a[1:3] == ["hooks", "install"]]
    return _installed(argv, monkeypatch)


def _refused_on_every_layer(config: SessionConfig, target: Path, home: Path) -> list[str]:
    """Each layer that lets the session read ``target``: empty when every layer refuses it."""
    wt = config.worktree
    let: list[str] = []
    if paths.protection(str(target), wt, config, writing=False) is None:
        let.append("the file tool")
    if not shell_paths.check(parse(f"cat {target}")[0], wt, config):
        let.append("the shell's hooks")
    policy = sandbox_policy(config, home=str(home), temp_dir="/tmp/pg-sibling")
    deny = policy.settings["sandbox"]["filesystem"]["denyRead"]
    allow = policy.settings["sandbox"]["filesystem"]["allowRead"]

    def under(path: str, roots: list[str]) -> bool:
        return any(path == r.rstrip("/") or path.startswith(r.rstrip("/") + "/") for r in roots)

    if not under(str(target), deny) or under(str(target), allow):
        let.append("the OS layer's policy")
    return let


@pytest.mark.parametrize("what", READS)
def test_a_role_session_of_a_later_run_reads_nothing_of_an_earlier_run(
    siblings: Siblings, monkeypatch: pytest.MonkeyPatch, tmp_path: Path, what: str
) -> None:
    session = _role_session(siblings, monkeypatch, tmp_path.resolve())
    home = siblings.b / "sessions" / "s-b" / "home"
    let = _refused_on_every_layer(session, siblings.a[what], home)
    assert let == [], f"a role session of run B reads run A's {what} through {', '.join(let)}"


@pytest.mark.parametrize("what", READS)
def test_a_raw_session_reads_nothing_of_a_harness_run_on_the_store(
    siblings: Siblings, monkeypatch: pytest.MonkeyPatch, tmp_path: Path, what: str
) -> None:
    session = _raw_session(siblings, monkeypatch, tmp_path.resolve())
    home = Path(session.worktree).parent / "session" / "home"
    let = _refused_on_every_layer(session, siblings.a[what], home)
    assert let == [], f"a raw session reads harness run A's {what} through {', '.join(let)}"


def test_a_role_session_still_reads_and_writes_its_own_worktree(
    siblings: Siblings, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    session = _role_session(siblings, monkeypatch, tmp_path.resolve())
    own = Path(session.worktree) / "modules" / "m1" / "controller.py"
    assert paths.protection(str(own), session.worktree, session, writing=False) is None
    assert paths.protection(str(own), session.worktree, session, writing=True) is None


@pytest.mark.parametrize("what", READS)
def test_a_reviewer_of_a_later_run_reads_nothing_of_an_earlier_run_by_its_allowance(
    siblings: Siblings, tmp_path: Path, what: str
) -> None:
    """Green before the change too: a reviewer reads only beneath its packet, and runs no shell."""
    base = tmp_path.resolve()
    read = base / "reviews" / "rv-1" / "read"
    sdir = base / "reviews" / "rv-1" / "session"
    for d in (read / WORKTREE_NAME, sdir / "state", sdir / "settings", sdir / "config"):
        d.mkdir(parents=True)
    harness = config(siblings.task_b, siblings.made, **_withheld(siblings.made))
    # As the reviewer's installer is given it (``reviewers.claude``): its read root, the run's
    # held-out roots, and nothing of the run's directory.
    request = InstallRequest(
        profile="reviewer",
        role=None,
        worktree=str(read / WORKTREE_NAME),
        own_branch=None,
        store_root=None,
        state_dir=str(sdir / "state"),
        target_dir=str(sdir / "settings"),
        claude_config_dir=str(sdir / "config"),
        user_home=str(sdir / "home"),
        token_ceiling=40960,
        read_roots=(str(read),),
        held_out=tuple(harness.held_out),
    )
    session = build_config(request, current_installation())
    target = str(siblings.a[what])
    assert paths.protection(target, session.worktree, session, writing=False) is not None
