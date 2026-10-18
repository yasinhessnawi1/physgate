"""A tier of tasks checked without being read: counts and digests are all it prints.

A task's id is chosen by its author and can say what the task is, so a tier is reported
by the digest of each id, never the id itself, unless every task in it is a visible one
and the ids are asked for.

Each task must load whole, its scorer must pass its good reference and fail each bad one
on the spec it names, and its brief must not give its answer away: no number of the good
reference that is not a trivial 0 or 1 may appear among the brief's numbers. Runs in the
evaluation environment, since it runs the scorer.
"""

from __future__ import annotations

import hashlib
import math
import re
from pathlib import Path
from typing import Any

from physgate.evaluation.per_role.answer import read_lti_tf
from physgate.evaluation.per_role.authoring import sha256sums
from physgate.evaluation.per_role.exceptions import PerRoleError
from physgate.evaluation.per_role.scorers.control import check_references
from physgate.evaluation.per_role.task import LoadedTask, load_task

_NUMBER = re.compile(r"[-+]?(?:\d+\.?\d*|\.\d+)(?:[eE][-+]?\d+)?")


def brief_leaks(loaded: LoadedTask) -> bool:
    """Whether the brief states a non-trivial number of the good reference."""
    good = next(ref for ref in loaded.references if ref.fails is None)
    answer = read_lti_tf(Path(good.answer_path))
    numbers = [float(answer.gain.value), *answer.num_values(), *answer.den_values()]
    told = [float(x) for x in _NUMBER.findall(loaded.task.brief)]
    return any(
        math.isclose(n, t, rel_tol=1e-9, abs_tol=0.0)
        for n in numbers
        if n not in (0.0, 1.0, -1.0)
        for t in told
    )


def id_digest(name: str) -> str:
    """What a held-out task's id is reported as: the first 16 hex digits of its sha256."""
    return hashlib.sha256(name.encode()).hexdigest()[:16]


def validate(tier: Path, *, show_ids: bool = False) -> dict[str, Any]:
    """The tier's counts and digest; every task held to its references and its brief.

    Ids are reported as their digests unless ``show_ids`` is asked for and every task in
    the tier loads as a visible one; a task that does not load cannot show it is visible.
    """
    ids: list[str] = []
    held: list[str] = []
    leaks: list[str] = []
    refused: list[str] = []
    visible = True
    for entry in sorted(p for p in tier.iterdir() if p.is_dir()):
        try:
            loaded = load_task(entry)
        except (PerRoleError, OSError):
            # A directory with no task in it is a refused task, never a crash of the count.
            refused.append(entry.name)
            visible = False
            continue
        visible = visible and loaded.task.tier == "visible"
        ids.append(loaded.task.id)
        try:
            check_references(loaded)
            held.append(loaded.task.id)
        except PerRoleError:
            refused.append(loaded.task.id)
        if brief_leaks(loaded):
            leaks.append(loaded.task.id)
    shown = (lambda name: name) if show_ids and visible else id_digest
    return {
        "tasks": len(ids),
        "references_held": len(held),
        "refused": sorted(map(shown, refused)),
        "brief_gives_the_answer": sorted(map(shown, leaks)),
        "ids": sorted(map(shown, ids)),
        "ids_shown": show_ids and visible,
        "sha256": hashlib.sha256(sha256sums(tier).encode()).hexdigest(),
    }
