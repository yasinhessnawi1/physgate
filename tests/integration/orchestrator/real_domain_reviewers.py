"""Six real reviews by the electrical and mechanical reviewers, after a schema pre-flight.

Run as a script, never collected as a test, and never without saying which kind:

    python real_domain_reviewers.py preflight --dry-run --criteria <stamp> --out <dir>
    python real_domain_reviewers.py preflight --real --criteria <stamp> --out <dir>
    python real_domain_reviewers.py reviews --dry-run --criteria <stamp> --out <dir>
    python real_domain_reviewers.py reviews --real --criteria <stamp> --out <dir>
    python real_domain_reviewers.py reviews --real --criteria <stamp> --out <dir> \
        --only e-consistent,m-consistent,m-attempt

**The pre-flight.** One short session per schema a review below is offered, four in all: each
role, once for a revision issued with no specification and once for an attempt whose issued
specification numbers two criteria. One turn, no file tool, a small output limit. It shows
only that the API takes the schema and that the binary compiles it with no strict-mode
warning.

**The reviews.** The six artefacts of ``domain_review_artefacts``, each reviewed once by its
role's Claude reviewer, judging with the role's promoted rubric, on ``claude-sonnet-5``:

- **The four revisions issued with no specification** are reviewed exactly as the
  injected-error instrument reviews an artefact. The given design and the revision are
  written through the real store into a fresh worktree (``materialise``), and the account is
  held to have no telltale and no answer (``require_blind``). The review then reads them under
  their seal, as an account, with no specification. A test holds that this matches the
  instrument's own per-artefact review.
- **The two attempts** carry an issued specification, committed before the attempt, with the
  role's curated files beside it as decomposition puts them. The attempt's commit and a
  hand-written stand-in of the implementing session's stream go with them. No role session
  runs: the electrical and mechanical roles are not in the role register.

Each review is retried once for an infrastructure cause, as the loop's review is, and the
outcome is recorded as it ended. A review with no verdict is ``review_unavailable``, never an
accept or a reject. Every review and its tokens go to this run's own event log. Its cost is
priced at the dated sheet, as a list-price estimate.

**A re-run** of some of the reviews names them with ``--only``; the run's first line records
which, and nothing else is made or reviewed.

**What is reported, and what is not.** Each artefact's verdict is set beside the verdict its
author expected (``EXPECTED``), and the run says which verdict forms it observed. It claims
no rate: there are six artefacts, written for this. The criteria stamp, hashed before the run,
says what is scored.

**The token.** With ``--real``, ``CLAUDE_CODE_OAUTH_TOKEN`` is read from the env file by this
script, held only in memory and never printed. At the end every file under the output
directory is scanned for it, for ``sk-ant-`` and for ``oat01``, and only the counts are
printed; nothing is rewritten.
"""

from __future__ import annotations

import argparse
import dataclasses
import functools
import hashlib
import json
import os
import shutil
import subprocess
import sys
import time
import uuid
from decimal import Decimal
from pathlib import Path
from typing import Any, Literal

HERE = Path(__file__).resolve().parent
REPO_ROOT = HERE.parents[2]
sys.path.insert(0, str(HERE))
sys.path.insert(0, str(REPO_ROOT / "tests"))

import domain_review_artefacts as artefacts  # noqa: E402
from record_scan import INSTALL_DIRNAME  # noqa: E402
from record_scan import scan as record_scan  # noqa: E402
from scripted_endpoint import DUMMY_OAUTH_TOKEN, Script, serving, text, tool  # noqa: E402

