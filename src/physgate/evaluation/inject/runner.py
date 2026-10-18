"""The instrument's run: every artefact reviewed alone and blind, then every artefact gated.

Risk row 1 runs the paired reviewers alone, then the gate. Here that order is
the whole run's, not each artefact's: **every review is written before the gate
runs on anything**, so while any reviewer works there is no gate output
anywhere in the run to be read. The reviewer is given the injected artefact as
a worktree, its design and a neutral account of the revision, checked first to
hold no answer; it is never given the corpus, the class, the expected check or
the run directory. Its copy is removed once its verdict is written, so no
reviewer finds another artefact, or an artefact's twin, beside its own. On
request the clean twins are reviewed too, in the same phase, each under an id of
its own, and their reviews go into the controls log.

The gate then judges each injected artefact over a fresh copy of it, made in the
run directory and never under the review root (a reviewer that wrote to its
worktree, or anywhere under that root, changes nothing the gate reads) in one call at all
three scopes, in ``observe``, with the patch as the one change set above the
base. It also judges each clean patch, as a control that the artefact was
otherwise valid; the controls have a log of their own, so the run's log counts
the injected artefacts alone.

Every review, of an artefact or of a twin, is given the corpus's parts sheet, the
same bytes each time, so a source citing one of its rows can be checked. The gate's
copies hold no sheet: the gate reads the design alone.

The run's log is an ordinary run-event log: a start line, one planned subtask
per artefact, then the review lines, then the gate lines. So the gate-event
derivation reads it like any run's, and the stamp on each gate event is the
review that came before it on the same artefact. ``physgate catches`` reads the
run directory and its ``controls`` directory, stamped with the digest of
``instrument.json`` that the first line carries; ``physgate gate-events`` reads
a driven run's ``run.json`` and does not read this directory. The loop's replay
would refuse it (a review before a gate), and it is never resumed: a killed run
is started again into new directories.

A review that is not a verdict never stops the run and is never a pass or a fail.
An infrastructure failure is retried after each delay of the run's schedule
(``infra_retry_delays_s``, one retry per delay, each waited out first, so one outage
does not use up every retry at once); after the last, the review is recorded in
the log as unavailable and in its row as ``review_unavailable`` with its cause. A
review that blocked, on a blocking defect of the issued specification, is a verdict:
it is in the log as a review and in its row as ``blocked``. Every artefact gets its
row.

Artefacts run under an id derived from the seed and the corpus id, in the
order those ids sort, so the log shows no corpus id and no class order. The
results file has one row per artefact, in corpus id order, and **no total**:
what the rows add up to is the experiment's to state.

**Review lanes.** The reviews may run in parallel lanes, each a reviewer session
at a time under a review root of its own (``scratch/lane-<k>``), taking the next
item in id order as it frees. A lane's copies and sessions are never under another
lane's root, and a reviewer reads only beneath its own packet in any case. The log
then holds the review lines in the order they ended, not in id order; every one is
still written before the gate runs on anything. Each finished review is also written
on its own, in ``reviews/<id>.json``: its outcome, tokens, lane and every try with
the delay waited before it. A progress line after each, on standard error, gives
counts only (how many are done, how many came to no verdict), so a running
measurement shows nothing a reader could steer by. One lane is the run as it always
was: one root, the same paths, the log in id order.
"""

from __future__ import annotations

import functools
import hashlib
import json
import os
import queue
import shutil
import sys
import threading
import time
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass, field
from pathlib import Path
from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field, StringConstraints

