"""A module review's try that a halt ended is priced at its role's reviewer, in a log of any age.

The logs are written by hand, with made-up ids and numbers, in the shape a real reviewed run's log
holds: the decomposition's spend, two subtasks of two roles whose reviewers are pinned to different
models, and per subtask the role session (spawned, its tokens, its end) and then the review. The
first subtask's first review try ended the run for a while: its tokens, and then, written at once
with them, the halt (the usage limit, a refused credential, an OS layer that would not start, the
machine's retries spent after a retried try) or held-out material's incident and halt. A run
recorded before every such try had its own line leaves nothing else of it; the resume's review then
passes. In the oldest form a review's spawn is not on the log at all.

The cost reader takes such a try as that review by the shared end rule: priced at the reviewer of
the role whose review stage it was taken at, under that subtask, every message once. Tokens alone,
with no halt after them (a process killed between them), are still no review the reader prices.
"""

from __future__ import annotations

import json
from decimal import Decimal
from typing import Any

import pytest
from orch_helpers import make_config
from pydantic import TypeAdapter

from physgate.evaluation.observe.cost import CostLine, load_price_sheet, price_events
from physgate.evaluation.observe.exceptions import ManifestError
from physgate.orchestrator.accounting import TokenAccount
from physgate.orchestrator.events import Event
from physgate.orchestrator.run_config import ModelStrings
from physgate.orchestrator.session_ends import halted_with, open_sessions

EVENT: TypeAdapter[Event] = TypeAdapter(Event)
DATE = "2026-10-16"
MANIFEST = "e" * 64
CONTROL, FIRMWARE = "control-a1b2c3", "firmware-d4e5f6"
#: The control review's try the halt ended, its retried try before a ladder's end, and the rest.
HALTED, RETRIED = "4d4d4d4d-5555-4555-8555-00000000000d", "4c4c4c4c-5555-4555-8555-00000000000c"
PASSED, OTHER = "5e5e5e5e-5555-4555-8555-00000000000e", "6f6f6f6f-5555-4555-8555-00000000000f"
MODELS = ModelStrings(
    decomposition="claude-sonnet-5",
    roles={"control": "claude-sonnet-5", "firmware": "claude-opus-5-5"},
    reviewers={"control": "claude-opus-5-5", "firmware": "claude-sonnet-5"},
)


def _usage(base: int) -> dict[str, int]:
    return {
        "input_tokens": 3 + base,
        "output_tokens": 20 + base,
        "cache_read_input_tokens": 100 + base,
        "cache_creation_input_tokens": 10,
    }


class _Log:
    """A run's log written line by line, each line's envelope filled in."""

    def __init__(self) -> None:
        self.lines: list[dict[str, Any]] = []

    def add(self, kind: str, **fields: Any) -> None:  # noqa: ANN401
        n = len(self.lines)
        envelope = {"seq": n, "ts": f"2026-01-01T00:{n // 60:02d}:{n % 60:02d}.000000Z"}
        self.lines.append(
            {**envelope, "run_id": "run-1", "gate_mode": "on", "kind": kind, **fields}
        )

    def tokens(self, attribution: str, base: int) -> None:
        self.add(
            "tokens_used",
            attribution=attribution,
            message_id=f"msg_{len(self.lines):04d}",
            usage=_usage(base),
        )

    def stages(self, subtask: str, attempt: int, *stages: str) -> None:
        for stage in stages:
            self.add("stage_entered", stage=stage, subtask_id=subtask, attempt=attempt)

    def spawn(self, session_id: str, *, recorded: bool = True) -> None:
        if recorded:
            self.add("session_spawned", session_id=session_id, pid=40001, started="Thu Jan  1")

    def role_session(self, subtask: str, session_id: str, base: int) -> None:
        self.stages(subtask, 1, "resolve", "spawn")
        self.spawn(session_id)
        self.tokens(f"session:{session_id}", base)
        self.add(
            "session_ended",
            session_id=session_id,
            outcome="completed",
            cause=None,
            attempt_commit="1" * 40,
            trajectory=f"sessions/{session_id}/stdout.jsonl",
            worktree=f"worktrees/{subtask}",
            reading_verified=True,
            subtask_id=subtask,
            attempt=1,
        )
        self.stages(subtask, 1, "verify_reading", "implement", "gate", "review")

    def review_ran(self, subtask: str, session_id: str, model: str) -> None:
        result = {
            "verdict": "pass",
            "finding": "sound",
            "reviewer_model": model,
            "session_id": session_id,
            "usage": [],
        }
        self.add("review_ran", result=result, subtask_id=subtask, attempt=1)

    def events(self) -> list[Event]:
        return [EVENT.validate_json(json.dumps(line)) for line in self.lines]


