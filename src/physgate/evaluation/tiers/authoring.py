"""Own tasks: authored blind by a model that is not the implementers', then split, then sealed.

Authoring sessions write tasks for a role, one task at a time, into a directory of their
own; what holds is pooled until twenty-four are there. Each is told the task format, the
scorer's metrics and their units, the role's domain and the rule that every task composes
at least two requirements, and nothing of the harness: no role prompt, no knowledge, no
rubric, no visible task. Its model must differ from the model the run's implementers use
(ARCH-141); a request naming the same model is refused before anything runs.

A seeded split then sends eight tasks each to the visible, the validation and the held-out
tier, so all three come from one author, one brief and one distribution, and the gaps between
them measure overfitting to what was seen, not a difference in difficulty. The split takes
only what its entry check admits (:func:`entry_refusal`), and the pool takes only that too.
The validation and held-out tiers are protected alike: each of their tasks gets a canary, and
each tier's canary list lies inside it, beneath the root that protects it, where every layer
refuses it to a session as it refuses a task: a canary a session could read would tell it
what not to print. They are written under their protected root, outside the repository, and
only their digests and their lists' digests leave them; the staging directory is removed.

The validator (in the evaluation environment, since it runs the scorer) reports counts,
task ids and digests only, so a person can approve the held-out tier without reading it.
"""

from __future__ import annotations

import hashlib
import json
import os
import random
import secrets
import shutil
import stat
from itertools import combinations
from pathlib import Path
from typing import Any

from physgate.evaluation.per_role.exceptions import PerRoleError
from physgate.evaluation.per_role.metrics import CONTROL_METRIC_UNITS, CONTROL_SCORER_VERSION
from physgate.evaluation.tiers.task import Role, Task, fold_id, load_task, parse_task, task_bytes

PER_TIER = 8
CANARIES_NAME = "canaries.json"
SUMS_NAME = "SHA256SUMS"


class AuthoringError(PerRoleError):
    """An authoring request, a staging directory or a split is not as it must be."""


def require_author_model(author: str, implementer: str) -> None:
    """Refuse an author on the implementers' model (ARCH-141, I-5).

    Raises:
        AuthoringError: the two model strings are the same.
    """
    if author.strip() == implementer.strip():
        msg = (
            f"the tasks would be authored on {author!r}, the implementers' own model; "
            "an author is always another model"
        )
        raise AuthoringError(msg, author=author)


AUTHOR_BRIEF = """\
You are writing evaluation tasks for one engineering design role: {role}.

Write up to {count} tasks, one at a time. Your session has a fixed token budget and is
stopped when it is spent, or when too long passes without a new complete task; every
task directory that is complete at that moment is kept, and nothing else is. So write
each task completely (task.json and its references) before you begin the next, and
begin with a task, not with tools. Each task is a directory under the directory you work
in, named by the task's id, holding:
  - task.json: the task, in the format below;
  - references/good/{answer}: an answer that meets every headline specification;
  - references/bad_<what it gets wrong>/{answer} and expect.json, at least one per task:
    an answer built to fail one named headline specification, and
    expect.json = {{"fails": "<that spec's name>"}}.

task.json fields:
  id (lower case, dots allowed{id_rule}), role "{role}", tier "visible", source {{"kind": "own"}},
  brief (what the designer reads: the problem, every given value with its unit, every
  requirement the answer is held to, and where to write the answer),
  inputs (every given value as {{"name", "value", "unit"}}; a bare number is an error),
  answer {{"path": "{answer}", "form": "{form}"}},
  specs (each {{"name", "metric", "op", "bound", "counts": "headline", "composes": [...]}};
  op is one of >=, <=, >, <, in; bound is {{"value", "unit"}} or two of them for "in"),
  scorer {{"id": "{scorer}", "version": "{scorer_version}"}}.

The plant, given in inputs, is G(s) = plant_gain * N(s) / D(s) * exp(-plant_delay * s),
s in 1/s:
  - plant_num_0, plant_num_1, ...: the coefficients of N(s), highest power first, and
    plant_den_0, plant_den_1, ...: those of D(s), each numbered from 0 with no gap;
  - the coefficient of s^k is written in the unit "s**k" ("s" for k = 1, "1" for k = 0);
  - plant_gain (unit "1") and plant_delay (unit "s") are optional: 1 and 0 when absent;
  - actuator_limit: what the actuator can deliver, in the unit of the controller's output
    (a torque, a voltage, a force), given whenever a task bounds actuator_peak;
  - reference_step: the step's amplitude, in the unit of the plant's output; 1 when absent.

The loop is unity negative feedback around C(s) * G(s), driven by a unit step reference.
The metrics the scorer computes on it, each with the unit every bound on it is written in:
{metrics}
  - actuator_peak, in the unit of actuator_limit: the largest magnitude of the controller's
    output while the loop answers the reference step, over the settling_time horizon;
Every task bounds settling_time: the scorer simulates for twenty times its upper bound.

The answer, a controller C(s) = K * N(s) / D(s), is the file {answer}:
  {{"form": "{form}", "gain": {{"value": K, "unit": "1"}}, "num": [...], "den": [...]}}
with the coefficients of N and D highest power first, each {{"value", "unit"}} in the unit
of its power as above. It is proper (N no higher in degree than D) and of order at most 10.
Every task's brief tells the designer this format and the file to write it to.

Tools: in the directory you work in, python3 has python-control 0.10.1, numpy and scipy,
and nothing else can be installed (there is no network). A few short python3 calls per
task, to check a reference against the metrics above, are enough; a tool for every task
is not worth building. If a tool call is refused, do not repeat it: write the task's
files with what you know and move on.

Rules:
  - every task composes at least two requirements: the "composes" lists of its headline
    specifications name two or more distinct requirements between them;
  - the brief states every headline specification, and never states or hints at an answer:
    no number of the good reference other than 0, 1 or -1 appears in it;
  - vary the plants, the numbers and the combination of requirements across the tasks;
  - when you have finished, every reference is scored: a task whose good reference fails
    any headline specification, or whose bad reference does not fail the one it names, is
    refused.
"""