from physgate.evaluation.inject.corpus import Base, Patch  # noqa: E402
from physgate.evaluation.inject.materialise import materialise, require_blind  # noqa: E402
from physgate.evaluation.observe.cost import load_price_sheet  # noqa: E402
from physgate.evaluation.observe.generalist import review_retried_once  # noqa: E402
from physgate.hooks.reading import content_lines  # noqa: E402
from physgate.knowledge.library import put_into, read_library  # noqa: E402
from physgate.knowledge.promote import KNOWLEDGE_ROOT  # noqa: E402
from physgate.orchestrator.credentials import (  # noqa: E402
    Credential,
    remove_secrets,
    write_login,
)
from physgate.orchestrator.decompose import binary_version as version_of  # noqa: E402
from physgate.orchestrator.decompose import read_stream  # noqa: E402
from physgate.orchestrator.events import (  # noqa: E402
    EventLog,
    ReviewRan,
    RunStarted,
    SubtaskPlanned,
    TokensUsed,
)
from physgate.orchestrator.exceptions import ReviewUnavailableError  # noqa: E402
from physgate.orchestrator.install import prepare_install  # noqa: E402
from physgate.orchestrator.invocation import (  # noqa: E402
    REVIEWER_ENV,
    claude_binary,
    isolated_env,
)
from physgate.orchestrator.protocols import Artefact, IssuedSpec, ReviewResult, Usage  # noqa: E402
from physgate.orchestrator.run_config import RunBounds  # noqa: E402
from physgate.orchestrator.trajectory import seal  # noqa: E402
from physgate.reviewers.claude import SYNTHETIC_MODEL, ClaudeReviewer, ReviewerSetup  # noqa: E402
from physgate.reviewers.contract import (  # noqa: E402
    CONSISTENCY,
    issued_criteria,
    verdict_schema,
)
from physgate.reviewers.packet import RECORD_NAME, SPEC_AS_ISSUED_NAME  # noqa: E402
from physgate.reviewers.places import require_review_root  # noqa: E402
from physgate.reviewers.rubric import load_rubric, not_evaluable_needs, parse_rubric  # noqa: E402

VARIABLE = "CLAUDE_CODE_OAUTH_TOKEN"
REVIEWER = "claude-sonnet-5"
#: The model the stand-in session streams name: the implementers' pin.
IMPLEMENTER = "claude-opus-5-5"
RUN_ID = "a4a-domain-reviews"
SEED = 7
PRICES = "2026-09-27"
ROLES = ("electrical", "mechanical")
REVIEW_DIRNAME = "review-scratch"
#: The bounds of a reviewer session, as the paired reviews' last real runs used them.
BOUNDS = RunBounds(
    binary_max_retries=0,
    session_wall_clock_s=4500.0,
    session_max_turns=80,
    infra_retry_delays_s=(60.0, 300.0),
)
EFFORT: Literal["high"] = "high"
MAX_OUTPUT_TOKENS = 64000
TOKEN_CEILING = 2_000_000
PREFLIGHT_PROMPT = "Reply by calling the StructuredOutput tool once, with any values it accepts."
PREFLIGHT_OUTPUT_TOKENS = 2000
GIT_ENV = {
    "GIT_AUTHOR_NAME": "design",
    "GIT_AUTHOR_EMAIL": "design@localhost",
    "GIT_COMMITTER_NAME": "design",
    "GIT_COMMITTER_EMAIL": "design@localhost",
    "GIT_AUTHOR_DATE": "2026-10-16T12:00:00Z",
    "GIT_COMMITTER_DATE": "2026-10-16T12:00:00Z",
}


def utc() -> str:
    return time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def review_id(artefact_id: str) -> str:
    """A neutral id for one artefact's review, so no path a reviewer reads names the artefact."""
    return "r" + hashlib.sha256(f"{SEED}:{artefact_id}".encode()).hexdigest()[:12]


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


def promoted_rubrics() -> dict[str, str]:
    """Each reviewed role's promoted rubric digest, as the reviews will load it."""
    return {r: load_rubric(REPO_ROOT / KNOWLEDGE_ROOT, r).sha256 for r in ROLES}


# --- The artefacts ---------------------------------------------------------------------------


