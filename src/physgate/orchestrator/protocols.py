"""The gate and the reviewer, as the loop calls them, and what each hands back.

The loop calls a ``Gate`` and then a ``Reviewer``, in that order, and ships no
implementation of either. A gate that passes everything "for now" would make
every downstream test green while enforcing nothing, so there is none: until the
physics gate registers one, the loop refuses to run past the gate stage in any
mode that needs a gate.

The result shapes are frozen here because two later pieces of work implement
them: the physics gate returns a ``GateResult`` and the reviewer a
``ReviewResult``. A repair instruction and an approval-queue item are built from
their fields by code, never phrased by a model.
"""

from __future__ import annotations

from typing import Annotated, Literal, Protocol, runtime_checkable

from pydantic import BaseModel, ConfigDict, Field, StringConstraints, model_validator

from physgate.orchestrator.common import ModelString, NonEmptyStr
from physgate.orchestrator.exceptions import GateContractError, ModelSeparationError

Count = Annotated[int, Field(ge=0)]

#: The gate modes in which a gate runs. Under ``off`` no gate runs and no result
#: exists at all; the loop records that the stage was skipped and why.
RunningGateMode = Literal["on", "observe"]
Verdict = Literal["pass", "fail"]


class _Frozen(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid", strict=True, allow_inf_nan=False)


class NumericOutput(_Frozen):
    """A number a check computed, with its unit. A bare number is not an output."""

    value: float | int
    unit: NonEmptyStr


class QuantityRef(_Frozen):
    """One quantity of one graph node, as a finding cites it."""

    node_id: NonEmptyStr
    name: NonEmptyStr
    value: float | int
    unit: NonEmptyStr


class Usage(_Frozen):
    """Token counts for one model message. Cache reads and writes are separate."""

    input_tokens: Count
    output_tokens: Count
    cache_read_input_tokens: Count
    cache_creation_input_tokens: Count

    def total(self) -> int:
        """Every token the message was charged for."""
        return (
            self.input_tokens
            + self.output_tokens
            + self.cache_read_input_tokens
            + self.cache_creation_input_tokens
        )


class MessageUsage(_Frozen):
    """One message's usage, keyed by its id so a repeated message is counted once."""

    message_id: NonEmptyStr
    usage: Usage


#: A session's captured stream of events, or a written account of a revision.
TrajectoryForm = Literal["session_stream", "account"]


class IssuedSpec(_Frozen):
    """A module specification as the decomposition issued it, and its digest then.

    ``commit`` is the commit that issued it; ``sha256`` was taken before the attempt
    was dispatched, so the bytes read at review must still be these.
    """

    commit: Annotated[str, StringConstraints(pattern=r"^[0-9a-f]{40}$")]
    path: NonEmptyStr
    sha256: Annotated[str, StringConstraints(pattern=r"^[0-9a-f]{64}$")]


#: Where the gate checks one attempt. System scope is the integration call's alone.
AttemptScope = Literal["subtask", "module"]


class Artefact(_Frozen):
    """What an attempt produced, as the gate and the reviewer receive it."""

    subtask_id: NonEmptyStr
    attempt: Annotated[int, Field(ge=1, le=3)]
    assigned_role: NonEmptyStr
    attempt_commit: Annotated[str, StringConstraints(pattern=r"^[0-9a-f]{40}$")]
    worktree: NonEmptyStr
    graph_root: NonEmptyStr
    trajectory: NonEmptyStr
    #: Where the gate checks this attempt: always its own nodes, and its module once
    #: the module is complete, which is when this is the last planned subtask for
    #: the module's directory.
    scopes: Annotated[tuple[AttemptScope, ...], Field(min_length=1)]
    #: The canonical journal's head before this attempt: nodes above it in the
    #: attempt's graph are the ones it wrote.
    base_revision: Annotated[int, Field(ge=0)]
    #: The trajectory's seal from the end of its session, for a reader to hold it to.
    trajectory_sha256: Annotated[str, StringConstraints(pattern=r"^[0-9a-f]{64}$")] | None = None
    trajectory_length: Annotated[int, Field(ge=0)] | None = None
    #: What the trajectory file is: a session's captured event stream, or, for an
    #: artefact no session produced, a written account of the revision.
    trajectory_form: TrajectoryForm = "session_stream"
    #: The commit the attempt's change is read against: where it left the run branch.
    base_commit: Annotated[str, StringConstraints(pattern=r"^[0-9a-f]{40}$")] | None = None
    #: The specification the attempt was issued, when a decomposition issued one.
    issued_spec: IssuedSpec | None = None
    #: The repository holding the attempt's commit, when it is not the run's own.
    repository: NonEmptyStr | None = None

    @model_validator(mode="after")
    def _own_nodes_always(self) -> Artefact:
        if "subtask" not in self.scopes or len(set(self.scopes)) != len(self.scopes):
            msg = "an attempt is always checked at subtask scope, and each scope once"
            raise ValueError(msg)
        return self


Revision = Annotated[int, Field(ge=1)]


class ChangeSet(_Frozen):
    """The journal revisions one merged attempt wrote: one "commit" of the design.

    A role writes only the nodes it owns, so a change and the nodes it constrains
    in other domains can never land in the same attempt. What changed together,
    and in what order, is therefore the unit the propagation check judges in.
    """

    subtask_id: NonEmptyStr
    attempt: Annotated[int, Field(ge=1, le=3)]
    revisions: Annotated[tuple[Revision, ...], Field(min_length=1)]


class IntegrationArtefact(_Frozen):
    """The whole design once every planned subtask has merged, as the gate checks it."""

    run_id: NonEmptyStr
    #: The canonical store, which the gate reads without writing.
    graph_root: NonEmptyStr
    #: The run branch's head: the design the integration call judges.
    run_head: Annotated[str, StringConstraints(pattern=r"^[0-9a-f]{40}$")]
    #: The journal's head when the run's design began: what decomposition wrote.
    #: Nodes at or below it are the given design; nothing in them was changed by
    #: the run, so nothing in them owes propagation.
    baseline_revision: Annotated[int, Field(ge=0)]
    #: Every revision above the baseline, grouped by the attempt that wrote it, in
    #: the order the attempts were applied.
    change_sets: tuple[ChangeSet, ...]

    @model_validator(mode="after")
    def _revisions_follow_the_baseline_in_order(self) -> IntegrationArtefact:
        revisions = [r for change in self.change_sets for r in change.revisions]
        if any(r <= self.baseline_revision for r in revisions):
            msg = "a change set names a revision at or below the baseline"
            raise ValueError(msg)
        if any(later <= earlier for earlier, later in zip(revisions, revisions[1:], strict=False)):
            msg = "change sets name each revision once, in the order it was written"
            raise ValueError(msg)
        return self


#: The architecture's physics checks, by name, with their numbers (ARCH-080).
CheckName = Literal[
    "units", "magnitude", "equilibrium", "power", "conservation", "thermal", "propagation"
]
CHECK_NUMBERS: dict[str, int] = {
    "units": 1,
    "magnitude": 2,
    "equilibrium": 3,
    "power": 4,
    "conservation": 5,
    "thermal": 6,
    "propagation": 7,
}
#: Where a check ran: on one attempt's own nodes, on a module, or on the whole system.
Scope = Literal["subtask", "module", "system"]
#: What one check found. ``unchecked`` is never a pass: it names what no check could judge.
Outcome = Literal["pass", "fail", "warn", "unchecked"]
Sha256 = Annotated[str, StringConstraints(pattern=r"^[0-9a-f]{64}$")]


class PassDetails(_Frozen):
    """A check that ran and found nothing wrong, and how many things it looked at."""

    form: Literal["pass"] = "pass"
    evaluated: Count


class UncheckedDetails(_Frozen):
    """The quantities no check could judge beyond what the record says."""

    form: Literal["unchecked"] = "unchecked"
    quantities: Annotated[tuple[NonEmptyStr, ...], Field(min_length=1)]


class UnitDetails(_Frozen):
    """Check 1: the offending expression and both unit sides."""

    form: Literal["units"] = "units"
    expression: NonEmptyStr
    left_unit: NonEmptyStr
    right_unit: NonEmptyStr


class MagnitudeDetails(_Frozen):
    """Check 2: the value, its expected range, and where the range comes from."""

    form: Literal["magnitude"] = "magnitude"
    value: NumericOutput
    low: NumericOutput
    high: NumericOutput
    source: NonEmptyStr
    table_sha256: Sha256


class ReactionValue(_Frozen):
    """One support's reaction: a force, and a moment where the support resists one."""

    support: NonEmptyStr
    force: NumericOutput
    moment: NumericOutput | None


class EquilibriumDetails(_Frozen):
    """Check 3: reaction forces and the unbalanced residual."""

    form: Literal["equilibrium"] = "equilibrium"
    solved: tuple[ReactionValue, ...]
    declared: tuple[ReactionValue, ...]
    residual_force: NumericOutput
    residual_moment: NumericOutput
    solver: NonEmptyStr


class PowerDetails(_Frozen):
    """Check 4: the deficit in watts and the nodes that contribute to it."""

    form: Literal["power"] = "power"
    deficit: NumericOutput
    contributing: Annotated[tuple[NonEmptyStr, ...], Field(min_length=1)]


class Term(_Frozen):
    """One term of a balance: a node's quantity."""

    node_id: NonEmptyStr
    name: NonEmptyStr
    value: NumericOutput


class ConservationDetails(_Frozen):
    """Check 5: the imbalance and the terms of the balance."""

    form: Literal["conservation"] = "conservation"
    imbalance: NumericOutput
    terms: Annotated[tuple[Term, ...], Field(min_length=1)]


class ThermalDetails(_Frozen):
    """Check 6: the margin, in kelvin or in watts."""

    form: Literal["thermal"] = "thermal"
    margin: NumericOutput


class PropagationDetails(_Frozen):
    """Check 7: the constrained edges a change left unwritten."""

    form: Literal["propagation"] = "propagation"
    unwritten: Annotated[tuple[NonEmptyStr, ...], Field(min_length=1)]


CheckDetails = Annotated[
    PassDetails
    | UncheckedDetails
    | UnitDetails
    | MagnitudeDetails
    | EquilibriumDetails
    | PowerDetails
    | ConservationDetails
    | ThermalDetails
    | PropagationDetails,
    Field(discriminator="form"),
]


class CheckRecord(_Frozen):
    """What one check found at one place, in one gate call (ARCH-080, ARCH-083).

    The gate builds these and the loop carries them in the gate's event line, so
    every check that ran is on the record with what it saw. ``reviewer_had_passed``
    is present and always empty here: the gate runs before any reviewer, and the
    catch-accounting reader fills it from the same attempt's review line, never by
    rewriting this one.
    """

    check: Annotated[int, Field(ge=1, le=7)]
    name: CheckName
    scope: Scope
    outcome: Outcome
    #: Whether a failure of this check blocks at this scope, whatever the run's mode.
    blocking: bool
    node: NonEmptyStr | None
    module: NonEmptyStr | None
    value: NumericOutput | None
    expected: NonEmptyStr | None
    tool: NonEmptyStr
    message: NonEmptyStr
    gate_mode: RunningGateMode
    reviewer_had_passed: None = None
    details: CheckDetails

    @model_validator(mode="after")
    def _consistent(self) -> CheckRecord:
        if CHECK_NUMBERS[self.name] != self.check:
            msg = f"check {self.check} is not the {self.name} check"
            raise ValueError(msg)
        if self.outcome == "warn" and self.blocking:
            msg = "a warning never blocks"
            raise ValueError(msg)
        expected = {"pass": "pass", "unchecked": "unchecked"}.get(self.outcome, self.name)
        if self.details.form != expected:
            msg = f"a {self.outcome} record of the {self.name} check carries {self.details.form}"
            raise ValueError(msg)
        return self


class GateResult(_Frozen):
    """What the physics gate hands back for one artefact.

    ``checks`` holds every check's record, and the verdict follows from them: it
    fails exactly when some check failed where a failure blocks, and
    ``failing_check`` names the first such check. The rule is the same under
    ``observe``: the verdict says what the gate would have refused, and the loop
    decides not to refuse it.
    """

    verdict: Verdict
    mode: RunningGateMode
    finding: NonEmptyStr
    failing_check: NonEmptyStr | None
    numeric_output: NumericOutput | None
    quantities: Annotated[tuple[QuantityRef, ...], Field(max_length=3)]
    checks: Annotated[tuple[CheckRecord, ...], Field(min_length=1)]
    #: Which catalogue of quantity kinds and relations judged this call. The catalogue
    #: decides what is checked at all, so a result that does not name it cannot be
    #: reproduced or compared with another.
    catalogue_sha256: Sha256

    @model_validator(mode="after")
    def _a_failure_names_its_check(self) -> GateResult:
        if (self.verdict == "fail") != (self.failing_check is not None):
            msg = "a failing verdict names the check that failed, and a pass names none"
            raise ValueError(msg)
        return self

    @model_validator(mode="after")
    def _the_verdict_is_what_the_records_say(self) -> GateResult:
        if any(record.gate_mode != self.mode for record in self.checks):
            msg = "every check record carries the mode the gate ran in"
            raise ValueError(msg)
        blocking = [r for r in self.checks if r.outcome == "fail" and r.blocking]
        if (self.verdict == "fail") != bool(blocking):
            msg = "the verdict fails exactly when a check failed where its failure blocks"
            raise ValueError(msg)
        if blocking and self.failing_check != blocking[0].name:
            msg = "the failing check is the first check whose failure blocks"
            raise ValueError(msg)
        return self


#: The rubric's four sections, as a verdict names them (ARCH-062).
RubricSection = Literal["acceptance_criteria", "domain_standards", "antipatterns", "reward_hacking"]
#: What a verdict says of one rubric item, in each section's own words (the approved
#: rubrics'): an acceptance criterion is ``met``, ``unmet`` or ``not evaluable``; a
#: domain standard or a skill-file antipattern is ``met``, ``unmet``, ``n/a`` (its
#: trigger is absent, with evidence) or ``not evaluable``; a reward-hacking indicator
#: is ``not observed``, ``noted`` (only suggested) or ``confirmed``. ``unmet`` and
#: ``confirmed`` reject. ``not evaluable`` is named by a specification defect, as the
#: role's rubric requires.
ItemResult = Literal["met", "unmet", "n/a", "not evaluable", "not observed", "noted", "confirmed"]
#: The results each section allows.
SECTION_RESULTS: dict[str, tuple[str, ...]] = {
    "acceptance_criteria": ("met", "unmet", "not evaluable"),
    "domain_standards": ("met", "unmet", "n/a", "not evaluable"),
    "antipatterns": ("met", "unmet", "n/a", "not evaluable"),
    "reward_hacking": ("not observed", "noted", "confirmed"),
}
#: The results that reject.
REJECTING_RESULTS = frozenset({"unmet", "confirmed"})
#: What a verdict says of one acceptance criterion of the issued specification.
CriterionResult = Literal["met", "unmet", "not evaluable"]
IndicatorKind = Literal["feature_isolation", "hard_coded_values", "disabled_checks"]
#: Confirmed rejects; noted is reported and does not; dismissed says why it is not one.
IndicatorDisposition = Literal["confirmed", "noted", "dismissed"]


class ItemVerdict(_Frozen):
    """What the review found for one rubric item."""

    item: NonEmptyStr
    section: RubricSection
    result: ItemResult
    #: Where in the diff, the worktree or the trajectory: file and line, or a tool call.
    evidence: str

    @model_validator(mode="after")
    def _a_result_its_section_allows(self) -> ItemVerdict:
        if self.result not in SECTION_RESULTS[self.section]:
            allowed = ", ".join(SECTION_RESULTS[self.section])
            msg = f"a {self.section} item is answered {allowed}, never {self.result}"
            raise ValueError(msg)
        if self.result == "n/a" and not self.evidence.strip():
            msg = "not applicable names the evidence that the item's trigger is absent"
            raise ValueError(msg)
        return self


class CriterionVerdict(_Frozen):
    """What the review found for one acceptance criterion of the issued specification."""

    #: The criterion's own reference: its number in the issued specification, or its text.
    criterion: NonEmptyStr
    result: CriterionResult
    evidence: NonEmptyStr


class IndicatorReport(_Frozen):
    """One reward-hacking indicator: raised by the review, or shown to it by the scan."""

    kind: IndicatorKind
    evidence: NonEmptyStr
    disposition: IndicatorDisposition
    reason: NonEmptyStr


class SpecDefect(_Frozen):
    """A finding against the specification as issued, not against the attempt.

    It goes to the approval queue as a note on the decomposition. A non-blocking one
    never changes the verdict. A blocking one is a safety-critical check that cannot
    be decided because the issued specification lacks its input: alone, it makes the
    review ``blocked``, which only the decomposition can resolve; beside a rejecting
    finding, the review is a reject that also names it.
    """

    finding: NonEmptyStr
    blocking: bool
    item: NonEmptyStr | None = None


#: Why a review that ran is not a verdict.
UnavailableCause = Literal[
    "infrastructure",
    "refused",
    "no_verdict",
    "invalid_verdict",
    "reading_incomplete",
    "compacted",
    "context_exceeded",
    "blocking_spec_defect",
    "unprepared",
]


class ReviewResult(_Frozen):
    """What a reviewer hands back, with the tokens it spent doing it.

    The fields after ``usage`` were added with the paired reviewers and are optional,
    so a review line written before them still reads. A verdict carries only
    non-blocking specification defects: one with a blocking defect is not a verdict.
    """

    verdict: Verdict
    finding: NonEmptyStr
    reviewer_model: ModelString
    session_id: Annotated[str, StringConstraints(pattern=r"^[A-Za-z0-9_-]{1,128}$")]
    usage: tuple[MessageUsage, ...]
    #: The rubric item that rejects, on a fail.
    failing_item: NonEmptyStr | None = None
    subject: NonEmptyStr | None = None
    numeric_output: NumericOutput | None = None
    items: tuple[ItemVerdict, ...] = ()
    #: One line per acceptance criterion of the issued specification.
    criteria: tuple[CriterionVerdict, ...] = ()
    indicators: tuple[IndicatorReport, ...] = ()
    spec_defects: tuple[SpecDefect, ...] = ()
    rubric_sha256: Sha256 | None = None
    rubric_kind: Literal["paired", "generalist"] | None = None
    packet_sha256: Sha256 | None = None
    reading_verified: bool | None = None
    #: The largest context any of the review's model messages had, in tokens.
    peak_context_tokens: Count | None = None
    #: How many structured answers the binary refused before this one, each told to the
    #: reviewer inside its session.
    schema_refusals: Count | None = None
    #: The output-token limit the review ran with. The window the binary keeps a
    #: session within depends on it, so a peak is read against both.
    max_output_tokens: Count | None = None
    #: The context window the binary reported for the review's model, if it did.
    context_window: Count | None = None

    @model_validator(mode="after")
    def _a_verdict_is_consistent(self) -> ReviewResult:
        rejecting = (
            any(i.result in REJECTING_RESULTS for i in self.items)
            or any(c.result == "unmet" for c in self.criteria)
            or any(r.disposition == "confirmed" for r in self.indicators)
        )
        blocking = any(d.blocking for d in self.spec_defects)
        if self.verdict == "pass" and (rejecting or blocking):
            msg = "a pass carries no rejecting finding and no blocking specification defect"
            raise ValueError(msg)
        if self.verdict == "fail" and blocking and not rejecting:
            msg = "a review whose only obstacle is a blocking defect is blocked, not a fail"
            raise ValueError(msg)
        return self


@runtime_checkable
class Gate(Protocol):
    """The physics gate: deterministic tooling, never a model (ARCH-004)."""

    def check(self, artefact: Artefact, *, mode: RunningGateMode) -> GateResult:
        """Check one attempt's ``artefact`` at its scopes and say whether it passes."""
        ...

    def check_integration(
        self, artefact: IntegrationArtefact, *, mode: RunningGateMode
    ) -> GateResult:
        """Check the integrated design at system scope and say whether it passes."""
        ...


@runtime_checkable
class Reviewer(Protocol):
    """A paired reviewer, on a different model from the implementer (ARCH-060)."""

    @property
    def model(self) -> str:
        """The pinned model string this reviewer runs on."""
        ...

    def review(self, artefact: Artefact) -> ReviewResult:
        """Review ``artefact`` and its full trajectory."""
        ...


def require_separate_models(*, implementer: str, reviewer: str) -> None:
    """Refuse to run a reviewer on the implementer's model string.

    Enforced here, at invocation, rather than trusted to configuration: a judge
    that shares a model with what it judges is the self-preference the
    architecture separates them to avoid.

    Raises:
        ModelSeparationError: the two strings are equal.
    """
    if implementer == reviewer:
        msg = "a reviewer may not run on the implementer's model"
        raise ModelSeparationError(msg, implementer=implementer, reviewer=reviewer)


def require_mode(result: GateResult, mode: RunningGateMode) -> GateResult:
    """Return ``result`` if it is for the mode the gate was asked to run in.

    Raises:
        GateContractError: it reports another mode.
    """
    if result.mode != mode:
        msg = "the gate reported a mode it was not asked to run in"
        raise GateContractError(msg, asked=mode, reported=result.mode)
    return result
