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
from collections import Counter
from pathlib import Path
from typing import Any, NamedTuple

from physgate.evaluation.per_role.answer import read_lti_tf
from physgate.evaluation.per_role.exceptions import PerRoleError
from physgate.evaluation.per_role.scorers.control import check_references, score
from physgate.evaluation.tiers.authoring import entry_refusal, sha256sums
from physgate.evaluation.tiers.task import LoadedTask, load_task

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


class _Seen(NamedTuple):
    directory: str
    task: str | None
    held: bool
    leaks: bool
    visible: bool
    #: Why the split would not take the task (:func:`.authoring.entry_refusal`), or ``None``.
    refused: str | None = None


def _leaks(loaded: LoadedTask) -> bool | None:
    """Whether the brief gives the answer away; ``None`` when that cannot be checked.

    A check that fails (the good reference's answer cannot be read, say) never ends the
    count and never passes the task: it is a task whose brief is unchecked, refused.
    """
    try:
        return brief_leaks(loaded)
    except Exception:  # noqa: BLE001 - a check that cannot run refuses, never passes
        return None


def _examine(tier: Path) -> list[_Seen]:
    seen = []
    for entry in sorted(p for p in tier.iterdir() if p.is_dir()):
        try:
            loaded = load_task(entry)
        except (PerRoleError, OSError):
            # A directory with no task in it is a refused task, never a crash of the count.
            seen.append(_Seen(entry.name, None, False, False, False))
            continue
        try:
            check_references(loaded)
            held = True
        except PerRoleError:
            held = False
        seen.append(
            _Seen(
                entry.name,
                loaded.task.id,
                held,
                _leaks(loaded) is not False,
                loaded.task.tier == "visible",
                entry_refusal(loaded.task),
            )
        )
    return seen


def sound(tier: Path) -> list[str]:
    """The tasks of ``tier`` a split may take, by directory; for the runner, never printed.

    A task qualifies when it loads, the split's own entry check admits it, its scorer holds
    its references, its brief can be checked and gives nothing away, and its directory is
    named by its own id.
    """
    return [
        s.directory
        for s in _examine(tier)
        if s.task == s.directory and s.held and not s.leaks and s.refused is None
    ]


def validate(tier: Path, *, show_ids: bool = False) -> dict[str, Any]:
    """The tier's counts and digest; every task held to its references and its brief.

    Ids are reported as their digests unless ``show_ids`` is asked for and every task in
    the tier loads as a visible one; a task that does not load cannot show it is visible.
    """
    seen = _examine(tier)
    loaded = [s for s in seen if s.task is not None]
    visible = all(s.visible for s in seen)
    shown = (lambda name: name) if show_ids and visible else id_digest
    refused = [s.directory if s.task is None else s.task for s in seen if not s.held]
    return {
        "tasks": len(loaded),
        "references_held": sum(s.held for s in loaded),
        "refused": sorted(map(shown, refused)),
        "brief_gives_the_answer": sorted(shown(s.task) for s in loaded if s.task and s.leaks),
        "ids": sorted(shown(s.task) for s in loaded if s.task),
        "ids_shown": show_ids and visible,
        "sha256": hashlib.sha256(sha256sums(tier).encode()).hexdigest(),
    }


def refusal_reasons(tier: Path) -> dict[str, int]:
    """Why the tasks of ``tier`` that a split may not take are refused, as counts only.

    Each reason is a category with, where it applies, a metric's name (a fixed vocabulary
    that says nothing of the task): ``not_a_task``, ``scorer_refuses_task``,
    ``good_fails:<metric>``, ``bad_passes:<metric>``, ``brief_leak``, ``brief_unchecked``
    (the leak check itself failed), ``id_not_directory``, and the split's entry check's own
    reasons (``tier_not_visible``, ``carries_canary``). A task counts once under each reason
    it has.
    """
    reasons: Counter[str] = Counter()
    for entry in sorted(p for p in tier.iterdir() if p.is_dir()):
        try:
            loaded = load_task(entry)
        except (PerRoleError, OSError):
            reasons["not_a_task"] += 1
            continue
        task = loaded.task
        metric = {spec.name: spec.metric for spec in task.specs}
        found: set[str] = set()
        try:
            for ref in loaded.references:
                record = score(task, Path(ref.answer_path))
                failed = {
                    row["name"]
                    for row in record["specs"]
                    if row["counts"] == "headline" and not row["passed"]
                }
                if ref.fails is None and not record["passed"]:
                    found |= {f"good_fails:{metric[name]}" for name in failed} or {
                        "good_fails:unreadable_answer"
                    }
                if ref.fails is not None and ref.fails not in failed:
                    found.add(f"bad_passes:{metric[ref.fails]}")
        except PerRoleError:
            found.add("scorer_refuses_task")
        leaks = _leaks(loaded)
        if leaks is None:
            found.add("brief_unchecked")
        elif leaks:
            found.add("brief_leak")
        refused = entry_refusal(task)
        if refused is not None:
            found.add(refused)
        if task.id != entry.name:
            found.add("id_not_directory")
        reasons.update(found)
    return dict(sorted(reasons.items()))