def wrap_revision(
    subtask_id: str,
    role: str,
    given: tuple[dict[str, Any], ...],
    revision: tuple[dict[str, Any], ...],
    answers: tuple[str, ...],
    place: Path,
) -> Artefact:
    """A revision issued with no specification, made real and wrapped as the instrument does.

    The same calls, in the same order, as the instrument's per-artefact review
    (``runner._review``): write the given design and the revision, hold what the reviewer
    is shown to no telltale and no answer, seal the account, and name it an account. A unit
    test holds the two to the same artefact. The one difference is the corpus format's rule
    for how a source is written, which these artefacts do not follow (see below).
    """
    # The corpus format would hold every source to a URL or arithmetic over rows of a parts
    # sheet the reviewer is never shown; these artefacts cite their sources in words, so a
    # reviewer can check them by reading. Nothing else is built differently.
    base = Base.model_construct(label="a design", nodes=given)
    made = materialise(base, Patch.model_construct(nodes=revision), place)
    require_blind(made, answers)
    sealed = seal(made.trajectory.read_bytes())
    return Artefact(
        subtask_id=subtask_id,
        attempt=1,
        assigned_role=role,
        attempt_commit=made.commit,
        worktree=str(made.worktree),
        graph_root=str(made.graph_root),
        trajectory=str(made.trajectory),
        trajectory_sha256=sealed.sha256,
        trajectory_length=sealed.length,
        trajectory_form="account",
        scopes=("subtask", "module"),
        base_revision=made.baseline,
        base_commit=made.base_commit,
        repository=str(made.worktree),
    )


def revision_artefact(artefact_id: str, place: Path) -> Artefact:
    """One of the revisions of ``domain_review_artefacts``, wrapped for its review."""
    role, given, revision = artefacts.REVISIONS[artefact_id]
    answers = (artefact_id, artefacts.EXPECTED[artefact_id][2])
    return wrap_revision(review_id(artefact_id), role, given, revision, answers, place)


def _git(cwd: Path, *args: str) -> str:
    done = subprocess.run(
        ["git", "-c", "commit.gpgsign=false", *args],
        cwd=cwd,
        env={**os.environ, **GIT_ENV},
        capture_output=True,
        text=True,
        check=True,
    )
    return done.stdout.strip()


def _event(kind: str, **fields: Any) -> str:  # noqa: ANN401 - an event's own fields
    return json.dumps({"type": kind, **fields}) + "\n"


def stand_in_stream(
    cwd: Path, reads: list[tuple[str, str]], write: tuple[str, str], summary: str
) -> str:
    """A hand-written stand-in of an implementing session's stream, in the binary's format."""
    lines = [
        _event("system", subtype="init", model=IMPLEMENTER, cwd=str(cwd), tools=["Read", "Write"])
    ]
    calls = [*(("Read", {"file_path": str(cwd / p)}, body) for p, body in reads)]
    calls.append(
        (
            "Write",
            {"file_path": str(cwd / write[0]), "content": write[1]},
            f"File created successfully at: {cwd / write[0]}",
        )
    )
    for n, (name, given, result) in enumerate(calls):
        use = f"toolu_{n:04d}"
        message = {
            "id": f"msg_{n:04d}",
            "model": IMPLEMENTER,
            "role": "assistant",
            "content": [{"type": "tool_use", "id": use, "name": name, "input": given}],
        }
        lines.append(_event("assistant", message=message))
        answer = {
            "role": "user",
            "content": [{"type": "tool_result", "tool_use_id": use, "content": result}],
        }
        lines.append(_event("user", message=answer))
    last = {
        "id": f"msg_{len(calls):04d}",
        "model": IMPLEMENTER,
        "role": "assistant",
        "content": [{"type": "text", "text": summary}],
    }
    lines.append(_event("assistant", message=last))
    lines.append(_event("result", subtype="success", is_error=False, result=summary))
    return "".join(lines)


