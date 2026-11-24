"""No later session reads what an earlier harness trial's reviews left under its review root.

A trial's reviews run under its review root, and leave three things there:
- each review's packet: the brief, the specification and the answer, protected for a held-out
  task;
- each reviewer's own session directory, with its sentinel's record;
- the place apart beside them, holding the key that maps every label back and the protected part
  of each reviewer's record.

Three kinds of session run afterwards, on the same machine as the same user: a later trial's
role session, a later trial's reviewer, and a raw baseline session of the same round. Each is
asked of each thing. A review root can lie inside the trial's own run directory, which lies in a
run root (where the round driver puts it), or outside the run roots: the standing root, which a
run made by hand can name, alone or shared with the later trial.

A measured run reviews only inside its own run directory, which lies in a run root withheld
whole from every later session. So:
- the requirement refuses any other review root;
- a baseline round refuses a harness run that recorded any other;
- a raw session is also withheld the harness run's recorded review root and the standing one.

A reviewer reads only its own review's packet, by its allowance; it was refused before the
change as after. Each read is judged at the layer that enforces it: the file tool's hook
decision, the shell's hook decision, and the OS layer's policy.
"""

from __future__ import annotations

import contextlib
import dataclasses
import io
import json
import os
import shutil
import subprocess
import sys
from collections.abc import Iterator
from dataclasses import dataclass
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest
from exposure_fixtures import LAYER, StandInStore, stand_in_store, with_run_root

ORCHESTRATOR_TESTS = Path(__file__).resolve().parents[2] / "orchestrator"
if str(ORCHESTRATOR_TESTS) not in sys.path:
    sys.path.insert(0, str(ORCHESTRATOR_TESTS))

from baseline_fixtures import (  # noqa: E402
    PRICES,
    SCORED,
    StandInArm,
    config,
    harness_run,
    run_set,
    setup_for,
)
from orch_helpers import SCRIPTED_BOUNDS  # noqa: E402

from physgate.evaluation import requirements  # noqa: E402
from physgate.evaluation.baseline.runner import BaselineError, run_baseline  # noqa: E402
from physgate.evaluation.observe.cost import load_price_sheet  # noqa: E402
from physgate.evaluation.per_role.arms import raw  # noqa: E402
from physgate.evaluation.per_role.arms.raw import RawSetup  # noqa: E402
from physgate.evaluation.per_role.exceptions import PerRoleError  # noqa: E402
from physgate.evaluation.tiers.exposure import run_roots  # noqa: E402
from physgate.evaluation.tiers.task import Task  # noqa: E402
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
from physgate.orchestrator.requirements import RunFacts  # noqa: E402
from physgate.orchestrator.review_root_record import record_review_root  # noqa: E402
from physgate.oslayer.policy import sandbox_policy  # noqa: E402
from physgate.oslayer.session_temp import make_session_temp  # noqa: E402
from physgate.reviewers.packet import WORKTREE_NAME  # noqa: E402
from physgate.reviewers.places import READ_DIRNAME, SESSION_DIRNAME, standing_root  # noqa: E402

#: Where the earlier trial's review root lies, and the later trial's beside it: each in its own
#: run (the round driver's layout), the earlier one outside the run roots and the later in its run,
#: or one root outside the run roots shared by both (the standing root, named by hand for each).
PLACEMENTS = ("in its run", "outside the run roots", "shared outside the run roots")
#: What an earlier trial's reviews left under its review root, by what each is.
THINGS = ("packet's brief", "packet's answer", "reviewer's record", "label key", "protected record")
#: Where a reviewer's place apart lies under its review root, as its installer makes it.
APART = "sentinel-apart"
ANSWER_MARK = "the answer the earlier trial gave"
REVIEW_A, REVIEW_B = (
    "0f1e2d3c-4b5a-6978-8796-a5b4c3d2e1f0",
    "1a2b3c4d-5e6f-4789-8abc-def012345678",
)
SID = "2b3c4d5e-6f70-4819-9abc-def012345679"


@dataclass
class Trials:
    made: StandInStore
    #: The earlier trial's run directory, its review root, and what its reviews left there.
    a: Path
    review_a: Path
    left: dict[str, Path]
    #: The later trial's run directory and review root.
    b: Path
    review_b: Path
    task_b: Task


def _withheld(made: StandInStore) -> dict[str, Any]:
    return {"withheld_whole": [str(root) for root in run_roots(made.store, "control")]}


