"""The own tasks' authoring session, and the blind check of the held-out tier, end to end.

**Authoring.** One session, on a model that is not the implementers', is given the author
brief and nothing else, and works in a fresh directory outside every held-out root (the
``baseline`` profile it runs under refuses those roots). When it ends, the runner:

1. copies each task it left into a staging directory beside its work, refusing a task
   that holds a link, a special file or more than a task's worth of files;
2. holds every staged task to its references and its brief (:func:`.validate.sound`), and
   never prints one: what leaves is counts and digests;
3. if fewer tasks hold than the two tiers need, keeps nothing and says how many held; a
   second session may then be run. There is no self-check inside the session in round 1;
4. otherwise takes the tiers' worth by a seeded draw, and splits them by the same seed:
   the visible tier where asked, the held-out tier inside its protected root;
5. moves the session's stream and record inside the protected root, since they hold every
   task the session wrote, and removes the work directory.

**The blind check.** A second session, on a model that is not the implementers' either,
reads the held-out tasks from a file placed in its own work directory (never its prompt,
which any process of the same user can list), keyed by the digest of each id, without
their references or canaries. It answers three questions per task with true or false and
nothing else. Its answer is read strictly: anything but those booleans for exactly those
keys is no answer. Its stream is moved inside the protected root as well. What leaves is
counts and the digests of the tasks with a ``false``.

Both are tested against the scripted endpoint; a real session is started by a person.
"""

from __future__ import annotations

import json
import random
import shutil
import stat
from collections.abc import Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from pydantic import BaseModel, ConfigDict, RootModel, ValidationError

from physgate.evaluation.per_role.arms.raw import RawSetup, run_session
from physgate.evaluation.per_role.authoring import (
    PER_TIER,
    AuthoringError,
    author_brief,
    require_author_model,
    split,
)
from physgate.evaluation.per_role.task import Role, load_task
from physgate.evaluation.per_role.validate import id_digest, sound, validate

#: The most files and bytes one staged task may hold: a task, a good reference and a few
#: bad ones, each a small JSON file.
MOST_FILES_PER_TASK = 64
MOST_BYTES_PER_TASK = 2 * 1024 * 1024


@dataclass(frozen=True)
class AuthoringPlan:
    """Where one authoring session works and where its two tiers go."""

    role: Role
    implementer_model: str
    #: A directory that does not exist yet, outside every held-out root.
    work: Path
    #: The visible tier's directory, which must not exist yet.
    visible: Path
    #: The protected root the held-out tier goes inside, as ``<root>/<role>``.
    held_out_root: Path
    seed: int
    cap: int
    #: How many tasks the session is asked for: at least the two tiers' worth.
    count: int = 2 * PER_TIER


def held_out_tier(root: Path, role: Role) -> Path:
    """Where a role's held-out tier lives inside its protected root."""
    return root / role


def _inside(path: Path, root: Path) -> bool:
    one, other = path.resolve(), root.resolve()
    return one == other or one.is_relative_to(other) or other.is_relative_to(one)


def _withheld(path: Path, roots: Sequence[Path]) -> bool:
    """Whether ``path`` is one of ``roots`` or inside one."""
    return any(path.resolve().is_relative_to(r.resolve()) for r in roots)


def _require_apart(plan: AuthoringPlan, setup: RawSetup) -> None:
    roots = [Path(r) for r in setup.held_out]
    if not _withheld(plan.held_out_root, roots):
        msg = "the session does not withhold the protected root the held-out tier goes in"
        raise AuthoringError(msg, root=str(plan.held_out_root))
    for name, path in (("work", plan.work), ("visible tier", plan.visible)):
        if any(_inside(path, r) for r in roots):
            msg = f"the {name} is inside a held-out root, or holds one"
            raise AuthoringError(msg, path=str(path))
    tier = held_out_tier(plan.held_out_root, plan.role)
    if plan.work.exists() or plan.visible.exists() or tier.exists():
        msg = "the work directory and both tiers are made new for each session"
        raise AuthoringError(msg, work=str(plan.work), visible=str(plan.visible))
    if plan.count < 2 * PER_TIER:
        msg = f"a session is asked for at least {2 * PER_TIER} tasks"
        raise AuthoringError(msg, count=str(plan.count))


