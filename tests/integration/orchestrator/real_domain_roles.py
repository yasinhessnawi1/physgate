"""The first real control and firmware subtasks, through the whole already-built loop.

Run as a script, never collected as a test, and never without saying which kind:

    python real_domain_roles.py --dry-run --criteria <stamp> --out <dir>  # scripted endpoint
    python real_domain_roles.py --real --criteria <stamp> --out <dir>     # the real API

**A labelled stand-in, not the reference design.** No reference design exists yet for either
module, so this driver uses a narrow, sourced stand-in instead: firmware's ``sample_rate`` and
control's ``loop_gain``, sourced from the Pololu Balboa 32U4 reference firmware's own balance
loop (full citations kept in the private working notes, not repeated in tracked
source), plus the one interface node ``decompose.py``'s ``Plan`` requires. Both proposals and the
interface node are written exactly as sourced, byte for byte — this driver does not re-derive or
rephrase a word of them.

**What it does.** One ``physgate decompose`` call plans both modules, control listed first; one
``physgate run`` dispatches both, control's subtask before firmware's.
- **Why control first:** the controller's design sets the loop rate firmware must meet, so control
  writes the edge that constrains firmware's node, and firmware's node follows it.
- **Why that order matters to the gate:** the propagation check counts a node's creation as a
  change, so a change owes every node it constrains a later rewrite. Written firmware first, the
  firmware node would precede the edge and never be rewritten after it, and the run would
  escalate at integration. Written control first, firmware's node is the rewrite the edge asks
  for.
- An edge may name a node that does not exist yet: nothing checks a target's existence at write
  time.

**The curated content is real.** Nothing is seeded into the target: at decomposition the
orchestrator copies each planned role's curated files from this checkout into the run branch, byte
for byte, and the sessions read those.

The gate is the real registered one. The reviewers are a stub, one per role, so a review stage
runs, spends nothing, and a ledger line never claims a review that did not happen. Handoff happens
only by the graph: control's node ``constrains`` firmware's, and nothing says so anywhere in prose
— proved by an automated grep over the whole target repository's history, not eyeballed.

**What passes.** The run must end ``done`` with the integration gate's verdict ``pass``, on top of
the dispatch, handoff and review checks. A run that ends any other way still writes its full
record, and every check still runs against it, so a failure is reported, not hidden.

**The token.** With ``--real``, read from the comment in ``real_rerun.py`` — unchanged here:
``CLAUDE_CODE_OAUTH_TOKEN`` from the env file, held only in memory, never printed. At the end,
every file under the output directory is scanned for it, for ``sk-ant-`` and for ``oat01``, and
email addresses are replaced; only the counts are printed.
"""

from __future__ import annotations

import argparse
import contextlib
import hashlib
import io
import json
import os
import re
import shutil
import subprocess
import sys
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

HERE = Path(__file__).resolve().parent
REPO_ROOT = HERE.parents[2]
sys.path.insert(0, str(HERE))
sys.path.insert(0, str(REPO_ROOT / "tests"))

from git_rig import Reviewer, target_repo  # noqa: E402
from scripted_endpoint import DUMMY_OAUTH_TOKEN, Script, serving, text, tool  # noqa: E402

from physgate.cli import main as physgate_main  # noqa: E402
from physgate.evaluation.observe.cost import (  # noqa: E402
    append_cost_line,
    load_price_sheet,
    price_run,
)
from physgate.evaluation.observe.manifest import read_manifest  # noqa: E402
from physgate.evaluation.observe.trace import read_traces  # noqa: E402
from physgate.gate.runner import PhysicsGate  # noqa: E402
from physgate.knowledge import loader  # noqa: E402
from physgate.orchestrator.cli import Registrations  # noqa: E402
from physgate.orchestrator.decompose import binary_version, mint_id  # noqa: E402
from physgate.orchestrator.events import (  # noqa: E402
    GateRan,
    IntegrationEscalated,
    IntegrationGateRan,
    Merged,
    ReviewRan,
    read_events,
)
from physgate.orchestrator.install import prepare_install  # noqa: E402
from physgate.orchestrator.invocation import claude_binary  # noqa: E402
from physgate.orchestrator.run_config import ModelStrings, RunBounds, harness_root  # noqa: E402
from physgate.state.protocol import NodeNotFoundError  # noqa: E402
from physgate.state.store import Store  # noqa: E402

