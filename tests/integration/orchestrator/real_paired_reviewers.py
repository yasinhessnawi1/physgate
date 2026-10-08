"""The first real paired reviews: the control and firmware subtasks, reviewed, then one baseline.

Run as a script, never collected as a test, and never without saying which kind:

    python real_paired_reviewers.py preflight --dry-run --criteria <stamp> --out <f>
    python real_paired_reviewers.py preflight --real --criteria <stamp> --out <f>
    python real_paired_reviewers.py paired --dry-run --criteria <stamp> --out <p>
    python real_paired_reviewers.py paired --real --criteria <stamp> --out <p>
    python real_paired_reviewers.py generalist --dry-run --criteria <stamp> --paired <p> --out <g>
    python real_paired_reviewers.py generalist --real --criteria <stamp> --paired <p> --out <g>

**The pre-flight.** Before the paired run: one short session per role, offered the verdict
schema its reviews will be offered, asked for one call, one turn, with no file tool and a
small output limit. It shows only that the API takes the schema and that the binary compiles
it without a strict-mode warning, at a few cents; it scores nothing.

**The paired run.** The two subtasks of the first control and firmware run
(``real_domain_roles.py``: its firmware specification and proposal, interface node, pins and
settings, control first), with two changes. The control subtask's issued specification is a
reviewable fixture (``control_fixture_spec.md``, held to its sha256), a balance-loop design task
drafted from sources and reviewed adversarially, in place of the stand-in that dictated one
literal node; the decomposition brief embeds it verbatim, as it embedded the stand-in. And the
session bounds are 40 turns and 4500 s (``SESSION_MAX_TURNS``, ``SESSION_WALL_CLOCK_S``). It runs
through ``physgate decompose`` and ``physgate run`` with the registrations the command ships with:
the physics gate and a paired Claude reviewer per role, each judging with its role's promoted
rubric. The checks, run against the run's own records whatever its ending:

- every subtask's attempts that passed the gate were reviewed, each review on the role's pinned
  reviewer model, with the promoted rubric's digest, its packet's digest, its reading verified,
  and its output limit and peak context recorded; the reviewer model is never the implementer's;
- each such review is on the task ledger (``review_result``), and the gate events of the same
  attempt carry the reviewer's verdict (``reviewer_had_passed``), or none for a blocked review,
  which is a verdict but neither a pass nor a fail; a blocked review counts as a review;
- an attempt a review rejected was followed by one whose instruction carries that review's
  finding; a run in which no review rejects says so, rather than passing that check.

**The baseline.** ``physgate generalist`` on the control subtask's last reviewed attempt of the
finished paired run: the same attempt reviewed again by the same reviewer with the control rubric
less its domain sections, then paired over generalist tokens and cost, n = 1. The paired run's
cost line, with what reviewing spent by subtask, is written beside it.

The dry run serves every session from the scripted endpoint. Its control session does the
fixture's work at the size the bounds were set for: about thirty-five tool turns of writing,
running and re-running analysis code whose printed output fills the transcript, then the node
of the fixture's section 10 with placeholder values. Its reviewer reads every file it must, a
long one in pieces, and gives a verdict on the role's real rubric, every item and every issued
criterion answered; the control subtask's first review rejects, so the repair path runs, or with
``--dry-control blocked`` is blocked on a blocking specification defect, so the blocked path
runs. The baseline's dry run serves on the address the paired dry run recorded, which the run
holds every later command to.

**The token.** With ``--real``, ``CLAUDE_CODE_OAUTH_TOKEN`` is read from the env file by this
script, held only in memory and never printed. At the end every file under the output directory
is scanned for it, for ``sk-ant-`` and for ``oat01``, and email addresses are replaced; only the
counts are printed.
"""

from __future__ import annotations