#: What each control metric measures, as the author is told it.
CONTROL_METRIC_MEANINGS: dict[str, str] = {
    "max_real_pole": "the largest real part of a closed-loop pole; the loop is stable when "
    "it is below 0",
    "phase_margin": "the smallest phase margin over every gain crossover, any delay "
    "included exactly; infinite with no gain crossover",
    "settling_time": "of the unit step response, to within 2 % of its final value; a "
    "response that does not settle fails every bound on it",
    "steady_state_error": "of the unit step response, |1 - T(0)|",
    "gain_margin_ratio": "the smallest gain margin over every phase crossover, as a ratio",
    "gain_margin_db": "the same gain margin in dB",
    "overshoot": "of the unit step response, in percent of its final value",
}


#: The tiers one round is split into, in the order of the seeded shuffle.
TIERS = ("visible", "validation", "held_out")


def entry_refusal(task: Task) -> str | None:
    """Why the split would not take ``task``, as a counted reason; ``None`` if it would.

    The split and the pool hold every task to this one check, so nothing enters the pool
    that would stop a later split: a task is written as a visible one (``tier_not_visible``;
    the schema makes a visible task one of our own), and carries no canary, which is given at
    the split and only there (``carries_canary``).
    """
    if task.tier != "visible":
        return "tier_not_visible"
    if task.canary is not None:
        return "carries_canary"
    return None


def author_brief(role: Role, *, count: int = len(TIERS) * PER_TIER, id_prefix: str = "") -> str:
    """What the authoring session is told: the format, the metrics, the rules. Nothing else.

    ``id_prefix`` is what every id must begin with, so that sessions pooled together do
    not write the same id; the author is told it and nothing about other sessions.
    """
    if role != "control":
        msg = f"no scorer exists yet for the {role} role's own tasks"
        raise AuthoringError(msg, role=role)
    metrics = "\n".join(
        f"  - {name}, in {unit}: {CONTROL_METRIC_MEANINGS[name]};"
        for name, unit in CONTROL_METRIC_UNITS.items()
    )
    return AUTHOR_BRIEF.format(
        role=role,
        count=count,
        id_rule=f', beginning with "{id_prefix}"' if id_prefix else "",
        answer="answer.json",
        form="lti_tf",
        scorer="control",
        scorer_version=CONTROL_SCORER_VERSION,
        metrics=metrics,
    )


def sha256sums(root: Path) -> str:
    """One ``<digest>  <path>`` line per file under ``root``, sorted by path."""
    lines = [
        f"{hashlib.sha256(p.read_bytes()).hexdigest()}  {p.relative_to(root).as_posix()}"
        for p in sorted(root.rglob("*"))
        if p.is_file() and p.name not in (SUMS_NAME, CANARIES_NAME)
    ]
    return "\n".join(lines) + "\n"


_DIR_FLAGS = os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW
_NEW_FILE = os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW


