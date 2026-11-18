"""The isolation probe: whether each held-out scenario needs its requirements together.

A scenario that names two requirements but whose pass turns on one of them shows no gap when an
implementer has isolated that one feature (ARCH-141): the held-out tier would then read clean on
an implementer that tampers by isolating features, which is the gap the tier is there to show. The
tier's schema already refuses a task that declares fewer than two, so what the probe looks for is
composition that does not hold in substance.

**What it does.** For each task of a version's held-out tier, and each requirement the task's
headline specifications compose, it builds an answer aimed at that requirement's own
specifications alone (for the control role, the reference search :func:`.synthesise.search`,
seeded, given those specifications only) and scores that answer as the scenario scores any
answer, on every headline specification. Each answer is one of:

- not found: no answer meeting the requirement's own specifications was found;
- ``pass``: the scenario passes it, although it was built for one requirement only;
- ``fail``: the scenario fails it, on some specification the requirement does not cover;
- ``unscored`` or ``flaky``: the scenario could not judge it.

Each task is then exactly one of:

- **passed by a single-requirement answer:** some answer built for one requirement passes it.
  The task does not compose in substance, whatever it declares;
- **failed by every single-requirement answer:** an answer was found for every requirement it
  composes, and the scenario scored each of them ``fail``;
- **undecided:** neither, because an answer was not found or could not be judged. It is never
  counted as either of the others.

**What it prints, and keeps.** Counts only: the tasks probed, the requirements per task (how
many tasks compose how many), the answers by what became of them, and the tasks by the three
kinds above; beside them the version, the tier's digest as read, the seed and the way of
answering. Never a task's id, brief, specification or answer. Every probe that returns is one
measurement of the version, a line in the register keyed by the digest of what it returned,
counted before anything is returned; the count is in the result. It judges nothing: what counts
as a tier that composes is for the experiment that measures it to fix.

**What it refuses**, counting nothing: inside a harness session's environment (defence in
depth; what holds a session off is that the probe is given the role's withheld root, which every
run on the role withholds); anything but a role's withheld root; a role its way of answering is
not for; a register that cannot be read whole; a version the role does not have, or that the
register marks exposed as read now (also under the register's lock, when the measurement is
counted); a held-out tier that is not, as read, the bytes its manifest names; a task that cannot
be read; a task of another role; a task its way of answering cannot make a scenario of; a
scenario that names fewer than two requirements; an outcome no scenario gives.

**Whatever goes wrong, no held-out task is named.** Every refusal's words are fixed and name no
task. An error the probe did not foresee, once the held-out tier is read (in reading a task,
building an answer or scoring one), is refused as ``probe_failed`` with fixed words, since an
error's own words may name a held-out task; nothing is counted, and the answers built are removed.

The answers are built beneath the role's withheld root, each in a place of its own, and removed
when the probe ends: an answer built for a held-out task says something about that task.

It reads the held-out tier once, through descriptors (:func:`.heldout.snapshot`), and probes the
bytes whose digest it checked: one of the named openers of the protected tiers. It runs in the
evaluation environment, since the control role's way of answering runs the search and the scorer.
"""

from __future__ import annotations

import hashlib
import os
import shutil
import tempfile
from collections import Counter
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Literal, Protocol, get_args

from pydantic import ConfigDict, Field

from physgate.evaluation.per_role.exceptions import PerRoleError
from physgate.evaluation.tiers.base import _Frozen
from physgate.evaluation.tiers.heldout import _sums, snapshot
from physgate.evaluation.tiers.scenario import OUTCOMES, Scenario, ScenarioError, require_composing
from physgate.evaluation.tiers.store import WITHHELD, version_dir
from physgate.evaluation.tiers.task import Role, Task, canonical_json, parse_task

PROBE_FORMAT: Literal[1] = 1
#: The tier the probe reads: the one no implementer reads, whose scenarios must compose.
PROBED_TIER: Literal["held_out"] = "held_out"
#: Where an answer is built while the probe runs, beneath the role's withheld root.
WORK_PREFIX = ".probe-"

#: Builds, in the directory it is given, an answer aimed at one requirement's own
#: specifications alone; its path, or ``None`` when no such answer was found.
AnswerFor = Callable[[str, Path], Path | None]


class ProbeError(PerRoleError):
    """The probe refused: ``refused_because`` says why, and nothing it says names a task."""


def _refuse(reason: str, msg: str) -> ProbeError:
    return ProbeError(msg, refused_because=reason)


#: What the probe says of an error it did not foresee: fixed, since the error's own words may
#: name a held-out task.
FAILED = (
    "the probe stopped on an error; what the error says is not shown, since it may name a "
    "held-out task, and nothing was counted"
)


@dataclass(frozen=True)
class Probed:
    """One scenario, and how to build an answer for one of its requirements alone."""

    scenario: Scenario
    answer_for: AnswerFor


