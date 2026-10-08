"""The first real paired reviews: the control and firmware subtasks, reviewed, then one baseline.

Run as a script, never collected as a test, and never without saying which kind:

    python real_paired_reviewers.py paired --dry-run --criteria <stamp> --out <p>
    python real_paired_reviewers.py paired --real --criteria <stamp> --out <p>
    python real_paired_reviewers.py generalist --dry-run --criteria <stamp> --paired <p> --out <g>
    python real_paired_reviewers.py generalist --real --criteria <stamp> --paired <p> --out <g>

**The paired run.** The same two stand-in subtasks as the first control and firmware run
(``real_domain_roles.py``: the same brief, specifications, proposals, interface node, pins and
settings, control first), through ``physgate decompose`` and ``physgate run``, now with the
registrations the command ships with: the physics gate and a paired Claude reviewer per role,
each judging with its role's promoted rubric. The checks, run against the run's own records
whatever its ending:

- every subtask's attempts that passed the gate were reviewed, each review on the role's pinned
  reviewer model, with the promoted rubric's digest, its packet's digest, its reading verified,
  and its output limit and peak context recorded; the reviewer model is never the implementer's;
- each such review is on the task ledger (``review_result``), and the gate events of the same
  attempt carry the reviewer's verdict (``reviewer_had_passed``);
- an attempt a review rejected was followed by one whose instruction carries that review's
  finding; a run in which no review rejects says so, rather than passing that check.

**The baseline.** ``physgate generalist`` on the control subtask's last reviewed attempt of the
finished paired run: the same attempt reviewed again by the same reviewer with the control rubric
less its domain sections, then paired over generalist tokens and cost, n = 1. The paired run's
cost line, with what reviewing spent by subtask, is written beside it.

The dry run serves every session from the scripted endpoint. Its reviewer reads every file it
must and gives a verdict on the role's real rubric, every item answered; the control subtask's
first review rejects, so the repair path runs. The baseline's dry run serves on the address the
paired dry run recorded, which the run holds every later command to.

**The token.** With ``--real``, ``CLAUDE_CODE_OAUTH_TOKEN`` is read from the env file by this
script, held only in memory and never printed. At the end every file under the output directory
is scanned for it, for ``sk-ant-`` and for ``oat01``, and email addresses are replaced; only the
counts are printed.
"""

from __future__ import annotations

import argparse
import contextlib
import io
import json
import os
import shutil
import subprocess
import sys
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
sys.path.insert(0, str(HERE.parents[1]))

import real_domain_roles as base  # noqa: E402
from scripted_endpoint import DUMMY_OAUTH_TOKEN, Script, serving, text, tool  # noqa: E402

from physgate.cli import main as physgate_main  # noqa: E402
from physgate.evaluation.observe.cost import load_price_sheet, price_run  # noqa: E402
from physgate.knowledge.promote import KNOWLEDGE_ROOT, PROMOTIONS_NAME  # noqa: E402
from physgate.orchestrator.cli import default_registrations  # noqa: E402
from physgate.orchestrator.decompose import binary_version  # noqa: E402
from physgate.orchestrator.events import (  # noqa: E402
    ReviewRan,
    ReviewUnavailable,
    RunStarted,
    SessionEnded,
    read_events,
)
from physgate.orchestrator.gate_events import gate_events  # noqa: E402
from physgate.orchestrator.invocation import claude_binary  # noqa: E402
from physgate.orchestrator.run_config import load_run_config  # noqa: E402
from physgate.reviewers.contract import issued_criteria  # noqa: E402
from physgate.reviewers.packet import (  # noqa: E402
    DIFF_NAME,
    RECORD_NAME,
    SPEC_AS_ISSUED_NAME,
    WORKTREE_NAME,
)
from physgate.reviewers.places import require_review_root  # noqa: E402
from physgate.reviewers.rubric import NOT_IN_REVIEW, parse_rubric  # noqa: E402
from physgate.state.task_ledger import TaskLedger  # noqa: E402

RUN_ID = "a1-paired-reviewers"
GENERALIST_RUN_ID = "a1-generalist-baseline"
ROLES = {base.CONTROL_ID: "control", base.FIRMWARE_ID: "firmware"}
#: Where reviews are prepared, beneath each phase's output directory, as the first run's driver
#: names it; checked before anything runs, so an output path a reviewer could read something
#: into is refused at once.
REVIEW_DIRNAME = "review-scratch"


def command(argv: list[str], log: Path) -> int:
    """One ``physgate`` command in this process, with the shipped registrations."""
    out, err = io.StringIO(), io.StringIO()
    with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
        code = physgate_main(argv, default_registrations())
    with log.open("a") as f:
        entry = {"argv": argv[:1], "code": code, "out": out.getvalue(), "err": err.getvalue()}
        f.write(json.dumps(entry) + "\n")
    return code


