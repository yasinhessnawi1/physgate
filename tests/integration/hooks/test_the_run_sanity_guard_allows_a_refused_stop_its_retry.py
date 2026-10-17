"""The run-sanity guard counts a Stop the runtime retried after a refusal as ours.

When the sentinel halts on a protected write it refuses every Stop, and the runtime
starts Stop again after each refusal. The guard raises when more hook commands start
than the generated settings account for, so a run under foreign hooks cannot pass as a
measurement; it allows a session's Stop to start at most once plus once per Stop
refusal the session's own hook log records. Every other count is unchanged.

The synthetic runs pin the arithmetic; the real one shows the retry happens and is
allowed, and says when it did not happen at all.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest
import test_the_bypass_suite as bp
from fake_messages_api import FakeMessagesApi, Recorded, Script, text
from hook_session import (
    HarnessError,
    SessionRun,
    check_the_run_means_something,
    run_session,
    stop_refusals,
)

from physgate.hooks.registry import REGISTRY

SESSION = "11111111-2222-3333-4444-555555555555"


def _started(name: str) -> dict[str, Any]:
    return {"type": "system", "subtype": "hook_started", "hook_name": name}


def _refusal(event: str, session: str = SESSION) -> dict[str, Any]:
    return {"session": session, "event": event, "hook": "sentinel", "decision": "refuse"}


def _run(
    tmp_path: Path, *, stops: int, log: list[dict[str, Any]], bash_starts: int = 1
) -> SessionRun:
    api = FakeMessagesApi(Script(main=[]))
    api.requests.append(
        Recorded(
            path="/v1/messages",
            carried_dummy_key=True,
            carried_other_credential=False,
            thread="main",
            tool_results=0,
            offered_tools=("Bash",),
            last_user="go",
            served={"tool": "Bash", "input": {}},
        )
    )
    stream = [{"type": "system", "subtype": "init", "session_id": SESSION}]
    stream += [_started("PreToolUse:Bash")] * bash_starts
    stream += [_started("Stop")] * stops
    return SessionRun(0, api, stream, log, None, tmp_path, "")  # type: ignore[arg-type]


def test_a_stop_started_once_per_recorded_refusal_and_once_more_is_allowed(
    tmp_path: Path,
) -> None:
    check_the_run_means_something(_run(tmp_path, stops=3, log=[_refusal("Stop")] * 2))


def test_one_stop_more_than_the_refusals_allow_still_raises(tmp_path: Path) -> None:
    with pytest.raises(HarnessError, match="'Stop': 4"):
        check_the_run_means_something(_run(tmp_path, stops=4, log=[_refusal("Stop")] * 2))


def test_with_no_refusal_on_record_a_second_stop_raises_as_before(tmp_path: Path) -> None:
    check_the_run_means_something(_run(tmp_path, stops=1, log=[]))
    with pytest.raises(HarnessError, match="'Stop': 2"):
        check_the_run_means_something(_run(tmp_path, stops=2, log=[]))


def test_a_refusal_of_another_session_or_another_event_buys_no_stop(tmp_path: Path) -> None:
    log = [_refusal("Stop", session="another"), _refusal("PreToolUse"), _refusal("PostToolUse")]
    run = _run(tmp_path, stops=2, log=log)
    assert stop_refusals(run) == 0
    with pytest.raises(HarnessError, match="'Stop': 2"):
        check_the_run_means_something(run)


def test_a_foreign_tool_hook_still_raises_while_the_stops_are_within_allowance(
    tmp_path: Path,
) -> None:
    # Two faults crossed: the Stop count is within its allowance, the Bash count is not.
    run = _run(tmp_path, stops=3, log=[_refusal("Stop")] * 2, bash_starts=2)
    with pytest.raises(HarnessError, match=r"PreToolUse:Bash': 2") as raised:
        check_the_run_means_something(run)
    assert "Stop" not in str(raised.value)


@pytest.mark.integration
def test_a_sentinel_halt_retries_stop_and_the_run_still_counts(tmp_path: Path) -> None:
    # The bypass suite's own node edit, with the shell parser off: the edit lands, the
    # sentinel halts on the node it no longer recognises and refuses every Stop.
    attempt = bp._attempt("node-edit")
    run = run_session(
        tmp_path,
        Script(main=[*bp._place(attempt.steps, tmp_path), text("end")]),
        files=bp.FILES,
        prepare=bp._prepare,
        store_root=str(tmp_path / "outside" / "store"),
        held_out=(str(tmp_path / "outside" / "heldout"),),
        registry={k: v for k, v in REGISTRY.items() if k != "shell_paths"},
    )
    starts = run.hook_commands_started()["Stop"]
    refused = stop_refusals(run)
    assert starts > 1, f"vacuous: Stop started {starts} time(s), so no retry was exercised"
    assert refused >= starts - 1