class Method(Protocol):
    """A way of answering for one role's tasks: what the probe asks of it."""

    @property
    def role(self) -> str:
        """The role whose tasks it builds answers for."""
        ...

    def describe(self) -> dict[str, Any]:
        """How it answers, as the result records it: what it is and its fixed parameters."""
        ...

    def probed(self, task: Task, seed: int) -> Probed:
        """``task`` as a scenario, with the answers it builds by ``seed``."""
        ...


class Answers(_Frozen):
    """What became of the answers the probe asked for, one per scenario and requirement."""

    model_config = ConfigDict(
        **_Frozen.model_config, serialize_by_alias=True, validate_by_name=True
    )

    asked: int
    found: int
    not_found: int
    # The outcomes of the answers found, each named as a scenario names it.
    pass_: int = Field(alias="pass")
    fail: int
    unscored: int
    flaky: int


class Findings(_Frozen):
    """The probe's counts for one tier: never an id."""

    tasks: int
    #: How many tasks compose how many requirements: ``{"2": 6, "3": 2}``.
    requirements_per_task: dict[str, int]
    answers: Answers
    tasks_passed_by_a_single_requirement_answer: int
    tasks_failed_by_every_single_requirement_answer: int
    tasks_undecided: int


Kind = Literal["passed", "failed", "undecided"]


def _kind(outcomes: Sequence[str | None]) -> Kind:
    """What one scenario's answers make it; ``None`` stands for an answer not found."""
    if "pass" in outcomes:
        return "passed"
    if outcomes and all(outcome == "fail" for outcome in outcomes):
        return "failed"
    return "undecided"


def probe_scenarios(probed: Sequence[Probed], work: Path) -> Findings:
    """Each scenario's answers for one requirement alone, built in ``work`` and scored; counted.

    Raises:
        ProbeError: a scenario names fewer than two requirements, or its score is no outcome.
    """
    answers: Counter[str] = Counter()
    kinds: Counter[Kind] = Counter()
    sizes: Counter[str] = Counter()
    for at, item in enumerate(probed):
        scenario = item.scenario
        try:
            require_composing(scenario)
        except ScenarioError:
            # The error names the scenario; only what is wrong is said.
            msg = "a scenario of the tier names fewer than two requirements"
            raise _refuse("scenario_not_composing", msg) from None
        requirements = sorted(set(scenario.requirements))
        sizes[str(len(requirements))] += 1
        outcomes: list[str | None] = []
        for number, requirement in enumerate(requirements):
            place = work / f"{at}-{number}"
            place.mkdir(mode=0o700)
            answers["asked"] += 1
            path = item.answer_for(requirement, place)
            if path is None:
                answers["not_found"] += 1
                outcomes.append(None)
                continue
            answers["found"] += 1
            outcome = scenario.score(path)
            if outcome not in OUTCOMES:
                msg = "a scenario's score is none of the outcomes a scenario gives"
                raise _refuse("outcome_unknown", msg)
            answers[outcome] += 1
            outcomes.append(outcome)
        kinds[_kind(outcomes)] += 1
    return Findings(
        tasks=len(probed),
        requirements_per_task=dict(sorted(sizes.items())),
        answers=Answers(
            asked=answers["asked"],
            found=answers["found"],
            not_found=answers["not_found"],
            pass_=answers["pass"],
            fail=answers["fail"],
            unscored=answers["unscored"],
            flaky=answers["flaky"],
        ),
        tasks_passed_by_a_single_requirement_answer=kinds["passed"],
        tasks_failed_by_every_single_requirement_answer=kinds["failed"],
        tasks_undecided=kinds["undecided"],
    )


class Measured(_Frozen):
    """The measurement the probe counted: its key in the register, and the version's count."""

    key: str
    count: int


class ProbeResult(_Frozen):
    """What one probe of a version's held-out tier returns: counts, and where they came from."""

    format: Literal[1]
    role: Role
    version: str
    tier: Literal["held_out"]
    tier_sha256: str
    seed: int
    method: dict[str, Any]
    findings: Findings
    measurement: Measured


def default_method() -> Method:
    """The control role's way of answering: the seeded search, aimed at one requirement.

    Raises:
        ImportError: the evaluation's numerical libraries are not in this environment.
    """
    from physgate.evaluation.per_role.probe import ControlSearch

    return ControlSearch()


def _tasks(files: dict[str, bytes]) -> list[Task]:
    """Every task of the tier, from bytes already read; refused without naming one."""
    names = sorted({name.partition("/")[0] for name in files if "/" in name})
    tasks: list[Task] = []
    for name in names:
        raw = files.get(f"{name}/task.json")
        try:
            if raw is None:
                raise PerRoleError("no task.json")
            tasks.append(parse_task(raw))
        except PerRoleError:
            raise _refuse("task_unreadable", "a task of the held-out tier cannot be read") from None
    return tasks


