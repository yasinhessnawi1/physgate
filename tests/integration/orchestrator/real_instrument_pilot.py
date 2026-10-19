"""The instrument's pilot: real reviewers through ``physgate inject``, every role, a test corpus.

Run as a script, never collected as a test, and never without saying which kind:

    python real_instrument_pilot.py --dry-run --out <dir>
    python real_instrument_pilot.py --real --out <dir> [--env-file <file>]

**What it asks.** The injected-error instrument has run only with fake reviewers. Before a
measurement is frozen on it, this pilot asks whether the real reviewers, given what the
instrument gives them (a neutral account of a revision, its worktree and the corpus's parts
sheet, issued with no specification), come to a verdict, in which form, for every role, and
at what cost. It also captures what the pinned binary sends with a reviewer's requests.

**The corpus is the four-role test corpus** (``pilot_corpus``), never the measurement's: one
artefact per role (control, electrical, firmware, mechanical), each with a clean twin, all
written by the gate's builder to exercise the apparatus. It is reviewed through the real
``physgate inject`` command, in this process, with the measurement's parameters (the
reviewer pin for every role, effort, output-token limit, token ceiling, session bounds),
seed 7, and every clean twin reviewed in the same blind phase: eight review sessions.

**One check is set aside, and only one.** The command refuses a corpus that is not complete
(ten artefacts of each class), so a measurement never runs on a partial corpus. This corpus
has one artefact per role, so that refusal is lifted in this process, for this run, and the
stamp says so. Nothing else of the command changes.

**What it reports.** For every review: its role, whether it judged an artefact or a twin,
its outcome (pass, fail, blocked, or review_unavailable with its cause), the rubric item
that failed and the items found unmet, its blocking specification defects, whether it read
the parts sheet, its tokens priced at the dated price sheet beside the binary's own total,
and its wall clock. Then the verdict forms observed, and ``blocked`` and
``review_unavailable`` counted per role, for the artefacts and for the twins. The gate's
verdicts on this corpus are listed as an apparatus check. No rate is claimed: there are
eight reviews of a corpus written for this.

**The request defaults.** With ``--dry-run`` the same command runs against the scripted
endpoint, with a dummy OAuth token and no model call: the scripted reviewer reads its
required files and answers. Every request the binary sends is recorded, its fields besides
the conversation and its beta header, so the reviewer requests' defaults on the pinned
binary are measured, not assumed, and set beside the role sessions' measured defaults for
the same version. A real run's requests go to the API and are not observed.

**The binary.** The pilot runs only on the pinned 2.1.301; any other version is refused
before anything is written.

**The token.** With ``--real``, ``CLAUDE_CODE_OAUTH_TOKEN`` is read from the env file by this
script, held in memory and in this process's environment only, and never printed. At the
end every file under the output directory is scanned for it, for ``sk-ant-`` and for
``oat01``, and only the counts are printed.

**A dollar cap.** ``--max-usd`` (default $20) bounds the spend. Before every session the
driver adds what the dearest session so far cost (at least $2, the floor) to what has been
spent; if that would pass the cap, the run stops there, before the session starts, and says
so. A session's cost is the binary's own total from its stream, or, where the stream gives
none, its tokens priced with every cache write at the one-hour rate, the dearer one.

**Expected cost.** Eight reviews. The electrical and mechanical reviews' validation on the
same reviewer model cost $1.15 to $1.34 per review by the binary's own total, 9 to 13
minutes each; a firmware review of a small packet cost $0.49 to $0.85. So about $9 to $11
and about 1.5 to 2 hours, run serially; at most about twice that if every review is retried
once for an infrastructure failure.
"""

from __future__ import annotations

import argparse
import contextlib
import hashlib
import json
import os
import shutil
import subprocess
import sys
import time
from collections import Counter
from collections.abc import Callable, Iterator, Mapping
from dataclasses import dataclass
from decimal import Decimal
from pathlib import Path
from typing import Any
from unittest import mock

HERE = Path(__file__).resolve().parent
REPO_ROOT = HERE.parents[2]
sys.path.insert(0, str(HERE))
sys.path.insert(0, str(REPO_ROOT / "tests"))
sys.path.insert(0, str(REPO_ROOT / "tests" / "unit" / "evaluation"))

