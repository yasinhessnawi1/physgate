"""A later trial's sessions reach nothing an earlier trial of the round left.

A round's trials are runs beside one another beneath one registered run root. An earlier trial's
run directory holds its configuration (every canary of the store), its specification (written from
its task's brief), its answer and its sessions' streams. So a session that comes after it must be
refused a read of each, by every layer that enforces a read: a role session of a later trial, a
raw baseline session on a later trial's task, and a reviewer of a later trial's work. A measured
run withholds every registered run root of the stores it names, whole, and its session reaches only
its own worktree there.

The sessions are installed as their installers are given them: the role session through the
dispatcher's own install command line, the raw session through the raw arm's, both run in this
process; the reviewer's request is built as its installer is given it. Each read is judged at the
file tool's hook, the shell's hook (a ``cat``), and the OS layer's policy for a shell read. A raw
session withheld a root whole is installed only with the OS layer: given none, the installer
refuses it. A reviewer reads only beneath its packet.
"""

from __future__ import annotations

import contextlib
import dataclasses
import io
import json
import shutil
import subprocess
from collections.abc import Iterator
from pathlib import Path
from typing import Any

import pytest
from round_rig import SCORED, Rig, make_rig, setup_for

from physgate.evaluation.harness_round import (
    HARNESS_ROUNDS,
    ROUND_RECORD,
    RoundError,
    run_round,
)
from physgate.evaluation.per_role.arms import raw
from physgate.evaluation.tiers.store import withheld_root, work_root
from physgate.hooks import cli as hooks_cli
from physgate.hooks import paths, shell_paths
from physgate.hooks import settings as hooks_settings
from physgate.hooks.config import SessionConfig
from physgate.hooks.settings import InstallRequest, build_config, current_installation
from physgate.hooks.shell import parse
from physgate.orchestrator import dispatch
from physgate.orchestrator.credentials import Credential
from physgate.orchestrator.dispatch import ClaudeDispatcher
from physgate.orchestrator.events import Decomposed, SubtaskPlanned, read_events
from physgate.orchestrator.merge import RunGit
from physgate.orchestrator.ports import SessionRequest
from physgate.orchestrator.run_config import load_run_config
from physgate.oslayer.policy import sandbox_policy
from physgate.oslayer.session_temp import make_session_temp
from physgate.reviewers.packet import WORKTREE_NAME

#: What the earlier trial left that a later session must not read, by what it is.
READS = ("configuration", "specification", "answer", "stream")


def _score(_task: Any, _answer: Path) -> dict[str, Any]:  # noqa: ANN401
    return dict(SCORED)


@dataclasses.dataclass(frozen=True)
class Trials:
    rig: Rig
    #: The first trial's files, by what each is.
    first: dict[str, Path]
    second: Path


@pytest.fixture(scope="module")
def trials(tmp_path_factory: pytest.TempPathFactory) -> Trials:
    """A visible round of two trials of one task: the first ended, the second's run beside it."""
    rig = make_rig(tmp_path_factory.mktemp("siblings"))
    status, summary = run_round(
        rig.inputs(tiers=("visible",), trials=2, tasks=1),
        driver=rig.driver(),
        scorer=_score,
        sleep=lambda _: None,
    )
    assert status == "done"
    place = withheld_root(rig.made.store, "control") / HARNESS_ROUNDS / summary["round"]
    record = json.loads((place / ROUND_RECORD).read_bytes())
    first, second = (Path(t["run_dir"]) for t in record["trials"])
    planned = next(e for e in read_events(first / "events.jsonl") if isinstance(e, SubtaskPlanned))
    merged = first / "worktrees" / "_integration"
    streams = sorted((first / "sessions").glob("*/stdout.jsonl"))
    streams += sorted((first / "decomposition").rglob("stdout.jsonl"))
    reached = {
        "configuration": first / "run.json",
        "specification": merged / planned.spec_path,
        # The run branch as merged, checked out in the orchestrator's own worktree.
        "answer": merged / planned.module_dir / rig.task().answer.path,
        "stream": streams[0] if streams else first / "sessions" / "none" / "stdout.jsonl",
    }
    # The rig, proven before any assertion a mark waits on: a failure here is no wait.
    for name, path in reached.items():
        if not path.is_file():
            pytest.fail(f"the first trial left no {name} at the path the row asks about")
    return Trials(rig, reached, second)


#: The temporary directories the rows made, removed when each row ends.
_LEFT: list[Path] = []


@pytest.fixture(autouse=True)
def _remove_temps() -> Iterator[None]:
    yield
    while _LEFT:
        shutil.rmtree(_LEFT.pop(), ignore_errors=True)


def _temp() -> Path:
    temp = make_session_temp()
    _LEFT.append(temp)
    return temp


