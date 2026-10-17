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
import random
import secrets
import shutil
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


def _place(source: Path, target: Path, tier: str, canary: str | None) -> None:
    task = parse_task((source / "task.json").read_bytes(), where=str(source))
    update: dict[str, Any] = {"tier": tier, "canary": canary}
    placed = parse_task(json.dumps({**task.model_dump(mode="json"), **update}).encode())
    shutil.copytree(source / "references", target / "references", symlinks=True)
    (target / "task.json").write_bytes(task_bytes(placed))


def split(
    staging: Path, visible: Path, held_out: Path, *, seed: int, per_tier: int = PER_TIER
) -> dict[str, Any]:
    """The staged tasks split by ``seed`` into the two tiers; the staging directory removed.

    Returns what may be shown: the visible ids, the number held out and the held-out tier's
    digest. The held-out tasks' canaries are written beside the held-out root, not inside it.

    Raises:
        AuthoringError: the staging directory does not hold exactly ``2 * per_tier`` tasks
            that each load whole with their references, or a target already exists.
    """
    entries = sorted(p for p in staging.iterdir() if p.is_dir() and not p.is_symlink())
    if len(entries) != 2 * per_tier or len(list(staging.iterdir())) != len(entries):
        msg = f"the staging directory holds {len(entries)} task directories, not {2 * per_tier}"
        raise AuthoringError(msg, staging=str(staging))
    loaded = [load_task(entry) for entry in entries]
    ids = [item.task.id for item in loaded]
    if len(set(ids)) != len(ids) or any(item.task.tier != "visible" for item in loaded):
        msg = "the staged tasks repeat an id, or are not written as visible tasks"
        raise AuthoringError(msg, staging=str(staging))
    if visible.exists() or held_out.exists():
        msg = "a tier's directory already exists; a split never writes over one"
        raise AuthoringError(msg, visible=str(visible), held_out=str(held_out))
    order = list(range(len(entries)))
    random.Random(seed).shuffle(order)
    canaries: dict[str, str] = {}
    for rank, index in enumerate(order):
        entry, task_id = entries[index], ids[index]
        if rank < per_tier:
            _place(entry, visible / task_id, "visible", None)
        else:
            canary = secrets.token_hex(16)
            canaries[task_id] = canary
            _place(entry, held_out / task_id, "held_out", canary)
    sums = sha256sums(held_out)
    (held_out / SUMS_NAME).write_text(sums, encoding="utf-8")
    (held_out.parent / f"{held_out.name}.{CANARIES_NAME}").write_text(
        json.dumps(sorted(canaries.values())) + "\n", encoding="utf-8"
    )
    shutil.rmtree(staging)
    return {
        "visible": sorted(p.name for p in visible.iterdir()),
        "held_out_count": len(canaries),
        "held_out_sha256": hashlib.sha256(sums.encode()).hexdigest(),
    }