def _open_chain(path: Path, *, make: bool) -> int:
    """A descriptor for directory ``path``, reached from ``/`` one component at a time.

    No component is followed if it is a link: a link anywhere on the way, planted at the
    place or above it, refuses the write instead of redirecting it. With ``make``, a missing
    component is created on the way.

    Raises:
        AuthoringError: a component is a link or not a directory, or is missing.
    """
    if not path.is_absolute():
        msg = f"{path} is not an absolute path"
        raise AuthoringError(msg, path=str(path))
    fd = os.open("/", _DIR_FLAGS)
    try:
        for name in path.parts[1:]:
            try:
                next_fd = os.open(name, _DIR_FLAGS, dir_fd=fd)
            except FileNotFoundError:
                if not make:
                    raise
                os.mkdir(name, 0o700, dir_fd=fd)
                next_fd = os.open(name, _DIR_FLAGS, dir_fd=fd)
            os.close(fd)
            fd = next_fd
    except OSError as exc:
        os.close(fd)
        msg = f"{path} is reached through a link, or a part of it is not a directory"
        raise AuthoringError(msg, path=str(path)) from exc
    return fd


def _write_file(dir_fd: int, name: str, data: bytes) -> None:
    fd = os.open(name, _NEW_FILE, 0o600, dir_fd=dir_fd)
    try:
        os.write(fd, data)
    finally:
        os.close(fd)


#: What a file is called while it is written, before it is whole and given its own name.
_PARTIAL = ".{}.partial"


def _write_whole(dir_fd: int, name: str, data: bytes) -> None:
    """Write ``name`` under ``dir_fd`` so that, under that name, it is only ever whole.

    It is written under a name of its own first, which no reader takes for it, and renamed
    to ``name`` once every byte is down: a look at the directory finds the file whole, or
    not at all.
    """
    partial = _PARTIAL.format(name)
    _write_file(dir_fd, partial, data)
    os.rename(partial, name, src_dir_fd=dir_fd, dst_dir_fd=dir_fd)


def _read_file(dir_fd: int, name: str) -> bytes:
    fd = os.open(name, os.O_RDONLY | os.O_NOFOLLOW, dir_fd=dir_fd)
    try:
        with os.fdopen(os.dup(fd), "rb") as handle:
            return handle.read()
    finally:
        os.close(fd)


def _refuse_links(root: Path) -> None:
    """Refuse a staged tree holding anything but plain directories and regular files."""
    for entry in [root, *root.rglob("*")]:
        mode = entry.lstat().st_mode
        if stat.S_ISLNK(mode) or not (stat.S_ISDIR(mode) or stat.S_ISREG(mode)):
            msg = f"the staged {entry} is a link or not a plain file"
            raise AuthoringError(msg, path=str(entry))


def _copy_tree(source: Path, dir_fd: int) -> None:
    for entry in sorted(source.iterdir()):
        if entry.is_symlink():
            msg = f"the staged {entry} is a link"
            raise AuthoringError(msg, path=str(entry))
        if entry.is_dir():
            os.mkdir(entry.name, 0o700, dir_fd=dir_fd)
            child = os.open(entry.name, _DIR_FLAGS, dir_fd=dir_fd)
            try:
                _copy_tree(entry, child)
            finally:
                os.close(child)
        else:
            _write_file(dir_fd, entry.name, entry.read_bytes())


def _place(source: Path, tier_fd: int, tier: str, canary: str | None) -> None:
    task = parse_task((source / "task.json").read_bytes(), where=str(source))
    update: dict[str, Any] = {"tier": tier, "canary": canary}
    placed = parse_task(json.dumps({**task.model_dump(mode="json"), **update}).encode())
    os.mkdir(placed.id, 0o700, dir_fd=tier_fd)
    task_fd = os.open(placed.id, _DIR_FLAGS, dir_fd=tier_fd)
    try:
        os.mkdir("references", 0o700, dir_fd=task_fd)
        refs_fd = os.open("references", _DIR_FLAGS, dir_fd=task_fd)
        try:
            _copy_tree(source / "references", refs_fd)
        finally:
            os.close(refs_fd)
        _write_file(task_fd, "task.json", task_bytes(placed))
    finally:
        os.close(task_fd)


def _check_placed(tier_fd: int, task_id: str, tier: str, canary: str | None) -> None:
    """Read a written task back, without following links, and hold it to what was meant."""
    task_fd = os.open(task_id, _DIR_FLAGS, dir_fd=tier_fd)
    try:
        written = parse_task(_read_file(task_fd, "task.json"), where=task_id)
    finally:
        os.close(task_fd)
    if written.tier != tier or written.canary != canary:
        msg = f"the task {task_id!r} was not written as a {tier} task with its own canary"
        raise AuthoringError(msg, task=task_id)


def _apart(one: Path, other: Path) -> bool:
    return not (one == other or one.is_relative_to(other) or other.is_relative_to(one))