VARIABLE = "CLAUDE_CODE_OAUTH_TOKEN"
#: The project's standing model pins: decomposition and both role sessions on Opus; the
#: reviewers (here the stub) on Sonnet.
MODEL = "claude-opus-5-5"
REVIEWER = "claude-sonnet-5"
SEED = 7
PRICES = "2026-09-27"
RUN_ID = "a0-domain-roles"
FIRMWARE_DIR = "modules/firmware"
CONTROL_DIR = "modules/control"
#: Minted the same way the orchestrator mints them, so the dry run can address each
#: session's own worktree by name before either one is dispatched.
CONTROL_ID = mint_id(SEED, 0, "control")
FIRMWARE_ID = mint_id(SEED, 1, "firmware")
EMAIL = re.compile(rb"[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}")

#: The sourced stand-in node proposal, verbatim — not re-derived, not rephrased.
FIRMWARE_PROPOSAL: dict[str, Any] = {
    "id": "firmware.main_loop",
    "kind": "component",
    "domain": "firmware",
    "owner_role": "firmware",
    "quantities": {
        "sample_rate": {
            "value": 100,
            "unit": "Hz",
            "source": (
                "Pololu balboa-32u4-arduino-library, examples/Balancer/Balance.h: 'The "
                "balancing code is all based on a 100 Hz update rate' (UPDATE_TIME_MS = 10), "
                "https://github.com/pololu/balboa-32u4-arduino-library/blob/master/examples/"
                "Balancer/Balance.h, retrieved 2026-10-01"
            ),
            "written_by": "firmware",
        }
    },
    "requirements": [],
    "constrains": [],
    "model": None,
    "geometry_hash": "sha256:0000000000000000000000000000000000000000000000000000000000000",
    "updated": "2026-10-01T00:00:00Z",
}

#: The sourced stand-in node proposal, verbatim. Its ``constrains`` already names
#: ``firmware.main_loop``.
CONTROL_PROPOSAL: dict[str, Any] = {
    "id": "control.loop_gain",
    "kind": "component",
    "domain": "control",
    "owner_role": "control",
    "quantities": {
        "loop_gain": {
            "value": 11,
            "unit": "dimensionless",
            "source": (
                "Pololu balboa-32u4-arduino-library, examples/Balancer/Balance.h, the "
                "ANGLE_RESPONSE constant ('determines the response to a combination of angle "
                "and angle_rate'), declared as a bare int16_t scalar with no physical unit in "
                "the source -- this stand-in treats it as dimensionless. "
                "https://github.com/pololu/balboa-32u4-arduino-library/blob/master/examples/"
                "Balancer/Balance.h, retrieved 2026-10-01"
            ),
            "written_by": "control",
        }
    },
    "requirements": [],
    "constrains": ["firmware.main_loop"],
    "model": None,
    "geometry_hash": "sha256:0000000000000000000000000000000000000000000000000000000000000",
    "updated": "2026-10-01T00:00:00Z",
}

#: The one required interface node, verbatim — ``decompose.py``'s ``Plan.interface_nodes``
#: requires at least one; nothing in these two subtasks needs a shared contract, so no number
#: is invented for it.
INTERFACE: dict[str, Any] = {
    "id": "iface.balance_control.v1",
    "kind": "interface",
    "domain": "cross",
    "owner_role": "control",
    "quantities": {},
    "requirements": [],
    "constrains": [],
    "model": None,
    "geometry_hash": "sha256:0000000000000000000000000000000000000000000000000000000000000",
    "updated": "2026-10-01T00:00:00Z",
}