def _probed(method: Method, task: Task, role: str, seed: int) -> Probed:
    """``task`` as ``method``'s scenario; refused without naming it where it cannot be one."""
    if task.role != role:
        raise _refuse("task_of_another_role", "a task of the held-out tier is of another role")
    try:
        return method.probed(task, seed)
    except (PerRoleError, ValueError):
        # A scenario that refuses a task names it; only what is wrong is said.
        msg = "a task of the held-out tier is not one its way of answering makes a scenario of"
        raise _refuse("task_not_probed", msg) from None


def _probe_tier(
    files: dict[str, bytes], method: Method, role: str, seed: int, withheld: Path
) -> Findings:
    """The findings on the tier read as ``files``; the answers built beneath ``withheld``, removed.

    Raises:
        ProbeError: as :func:`probe_scenarios`, a task cannot be read, is of another role or is
            no scenario of ``method``'s, or an error the probe did not foresee (``probe_failed``).
    """
    try:
        probed = [_probed(method, task, role, seed) for task in _tasks(files)]
        work = Path(tempfile.mkdtemp(prefix=WORK_PREFIX, dir=withheld))
        try:
            return probe_scenarios(probed, work)
        finally:
            shutil.rmtree(work, ignore_errors=True)
    except ProbeError:
        raise
    except Exception:
        raise _refuse("probe_failed", FAILED) from None


def probe_version(
    withheld: Path, version: str, *, seed: int, method: Method | None = None
) -> ProbeResult:
    """Probe ``version``'s held-out tier, count it as one measurement, and return the counts.

    ``withheld`` is the role's withheld root, ``<store>/<role>/withheld``. ``method`` is the way
    of answering; the control role's when ``None`` (:func:`default_method`).

    Raises:
        ProbeError: the probe refuses (``refused_because`` says why), or stopped on an error once
            the tier was read (``probe_failed``); nothing is counted.
        ExposureError: asked for inside a session; the register cannot be read whole; or, as the
            measurement is counted, the version is marked exposed.
        ImportError: no method is given and this is not the evaluation environment.
    """
    from physgate.evaluation.tiers.exposure import (
        _refuse_inside_a_session,
        exposed_versions,
        record_measurement,
        register_lines,
        versions,
    )

    _refuse_inside_a_session()
    withheld = Path(os.path.realpath(withheld))
    store, role = withheld.parent.parent, withheld.parent.name
    if withheld.name != WITHHELD or role not in get_args(Role):
        raise _refuse("not_a_withheld_root", "the probe is given a role's withheld root")
    chosen = default_method() if method is None else method
    if chosen.role != role:
        msg = "the probe's way of answering is for another role's tasks"
        raise _refuse("role_not_probed", msg)
    # The register first: where it cannot be read, nothing else is.
    register_lines(store, role)  # type: ignore[arg-type]
    known = versions(store, role)  # type: ignore[arg-type]
    if version not in known:
        raise _refuse("version_unknown", f"the role has no version {version[:8]}")
    if version in exposed_versions(store, role):  # type: ignore[arg-type]
        msg = f"the version {version[:8]} is marked exposed as the register reads now"
        raise _refuse("version_exposed", msg)
    tier = version_dir(store, role, version) / PROBED_TIER  # type: ignore[arg-type]
    try:
        files = snapshot(tier)
    except (PerRoleError, OSError):
        # What could not be read may be a task's file; only the tier is said.
        raise _refuse("tier_unreadable", "the held-out tier cannot be read whole") from None
    digest = hashlib.sha256(_sums(files).encode()).hexdigest()
    if digest != known[version].held_out.sha256:
        msg = "the held-out tier is not, as read now, the bytes its version's manifest names"
        raise _refuse("tier_changed", msg)
    findings = _probe_tier(files, chosen, role, seed, withheld)
    payload: dict[str, Any] = {
        "format": PROBE_FORMAT,
        "role": role,
        "version": version,
        "tier": PROBED_TIER,
        "tier_sha256": digest,
        "seed": seed,
        "method": chosen.describe(),
        "findings": findings.model_dump(mode="json"),
    }
    key = hashlib.sha256(canonical_json(payload)).hexdigest()
    # Counted before anything is returned: a probe's result is never seen uncounted.
    count = record_measurement(store, role, version, measured="probe", key=key)  # type: ignore[arg-type]
    return ProbeResult(
        format=PROBE_FORMAT,
        role=role,  # type: ignore[arg-type]
        version=version,
        tier=PROBED_TIER,
        tier_sha256=digest,
        seed=seed,
        method=payload["method"],
        findings=findings,
        measurement=Measured(key=key, count=count),
    )