def promoted_rubrics() -> dict[str, str]:
    """Each role's rubric digest, as its last promotion line in this checkout records it."""
    found: dict[str, str] = {}
    for line in (base.REPO_ROOT / KNOWLEDGE_ROOT / PROMOTIONS_NAME).read_text().splitlines():
        event = json.loads(line)
        if event.get("kind") == "rubric":
            found[event["domain"]] = event["sha256"]
    return found


def check_paired(run_dir: Path, review_root: Path) -> dict[str, Any]:
    """The paired reviews, against the run's own records, whatever its ending."""
    events = read_events(run_dir / "events.jsonl")
    config = load_run_config(run_dir / "run.json")
    rubrics = promoted_rubrics()
    reviews = [e for e in events if isinstance(e, ReviewRan)]
    unavailable = [e for e in events if isinstance(e, ReviewUnavailable)]
    per_review = []
    for review in reviews:
        result, role = review.result, ROLES.get(review.subtask_id, "?")
        packet = review_root / result.session_id / RECORD_NAME
        per_review.append(
            {
                "subtask": review.subtask_id,
                "attempt": review.attempt,
                "verdict": result.verdict,
                "failing_item": result.failing_item,
                "on_pinned_model": result.reviewer_model == config.models.reviewers.get(role),
                "not_the_implementer_s": result.reviewer_model != config.models.roles.get(role),
                "rubric_is_promoted": result.rubric_sha256 == rubrics.get(role),
                "rubric_kind": result.rubric_kind,
                "packet_recorded": packet.is_file() and result.packet_sha256 is not None,
                "reading_verified": result.reading_verified is True,
                "max_output_tokens": result.max_output_tokens,
                "context_window": result.context_window,
                "peak_context_tokens": result.peak_context_tokens,
                "schema_refusals": result.schema_refusals,
                "criteria_lines": len(result.criteria),
                "tokens": sum(m.usage.total() for m in result.usage),
            }
        )
    ledger = {line.id: line for line in TaskLedger(run_dir / "ledger.jsonl").read_all()}
    on_ledger = all(
        ledger.get(r.subtask_id) is not None and ledger[r.subtask_id].review_result is not None
        for r in reviews
    )
    (started,) = [e for e in events if isinstance(e, RunStarted)]
    stamped = gate_events(events, started.config_sha256)
    stamped_ok = all(
        any(
            g.subtask_id == r.subtask_id
            and g.attempt == r.attempt
            and g.reviewer_had_passed == (r.result.verdict == "pass")
            for g in stamped
        )
        for r in reviews
    )
    prompts = {}
    for record in sorted((run_dir / "sessions").glob("*/process.json")):
        spawned = json.loads(record.read_text())
        argv = spawned["argv"]
        prompts[spawned["session_id"]] = argv[argv.index("-p") + 1]
    ended = [e for e in events if isinstance(e, SessionEnded)]
    rejections = [r for r in reviews if r.result.verdict == "fail"]
    repaired = []
    for rejected in rejections:
        nexts = [
            e
            for e in ended
            if e.subtask_id == rejected.subtask_id and e.attempt == rejected.attempt + 1
        ]
        carries = any(rejected.result.finding in prompts.get(e.session_id, "") for e in nexts)
        repaired.append({"subtask": rejected.subtask_id, "next_attempt_carries_finding": carries})
    subtasks_reviewed = {r.subtask_id for r in reviews}
    # A review ends in a verdict when its last line for an attempt is a review, not unavailable.
    last_line: dict[tuple[str, int], str] = {}
    for event in events:
        if isinstance(event, ReviewRan | ReviewUnavailable) and not (
            isinstance(event, ReviewUnavailable) and event.retry
        ):
            last_line[(event.subtask_id, event.attempt)] = event.kind
    checks = {
        "every_review_ends_in_a_verdict": bool(last_line)
        and all(kind == "review_ran" for kind in last_line.values()),
        "every_subtask_reviewed": subtasks_reviewed == set(ROLES),
        "every_review_well_formed": bool(per_review)
        and all(
            r["on_pinned_model"]
            and r["not_the_implementer_s"]
            and r["rubric_is_promoted"]
            and r["rubric_kind"] == "paired"
            and r["packet_recorded"]
            and r["reading_verified"]
            and r["max_output_tokens"] == config.max_output_tokens
            and bool(r["criteria_lines"])
            for r in per_review
        ),
        "every_review_on_the_ledger": bool(reviews) and on_ledger,
        "gate_events_carry_the_reviewer_verdict": bool(reviews) and stamped_ok,
        "repair_carries_the_finding": (
            all(r["next_attempt_carries_finding"] for r in repaired) if repaired else None
        ),
    }
    return {
        "reviews": per_review,
        "reviews_unavailable": [
            {"subtask": e.subtask_id, "attempt": e.attempt, "cause": e.cause, "retry": e.retry}
            for e in unavailable
        ],
        "rejections_followed": repaired,
        "checks": checks,
        "all_pass": all(v is not False for v in checks.values())
        and checks["repair_carries_the_finding"] is not False,
        "repair_path_exercised": bool(repaired),
    }


