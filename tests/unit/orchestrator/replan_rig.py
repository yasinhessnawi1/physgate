"""A scripted reviewed decomposition: each round's call, start check and review said in advance.

``decompose`` is driven through the command as a person runs it, with the call, the plan's reviewer
and its installation stood in for: round k's call answers as the script's k-th step says (a plan of
its own, a failed call, an accounting mismatch, a stop), its plan is refused at the start check
where the step says, and its review gives the step's verdict, no verdict, an exposure, an error
that is not a review, or a stop. A run is a reportable ``repair:N`` run, or an ``on`` or ``observe``
run, on the same script.

What a round leaves is read back from the run directory: the round journal, the plan files, and
the run's opening where a run was started; :func:`rounds_record` normalises them (session ids,
the run id, the run-directory prefix and every time taken out) so two runs' rounds compare as
bytes. Every name the loop adds is looked up when a test asks for it, so a test of it fails on an
assertion, not at collection, in a tree without it.
"""

from __future__ import annotations

import importlib
import json
import re
from collections.abc import Sequence
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import pytest
from design_review_rig import outcome_of, target_repo
from orch_helpers import CLEAN_HARNESS
from test_the_physgate_command_starts_and_decides import PARAMS, fake_binary

import physgate.orchestrator.cli as orchestrator_cli
from physgate.cli import main
from physgate.orchestrator.canaries import CanaryCheck
from physgate.orchestrator.decompose import Outcome
from physgate.orchestrator.decompose import require_startable as real_startable
from physgate.orchestrator.exceptions import (
    AccountingError,
    HeldOutExposedError,
    InvocationError,
    LibraryRefusedError,
    ModelSeparationError,
    PlanRefusedError,
    ReviewUnavailableError,
)
from physgate.orchestrator.plan import Plan
from physgate.orchestrator.protocols import MessageUsage, ReviewResult, SpecDefect, Usage
from physgate.orchestrator.record import ReviewInstall
from physgate.orchestrator.trajectory import seal

DESIGN = "claude-opus-5-5"
BRIEF = "Build a robot.\n\n## Acceptance criteria\n\n1. It stands.\n"
#: The run's one held-out canary, carried by the scripted configuration for the canary's case only.
CANARY = "CANARY-held-out-7f3a9c"
INSTALL = ReviewInstall(path="/install", action="checked", seconds=0.0, entries=1)
UNAVAILABLE = (
    "refused",
    "no_verdict",
    "invalid_verdict",
    "reading_incomplete",
    "compacted",
    "context_exceeded",
)


class Stopped(BaseException):
    """The process ended where it was raised: nothing after it runs."""


@dataclass(frozen=True)
class Step:
    """What one round does.

    ``call``: ``None`` gives the round's own plan; a failure cause gives a failed call with it;
    ``accounting`` raises an accounting mismatch; ``stop`` stops the process at the call, and
    ``stop-after`` once the call has written its stream. ``refusal``: ``plan_refused`` or
    ``library_refused`` at the start check. ``review``: a verdict, ``canary`` (a fail whose finding
    carries the canary), an unavailable cause, ``exposed``, ``invocation_error``,
    ``model_separation``, or ``stop``. ``said``: the round whose plan and finding it gives.
    """

    call: str | None = None
    refusal: str | None = None
    review: str = "fail"
    #: The round whose plan and finding this round gives in place of its own.
    said: int | None = None


def plan_of(k: int) -> Plan:
    """Round k's plan: one electrical module and one node, its specification naming the round."""
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
    spec = f"Power it, as round {k} plans.\n\n## Acceptance criteria\n\n1. It is powered.\n"
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


def verdict(k: int, kind: str, said: int | None = None) -> ReviewResult:
    """Round k's verdict, finding as round ``said`` (or k) does; ``canary`` carries the canary."""
    finding = f"round {said or k}: the plan leaves the bus unprotected"
    if kind == "canary":
        finding += f" ({CANARY})"
    blocking = (SpecDefect(finding="the brief gives no supply voltage", blocking=True),)
    return ReviewResult(
        verdict="fail" if kind == "canary" else kind,  # type: ignore[arg-type]
        finding=finding,
        reviewer_model=DESIGN,
        session_id=f"review-{k}",
        usage=(MessageUsage(message_id=f"r{k}", usage=_usage(5)),),
        spec_defects=blocking if kind == "blocked" else (),
    )