def _capture(monkeypatch: pytest.MonkeyPatch) -> list[list[str]]:
    """The installer's command lines, answered as the installer answers; nothing else runs."""
    seen: list[list[str]] = []
    real_run = subprocess.run

    def fake_run(argv: list[str], **kw: Any) -> Any:  # noqa: ANN401
        if list(argv[1:3]) != ["hooks", "install"]:
            return real_run(argv, **kw)  # every other command (git among them) runs as it does
        seen.append(list(argv))
        out = {"settings": "s", "config": "c", "spawn_args": [], "spawn_env": {}}
        return subprocess.CompletedProcess(argv, 0, json.dumps(out), "")

    monkeypatch.setattr(subprocess, "run", fake_run)
    return seen


def _installed(argv: list[str], monkeypatch: pytest.MonkeyPatch) -> SessionConfig:
    """The session configuration the real installer writes for ``argv``, run in this process."""
    monkeypatch.undo()
    # The rows' trees lie in pytest's temporary directories, which the OS layer makes writable:
    # no session runs here, so where the worktree lies is not what is asked.
    monkeypatch.setattr(hooks_settings, "machine_writable", lambda: ())
    words = argv[argv.index("hooks") :]
    printed = io.StringIO()
    with contextlib.redirect_stdout(printed):
        if hooks_cli.main(words) != 0:
            pytest.fail("the installer refused the session")
    path = Path(json.loads(printed.getvalue())["config"])
    return SessionConfig.model_validate_json(path.read_bytes())


def _role_session(trials: Trials, monkeypatch: pytest.MonkeyPatch, name: str) -> SessionConfig:
    """The second trial's role session ``name``, installed as the dispatcher installs one."""
    run_dir = trials.second
    config = load_run_config(run_dir / "run.json")
    events = read_events(run_dir / "events.jsonl")
    (planned,) = [e for e in events if isinstance(e, SubtaskPlanned)]
    (decomposed,) = [e for e in events if isinstance(e, Decomposed)]
    run = RunGit(repo=run_dir / "target", run_dir=run_dir, run_id=config.run_id)
    worktree = run.open_subtask(planned.subtask_id)
    seen = _capture(monkeypatch)
    monkeypatch.setattr(dispatch, "session_protected_roots", lambda *_a: ((), ()))
    monkeypatch.setattr(dispatch, "harness_protection", lambda: [])
    dispatcher = ClaudeDispatcher(
        config=config,
        run=run,
        store_root=run_dir / "store",
        install_bin=run_dir.parent / "install" / "bin" / "physgate",
        binary="claude",
        base_url=None,
        credential=Credential(mode="api_key", secret="not-a-key"),
        review_root=run_dir / "review",
    )
    request = SessionRequest(
        subtask_id=planned.subtask_id,
        attempt=2,
        assigned_role="control",
        spec_path=planned.spec_path,
        module_dir=planned.module_dir,
        model=config.models.roles["control"],
        repair_instruction=None,
        bounds=config.bounds,
        spec_commit=decomposed.spec_commit,
    )
    temp = _temp()
    dispatcher._install(request, worktree, run_dir / "sessions" / name, temp, own_temp=temp)  # noqa: SLF001
    (argv,) = [a for a in seen if a[1:3] == ["hooks", "install"]]
    return _installed(argv, monkeypatch)


def _raw_argv(
    trials: Trials, monkeypatch: pytest.MonkeyPatch, tmp: Path, *, layer: bool
) -> tuple[list[str], Path]:
    """The installer's command line for a raw session on the second trial's task, and its place.

    ``layer``: the session is given the OS layer's temporary directory, as the raw arm gives it
    where the layer is present.
    """
    made = trials.rig.made
    place = work_root(made.store, "control") / f"baseline-{tmp.name}-0001-1" / "place"
    (place / "worktree").mkdir(parents=True)
    (place.parent / "harness").mkdir()
    out = tmp / "round"
    out.mkdir()
    setup = dataclasses.replace(
        setup_for(load_run_config(trials.second / "run.json"), "control"),
        install_bin=tmp / "install" / "bin" / "physgate",
        held_out_carved=str(place),
        held_out_also=(str(out),),
    )
    seen = _capture(monkeypatch)
    temp = _temp() if layer else None
    raw._install(setup, place / "worktree", place / "session", temp)  # noqa: SLF001
    (argv,) = [a for a in seen if a[1:3] == ["hooks", "install"]]
    return argv, place.parent


def _raw_session(trials: Trials, monkeypatch: pytest.MonkeyPatch, tmp: Path) -> SessionConfig:
    """A raw session on the second trial's task, in a trial's place in the work root."""
    argv, place = _raw_argv(trials, monkeypatch, tmp, layer=True)
    try:
        return _installed(argv, monkeypatch)
    finally:
        shutil.rmtree(place, ignore_errors=True)