#: The two module specs, fully prescribed: each session writes the given JSON verbatim, no
#: design judgement asked of it, same discipline as every real dispatch so far.
FIRMWARE_SPEC = (
    "STAND-IN BRIEF, not the reference design. Propose exactly this node, and do nothing else: "
    "write it exactly as the whole content of .physgate/proposals/firmware.main_loop.json:\n\n"
    f"{json.dumps(FIRMWARE_PROPOSAL)}"
    "\n\nWhen the file is written, reply with the single word done.\n"
)
CONTROL_SPEC = (
    "STAND-IN BRIEF, not the reference design. Propose exactly this node, and do nothing else: "
    "write it exactly as the whole content of .physgate/proposals/control.loop_gain.json:\n\n"
    f"{json.dumps(CONTROL_PROPOSAL)}"
    "\n\nWhen the file is written, reply with the single word done.\n"
)
#: The decomposition brief: names both modules, control first and why, and the one interface
#: node, verbatim. A real decomposition model reads this; the scripted endpoint does not.
BRIEF = (
    "STAND-IN BRIEF for the first control and firmware subtasks, not the reference design's "
    "brief.\n\n"
    "Plan exactly two modules, in this order: control first, firmware second. The controller's "
    "design sets the loop rate the firmware must meet, so control writes the node whose "
    "constrains edge names firmware's node, and firmware's node is written after it, following "
    "the edge that constrains it.\n"
    "1. name 'control', role 'control', module_dir 'modules/control', using the text between "
    "the markers below, verbatim, as its specification.\n<<<\n"
    f"{CONTROL_SPEC}>>>\n"
    "2. name 'firmware', role 'firmware', module_dir 'modules/firmware', using the text "
    "between the markers below, verbatim, as its specification.\n<<<\n"
    f"{FIRMWARE_SPEC}>>>\n"
    "Plan exactly one interface node, this one, verbatim:\n"
    f"{json.dumps(INTERFACE)}\n"
)

#: ``.physgate/specs/`` is the orchestrator's own task text (written before either role ran,
#: never a role's prose); ``.physgate/proposals/`` is the graph write itself. Neither is a
#: *handoff* — a role leaving a note for another role instead of a typed graph edge — so both
#: are excluded from the grep below.
_NOT_A_HANDOFF = (".physgate/specs/", ".physgate/proposals/")
#: The handoff quantity's own value, to grep for: the firmware loop period, bare and with its
#: unit.
GREP_PATTERNS = ("100 Hz", "100")


def params() -> dict[str, Any]:
    """The run parameters, as the parameters file holds them."""
    return {
        "auth": "subscription",
        "gate_mode": "on",
        "models": ModelStrings(
            decomposition=MODEL,
            roles={"firmware": MODEL, "control": MODEL},
            reviewers={"firmware": REVIEWER, "control": REVIEWER},
        ).model_dump(),
        "bounds": RunBounds(
            binary_max_retries=0,
            session_wall_clock_s=900.0,
            session_max_turns=20,
            infra_retry_delays_s=(),
        ).model_dump(mode="json"),
        "token_ceiling": 400_000,
        "reportable": True,
        "effort": "high",
        "max_output_tokens": 64000,
        "thinking_display": "summarized",
    }


def registrations() -> Registrations:
    """The real registered gate, and a stub reviewer, one per role.

    No reviewer is registered by default yet, and this run is not reviewers' own acceptance
    test.
    """
    return Registrations(
        gate=PhysicsGate(),
        reviewers={"control": Reviewer(model=REVIEWER), "firmware": Reviewer(model=REVIEWER)},
    )


def utc() -> str:
    return datetime.now(UTC).isoformat(timespec="milliseconds")


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def load_token(env_file: Path) -> str:
    """The token's value from the env file; only that line is read. Never printed."""
    for raw in env_file.read_text().splitlines():
        line = raw.strip().removeprefix("export ").strip()
        if line.startswith(f"{VARIABLE}="):
            value = line.split("=", 1)[1].strip().strip("'\"")
            if value:
                return value
    msg = f"{VARIABLE} is not set in the env file"
    raise SystemExit(msg)