import pilot_corpus  # noqa: E402
import scripted_endpoint  # noqa: E402
from real_domain_reviewers import load_token, scripted_verdict  # noqa: E402
from record_scan import scan as record_scan  # noqa: E402
from scripted_endpoint import DUMMY_OAUTH_TOKEN, Script, serving, text, tool  # noqa: E402

from physgate.cli import main as physgate_main  # noqa: E402
from physgate.evaluation.inject import cli as inject_cli  # noqa: E402
from physgate.evaluation.inject.runner import (  # noqa: E402
    CONTROLS_DIRNAME,
    EVENTS_NAME,
    RESULTS_NAME,
    control_id,
    review_id,
)
from physgate.evaluation.observe.calls import (  # noqa: E402
    REVIEW_SESSION_DIRNAME,
    STREAM_NAME,
    read_call,
)
from physgate.evaluation.observe.cost import DatedSheet, load_price_sheet  # noqa: E402
from physgate.evaluation.observe.exceptions import PriceSheetError  # noqa: E402
from physgate.evaluation.observe.manifest import BINARY_DEFAULTS  # noqa: E402
from physgate.hooks.reading import content_lines  # noqa: E402
from physgate.knowledge.promote import KNOWLEDGE_ROOT  # noqa: E402
from physgate.orchestrator.cli import Registrations  # noqa: E402
from physgate.orchestrator.decompose import binary_version  # noqa: E402
from physgate.orchestrator.events import (  # noqa: E402
    ReviewRan,
    ReviewUnavailable,
    SubtaskPlanned,
    read_events,
)
from physgate.orchestrator.exceptions import ReviewUnavailableError  # noqa: E402
from physgate.orchestrator.invocation import claude_binary  # noqa: E402
from physgate.orchestrator.protocols import (  # noqa: E402
    Artefact,
    MessageUsage,
    Reviewer,
    ReviewResult,
    Usage,
)
from physgate.reviewers.claude import ReviewerSetup, claude_reviewers  # noqa: E402
from physgate.reviewers.packet import RECORD_NAME  # noqa: E402
from physgate.reviewers.places import require_review_root  # noqa: E402
from physgate.reviewers.rubric import load_rubric  # noqa: E402

VARIABLE = "CLAUDE_CODE_OAUTH_TOKEN"
#: The binary the pilot runs on: the one the measurement will be pinned to.
PILOT_VERSION = "2.1.301"
RUN_ID = "instrument-pilot"
SEED = 7
#: The dated price sheet that prices each call's cache writes at the lifetime it paid.
PRICES = "2026-10-16"
#: The measurement's reviewer parameters, as its run plan sets them; one reviewer per role.
PARAMS: dict[str, Any] = {
    "auth": "subscription",
    "reviewers": dict.fromkeys(pilot_corpus.ROLES, pilot_corpus.REVIEWER),
    "bounds": {
        "binary_max_retries": 0,
        "session_wall_clock_s": 4500.0,
        "session_max_turns": 80,
        "infra_retry_delays_s": [60.0, 300.0],
    },
    "effort": "high",
    "max_output_tokens": 64000,
    "token_ceiling": 400000,
    "lanes": 1,
    "pause_after_failures": 3,
    "pause_s": 900.0,
    "repair_resumes": 1,
}
#: The outcomes a review can come to, as the instrument's rows name them.
OUTCOMES = ("pass", "fail", "blocked", "review_unavailable")
#: What the completeness refusal's lifting is recorded as.
LIFTED = (
    "lifted in this process: the pilot corpus has one artefact per role, not ten per class; "
    "nothing else of the command is changed"
)
#: Where in the out directory each part goes. The review root's name holds no giveaway word.
CORPUS_DIRNAME, RUN_DIRNAME, ROOT_DIRNAME, INSTALL_DIRNAME = "corpus", "run", "rs", "install"
#: The dry run's scripted verdicts: each artefact rejected, each twin accepted, and the
#: firmware twin blocked, so every outcome the report counts is exercised. They mean nothing.
SCRIPTED_TWIN_BLOCKED = "f1"
#: The default dollar cap, and the least a session is expected to cost before one has run.
MAX_USD = Decimal("20")
SESSION_FLOOR_USD = Decimal("2.00")


