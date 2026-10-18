"""Every ``ps`` call has a time limit, and a call that fails is never read as "nothing runs".

A hung ``ps`` would hang the orchestrator's stop or its resume; a ``ps`` that failed and
printed nothing would read as an empty table, and a session still running would be taken
for gone. So each call is bounded, and one that times out, cannot start or fails raises.
"""

from __future__ import annotations

import subprocess
from typing import Any

import pytest

from physgate.orchestrator import processes
from physgate.reviewers import ending


class Ps:
    """``subprocess`` for one module: ``ps`` hangs past its limit, fails, or cannot start."""

    SubprocessError = subprocess.SubprocessError
    TimeoutExpired = subprocess.TimeoutExpired
    CompletedProcess = subprocess.CompletedProcess

    def __init__(self, how: str) -> None:
        self.how = how
        self.limits: list[object] = []

    def run(self, argv: list[str], **kwargs: Any) -> subprocess.CompletedProcess[str]:  # noqa: ANN401
        if argv[0] != "ps":
            return subprocess.run(argv, **kwargs)  # noqa: S603, PLW1510
        self.limits.append(kwargs.get("timeout"))
        if self.how == "hangs":
            if kwargs.get("timeout") is None:
                pytest.fail(f"ps was called with no time limit: {argv}")
            raise subprocess.TimeoutExpired(argv, kwargs["timeout"])
        if self.how == "raises":
            raise OSError(1, "ps could not be started")
        return subprocess.CompletedProcess(argv, 1, stdout="", stderr="")


@pytest.mark.parametrize("how", ["hangs", "raises"])
def test_a_command_line_that_cannot_be_read_raises_and_is_never_taken_for_no_session(
    monkeypatch: pytest.MonkeyPatch, how: str
) -> None:
    ps = Ps(how)
    monkeypatch.setattr(processes, "subprocess", ps)
    with pytest.raises(processes.ProcessTableError):
        processes.command_of(1)
    assert all(limit is not None for limit in ps.limits)


def test_a_pid_that_is_not_running_has_no_command_line() -> None:
    # ``ps -p`` of a pid nobody holds exits 1 and prints nothing: that one is an answer.
    assert processes.command_of(2**22 + 12345) is None


@pytest.mark.parametrize("how", ["hangs", "raises", "fails"])
def test_a_group_that_cannot_be_listed_raises_and_is_never_read_as_empty(
    monkeypatch: pytest.MonkeyPatch, how: str
) -> None:
    ps = Ps(how)
    monkeypatch.setattr(ending, "subprocess", ps)
    with pytest.raises(processes.ProcessTableError):
        ending.group(1)
    assert all(limit is not None for limit in ps.limits)