def attempt_artefact(artefact_id: str, place: Path) -> Artefact:
    """An attempt at a subtask: its issued specification, its commit and a stand-in stream."""
    role, spec, proposal, summary = artefacts.ATTEMPTS[artefact_id]
    rid = review_id(artefact_id)
    repo = place / "target"
    repo.mkdir(parents=True)
    _git(repo, "init", "-q", "-b", "run")
    curated = read_library(REPO_ROOT, [role])
    put_into(repo, curated)
    spec_path = f".physgate/specs/{rid}.md"
    (repo / spec_path).parent.mkdir(parents=True)
    (repo / spec_path).write_text(spec)
    _git(repo, "add", "-A")
    _git(repo, "commit", "-q", "-m", "issue the module specification")
    issued_by = _git(repo, "rev-parse", "HEAD")
    proposal_path = f".physgate/proposals/{proposal['id']}.json"
    body = json.dumps(proposal, indent=1, sort_keys=True) + "\n"
    (repo / proposal_path).parent.mkdir(parents=True)
    (repo / proposal_path).write_text(body)
    _git(repo, "add", "-A")
    _git(repo, "commit", "-q", "-m", "the attempt")
    reads = [(rel.as_posix(), data.decode()) for rel, data in sorted(curated.items())]
    reads.append((spec_path, spec))
    stream = place / "session" / "stdout.jsonl"
    stream.parent.mkdir(parents=True)
    stream.write_text(stand_in_stream(repo, reads, (proposal_path, body), summary))
    sealed = seal(stream.read_bytes())
    return Artefact(
        subtask_id=rid,
        attempt=1,
        assigned_role=role,
        attempt_commit=_git(repo, "rev-parse", "HEAD"),
        worktree=str(repo),
        graph_root=str(repo / "store"),
        trajectory=str(stream),
        trajectory_sha256=sealed.sha256,
        trajectory_length=sealed.length,
        scopes=("subtask",),
        base_revision=0,
        base_commit=issued_by,
        issued_spec=IssuedSpec(
            commit=issued_by, path=spec_path, sha256=hashlib.sha256(spec.encode()).hexdigest()
        ),
        repository=str(repo),
    )


def selected(only: str | None) -> tuple[str, ...]:
    """The artefacts to review, in the driver's order: every one, or those ``only`` names.

    ``only`` is a comma-separated list of artefact ids.

    Raises:
        ValueError: ``only`` is empty, or names an artefact twice or one the driver lacks.
    """
    every = (*artefacts.REVISIONS, *artefacts.ATTEMPTS)
    if only is None:
        return every
    names = only.split(",")
    unknown = [n for n in names if n not in every]
    if not only or unknown or len(set(names)) != len(names):
        msg = f"a re-run names each review it runs once, from {', '.join(every)}: {only!r}"
        raise ValueError(msg)
    return tuple(aid for aid in every if aid in names)


def all_artefacts(root: Path, only: tuple[str, ...] | None = None) -> list[tuple[str, Artefact]]:
    """Every artefact, or those in ``only``, made in a fixed order: revisions, then attempts."""
    chosen = selected(None) if only is None else only
    made = []
    for artefact_id in artefacts.REVISIONS:
        if artefact_id in chosen:
            place = root / "made" / review_id(artefact_id)
            made.append((artefact_id, revision_artefact(artefact_id, place)))
    for artefact_id in artefacts.ATTEMPTS:
        if artefact_id in chosen:
            place = root / "made" / review_id(artefact_id)
            made.append((artefact_id, attempt_artefact(artefact_id, place)))
    return made


# --- The scripted reviewer of a dry run -------------------------------------------------------

CLEAN = {
    "acceptance_criteria": "met",
    "domain_standards": "n/a",
    "antipatterns": "n/a",
    "reward_hacking": "not observed",
}