def command(argv: list[str], log: Path) -> int:
    """One ``physgate`` command in this process, its output kept in ``log``."""
    out, err = io.StringIO(), io.StringIO()
    with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
        code = physgate_main(argv, registrations())
    with log.open("a") as f:
        f.write(
            json.dumps(
                {"argv": argv[:1], "code": code, "out": out.getvalue(), "err": err.getvalue()}
            )
            + "\n"
        )
    return code


def tokens(run_dir: Path) -> dict[str, Any]:
    """The run's token account from its own trace: decomposition, each session, reviewers."""
    trace = read_traces(run_dir)
    return {
        "decomposition": trace.decomposition_tokens.model_dump(),
        "sessions": [
            {
                "session_id": s.session_id,
                **s.tokens.model_dump(),
                "wall_clock_s_incl_setup": s.wall_clock_s,
            }
            for s in trace.sessions
        ],
        "reviewer_stub": {k: v.total() for k, v in trace.reviewer_tokens.items()},
        "routing": trace.routing_tokens.total(),
    }


def summary(run_dir: Path, trend: Path) -> dict[str, Any]:
    """The finished run's manifest, tokens and priced cost line."""
    manifest = read_manifest(run_dir)
    line = price_run(run_dir, load_price_sheet(PRICES))
    append_cost_line(trend, line)
    return {
        "manifest_id": manifest.manifest_id,
        "run_id": manifest.config.run_id,
        "endpoint": manifest.config.endpoint,
        "tokens": tokens(run_dir),
        "cost": {
            "basis": line.basis,
            "usd": str(line.usd),
            "nok": str(line.nok),
            "prices": line.prices_date,
        },
        "reviewer_stub_model_pins": {"firmware": REVIEWER, "control": REVIEWER},
    }


def printed_outcome(log: Path) -> dict[str, Any] | None:
    """What the last ``physgate run`` printed, as JSON, or ``None`` if it printed none."""
    for raw in reversed(log.read_text().splitlines()):
        entry = json.loads(raw)
        if entry["argv"] == ["run"]:
            with contextlib.suppress(json.JSONDecodeError):
                printed = json.loads(entry["out"])
                if isinstance(printed, dict):
                    return printed
            return None
    return None


def _library_bytes() -> dict[str, bytes]:
    """This checkout's curated files for both roles, by the path the copy gives them."""
    harness = harness_root()
    if harness is None:
        return {}
    relatives = {p for role in ("control", "firmware") for p in loader.always_loaded(role)}
    return {r.as_posix(): (harness / r).read_bytes() for r in sorted(relatives)}


