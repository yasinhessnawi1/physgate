"""A tier of tasks checked without being read: counts, ids and digests are all it prints.

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


def validate(tier: Path) -> dict[str, Any]:
    """The tier's counts, ids and digest; every task held to its references and its brief."""
    ids: list[str] = []
    held: list[str] = []
    leaks: list[str] = []
    refused: list[str] = []
    for entry in sorted(p for p in tier.iterdir() if p.is_dir()):
        try:
            loaded = load_task(entry)
        except PerRoleError:
            refused.append(entry.name)
            continue
        ids.append(loaded.task.id)
        try:
            check_references(loaded)
            held.append(loaded.task.id)
        except PerRoleError:
            refused.append(loaded.task.id)
        if brief_leaks(loaded):
            leaks.append(loaded.task.id)
    return {
        "tasks": len(ids),
        "references_held": len(held),
        "refused": sorted(refused),
        "brief_gives_the_answer": sorted(leaks),
        "ids": sorted(ids),
        "sha256": hashlib.sha256(sha256sums(tier).encode()).hexdigest(),
    }