def _reads(path: str) -> list[dict[str, Any]]:
    lines = content_lines(Path(path).read_bytes())
    if lines <= 1:
        return [tool("Read", file_path=path)]
    half = lines // 2
    return [
        tool("Read", file_path=path, offset=1, limit=half),
        tool("Read", file_path=path, offset=half + 1, limit=lines - half),
    ]


def scripted_verdict(
    read: Path, packet: dict[str, Any], verdict: str, deciding: tuple[str, ...] = ()
) -> dict[str, Any]:
    """A verdict on the packet's own rubric, of the form ``verdict``, every item answered."""
    items = parse_rubric((read / "rubric.md").read_text())
    first = {s: next(i.id for i in items if i.section == s) for s in CLEAN}
    issued = read / SPEC_AS_ISSUED_NAME
    criteria = issued_criteria(issued.read_text()) if issued.is_file() else None
    answers = {
        i.id: {"result": CLEAN[i.section], "evidence": "worktree: the node files"} for i in items
    }
    lines: list[dict[str, Any]]
    if issued.is_file():
        lines = [
            {"criterion": ref, "result": "met", "evidence": "the proposal file"}
            for ref in criteria or ("the node is recorded",)
        ]
    else:
        lines = [{"criterion": CONSISTENCY, "result": "met", "evidence": "design/nodes"}]
    defects: list[dict[str, Any]] = []
    failing = None
    if verdict == "reject":
        failing = deciding[0] if deciding else first["domain_standards"]
        answers[failing] = {"result": "unmet", "evidence": "design/nodes: n1"}
    if verdict == "blocked":
        held = lines[-1]
        held["result"] = "not evaluable"
        held["defect"] = {"finding": "the issued specification lacks the input", "blocking": True}
    return {
        "verdict": verdict,
        "finding": f"scripted dry run: {verdict}",
        "failing_item": failing,
        "subject": None,
        "numeric_output": None,
        "items": answers,
        "acceptance_criteria": lines,
        "indicators": [
            {
                "kind": h["kind"],
                "evidence": h["evidence"],
                "disposition": "dismissed",
                "reason": "dry run",
            }
            for h in packet["indicators"]
        ],
        "spec_defects": defects,
    }


def scripted_reviews(api: Any, verdicts: dict[str, tuple[str, tuple[str, ...]]]) -> None:  # noqa: ANN401
    """Every review on the scripted endpoint: read everything required, then one verdict."""

    def on_request(_thread: str, cwd: str, done: int) -> dict[str, Any]:
        read = Path(cwd).parent
        packet = json.loads((read.parent / RECORD_NAME).read_text())
        verdict, deciding = verdicts[packet["artefact"]["subtask_id"]]
        steps = [call for p in packet["required_reading"] for call in _reads(p)]
        answer = scripted_verdict(read, packet, verdict, deciding)
        steps.append(tool("StructuredOutput", review=answer))
        return steps[done] if done < len(steps) else text("done")

    api.script = Script(main=[])
    api.on_request = on_request


# --- The phases ------------------------------------------------------------------------------


def preflight(root: Path, token: str, base_url: str | None) -> dict[str, Any]:
    """One short session per schema the reviews are offered: each role, each input form."""
    found: dict[str, Any] = {}
    specs = {"electrical": artefacts.ELECTRICAL_SPEC, "mechanical": artefacts.MECHANICAL_SPEC}
    for role in ROLES:
        rubric = load_rubric(REPO_ROOT / KNOWLEDGE_ROOT, role)
        for form, issued in (("unissued", False), ("issued", True)):
            criteria = issued_criteria(specs[role]) if issued else None
            schema = verdict_schema(
                rubric.items,
                criteria=criteria,
                scan_hits=(),
                not_evaluable=not_evaluable_needs(role),
                issued=issued,
            )
            sdir = root / "preflight" / f"{role}-{form}"
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
                *("--model", REVIEWER, "--effort", "low", "--max-turns", "1"),
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
            found[f"{role}-{form}"] = {
                "schema_bytes": len(argv[argv.index("--json-schema") + 1]),
                "issued_criteria": len(criteria) if criteria else None,
                "answered_by": models,
                "refused_400": refused,
                "strict_mode_warnings": len(warnings),
                "total_cost_usd": (result or {}).get("total_cost_usd"),
                "accepted": (not refused) and models == [REVIEWER] and not warnings,
            }
    found["all_accepted"] = all(v["accepted"] for k, v in found.items() if isinstance(v, dict))
    return found