def grep_proof(repo: Path, store_root: Path) -> dict[str, Any]:
    """The handoff-by-graph proof, run for real: the loop-period value lives only on the graph.

    Greps every file of every commit reachable from any ref of ``repo`` — every subtask
    attempt, the run branch, master — plus every commit message, for ``GREP_PATTERNS``,
    excluding ``_NOT_A_HANDOFF``, and the curated files the orchestrator copied in at
    decomposition wherever their bytes are exactly the library's (a curated file may well
    mention a sample rate; it is not a role's prose). A curated path holding anything
    else counts like any other file. Then confirms the value is present in the merged
    store, which is the one place it is allowed to be.
    """
    library = _library_bytes()
    library_skipped: list[str] = []
    commits = subprocess.run(
        ["git", "-C", str(repo), "log", "--all", "--format=%H"],
        capture_output=True,
        text=True,
        check=True,
    ).stdout.split()
    messages = subprocess.run(
        ["git", "-C", str(repo), "log", "--all", "--format=%B"],
        capture_output=True,
        text=True,
        check=True,
    ).stdout
    prose_hits = [f"a commit message: {p!r}" for p in GREP_PATTERNS if p in messages]
    for commit in commits:
        paths = subprocess.run(
            ["git", "-C", str(repo), "ls-tree", "-r", "--name-only", commit],
            capture_output=True,
            text=True,
            check=True,
        ).stdout.splitlines()
        for path in paths:
            if any(path.startswith(prefix) for prefix in _NOT_A_HANDOFF):
                continue
            raw = subprocess.run(
                ["git", "-C", str(repo), "show", f"{commit}:{path}"],
                capture_output=True,
                check=True,
            ).stdout
            if path in library and raw == library[path]:
                library_skipped.append(f"{path} @ {commit[:8]}")
                continue
            content = raw.decode(errors="replace")
            for pattern in GREP_PATTERNS:
                if pattern in content:
                    prose_hits.append(f"{path} @ {commit[:8]}: {pattern!r}")
    node_hits = [
        f"{candidate.relative_to(store_root)}: {pattern!r}"
        for candidate in sorted(store_root.rglob("*"))
        if candidate.is_file()
        for pattern in GREP_PATTERNS
        if pattern in candidate.read_text(errors="ignore")
    ]
    return {
        "commits_searched": len(commits),
        "curated_copies_not_searched": library_skipped,
        "prose_hits": prose_hits,
        "node_hits": node_hits,
        "pass": not prose_hits and bool(node_hits),
    }


def curated_proof(repo: Path) -> dict[str, Any]:
    """The curated files the sessions read are the real library, not a fixture.

    Every always-loaded file of both roles, as the run branch holds it (which is
    where each session's worktree branched from), against this checkout's own
    library, byte for byte; a fixture is a few dozen bytes, a curated file
    thousands.
    """
    harness = harness_root()
    branch = f"physgate/{RUN_ID}/run"
    files: dict[str, dict[str, Any]] = {}
    relatives = {p for role in ("control", "firmware") for p in loader.always_loaded(role)}
    for relative in sorted(relatives):
        shown = subprocess.run(
            ["git", "-C", str(repo), "show", f"{branch}:{relative.as_posix()}"],
            capture_output=True,
            check=False,
        ).stdout
        real = (harness / relative).read_bytes() if harness is not None else None
        files[relative.as_posix()] = {"bytes": len(shown), "equals_library": shown == real}
    return {
        "files": files,
        "pass": bool(files)
        and all(f["equals_library"] and f["bytes"] > 1000 for f in files.values()),
    }


def _node(store: Store, node_id: str) -> dict[str, Any] | None:
    """A node's payload, or ``None`` if the run never wrote it: a failed run is still reported."""
    try:
        return store.read_node(node_id)
    except NodeNotFoundError:
        return None