import argparse
import contextlib
import hashlib
import io
import json
import os
import shutil
import subprocess
import sys
import uuid
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
from physgate.knowledge import loader  # noqa: E402
from physgate.knowledge.promote import KNOWLEDGE_ROOT, PROMOTIONS_NAME  # noqa: E402
from physgate.orchestrator.cli import default_registrations  # noqa: E402
from physgate.orchestrator.credentials import remove_secrets, write_login  # noqa: E402
from physgate.orchestrator.decompose import binary_version, read_stream  # noqa: E402
from physgate.orchestrator.events import (  # noqa: E402
    ReviewRan,
    ReviewUnavailable,
    RunStarted,
    SessionEnded,
    read_events,
)
from physgate.orchestrator.gate_events import gate_events  # noqa: E402
from physgate.orchestrator.invocation import (  # noqa: E402
    REVIEWER_ENV,
    claude_binary,
    isolated_env,
)
from physgate.orchestrator.run_config import RunBounds, load_run_config  # noqa: E402
from physgate.reviewers.claude import SYNTHETIC_MODEL  # noqa: E402
from physgate.reviewers.contract import issued_criteria, verdict_schema  # noqa: E402
from physgate.reviewers.packet import (  # noqa: E402
    DIFF_NAME,
    RECORD_NAME,
    SPEC_AS_ISSUED_NAME,
    WORKTREE_NAME,
)
from physgate.reviewers.places import require_review_root  # noqa: E402
from physgate.reviewers.rubric import (  # noqa: E402
    NOT_IN_REVIEW,
    load_rubric,
    not_evaluable_needs,
    parse_rubric,
)
from physgate.state.task_ledger import TaskLedger  # noqa: E402

RUN_ID = "a1-paired-reviewers"
GENERALIST_RUN_ID = "a1-generalist-baseline"
ROLES = {base.CONTROL_ID: "control", base.FIRMWARE_ID: "firmware"}
#: Where reviews are prepared, beneath each phase's output directory, as the first run's driver
#: names it; checked before anything runs, so an output path a reviewer could read something
#: into is refused at once.
REVIEW_DIRNAME = "review-scratch"

#: The control subtask's issued specification: the reviewable fixture, byte for byte as it was
#: frozen. It is read from the file beside this driver and held to its digest before use.
CONTROL_FIXTURE = HERE / "control_fixture_spec.md"
CONTROL_FIXTURE_SHA256 = "f2a7080355c587a6925c992fdcb377ae20ba3458f6dc41f4d07143c3be16bf88"
#: The session bounds the fixture was sized for: its upper estimate is 31 turns and 3200 s.
SESSION_MAX_TURNS = 40
SESSION_WALL_CLOCK_S = 4500.0


def control_fixture_spec() -> str:
    """The fixture's text, refused unless its bytes are the frozen ones."""
    data = CONTROL_FIXTURE.read_bytes()
    found = hashlib.sha256(data).hexdigest()
    if found != CONTROL_FIXTURE_SHA256:
        msg = f"the control fixture is not the frozen one: sha256 {found}"
        raise SystemExit(msg)
    return data.decode("utf-8")


def brief(control_spec: str) -> str:
    """The decomposition brief: the first run's, with the fixture as control's specification."""
    return (
        "BRIEF for the paired-review run's control and firmware subtasks, not the reference "
        "design's brief. Control's specification is a reviewable fixture; firmware's is a "
        "labelled stand-in.\n\n"
        "Plan exactly two modules, in this order: control first, firmware second. The "
        "controller's design sets the loop rate the firmware must meet, so control writes the "
        "node whose constrains edge names firmware's node, and firmware's node is written after "
        "it, following the edge that constrains it.\n"
        "1. name 'control', role 'control', module_dir 'modules/control', using the text between "
        "the markers below, verbatim, as its specification.\n<<<\n"
        f"{control_spec}>>>\n"
        "2. name 'firmware', role 'firmware', module_dir 'modules/firmware', using the text "
        "between the markers below, verbatim, as its specification.\n<<<\n"
        f"{base.FIRMWARE_SPEC}>>>\n"
        "Plan exactly one interface node, this one, verbatim:\n"
        f"{json.dumps(base.INTERFACE)}\n"
    )


#: The first run's parameters, kept before ``use_fixture`` points its driver at ours.
FIRST_RUN_PARAMS = base.params


