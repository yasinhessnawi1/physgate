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
import os
import random
import shutil
import stat
import uuid
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
from physgate.evaluation.per_role.firmware.sandbox import open_directory
from physgate.evaluation.per_role.task import Role, load_task
from physgate.evaluation.per_role.validate import id_digest, sound, validate

_READ = os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK
_NEW = os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW

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
    for name, path in (
        ("work", plan.work),
        ("visible tier", plan.visible),
        ("protected root", plan.held_out_root),
    ):
        if path.resolve() != path.absolute():
            msg = f"the {name} is reached through a link; give its resolved path"
            raise AuthoringError(msg, path=str(path))
    tier = held_out_tier(plan.held_out_root, plan.role)
    if plan.work.exists() or plan.visible.exists() or tier.exists():
        msg = "the work directory and both tiers are made new for each session"
        raise AuthoringError(msg, work=str(plan.work), visible=str(plan.visible))
    if plan.count < 2 * PER_TIER:
        msg = f"a session is asked for at least {2 * PER_TIER} tasks"
        raise AuthoringError(msg, count=str(plan.count))


class _NotPlainError(Exception):
    """A staged task holds something that is not a plain directory or a singly named file."""


def _classify(name: str, dir_fd: int) -> os.stat_result:
    """What ``name`` is, under ``dir_fd``, without following it: the listing's view only.

    Only the type decides how the entry is opened; whatever it is opened as is checked
    again on the descriptor, since the entry can be replaced between here and the open.
    """
    return os.stat(name, dir_fd=dir_fd, follow_symlinks=False)


def _new_file(name: str, dir_fd: int) -> int:
    """A file made new as ``name`` under ``dir_fd``: never one already there, never a link."""
    return os.open(name, _NEW, 0o600, dir_fd=dir_fd)


def _copy_into(source_fd: int, target_fd: int, budget: list[int]) -> None:
    """Copy the directory ``source_fd`` into the empty directory ``target_fd``, by content.

    ``budget`` is the files and bytes the task may still hold.

    Raises:
        _NotPlainError: an entry is a link of either kind, a special file, or past the budget.
    """
    for name in sorted(os.listdir(source_fd)):
        kind = _classify(name, source_fd).st_mode
        if stat.S_ISDIR(kind):
            try:
                child = open_directory(name, source_fd)
            except OSError as exc:
                raise _NotPlainError(name) from exc
            try:
                os.mkdir(name, 0o700, dir_fd=target_fd)
                made = open_directory(name, target_fd)
                try:
                    _copy_into(child, made, budget)
                finally:
                    os.close(made)
            finally:
                os.close(child)
            continue
        if not stat.S_ISREG(kind):
            raise _NotPlainError(name)
        try:
            fd = os.open(name, _READ, dir_fd=source_fd)
        except OSError as exc:  # replaced by a link or a FIFO since it was listed
            raise _NotPlainError(name) from exc
        try:
            info = os.fstat(fd)
            if not stat.S_ISREG(info.st_mode) or info.st_nlink != 1:
                raise _NotPlainError(name)
            budget[0] -= 1
            budget[1] -= info.st_size
            if budget[0] < 0 or budget[1] < 0:
                raise _NotPlainError(name)
            with os.fdopen(os.dup(fd), "rb") as handle:
                data = handle.read(MOST_BYTES_PER_TASK + 1)
        finally:
            os.close(fd)
        try:
            out = _new_file(name, target_fd)
        except OSError as exc:  # something stands where the copy goes
            raise _NotPlainError(name) from exc
        try:
            os.write(out, data)
        finally:
            os.close(out)