def _leave_reviews(root: Path, review: str, task: Task) -> dict[str, Path]:
    """What a review leaves under ``root``, as the reviewer's installer and sentinel lay it out."""
    read = root / review / READ_DIRNAME
    brief = read / "brief.md"
    answer = read / WORKTREE_NAME / "modules" / "m1" / task.answer.path
    record = root / review / SESSION_DIRNAME / "state" / "sessions" / SID / "sentinel"
    record = record / "baseline.json"
    key, kept = root / APART / "labels.key", root / APART / f"{SID}.json"
    for path, body in (
        (brief, task.brief),
        (answer, ANSWER_MARK),
        (record, json.dumps({"hidden": [task.id]})),
        (key, "0" * 64),
        (kept, json.dumps({"hidden": [task.id]})),
    ):
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(body + "\n")
    return dict(zip(THINGS, (brief, answer, record, key, kept), strict=True))


def _trials(base: Path, placement: str, *, later: bool = True) -> Trials:
    """Two trials of one round under one run root; the earlier one ended and was reviewed."""
    made = stand_in_store(base / "s")
    runs = with_run_root(made, base / "runs")
    task_a, task_b = made.tasks["held_out"][:2]
    run_a = harness_run(runs, task_a, made, **_withheld(made))
    review_a = run_a / "review" if placement == "in its run" else base / "review-scratch"
    left = _leave_reviews(review_a, REVIEW_A, task_a)
    record_review_root(run_a, review_a)
    run_b = runs / "run-b"
    if later:
        (run_b / "worktrees" / "m1").mkdir(parents=True)
        (run_b / "run.json").write_text(config(task_b, made, **_withheld(made)).model_dump_json())
    review_b = review_a if placement.startswith("shared") else run_b / "review"
    return Trials(made, run_a, review_a, left, run_b, review_b, task_b)


def _admitted(trials: Trials) -> bool:
    """Whether the measured-run rule lets the earlier trial review under its review root.

    It is asked as the command asks it at the trial's ``run``, shown the review root it names.
    Where a requirement is shown no review root, as before the change, nothing refuses one.
    """
    harness = config(trials.task_b, trials.made, **_withheld(trials.made))
    shown = {f.name for f in dataclasses.fields(RunFacts)}
    given = {"review_root": trials.review_a} if "review_root" in shown else {}
    facts = RunFacts(config=harness, os_layer=LAYER, shell_sessions=True, run_dir=trials.a, **given)
    return requirements.a_measured_run_withholds_every_run_root_whole(facts) is None


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


def _capture(mp: pytest.MonkeyPatch) -> list[list[str]]:
    """The installer's command lines, answered as the installer answers; nothing else runs."""
    seen: list[list[str]] = []

    def fake_run(argv: list[str], **_kw: Any) -> subprocess.CompletedProcess[str]:  # noqa: ANN401
        seen.append(list(argv))
        out = {"settings": "s", "config": "c", "spawn_args": [], "spawn_env": {}}
        return subprocess.CompletedProcess(argv, 0, json.dumps(out), "")

    mp.setattr(subprocess, "run", fake_run)
    return seen


def _installed(argv: list[str]) -> SessionConfig:
    """The session configuration the real installer writes for ``argv``, run in this process."""
    with pytest.MonkeyPatch.context() as mp:
        # The rows' trees lie in pytest's temporary directories, which the OS layer makes
        # writable: no session runs here, so where the worktree lies is not what is asked.
        mp.setattr(hooks_settings, "machine_writable", lambda: ())
        printed = io.StringIO()
        with contextlib.redirect_stdout(printed):
            assert hooks_cli.main(argv[argv.index("hooks") :]) == 0, "the installer refused"
    path = Path(json.loads(printed.getvalue())["config"])
    return SessionConfig.model_validate_json(path.read_bytes())


def _let_through(config: SessionConfig, target: Path, home: Path) -> list[str]:
    """Each layer that lets the session read ``target``: empty when every layer refuses it."""
    wt = config.worktree
    let: list[str] = []
    if paths.protection(str(target), wt, config, writing=False) is None:
        let.append("the file tool")
    if not shell_paths.check(parse(f"cat {target}")[0], wt, config):
        let.append("the shell's hooks")
    policy = sandbox_policy(config, home=str(home), temp_dir="/tmp/pg-review-root")
    deny = policy.settings["sandbox"]["filesystem"]["denyRead"]
    allow = policy.settings["sandbox"]["filesystem"]["allowRead"]

    def under(path: str, roots: list[str]) -> bool:
        return any(path == r.rstrip("/") or path.startswith(r.rstrip("/") + "/") for r in roots)

    if not under(str(target), deny) or under(str(target), allow):
        let.append("the OS layer's policy")
    return let