def params() -> dict[str, Any]:
    """The first run's parameters, with the session bounds the fixture needs."""
    found = FIRST_RUN_PARAMS()
    found["bounds"] = RunBounds(
        binary_max_retries=0,
        session_wall_clock_s=SESSION_WALL_CLOCK_S,
        session_max_turns=SESSION_MAX_TURNS,
        infra_retry_delays_s=(),
    ).model_dump(mode="json")
    return found


def use_fixture() -> str:
    """Point the first run's driver at the fixture and the bounds; return the fixture's text."""
    spec = control_fixture_spec()
    base.CONTROL_SPEC = spec
    base.BRIEF = brief(spec)
    base.params = params
    return spec


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


def _stamp(review: ReviewRan) -> bool | None:
    """What the gate events of a review's attempt say of it: nothing, for a blocked one."""
    return None if review.result.verdict == "blocked" else review.result.verdict == "pass"


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
            and g.reviewer_had_passed == _stamp(r)
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


#: The most a scripted reviewer asks of one Read: the binary refuses a read whose content is
#: over its token limit and asks for an offset and a limit instead, as a reviewer then pages.
READ_CHUNK_BYTES = 60_000


def _reads(path: str) -> list[dict[str, Any]]:
    """The Read calls that show every line of ``path``: one, or pages of whole lines.

    Lines are counted as the Read tool counts them: a file ending in a newline has one more,
    empty, line after it, which a page must reach too.
    """
    lines = Path(path).read_bytes().split(b"\n")
    if sum(len(line) for line in lines) <= READ_CHUNK_BYTES:
        return [tool("Read", file_path=path)]
    calls, start, size = [], 0, 0
    for index, line in enumerate(lines):
        if size and size + len(line) > READ_CHUNK_BYTES:
            calls.append(tool("Read", file_path=path, offset=start + 1, limit=index - start))
            start, size = index, 0
        size += len(line)
    calls.append(tool("Read", file_path=path, offset=start + 1, limit=len(lines) - start))
    return calls


#: A clean answer in each section's own words.
CLEAN = {
    "acceptance_criteria": "met",
    "domain_standards": "n/a",
    "antipatterns": "n/a",
    "reward_hacking": "not observed",
}


def _verdict(cwd: str, reject: bool, *, blocked: bool = False) -> dict[str, Any]:
    """A verdict on the packet's own rubric: every item answered; the scan's hits dismissed.

    ``blocked`` answers one domain-standards item not evaluable, with a blocking defect of the
    issued specification naming it, and nothing rejecting.
    """
    read = Path(cwd).parent
    rubric = (read / "rubric.md").read_text()
    kind = "generalist" if NOT_IN_REVIEW in rubric else "paired"
    items = parse_rubric(rubric, kind)  # type: ignore[arg-type]
    first = next(i for i in items if i.section == "acceptance_criteria")
    packet = json.loads((read.parent / RECORD_NAME).read_text())
    issued = read / SPEC_AS_ISSUED_NAME
    criteria = issued_criteria(issued.read_text() if issued.is_file() else None)
    if blocked:
        answer = _verdict(cwd, reject=False)
        held = next(i.id for i in items if i.section == "domain_standards")
        answer["verdict"] = "blocked"
        answer["finding"] = f"{held} cannot be decided: the issued specification lacks its input"
        answer["items"][held] = {"result": "not evaluable", "evidence": "spec_as_issued.md"}
        answer["spec_defects"] = [
            {"finding": "the input this check needs is not given", "blocking": True, "item": held}
        ]
        return answer
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


#: A placeholder a dry run writes, never a design value.
DRY = "scripted dry run placeholder, not a design: modules/control/results.txt"
#: The node of the fixture's section 10, as a dry run fills it: every listed quantity with its
#: listed unit, and placeholder values.
DRY_NODE_UNITS = {
    "sample_rate": (100, "Hz"),
    "sample_period": (0.01, "s"),
    "unstable_pole": (8.56, "rad/s"),
    "gain_crossover_frequency": (14.0, "rad/s"),
    "phase_margin": (0.74, "rad"),
    "gain_margin_upper": (2.4, "dimensionless"),
    "gain_margin_lower": (0.42, "dimensionless"),
    "stability_margin": (0.52, "dimensionless"),
    "sensitivity_peak": (1.92, "dimensionless"),
    "complementary_sensitivity_peak": (1.93, "dimensionless"),
    "loop_delay_total": (0.01545, "s"),
    "loop_delay_common": (0.008, "s"),
    "delay_margin": (0.03, "s"),
    "actuator_voltage_limit": (5.4, "V"),
    "actuator_voltage_rate_limit": (216000, "V/s"),
    "available_bandwidth": (33.3, "rad/s"),
}


