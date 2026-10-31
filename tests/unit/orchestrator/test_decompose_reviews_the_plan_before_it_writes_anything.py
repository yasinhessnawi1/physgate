"""``decompose`` reviews the plan after its one call and before the run is written, when asked to.

A run that reviews its plan names where reviews are prepared and the hooks' installation they
run under, and the design reviewer is built from its pins before the call is spent. After the
call the reviewer is handed the plan under review: the brief as the decomposition was given it,
the plan and its digest, and the call's stream with the seal taken where the call wrote it. What
the review came to goes into the run's opening. The call is made once, whatever the verdict.

A reviewer that cannot run fails the command with nothing of the run recorded, as a refused
start does, and a command stopped during the review leaves no run behind. A run that does not
review its plan asks nothing of a reviewer.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest
from design_review_rig import outcome_of, target_repo
from test_the_physgate_command_starts_and_decides import PARAMS, _run_args, fake_binary

import physgate.orchestrator.cli as orchestrator_cli
from physgate.cli import main
from physgate.orchestrator.accounting import TokenAccount
from physgate.orchestrator.decompose import Outcome
from physgate.orchestrator.events import read_events
from physgate.orchestrator.exceptions import (
    HeldOutExposedError,
    InvocationError,
    ModelSeparationError,
    ReviewUnavailableError,
)
from physgate.orchestrator.git import head_of
from physgate.orchestrator.plan import Plan, plan_sha256
from physgate.orchestrator.protocols import MessageUsage, ReviewResult, SpecDefect, Usage
from physgate.orchestrator.trajectory import seal

DESIGN = "claude-opus-5-5"
BRIEF = "Build a robot.\n\n## Acceptance criteria\n\n1. It stands.\n"
REVIEWING = {
    **PARAMS,
    "design_review": "observe",
    "models": {**PARAMS["models"], "reviewers": {"electrical": DESIGN, "design": DESIGN}},  # type: ignore[dict-item]
}


def _plan() -> Plan:
    node: dict[str, Any] = {
        "id": "iface.bus",
        "kind": "interface",
        "domain": "electrical",
        "owner_role": "electrical",
        "quantities": {
            "v_bus": {"value": 12, "unit": "V", "source": "brief", "written_by": "electrical"}
        },
        "requirements": [],
        "constrains": [],
        "model": None,
        "geometry_hash": "sha256:0",
        "updated": "2026-10-31T00:00:00Z",
    }
    spec = "Power it.\n\n## Acceptance criteria\n\n1. It is powered.\n"
    answer = {
        "modules": [
            {"name": "power", "role": "electrical", "module_dir": "modules/p", "spec": spec}
        ],
        "interface_nodes": [node],
    }
    return Plan.model_validate_json(json.dumps(answer))


def _usage(n: int) -> Usage:
    return Usage(
        input_tokens=n, output_tokens=n, cache_read_input_tokens=0, cache_creation_input_tokens=0
    )


class Calls:
    """A stand-in for the one model call: it writes its stream where the call does."""

    def __init__(self) -> None:
        self.made = 0

    def __call__(self, brief: str, *, workdir: Path, **_: Any) -> Outcome:  # noqa: ANN401
        self.made += 1
        workdir.mkdir(parents=True, exist_ok=True)
        message = {"id": "m1", "model": "claude-sonnet-5", "content": []}
        (workdir / "stdout.jsonl").write_text(json.dumps({"type": "assistant", "message": message}))
        return Outcome(
            session_id="decomposition-session-1",
            ok=True,
            cause=None,
            detail="a plan",
            plan=_plan(),
            usage=(MessageUsage(message_id="d1", usage=_usage(10)),),
            model="claude-sonnet-5",
            num_turns=1,
            stream_seal=seal((workdir / "stdout.jsonl").read_bytes()),
        )


class StandIn:
    """A plan reviewer that answers what it is given, and remembers what it was handed."""

    def __init__(self, answer: ReviewResult | BaseException) -> None:
        self.answer = answer
        self.seen: list[Any] = []
        self.setups: list[Any] = []

    @property
    def model(self) -> str:
        return DESIGN

    def review_plan(self, under: Any) -> ReviewResult:  # noqa: ANN401
        self.seen.append(under)
        if isinstance(self.answer, BaseException):
            raise self.answer
        return self.answer

    def factory(self, setup: Any, config: Any) -> StandIn:  # noqa: ANN401
        self.setups.append(setup)
        return self


def _verdict(verdict: str = "fail") -> ReviewResult:
    return ReviewResult(
        verdict=verdict,  # type: ignore[arg-type]
        finding="the plan leaves the bus unprotected",
        reviewer_model=DESIGN,
        session_id="review-session-1",
        usage=(MessageUsage(message_id="r1", usage=_usage(5)),),
        spec_defects=_blocking(verdict),
    )


class Stopped(BaseException):
    """The process ended where it was raised: nothing after it runs."""


def _args(tmp_path: Path, params: dict[str, Any], *, places: bool = True) -> list[str]:
    repo = target_repo(tmp_path)
    (tmp_path / "brief.md").write_text(BRIEF)
    (tmp_path / "params.json").write_text(json.dumps(params))
    found = [
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
        str(tmp_path / "run"),
    ]
    if places:
        run_args = _run_args(tmp_path)
        found += run_args[run_args.index("--install") :]
    return found


@pytest.fixture
def calls(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Calls:
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-ant-test-dummy-not-a-credential")
    monkeypatch.setenv("PHYSGATE_CLAUDE_BIN", str(fake_binary(tmp_path, "2.1.272")))
    made = Calls()
    monkeypatch.setattr(orchestrator_cli, "call", made)
    return made


def _exit(args: list[str], reviewer: StandIn | None) -> Any:  # noqa: ANN401 - a code, or the escape
    def run() -> int:
        registrations = (
            orchestrator_cli.Registrations(plan_reviewer_factory=reviewer.factory)
            if reviewer is not None
            else orchestrator_cli.Registrations()
        )
        try:
            return main(args, registrations)
        except SystemExit as exc:  # the parser's refusal of an argument it does not know
            return int(exc.code or 0) + 100

    return outcome_of(run)


def _nothing_recorded(run_dir: Path) -> None:
    for name in ("run.json", "events.jsonl", "store", "queue.jsonl"):
        assert not (run_dir / name).exists(), name


def test_decompose_reviews_the_plan_and_records_it_in_the_opening(
    tmp_path: Path, calls: Calls
) -> None:
    reviewer = StandIn(_verdict())
    assert _exit(_args(tmp_path, REVIEWING), reviewer) == 0
    assert calls.made == 1
    [under] = reviewer.seen
    run_dir = tmp_path / "run"
    stream = run_dir / "decomposition" / "stdout.jsonl"
    assert under.brief == BRIEF
    assert under.plan == _plan()
    assert under.plan_sha256 == plan_sha256(_plan())
    assert Path(under.stream) == stream
    assert under.stream_seal == seal(stream.read_bytes())
    assert under.decomposition_model == "claude-sonnet-5"
    assert under.decomposition_session_id == "decomposition-session-1"
    [setup] = reviewer.setups
    assert Path(setup.review_root) == (tmp_path / "review-scratch").resolve()
    assert Path(setup.install_bin) == (tmp_path / "install").resolve() / "bin" / "physgate"
    log = [json.loads(raw) for raw in (run_dir / "events.jsonl").read_text().splitlines()]
    assert log[0]["design_review"] == "observe"
    [installed] = [one for one in log if one["kind"] == "install_checked"]
    assert installed["path"] == str((tmp_path / "install").resolve())
    assert log[-1]["kind"] == "design_review_ran"
    assert log[-1]["result"]["verdict"] == "fail"


@pytest.mark.parametrize("verdict", ["pass", "fail", "blocked"])
def test_no_second_decomposition_call_outside_repair(
    tmp_path: Path, calls: Calls, verdict: str
) -> None:
    assert _exit(_args(tmp_path, REVIEWING), StandIn(_verdict(verdict))) == 0
    assert calls.made == 1
    found = outcome_of(lambda: read_events(tmp_path / "run" / "events.jsonl"))
    assert isinstance(found, list), found
    account = TokenAccount.from_events(found)
    assert account.decomposition_invocations() == 1
    account.assert_no_routing()
    assert [a for a in account.by_attribution() if a.startswith("reviewer:")] == [
        "reviewer:review-session-1"
    ]


def test_a_run_that_reviews_its_plan_names_where_reviews_are_prepared(
    tmp_path: Path, calls: Calls, capsys: pytest.CaptureFixture[str]
) -> None:
    reviewer = StandIn(_verdict())
    assert _exit(_args(tmp_path, REVIEWING, places=False), reviewer) == 2
    assert "--review-root" in capsys.readouterr().err
    # Refused before the call is spent, and before anything is written.
    assert calls.made == 0
    assert reviewer.seen == []
    _nothing_recorded(tmp_path / "run")


@pytest.mark.parametrize(
    "error",
    [
        InvocationError("the review was answered by a model other than the pinned one"),
        ModelSeparationError("a reviewer may not run on the implementer's model"),
    ],
    ids=["invocation", "separation"],
)
def test_a_review_that_cannot_run_fails_decompose_with_nothing_recorded(
    tmp_path: Path, calls: Calls, error: Exception
) -> None:
    reviewer = StandIn(error)
    assert _exit(_args(tmp_path, REVIEWING), reviewer) == 2
    assert len(reviewer.seen) == 1
    _nothing_recorded(tmp_path / "run")


def test_a_decompose_stopped_during_the_review_leaves_no_run(
    tmp_path: Path, calls: Calls, capsys: pytest.CaptureFixture[str]
) -> None:
    reviewer = StandIn(Stopped())
    with pytest.raises(BaseException) as stopped:  # noqa: PT011 - the stop is the point
        _exit(_args(tmp_path, REVIEWING), reviewer)
    assert stopped.type is Stopped
    assert len(reviewer.seen) == 1
    run_dir = tmp_path / "run"
    _nothing_recorded(run_dir)
    # What it leaves is inert: no run is driven from it.
    assert main(_run_args(tmp_path)) == 2
    assert "no run configuration" in capsys.readouterr().err


def test_a_run_that_does_not_review_its_plan_asks_for_no_review(
    tmp_path: Path, calls: Calls
) -> None:
    reviewer = StandIn(_verdict())
    params = {**REVIEWING, "design_review": "off"}
    assert _exit(_args(tmp_path, params, places=False), reviewer) == 0
    assert reviewer.seen == [] and reviewer.setups == []
    assert calls.made == 1
    log = [json.loads(raw) for raw in (tmp_path / "run" / "events.jsonl").read_text().splitlines()]
    assert "design_review" not in log[0]
    assert all(one["kind"] not in ("design_review_ran", "install_checked") for one in log)
    assert head_of(tmp_path / "target", "master")


def _blocking(verdict: str) -> tuple[SpecDefect, ...]:
    """A blocked review's one blocking defect: the brief lacks an input a check needs."""
    if verdict != "blocked":
        return ()
    return (SpecDefect(finding="the brief gives no supply voltage", blocking=True),)


