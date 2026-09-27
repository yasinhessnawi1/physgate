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

The gate then judges each injected artefact over a fresh copy of it (a reviewer
that wrote to its worktree changes nothing the gate reads) in one call at all
three scopes, in ``observe``, with the patch as the one change set above the
base. It also judges each clean patch, as a control that the artefact was
otherwise valid; the controls have a log of their own, so the run's log counts
the injected artefacts alone.

The run's log is an ordinary run-event log: a start line, one planned subtask
per artefact, then the review lines, then the gate lines. So ``physgate
gate-events`` and ``physgate catches`` read it like any run, and the stamp on
each gate event is the review that came before it on the same artefact. The
loop's replay would refuse it (a review before a gate), and it is never
resumed: a killed run is started again into new directories.

Artefacts run under an id derived from the seed and the corpus id, in the
order those ids sort, so the log shows no corpus id and no class order. The
results file has one row per artefact, in corpus id order, and **no total**:
what the rows add up to is the experiment's to state.
"""

from __future__ import annotations

import hashlib
import json
import shutil
from collections.abc import Mapping
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
from physgate.evaluation.inject.exceptions import ReviewerRefusedError, RunDirectoryError
from physgate.evaluation.inject.materialise import (
    DESIGN_DIRNAME,
    Materialised,
    materialise,
    require_blind,
)
from physgate.gate.catalogue import catalogue_digest
from physgate.gate.graph import ChangeHistory, GraphView
from physgate.gate.runner import PhysicsGate
from physgate.orchestrator.common import ModelString, NonEmptyStr
from physgate.orchestrator.events import EventLog, GateRan, ReviewRan, RunStarted, SubtaskPlanned
from physgate.orchestrator.protocols import (
    Artefact,
    ChangeSet,
    CheckName,
    GateResult,
    Reviewer,
    ReviewResult,
    Scope,
    Verdict,
    require_separate_models,
)

#: One gate call per artefact, at every scope: for a design written as one change
#: set these are exactly the scopes the loop's two calls cover.
SCOPES: tuple[Scope, ...] = ("subtask", "module", "system")
GATE_MODE: Literal["observe"] = "observe"
EVENTS_NAME = "events.jsonl"
RESULTS_NAME = "results.jsonl"
CONFIG_NAME = "instrument.json"
CONTROLS_DIRNAME = "controls"
ReviewId = Annotated[str, StringConstraints(pattern=r"^r[0-9a-f]{12}$")]
Sha256 = Annotated[str, StringConstraints(pattern=r"^[0-9a-f]{64}$")]


class _Frozen(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid", strict=True)


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


class ResultRow(_Frozen):
    """One artefact: what it is, what its reviewer said, and what the gate said after."""

    artefact: ArtefactId
    #: The id the artefact ran under in the run's log.
    review_id: ReviewId
    error_class: ErrorClass
    expected_check: CheckName
    reviewer_verdict: Verdict
    reviewer_model: ModelString
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
    control_reviewer_verdict: Verdict | None
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
        RunDirectoryError: one exists and is not empty, or one is inside another.
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
) -> ReviewResult:
    """One blind review of ``patch`` over ``base``, on a copy removed once it is judged.

    The copy is gone before the next review starts, so no reviewer finds another's
    artefact, or an artefact's twin, beside its own.
    """
    made = materialise(base, patch, place)
    try:
        require_blind(made, (artefact.id, artefact.description))
        result = reviewer.review(
            Artefact(
                subtask_id=subtask,
                attempt=1,
                assigned_role=artefact.assigned_role,
                attempt_commit=made.commit,
                worktree=str(made.worktree),
                graph_root=str(made.graph_root),
                trajectory=str(made.trajectory),
                scopes=("subtask", "module"),
                base_revision=made.baseline,
            )
        )
    finally:
        shutil.rmtree(place)
    require_separate_models(implementer=author, reviewer=result.reviewer_model)
    return result


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
) -> tuple[ResultRow, ...]:
    """Review every artefact of ``corpus`` blind, then gate each, and write the results.

    Writes ``instrument.json``, ``events.jsonl``, ``controls/events.jsonl`` and
    ``results.jsonl`` into ``run_dir``; the materialised worktrees go under
    ``scratch``. Returns the rows written.

    With ``review_clean_twins``, each clean twin is also reviewed, in the same blind
    phase and under its own id, interleaved with the injected artefacts by id, and
    its review goes into the controls log before the control's gate line. Off unless
    asked for, and recorded in ``instrument.json`` either way.

    Raises:
        ReviewerRefusedError, ModelSeparationError: as :func:`require_reviewers`,
            and a review whose own model string is the author's.
        RunDirectoryError: as :func:`require_places`.
        BlindnessError: what a reviewer would be shown states an answer.
        CorpusError: the store refuses a node of the corpus.
    """
    require_reviewers(corpus, reviewers)
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
    reviews: dict[str, ReviewRan] = {}
    try:
        # Every review first, each on its own copy, before the gate has run on anything.
        queue = [(rid, a, a.injected, log) for rid, a in order]
        if review_clean_twins:
            queue += [(cid, a, a.clean, controls) for cid, a in twins]
        for subtask, artefact, patch, into in sorted(queue, key=lambda q: q[0]):
            result = _review(
                reviewers[artefact.assigned_role],
                author,
                corpus.base,
                patch,
                scratch / "review" / subtask,
                subtask,
                artefact,
            )
            reviews[subtask] = into.append(
                ReviewRan(**into.envelope(), subtask_id=subtask, attempt=1, result=result)
            )
        gated: dict[str, GateRan] = {}
        for rid, artefact in order:
            made = materialise(corpus.base, artefact.injected, scratch / "gate" / rid)
            gated[rid] = log.append(
                GateRan(**log.envelope(), subtask_id=rid, attempt=1, result=_gate(gate, made, rid))
            )
        controlled: dict[str, GateResult] = {}
        for cid, artefact in twins:
            made = materialise(corpus.base, artefact.clean, scratch / "control" / cid)
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
            reviewer_verdict=reviews[rid].result.verdict,
            reviewer_model=reviews[rid].result.reviewer_model,
            reviewer_tokens=sum(m.usage.total() for m in reviews[rid].result.usage),
            review_seq=reviews[rid].seq,
            gate_seq=gated[rid].seq,
            gate_verdict=gated[rid].result.verdict,
            gate_blocking=blocking(gated[rid].result),
            control_id=twin_of[artefact.id],
            control_reviewer_verdict=(
                reviews[twin_of[artefact.id]].result.verdict if review_clean_twins else None
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