def check_criteria(
    run_dir: Path, repo: Path, store_root: Path, run_exit: int, outcome: dict[str, Any] | None
) -> dict[str, Any]:
    """Automated proof, against this run's own records: dispatch, merge, handoff, review, end.

    Every check runs whatever the run's ending, so a run that escalates or stops early still
    reports which checks held and which did not.
    """
    events = read_events(run_dir / "events.jsonl")
    seen_order: list[str] = []
    for event in events:
        subtask_id = getattr(event, "subtask_id", None)
        if subtask_id and subtask_id not in seen_order:
            seen_order.append(subtask_id)
    dispatch_order = [s for s in seen_order if s in (CONTROL_ID, FIRMWARE_ID)]

    gate_verdicts = {
        subtask: [
            e.result.verdict for e in events if isinstance(e, GateRan) and e.subtask_id == subtask
        ]
        for subtask in (CONTROL_ID, FIRMWARE_ID)
    }
    merged = {
        subtask: any(isinstance(e, Merged) and e.subtask_id == subtask for e in events)
        for subtask in (CONTROL_ID, FIRMWARE_ID)
    }
    integration = next((e for e in events if isinstance(e, IntegrationGateRan)), None)
    escalated = [e.item_id for e in events if isinstance(e, IntegrationEscalated)]
    step = None if outcome is None else outcome.get("step")
    open_items = None if outcome is None else outcome.get("open_queue_items")
    ended_done = run_exit == 0 and step == "done" and open_items == [] and not escalated
    integration_pass = integration is not None and integration.result.verdict == "pass"

    store = Store(store_root)
    try:
        firmware_node = _node(store, "firmware.main_loop")
        control_node = _node(store, "control.loop_gain")
        traversal = (
            store.traverse_constrains("control.loop_gain") if control_node is not None else []
        )
    finally:
        store.close()

    grep = grep_proof(repo, store_root)
    curated = curated_proof(repo)
    # A review stage really ran for both subtasks (never skipped), its pinned stub model
    # string is the one recorded in the event, and it spent nothing — the observable signal
    # that a ledger line's review is the stub, not a widening of the frozen outcome literal.
    review_ran = {
        subtask: next(
            (e.result for e in events if isinstance(e, ReviewRan) and e.subtask_id == subtask),
            None,
        )
        for subtask in (CONTROL_ID, FIRMWARE_ID)
    }
    reviewer_model_pins = {s: (r.reviewer_model if r else None) for s, r in review_ran.items()}
    reviewer_zero = all(r is not None and len(r.usage) == 0 for r in review_ran.values())

    written_by = (
        None
        if firmware_node is None
        else firmware_node["quantities"].get("sample_rate", {}).get("written_by")
    )
    constrains_edge = control_node is not None and "firmware.main_loop" in control_node.get(
        "constrains", []
    )
    gates_pass = all(v == ["pass"] for v in gate_verdicts.values())
    review_ran_for_both = all(r is not None for r in review_ran.values())
    pins_hold = all(p == REVIEWER for p in reviewer_model_pins.values())

    return {
        "control_subtask_id": CONTROL_ID,
        "firmware_subtask_id": FIRMWARE_ID,
        "dispatch_order": dispatch_order,
        "control_then_firmware_dispatched": dispatch_order == [CONTROL_ID, FIRMWARE_ID],
        "gate_verdicts": gate_verdicts,
        "both_gates_pass": gates_pass,
        "merged": merged,
        "both_merged": all(merged.values()),
        "run_exit": run_exit,
        "run_step": step,
        "open_queue_items": open_items,
        "integration_escalated": escalated,
        "ended_done": ended_done,
        "integration_gate_verdict": integration.result.verdict if integration else None,
        "integration_gate_finding": integration.result.finding if integration else None,
        "integration_gate_pass": integration_pass,
        "handoff_firmware_node_present": firmware_node is not None,
        "handoff_control_node_present": control_node is not None,
        "handoff_firmware_node_written_by": written_by,
        "handoff_edge_on_graph": constrains_edge,
        "handoff_traversal_includes_firmware": "firmware.main_loop" in traversal,
        "handoff_grep": grep,
        "curated_content": curated,
        "review_ran_for_both": review_ran_for_both,
        "reviewer_tokens_zero": reviewer_zero,
        "reviewer_model_pins": reviewer_model_pins,
        "reviewer_model_pins_expected": REVIEWER,
        # The run passes only if it ends done with the integration gate passing, on top of the
        # dispatch, handoff and review checks: control first is known to merge clean, so an
        # escalation here would be something unexpected, never a pass.
        "all_pass": (
            dispatch_order == [CONTROL_ID, FIRMWARE_ID]
            and gates_pass
            and all(merged.values())
            and ended_done
            and integration_pass
            and written_by == "firmware"
            and constrains_edge
            and "firmware.main_loop" in traversal
            and grep["pass"]
            and curated["pass"]
            and review_ran_for_both
            and pins_hold
            and reviewer_zero
        ),
    }