def utc() -> str:
    return time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())


def sha256(path: Path) -> str:
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def promoted_rubrics() -> dict[str, str]:
    """Each role's promoted rubric digest, as its reviewer will load it."""
    return {r: load_rubric(REPO_ROOT / KNOWLEDGE_ROOT, r).sha256 for r in pilot_corpus.ROLES}


@contextlib.contextmanager
def completeness_lifted() -> Iterator[None]:
    """The command's refusal of an incomplete corpus set aside, for this process only."""
    with mock.patch.object(inject_cli, "require_complete", lambda corpus, per_class: None):
        yield


def argv(out: Path) -> list[str]:
    """The ``physgate inject`` command line the pilot runs."""
    return [
        "inject",
        *("--corpus", str(out / CORPUS_DIRNAME), "--run-dir", str(out / RUN_DIRNAME)),
        *("--scratch", str(out / ROOT_DIRNAME), "--run-id", RUN_ID, "--seed", str(SEED)),
        *("--params", str(out / "params.json"), "--install", str(out / INSTALL_DIRNAME)),
        "--review-clean-twins",
    ]


def prepare(out: Path) -> None:
    """Write the corpus and the parameters file into ``out``."""
    pilot_corpus.write_pilot_corpus(out / CORPUS_DIRNAME)
    (out / "params.json").write_text(json.dumps(PARAMS, indent=1, sort_keys=True) + "\n")


# --- The dollar cap ---------------------------------------------------------------------------

#: What a session cost: from its session id, its messages' usage and its model.
SessionCost = Callable[[str | None, tuple[MessageUsage, ...], str | None], Decimal]


class BudgetStop(Exception):  # noqa: N818 - a stop, not an error of the run
    """The next session could take the spend past the cap, so the run stops before it.

    Not one of the instrument's own errors, so the command does not turn it into a refusal
    of its own: it reaches this driver, which records it.
    """


@dataclass
class Budget:
    """The spend so far, held to a cap before every session."""

    cap_usd: Decimal
    #: The least the next session is expected to cost, before any has run.
    floor_usd: Decimal
    cost_of: SessionCost
    spent: Decimal = Decimal(0)
    largest: Decimal = Decimal(0)
    sessions: int = 0

    def before(self) -> None:
        """Refuse the next session if it could take the spend past the cap.

        Raises:
            BudgetStop: the spend so far plus the dearest session so far (at least the
                floor) is more than the cap.
        """
        expected = max(self.floor_usd, self.largest)
        if self.spent + expected > self.cap_usd:
            msg = (
                f"stopped before session {self.sessions + 1}: ${self.spent} spent, and a "
                f"session expected at ${expected} would pass the ${self.cap_usd} cap"
            )
            raise BudgetStop(msg)

    def after(self, cost: Decimal) -> None:
        """Count one session's cost."""
        self.spent += cost
        self.largest = max(self.largest, cost)
        self.sessions += 1


class Capped:
    """A reviewer that asks the budget before every session and counts what each cost."""

    def __init__(self, inner: Reviewer, budget: Budget) -> None:
        self._inner, self._budget = inner, budget

    @property
    def model(self) -> str:
        return self._inner.model

    def review(self, artefact: Artefact) -> ReviewResult:
        self._budget.before()
        try:
            result = self._inner.review(artefact)
        except ReviewUnavailableError as exc:
            self._budget.after(
                self._budget.cost_of(exc.session_id, tuple(exc.usage), exc.reviewer_model)
            )
            raise
        self._budget.after(
            self._budget.cost_of(result.session_id, result.usage, result.reviewer_model)
        )
        return result


def capped(
    budget: Budget, factory: Callable[[Any], Mapping[str, Reviewer]]
) -> Callable[[Any], dict[str, Reviewer]]:
    """``factory``, its every reviewer held to ``budget``."""

    def build(setup: Any) -> dict[str, Reviewer]:  # noqa: ANN401 - the factory's own setup
        return {role: Capped(r, budget) for role, r in factory(setup).items()}

    return build


