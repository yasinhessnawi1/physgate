"""A rerun reproduces its run exactly on a fake session, or names the first place they part.

Criterion: a rerun of a fake-session run reproduces every record after the
measured normalisation and nothing else; a perturbed step is named by its line,
subtask, attempt and stage. Each dropped field is shown to be needed by removing
it from the list, and each mapped identifier by its placeholder. A run on a real
endpoint is compared on its decisions alone.
"""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any

import pytest
from observe_rig import (
    HARNESS,
    FakeSession,
    Gate,
    drive,
    fake_driver,
    fake_run,
    start,
    target_repo,
)

from physgate.evaluation.observe import rerun as rerun_module
from physgate.evaluation.observe import sequence
from physgate.evaluation.observe.exceptions import RerunError
from physgate.evaluation.observe.manifest import read_manifest
from physgate.evaluation.observe.rerun import MEASURED, RerunPlan, compare_runs, rerun
from physgate.evaluation.observe.sequence import RunView, level_of
from physgate.orchestrator.git import head_of
from physgate.orchestrator.ports import SessionReport, SessionRequest
from physgate.orchestrator.run_config import RunConfig

BRIEF = "Build two modules.\n"
#: A rerun's run directory is elsewhere on disk from the recorded run's, as it would be.
ELSEWHERE = "elsewhere"


@pytest.fixture
def brief(tmp_path: Path) -> Path:
    path = tmp_path / "brief.md"
    path.write_text(BRIEF)
    return path