def _role_session(trials: Trials, tmp: Path) -> SessionConfig:
    """A role session of the later trial, installed as the dispatcher installs one in the layer."""
    with pytest.MonkeyPatch.context() as mp:
        seen = _capture(mp)
        mp.setattr(dispatch, "session_protected_roots", lambda *_a: ((), ()))
        mp.setattr(dispatch, "harness_protection", lambda: [])
        dispatcher = ClaudeDispatcher(
            config=config(trials.task_b, trials.made, **_withheld(trials.made)),
            run=SimpleNamespace(  # type: ignore[arg-type]
                subtask_branch=lambda subtask, _reopen=0: f"b/{subtask}", run_dir=trials.b
            ),
            store_root=tmp / "graph",
            install_bin=tmp / "install" / "bin" / "physgate",
            binary="claude",
            base_url=None,
            credential=Credential(mode="api_key", secret="not-a-key"),
            review_root=trials.review_b,
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
        worktree, sdir = trials.b / "worktrees" / "m1", trials.b / "sessions" / "s-b"
        dispatcher._install(request, worktree, sdir, temp, own_temp=temp)  # noqa: SLF001
    (argv,) = [a for a in seen if a[1:3] == ["hooks", "install"]]
    return _installed(argv)


@pytest.mark.parametrize("what", THINGS)
@pytest.mark.parametrize("placement", PLACEMENTS)
def test_a_role_session_of_a_later_trial_reads_nothing_an_earlier_trial_s_reviews_left(
    tmp_path: Path, placement: str, what: str
) -> None:
    trials = _trials(tmp_path.resolve(), placement)
    if not _admitted(trials):
        # The earlier trial never reviewed there: the command refused it before its first review.
        return
    session = _role_session(trials, tmp_path.resolve())
    let = _let_through(session, trials.left[what], trials.b / "sessions" / "s-b" / "home")
    assert let == [], f"a later trial's role session reads the earlier's {what} through {let}"


def test_a_role_session_whose_review_root_lies_in_its_run_still_reaches_its_worktree(
    tmp_path: Path,
) -> None:
    trials = _trials(tmp_path.resolve(), "in its run")
    session = _role_session(trials, tmp_path.resolve())
    own = Path(session.worktree) / "modules" / "m1" / "controller.py"
    assert paths.protection(str(own), session.worktree, session, writing=False) is None
    assert paths.protection(str(own), session.worktree, session, writing=True) is None
    # And its own run's reviews, where they lie in its run, stay refused to it.
    mine = _leave_reviews(trials.review_b, REVIEW_B, trials.task_b)
    for what, path in mine.items():
        let = _let_through(session, path, trials.b / "sessions" / "s-b" / "home")
        assert let == [], f"a role session reads its own run's review {what} through {let}"


@dataclass
class _Keeping(StandInArm):
    """The stand-in raw arm, which first installs its session through the real installer."""

    targets: tuple[Path, ...] = ()
    let: dict[Path, list[str]] = dataclasses.field(default_factory=dict)
    argv: list[list[str]] = dataclasses.field(default_factory=list)

    def __call__(
        self, task: Task, setup: RawSetup, work: Path, *, cap: int, harness: Path | None = None
    ) -> dict[str, Any]:
        (work / "worktree").mkdir(parents=True)
        with pytest.MonkeyPatch.context() as mp:
            seen = _capture(mp)
            temp = _temp()
            raw._install(
                dataclasses.replace(setup, install_bin=Path("/nowhere/bin/physgate")),
                work / "worktree",
                work / "session",
                temp,
            )
        (argv,) = [a for a in seen if a[1:3] == ["hooks", "install"]]
        self.argv.append(argv)
        session = _installed(argv)
        for target in self.targets:
            self.let[target] = _let_through(session, target, work / "session" / "home")
        shutil.rmtree(work)  # the stand-in arm makes the session's place afresh
        return super().__call__(task, setup, work, cap=cap, harness=harness)


def _raw_round(trials: Trials, out: Path, targets: tuple[Path, ...]) -> _Keeping | BaselineError:
    """A baseline round on the earlier trial: the arm the round ran, or why it was refused."""
    arm = _Keeping(targets=targets)
    try:
        run_baseline(
            store=trials.made.store,
            role="control",
            version=trials.made.version,
            runs=run_set((trials.a, 0)),
            out=out,
            setup_for=setup_for,
            score=lambda _task, _answer: dict(SCORED),
            prices=load_price_sheet(PRICES),
            arm=arm,
            sleep=lambda _s: None,
        )
    except BaselineError as exc:
        assert arm.calls == [], "a raw session started before the round was refused"
        return exc
    assert len(arm.calls) == 1, "the round ran no raw session on the harness trial"
    return arm


@pytest.mark.parametrize("placement", PLACEMENTS)
def test_a_raw_session_reads_nothing_the_harness_trial_s_reviews_left(
    tmp_path: Path, placement: str
) -> None:
    trials = _trials(tmp_path.resolve(), placement, later=False)
    ran = _raw_round(trials, tmp_path.resolve() / "round", tuple(trials.left.values()))
    if isinstance(ran, BaselineError):
        # The round refused the harness run for where its reviews lie, before any session.
        assert "review root" in str(ran), ran
        return
    let = {what: ran.let[path] for what, path in trials.left.items() if ran.let[path]}
    assert let == {}, f"a raw session reads what the harness trial's reviews left: {let}"


def test_a_raw_session_is_refused_the_standing_review_root_and_its_place_apart(
    tmp_path: Path,
) -> None:
    """Whatever the harness run named: a run made by hand reviews under it by convention."""
    trials = _trials(tmp_path.resolve(), "in its run", later=False)
    standing = standing_root(Path.home())
    targets = (
        standing / APART / "labels.key",
        standing / APART / f"{SID}.json",
        standing / REVIEW_A / READ_DIRNAME / "brief.md",
    )
    ran = _raw_round(trials, tmp_path.resolve() / "round", targets)
    assert not isinstance(ran, BaselineError), ran
    let = {str(path.relative_to(standing)): ran.let[path] for path in targets if ran.let[path]}
    assert let == {}, f"a raw session reads beneath the standing review root: {let}"


def test_a_raw_session_is_given_the_harness_run_s_review_root_and_the_standing_one(
    tmp_path: Path,
) -> None:
    """Named to the installer as review material, so each layer refuses it whole."""
    trials = _trials(tmp_path.resolve(), "in its run", later=False)
    ran = _raw_round(trials, tmp_path.resolve() / "round", ())
    assert not isinstance(ran, BaselineError), ran
    (argv,) = ran.argv
    given = {argv[i + 1] for i, word in enumerate(argv) if word == "--review-material"}
    wanted = {str(trials.review_a), os.path.realpath(standing_root(Path.home()))}
    assert wanted <= given, f"the raw session is not withheld {sorted(wanted - given)}"


@pytest.mark.parametrize("placement", ["outside the run roots", "shared outside the run roots"])
def test_a_baseline_round_refuses_a_harness_run_that_reviewed_outside_its_directory(
    tmp_path: Path, placement: str
) -> None:
    base = tmp_path.resolve()
    trials = _trials(base, placement, later=False)
    ran = _raw_round(trials, base / "round", ())
    assert isinstance(ran, PerRoleError), "the round ran a raw session on the harness trial"
    assert ran.context.get("refused_because") == "review_root_outside_the_run", ran.context
    assert str(base) not in str(ran), ran


def test_a_baseline_round_refuses_a_harness_run_that_recorded_no_review_root(
    tmp_path: Path,
) -> None:
    """Where its reviews ran is then unknown, so nothing can withhold them from the raw session."""
    trials = _trials(tmp_path.resolve(), "in its run", later=False)
    (trials.a / "review_root.json").unlink()
    ran = _raw_round(trials, tmp_path.resolve() / "round", ())
    assert isinstance(ran, PerRoleError), "the round ran a raw session on the harness trial"
    assert ran.context.get("refused_because") == "review_root_unrecorded", ran.context


def _reviewer(trials: Trials, review: str) -> SessionConfig:
    """The later trial's reviewer, its request built as its installer is given it."""
    read = trials.review_b / review / READ_DIRNAME
    sdir = trials.review_b / review / SESSION_DIRNAME
    for d in (read / WORKTREE_NAME, sdir / "state", sdir / "settings", sdir / "config"):
        d.mkdir(parents=True, exist_ok=True)
    harness = config(trials.task_b, trials.made, **_withheld(trials.made))
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
    return build_config(request, current_installation())


@pytest.mark.parametrize("what", THINGS)
@pytest.mark.parametrize("placement", PLACEMENTS)
def test_a_reviewer_of_a_later_trial_reads_nothing_an_earlier_trial_s_reviews_left(
    tmp_path: Path, placement: str, what: str
) -> None:
    """Refused before the change too: a reviewer reads only its own packet, and runs no shell."""
    trials = _trials(tmp_path.resolve(), placement)
    session = _reviewer(trials, REVIEW_B)
    target = str(trials.left[what])
    assert paths.protection(target, session.worktree, session, writing=False) is not None


@pytest.mark.parametrize("placement", PLACEMENTS)
def test_a_reviewer_still_reads_its_own_packet_wherever_its_review_root_lies(
    tmp_path: Path, placement: str
) -> None:
    trials = _trials(tmp_path.resolve(), placement)
    session = _reviewer(trials, REVIEW_B)
    mine = _leave_reviews(trials.review_b, REVIEW_B, trials.task_b)
    for what in ("packet's brief", "packet's answer"):
        found = paths.protection(str(mine[what]), session.worktree, session, writing=False)
        assert found is None, f"a reviewer may not read its own {what}: {found}"
    for what in ("reviewer's record", "label key", "protected record"):
        found = paths.protection(str(mine[what]), session.worktree, session, writing=False)
        assert found is not None, f"a reviewer may read its own review's {what}"
