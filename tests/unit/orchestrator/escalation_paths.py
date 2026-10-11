"""Every way a subtask reaches the approval queue today, run through the real loop.

The queue is filled at the end of an attempt that did not merge, and at the
integration call. This module builds one run for each way that can happen, in
each gate mode it can happen in, and returns each run's records as a rerun
compares them: the configuration, the event log, the task ledger, the queue and
its decisions, normalised the way an exact rerun comparison normalises them
(timestamps dropped, the run directory, session ids and commits replaced by what
they stand for).

The records were written to ``escalation_paths.golden.json`` from the code as it
was before the escalation decision interface existed, and committed before any
change to the loop. The interface is meant to change nothing about what reaches a
person, so every later version of the loop must reproduce those records; what it
adds of its own (its decision lines) is the only difference allowed, and the
comparison names it explicitly.

Two kinds of run:

- **stand-ins over the loop's ports** (scripted sessions, gate and reviewer), one
  per path and gate mode: a clean merge; a rejection then a pass; three rejections
  by the reviewer, the gate, the reading check and the write-scope check, and a
  mixture; a blocked review, first or after a rejection; a review with no verdict,
  final at once or after its one infrastructure retry; the integration call
  failing; two subtasks where one is escalated;
- **the physics gate's three-mode plan** with the real gate, store and git, and a
  stand-in session and reviewer, as the operator UI's tests build it.

Run as a script to rewrite the golden file: ``uv run python
tests/unit/orchestrator/escalation_paths.py``. Rewriting it is never a fix for a
red test; the file's first commit is the evidence of what the loop did before.
"""

from __future__ import annotations

import json
import sys
import tempfile
from collections.abc import Callable
from pathlib import Path
from typing import Any

HERE = Path(__file__).resolve().parent
TESTS = HERE.parents[1]
if __name__ == "__main__":  # pragma: no cover - the script form puts its own imports in reach
    sys.path[:0] = [str(HERE), str(TESTS)]

from loop_fakes import (  # noqa: E402 - after the script form's path
    FakeChanges,
    FakeDispatcher,
    FakeGate,
    FakeReviewer,
    Rig,
    plan,
)

from physgate.evaluation.observe.sequence import RunView  # noqa: E402
from physgate.orchestrator.common import GateMode  # noqa: E402
from physgate.orchestrator.exceptions import ReviewUnavailableError  # noqa: E402
from physgate.orchestrator.protocols import (  # noqa: E402
    ItemVerdict,
    MessageUsage,
    ReviewResult,
    SpecDefect,
    Usage,
)

GOLDEN = HERE / "escalation_paths.golden.json"

#: The records compared, in the order a difference is reported.
RECORDS = ("config", "events", "ledger", "queue", "queue_decisions", "journal", "git")

MODES: tuple[GateMode, ...] = ("on", "observe", "off")

BLOCKING = SpecDefect(finding="no unstable pole is given", blocking=True, item="DS-4")


def _usage(n: int) -> Usage:
    return Usage(
        input_tokens=n, output_tokens=1, cache_read_input_tokens=0, cache_creation_input_tokens=0
    )


def blocked_review(n: int) -> ReviewResult:
    """The reviewer's answer when the issued specification lacks a safety-critical input."""
    return ReviewResult(
        verdict="blocked",
        finding="the stability check cannot be decided: no unstable pole is given",
        reviewer_model="claude-opus-5-5",
        session_id=f"rev-{n}",
        usage=(MessageUsage(message_id=f"b-{n}", usage=_usage(9)),),
        items=(
            ItemVerdict(
                item="DS-4", section="domain_standards", result="not evaluable", evidence="spec:3"
            ),
        ),
        spec_defects=(BLOCKING,),
    )