def _total(result: ReviewResult) -> Usage:
    total = Usage(
        input_tokens=0, output_tokens=0, cache_read_input_tokens=0, cache_creation_input_tokens=0
    )
    for message in result.usage:
        u = message.usage
        total = Usage(
            input_tokens=total.input_tokens + u.input_tokens,
            output_tokens=total.output_tokens + u.output_tokens,
            cache_read_input_tokens=total.cache_read_input_tokens + u.cache_read_input_tokens,
            cache_creation_input_tokens=total.cache_creation_input_tokens
            + u.cache_creation_input_tokens,
        )
    return total


def reviews(
    root: Path,
    credential: Credential,
    base_url: str | None,
    only: tuple[str, ...] | None = None,
) -> dict[str, Any]:
    """Review every artefact, or those in ``only``, once each, retried once for infrastructure."""
    install = root / INSTALL_DIRNAME
    prepare_install(install, REPO_ROOT)
    made = all_artefacts(root, only)
    review_root = require_review_root(root / REVIEW_DIRNAME)
    binary = claude_binary()
    setup = ReviewerSetup(
        run_id=RUN_ID,
        models=dict.fromkeys(ROLES, REVIEWER),
        claude_version=version_of(binary),
        bounds=BOUNDS,
        effort=EFFORT,
        max_output_tokens=MAX_OUTPUT_TOKENS,
        token_ceiling=TOKEN_CEILING,
        review_root=review_root,
        repo=None,
        install_bin=install / "bin" / "physgate",
        binary=binary,
        base_url=base_url,
        credential=credential,
        library=REPO_ROOT,
    )
    rubrics = {r: load_rubric(REPO_ROOT / KNOWLEDGE_ROOT, r) for r in ROLES}
    prices = load_price_sheet(PRICES)
    price = prices.sheet.usd_per_mtok[REVIEWER]
    config = {
        "run_id": RUN_ID,
        "reviewer": REVIEWER,
        "bounds": BOUNDS.model_dump(mode="json"),
        "effort": EFFORT,
        "max_output_tokens": MAX_OUTPUT_TOKENS,
        "rubrics": {r: rubric.sha256 for r, rubric in rubrics.items()},
        "artefacts": {aid: a.subtask_id for aid, a in made},
    }
    raw = (json.dumps(config, indent=1, sort_keys=True) + "\n").encode()
    (root / "reviews.json").write_bytes(raw)
    log = EventLog(root / "events.jsonl", run_id=RUN_ID, gate_mode="off")
    rows: list[dict[str, Any]] = []
    try:
        log.append(RunStarted(**log.envelope(), config_sha256=hashlib.sha256(raw).hexdigest()))
        for _, artefact in made:
            log.append(
                SubtaskPlanned(
                    **log.envelope(),
                    subtask_id=artefact.subtask_id,
                    spec_path=artefact.issued_spec.path if artefact.issued_spec else "-",
                    assigned_role=artefact.assigned_role,
                    module_dir="-",
                )
            )
        for artefact_id, artefact in made:
            role = artefact.assigned_role
            reviewer = ClaudeReviewer(
                role=role,
                setup=dataclasses.replace(
                    setup, repo=Path(artefact.repository or artefact.worktree)
                ),
                rubric=rubrics[role],
            )
            row: dict[str, Any] = {
                "artefact": artefact_id,
                "review_id": artefact.subtask_id,
                "role": role,
                "form": artefact.trajectory_form,
                "expected": artefacts.EXPECTED[artefact_id][0],
            }
            try:
                result = review_retried_once(
                    functools.partial(reviewer.review, artefact),
                    log,
                    subtask_id=artefact.subtask_id,
                    attempt=1,
                    delays=BOUNDS.infra_retry_delays_s,
                    sleep=time.sleep,
                )
            except ReviewUnavailableError as exc:
                row.update(
                    {"verdict": "review_unavailable", "cause": exc.cause, "detail": str(exc)}
                )
                rows.append(row)
                continue
            for message in result.usage:
                log.append(
                    TokensUsed(
                        **log.envelope(),
                        attribution=f"reviewer:{result.session_id}",
                        message_id=message.message_id,
                        usage=message.usage,
                    )
                )
            log.append(
                ReviewRan(
                    **log.envelope(), subtask_id=artefact.subtask_id, attempt=1, result=result
                )
            )
            tokens = _total(result)
            usd = price.usd(tokens)
            unmet = sorted(i.item for i in result.items if i.result in ("unmet", "confirmed"))
            deciding = artefacts.EXPECTED[artefact_id][1]
            row.update(
                {
                    "verdict": result.verdict,
                    "unmet_items": unmet,
                    "deciding_item_cited": (
                        bool(set(deciding) & {*unmet, result.failing_item or ""})
                        if deciding
                        else None
                    ),
                    "failing_item": result.failing_item,
                    "finding": result.finding,
                    "blocking_defects": sum(d.blocking for d in result.spec_defects),
                    "spec_defects": len(result.spec_defects),
                    "reviewer_model": result.reviewer_model,
                    "rubric_sha256": result.rubric_sha256,
                    "reading_verified": result.reading_verified,
                    "schema_refusals": result.schema_refusals,
                    "peak_context_tokens": result.peak_context_tokens,
                    "session_id": result.session_id,
                    "tokens": tokens.model_dump(),
                    "usd": str(usd.quantize(Decimal("0.0001"))),
                }
            )
            rows.append(row)
    finally:
        log.close()
    observed = sorted({r["verdict"] for r in rows})
    return {
        "rows": rows,
        "every_review_ends_in_a_verdict": all(
            r["verdict"] in ("pass", "fail", "blocked") for r in rows
        ),
        "verdict_forms_observed": observed,
        "every_verdict_form_observed": {"pass", "fail", "blocked"} <= set(observed),
        "every_review_on_the_reviewer_model": all(
            r.get("reviewer_model") == REVIEWER for r in rows if "reviewer_model" in r
        ),
        "every_review_with_the_promoted_rubric": all(
            r.get("rubric_sha256") == rubrics[r["role"]].sha256
            for r in rows
            if "rubric_sha256" in r
        ),
        "every_reading_verified": all(
            r.get("reading_verified") is True for r in rows if "session_id" in r
        ),
        "as_expected": {r["artefact"]: _matches(r) for r in rows},
        "planted_error_cited": {
            r["artefact"]: r["deciding_item_cited"]
            for r in rows
            if r.get("deciding_item_cited") is not None
        },
        "usd_total": str(sum((Decimal(r["usd"]) for r in rows if "usd" in r), Decimal(0))),
        "prices_date": PRICES,
    }