def _plain_tree(directory: Path) -> bool:
    """Whether ``directory`` holds only plain directories and small regular files."""
    files = 0
    size = 0
    for entry in [directory, *directory.rglob("*")]:
        mode = entry.lstat().st_mode
        if stat.S_ISLNK(mode) or not (stat.S_ISDIR(mode) or stat.S_ISREG(mode)):
            return False
        if stat.S_ISREG(mode):
            files += 1
            size += entry.lstat().st_size
    return files <= MOST_FILES_PER_TASK and size <= MOST_BYTES_PER_TASK


def stage(worktree: Path, staging: Path) -> int:
    """Copy each task directory the session left into ``staging``; how many were refused.

    Only top-level directories are looked at, ``.git`` aside; one that holds a link, a
    special file or more than a task's worth is refused and not copied.
    """
    staging.mkdir(mode=0o700)
    refused = 0
    for entry in sorted(worktree.iterdir()):
        if entry.name == ".git" or entry.is_symlink() or not entry.is_dir():
            continue
        if not _plain_tree(entry):
            refused += 1
            continue
        shutil.copytree(entry, staging / entry.name, symlinks=True)
    return refused


def _keep_evidence(work: Path, record: dict[str, Any], into: Path) -> None:
    """Move the session's stream and record inside the protected root, then drop ``work``."""
    into.mkdir(mode=0o700, parents=True, exist_ok=True)
    target = into / str(record["session_id"])
    shutil.move(str(work / "session"), str(target))
    (target / "record.json").write_text(json.dumps(record, sort_keys=True, indent=1))
    shutil.rmtree(work)


def _spent(record: dict[str, Any]) -> dict[str, Any]:
    return {key: record.get(key) for key in ("end", "tokens", "cap", "wall_clock_s")}


def author(plan: AuthoringPlan, setup: RawSetup) -> dict[str, Any]:
    """Run one authoring session and, if enough of its tasks hold, split them into tiers.

    Returns what may be shown: counts, the visible tier's ids, the held-out tier's digest,
    and what the session spent.

    Raises:
        AuthoringError: the author's model is the implementers', a place is inside a held-out
            root or already exists, or the session does not withhold the protected root.
    """
    require_author_model(setup.model, plan.implementer_model)
    _require_apart(plan, setup)
    record = run_session(author_brief(plan.role, count=plan.count), setup, plan.work, cap=plan.cap)
    staging = plan.work / "staging"
    refused = stage(plan.work / "worktree", staging)
    staged = sum(1 for p in staging.iterdir() if p.is_dir())
    held = sound(staging)
    summary: dict[str, Any] = {
        "asked": plan.count,
        "written": staged + refused,
        "refused_as_files": refused,
        "held": len(held),
        "session": _spent(record),
    }
    evidence = plan.held_out_root / f"{plan.role}.author"
    if len(held) < 2 * PER_TIER:
        _keep_evidence(plan.work, record, evidence)
        return {**summary, "status": "too_few_held"}
    chosen = sorted(held)
    random.Random(plan.seed).shuffle(chosen)
    for entry in staging.iterdir():
        if entry.name not in chosen[: 2 * PER_TIER]:
            shutil.rmtree(entry)
    tier = held_out_tier(plan.held_out_root, plan.role)
    placed = split(staging, plan.visible, tier, seed=plan.seed)
    _keep_evidence(plan.work, record, evidence)
    return {
        **summary,
        "status": "split",
        "visible": placed["visible"],
        "held_out_count": placed["held_out_count"],
        "held_out_sha256": placed["held_out_sha256"],
        "visible_check": validate(plan.visible, show_ids=True),
        "held_out_check": validate(tier),
    }


# ----------------------------------------------------------------------- the blind check