def unavailable(cause: str) -> ReviewUnavailableError:
    """A review that reached no verdict, for ``cause``."""
    return ReviewUnavailableError(
        f"the review reached no verdict: {cause}",
        cause=cause,  # type: ignore[arg-type]
        session_id=f"rev-{cause}",
        reviewer_model="claude-opus-5-5",
        usage=(MessageUsage(message_id=f"u-{cause}", usage=_usage(5)),),
    )


def _drive(rig: Rig, *subtasks: str) -> None:
    loop = rig.open()
    try:
        loop.start(plan(*subtasks))
        loop.run()
    finally:
        loop.close()


def _stand_in(
    build: Callable[[Path, GateMode], Rig], subtasks: tuple[str, ...] = ("s1",)
) -> Callable[[Path, GateMode], Path]:
    def run(root: Path, mode: GateMode) -> Path:
        run_dir = root / "run"
        _drive(build(run_dir, mode), *subtasks)
        return run_dir

    return run


#: name -> (gate modes it runs in, how it is built). A path that cannot happen in a
#: mode (the gate refusing under ``observe`` or ``off``) is not run in it.
STAND_INS: dict[str, tuple[tuple[GateMode, ...], Callable[[Path, GateMode], Path]]] = {
    "clean_merge": (MODES, _stand_in(lambda d, m: Rig(d, gate_mode=m))),
    "review_reject_then_pass": (
        MODES,
        _stand_in(lambda d, m: Rig(d, gate_mode=m, reviewer=FakeReviewer(verdicts=["fail"]))),
    ),
    "review_rejects_three_times": (
        MODES,
        _stand_in(lambda d, m: Rig(d, gate_mode=m, reviewer=FakeReviewer(verdicts=["fail"] * 3))),
    ),
    "gate_rejects_three_times": (
        ("on",),
        _stand_in(lambda d, m: Rig(d, gate_mode=m, gate=FakeGate(verdicts=["fail"] * 3))),
    ),
    "gate_rejects_then_pass": (
        ("on",),
        _stand_in(lambda d, m: Rig(d, gate_mode=m, gate=FakeGate(verdicts=["fail"]))),
    ),
    "gate_fails_observed_and_reviewed": (
        ("observe",),
        _stand_in(lambda d, m: Rig(d, gate_mode=m, gate=FakeGate(verdicts=["fail"] * 3))),
    ),
    "reading_unverified_three_times": (
        MODES,
        _stand_in(lambda d, m: Rig(d, gate_mode=m, dispatcher=FakeDispatcher(unread={1, 2, 3}))),
    ),
    "write_scope_refused_three_times": (
        MODES,
        _stand_in(
            lambda d, m: Rig(
                d,
                gate_mode=m,
                changes=FakeChanges(
                    refuse={i: ("write_scope", "the attempt changed x outside") for i in (1, 2, 3)}
                ),
            )
        ),
    ),
    "proposal_refused_reading_then_review": (
        MODES,
        _stand_in(
            lambda d, m: Rig(
                d,
                gate_mode=m,
                changes=FakeChanges(refuse={1: ("proposal", "the store refused n1")}),
                dispatcher=FakeDispatcher(unread={2}),
                reviewer=FakeReviewer(verdicts=["fail"]),
            )
        ),
    ),
    "review_blocked_first": (
        MODES,
        _stand_in(
            lambda d, m: Rig(d, gate_mode=m, reviewer=FakeReviewer(results={1: blocked_review(1)}))
        ),
    ),
    "review_blocked_after_a_rejection": (
        MODES,
        _stand_in(
            lambda d, m: Rig(
                d,
                gate_mode=m,
                reviewer=FakeReviewer(verdicts=["fail"], results={2: blocked_review(2)}),
            )
        ),
    ),
    "review_unavailable_at_once": (
        MODES,
        _stand_in(
            lambda d, m: Rig(
                d, gate_mode=m, reviewer=FakeReviewer(unavailable={1: unavailable("refused")})
            )
        ),
    ),
    "review_unavailable_after_its_retry": (
        MODES,
        _stand_in(
            lambda d, m: Rig(
                d,
                gate_mode=m,
                reviewer=FakeReviewer(
                    unavailable={
                        1: unavailable("infrastructure"),
                        2: unavailable("infrastructure"),
                    }
                ),
            )
        ),
    ),
    "review_retried_then_passes": (
        MODES,
        _stand_in(
            lambda d, m: Rig(
                d,
                gate_mode=m,
                reviewer=FakeReviewer(unavailable={1: unavailable("infrastructure")}),
            )
        ),
    ),
    "review_unavailable_after_a_rejection": (
        MODES,
        _stand_in(
            lambda d, m: Rig(
                d,
                gate_mode=m,
                reviewer=FakeReviewer(
                    verdicts=["fail"], unavailable={2: unavailable("no_verdict")}
                ),
            )
        ),
    ),
    "integration_fails": (
        ("on", "observe"),
        _stand_in(lambda d, m: Rig(d, gate_mode=m, gate=FakeGate(integration_verdict="fail"))),
    ),
    "one_of_two_subtasks_escalated": (
        MODES,
        _stand_in(
            lambda d, m: Rig(d, gate_mode=m, reviewer=FakeReviewer(verdicts=["fail"] * 3)),
            ("s1", "s2"),
        ),
    ),
    "two_subtasks_merged_then_integration_fails": (
        ("on",),
        _stand_in(
            lambda d, m: Rig(d, gate_mode=m, gate=FakeGate(integration_verdict="fail")),
            ("s1", "s2"),
        ),
    ),
}


