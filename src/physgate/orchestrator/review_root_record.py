"""The review root a run's reviews run under, recorded in its run directory.

A review's session directory lives beneath the review root, outside the run directory, and a
later command finds it only beneath the root it is given. A ``run`` or ``resume`` that named
another root would find none of the run's reviews: a review killed after its end record would
never be scanned, and one left running in its repair would never be stopped. So the root is
recorded, resolved and absolute, by the first command that names one for the run directory,
before anything runs under it: ``decompose`` when it reviews the plan, else the first ``run`` or
``resume``. Every later ``run`` or ``resume`` that names another root is refused, before it stops
or spawns anything, and the refusal names both. ``decompose`` writes it, over any earlier one, only into
a directory it has found fresh, once a review a killed decomposition left there has been stopped
and scanned through that review's own record, which names its directory in full.

A run directory written before the record existed holds none, and nothing tells it apart from a
run whose first ``run`` is still to come. Its next ``run`` or ``resume`` goes on as it always did,
under the root it names, and records that root: every command after it is held to it.

A record that cannot be read refuses every command that names a root: which root the reviews ran
under is then unknown. The file is the orchestrator's, synced when written, so a kill or a machine
going down after a review's spawn keeps it with the review's own files.
"""

from __future__ import annotations

import json
import os
from pathlib import Path

from physgate.orchestrator.exceptions import RunStateError
from physgate.reviewers.places import review_root_path

#: Where the run's review root is recorded, in its run directory.
RECORD_NAME = "review_root.json"


def recorded_review_root(run_dir: Path) -> Path | None:
    """The review root the run directory recorded, or ``None`` if it holds no record.

    Raises:
        RunStateError: the record is there and cannot be read, or names no absolute path.
    """
    path = Path(run_dir) / RECORD_NAME
    if not path.exists():
        return None
    try:
        root = json.loads(path.read_text())["review_root"]
        if not isinstance(root, str) or not Path(root).is_absolute():
            raise TypeError(type(root).__name__)
    except (OSError, ValueError, KeyError, TypeError) as exc:
        msg = (
            "the run's record of its review root cannot be read, so where its reviews ran is "
            "unknown; nothing runs until it is restored"
        )
        raise RunStateError(msg, run_dir=str(run_dir), record=str(path), why=repr(exc)) from exc
    return Path(root)


def require_recorded_review_root(run_dir: Path, named: Path) -> Path:
    """Return ``named`` as every reader takes it, if it is the root the run recorded, or none is.

    Raises:
        RunStateError: the run recorded another review root, or its record cannot be read.
    """
    root = review_root_path(named)
    recorded = recorded_review_root(run_dir)
    if recorded is not None and recorded != root:
        msg = (
            f"this run's reviews run under the review root {recorded}, which it recorded; this "
            f"command names {root}, beneath which none of its reviews would be found"
        )
        raise RunStateError(msg, run_dir=str(run_dir), recorded=str(recorded), named=str(root))
    return root


def record_review_root(run_dir: Path, root: Path) -> None:
    """Record ``root``, resolved, as the run's review root, synced, unless it is recorded already.

    Raises:
        RunStateError: the record could not be written.
    """
    resolved = review_root_path(root)
    path = Path(run_dir) / RECORD_NAME
    written = path.with_name(f".{path.name}.part")
    try:
        if path.exists() and recorded_review_root(run_dir) == resolved:
            return
        path.parent.mkdir(parents=True, exist_ok=True)
        with written.open("wb") as handle:
            handle.write(json.dumps({"review_root": str(resolved)}).encode())
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(written, path)
    except OSError as exc:
        msg = "the run's review root could not be recorded; nothing runs under it unrecorded"
        raise RunStateError(msg, run_dir=str(run_dir), why=repr(exc)) from exc