def _priced(events: list[Event]) -> CostLine:
    """The run's cost line; a refusal fails the row on an assertion that names it."""
    try:
        return price_events(make_config(models=MODELS), MANIFEST, events, load_price_sheet(DATE))
    except ManifestError as exc:
        pytest.fail(f"the run is not priced: {exc}")


def _halt(log: _Log, how: str) -> None:
    """The halt, or the incident and halt, written at once with the halted try's tokens."""
    where = f"subtask {CONTROL} attempt 1"
    if how == "usage_limit":
        log.add(
            "halted",
            reason="usage_limit",
            detail=f"{where}: review session {HALTED} ended on the account's usage limit",
            usage_limit={"resets": "later"},
        )
    elif how == "held_out_read":
        log.add("halted", reason="incident", detail=f"held_out_read in {CONTROL}")
    else:
        log.add("halted", reason=how, detail=f"{where}: review session {HALTED} ended; resume")


def _a_run_recorded_before(how: str, *, spawns: bool = True) -> _Log:
    """The log a run recorded before every halting try had its own line, ``how`` its halt."""
    log = _Log()
    log.tokens("decomposition:0d0d0d0d-1111-4111-8111-000000000001", 40)
    for subtask, role in ((CONTROL, "control"), (FIRMWARE, "firmware")):
        log.add(
            "subtask_planned",
            subtask_id=subtask,
            spec_path=f"specs/{subtask}.md",
            assigned_role=role,
            module_dir=f"modules/{subtask}",
        )
    log.role_session(CONTROL, "1a1a1a1a-3333-4333-8333-00000000000a", 21)
    if how == "infrastructure_exhausted":
        # The ladder's earlier try ended on a line of its own (retried); the last on the halt.
        log.spawn(RETRIED, recorded=spawns)
        log.tokens(f"reviewer:{RETRIED}", 51)
        log.add(
            "review_unavailable",
            subtask_id=CONTROL,
            attempt=1,
            cause="infrastructure",
            detail="the review's session ended with api_error",
            retry=True,
            session_id=RETRIED,
            reviewer_model="claude-opus-5-5",
        )
    if how == "held_out_read":
        log.add("incident", subtask_id=CONTROL, cause="held_out_read", detail="in a review")
    log.spawn(HALTED, recorded=spawns)
    log.tokens(f"reviewer:{HALTED}", 61)
    log.tokens(f"reviewer:{HALTED}", 62)
    _halt(log, how)
    if how == "held_out_read":
        return log  # the run is stopped for good: no resume
    log.add("resumed", subtask_id=CONTROL, attempt=1, point="verify_reading")
    log.stages(CONTROL, 1, "verify_reading", "implement", "gate", "review")
    log.spawn(PASSED, recorded=spawns)
    log.tokens(f"reviewer:{PASSED}", 71)
    log.review_ran(CONTROL, PASSED, "claude-opus-5-5")
    log.role_session(FIRMWARE, "2b2b2b2b-3333-4333-8333-00000000000b", 31)
    log.spawn(OTHER, recorded=spawns)
    log.tokens(f"reviewer:{OTHER}", 81)
    log.review_ran(FIRMWARE, OTHER, "claude-sonnet-5")
    return log


HOWS = [
    "usage_limit",
    "credential_refused",
    "os_layer_unavailable",
    "infrastructure_exhausted",
    "held_out_read",
]