def stage(worktree: Path, staging: Path) -> int:
    """Copy each task directory the session left into ``staging``; how many were refused.

    Everything is reached through descriptors, never by a path checked and then opened:
    the worktree and each directory in it are opened without following a link and checked
    on the descriptor (:func:`.firmware.sandbox.open_directory`); each file is opened the
    same way and checked on its descriptor to be a regular file with one name; each copy
    is a file made new under the staging directory's descriptor. Only top-level
    directories are looked at, those whose names begin with a dot aside. A task holding a
    symbolic or a hard link, a special file or more than a task's worth is refused, and
    what was copied of it removed.

    Raises:
        OSError: the staging directory cannot be made new (something stands there).
    """
    staging.mkdir(mode=0o700)
    target = open_directory(str(staging))
    source = open_directory(str(worktree))
    refused = 0
    try:
        for name in sorted(os.listdir(source)):
            if name.startswith(".") or not stat.S_ISDIR(_classify(name, source).st_mode):
                continue
            try:
                task = open_directory(name, source)
            except OSError:
                refused += 1
                continue
            try:
                os.mkdir(name, 0o700, dir_fd=target)
                made = open_directory(name, target)
                try:
                    _copy_into(task, made, [MOST_FILES_PER_TASK, MOST_BYTES_PER_TASK])
                except _NotPlainError:
                    refused += 1
                    shutil.rmtree(name, dir_fd=target)
                finally:
                    os.close(made)
            finally:
                os.close(task)
    finally:
        os.close(source)
        os.close(target)
    return refused


def _remove(path: Path) -> str | None:
    """Remove ``path`` if it is there; the reason if it could not be, never silently."""
    if not path.exists() and not path.is_symlink():
        return None
    try:
        shutil.rmtree(path)
    except OSError as exc:
        return f"{path}: {exc}"
    return None if not path.exists() else f"{path}: still there"


def _keep_evidence(work: Path, record: dict[str, Any] | None, into: Path) -> list[str | None]:
    """Move the session's stream and record inside the protected root, then drop ``work``.

    Run however the session or what follows it ended: what the session wrote holds tasks
    that may become held-out ones, so it never stays outside the protected root. A session
    that left no record is kept under a name of its own. Every step is tried; what could
    not be done is returned, for the caller to refuse on.
    """
    problems: list[str | None] = []
    name = str(record["session_id"]) if record else f"unrecorded-{uuid.uuid4().hex[:12]}"
    target = into / name
    try:
        into.mkdir(mode=0o700, parents=True, exist_ok=True)
        if (work / "session").is_dir():
            shutil.move(str(work / "session"), str(target))
        else:
            target.mkdir(mode=0o700)
        (target / "record.json").write_text(json.dumps(record or {}, sort_keys=True, indent=1))
    except OSError as exc:
        problems.append(f"the session's stream into {target}: {exc}")
    problems.append(_remove(work))
    return problems


def _closed(problems: Sequence[str | None]) -> None:
    """Refuse, loudly, if anything that could hold a task was left where it could be read.

    Raises:
        AuthoringError: a removal failed: say where, and report no result.
    """
    left = [p for p in problems if p is not None]
    if left:
        msg = (
            "what the session wrote could not be removed, so a held-out task may be readable "
            "outside the protected root; remove these by hand before anything else runs: "
            + "; ".join(left)
        )
        raise AuthoringError(msg, left=" | ".join(left))


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
    evidence = plan.held_out_root / f"{plan.role}.author"
    tier = held_out_tier(plan.held_out_root, plan.role)
    record: dict[str, Any] | None = None
    split_started = False
    try:
        record = run_session(
            author_brief(plan.role, count=plan.count), setup, plan.work, cap=plan.cap
        )
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
        if len(held) < 2 * PER_TIER:
            return {**summary, "status": "too_few_held"}
        chosen = sorted(held)
        random.Random(plan.seed).shuffle(chosen)
        for entry in staging.iterdir():
            if entry.name not in chosen[: 2 * PER_TIER]:
                shutil.rmtree(entry)
        split_started = True
        placed = split(staging, plan.visible, tier, seed=plan.seed)
        split_started = False
    finally:
        problems: list[str | None] = []
        if split_started:
            # Neither tier existed before this call; half a split is no tier at all.
            problems = [_remove(plan.visible), _remove(tier)]
        _closed([*problems, *_keep_evidence(plan.work, record, evidence)])
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
    record: dict[str, Any] | None = None
    try:
        record = run_session(
            CHECK_BRIEF.format(count=len(tasks)), setup, work, cap=cap, files=files
        )
        answers = read_answers(work / "worktree" / "answers.json", list(tasks))
    finally:
        # The work holds the held-out tasks it was given: it never stays outside the root.
        _closed(_keep_evidence(work, record, evidence))
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