def _reading(cwd: str) -> list[str]:
    read = Path(cwd).parent
    files = sorted(p for p in read.rglob("*") if p.is_file() and p != read / DIFF_NAME)
    return [str(p) for p in files if (read / WORKTREE_NAME) not in p.parents]


#: A clean answer in each section's own words.
CLEAN = {
    "acceptance_criteria": "met",
    "domain_standards": "n/a",
    "antipatterns": "n/a",
    "reward_hacking": "not observed",
}


def _verdict(cwd: str, reject: bool) -> dict[str, Any]:
    """A verdict on the packet's own rubric: every item answered; the scan's hits dismissed."""
    read = Path(cwd).parent
    rubric = (read / "rubric.md").read_text()
    kind = "generalist" if NOT_IN_REVIEW in rubric else "paired"
    items = parse_rubric(rubric, kind)  # type: ignore[arg-type]
    first = next(i for i in items if i.section == "acceptance_criteria")
    packet = json.loads((read.parent / RECORD_NAME).read_text())
    issued = read / SPEC_AS_ISSUED_NAME
    criteria = issued_criteria(issued.read_text() if issued.is_file() else None)
    return {
        "verdict": "reject" if reject else "accept",
        "finding": "the stand-in's gain is not the specified one" if reject else "every item met",
        "failing_item": first.id if reject else None,
        "subject": "control.loop_gain" if reject else None,
        "numeric_output": {"value": 11, "unit": "dimensionless"} if reject else None,
        "items": {
            i.id: {
                "result": "unmet" if reject and i.id == first.id else CLEAN[i.section],
                "evidence": "diff.patch: the one proposal file it adds",
            }
            for i in items
        },
        "acceptance_criteria": [
            {
                "criterion": ref,
                "result": "unmet" if reject else "met",
                "evidence": "worktree: the proposal file, as specified",
            }
            for ref in criteria or ("the node is written exactly as specified",)
        ],
        "indicators": [
            {
                "kind": hit["kind"],
                "evidence": hit["evidence"],
                "disposition": "dismissed",
                "reason": "the stand-in specification asks for exactly this",
            }
            for hit in packet["indicators"]
        ],
        "spec_defects": [],
    }


def dry_reviews(api: Any) -> None:  # noqa: ANN401
    """Wrap the first run's scripted sessions with a scripted reviewer for every review."""
    roles = api.on_request
    reviewed: list[str] = []

    def on_request(thread: str, cwd: str, done: int) -> dict[str, Any] | None:
        if not cwd.endswith(f"/read/{WORKTREE_NAME}"):
            return roles(thread, cwd, done) if roles is not None else None
        packet = json.loads((Path(cwd).parent.parent / RECORD_NAME).read_text())
        if packet["artefact"]["assigned_role"] == "control" and cwd not in reviewed:
            reviewed.append(cwd)
        # The control subtask's first paired review rejects, so the repair path runs.
        rubric = (Path(cwd).parent / "rubric.md").read_text()
        first_control = bool(reviewed) and reviewed[0] == cwd and NOT_IN_REVIEW not in rubric
        steps = [tool("Read", file_path=p) for p in _reading(cwd)]
        steps.append(tool("StructuredOutput", **_verdict(cwd, reject=first_control)))
        return steps[done] if done < len(steps) else text("done")

    api.on_request = on_request


def paired(root: Path) -> dict[str, Any]:
    result = base.one_run(root)  # decompose and run, with the shipped registrations
    # The first run's own checks, kept as they are: those about its review stub (a review that
    # spends nothing, one gate pass per subtask) do not describe a run with real reviewers.
    result["first_run_checks"] = result.pop("criteria", None)
    run_dir = root / base.RUN_ID
    if (run_dir / "events.jsonl").exists():
        result["reviews"] = check_paired(run_dir, root / REVIEW_DIRNAME)
    return result