@pytest.fixture(autouse=True)
def scripted_endpoint(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("ANTHROPIC_BASE_URL", "http://127.0.0.1:9")


def recorded(tmp_path: Path, repo: Path, run_id: str = "run-a", **kwargs: Any) -> Path:  # noqa: ANN401
    digest = hashlib.sha256(BRIEF.encode()).hexdigest()
    overrides = {"brief_sha256": digest, **kwargs.pop("overrides", {})}
    return fake_run(tmp_path, run_id, repo, overrides=overrides, **kwargs)


def do_rerun(tmp_path: Path, run: Path, repo: Path, brief: Path, **drive_kwargs: Any) -> Any:  # noqa: ANN401
    return rerun(
        run,
        brief=brief,
        run_id="run-r",
        run_dir=tmp_path / ELSEWHERE / "run-r",
        target=repo,
        install=tmp_path / "install",
        driver=fake_driver(tmp_path / ELSEWHERE, repo, **drive_kwargs),
    )


def test_a_fake_session_rerun_reproduces_every_record_exactly(tmp_path: Path, brief: Path) -> None:
    repo = target_repo(tmp_path)
    run = recorded(tmp_path, repo)
    result = do_rerun(tmp_path, run, repo, brief)
    assert result.level == "exact" and result.reproduced and result.first is None
    assert set(result.exact) == set(sequence.RECORDS)
    assert result.decisions_compared == 9  # 2 planned, 2 x (gate, review, merged), integration
    assert result.recorded_manifest_id == read_manifest(run).manifest_id
    assert result.rerun_manifest_id == read_manifest(tmp_path / ELSEWHERE / "run-r").manifest_id
    assert result.recorded_manifest_id != result.rerun_manifest_id


def test_a_proposal_with_a_bare_number_is_named_where_the_rerun_parts(
    tmp_path: Path, brief: Path
) -> None:
    repo = target_repo(tmp_path)
    run = recorded(tmp_path, repo)
    result = do_rerun(tmp_path, run, repo, brief, bare={1})
    events = [json.loads(line) for line in (run / "events.jsonl").read_text().splitlines()]
    ended = next(e for e in events if e["kind"] == "session_ended")
    first = result.first
    assert not result.reproduced and first is not None
    assert (first.record, first.seq, first.field) == ("events", ended["seq"], "attempt_commit")
    assert (first.subtask_id, first.attempt, first.stage) == (ended["subtask_id"], 1, "spawn")
    decided = result.decisions
    assert decided is not None
    assert (decided.field, decided.recorded, decided.rerun) == ("step", '"gate"', '"rejected"')
    assert (decided.subtask_id, decided.attempt, decided.stage) == (ended["subtask_id"], 1, "gate")


#: Each dropped field, and the lines it differs on between two fake-session runs. The
#: installation check's ``seconds`` is not here: a fake-session run has no
#: installation, so the scripted rerun through the command is where it is needed.
NEEDED_DROPS = [
    ("run_started", "config_sha256"),
    ("proposals_checked", "graph_root"),
    ("session_ended", "trajectory_seal"),
    ("tokens_used", "message_id"),
    ("worktree_removed", "seconds"),
]


@pytest.mark.parametrize(("kind", "field"), NEEDED_DROPS)
def test_each_dropped_field_is_needed(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, kind: str, field: str
) -> None:
    repo = target_repo(tmp_path)
    a, b = recorded(tmp_path, repo, "run-a"), recorded(tmp_path, repo, "run-b")
    assert compare_runs(a, b).reproduced
    monkeypatch.setitem(sequence.DROPPED, kind, sequence.DROPPED[kind] - {field})
    compared = compare_runs(a, b)
    assert not compared.reproduced and compared.decisions is None
    parted = compared.exact["events"]
    assert parted is not None and parted.field is not None
    assert parted.field.split(".")[0] == field
    assert json.loads(parted.recorded or "null") != json.loads(parted.rerun or "null")


def test_a_review_s_message_ids_are_dropped_and_are_needed(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    repo = target_repo(tmp_path)
    a = recorded(tmp_path, repo, "run-a")
    b = recorded(tmp_path, repo, "run-b", reviewer_ids="q")
    raw = [json.loads(x) for x in (b / "events.jsonl").read_text().splitlines()]
    assert {e["result"]["usage"][0]["message_id"] for e in raw if e["kind"] == "review_ran"} == {
        "q-1",
        "q-2",
    }
    assert compare_runs(a, b).reproduced  # the two differ in nothing else
    monkeypatch.setattr(sequence, "DROPPED_AT", {})
    compared = compare_runs(a, b)
    parted = compared.exact["events"]
    assert not compared.reproduced and parted is not None
    assert (parted.field, parted.recorded, parted.rerun) == (
        "result.usage[0].message_id",
        '"r-1"',
        '"q-1"',
    )


def test_the_timestamp_is_dropped_on_every_line_and_is_needed(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    repo = target_repo(tmp_path)
    a, b = recorded(tmp_path, repo, "run-a"), recorded(tmp_path, repo, "run-b")
    monkeypatch.setattr(sequence, "DROPPED_EVERYWHERE", frozenset())
    parted = compare_runs(a, b).exact
    assert parted["events"] is not None and parted["events"].field == "ts"
    assert (parted["events"].index, parted["events"].subtask_id) == (0, None)


def test_every_dropped_field_and_no_other_is_removed_from_a_line(tmp_path: Path) -> None:
    view = RunView(recorded(tmp_path, target_repo(tmp_path)))
    for kind, fields in sequence.DROPPED.items():
        line = {"seq": 3, "ts": "t", "kind": kind, "kept": 1, **dict.fromkeys(fields, "x")}
        assert view.line(line) == {"seq": 3, "kind": kind, "kept": 1}
    assert "leftover_read" in sequence.DROPPED  # a resumed run's reading of a leftover stream
    usage: list[dict[str, Any]] = [{"message_id": "m1", "usage": 1}, {"message_id": "m2"}]
    result: dict[str, Any] = {"verdict": "pass", "usage": usage}
    review: dict[str, Any] = {"seq": 4, "ts": "t", "kind": "review_ran", "result": result}
    assert view.line(review) == {
        "seq": 4,
        "kind": "review_ran",
        "result": {"verdict": "pass", "usage": [{"usage": 1}, {}]},
    }


def test_each_mapped_identifier_is_replaced_by_what_it_stands_for(tmp_path: Path) -> None:
    run = recorded(tmp_path, target_repo(tmp_path))
    view = RunView(run)
    manifest = read_manifest(run)
    merged = manifest.artefacts.merged[0]
    sessions = list(view.sessions)
    assert sessions[0] == "no-call"  # the decomposition's, first in the log
    text = f"{run}/sessions/{sessions[1]}/x {merged.merge_commit} physgate/run-a/run"
    assert view.text(text) == (
        f"<run-dir>/sessions/<session 2>/x <tree {merged.merge_tree}> physgate/<run>/run"
    )
    unknown = "f" * 40  # not a commit of this run: left as it is, so it diverges
    assert view.text(unknown) == unknown


def test_a_run_id_inside_a_placeholder_does_not_rewrite_it(tmp_path: Path) -> None:
    repo = target_repo(tmp_path)
    view = RunView(recorded(tmp_path, repo, "run-d"))
    assert view.text(f"{view.run_dir}/sessions/x physgate/run-d/run") == (
        "<run-dir>/sessions/x physgate/<run>/run"
    )


class Killed(BaseException):
    """The orchestrator's process dying while a session runs."""


def killed_and_resumed(
    tmp_path: Path,
    repo: Path,
    monkeypatch: pytest.MonkeyPatch,
    before: dict[int, str] | None = None,
    after: dict[int, str] | None = None,
) -> Path:
    """A run whose process dies in its second subtask's session, then is resumed.

    ``before`` and ``after`` give the module file's content per session call of
    the first and the second process.
    """
    digest = hashlib.sha256(BRIEF.encode()).hexdigest()
    cfg = start(tmp_path, "run-k", repo, brief_sha256=digest)
    real_run = FakeSession.run

    def dies_on_the_second_subtask(self: FakeSession, request: SessionRequest) -> SessionReport:
        if request.subtask_id.startswith("s2"):
            raise Killed
        return real_run(self, request)

    monkeypatch.setattr(FakeSession, "run", dies_on_the_second_subtask)
    with pytest.raises(Killed):
        drive(tmp_path, cfg, repo, session_content=before)
    monkeypatch.setattr(FakeSession, "run", real_run)
    assert drive(tmp_path, cfg, repo, session_content=after, resume=True) == "done"
    return tmp_path / "run-k"


def test_a_run_killed_and_resumed_reproduces_exactly_up_to_where_it_resumed(
    tmp_path: Path, brief: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    repo = target_repo(tmp_path)
    run = killed_and_resumed(tmp_path, repo, monkeypatch)
    result = do_rerun(tmp_path, run, repo, brief)
    events = [json.loads(x) for x in (run / "events.jsonl").read_text().splitlines()]
    resumed = next(i for i, e in enumerate(events) if e["kind"] == "resumed")
    assert (result.rule, result.resumed_at) == ("exact_to_resume", resumed)
    assert result.reproduced
    # The project's state and every decision are the uninterrupted run's.
    assert result.decisions is None
    assert {k for k, v in result.exact.items() if v is not None} == {"events"}
    # The log parts at the one line only the resumed run has.
    parted = result.exact["events"]
    assert parted is not None and (parted.field, parted.recorded) == ("kind", '"resumed"')
    assert (parted.index, parted.subtask_id, parted.attempt, parted.stage) == (
        resumed,
        "s2-5e2ad0",
        1,
        "spawn",
    )


def test_a_resumed_run_that_parts_before_its_resume_line_is_not_reproduced(
    tmp_path: Path, brief: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    repo = target_repo(tmp_path)
    # The first process's first session wrote other work than the rerun's will.
    run = killed_and_resumed(tmp_path, repo, monkeypatch, before={1: "x = 2\n"})
    result = do_rerun(tmp_path, run, repo, brief)
    parted = result.exact["events"]
    assert result.rule == "exact_to_resume" and not result.reproduced
    assert parted is not None and result.resumed_at is not None
    assert parted.index < result.resumed_at and parted.subtask_id == "s1-af41ca"


def test_a_resumed_run_whose_log_alone_parts_before_its_resume_line_is_not_reproduced(
    tmp_path: Path, brief: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    repo = target_repo(tmp_path)
    run = killed_and_resumed(tmp_path, repo, monkeypatch)
    # One token more on the first session's line: a difference only the log holds,
    # so no other record can fail the comparison in its place.
    log = run / "events.jsonl"
    lines = [json.loads(x) for x in log.read_text().splitlines()]
    first = next(i for i, e in enumerate(lines) if e["kind"] == "tokens_used")
    lines[first]["usage"]["input_tokens"] += 1
    log.write_text("".join(json.dumps(e, separators=(",", ":")) + "\n" for e in lines))
    result = do_rerun(tmp_path, run, repo, brief)
    parted = result.exact["events"]
    assert result.decisions is None
    assert {k for k, v in result.exact.items() if v is not None} == {"events"}
    assert parted is not None and result.resumed_at is not None
    assert (parted.index, parted.field) == (first, "usage.input_tokens")
    assert first < result.resumed_at and not result.reproduced


def test_a_resumed_run_whose_state_differs_after_the_resume_is_not_reproduced(
    tmp_path: Path, brief: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    repo = target_repo(tmp_path)
    # After the resume the second subtask's work differs. The log's first
    # divergence is still the resume line, so only the other records can tell.
    run = killed_and_resumed(tmp_path, repo, monkeypatch, after={1: "x = 2\n"})
    result = do_rerun(tmp_path, run, repo, brief)
    parted = result.exact["events"]
    assert parted is not None and parted.index == result.resumed_at
    assert result.exact["git"] is not None and result.decisions is None
    assert not result.reproduced


def test_a_real_endpoint_run_is_compared_on_its_decisions_alone(tmp_path: Path) -> None:
    repo = target_repo(tmp_path)
    real = {"endpoint": "default"}
    a = recorded(tmp_path, repo, "run-a", overrides=real)
    b = recorded(tmp_path, repo, "run-b", overrides=real, session_content={1: "x = 2\n"})
    same = compare_runs(a, b)
    assert same.level == "decisions" and same.reproduced
    assert same.exact["events"] is not None  # a measured difference, not scored
    c = recorded(tmp_path, repo, "run-c", overrides=real, gate=Gate(fail_on={1}))
    parted = compare_runs(a, c)
    assert not parted.reproduced and parted.decisions is not None
    assert (parted.decisions.field, parted.decisions.rerun) == ("failing_check", '"magnitude"')
    assert (parted.decisions.subtask_id, parted.decisions.attempt) == ("s1-af41ca", 1)


@pytest.mark.parametrize(
    ("endpoint", "level"),
    [
        ("http://127.0.0.1:41817", "exact"),
        ("http://localhost:8080/v1", "exact"),
        ("default", "decisions"),
        ("https://proxy.example.com", "decisions"),
    ],
)
def test_the_level_follows_whether_a_real_model_answered(
    tmp_path: Path, endpoint: str, level: str
) -> None:
    repo = target_repo(tmp_path)
    run = recorded(tmp_path, repo, overrides={"endpoint": endpoint})
    assert level_of(read_manifest(run).config) == level


def refused(tmp_path: Path, run: Path, repo: Path, given: Path, **changes: Any) -> RerunError:  # noqa: ANN401
    calls: list[RerunPlan] = []
    arguments: dict[str, Any] = {
        "brief": given,
        "run_id": "run-r",
        "run_dir": tmp_path / "run-r",
        "target": repo,
        "install": tmp_path / "install",
        "driver": calls.append,
    } | changes
    with pytest.raises(RerunError) as refusal:
        rerun(run, **arguments)
    assert calls == []  # refused before anything was driven
    return refusal.value


def test_a_rerun_from_another_brief_or_under_the_same_id_is_refused(
    tmp_path: Path, brief: Path
) -> None:
    repo = target_repo(tmp_path)
    run = recorded(tmp_path, repo)
    other = tmp_path / "other.md"
    other.write_text("Build three modules.\n")
    assert "brief" in str(refused(tmp_path, run, repo, brief, brief=other))
    assert "run id" in str(refused(tmp_path, run, repo, brief, run_id="run-a"))


def test_a_rerun_against_a_moved_target_is_refused(tmp_path: Path, brief: Path) -> None:
    repo = target_repo(tmp_path)
    run = recorded(tmp_path, repo)
    (repo / "README.md").write_text("moved\n")
    ident = ["-c", "user.email=t@example.invalid", "-c", "user.name=t"]
    import subprocess

    subprocess.run(["git", *ident, "commit", "-qam", "m"], cwd=repo, check=True)
    assert head_of(repo, "HEAD") != read_manifest(run).config.target_head
    assert "target" in str(refused(tmp_path, run, repo, brief))


def test_a_rerun_on_other_code_is_refused(
    tmp_path: Path, brief: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    repo = target_repo(tmp_path)
    run = recorded(tmp_path, repo)
    moved = HARNESS.model_copy(
        update={"commit": "0" * 40, "clean": True, "uncommitted_sha256": None}
    )
    monkeypatch.setattr(rerun_module, "harness_state", lambda _root: moved)
    assert refused(tmp_path, run, repo, brief).context["changed"]


def test_a_rerun_against_another_endpoint_is_refused(
    tmp_path: Path, brief: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    repo = target_repo(tmp_path)
    run = recorded(tmp_path, repo)
    monkeypatch.setenv("ANTHROPIC_BASE_URL", "http://127.0.0.1:10")
    assert "endpoint" in str(refused(tmp_path, run, repo, brief))


def test_the_command_driver_refuses_another_binary_version(
    tmp_path: Path, brief: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    import physgate.orchestrator.decompose as decompose

    repo = target_repo(tmp_path)
    run = recorded(tmp_path, repo)
    monkeypatch.setattr(decompose, "binary_version", lambda: "2.1.999")
    with pytest.raises(RerunError, match="binary") as refusal:
        rerun_module.through_the_command()(plan_of(tmp_path, run, repo, brief))
    assert refusal.value.context == {"recorded": "2.1.272", "now": "2.1.999"}


def test_the_command_driver_reports_a_refusal_by_the_orchestrator(
    tmp_path: Path, brief: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    import physgate.cli
    import physgate.orchestrator.decompose as decompose

    repo = target_repo(tmp_path)
    run = recorded(tmp_path, repo)
    monkeypatch.setattr(decompose, "binary_version", lambda: "2.1.272")
    seen: list[list[str]] = []

    def refusing(argv: list[str], registrations: object = None) -> int:
        seen.append(argv)
        return 2

    monkeypatch.setattr(physgate.cli, "main", refusing)
    with pytest.raises(RerunError, match="refused") as refusal:
        rerun_module.through_the_command()(plan_of(tmp_path, run, repo, brief))
    assert refusal.value.context["step"] == "decompose" and len(seen) == 1
    params = seen[0][seen[0].index("--params") + 1]
    assert seen[0][seen[0].index("--seed") + 1] == "1" and not Path(params).exists()


def plan_of(tmp_path: Path, run: Path, repo: Path, brief: Path) -> RerunPlan:
    return RerunPlan(
        recorded=read_manifest(run).config,
        brief=brief,
        run_id="run-r",
        run_dir=tmp_path / "run-r",
        target=repo,
        install=tmp_path / "install",
    )


def test_the_parameters_are_the_recorded_run_s_without_what_decompose_measures(
    tmp_path: Path, brief: Path
) -> None:
    repo = target_repo(tmp_path)
    plan = plan_of(tmp_path, recorded(tmp_path, repo), repo, brief)
    params = plan.params()
    assert set(params) == set(RunConfig.model_fields) - MEASURED
    assert params["models"]["reviewers"] == {"electrical": "claude-opus-5-5"}