QUESTIONS = ("states_every_requirement", "unambiguous", "answerable_as_asked")

CHECK_BRIEF = """\
You are checking engineering design tasks before they are used. The file tasks.json in
the directory you work in holds them, each under a key. For each task read its brief, its
inputs, its answer contract and its specifications, and answer three questions:
  - states_every_requirement: does the brief state every specification, with its bound
    and unit, so that a designer reading only the brief knows what is asked?
  - unambiguous: can the brief be read in only one way where it matters for the answer?
  - answerable_as_asked: could a competent designer meet every specification with an
    answer of the stated form?

Write the file answers.json in the directory you work in, and nothing else:
  {{"<key>": {{"states_every_requirement": true or false, "unambiguous": true or false,
             "answerable_as_asked": true or false}}, ...}}
with every key of tasks.json once. Write no explanation in it or anywhere else. There are
{count} tasks.
"""


class _Answer(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid", strict=True)

    states_every_requirement: bool
    unambiguous: bool
    answerable_as_asked: bool


class _Answers(RootModel[dict[str, _Answer]]):
    model_config = ConfigDict(strict=True)


#: The largest answer file read: three booleans for each of a few dozen tasks.
MAX_ANSWERS_BYTES = 64 * 1024


def bundle(tier: Path) -> dict[str, dict[str, Any]]:
    """The tier's tasks as the check reads them: by id digest, without references or canary.

    Raises:
        PerRoleError: a task in the tier does not load.
    """
    found: dict[str, dict[str, Any]] = {}
    for entry in sorted(p for p in tier.iterdir() if p.is_dir()):
        task = load_task(entry).task
        found[id_digest(task.id)] = {
            "brief": task.brief,
            "inputs": [m.model_dump(mode="json") for m in task.inputs],
            "answer": task.answer.model_dump(mode="json"),
            "specs": [s.model_dump(mode="json") for s in task.specs],
        }
    return found


def read_answers(path: Path, keys: Sequence[str]) -> dict[str, _Answer] | None:
    """The check's answers, or ``None`` unless they are booleans for exactly ``keys``."""
    if path.is_symlink() or not path.is_file() or path.stat().st_size > MAX_ANSWERS_BYTES:
        return None
    try:
        answers = _Answers.model_validate_json(path.read_bytes()).root
    except ValidationError:
        return None
    return answers if sorted(answers) == sorted(keys) else None


def blind_check(
    tier: Path, setup: RawSetup, work: Path, *, implementer_model: str, cap: int, evidence: Path
) -> dict[str, Any]:
    """Run the blind check on ``tier``; counts and the digests of tasks with a ``false``.

    Raises:
        AuthoringError: the checking model is the implementers', ``work`` is inside a
            held-out root, or the session does not withhold the tier.
        PerRoleError: a task in the tier does not load.
    """
    require_author_model(setup.model, implementer_model)
    roots = [Path(r) for r in setup.held_out]
    if not _withheld(tier, roots) or any(_inside(work, r) for r in roots):
        msg = "the check withholds the tier and works outside every held-out root"
        raise AuthoringError(msg, tier=str(tier), work=str(work))
    tasks = bundle(tier)
    files = {"tasks.json": json.dumps(tasks, sort_keys=True, indent=1).encode()}
    record = run_session(CHECK_BRIEF.format(count=len(tasks)), setup, work, cap=cap, files=files)
    answers = read_answers(work / "worktree" / "answers.json", list(tasks))
    _keep_evidence(work, record, evidence)
    if answers is None:
        return {"tasks": len(tasks), "answered": False, "session": _spent(record)}
    flagged = sorted(key for key, a in answers.items() if not all(getattr(a, q) for q in QUESTIONS))
    return {
        "tasks": len(tasks),
        "answered": True,
        "all_yes": len(tasks) - len(flagged),
        "flagged": flagged,
        "session": _spent(record),
    }


__all__ = [
    "AuthoringPlan",
    "author",
    "blind_check",
    "bundle",
    "held_out_tier",
    "read_answers",
    "stage",
]
