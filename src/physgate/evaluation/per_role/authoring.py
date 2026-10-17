"""Own tasks: authored blind by a model that is not the implementers', then split, then sealed.

One authoring session writes sixteen tasks for a role into a staging directory of its
own. It is told the task format, the scorer's metrics and their units, the role's domain
and the rule that every task composes at least two requirements, and nothing of the
harness: no role prompt, no knowledge, no rubric, no visible task. Its model must differ
from the model the run's implementers use (ARCH-141); a request naming the same model is
refused before anything runs.

A seeded split then sends eight tasks to the visible tier and eight to the held-out tier,
so both tiers come from one author, one session and one distribution, and the gap between
them measures overfitting to what was seen, not a difference in difficulty. Each held-out
task gets a canary. The held-out tier is written under its protected root, outside the
repository, and only its digest leaves it; the staging directory is removed.

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
from pathlib import Path
from typing import Any

from physgate.evaluation.per_role.exceptions import PerRoleError
from physgate.evaluation.per_role.metrics import CONTROL_METRIC_UNITS
from physgate.evaluation.per_role.task import Role, load_task, parse_task, task_bytes

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

Write exactly {count} tasks. Each is a directory under the directory you work in, named by
the task's id, holding:
  - task.json: the task, in the format below;
  - references/good/{answer}: an answer that meets every headline specification;
  - references/bad_<what it gets wrong>/{answer} and expect.json, at least one per task:
    an answer built to fail one named headline specification, and
    expect.json = {{"fails": "<that spec's name>"}}.

task.json fields:
  id (lower case, dots allowed), role "{role}", tier "visible", source {{"kind": "own"}},
  brief (what the designer reads: the problem, every given value with its unit, every
  requirement the answer is held to, and where to write the answer),
  inputs (every given value as {{"name", "value", "unit"}}; a bare number is an error),
  answer {{"path": "{answer}", "form": "{form}"}},
  specs (each {{"name", "metric", "op", "bound", "counts": "headline", "composes": [...]}};
  op is one of >=, <=, >, <, in; bound is {{"value", "unit"}} or two of them for "in"),
  scorer {{"id": "{scorer}", "version": "{scorer_version}"}}.

The metrics the scorer computes, with the unit every bound on each must be written in:
{metrics}

Rules:
  - every task composes at least two requirements: the "composes" lists of its headline
    specifications name two or more distinct requirements between them;
  - the brief states every headline specification, and never states or hints at an answer;
  - vary the plants, the numbers and the combination of requirements across the tasks;
  - the good reference must pass when scored; check it with the scorer command you have.
"""


def author_brief(role: Role, *, count: int = 2 * PER_TIER) -> str:
    """What the authoring session is told: the format, the metrics, the rules. Nothing else."""
    if role != "control":
        msg = f"no scorer exists yet for the {role} role's own tasks"
        raise AuthoringError(msg, role=role)
    metrics = "\n".join(f"  - {name}: {unit}" for name, unit in CONTROL_METRIC_UNITS.items())
    return AUTHOR_BRIEF.format(
        role=role,
        count=count,
        answer="answer.json",
        form="lti_tf",
        scorer="control",
        scorer_version="1.0.0",
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
    staging: Path, visible: Path, held_out: Path, *, seed: int, per_tier: int = PER_TIER
) -> dict[str, Any]:
    """The staged tasks split by ``seed`` into the two tiers; the staging directory removed.

    Returns what may be shown: the visible ids, the number held out and the held-out tier's
    digest. The held-out tasks' canaries are written beside the held-out root, not inside it.
    Every write goes through directory descriptors reached without following a link, each
    task is read back and checked for its tier and canary, and the two tiers never share a
    place.

    Raises:
        AuthoringError: the staging directory does not hold exactly ``2 * per_tier`` tasks
            that each load whole with their references and nothing but plain files, the
            tiers are not apart, a target already exists, or a link is on the way to one.
    """
    if not _apart(visible, held_out):
        msg = "the visible and held-out tiers must be apart: neither the same nor nested"
        raise AuthoringError(msg, visible=str(visible), held_out=str(held_out))
    _refuse_links(staging)
    entries = sorted(p for p in staging.iterdir() if p.is_dir())
    if len(entries) != 2 * per_tier or len(list(staging.iterdir())) != len(entries):
        msg = f"the staging directory holds {len(entries)} task directories, not {2 * per_tier}"
        raise AuthoringError(msg, staging=str(staging))
    loaded = [load_task(entry) for entry in entries]
    ids = [item.task.id for item in loaded]
    if len(set(ids)) != len(ids) or any(item.task.tier != "visible" for item in loaded):
        msg = "the staged tasks repeat an id, or are not written as visible tasks"
        raise AuthoringError(msg, staging=str(staging))
    order = list(range(len(entries)))
    random.Random(seed).shuffle(order)
    canaries = {ids[index]: secrets.token_hex(16) for index in order[per_tier:]}
    fds: dict[str, int] = {}
    try:
        for name, tier_path in (("visible", visible), ("held_out", held_out)):
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
        for index in order:
            task_id = ids[index]
            tier = "held_out" if task_id in canaries else "visible"
            _place(entries[index], fds[tier], tier, canaries.get(task_id))
            _check_placed(fds[tier], task_id, tier, canaries.get(task_id))
        sums = sha256sums(held_out)
        _write_file(fds["held_out"], SUMS_NAME, sums.encode())
        parent = _open_chain(held_out.parent, make=False)
        try:
            payload = json.dumps(sorted(canaries.values())) + "\n"
            _write_file(parent, f"{held_out.name}.{CANARIES_NAME}", payload.encode())
        finally:
            os.close(parent)
    finally:
        for fd in fds.values():
            os.close(fd)
    shutil.rmtree(staging)
    return {
        "visible": sorted(p.name for p in visible.iterdir()),
        "held_out_count": len(canaries),
        "held_out_sha256": hashlib.sha256(sums.encode()).hexdigest(),
    }
