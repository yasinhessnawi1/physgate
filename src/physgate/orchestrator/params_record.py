"""The parameters file a run was started with, recorded in its run directory.

The parameters name the held-out tier's canaries, and the file lies wherever the operator put it,
often beside the run directory and so within reach of a role session's shell. So ``decompose``
records the file's resolved path, synced, in the fresh run directory before anything runs, and
every role session is installed with that file withheld from all its reads. The record is one of
the run's records a session may not write: it is put back if it changes.

A run directory written before the record existed holds none, and its sessions withhold no
parameters file, as they never did. A record that cannot be read installs no session: which file
to withhold is then unknown.
"""

from __future__ import annotations

import json
import os
from pathlib import Path

from physgate.orchestrator.exceptions import RunStateError

#: Where the run's parameters file is recorded, in its run directory.
RECORD_NAME = "params_source.json"


def recorded_params(run_dir: Path) -> Path | None:
    """The parameters file the run recorded, or ``None`` if it holds no record.

    Raises:
        RunStateError: the record is there and cannot be read, or names no absolute path.
    """
    path = Path(run_dir) / RECORD_NAME
    if not path.exists():
        return None
    try:
        named = json.loads(path.read_text())["params"]
        if not isinstance(named, str) or not Path(named).is_absolute():
            raise TypeError(type(named).__name__)
    except (OSError, ValueError, KeyError, TypeError) as exc:
        msg = (
            "the run's record of its parameters file cannot be read, so which file to withhold "
            "from its sessions is unknown; no session is installed until it is restored"
        )
        raise RunStateError(msg, run_dir=str(run_dir), record=str(path), why=repr(exc)) from exc
    return Path(named)


def record_params(run_dir: Path, params: Path) -> None:
    """Record ``params``, resolved, as the run's parameters file, synced.

    Raises:
        RunStateError: the record could not be written.
    """
    path = Path(run_dir) / RECORD_NAME
    written = path.with_name(f".{path.name}.part")
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        with written.open("wb") as handle:
            handle.write(json.dumps({"params": str(Path(params).resolve())}).encode())
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(written, path)
    except OSError as exc:
        msg = "the run's parameters file could not be recorded; nothing runs with it unrecorded"
        raise RunStateError(msg, run_dir=str(run_dir), why=repr(exc)) from exc