@dataclass
class Script:
    """The call, the start check and the reviewer of one scripted run, and what each was given."""

    steps: Sequence[Step]
    calls: list[dict[str, Any]] = field(default_factory=list)
    seen: list[Any] = field(default_factory=list)

    def _step(self, k: int) -> Step:
        return self.steps[k - 1] if k <= len(self.steps) else Step(review="pass")

    def call(self, brief: str, *, workdir: Path, **given: Any) -> Outcome:  # noqa: ANN401
        k = len(self.calls) + 1
        self.calls.append({"brief": brief, "workdir": workdir, **given})
        step = self._step(k)
        if step.call == "stop":
            raise Stopped
        session = given.get("session_id") or f"decomposition-{k}"
        workdir.mkdir(parents=True, exist_ok=True)
        message = {"id": f"m{k}", "model": "claude-sonnet-5", "content": []}
        stream = workdir / "stdout.jsonl"
        stream.write_text(json.dumps({"type": "assistant", "message": message, "round": k}))
        if step.call == "stop-after":
            raise Stopped
        if step.call == "accounting":
            msg = "the per-message account differs from the binary's own totals"
            raise AccountingError(msg, field="input_tokens", account="1", result="2")
        failed = step.call is not None
        return Outcome(
            session_id=session,
            ok=not failed,
            cause=step.call if failed else None,  # type: ignore[arg-type]
            detail=f"the call ended with {step.call}" if failed else "a plan",
            plan=None if failed else plan_of(step.said or k),
            usage=(MessageUsage(message_id=f"d{k}", usage=_usage(10)),),
            model="claude-sonnet-5",
            num_turns=1,
            stream_seal=seal(stream.read_bytes()),
        )

    def startable(self, plan: Any, **given: Any) -> Any:  # noqa: ANN401
        refusal = self._step(len(self.calls)).refusal
        if refusal == "plan_refused":
            msg = "an interface node's id is not a node id"
            raise PlanRefusedError(msg, node="iface.bus")
        if refusal == "library_refused":
            msg = "the target holds other bytes where the library goes"
            raise LibraryRefusedError(msg, path=".physgate/lib")
        return real_startable(plan, **given)

    @property
    def model(self) -> str:
        return DESIGN

    def review_plan(self, under: Any) -> ReviewResult:  # noqa: ANN401
        self.seen.append(under)
        k = len(self.calls)
        kind = self._step(k).review
        spent = (MessageUsage(message_id=f"r{k}", usage=_usage(5)),)
        if kind == "stop":
            raise Stopped
        if kind in (*UNAVAILABLE, "infrastructure", "unprepared"):
            raise ReviewUnavailableError(
                f"round {k}: the review reached no verdict",
                cause=kind,  # type: ignore[arg-type]
                session_id=f"review-{k}",
                reviewer_model=DESIGN,
                usage=spent,
            )
        if kind == "exposed":
            raise HeldOutExposedError(
                "held-out material", session_id=f"review-{k}", reviewer_model=DESIGN, usage=spent
            )
        if kind == "invocation_error":
            raise InvocationError("the review was answered by a model other than the pinned one")
        if kind == "model_separation":
            raise ModelSeparationError("a reviewer may not run on the designer's model")
        return verdict(k, kind, self._step(k).said)


@dataclass(frozen=True)
class Ran:
    """What one scripted ``decompose`` came to: its exit, its directory, its script, its stderr."""

    code: Any
    run_dir: Path
    script: Script
    err: str


def decompose(
    root: Path,
    design_review: str,
    steps: Sequence[Step],
    *,
    capsys: Any = None,  # noqa: ANN401 - pytest's capture fixture
    loop_patches: dict[str, Any] | None = None,
) -> Ran:
    """Run ``decompose`` once under ``design_review`` on ``steps``, in ``root``; never raises.

    ``loop_patches`` replaces names in the loop's module for the run, where a row needs it.
    """
    root.mkdir(parents=True, exist_ok=True)
    repo = target_repo(root)
    (root / "brief.md").write_text(BRIEF)
    params = {
        **PARAMS,
        "design_review": "on" if design_review.startswith("repair:") else design_review,
        "models": {**PARAMS["models"], "reviewers": {"electrical": DESIGN, "design": DESIGN}},  # type: ignore[dict-item]
    }
    (root / "params.json").write_text(json.dumps(params))
    script = Script(steps)
    args = [
        "decompose",
        str(root / "brief.md"),
        "--seed",
        "7",
        "--run-id",
        "run-1",
        "--params",
        str(root / "params.json"),
        "--target",
        str(repo),
        "--run-dir",
        str(root / "run"),
    ]
    code: Any
    with pytest.MonkeyPatch.context() as patch:
        patch.setenv("ANTHROPIC_API_KEY", "sk-ant-test-dummy-not-a-credential")
        patch.setenv("PHYSGATE_CLAUDE_BIN", str(fake_binary(root, "2.1.272")))
        patch.setattr(orchestrator_cli, "call", script.call)
        patch.setattr(orchestrator_cli, "refusals", lambda facts: [])
        patch.setattr(
            orchestrator_cli,
            "_plan_reviewer",
            # As the command's own: a run that does not review its plan is given no reviewer.
            lambda args, config, *a: None if config.design_review == "off" else (script, INSTALL),
        )
        held = frozenset({CANARY})
        patch.setattr(
            orchestrator_cli,
            "material_check",
            lambda config: CanaryCheck(held_out=held, review_material=frozenset()),
        )
        loop = _loop_module()
        if loop is not None:
            patch.setattr(loop, "require_startable", script.startable)
            for name, value in (loop_patches or {}).items():
                patch.setattr(loop, name, value)
        real = orchestrator_cli._config

        def configured(given: Any) -> Any:  # noqa: ANN401
            update: dict[str, Any] = {"design_review": design_review}
            if design_review.startswith("repair:"):
                update |= {"reportable": True, "harness": CLEAN_HARNESS}
            return real(given).model_copy(update=update)

        patch.setattr(orchestrator_cli, "_config", configured)
        try:
            code = outcome_of(lambda: main(args))
        except Stopped as stopped:
            code = stopped
    err = capsys.readouterr().err if capsys is not None else ""
    return Ran(code=code, run_dir=root / "run", script=script, err=err)