def session_cost(root: Path, prices: DatedSheet) -> SessionCost:
    """A session's cost: the binary's own total, else its tokens at the dearer write rate."""

    def cost(session_id: str | None, usage: tuple[MessageUsage, ...], model: str | None) -> Decimal:
        stream = root / str(session_id) / REVIEW_SESSION_DIRNAME / STREAM_NAME
        if session_id and stream.is_file():
            recorded = read_call(stream, session_id)
            if recorded is not None and recorded.binary_usd is not None:
                return recorded.binary_usd
        price = prices.sheet.usd_per_mtok[model or pilot_corpus.REVIEWER]
        dearer = price.model_copy(
            update={"cache_write": max(price.cache_write, price.cache_write_1h or Decimal(0))}
        )
        return dearer.usd(_sum([m.usage for m in usage]))

    return cost


# --- What each review came to ----------------------------------------------------------------


def _stream_facts(stream: Path) -> dict[str, Any]:
    """From a review's own stream: whether it read the parts sheet, and its wall clock."""
    read_sheet, duration = False, None
    for line in stream.read_text(errors="replace").splitlines():
        try:
            event = json.loads(line)
        except json.JSONDecodeError:
            continue
        if event.get("type") == "result":
            duration = event.get("duration_ms")
        message = event.get("message") if isinstance(event.get("message"), dict) else {}
        for block in message.get("content") or []:
            if (
                isinstance(block, dict)
                and block.get("type") == "tool_use"
                and block.get("name") == "Read"
                and str((block.get("input") or {}).get("file_path", "")).endswith(
                    "/parts_sheet.json"
                )
            ):
                read_sheet = True
    return {"read_parts_sheet": read_sheet, "duration_ms": duration}


def _sum(usages: list[Usage]) -> Usage:
    return Usage(
        input_tokens=sum(u.input_tokens for u in usages),
        output_tokens=sum(u.output_tokens for u in usages),
        cache_read_input_tokens=sum(u.cache_read_input_tokens for u in usages),
        cache_creation_input_tokens=sum(u.cache_creation_input_tokens for u in usages),
    )


def _priced(
    session_id: str | None, model: str | None, usage: Usage, root: Path, prices: DatedSheet
) -> dict[str, Any]:
    """A session's tokens at the dated sheet, beside the binary's own figure, from its stream."""
    found: dict[str, Any] = {"tokens": usage.model_dump(), "usd": None, "binary_usd": None}
    stream = root / str(session_id) / REVIEW_SESSION_DIRNAME / STREAM_NAME
    recorded = read_call(stream, session_id) if session_id and stream.is_file() else None
    if session_id and stream.is_file():
        found.update(_stream_facts(stream))
    price = prices.sheet.usd_per_mtok.get(model or "")
    if price is not None:
        writes = recorded.cache_writes if recorded is not None else None
        split = writes if prices.sheet.cache_write_ttl == "per_call" else None
        try:
            usd = price.usd(usage, split)
        except PriceSheetError:
            # The result's split does not add up to the messages' writes: priced at the
            # five-minute rate, and said so.
            usd, found["ttl_split_unread"] = price.usd(usage), True
        found["usd"] = str(usd.quantize(Decimal("0.0001")))
    if recorded is not None and recorded.binary_usd is not None:
        found["binary_usd"] = str(recorded.binary_usd)
    return found