def dry_node() -> dict[str, Any]:
    """The fixture's node template with placeholder values, as the dry control session writes it."""
    return {
        "id": "control.loop_gain",
        "kind": "component",
        "domain": "control",
        "owner_role": "control",
        "quantities": {
            name: {"value": value, "unit": unit, "source": DRY, "written_by": "control"}
            for name, (value, unit) in DRY_NODE_UNITS.items()
        },
        "requirements": ["the balance loop runs every 0.01 s (placeholder)"],
        "constrains": ["firmware.main_loop"],
        "model": "scripted dry run placeholder: no plant, estimator or controller is designed",
        "geometry_hash": "sha256:" + "0" * 64,
        "updated": "2026-10-08T12:00:00Z",
    }


#: The dry session's analysis script: deterministic tables of about 20 KB per run, so the
#: transcript grows as a real design session's would; it designs nothing.
DRY_ANALYSIS = """# Scripted dry run placeholder: tables of the size a real analysis prints.
import math

WEIGHT = 1.0
CASES = ("nominal", "l_low", "l_high", "jm_low", "jm_high")

for k, case in enumerate(CASES):
    p = 7.70 + 0.2 * k
    print(f"case {case}: p = {p:.4f} rad/s (placeholder)")
    for i in range(70):
        w = 0.1 * 1.07 ** i
        mag = WEIGHT * p / math.hypot(w, p)
        print(f"  w={w:10.5f} |L|={mag:10.6f} arg={-math.degrees(math.atan2(w, p)):9.4f} deg")
print(f"weight {WEIGHT}")
"""
DRY_SIMULATE = """# Scripted dry run placeholder: one line per edge run, as a simulation reports.
import random

random.seed(7)
print("seed 7")
for case in ("nominal", "l_low", "l_high", "jm_low", "jm_high"):
    for edge in ("theta+", "theta-", "speed+", "speed-"):
        for push in ("+", "-"):
            print(f"{case:8} {edge:7} push{push} recovered t={random.uniform(1, 4):.3f} s")
"""
DRY_CONTROLLER = """# Scripted dry run placeholder: the shape of controller.py, no designed values.
H = 0.01
LIMIT_COUNTS = 300
GAINS = (0.0, 0.0, 0.0, 0.0)


def step(state, measurement):
    return 0
"""
#: Re-runs of the analysis after an edit, as tuning to the margins takes: eleven cycles.
DRY_TUNING_CYCLES = 11


def dry_fixture_session() -> list[dict[str, Any]]:
    """The dry control session's steps: the fixture's work at the size the bounds allow for."""
    mod = "{cwd}/" + base.CONTROL_DIR
    run = f"cd {{cwd}} && python3 {base.CONTROL_DIR}/analysis.py"
    steps = [
        *(
            tool("Read", file_path=f"{{cwd}}/{relative.as_posix()}")
            for relative in loader.always_loaded("control")
        ),
        tool("Read", file_path="{cwd}/.physgate/specs/{cwd_name}.md"),
        tool("Write", file_path=f"{mod}/controller.py", content=DRY_CONTROLLER),
        tool("Write", file_path=f"{mod}/analysis.py", content=DRY_ANALYSIS),
        tool("Bash", command=run),
    ]
    for cycle in range(DRY_TUNING_CYCLES):
        before, after = f"WEIGHT = 1.{cycle}", f"WEIGHT = 1.{cycle + 1}"
        steps.append(
            tool("Edit", file_path=f"{mod}/analysis.py", old_string=before, new_string=after)
        )
        steps.append(tool("Bash", command=run))
    results = f"{base.CONTROL_DIR}/results.txt"
    steps += [
        tool("Write", file_path=f"{mod}/simulate.py", content=DRY_SIMULATE),
        tool("Bash", command=f"cd {{cwd}} && python3 {base.CONTROL_DIR}/simulate.py"),
        tool(
            "Bash",
            command=(
                f"cd {{cwd}} && python3 {base.CONTROL_DIR}/analysis.py > {results}"
                f" && python3 {base.CONTROL_DIR}/simulate.py >> {results}"
            ),
        ),
        tool(
            "Write",
            file_path="{cwd}/.physgate/proposals/control.loop_gain.json",
            content=json.dumps(dry_node()),
        ),
        text("done: scripted dry run placeholder; no criterion is claimed."),
    ]
    return steps