def _loop_module() -> Any:  # noqa: ANN401 - the module, or None in a tree without it
    try:
        return importlib.import_module("physgate.orchestrator.design_rounds")
    except ImportError:
        return None


def journal(run_dir: Path) -> list[dict[str, Any]]:
    """The round journal's lines, as written; empty if there is none."""
    path = run_dir / "decomposition" / "rounds.jsonl"
    if not path.exists():
        return []
    return [json.loads(raw) for raw in path.read_text().splitlines()]


def events(run_dir: Path) -> list[dict[str, Any]]:
    """The run's event log, as written; empty if no run was started."""
    path = run_dir / "events.jsonl"
    if not path.exists():
        return []
    return [json.loads(raw) for raw in path.read_text().splitlines()]


def plan_file(run_dir: Path, k: int) -> Path:
    return run_dir / "decomposition" / f"round-{k}" / "plan.json"


def round_dir(run_dir: Path, k: int) -> Path:
    """Where round k's call ran: the decomposition's directory for round 1, its own after."""
    return run_dir / "decomposition" if k == 1 else run_dir / "decomposition" / f"round-{k}"


_ENVELOPE = ("seq", "ts", "run_id", "held_item")
_TIMES = ("started", "ended", "call_ended", "review_started")
_UUID = re.compile(r"[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}")


def _drop_times(value: Any) -> Any:  # noqa: ANN401 - a JSON value
    if isinstance(value, dict):
        return {k: _drop_times(v) for k, v in value.items() if k not in _TIMES}
    if isinstance(value, list):
        return [_drop_times(v) for v in value]
    return value


def rounds_record(run_dir: Path, upto: int, *, opening: bool = True) -> str:
    """Rounds 1 … ``upto`` as the run recorded them, normalised, as one comparable text.

    The journal's start and end lines of those rounds, their plan files, and (``opening``) where a
    run was started, its tokens of those rounds' sessions and those rounds' review lines; session
    ids, the run id and the run-directory prefix replaced by placeholders in order of first
    appearance, ``ts``, ``started``, ``ended`` and the call's end and the review's start dropped,
    each round's proposal kept, and of a review line its place in the
    log and the item it holds on (the last round alone holds, and it is not among those compared).
    """
    lines = [one for one in journal(run_dir) if one.get("round", 0) <= upto]
    lines = [one for one in lines if one["kind"] in ("round_started", "round_ended")]
    sessions = {one["session_id"] for one in lines if "session_id" in one}
    sessions |= {
        one["review"]["session_id"]
        for one in lines
        if isinstance(one.get("review"), dict) and one["review"].get("session_id")
    }
    plans = {
        k: plan_file(run_dir, k).read_text() if plan_file(run_dir, k).exists() else None
        for k in range(1, upto + 1)
    }
    log = events(run_dir) if opening else []
    spent = [
        {k: v for k, v in one.items() if k not in _ENVELOPE}
        for one in log
        if one["kind"] == "tokens_used" and one["attribution"].split(":", 1)[1] in sessions
    ]
    reviews = [
        {k: v for k, v in one.items() if k not in _ENVELOPE}
        for one in log
        if one["kind"] == "design_review_ran"
    ][:upto]
    proposals = [
        {k: v for k, v in one.items() if k not in _ENVELOPE}
        for one in log
        if one["kind"] == "plan_proposed" and one["round"] <= upto
    ]
    records = {"journal": lines, "plans": plans, "tokens": spent, "reviews": reviews}
    text = json.dumps(
        _drop_times({**records, "proposals": proposals}),
        sort_keys=True,
    )
    text = text.replace(str(run_dir), "<run-dir>")
    seen: dict[str, str] = {}
    return _UUID.sub(lambda m: seen.setdefault(m.group(0), f"<session-{len(seen)}>"), text)