from physgate.evaluation.inject.corpus import (
    ArtefactId,
    Base,
    Corpus,
    CorpusArtefact,
    ErrorClass,
    Patch,
    digest,
)
from physgate.evaluation.inject.exceptions import (
    ReviewerRefusedError,
    RunDirectoryError,
)
from physgate.evaluation.inject.materialise import (
    DESIGN_DIRNAME,
    Materialised,
    materialise,
    require_blind,
)
from physgate.gate.catalogue import catalogue_digest
from physgate.gate.graph import ChangeHistory, GraphView
from physgate.gate.runner import PhysicsGate
from physgate.orchestrator.common import AuthMode, ModelString, NonEmptyStr
from physgate.orchestrator.events import (
    EventLog,
    GateRan,
    ReviewRan,
    ReviewUnavailable,
    RunStarted,
    SubtaskPlanned,
)
from physgate.orchestrator.exceptions import ReviewUnavailableError
from physgate.orchestrator.protocols import (
    Artefact,
    ChangeSet,
    CheckName,
    GateResult,
    RecordedUnavailableCause,
    Reviewer,
    ReviewResult,
    Scope,
    Verdict,
    require_separate_models,
)
from physgate.orchestrator.run_config import Effort, RunBounds
from physgate.orchestrator.trajectory import seal
from physgate.reviewers.exceptions import ReviewRootError
from physgate.reviewers.places import require_review_root

#: One gate call per artefact, at every scope: for a design written as one change
#: set these are exactly the scopes the loop's two calls cover.
SCOPES: tuple[Scope, ...] = ("subtask", "module", "system")
GATE_MODE: Literal["observe"] = "observe"
EVENTS_NAME = "events.jsonl"
RESULTS_NAME = "results.jsonl"
CONFIG_NAME = "instrument.json"
CONTROLS_DIRNAME = "controls"
#: Where, in the run directory, the gate's fresh copies are made: outside the review root.
COPIES_DIRNAME = "copies"
#: Where, in the run directory, each finished review is written on its own.
REVIEWS_DIRNAME = "reviews"
ReviewId = Annotated[str, StringConstraints(pattern=r"^r[0-9a-f]{12}$")]
Sha256 = Annotated[str, StringConstraints(pattern=r"^[0-9a-f]{64}$")]