def _let_through(config: SessionConfig, target: Path, home: Path) -> list[str]:
    """Each layer that lets the session read ``target``: empty when every layer refuses it."""
    wt = config.worktree
    let: list[str] = []
    if paths.protection(str(target), wt, config, writing=False) is None:
        let.append("the file tool")
    if not shell_paths.check(parse(f"cat {target}")[0], wt, config):
        let.append("the shell's hooks")
    policy = sandbox_policy(config, home=str(home), temp_dir="/var/tmp/pgs/0123456789")
    deny = policy.settings["sandbox"]["filesystem"]["denyRead"]
    allow = policy.settings["sandbox"]["filesystem"]["allowRead"]

    def under(path: str, roots: list[str]) -> bool:
        return any(path == r.rstrip("/") or path.startswith(r.rstrip("/") + "/") for r in roots)

    if not under(str(target), deny) or under(str(target), allow):
        let.append("the OS layer's policy")
    return let


@pytest.mark.parametrize("what", READS)
def test_the_second_trial_s_role_session_reads_nothing_the_first_trial_left(
    trials: Trials, monkeypatch: pytest.MonkeyPatch, what: str
) -> None:
    session = _role_session(trials, monkeypatch, f"later-{what}")
    # The configuration built is the session's: its own run's record it may not read.
    own = trials.second / "run.json"
    if paths.protection(str(own), session.worktree, session, writing=False) is None:
        pytest.fail("the session as installed here may read its own run's configuration")
    home = trials.second / "sessions" / f"later-{what}" / "home"
    let = _let_through(session, trials.first[what], home)
    assert let == [], f"the later trial's role session reads the earlier's {what} through {let}"


@pytest.mark.parametrize("what", READS)
def test_a_raw_session_on_the_second_trial_s_task_reads_nothing_the_first_trial_left(
    trials: Trials, monkeypatch: pytest.MonkeyPatch, tmp_path: Path, what: str
) -> None:
    session = _raw_session(trials, monkeypatch, tmp_path.resolve())
    home = Path(session.worktree).parent / "session" / "home"
    let = _let_through(session, trials.first[what], home)
    assert let == [], f"a raw session reads the harness trial's {what} through {let}"


def test_a_raw_session_on_the_second_trial_s_task_is_not_installed_without_the_os_layer(
    trials: Trials,
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    """The hooks alone do not hold a root whole against a path a command builds as it runs."""
    argv, place = _raw_argv(trials, monkeypatch, tmp_path.resolve(), layer=False)
    try:
        assert "--withheld-whole" in argv and "--os-layer-temp" not in argv
        monkeypatch.undo()
        monkeypatch.setattr(hooks_settings, "machine_writable", lambda: ())
        try:
            code: int | str = hooks_cli.main(argv[argv.index("hooks") :])
        except Exception as exc:  # noqa: BLE001 - what the installer did instead is the failure
            code = f"raised {type(exc).__name__}"
    finally:
        shutil.rmtree(place, ignore_errors=True)
    said = capsys.readouterr()
    # Refused, with nothing written: no configuration's path is printed for the client to load.
    assert code == 2, code
    assert said.out == ""
    assert "installed only with the OS layer" in json.loads(said.err)["error"]


@pytest.mark.parametrize("what", READS)
def test_a_reviewer_of_the_second_trial_reads_nothing_the_first_trial_left(
    trials: Trials, tmp_path: Path, what: str
) -> None:
    """Holds today: a reviewer reads only beneath its packet, and runs no shell."""
    base = tmp_path.resolve()
    read = base / "reviews" / "rv-1" / "read"
    sdir = base / "reviews" / "rv-1" / "session"
    for d in (read / WORKTREE_NAME, sdir / "state", sdir / "settings", sdir / "config"):
        d.mkdir(parents=True)
    config = load_run_config(trials.second / "run.json")
    # As the reviewer's installer is given it: its read root, the run's held-out roots, and
    # nothing of the run's directory.
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
        held_out=tuple(config.held_out),
    )
    session = build_config(request, current_installation())
    target = str(trials.first[what])
    assert paths.protection(target, session.worktree, session, writing=False) is not None


def test_a_protected_tier_whose_parameters_withhold_every_run_root_whole_is_run(
    tmp_path: Path,
) -> None:
    rig = make_rig(tmp_path)
    try:
        status, summary = run_round(
            rig.inputs(tiers=("held_out",), trials=2, tasks=1),
            driver=rig.driver(),
            scorer=_score,
            sleep=lambda _: None,
        )
    except RoundError as exc:
        reason = exc.context.get("refused_because")
        assert reason is None, f"a protected tier withheld as the core asks was refused: {reason}"
        raise
    assert status == "done" and summary["tiers"]["held_out"]["assembled"] == 2


def test_a_protected_tier_whose_parameters_leave_a_run_root_out_is_refused_by_the_core_s_rule(
    tmp_path: Path,
) -> None:
    rig = make_rig(tmp_path, withheld_whole=[])
    driver = rig.driver()
    with pytest.raises(RoundError) as refused:
        run_round(
            rig.inputs(tiers=("held_out",), trials=1, tasks=1),
            driver=driver,
            scorer=_score,
            sleep=lambda _: None,
        )
    assert refused.value.context.get("refused_because") == "run_root_not_withheld"
    assert driver.decomposed == [] and not (rig.root / "out").exists()