def scan(root: Path, token: str) -> dict[str, int]:
    """Counts only: files holding the token, ``sk-ant-`` or ``oat01``; emails replaced."""
    files = [p for p in root.rglob("*") if p.is_file() and not p.is_symlink()]
    counts = {"token": 0, "sk-ant-": 0, "oat01": 0, "emails_replaced": 0}
    for path in files:
        data = path.read_bytes()
        counts["token"] += token.encode() in data
        counts["sk-ant-"] += b"sk-ant-" in data
        counts["oat01"] += b"oat01" in data
        found = len(EMAIL.findall(data))
        records = (root / "install") not in path.parents
        if found and records and path.suffix in (".json", ".jsonl", ".log", ".txt", ".md", ".out"):
            path.write_bytes(EMAIL.sub(b"<email>", data))
            counts["emails_replaced"] += found
    return counts


def dry_script(api: Any) -> None:  # noqa: ANN401
    """The scripted endpoint as the model: the plan, then each role's own reads and write."""
    plan = tool(
        "StructuredOutput",
        modules=[
            {"name": "control", "role": "control", "module_dir": CONTROL_DIR, "spec": CONTROL_SPEC},
            {
                "name": "firmware",
                "role": "firmware",
                "module_dir": FIRMWARE_DIR,
                "spec": FIRMWARE_SPEC,
            },
        ],
        interface_nodes=[INTERFACE],
    )
    firmware_steps = [
        *(
            tool("Read", file_path=f"{{cwd}}/{relative.as_posix()}")
            for relative in loader.always_loaded("firmware")
        ),
        tool("Read", file_path="{cwd}/.physgate/specs/{cwd_name}.md"),
        tool(
            "Write",
            file_path="{cwd}/.physgate/proposals/firmware.main_loop.json",
            content=json.dumps(FIRMWARE_PROPOSAL),
        ),
        text("done"),
    ]
    control_steps = [
        *(
            tool("Read", file_path=f"{{cwd}}/{relative.as_posix()}")
            for relative in loader.always_loaded("control")
        ),
        tool("Read", file_path="{cwd}/.physgate/specs/{cwd_name}.md"),
        tool(
            "Write",
            file_path="{cwd}/.physgate/proposals/control.loop_gain.json",
            content=json.dumps(CONTROL_PROPOSAL),
        ),
        text("done"),
    ]

    def on_request(thread: str, cwd: str, done: int) -> dict[str, Any] | None:
        if thread != "main":
            return None
        if cwd.endswith("/decomposition/cwd") and done == 0:
            return plan
        if cwd.endswith(f"/worktrees/{FIRMWARE_ID}"):
            return firmware_steps[done] if done < len(firmware_steps) else text("done")
        if cwd.endswith(f"/worktrees/{CONTROL_ID}"):
            return control_steps[done] if done < len(control_steps) else text("done")
        return None

    api.script = Script(main=[])
    api.on_request = on_request


def one_run(root: Path) -> dict[str, Any]:
    # Nothing curated is seeded here: at decomposition the orchestrator copies each
    # planned role's real curated files from this checkout into the run branch, and
    # the sessions read those.
    repo = target_repo(root)
    install = root / "install"
    prepare_install(install, REPO_ROOT)
    (root / "brief.md").write_text(BRIEF)
    (root / "params.json").write_text(json.dumps(params()))
    log = root / "commands.jsonl"
    run_dir = root / RUN_ID
    common = ["--target", str(repo)]
    code = command(
        [
            "decompose",
            str(root / "brief.md"),
            "--seed",
            str(SEED),
            "--run-id",
            RUN_ID,
            "--params",
            str(root / "params.json"),
            *common,
            "--run-dir",
            str(run_dir),
        ],
        log,
    )
    result: dict[str, Any] = {"decompose_exit": code}
    if code != 0:
        result["stopped"] = "decomposition did not start a run; nothing more was called"
        return result
    result["run_exit"] = command(
        [
            "run",
            "--run-dir",
            str(run_dir),
            *common,
            "--install",
            str(install),
            "--review-root",
            str(root / "review-scratch"),
        ],
        log,
    )
    outcome = printed_outcome(log)
    result["run_outcome"] = outcome
    # Whatever the ending — done, escalated, or stopped — the run's own records are read and
    # every check runs against them, so a failed real run still produces a full report. Only a
    # run that left no event log at all has nothing to read.
    if not (run_dir / "events.jsonl").exists():
        result["stopped"] = "the run left no event log; nothing more could be checked"
        return result
    if result["run_exit"] == 0:
        result["summary"] = summary(run_dir, root / "cost_trend.jsonl")
    else:
        # No manifest is written for a run that did not finish, so no priced cost line; the
        # token account is read from the trace instead, and a failure to read it is recorded.
        try:
            result["tokens_unfinished_run"] = tokens(run_dir)
        except Exception as exc:  # recorded, never hidden: the report must still be written
            result["tokens_unfinished_run"] = f"{type(exc).__name__}: {exc}"
    result["criteria"] = check_criteria(
        run_dir, repo, run_dir / "store", result["run_exit"], outcome
    )
    return result