def reviews(run_dir: Path, root: Path, prices: DatedSheet) -> list[dict[str, Any]]:
    """Every review session of the run, in log order: the artefacts', then the twins'."""
    found: list[dict[str, Any]] = []
    for kind, log in (
        ("artefact", run_dir / EVENTS_NAME),
        ("twin", run_dir / CONTROLS_DIRNAME / EVENTS_NAME),
    ):
        events = read_events(log)
        roles = {e.subtask_id: e.assigned_role for e in events if isinstance(e, SubtaskPlanned)}
        for e in events:
            if isinstance(e, ReviewRan):
                result = e.result
                usage = _sum([m.usage for m in result.usage])
                unmet = sorted(i.item for i in result.items if i.result in ("unmet", "confirmed"))
                row = {
                    "review_id": e.subtask_id,
                    "role": roles[e.subtask_id],
                    "kind": kind,
                    "outcome": result.verdict,
                    "cause": "blocking_spec_defect" if result.verdict == "blocked" else None,
                    "retry": False,
                    "session_id": result.session_id,
                    "reviewer_model": result.reviewer_model,
                    "rubric_sha256": result.rubric_sha256,
                    "reading_verified": result.reading_verified,
                    "schema_refusals": result.schema_refusals,
                    "failing_item": result.failing_item,
                    "unmet_items": unmet,
                    "blocking_defects": sum(d.blocking for d in result.spec_defects),
                    "finding": result.finding,
                    **_priced(result.session_id, result.reviewer_model, usage, root, prices),
                }
            elif isinstance(e, ReviewUnavailable):
                row = {
                    "review_id": e.subtask_id,
                    "role": roles[e.subtask_id],
                    "kind": kind,
                    "outcome": "review_unavailable",
                    "cause": e.cause,
                    "retry": e.retry,
                    "session_id": e.session_id,
                    "reviewer_model": e.reviewer_model,
                    "detail": e.detail,
                    **_priced(e.session_id, e.reviewer_model, _sum([]), root, prices),
                }
            else:
                continue
            found.append(row)
    return found


def summary(run_dir: Path, root: Path, prices: DatedSheet) -> dict[str, Any]:
    """The pilot's report: every review, the forms observed, and the counts per role."""
    rows = [json.loads(x) for x in (run_dir / RESULTS_NAME).read_text().splitlines()]
    sessions = reviews(run_dir, root, prices)
    # The outcome that counts for an artefact or a twin is its row's: after a retry, the last.
    final = [(r["reviewer_verdict"], "artefact", r["review_id"]) for r in rows]
    final += [(r["control_reviewer_verdict"], "twin", r["control_id"]) for r in rows]
    role_of = {s["review_id"]: s["role"] for s in sessions}
    per_role: dict[str, dict[str, dict[str, int]]] = {}
    for outcome, kind, rid in final:
        counts = per_role.setdefault(role_of.get(rid, "?"), {}).setdefault(
            kind, dict.fromkeys(OUTCOMES, 0)
        )
        counts[outcome] += 1
    blocked_or_unavailable = {
        role: {
            kind: {o: counts[o] for o in ("blocked", "review_unavailable")}
            for kind, counts in kinds.items()
        }
        for role, kinds in sorted(per_role.items())
    }
    usd = [Decimal(s["usd"]) for s in sessions if s.get("usd") is not None]
    binary = [Decimal(s["binary_usd"]) for s in sessions if s.get("binary_usd") is not None]
    tokens = _sum([Usage(**s["tokens"]) for s in sessions])
    return {
        "sessions": sessions,
        "verdict_forms_observed": sorted({o for o, _, _ in final}),
        "per_role": dict(sorted(per_role.items())),
        "blocked_and_unavailable_per_role": blocked_or_unavailable,
        "every_role_reviewed": sorted(per_role) == sorted(pilot_corpus.ROLES),
        "every_review_on_the_reviewer_pin": all(
            s.get("reviewer_model") in (None, pilot_corpus.REVIEWER) for s in sessions
        ),
        "parts_sheet_read": sum(bool(s.get("read_parts_sheet")) for s in sessions),
        "tokens_total": tokens.model_dump(),
        "usd_priced_total": str(sum(usd, Decimal(0))),
        "usd_binary_total": str(sum(binary, Decimal(0))),
        "prices_date": PRICES,
        "gate_apparatus": {
            r["artefact"]: {"artefact": r["gate_verdict"], "twin": r["control_verdict"]}
            for r in rows
        },
    }


# --- The dry run's scripted reviewer and the requests it records ------------------------------

#: What the binary asked for, per request: the fields besides the conversation, and the beta
#: header, as the role sessions' defaults were measured.
REQUESTS: list[dict[str, Any]] = []
_ANSWER = scripted_endpoint.FakeMessagesApi.answer


def _recording(self: Any, path: str, headers: Any, body: dict[str, Any]) -> Any:  # noqa: ANN401
    REQUESTS.append(
        {
            "model": body.get("model"),
            "max_tokens": body.get("max_tokens"),
            "thinking": body.get("thinking"),
            "output_config": body.get("output_config"),
            "context_management": body.get("context_management"),
            "sampling": sorted(k for k in ("temperature", "top_p", "top_k") if k in body),
            "anthropic_beta": sorted((headers.get("anthropic-beta") or "").split(",")),
        }
    )
    return _ANSWER(self, path, headers, body)


