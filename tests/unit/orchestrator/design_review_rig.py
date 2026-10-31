"""A run started from one plan, its review in the opening: the shared rig of the plan's review.

The plan is a base plan of a run with the control and firmware roles, one module each and one
interface node. The call's stream is written where the call writes it, and sealed as it stands.
Every name the plan's review adds is looked up when a test asks for it, so a test of it fails on
an assertion, not at collection, in a tree without it.
"""

from __future__ import annotations

import json
import subprocess
from collections.abc import Callable
from pathlib import Path
from typing import Any

from knowledge_fixture import FIXTURE_ROLES, write_fixture
from orch_helpers import make_config

import physgate.orchestrator.events as events
import physgate.orchestrator.record as record
from physgate.orchestrator.decompose import Outcome, start_run
from physgate.orchestrator.events import EventLog
from physgate.orchestrator.exceptions import CorruptEventLogError
from physgate.orchestrator.git import head_of
from physgate.orchestrator.plan import Plan, plan_sha256
from physgate.orchestrator.protocols import MessageUsage, ReviewResult, SpecDefect, Usage
from physgate.orchestrator.replay import RunState
from physgate.orchestrator.run_config import ModelStrings
from physgate.orchestrator.trajectory import seal

RUN_ID = "run-1"
SEED = 7
DECOMPOSITION = "claude-opus-5-5"
REVIEWER = "claude-sonnet-5"
ROLES = ("control", "firmware")
SESSION = "decomposition-session-1"
REVIEW_SESSION = "review-session-1"
BRIEF = "Build a robot.\n\n## Acceptance criteria\n\n1. It stands.\n"


def outcome_of(how: Callable[[], Any]) -> Any:  # noqa: ANN401 - whatever came of it
    """What ``how`` returned, or the exception it raised: a test asserts on either."""
    try:
        return how()
    except Exception as exc:  # noqa: BLE001 - the escape is what the test asserts on
        return exc


def spec() -> str:
    return "Do the work.\n\n## Acceptance criteria\n\n1. It holds.\n"


def plan() -> Plan:
    node = {
        "id": "iface.drive",
        "kind": "interface",
        "domain": "control",
        "owner_role": "control",
        "quantities": {
            "v_bus": {"value": 12, "unit": "V", "source": "brief", "written_by": "control"}
        },
        "requirements": [],
        "constrains": [],
        "model": None,
        "geometry_hash": "sha256:0",
        "updated": "2026-10-31T00:00:00Z",
    }
    answer = {
        "modules": [
            {"name": "drive", "role": "control", "module_dir": "modules/drive", "spec": spec()},
            {"name": "imu-fw", "role": "firmware", "module_dir": "modules/fw", "spec": spec()},
        ],
        "interface_nodes": [node],
    }
    return Plan.model_validate_json(json.dumps(answer))


def git(cwd: Path, *args: str) -> str:
    return subprocess.run(
        ["git", *args], cwd=cwd, check=True, capture_output=True, text=True
    ).stdout


def target_repo(root: Path) -> Path:
    repo = root / "target"
    (repo / "modules").mkdir(parents=True)
    (repo / "README.md").write_text("target\n")
    git(repo, "init", "-q", "-b", "master")
    git(repo, "-c", "user.email=t@example.invalid", "-c", "user.name=t", "add", "-A")
    git(repo, "-c", "user.email=t@example.invalid", "-c", "user.name=t", "commit", "-q", "-m", "i")
    return repo


def config(repo: Path, design_review: str | None, **overrides: Any) -> Any:  # noqa: ANN401
    """The run's configuration; ``None`` leaves the flag out, as a run before it existed did."""
    fields: dict[str, Any] = {
        "run_id": RUN_ID,
        "seed": SEED,
        "target_head": head_of(repo, "master"),
        "models": ModelStrings(
            decomposition=DECOMPOSITION,
            roles=dict.fromkeys(ROLES, DECOMPOSITION),
            reviewers={**dict.fromkeys(ROLES, REVIEWER), "design": REVIEWER},
        ),
        **overrides,
    }
    if design_review is not None:
        fields["design_review"] = design_review
    return make_config(**fields)


def stream(run_dir: Path) -> Path:
    """The call's stream, where the call writes it."""
    path = run_dir / "decomposition" / "stdout.jsonl"
    path.parent.mkdir(parents=True, exist_ok=True)
    message = {"id": "m1", "model": DECOMPOSITION, "content": []}
    path.write_text(
        json.dumps({"type": "assistant", "message": message})
        + "\n"
        + json.dumps({"type": "result", "subtype": "success", "num_turns": 1})
        + "\n"
    )
    return path