class _Frozen(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid", strict=True)


class InstrumentParams(_Frozen):
    """What the instrument's real reviewers run under, from a parameters file. No defaults."""

    auth: AuthMode
    #: The reviewer model of each role the corpus's artefacts go to.
    reviewers: dict[NonEmptyStr, ModelString]
    bounds: RunBounds
    effort: Effort
    max_output_tokens: Annotated[int, Field(gt=0)]
    token_ceiling: Annotated[int, Field(gt=0)]


class Reviewing(_Frozen):
    """The real reviewers' run, as ``instrument.json`` records it."""

    params: InstrumentParams
    claude_version: NonEmptyStr
    endpoint: NonEmptyStr
    install: NonEmptyStr


class InstrumentConfig(_Frozen):
    """What one run of the instrument was, recorded before its first action."""

    run_id: NonEmptyStr
    seed: int
    corpus_label: NonEmptyStr
    corpus_manifest_sha256: Sha256
    author_model: ModelString
    #: The reviewer each role's artefacts go to, by its pinned model string.
    reviewer_models: dict[NonEmptyStr, ModelString]
    #: Whether each clean twin was reviewed too, in the same blind phase.
    review_clean_twins: bool
    gate_mode: Literal["observe"]
    scopes: tuple[Scope, ...]
    catalogue_sha256: Sha256
    #: How the real reviewers ran: their parameters, the auth mode, the binary's
    #: version and the endpoint. ``None`` for reviewers given built, as in tests.
    reviewing: Reviewing | None = None
    #: The corpus's size per class, as the run held it to. Defaults read records
    #: written before these fields existed: ten per class, one lane, one retry at once.
    per_class: Annotated[int, Field(ge=1)] = 10
    #: How many reviews ran at once, each lane under its own review root.
    lanes: Annotated[int, Field(ge=1)] = 1
    #: The delay waited before each infrastructure retry; its length is the retries.
    retry_delays_s: tuple[Annotated[float, Field(ge=0)], ...] = (0.0,)


#: What one artefact's review came to, as its row records it.
ReviewOutcome = Literal["pass", "fail", "blocked", "review_unavailable"]

#: Why a review came to neither a pass nor a fail: a blocked verdict's one reason, or
#: why a review reached no verdict.
ReviewCause = RecordedUnavailableCause


class ResultRow(_Frozen):
    """One artefact: what it is, what its reviewer said, and what the gate said after."""

    artefact: ArtefactId
    #: The id the artefact ran under in the run's log.
    review_id: ReviewId
    error_class: ErrorClass
    expected_check: CheckName
    #: What the review came to: a pass or a fail; ``blocked``, a blocking defect of
    #: the issued specification; or ``review_unavailable``, no verdict after the one
    #: retry an infrastructure failure gets. Neither of the last two is a pass or a fail.
    reviewer_verdict: ReviewOutcome
    #: Why the review gave no pass or fail, for ``blocked`` and ``review_unavailable``.
    review_cause: ReviewCause | None
    #: ``None`` only for a review that never reached its model.
    reviewer_model: ModelString | None
    #: Every token the artefact's review spent, a retried try included.
    reviewer_tokens: Annotated[int, Field(ge=0)]
    review_seq: Annotated[int, Field(ge=0)]
    gate_seq: Annotated[int, Field(ge=0)]
    gate_verdict: Verdict
    #: The checks whose failure blocked on the injected artefact, in the table's
    #: order; empty when the gate caught nothing.
    gate_blocking: tuple[CheckName, ...]
    #: The id the clean twin ran under in the controls log.
    control_id: ReviewId
    #: The clean twin's reviewer verdict, when the twins were reviewed; else ``None``.
    control_reviewer_verdict: ReviewOutcome | None
    #: The gate on the clean patch, the control.
    control_verdict: Verdict
    control_blocking: tuple[CheckName, ...]


def review_id(seed: int, artefact_id: str) -> str:
    """The id an artefact runs under: from the seed and its corpus id, telling neither."""
    return "r" + hashlib.sha256(f"{seed}:{artefact_id}".encode()).hexdigest()[:12]


def control_id(seed: int, artefact_id: str) -> str:
    """The id an artefact's clean twin runs under: another id, of the same form."""
    return review_id(seed, f"{artefact_id}#clean")


def require_reviewers(corpus: Corpus, reviewers: Mapping[str, Reviewer]) -> None:
    """Refuse a run before it starts unless every artefact has a reviewer off the author's model.

    Raises:
        ReviewerRefusedError: an artefact's role has no registered reviewer.
        ModelSeparationError: a reviewer runs on the corpus author's model string.
    """
    for role in sorted({a.assigned_role for a in corpus.artefacts}):
        reviewer = reviewers.get(role)
        if reviewer is None:
            msg = "no reviewer is registered for a role the corpus's artefacts go to"
            raise ReviewerRefusedError(msg, role=role)
        require_separate_models(implementer=corpus.manifest.author_model, reviewer=reviewer.model)


def _inside(path: Path, root: Path) -> bool:
    return path == root or root in path.parents


def require_places(corpus_root: Path, run_dir: Path, scratch: Path) -> None:
    """Refuse run and scratch directories that are not fresh, or that could leak an answer.

    The reviewer reads under ``scratch``, so neither the corpus nor the run's records
    may be inside it; and a reviewer is refused the corpus and the run directory,
    so its own worktree may not be inside either.

    Raises:
        RunDirectoryError: one exists and is not empty, one is inside another, or the
            scratch directory is not a review root (its path names what is measured, or
            it lies inside a git checkout).
    """
    places = {
        "corpus": corpus_root.resolve(),
        "run": run_dir.resolve(),
        "scratch": scratch.resolve(),
    }
    for a, b in (
        ("run", "scratch"),
        ("scratch", "run"),
        ("run", "corpus"),
        ("scratch", "corpus"),
        ("corpus", "scratch"),
    ):
        if _inside(places[a], places[b]):
            msg = "the directories are kept apart, so a reviewer reads none of the others"
            raise RunDirectoryError(msg, inside=f"{a} in {b}", path=str(places[a]))
    for name in ("run", "scratch"):
        path = places[name]
        if path.exists() and (not path.is_dir() or any(path.iterdir())):
            msg = "the instrument writes into directories that are new or empty"
            raise RunDirectoryError(msg, **{name: str(path)})
    # Every path a reviewer is shown begins with the scratch directory's, so a scratch
    # path that names the harness would be refused at the first artefact. It is refused
    # here instead, before anything is written.
    try:
        require_review_root(places["scratch"])
    except ReviewRootError as exc:
        raise RunDirectoryError(str(exc), **exc.context) from None


def _gate(gate: PhysicsGate, made: Materialised, subtask: str) -> GateResult:
    history = ChangeHistory(
        baseline=made.baseline,
        change_sets=(ChangeSet(subtask_id=subtask, attempt=1, revisions=made.revisions),),
    )
    view = GraphView.read(made.graph_root, base_revision=made.baseline, history=history)
    return gate.run(view, SCOPES, GATE_MODE)


def check_base(base: Base, into: Path, gate: PhysicsGate | None = None) -> GateResult:
    """Gate the base design alone, as one change set over nothing, before any artefact exists."""
    return _gate(gate or PhysicsGate(), materialise(base, None, into), "base")


def blocking(result: GateResult) -> tuple[CheckName, ...]:
    """The checks whose failure blocked, each once, in the order the records give."""
    names = [r.name for r in result.checks if r.outcome == "fail" and r.blocking]
    return tuple(dict.fromkeys(names))


def _start(
    path: Path, run_id: str, config_sha256: str, order: list[tuple[str, CorpusArtefact]]
) -> EventLog:
    log = EventLog(path, run_id=run_id, gate_mode=GATE_MODE)
    log.append(RunStarted(**log.envelope(), config_sha256=config_sha256))
    for rid, artefact in order:
        log.append(
            SubtaskPlanned(
                **log.envelope(),
                subtask_id=rid,
                spec_path=f"artefacts/{artefact.id}.json",
                assigned_role=artefact.assigned_role,
                module_dir=DESIGN_DIRNAME,
            )
        )
    return log


def _review(
    reviewer: Reviewer,
    author: str,
    base: Base,
    patch: Patch,
    place: Path,
    subtask: str,
    artefact: CorpusArtefact,
    parts_sheet: bytes | None = None,
) -> ReviewResult:
    """One blind review of ``patch`` over ``base``, on a copy removed once it is judged.

    The copy is gone before the next review starts, so no reviewer finds another's
    artefact, or an artefact's twin, beside its own. With ``parts_sheet``, the copy
    holds the corpus's parts sheet beside the design, held to the same check.
    """
    made = materialise(base, patch, place, parts_sheet)
    try:
        require_blind(made, (artefact.id, artefact.description))
        # Sealed as written, so the reviewer holds its own read to these bytes.
        sealed = seal(made.trajectory.read_bytes())
        result = reviewer.review(
            Artefact(
                subtask_id=subtask,
                attempt=1,
                assigned_role=artefact.assigned_role,
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
        )
    finally:
        shutil.rmtree(place)
    require_separate_models(implementer=author, reviewer=result.reviewer_model)
    return result


@dataclass(frozen=True)
class _Try:
    """One try at a review: why it gave no verdict (``None`` if it gave one), and the wait."""

    cause: str | None
    #: How long the run waited before this try, in seconds; 0 for the first.
    delay_before_s: float


@dataclass(frozen=True)
class _Reviewed:
    """One artefact's review as its log records it, and every token its tries spent."""

    line: ReviewRan | ReviewUnavailable
    tokens: int
    tries: tuple[_Try, ...] = ()
    lane: int = 0

    @property
    def outcome(self) -> ReviewOutcome:
        if isinstance(self.line, ReviewRan):
            return self.line.result.verdict
        return "review_unavailable"

    @property
    def cause(self) -> ReviewCause | None:
        if isinstance(self.line, ReviewRan):
            return "blocking_spec_defect" if self.line.result.verdict == "blocked" else None
        return self.line.cause

    @property
    def model(self) -> str | None:
        if isinstance(self.line, ReviewRan):
            return self.line.result.reviewer_model
        return self.line.reviewer_model

    def record(self, subtask: str) -> dict[str, object]:
        """What ``reviews/<id>.json`` holds for this review."""
        return {
            "review_id": subtask,
            "lane": self.lane,
            "outcome": self.outcome,
            "cause": self.cause,
            "seq": self.line.seq,
            "tokens": self.tokens,
            "tries": [{"cause": t.cause, "delay_before_s": t.delay_before_s} for t in self.tries],
        }


@dataclass
class _Shared:
    """What the lanes share: the lock on both logs, and the counts the progress line gives."""

    total: int
    lock: threading.Lock = field(default_factory=threading.Lock)
    done: int = 0
    unavailable: int = 0


def _reviewed(
    log: EventLog,
    review: Callable[[], ReviewResult],
    subtask: str,
    *,
    delays: tuple[float, ...] = (0.0,),
    sleep: Callable[[float], None] = time.sleep,
    lock: threading.Lock | None = None,
) -> _Reviewed:
    """Review one artefact and record the outcome; a review that gives no verdict is recorded too.

    An infrastructure failure is retried once for each of ``delays``, after waiting
    that long, as in the loop: an outage that outlasts the first wait still finds the
    later ones. Any other review that is not a verdict, or an infrastructure failure
    after the last retry, is recorded as such and the run goes on: every artefact gets
    its row, and a review that gave no verdict is never counted as a pass or a fail.
    """
    guard = lock or threading.Lock()
    tries: list[_Try] = []
    retries_done, tokens, waited = 0, 0, 0.0
    while True:
        try:
            result = review()
        except ReviewUnavailableError as exc:
            tokens += sum(m.usage.total() for m in exc.usage)
            retry = exc.cause == "infrastructure" and retries_done < len(delays)
            with guard:
                line = log.append(
                    ReviewUnavailable(
                        **log.envelope(),
                        subtask_id=subtask,
                        attempt=1,
                        cause=exc.cause,
                        detail=str(exc) or exc.cause,
                        retry=retry,
                        session_id=exc.session_id,
                        reviewer_model=exc.reviewer_model,
                        spec_defects=exc.spec_defects,
                    )
                )
            tries.append(_Try(exc.cause, waited))
            if not retry:
                return _Reviewed(line=line, tokens=tokens, tries=tuple(tries))
            waited = delays[retries_done]
            retries_done += 1
            sleep(waited)
            continue
        tokens += sum(m.usage.total() for m in result.usage)
        with guard:
            ran = log.append(
                ReviewRan(**log.envelope(), subtask_id=subtask, attempt=1, result=result)
            )
        tries.append(_Try(None, waited))
        return _Reviewed(line=ran, tokens=tokens, tries=tuple(tries))


def _write_state(path: Path, record: dict[str, object]) -> None:
    """Write one review's record whole: to a new name first, then renamed over."""
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(".tmp")
    temporary.write_text(json.dumps(record, sort_keys=True) + "\n")
    os.replace(temporary, path)


def _progress_line(shared: _Shared) -> str:
    """Counts only: how many reviews are done, and how many came to no verdict."""
    return (
        f"progress: {shared.done}/{shared.total} reviews done, "
        f"{shared.unavailable} without a verdict"
    )


@dataclass(frozen=True)
class _Lanes:
    """What every lane reviews with: its reviewers and root, and the run's retry schedule."""

    reviewers: list[Mapping[str, Reviewer]]
    roots: list[Path]
    author: str
    corpus: Corpus
    delays: tuple[float, ...]
    sleep: Callable[[float], None]


_Item = tuple[str, CorpusArtefact, Patch, EventLog]


def _review_all(
    items: list[_Item],
    lanes: _Lanes,
    reviews: dict[str, _Reviewed],
    run_dir: Path,
    say: Callable[[str], None],
) -> None:
    """Review every item, in as many lanes as there are roots, each taking the next in order.

    A lane that raises stops every lane from taking another item; the first error is
    raised once all have stopped, as a single lane's would be.
    """
    work: queue.Queue[_Item] = queue.Queue()
    for item in items:
        work.put(item)
    shared = _Shared(total=len(items))
    stop = threading.Event()
    errors: list[BaseException] = []

    def lane(k: int) -> None:
        while not stop.is_set():
            try:
                subtask, artefact, patch, into = work.get_nowait()
            except queue.Empty:
                return
            review = functools.partial(
                _review,
                lanes.reviewers[k][artefact.assigned_role],
                lanes.author,
                lanes.corpus.base,
                patch,
                lanes.roots[k] / "review" / subtask,
                subtask,
                artefact,
                lanes.corpus.parts_sheet,
            )
            try:
                done = _reviewed(
                    into, review, subtask, delays=lanes.delays, sleep=lanes.sleep, lock=shared.lock
                )
            except BaseException as exc:
                stop.set()
                with shared.lock:
                    errors.append(exc)
                return
            done = _Reviewed(line=done.line, tokens=done.tokens, tries=done.tries, lane=k)
            _write_state(run_dir / REVIEWS_DIRNAME / f"{subtask}.json", done.record(subtask))
            with shared.lock:
                reviews[subtask] = done
                shared.done += 1
                shared.unavailable += done.outcome == "review_unavailable"
                line = _progress_line(shared)
            say(line)

    if len(lanes.roots) == 1:
        lane(0)
    else:
        threads = [
            threading.Thread(target=lane, args=(k,), name=f"review-lane-{k}")
            for k in range(len(lanes.roots))
        ]
        for thread in threads:
            thread.start()
        for thread in threads:
            thread.join()
    if errors:
        raise errors[0]


def run_instrument(
    corpus: Corpus,
    reviewers: Mapping[str, Reviewer],
    *,
    run_dir: Path,
    scratch: Path,
    run_id: str,
    seed: int,
    review_clean_twins: bool = False,
    gate: PhysicsGate | None = None,
    reviewing: Reviewing | None = None,
    per_class: int = 10,
    lanes: int = 1,
    lane_reviewers: Sequence[Mapping[str, Reviewer]] | None = None,
    retry_delays_s: tuple[float, ...] = (0.0,),
    sleep: Callable[[float], None] = time.sleep,
    progress: Callable[[str], None] | None = None,
) -> tuple[ResultRow, ...]:
    """Review every artefact of ``corpus`` blind, then gate each, and write the results.

    Writes ``instrument.json``, ``events.jsonl``, ``controls/events.jsonl`` and
    ``results.jsonl`` into ``run_dir``. The worktrees the reviewers read are made
    under ``scratch``, the review root, and each is removed once judged; the fresh
    copies the gate judges are made under ``run_dir/copies``, outside the review
    root, after every review has ended. Returns the rows written.

    With ``review_clean_twins``, each clean twin is also reviewed, in the same blind
    phase and under its own id, interleaved with the injected artefacts by id, and
    its review goes into the controls log before the control's gate line. Off unless
    asked for, and recorded in ``instrument.json`` either way.

    With ``lanes`` above one, that many reviews run at once, lane ``k`` under the review
    root ``scratch/lane-<k>`` with its own reviewers (``lane_reviewers[k]``, built for
    that root; the same ``reviewers`` for every lane when none are given). Each
    infrastructure failure is retried once per delay of ``retry_delays_s``, waited out
    with ``sleep`` first. ``per_class`` is the corpus size the caller held it to, and
    is recorded. ``progress`` is given a count-only line after each review; standard
    error when none is given.

    Raises:
        ReviewerRefusedError, ModelSeparationError: as :func:`require_reviewers`,
            and a review whose own model string is the author's.
        RunDirectoryError: as :func:`require_places`.
        BlindnessError: what a reviewer would be shown states an answer.
        CorpusError: the store refuses a node of the corpus.
    """
    if lanes < 1:
        msg = "a run reviews in at least one lane"
        raise RunDirectoryError(msg, lanes=str(lanes))
    sets = list(lane_reviewers) if lane_reviewers is not None else [reviewers] * lanes
    if len(sets) != lanes:
        msg = "every lane has its own set of reviewers, built for its own review root"
        raise ReviewerRefusedError(msg, lanes=str(lanes), sets=str(len(sets)))
    for reviewer_set in (reviewers, *sets):
        require_reviewers(corpus, reviewer_set)
    require_places(corpus.root, run_dir, scratch)
    gate = gate or PhysicsGate()
    author = corpus.manifest.author_model
    roles = sorted({a.assigned_role for a in corpus.artefacts})
    config = InstrumentConfig(
        run_id=run_id,
        seed=seed,
        corpus_label=corpus.manifest.label,
        corpus_manifest_sha256=corpus.manifest_sha256,
        author_model=author,
        reviewer_models={role: reviewers[role].model for role in roles},
        review_clean_twins=review_clean_twins,
        gate_mode=GATE_MODE,
        scopes=SCOPES,
        catalogue_sha256=catalogue_digest(),
        reviewing=reviewing,
        per_class=per_class,
        lanes=lanes,
        retry_delays_s=retry_delays_s,
    )
    run_dir.mkdir(parents=True, exist_ok=True)
    config_path = run_dir / CONFIG_NAME
    config_path.write_text(
        json.dumps(config.model_dump(mode="json"), indent=1, sort_keys=True) + "\n"
    )
    config_sha256 = digest(config_path)
    order = sorted(((review_id(seed, a.id), a) for a in corpus.artefacts), key=lambda p: p[0])
    twins = sorted(((control_id(seed, a.id), a) for a in corpus.artefacts), key=lambda p: p[0])
    twin_of = {a.id: cid for cid, a in twins}

    log = _start(run_dir / EVENTS_NAME, run_id, config_sha256, order)
    controls = _start(
        run_dir / CONTROLS_DIRNAME / EVENTS_NAME, f"{run_id}-controls", config_sha256, twins
    )
    reviews: dict[str, _Reviewed] = {}
    try:
        # Every review first, each on its own copy, before the gate has run on anything.
        queue_ = [(rid, a, a.injected, log) for rid, a in order]
        if review_clean_twins:
            queue_ += [(cid, a, a.clean, controls) for cid, a in twins]
        roots = [scratch] if lanes == 1 else [scratch / f"lane-{k}" for k in range(lanes)]
        _review_all(
            sorted(queue_, key=lambda q: q[0]),
            _Lanes(sets, roots, author, corpus, retry_delays_s, sleep),
            reviews,
            run_dir,
            progress or (lambda line: print(line, file=sys.stderr, flush=True)),
        )
        # The gate's copies are made in the run directory, never under the review root: a
        # reviewer session works under that root, and one still running, or anything a
        # reviewer wrote there, must find nothing the gate will read.
        copies = run_dir / COPIES_DIRNAME
        gated: dict[str, GateRan] = {}
        for rid, artefact in order:
            made = materialise(corpus.base, artefact.injected, copies / "gate" / rid)
            gated[rid] = log.append(
                GateRan(**log.envelope(), subtask_id=rid, attempt=1, result=_gate(gate, made, rid))
            )
        controlled: dict[str, GateResult] = {}
        for cid, artefact in twins:
            made = materialise(corpus.base, artefact.clean, copies / "control" / cid)
            controlled[cid] = _gate(gate, made, cid)
            controls.append(
                GateRan(**controls.envelope(), subtask_id=cid, attempt=1, result=controlled[cid])
            )
    finally:
        log.close()
        controls.close()

    rows = tuple(
        ResultRow(
            artefact=artefact.id,
            review_id=rid,
            error_class=artefact.error_class,
            expected_check=artefact.expected_check,
            reviewer_verdict=reviews[rid].outcome,
            review_cause=reviews[rid].cause,
            reviewer_model=reviews[rid].model,
            reviewer_tokens=reviews[rid].tokens,
            review_seq=reviews[rid].line.seq,
            gate_seq=gated[rid].seq,
            gate_verdict=gated[rid].result.verdict,
            gate_blocking=blocking(gated[rid].result),
            control_id=twin_of[artefact.id],
            control_reviewer_verdict=(
                reviews[twin_of[artefact.id]].outcome if review_clean_twins else None
            ),
            control_verdict=controlled[twin_of[artefact.id]].verdict,
            control_blocking=blocking(controlled[twin_of[artefact.id]]),
        )
        for rid, artefact in sorted(order, key=lambda p: p[1].id)
    )
    (run_dir / RESULTS_NAME).write_text(
        "".join(json.dumps(r.model_dump(mode="json"), sort_keys=True) + "\n" for r in rows)
    )
    return rows