@pytest.mark.parametrize("spawns", [True, False], ids=["spawns recorded", "no spawn recorded"])
@pytest.mark.parametrize("how", HOWS)
def test_a_halted_try_is_priced_at_its_role_s_reviewer_under_its_subtask(
    how: str, spawns: bool
) -> None:
    events = _a_run_recorded_before(how, spawns=spawns).events()
    assert halted_with(HALTED, events) is not None
    assert open_sessions(events) == ()
    line = _priced(events)
    account = TokenAccount.from_events(events)
    by_model = {row.model: row.tokens.total() for row in line.rows}
    assert sum(by_model.values()) == account.total().total(), "every message once"
    halted = account.by_attribution()[f"reviewer:{HALTED}"].total()
    control_reviews = halted + sum(
        account.by_attribution()[f"reviewer:{s}"].total()
        for s in (RETRIED, PASSED)
        if f"reviewer:{s}" in account.by_attribution()
    )
    assert line.review_tokens[CONTROL].total() == control_reviews
    assert "(left over)" not in line.review_tokens
    # The control role's reviewer (opus) is not the firmware role's (sonnet): the halted try is
    # priced at its own role's, never at the run's one reviewer model (there is none).
    opus = by_model["claude-opus-5-5"]
    firmware_role = sum(
        u.total() for a, u in account.by_attribution().items() if a.startswith("session:2b2b")
    )
    assert opus == control_reviews + firmware_role
    assert line.usd > Decimal(0)


def test_a_review_s_tokens_with_no_halt_after_them_are_still_no_review_it_prices() -> None:
    log = _a_run_recorded_before("usage_limit")
    # A process killed between the try's token lines: nothing after them names the try.
    at = next(k for k, x in enumerate(log.lines) if x["kind"] == "halted")
    log.lines = log.lines[:at]
    events = log.events()
    assert halted_with(HALTED, events) is None
    with pytest.raises(ManifestError, match="records no review for"):
        price_events(make_config(models=MODELS), MANIFEST, events, load_price_sheet(DATE))


def test_a_halt_after_a_try_s_own_line_is_read_by_that_line_not_by_the_halt() -> None:
    # The loop's shape now: the try's tokens, its own ``review_unavailable`` and then the halt.
    log = _a_run_recorded_before("credential_refused")
    at = next(k for k, x in enumerate(log.lines) if x["kind"] == "halted")
    log.lines.insert(
        at,
        {
            **log.lines[at],
            "kind": "review_unavailable",
            "subtask_id": CONTROL,
            "attempt": 1,
            "cause": "infrastructure",
            "detail": "the session ended; the run halts credential_refused, the review owed again",
            "retry": True,
            "session_id": HALTED,
            "reviewer_model": "claude-opus-5-5",
        },
    )
    for k, x in enumerate(log.lines):
        x["seq"] = k
    for key in ("reason", "usage_limit"):
        log.lines[at].pop(key, None)
    events = log.events()
    assert halted_with(HALTED, events) is None, "its own line ends it, before the halt"
    line = _priced(events)
    assert CONTROL in line.review_tokens


def test_a_try_its_own_line_ended_is_not_taken_again_by_a_halt_after_more_of_its_tokens() -> None:
    # A log that records no spawn of the session: its try ended on its own line, and the same id
    # spent again later, right before a halt. The line ended it first; the halt is not its end.
    log = _a_run_recorded_before("credential_refused", spawns=False)
    at = next(k for k, x in enumerate(log.lines) if x["kind"] == "halted")
    named = {
        **{k: log.lines[at][k] for k in ("seq", "ts", "run_id", "gate_mode")},
        "kind": "review_unavailable",
        "subtask_id": CONTROL,
        "attempt": 1,
        "cause": "infrastructure",
        "detail": "the review's session ended with api_error",
        "retry": True,
        "session_id": HALTED,
        "reviewer_model": "claude-opus-5-5",
    }
    log.lines.insert(at - 2, named)
    for k, x in enumerate(log.lines):
        x["seq"] = k
    assert halted_with(HALTED, log.events()) is None