def main() -> None:
    parser = argparse.ArgumentParser()
    kind = parser.add_mutually_exclusive_group(required=True)
    kind.add_argument("--dry-run", action="store_true", help="scripted endpoint, dummy token")
    kind.add_argument("--real", action="store_true", help="the real API, on the subscription")
    parser.add_argument("--criteria", type=Path, required=True, help="the criteria stamped first")
    parser.add_argument("--out", type=Path, required=True)
    parser.add_argument("--env-file", type=Path, default=Path.home() / "dev" / "physgate" / ".env")
    args = parser.parse_args()
    root = args.out.resolve()
    root.mkdir(parents=True)
    version = binary_version()  # refused unless it is the pinned one

    def git(*a: str) -> str:
        return subprocess.run(
            ["git", *a], cwd=REPO_ROOT, capture_output=True, text=True, check=False
        ).stdout.strip()

    stamp = {
        "kind": "dry-run" if args.dry_run else "real",
        "commit": git("rev-parse", "HEAD"),
        "dirty": bool(git("status", "--porcelain")),
        "script_sha256": sha256(Path(__file__)),
        "criteria_sha256": sha256(args.criteria),
        "binary_version": version,
        "binary_sha256": sha256(Path(shutil.which(claude_binary()) or claude_binary())),
        "started_utc": utc(),
    }
    print(json.dumps(stamp), flush=True)
    token = DUMMY_OAUTH_TOKEN if args.dry_run else load_token(args.env_file)
    for name in ("ANTHROPIC_API_KEY", "ANTHROPIC_AUTH_TOKEN", "ANTHROPIC_BASE_URL"):
        os.environ.pop(name, None)
    os.environ[VARIABLE] = token
    os.environ["DISABLE_AUTOUPDATER"] = "1"
    try:
        if args.dry_run:
            with serving(Script(main=[])) as (api, url):
                dry_script(api)
                os.environ["ANTHROPIC_BASE_URL"] = url
                result = one_run(root)
                result["endpoint_failures"] = list(api.failures)
                result["endpoint_requests"] = len(api.requests)
        else:
            result = one_run(root)
    finally:
        os.environ.pop(VARIABLE, None)
    result["finished_utc"] = utc()
    (root / "result.json").write_text(json.dumps({**stamp, **result}, indent=1, sort_keys=True))
    result["scan"] = scan(root, token)
    (root / "result.json").write_text(json.dumps({**stamp, **result}, indent=1, sort_keys=True))
    print(
        json.dumps(
            {
                "scan": result["scan"],
                "run_exit": result.get("run_exit"),
                "ended_done": result.get("criteria", {}).get("ended_done"),
                "integration_gate_verdict": result.get("criteria", {}).get(
                    "integration_gate_verdict"
                ),
                "all_pass": result.get("criteria", {}).get("all_pass"),
            }
        ),
        flush=True,
    )


if __name__ == "__main__":
    main()
