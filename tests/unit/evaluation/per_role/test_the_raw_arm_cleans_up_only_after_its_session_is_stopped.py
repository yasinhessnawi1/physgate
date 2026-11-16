"""The raw arm removes a session's credential and records only once the session has stopped.

The cleanup (the credential, the sentinel's record of the protected paths) runs on every way out
of the session. A way out that raises while the session still runs, a watch that cannot start or
a wait that fails, would otherwise clean up beside a living session: its next hook would find no
record and take a new one, naming the protected paths again, after the cleanup. So the session
is killed and reaped first, and only then is anything removed; what was raised is raised still.

The stand-in session sleeps: it is alive for as long as the row does not stop it.
"""

from __future__ import annotations

import contextlib
import json
import os
import signal
import subprocess
from pathlib import Path
from typing import Any

import pytest
from task_fixtures import own_task
from test_the_raw_arm_s_credential_is_handled_as_a_role_session_s import _script, _setup

from physgate.evaluation.per_role.arms import raw
from physgate.evaluation.tiers.task import parse_task

TASK = parse_task(json.dumps(own_task()).encode())
SLEEPS = "sleep 60\n"


class _FailedError(RuntimeError):
    """A way out of the session that raises while it runs."""


def _fails_in(step: str, monkeypatch: pytest.MonkeyPatch) -> None:
    def failing(*_a: Any, **_k: Any) -> Any:  # noqa: ANN401
        raise _FailedError(step)

    if step == "watch.start":
        monkeypatch.setattr(raw.BudgetWatch, "start", failing)
    else:
        monkeypatch.setattr(raw, step, failing)


@pytest.mark.parametrize("step", ["watch.start", "await_session"])
def test_nothing_is_cleaned_up_until_the_session_is_stopped_and_reaped(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, step: str
) -> None:
    spawned: list[subprocess.Popen[bytes]] = []
    at_cleanup: list[int | None] = []
    real_spawn, real_clean = raw.spawn_held, raw._clean

    def spawn(*a: Any, **k: Any) -> Any:  # noqa: ANN401
        process, started = real_spawn(*a, **k)
        spawned.append(process)
        return process, started

    def clean(*a: Any, **k: Any) -> None:  # noqa: ANN401
        # What the session is when the cleanup begins: reaped (its exit status), or running.
        at_cleanup.append(spawned[0].poll() if spawned else -999)
        real_clean(*a, **k)

    monkeypatch.setattr(raw, "spawn_held", spawn)
    monkeypatch.setattr(raw, "_clean", clean)
    _fails_in(step, monkeypatch)
    try:
        with pytest.raises(_FailedError):
            binary = _script(tmp_path / "claude", SLEEPS)
            raw.run_raw(TASK, _setup(tmp_path, binary), tmp_path / "w", cap=10**9)
        assert spawned, "no session was spawned: the row shows nothing"
        assert at_cleanup == [spawned[0].returncode], at_cleanup
        assert at_cleanup[0] is not None, "the cleanup ran while the session still ran"
    finally:
        for process in spawned:
            if process.poll() is None:  # unreaped: its group id is still its own
                with contextlib.suppress(OSError):
                    os.killpg(process.pid, signal.SIGKILL)
                process.kill()
                process.wait()