def dry_control(api: Any) -> None:  # noqa: ANN401
    """Serve the control subtask's sessions with the fixture's dry session, every attempt."""
    inner = api.on_request
    steps = dry_fixture_session()

    def on_request(thread: str, cwd: str, done: int) -> dict[str, Any] | None:
        if thread == "main" and cwd.endswith(f"/worktrees/{base.CONTROL_ID}"):
            return steps[done] if done < len(steps) else text("done")
        return inner(thread, cwd, done) if inner is not None else None

    api.on_request = on_request


def dry_reviews(api: Any, control: str = "reject") -> None:  # noqa: ANN401
    """Wrap the first run's scripted sessions with a scripted reviewer for every review.

    ``control`` is what the control subtask's first paired review submits: a reject, so the
    repair path runs, or a blocked verdict, so the blocked path does.
    """
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
        steps = [call for p in _reading(cwd) for call in _reads(p)]
        blocked = first_control and control == "blocked"
        submitted = _verdict(cwd, reject=first_control and not blocked, blocked=blocked)
        steps.append(tool("StructuredOutput", review=submitted))
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
    result["control_spec_issued"] = issued_control_spec(root / "target")
    return result


def issued_control_spec(repo: Path) -> dict[str, Any]:
    """The control subtask's specification as the run issued it, against the fixture's digest.

    Reported, not scored: the decomposition model copies the specification from the brief,
    and a copy that is not byte for byte the fixture is seen here.
    """
    shown = subprocess.run(
        [
            *("git", "-C", str(repo), "show"),
            f"physgate/{base.RUN_ID}/run:.physgate/specs/{base.CONTROL_ID}.md",
        ],
        capture_output=True,
        check=False,
    )
    if shown.returncode != 0:
        return {"sha256": None, "is_the_fixture": False}
    digest = hashlib.sha256(shown.stdout).hexdigest()
    return {
        "sha256": digest,
        "bytes": len(shown.stdout),
        "is_the_fixture": digest == CONTROL_FIXTURE_SHA256,
    }


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


#: What the pre-flight asks of each reviewer session: one call, any values.
PREFLIGHT_PROMPT = "Reply by calling the StructuredOutput tool once, with any values it accepts."
#: The output limit of a pre-flight session: enough for the API to take the request and the
#: model to begin its answer; the answer itself is not wanted.
PREFLIGHT_OUTPUT_TOKENS = 2000