def split(
    staging: Path,
    visible: Path,
    held_out: Path,
    *,
    validation: Path,
    seed: int,
    per_tier: int = PER_TIER,
) -> dict[str, Any]:
    """The staged tasks split by ``seed`` into the three tiers; the staging directory removed.

    The staged tasks are shuffled by ``seed`` and cut in that order: the first ``per_tier``
    to the visible tier, the next to the validation tier, the last to the held-out tier.

    Returns what may be shown: the visible ids, and for each protected tier its count, its
    digest and its canary list's digest. Each protected tier's list is written inside it, as
    ``canaries.json`` beside its digest file, so it lies beneath the root that protects the
    tier; it is written whole (:func:`_write_whole`) and before any task, so the tier never
    holds a task without its list. Every write goes through directory descriptors reached
    without following a link, each task is read back and checked for its tier and canary,
    and no two tiers share a place.

    Raises:
        AuthoringError: the staging directory does not hold exactly ``3 * per_tier`` tasks
            that each load whole with their references and nothing but plain files, a task
            is one the entry check refuses (``refused_because`` says why) or repeats an id
            however it is spelt (``id_fold_collision``: :func:`.task.fold_id`),
            the tiers are not apart, a target already exists, or a link is on the way to one.
    """
    places = {"visible": visible, "validation": validation, "held_out": held_out}
    if not all(_apart(one, other) for one, other in combinations(places.values(), 2)):
        msg = "the visible, validation and held-out tiers must be apart: none the same or nested"
        raise AuthoringError(msg, **{name: str(path) for name, path in places.items()})
    _refuse_links(staging)
    entries = sorted(p for p in staging.iterdir() if p.is_dir())
    whole = len(TIERS) * per_tier
    if len(entries) != whole or len(list(staging.iterdir())) != len(entries):
        msg = f"the staging directory holds {len(entries)} task directories, not {whole}"
        raise AuthoringError(msg, staging=str(staging))
    loaded = [load_task(entry) for entry in entries]
    ids = [item.task.id for item in loaded]
    if len({fold_id(task_id) for task_id in ids}) != len(ids):
        msg = "the staged tasks repeat an id, however it is spelt (case, compatibility, separators)"
        raise AuthoringError(msg, staging=str(staging), refused_because="id_fold_collision")
    for item in loaded:
        reason = entry_refusal(item.task)
        if reason is not None:
            msg = f"a staged task is one the split does not take ({reason})"
            raise AuthoringError(msg, staging=str(staging), refused_because=reason)
    for path in places.values():
        if os.path.lexists(path):
            msg = f"{path} already exists (or a link stands there); a split never writes over one"
            raise AuthoringError(msg, path=str(path))
    order = list(range(len(entries)))
    random.Random(seed).shuffle(order)
    tier_of = {ids[index]: TIERS[n // per_tier] for n, index in enumerate(order)}
    canaries = {
        task_id: secrets.token_hex(16) for task_id, tier in tier_of.items() if tier != "visible"
    }
    listed = {
        tier: (
            json.dumps(sorted(c for t, c in canaries.items() if tier_of[t] == tier)) + "\n"
        ).encode()
        for tier in TIERS[1:]
    }
    fds: dict[str, int] = {}
    sums: dict[str, str] = {}
    try:
        for name, tier_path in places.items():
            parent = _open_chain(tier_path.parent, make=True)
            try:
                os.mkdir(tier_path.name, 0o700, dir_fd=parent)
            except FileExistsError as exc:
                msg = (
                    f"{tier_path} already exists (or a link stands there); "
                    "a split never writes over one"
                )
                raise AuthoringError(msg, path=str(tier_path)) from exc
            finally:
                os.close(parent)
            fds[name] = _open_chain(tier_path, make=False)
        for tier in TIERS[1:]:
            _write_whole(fds[tier], CANARIES_NAME, listed[tier])
        for index in order:
            task_id = ids[index]
            tier = tier_of[task_id]
            _place(entries[index], fds[tier], tier, canaries.get(task_id))
            _check_placed(fds[tier], task_id, tier, canaries.get(task_id))
        for tier in TIERS[1:]:
            sums[tier] = sha256sums(places[tier])
            _write_file(fds[tier], SUMS_NAME, sums[tier].encode())
    finally:
        for fd in fds.values():
            os.close(fd)
    shutil.rmtree(staging)
    shown: dict[str, Any] = {"visible": sorted(p.name for p in visible.iterdir())}
    for tier in TIERS[1:]:
        shown[f"{tier}_count"] = per_tier
        shown[f"{tier}_sha256"] = hashlib.sha256(sums[tier].encode()).hexdigest()
        shown[f"{tier}_canaries_sha256"] = hashlib.sha256(listed[tier]).hexdigest()
    return shown