def _log(tmp_path: Path) -> list[dict[str, Any]]:
    events = (tmp_path / "run" / "events.jsonl").read_text().splitlines()
    return [json.loads(raw) for raw in events]


def test_a_review_with_no_verdict_is_what_the_review_came_to(tmp_path: Path, calls: Calls) -> None:
    spent = (MessageUsage(message_id="r9", usage=_usage(3)),)
    reviewer = StandIn(
        ReviewUnavailableError(
            "a required file was not read in full",
            cause="reading_incomplete",
            session_id="review-session-2",
            reviewer_model=DESIGN,
            usage=spent,
        )
    )
    assert _exit(_args(tmp_path, REVIEWING), reviewer) == 0
    log = _log(tmp_path)
    assert log[-1]["kind"] == "design_review_ran"
    assert log[-1]["unavailable"]["cause"] == "reading_incomplete"
    assert log[-1]["unavailable"]["session_id"] == "review-session-2"
    assert log[-2]["attribution"] == "reviewer:review-session-2"


def test_a_review_that_showed_held_out_material_halts_the_run_it_starts(
    tmp_path: Path, calls: Calls
) -> None:
    reviewer = StandIn(
        HeldOutExposedError(
            "held-out material", session_id="review-session-3", reviewer_model=DESIGN, usage=()
        )
    )
    assert _exit(_args(tmp_path, REVIEWING), reviewer) == 0
    log = _log(tmp_path)
    assert [one["kind"] for one in log[-2:]] == ["incident", "halted"]
    assert log[-2]["cause"] == "held_out_read"
    assert all(one["kind"] != "design_review_ran" for one in log)