def preflight(root: Path, token: str, base_url: str | None) -> dict[str, Any]:
    """One short reviewer session per role, with the schema its reviews will be offered.

    Each role's schema counts the criteria its issued specification numbers, as its reviews'
    will. It shows only that the API takes the schema: the session is answered by the pinned
    reviewer model and not refused with a 400, and the binary compiles the schema with no
    strict-mode warning. One turn, no file tool, the output limit small.
    """
    found: dict[str, Any] = {}
    issued = {"control": base.CONTROL_SPEC, "firmware": base.FIRMWARE_SPEC}
    for role in ("control", "firmware"):
        rubric = load_rubric(base.REPO_ROOT / KNOWLEDGE_ROOT, role)
        criteria = issued_criteria(issued[role])
        schema = verdict_schema(
            rubric.items, criteria=criteria, scan_hits=(), not_evaluable=not_evaluable_needs(role)
        )
        sdir = root / "preflight" / role
        (sdir / "home").mkdir(parents=True)
        config_dir = sdir / "config"
        write_login(config_dir, token)
        env = isolated_env(
            home=sdir / "home",
            config_dir=config_dir,
            binary=claude_binary(),
            max_retries=0,
            max_output_tokens=PREFLIGHT_OUTPUT_TOKENS,
            base_url=base_url,
            api_key=None,
        )
        env.update(REVIEWER_ENV)
        argv = [
            claude_binary(),
            *("-p", PREFLIGHT_PROMPT, "--setting-sources", "", "--tools", ""),
            *("--json-schema", json.dumps(schema, sort_keys=True, separators=(",", ":"))),
            *("--model", base.REVIEWER, "--effort", "low", "--max-turns", "1"),
            *("--output-format", "stream-json", "--verbose", "--include-partial-messages"),
            *("--session-id", str(uuid.uuid4()), "--permission-mode", "bypassPermissions"),
        ]
        try:
            done = subprocess.run(
                argv,
                cwd=sdir / "home",
                env=env,
                stdin=subprocess.DEVNULL,
                capture_output=True,
                text=True,
                timeout=600,
                check=False,
            )
        finally:
            remove_secrets(sdir, config_dir)
        (sdir / "stdout.jsonl").write_text(done.stdout)
        (sdir / "stderr.txt").write_text(done.stderr)
        result, usage, answered = read_stream(done.stdout)
        refused = result is not None and result.get("api_error_status") == 400
        models = sorted(answered - {SYNTHETIC_MODEL})
        warnings = [line for line in done.stderr.splitlines() if "strict mode" in line]
        found[role] = {
            "schema_bytes": len(argv[argv.index("--json-schema") + 1]),
            "issued_criteria": len(criteria) if criteria else None,
            "answered_by": models,
            "refused_400": refused,
            "api_error": (result or {}).get("result") if refused else None,
            "strict_mode_warnings": len(warnings),
            "total_cost_usd": (result or {}).get("total_cost_usd"),
            "tokens": sum(m.usage.total() for m in usage),
            "accepted": (not refused) and models == [base.REVIEWER] and not warnings,
        }
    found["all_accepted"] = all(found[r]["accepted"] for r in ("control", "firmware"))
    return found


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("phase", choices=["preflight", "paired", "generalist"])
    kind = parser.add_mutually_exclusive_group(required=True)
    kind.add_argument("--dry-run", action="store_true", help="scripted endpoint, dummy token")
    kind.add_argument("--real", action="store_true", help="the real API, on the subscription")
    parser.add_argument("--criteria", type=Path, required=True, help="the criteria stamped first")
    parser.add_argument("--out", type=Path, required=True)
    parser.add_argument("--paired", type=Path, help="generalist: the paired run's --out")
    parser.add_argument(
        "--dry-control",
        choices=["reject", "blocked"],
        default="reject",
        help="dry run: the control subtask's first paired review rejects, or is blocked",
    )
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
        "control_fixture_sha256": hashlib.sha256(use_fixture().encode()).hexdigest(),
        "session_bounds": {"max_turns": SESSION_MAX_TURNS, "wall_clock_s": SESSION_WALL_CLOCK_S},
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
    result: dict[str, Any]
    try:
        if args.phase == "preflight":
            if args.dry_run:
                # The scripted endpoint refuses what the API is known to refuse.
                with serving(Script(main=[text("done")])) as (api, url):
                    result = {"preflight": preflight(root, token, url)}
                    result["endpoint_refusals"] = list(api.refusals)
            else:
                result = {"preflight": preflight(root, token, None)}
        elif args.phase == "paired":
            if args.dry_run:
                with serving(Script(main=[])) as (api, url):
                    base.dry_script(api)
                    dry_control(api)
                    dry_reviews(api, args.dry_control)
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
                "preflight_all_accepted": (result.get("preflight") or {}).get("all_accepted"),
                "token_ratio": (result.get("baseline") or {}).get("token_ratio"),
            }
        ),
        flush=True,
    )


if __name__ == "__main__":
    main()