def outcome(run_dir: Path, the_plan: Plan | None = None) -> Any:  # noqa: ANN401
    """The call's outcome, its stream sealed where it was written."""
    path = stream(run_dir)
    return Outcome(
        session_id=SESSION,
        ok=True,
        cause=None,
        detail="a plan",
        plan=the_plan or plan(),
        usage=(MessageUsage(message_id="d1", usage=usage(10)),),
        model=DECOMPOSITION,
        num_turns=1,
        stream_seal=seal(path.read_bytes()),
    )


def usage(tokens: int) -> Usage:
    return Usage(
        input_tokens=tokens,
        output_tokens=tokens,
        cache_read_input_tokens=0,
        cache_creation_input_tokens=0,
    )


def result(verdict: str = "fail") -> ReviewResult:
    return ReviewResult(
        verdict=verdict,  # type: ignore[arg-type]
        finding="the plan leaves the push recovery to no module",
        reviewer_model=REVIEWER,
        session_id=REVIEW_SESSION,
        usage=(MessageUsage(message_id="r1", usage=usage(5)),),
        spec_defects=_blocking(verdict),
    )


INSTALL = {"path": "/install", "action": "checked", "seconds": 0.5, "entries": 3}


def reviewed(run_dir: Path, **fields: Any) -> Any:  # noqa: ANN401
    """What the plan's review came to, as the opening records it."""
    built = getattr(record, "PlanReviewed", None)
    assert built is not None, "the record takes no plan review"
    seal_now = seal((run_dir / "decomposition" / "stdout.jsonl").read_bytes())
    defaults: dict[str, Any] = {
        "install": INSTALL,
        "stream_seal": seal_now,
        "session_id": REVIEW_SESSION,
        "usage": (MessageUsage(message_id="r1", usage=usage(5)),),
    }
    if not {"result", "unavailable", "exposed"} & set(fields):
        defaults["result"] = result()
    return built.model_validate({**defaults, **fields})


def started(
    root: Path,
    design_review: str | None = "observe",
    *,
    review: Callable[[Path], Any] | None = reviewed,
    **overrides: Any,
) -> Path:
    """A run started from the plan, its review recorded when ``review`` gives one."""
    repo = target_repo(root)
    library = root / "library"
    write_fixture(library, (*FIXTURE_ROLES, *ROLES))
    run_dir = root / "run"
    the_config = config(repo, design_review, **overrides)
    the_outcome = outcome(run_dir)
    given = {"reviewed": review(run_dir)} if review is not None else {}
    start_run(
        the_outcome,
        config=the_config,
        run_dir=run_dir,
        target_repo=repo,
        library=library,
        brief=BRIEF,
        **given,
    ).close()
    return run_dir


def lines(run_dir: Path) -> list[dict[str, Any]]:
    return [json.loads(raw) for raw in (run_dir / "events.jsonl").read_text().splitlines()]


def kinds(run_dir: Path) -> list[str]:
    return [one["kind"] for one in lines(run_dir)]


def refusal(root: Path, log: list[dict[str, Any]]) -> str:
    """Why a run state refuses ``log`` (renumbered) at open, or ``""`` if it follows it."""
    path = root / "edited" / "events.jsonl"
    path.parent.mkdir(exist_ok=True)
    path.write_text("".join(json.dumps({**one, "seq": i}) + "\n" for i, one in enumerate(log)))
    try:
        EventLog(path, run_id=RUN_ID, gate_mode="on", state=RunState()).close()
    except CorruptEventLogError as exc:
        return exc.context["reason"]
    finally:
        path.unlink()
    return ""


def line(kind: str, template: dict[str, Any], **fields: Any) -> dict[str, Any]:  # noqa: ANN401
    """A line of ``kind`` with ``template``'s envelope and ``fields``."""
    envelope = {k: template[k] for k in ("seq", "ts", "run_id", "gate_mode")}
    return {**envelope, "kind": kind, **fields}


def design_line_kind() -> str:
    """The kind the plan's review is recorded under, asserted to exist."""
    model = getattr(events, "DesignReviewRan", None)
    assert model is not None, "no line records the plan's review"
    return str(model.model_fields["kind"].default)


def digest(the_plan: Plan) -> str:
    return plan_sha256(the_plan)


def _blocking(verdict: str) -> tuple[SpecDefect, ...]:
    """A blocked review's one blocking defect: the brief lacks an input a check needs."""
    if verdict != "blocked":
        return ()
    return (SpecDefect(finding="the brief gives no supply voltage", blocking=True),)