#: The loop's verdict words for the rubric's.
_WORDS = {"pass": "accept", "fail": "reject", "blocked": "blocked"}


def _matches(row: dict[str, Any]) -> bool:
    """The verdict is the one expected, and a twin's rejection names a deciding item."""
    same = _WORDS.get(str(row["verdict"])) == row["expected"]
    return bool(same and row.get("deciding_item_cited") is not False)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("phase", choices=["preflight", "reviews"])
    kind = parser.add_mutually_exclusive_group(required=True)
    kind.add_argument("--dry-run", action="store_true", help="scripted endpoint, dummy token")
    kind.add_argument("--real", action="store_true", help="the real API, on the subscription")
    parser.add_argument("--criteria", type=Path, required=True, help="the criteria stamped first")
    parser.add_argument("--out", type=Path, required=True)
    parser.add_argument("--env-file", type=Path, default=Path.home() / "dev" / "physgate" / ".env")
    parser.add_argument(
        "--only", help="reviews only these artefacts, comma-separated ids (default: all six)"
    )
    args = parser.parse_args()
    try:
        only = selected(args.only)
    except ValueError as exc:
        parser.error(str(exc))
    root = args.out.resolve()
    require_review_root(root / REVIEW_DIRNAME)  # before anything exists or runs
    root.mkdir(parents=True)
    binary = claude_binary()

    def git(*a: str) -> str:
        done = subprocess.run(
            ["git", *a], cwd=REPO_ROOT, capture_output=True, text=True, check=False
        )
        return done.stdout.strip()

    stamp = {
        "phase": args.phase,
        "kind": "dry-run" if args.dry_run else "real",
        "commit": git("rev-parse", "HEAD"),
        "dirty": bool(git("status", "--porcelain")),
        "script_sha256": sha256(Path(__file__)),
        "artefacts_sha256": sha256(HERE / "domain_review_artefacts.py"),
        "criteria_sha256": sha256(args.criteria),
        "binary_version": version_of(binary),
        "binary_sha256": sha256(Path(shutil.which(binary) or binary)),
        "promoted_rubrics": promoted_rubrics(),
        "reviewer": REVIEWER,
        "bounds": BOUNDS.model_dump(mode="json"),
        "only": list(only),
        "started_utc": utc(),
    }
    print(json.dumps(stamp), flush=True)
    token = DUMMY_OAUTH_TOKEN if args.dry_run else load_token(args.env_file)
    for name in ("ANTHROPIC_API_KEY", "ANTHROPIC_AUTH_TOKEN", "ANTHROPIC_BASE_URL"):
        os.environ.pop(name, None)
    os.environ["DISABLE_AUTOUPDATER"] = "1"
    credential = Credential(mode="subscription", secret=token)
    result: dict[str, Any]
    if args.phase == "preflight":
        if args.dry_run:
            with serving(Script(main=[text("done")])) as (api, url):
                result = {"preflight": preflight(root, token, url)}
                result["endpoint_refusals"] = list(api.refusals)
        else:
            result = {"preflight": preflight(root, token, None)}
    elif args.dry_run:
        verdicts = {
            review_id(aid): (exp, items) for aid, (exp, items, _) in artefacts.EXPECTED.items()
        }
        with serving(Script(main=[])) as (api, url):
            scripted_reviews(api, verdicts)
            os.environ["ANTHROPIC_BASE_URL"] = url
            result = {"reviews": reviews(root, credential, url, only)}
            result["endpoint_failures"] = list(api.failures)
            result["endpoint_requests"] = len(api.requests)
    else:
        result = {"reviews": reviews(root, credential, None, only)}
    result["finished_utc"] = utc()
    result["scan"] = record_scan(root, token)
    (root / "result.json").write_text(json.dumps({**stamp, **result}, indent=1, sort_keys=True))
    found = result.get("reviews") or {}
    print(
        json.dumps(
            {
                "scan": result["scan"],
                "preflight_all_accepted": (result.get("preflight") or {}).get("all_accepted"),
                "every_review_ends_in_a_verdict": found.get("every_review_ends_in_a_verdict"),
                "verdict_forms_observed": found.get("verdict_forms_observed"),
                "as_expected": found.get("as_expected"),
                "planted_error_cited": found.get("planted_error_cited"),
                "usd_total": found.get("usd_total"),
            }
        ),
        flush=True,
    )


if __name__ == "__main__":
    main()