def records(run_dir: Path) -> dict[str, list[Any]]:
    """The run's records as an exact rerun comparison reads them.

    The harness the run recorded is the checkout the tests run from, which changes with
    every commit, so it is replaced by a placeholder; nothing about escalation reads it.
    """
    out = RunView(run_dir).records()
    for config in out["config"]:
        config["harness"] = "<harness>"
    return {name: out[name] for name in RECORDS}


def scenario_names() -> list[str]:
    """Every scenario, as ``<path>/<gate mode>``, the real-gate runs included."""
    names = [f"{name}/{mode}" for name, (modes, _) in STAND_INS.items() for mode in modes]
    return [*names, *(f"real_gate_three_modes/{mode}" for mode in MODES)]


def build(name: str, root: Path) -> dict[str, list[Any]]:
    """Build the scenario ``name`` under ``root`` and return its records."""
    path, mode = name.split("/")
    if path == "real_gate_three_modes":
        from ui_three_mode_rig import three_mode_runs  # noqa: PLC0415 - real git and gate, slow

        built = three_mode_runs(root, root / "runs")
        return records(next(d for d in built if d.name == f"drive-{mode}"))
    _, run = STAND_INS[path]
    return records(run(root, mode))  # type: ignore[arg-type]


def build_all(root: Path) -> dict[str, dict[str, list[Any]]]:
    """Every scenario's records; the three real-gate runs are built once, together."""
    out: dict[str, dict[str, list[Any]]] = {}
    for name in scenario_names():
        path, mode = name.split("/")
        if path == "real_gate_three_modes":
            continue
        out[name] = build(name, root / name.replace("/", "-"))
    from ui_three_mode_rig import three_mode_runs  # noqa: PLC0415 - real git and gate, slow

    for run_dir in three_mode_runs(root / "real", root / "real" / "runs"):
        out[f"real_gate_three_modes/{run_dir.name.removeprefix('drive-')}"] = records(run_dir)
    return out


def main() -> None:  # pragma: no cover - the script form
    """Rewrite the golden file from the loop as it is now."""
    with tempfile.TemporaryDirectory(prefix="escalation-paths-") as tmp:
        built = build_all(Path(tmp))
    GOLDEN.write_text(json.dumps(built, indent=1, sort_keys=True) + "\n")
    print(f"{len(built)} scenarios written to {GOLDEN}")


if __name__ == "__main__":  # pragma: no cover
    main()