def generalist(paired_root: Path, out: Path) -> dict[str, Any]:
    run_dir = paired_root / base.RUN_ID
    events = read_events(run_dir / "events.jsonl")
    reviewed = [e for e in events if isinstance(e, ReviewRan) and e.subtask_id == base.CONTROL_ID]
    if not reviewed:
        return {"stopped": "the paired run holds no review of the control subtask"}
    attempt = reviewed[-1].attempt
    log = out / "commands.jsonl"
    code = command(
        [
            "generalist",
            *("--run-dir", str(run_dir), "--subtask", base.CONTROL_ID, "--attempt", str(attempt)),
            *("--target", str(paired_root / "target"), "--install", str(paired_root / "install")),
            *("--review-root", str(paired_root / REVIEW_DIRNAME)),
            *("--out", str(out / "generalist")),
            *("--run-id", GENERALIST_RUN_ID, "--prices", base.PRICES),
        ],
        log,
    )
    found: dict[str, Any] = {"generalist_exit": code, "attempt": attempt}
    baseline = out / "generalist" / "baseline.json"
    if baseline.is_file():
        found["baseline"] = json.loads(baseline.read_text())
    with contextlib.suppress(Exception):
        line = price_run(run_dir, load_price_sheet(base.PRICES))
        found["paired_run_cost"] = json.loads(line.model_dump_json())
    return found


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("phase", choices=["paired", "generalist"])
    kind = parser.add_mutually_exclusive_group(required=True)
    kind.add_argument("--dry-run", action="store_true", help="scripted endpoint, dummy token")
    kind.add_argument("--real", action="store_true", help="the real API, on the subscription")
    parser.add_argument("--criteria", type=Path, required=True, help="the criteria stamped first")
    parser.add_argument("--out", type=Path, required=True)
    parser.add_argument("--paired", type=Path, help="generalist: the paired run's --out")
    parser.add_argument("--env-file", type=Path, default=Path.home() / "dev" / "physgate" / ".env")
    args = parser.parse_args()
    if args.phase == "generalist" and args.paired is None:
        parser.error("generalist needs --paired, the paired run's output directory")
    root = args.out.resolve()
    require_review_root(root / REVIEW_DIRNAME)  # before anything exists or runs
    if args.phase == "generalist":
        require_review_root(args.paired.resolve() / REVIEW_DIRNAME)
    root.mkdir(parents=True)
    version = binary_version()  # refused unless it is the pinned one

    def git(*a: str) -> str:
        done = subprocess.run(
            ["git", *a], cwd=base.REPO_ROOT, capture_output=True, text=True, check=False
        )
        return done.stdout.strip()

    stamp = {
        "phase": args.phase,
        "kind": "dry-run" if args.dry_run else "real",
        "commit": git("rev-parse", "HEAD"),
        "dirty": bool(git("status", "--porcelain")),
        "script_sha256": base.sha256(Path(__file__)),
        "criteria_sha256": base.sha256(args.criteria),
        "binary_version": version,
        "binary_sha256": base.sha256(Path(shutil.which(claude_binary()) or claude_binary())),
        "promoted_rubrics": promoted_rubrics(),
        "started_utc": base.utc(),
    }
    print(json.dumps(stamp), flush=True)
    token = DUMMY_OAUTH_TOKEN if args.dry_run else base.load_token(args.env_file)
    for name in ("ANTHROPIC_API_KEY", "ANTHROPIC_AUTH_TOKEN", "ANTHROPIC_BASE_URL"):
        os.environ.pop(name, None)
    os.environ[base.VARIABLE] = token
    os.environ["DISABLE_AUTOUPDATER"] = "1"
    # The first run's driver commands, with the shipped registrations in place of its stub.
    base.command = command
    base.RUN_ID = RUN_ID
    try:
        if args.phase == "paired":
            if args.dry_run:
                with serving(Script(main=[])) as (api, url):
                    base.dry_script(api)
                    dry_reviews(api)
                    os.environ["ANTHROPIC_BASE_URL"] = url
                    result = paired(root)
                    result["endpoint_failures"] = list(api.failures)
                    result["endpoint_requests"] = len(api.requests)
            else:
                result = paired(root)
        else:
            paired_root = args.paired.resolve()
            if args.dry_run:
                recorded = load_run_config(paired_root / RUN_ID / "run.json").endpoint
                port = urlparse(recorded).port or 0
                with serving(Script(main=[]), port=port) as (api, url):
                    dry_reviews(api)
                    os.environ["ANTHROPIC_BASE_URL"] = url
                    result = generalist(paired_root, root)
                    result["endpoint_failures"] = list(api.failures)
            else:
                result = generalist(paired_root, root)
    finally:
        os.environ.pop(base.VARIABLE, None)
    result["finished_utc"] = base.utc()
    result["scan"] = base.scan(root, token)
    (root / "result.json").write_text(json.dumps({**stamp, **result}, indent=1, sort_keys=True))
    reviews = result.get("reviews", {})
    print(
        json.dumps(
            {
                "scan": result["scan"],
                "run_exit": result.get("run_exit"),
                "reviews_all_pass": reviews.get("all_pass") if reviews else None,
                "repair_path_exercised": reviews.get("repair_path_exercised") if reviews else None,
                "generalist_exit": result.get("generalist_exit"),
                "token_ratio": (result.get("baseline") or {}).get("token_ratio"),
            }
        ),
        flush=True,
    )


if __name__ == "__main__":
    main()