def request_defaults(requests: list[dict[str, Any]], version: str) -> dict[str, Any]:
    """The distinct settings the reviewer requests carried, beside the version's role defaults."""
    distinct = Counter(json.dumps(r, sort_keys=True) for r in requests)
    known = BINARY_DEFAULTS.get(version)
    seen = [json.loads(k) for k in distinct]
    compared = None
    if known is not None:
        compared = {
            "thinking_type_as_role_sessions": all(
                (r["thinking"] or {}).get("type") == known.thinking.get("type") for r in seen
            ),
            "context_management_as_role_sessions": all(
                r["context_management"] == known.context_management for r in seen
            ),
            "anthropic_beta_as_role_sessions": all(
                [b for b in r["anthropic_beta"] if b] == sorted(known.anthropic_beta) for r in seen
            ),
        }
    return {
        "requests": len(requests),
        "distinct": [{"count": n, **json.loads(k)} for k, n in sorted(distinct.items())],
        "role_session_defaults_known_for_version": known is not None,
        "compared_with_role_sessions": compared,
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


def scripted_plan() -> dict[str, str]:
    """The dry run's verdict for each review id. Scripted; it means nothing."""
    plan: dict[str, str] = {}
    for artefact in pilot_corpus.ARTEFACTS:
        aid = str(artefact["id"])
        plan[review_id(SEED, aid)] = "reject"
        plan[control_id(SEED, aid)] = "blocked" if aid == SCRIPTED_TWIN_BLOCKED else "accept"
    return plan


def scripted_reviewer(api: Any, plan: dict[str, str]) -> None:  # noqa: ANN401
    """Every review on the scripted endpoint: read everything required, then one verdict."""

    def on_request(_thread: str, cwd: str, done: int) -> dict[str, Any]:
        read = Path(cwd).parent
        packet = json.loads((read.parent / RECORD_NAME).read_text())
        verdict = plan[packet["artefact"]["subtask_id"]]
        steps = [call for p in packet["required_reading"] for call in _reads(p)]
        steps.append(tool("StructuredOutput", review=scripted_verdict(read, packet, verdict)))
        return steps[done] if done < len(steps) else text("done")

    api.script = Script(main=[])
    api.on_request = on_request


# --- The run ---------------------------------------------------------------------------------


def run(out: Path, *, dry_run: bool, version: str, max_usd: Decimal = MAX_USD) -> dict[str, Any]:
    """Run the command once over the pilot corpus; what it exited with, and what it recorded."""
    prepare(out)
    prices = load_price_sheet(PRICES)
    budget = Budget(
        cap_usd=max_usd,
        floor_usd=SESSION_FLOOR_USD,
        cost_of=session_cost(out / ROOT_DIRNAME, prices),
    )
    registrations = Registrations(reviewer_factory=capped(budget, _claude_reviewers))
    found: dict[str, Any] = {}
    try:
        with completeness_lifted():
            if dry_run:
                scripted_endpoint.FakeMessagesApi.answer = _recording  # type: ignore[method-assign]
                try:
                    with serving(Script(main=[])) as (api, url):
                        scripted_reviewer(api, scripted_plan())
                        os.environ["ANTHROPIC_BASE_URL"] = url
                        found["exit"] = physgate_main(argv(out), registrations)
                        found["endpoint_failures"] = list(api.failures)
                finally:
                    scripted_endpoint.FakeMessagesApi.answer = _ANSWER  # type: ignore[method-assign]
                    os.environ.pop("ANTHROPIC_BASE_URL", None)
                found["request_defaults"] = request_defaults(REQUESTS, version)
            else:
                found["exit"] = physgate_main(argv(out), registrations)
    except BudgetStop as exc:
        found["stopped_by_cap"] = str(exc)
    found["budget"] = {
        "cap_usd": str(budget.cap_usd),
        "spent_usd": str(budget.spent),
        "sessions": budget.sessions,
    }
    if (out / RUN_DIRNAME / RESULTS_NAME).is_file():
        found["report"] = summary(out / RUN_DIRNAME, out / ROOT_DIRNAME, prices)
    elif (out / RUN_DIRNAME / EVENTS_NAME).is_file():
        # Stopped part way: no rows, but every session that ran is in the logs.
        found["report"] = {"sessions": reviews(out / RUN_DIRNAME, out / ROOT_DIRNAME, prices)}
    return found


def _claude_reviewers(setup: ReviewerSetup) -> Mapping[str, Reviewer]:
    """The command's own reviewers, as it builds them unregistered."""
    return claude_reviewers(setup)


def _git(*args: str) -> str:
    done = subprocess.run(
        ["git", *args], cwd=REPO_ROOT, capture_output=True, text=True, check=False
    )
    return done.stdout.strip()


def main(argv_: list[str] | None = None, *, binary_check: Callable[[], str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    kind = parser.add_mutually_exclusive_group(required=True)
    kind.add_argument("--dry-run", action="store_true", help="scripted endpoint, dummy token")
    kind.add_argument("--real", action="store_true", help="the real API, on the subscription")
    parser.add_argument("--out", type=Path, required=True, help="a new directory")
    parser.add_argument("--env-file", type=Path, default=Path.home() / "dev" / "physgate" / ".env")
    parser.add_argument(
        "--max-usd",
        type=Decimal,
        default=MAX_USD,
        help="stop before a session that could take the spend past this many dollars",
    )
    args = parser.parse_args(argv_)
    out = args.out.expanduser().resolve()
    # Before anything exists or runs: the review root's path names nothing, and is new.
    require_review_root(out / ROOT_DIRNAME)
    binary = claude_binary()
    version = binary_check() if binary_check is not None else binary_version(binary)
    if version != PILOT_VERSION:
        print(json.dumps({"refused": "the pilot runs on the pinned binary", "found": version}))
        return 2
    out.mkdir(parents=True)
    stamp = {
        "kind": "dry-run" if args.dry_run else "real",
        "commit": _git("rev-parse", "HEAD"),
        "dirty": bool(_git("status", "--porcelain")),
        "script_sha256": sha256(Path(__file__)),
        "corpus_module_sha256": sha256(Path(pilot_corpus.__file__)),
        "binary_version": version,
        "binary_sha256": sha256(Path(shutil.which(binary) or binary)),
        "promoted_rubrics": promoted_rubrics(),
        "params": PARAMS,
        "seed": SEED,
        "completeness_check": LIFTED,
        "max_usd": str(args.max_usd),
        "session_floor_usd": str(SESSION_FLOOR_USD),
        "argv": argv(out),
        "started_utc": utc(),
    }
    print(json.dumps(stamp), flush=True)
    token = DUMMY_OAUTH_TOKEN if args.dry_run else load_token(args.env_file)
    for name in ("ANTHROPIC_API_KEY", "ANTHROPIC_AUTH_TOKEN", "ANTHROPIC_BASE_URL"):
        os.environ.pop(name, None)
    os.environ["DISABLE_AUTOUPDATER"] = "1"
    os.environ[VARIABLE] = token
    try:
        result = run(out, dry_run=args.dry_run, version=version, max_usd=args.max_usd)
    finally:
        os.environ.pop(VARIABLE, None)
    result["finished_utc"] = utc()
    result["scan"] = record_scan(out, token)
    (out / "result.json").write_text(json.dumps({**stamp, **result}, indent=1, sort_keys=True))
    report = result.get("report") or {}
    print(
        json.dumps(
            {
                "exit": result.get("exit"),
                "stopped_by_cap": result.get("stopped_by_cap"),
                "budget": result.get("budget"),
                "scan": result["scan"],
                "verdict_forms_observed": report.get("verdict_forms_observed"),
                "blocked_and_unavailable_per_role": report.get("blocked_and_unavailable_per_role"),
                "every_role_reviewed": report.get("every_role_reviewed"),
                "parts_sheet_read": report.get("parts_sheet_read"),
                "tokens_total": report.get("tokens_total"),
                "usd_priced_total": report.get("usd_priced_total"),
                "usd_binary_total": report.get("usd_binary_total"),
                "request_defaults": (result.get("request_defaults") or {}).get(
                    "compared_with_role_sessions"
                ),
            }
        ),
        flush=True,
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
