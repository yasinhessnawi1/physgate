"""A decomposition stopped by the account's usage limit names the limit, and waits for its reset.

The plan call is a session like any other: when the account it spends from reaches its usage
limit, its stream says so as a role session's does (a ``rate_limit_event`` whose state is
``rejected``, an assistant message whose error is ``rate_limit``, a result whose text names the
limit). So the call's end is read as a role session's is, by the same reading, and named
``usage_limit`` with the reset the stream gave, never ``api_error``: the run's record and the round
journal carry the cause and the reset, and ``decompose`` exits as a run halted on the limit does
(75, the step ``waiting_for_limit``, and the instant after which to come back). The same holds for
the plan's review, whose reviewer reads the limit as an attempt's reviewer does.

Nothing of such a call is counted but what its stream says it used, and nothing is an attempt. A
stopped decomposition is not resumed: its directory is refused as every decomposed directory is,
and a decomposition into a fresh directory after the reset goes on. An API error that is not the
limit is still an API error.

The plan call here is the real one, its binary's output scripted: the streams are the stand-ins
the role sessions' rows use, in the shape a live run's stream gave when its account reached the
limit, with the reset a couple of hours from now so the record's reset is one a run would wait
for.
"""

from __future__ import annotations

import json
import shutil
import subprocess
import time
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

import pytest
import replan_rig
from orch_helpers import make_config
from replan_rig import DESIGN, Script, Step, events, journal
from test_a_usage_limit_is_its_own_cause_and_the_run_waits_for_its_reset import (
    SESSION_LIMIT,
    _limited,
    _outage,
)

import physgate.orchestrator.decompose as decompose
from physgate.orchestrator.common import utc_stamp
from physgate.orchestrator.credentials import Credential
from physgate.orchestrator.design_rounds import read_journal
from physgate.orchestrator.events import Halted, read_events
from physgate.orchestrator.exceptions import ReviewUnavailableError, RunStateError
from physgate.orchestrator.protocols import MessageUsage, Usage
from physgate.orchestrator.usage_limit import UsageLimit, usage_limit_of

#: The binary the scripted plan call is made with: its output is the step's stream.
FAKE = "/nonexistent/claude"
#: What ``decompose`` exits with for a run waiting for the account's usage limit.
WAITING = 75
#: The limit's text where it gives no reset.
NO_RESET = "You've hit your session limit"
#: What a session refused at its first request used.
NOTHING = Usage(
    input_tokens=0, output_tokens=0, cache_read_input_tokens=0, cache_creation_input_tokens=0
)


def _epoch() -> int:
    """A reset two hours from now, in whole seconds, as the refusal event gives it."""
    return int(time.time()) + 2 * 3600


def _stamp(epoch: int) -> str:
    return utc_stamp(datetime.fromtimestamp(epoch, UTC))


@dataclass
class LimitScript(Script):
    """The scripted rounds, with a step whose plan call is the real one on a scripted stream.

    ``call``: ``limit`` ends on the limit with the refusal's reset instant, ``limit-unread`` with
    no reset at all, ``limit-text`` with the reset in the result's text alone, ``outage`` on a 503.
    ``review``: ``limit`` is a review its reviewer read as ended on the limit.
    """

    epoch: int = field(default_factory=_epoch)

    def stream(self, kind: str) -> tuple[str, dict[str, Any]]:
        if kind == "limit":
            return _limited(resets_at=self.epoch)
        if kind == "limit-unread":
            return _limited(NO_RESET, resets_at=None)
        if kind == "limit-text":
            return _limited(SESSION_LIMIT, resets_at=None)
        return _outage()

    def call(self, brief: str, *, workdir: Path, **given: Any) -> Any:  # noqa: ANN401
        step = self._step(len(self.calls) + 1)
        if step.call not in ("limit", "limit-unread", "limit-text", "outage"):
            return super().call(brief, workdir=workdir, **given)
        self.calls.append({"brief": brief, "workdir": workdir, **given})
        stream, _ = self.stream(step.call)
        return real_call(brief, workdir=workdir, stream=stream, **given)

    def review_plan(self, under: Any) -> Any:  # noqa: ANN401
        k = len(self.calls)
        if self._step(k).review != "limit":
            return super().review_plan(under)
        self.seen.append(under)
        stream, result = self.stream("limit")
        raise ReviewUnavailableError(
            "the session ended with api_error",
            cause="infrastructure",
            session_id=f"review-{k}",
            reviewer_model=DESIGN,
            usage=(MessageUsage(message_id=f"r{k}", usage=NOTHING),),
            usage_limit=usage_limit_of(stream, result),
        )


def real_call(
    brief: str,
    *,
    workdir: Path,
    stream: str,
    **given: Any,  # noqa: ANN401
) -> decompose.Outcome:
    """The plan call as ``decompose`` makes it, its binary answering with ``stream``."""
    config = given["config"]
    real_run = subprocess.run

    def ran(argv: Any, *args: Any, **kwargs: Any) -> Any:  # noqa: ANN401
        if isinstance(argv, list) and argv and argv[0] == FAKE:
            return subprocess.CompletedProcess(argv, 1, stdout=stream, stderr="")
        return real_run(argv, *args, **kwargs)

    with pytest.MonkeyPatch.context() as patch:
        patch.setattr(decompose, "claude_binary", lambda: FAKE)
        patch.setattr(decompose, "binary_version", lambda binary=None: config.claude_version)
        patch.setattr(subprocess, "run", ran)
        patch.setattr(decompose, "traffic_refusal", lambda *a, **k: None)
        patch.setattr(decompose, "drift", lambda *a, **k: None)
        return decompose.call(brief, workdir=workdir, **given)


@dataclass(frozen=True)
class Made:
    """What one ``decompose`` came to: its exit, directory, script and what it printed."""

    code: Any
    run_dir: Path
    script: LimitScript
    out: dict[str, Any]
    err: dict[str, Any]


def _json(text: str) -> dict[str, Any]:
    """The last thing printed, where it is an object: the command's own words."""
    text = text.strip()
    if text.startswith("{") and text.endswith("}"):
        try:
            return dict(json.loads(text))
        except json.JSONDecodeError:
            pass
    for line in reversed(text.splitlines()):
        if line.startswith("{"):
            try:
                return dict(json.loads(line))
            except json.JSONDecodeError:
                continue
    return {}


def made(
    root: Path,
    mode: str,
    steps: list[Step],
    capsys: pytest.CaptureFixture[str],
    monkeypatch: pytest.MonkeyPatch,
) -> Made:
    """``decompose`` under ``mode`` on ``steps``, through the command, in ``root``."""
    monkeypatch.setattr(replan_rig, "Script", LimitScript)
    capsys.readouterr()
    ran = replan_rig.decompose(root, mode, steps)
    said = capsys.readouterr()
    script = ran.script
    assert isinstance(script, LimitScript)
    return Made(ran.code, ran.run_dir, script, _json(said.out), _json(said.err))


def _halts(run_dir: Path) -> list[Halted]:
    return [e for e in read_events(run_dir / "events.jsonl") if isinstance(e, Halted)]


# -- a run that does not review its plan ----------------------------------------------------------


def test_a_plan_call_stopped_by_the_limit_is_recorded_as_the_limit_with_its_reset(
    tmp_path: Path, capsys: pytest.CaptureFixture[str], monkeypatch: pytest.MonkeyPatch
) -> None:
    ran = made(tmp_path, "off", [Step(call="limit")], capsys, monkeypatch)
    reset = _stamp(ran.script.epoch)
    (halt,) = _halts(ran.run_dir)
    # A failed decomposition, as every plan call that gave no plan is; its cause is the limit.
    assert halt.reason == "decomposition_failed"
    assert halt.detail.split(":", 1)[0] == "usage_limit", halt.detail
    assert halt.usage_limit is not None, "the halt carries no limit"
    assert halt.usage_limit.resets_at == reset
    assert halt.usage_limit.limit_type == "five_hour"
    assert halt.usage_limit.resets == "1:20pm (Europe/Oslo)"


def test_decompose_stopped_by_the_limit_exits_as_a_run_waiting_for_it(
    tmp_path: Path, capsys: pytest.CaptureFixture[str], monkeypatch: pytest.MonkeyPatch
) -> None:
    ran = made(tmp_path, "off", [Step(call="limit")], capsys, monkeypatch)
    reset = _stamp(ran.script.epoch)
    assert ran.code == WAITING, (ran.code, ran.out, ran.err)
    assert ran.out["decomposed"] is False
    assert ran.out["cause"] == "usage_limit"
    assert ran.out["step"] == "waiting_for_limit"
    assert ran.out["limit_type"] == "five_hour"
    assert ran.out["resets_at"] == reset
    assert ran.out["resume_after"] == reset


def test_a_plan_call_stopped_by_the_limit_with_no_reset_waits_the_unread_wait(
    tmp_path: Path, capsys: pytest.CaptureFixture[str], monkeypatch: pytest.MonkeyPatch
) -> None:
    ran = made(tmp_path, "off", [Step(call="limit-unread")], capsys, monkeypatch)
    (halt,) = _halts(ran.run_dir)
    assert halt.detail.split(":", 1)[0] == "usage_limit", halt.detail
    assert halt.usage_limit is not None
    assert (halt.usage_limit.resets, halt.usage_limit.resets_at) == (None, None)
    assert ran.code == WAITING, (ran.code, ran.out, ran.err)
    after = datetime.strptime(halt.ts, "%Y-%m-%dT%H:%M:%S.%fZ").replace(tzinfo=UTC)
    assert ran.out["resets_at"] is None
    assert ran.out["resume_after"] == utc_stamp(after + timedelta(hours=5))


def test_a_reset_the_limit_gives_only_in_its_text_is_read_at_the_halt(
    tmp_path: Path, capsys: pytest.CaptureFixture[str], monkeypatch: pytest.MonkeyPatch
) -> None:
    # The text's wall time read in its zone, the next such instant after the halt: zone data is
    # needed, so this row runs where the machine has it.
    ran = made(tmp_path, "off", [Step(call="limit-text")], capsys, monkeypatch)
    (halt,) = _halts(ran.run_dir)
    assert halt.usage_limit is not None
    assert halt.usage_limit.resets == "1:20pm (Europe/Oslo)"
    instant = halt.usage_limit.resets_at
    assert instant is not None, "the text's reset was not read"
    assert halt.ts < instant
    assert ran.out["resume_after"] == instant


def test_nothing_of_a_call_stopped_by_the_limit_is_counted_but_what_its_stream_used(
    tmp_path: Path, capsys: pytest.CaptureFixture[str], monkeypatch: pytest.MonkeyPatch
) -> None:
    ran = made(tmp_path, "off", [Step(call="limit")], capsys, monkeypatch)
    kinds = [e["kind"] for e in events(ran.run_dir)]
    # The run's start, the call's one message as the stream gave it, and the halt: no session,
    # no attempt, no retry, no subtask.
    assert kinds == ["run_started", "tokens_used", "halted"], kinds
    (spent,) = [e for e in events(ran.run_dir) if e["kind"] == "tokens_used"]
    assert spent["attribution"].startswith("decomposition:")
    assert spent["message_id"] == "msg_1"
    assert all(n == 0 for n in spent["usage"].values()), spent["usage"]
    assert ran.out["subtasks"] == []


def test_a_stopped_decomposition_s_directory_is_refused_and_a_fresh_one_goes_on(
    tmp_path: Path, capsys: pytest.CaptureFixture[str], monkeypatch: pytest.MonkeyPatch
) -> None:
    first = made(tmp_path / "a", "off", [Step(call="limit")], capsys, monkeypatch)
    assert first.code == WAITING, (first.code, first.out, first.err)
    # Into the directory it left (its bytes, beside a target of its own): refused before any
    # call, and what it left kept as it was.
    shutil.copytree(first.run_dir, tmp_path / "a2" / "run", symlinks=True)
    before = (tmp_path / "a2" / "run" / "events.jsonl").read_bytes()
    again = made(tmp_path / "a2", "off", [Step()], capsys, monkeypatch)
    assert again.code == 2, (again.code, again.out, again.err)
    assert again.script.calls == []
    assert "already holds a run" in again.err["error"]
    assert (again.run_dir / "events.jsonl").read_bytes() == before
    # Into a fresh directory, after the reset: the decomposition goes on and the run starts.
    fresh = made(tmp_path / "b", "off", [Step()], capsys, monkeypatch)
    assert fresh.code == 0, (fresh.code, fresh.out, fresh.err)
    assert fresh.out["decomposed"] is True
    assert "decomposed" in [e["kind"] for e in events(fresh.run_dir)]


def test_an_api_error_that_is_not_the_limit_is_still_an_api_error(
    tmp_path: Path, capsys: pytest.CaptureFixture[str], monkeypatch: pytest.MonkeyPatch
) -> None:
    ran = made(tmp_path, "off", [Step(call="outage")], capsys, monkeypatch)
    (halt,) = _halts(ran.run_dir)
    assert halt.detail.split(":", 1)[0] == "api_error", halt.detail
    assert halt.usage_limit is None
    assert ran.code == 1
    assert ran.out["cause"] == "api_error"
    assert "step" not in ran.out


# -- a run that reviews its plan -----------------------------------------------------------------


def test_a_plan_call_stopped_by_the_limit_ends_the_rounds_void_on_the_limit_with_its_reset(
    tmp_path: Path, capsys: pytest.CaptureFixture[str], monkeypatch: pytest.MonkeyPatch
) -> None:
    ran = made(tmp_path, "on", [Step(call="limit")], capsys, monkeypatch)
    reset = _stamp(ran.script.epoch)
    lines = journal(ran.run_dir)
    ended = next(one for one in lines if one["kind"] == "round_ended")
    assert ended["ending"]["plan_cause"] == "usage_limit"
    assert ended["usage_limit"]["resets_at"] == reset
    terminal = lines[-1]
    assert (terminal["follows"], terminal["ending_class"], terminal["cause"]) == (
        "void",
        "infrastructure",
        "usage_limit",
    )
    read_journal(ran.run_dir, last=1)  # what was written is what the rounds write
    assert events(ran.run_dir) == [], "a void decomposition starts no run"
    assert ran.code == WAITING, (ran.code, ran.out, ran.err)
    assert ran.err["step"] == "waiting_for_limit"
    assert ran.err["resume_after"] == reset


def test_a_plan_call_stopped_by_the_limit_in_an_observed_run_halts_on_the_limit(
    tmp_path: Path, capsys: pytest.CaptureFixture[str], monkeypatch: pytest.MonkeyPatch
) -> None:
    ran = made(tmp_path, "observe", [Step(call="limit")], capsys, monkeypatch)
    reset = _stamp(ran.script.epoch)
    (halt,) = _halts(ran.run_dir)
    assert halt.detail.split(":", 1)[0] == "usage_limit", halt.detail
    assert halt.usage_limit is not None
    assert halt.usage_limit.resets_at == reset
    terminal = journal(ran.run_dir)[-1]
    assert (terminal["follows"], terminal["cause"]) == ("fail_run", "usage_limit")
    read_journal(ran.run_dir, last=1, holds=False)
    assert ran.code == WAITING, (ran.code, ran.out, ran.err)
    assert ran.out["resume_after"] == reset


def test_a_plan_review_stopped_by_the_limit_ends_the_rounds_void_on_the_limit_with_its_reset(
    tmp_path: Path, capsys: pytest.CaptureFixture[str], monkeypatch: pytest.MonkeyPatch
) -> None:
    ran = made(tmp_path, "on", [Step(review="limit")], capsys, monkeypatch)
    reset = _stamp(ran.script.epoch)
    lines = journal(ran.run_dir)
    ended = next(one for one in lines if one["kind"] == "round_ended")
    # The review's own end is infrastructure, as an attempt's review on the limit is; the limit
    # it was read as rides beside it, and the rounds end on the limit.
    assert ended["ending"]["review_cause"] == "infrastructure"
    assert ended["review"]["unavailable"]["usage_limit"]["resets_at"] == reset
    assert ended["usage_limit"]["resets_at"] == reset
    terminal = lines[-1]
    assert (terminal["follows"], terminal["cause"]) == ("void", "usage_limit")
    read_journal(ran.run_dir, last=1)
    assert ran.code == WAITING, (ran.code, ran.out, ran.err)
    assert ran.err["resume_after"] == reset


def test_a_plan_review_stopped_by_the_limit_in_an_observed_run_starts_it_naming_the_limit(
    tmp_path: Path, capsys: pytest.CaptureFixture[str], monkeypatch: pytest.MonkeyPatch
) -> None:
    # An observed review's infrastructure end starts the run, as it always has; the record says
    # the review ended on the limit, with its reset.
    ran = made(tmp_path, "observe", [Step(review="limit")], capsys, monkeypatch)
    reset = _stamp(ran.script.epoch)
    (line,) = [e for e in events(ran.run_dir) if e["kind"] == "design_review_ran"]
    assert line["unavailable"]["cause"] == "infrastructure"
    assert line["unavailable"]["usage_limit"]["resets_at"] == reset
    assert ran.code == 0, (ran.code, ran.out, ran.err)


def _rewrite(run_dir: Path, lines: list[dict[str, Any]]) -> None:
    path = run_dir / "decomposition" / "rounds.jsonl"
    path.write_text("".join(json.dumps(one) + "\n" for one in lines))


def test_the_journal_holds_a_limit_exactly_where_its_round_ended_on_it(
    tmp_path: Path, capsys: pytest.CaptureFixture[str], monkeypatch: pytest.MonkeyPatch
) -> None:
    limited = made(tmp_path / "a", "on", [Step(call="limit")], capsys, monkeypatch)
    lines = journal(limited.run_dir)
    ended = next(one for one in lines if one["kind"] == "round_ended")
    del ended["usage_limit"]
    _rewrite(limited.run_dir, lines)
    with pytest.raises(RunStateError) as without:
        read_journal(limited.run_dir, last=1)
    assert without.value.context["check"] == "limit"
    # A review that ended in infrastructure, not on the limit: the rounds end on its cause.
    other = made(tmp_path / "b", "on", [Step(review="infrastructure")], capsys, monkeypatch)
    lines = journal(other.run_dir)
    assert lines[-1]["cause"] == "infrastructure"
    read_journal(other.run_dir, last=1)
    lines[-1]["cause"] = "usage_limit"
    _rewrite(other.run_dir, lines)
    with pytest.raises(RunStateError) as named:
        read_journal(other.run_dir, last=1)
    assert named.value.context["check"] == "terminal"


# -- the reading is the role session's, on both pins ----------------------------------------------


@pytest.mark.parametrize("pin", ["2.1.301", "2.1.322"])
def test_the_plan_call_reads_the_limit_as_a_role_session_does_on_both_pins(
    tmp_path: Path, pin: str
) -> None:
    stream, result = _limited(resets_at=_epoch())
    outcome = real_call(
        "Build a robot.\n",
        workdir=tmp_path / "decomposition",
        stream=stream,
        config=make_config(claude_version=pin),
        base_url=None,
        credential=Credential(mode="api_key", secret="sk-ant-test-dummy-not-a-credential"),
    )
    assert outcome.cause == "usage_limit"
    assert outcome.ok is False
    assert outcome.usage_limit == usage_limit_of(stream, result)


def test_a_failed_decomposition_s_halt_carries_a_limit_only_where_its_cause_is_the_limit() -> None:
    envelope: dict[str, Any] = {
        "seq": 1,
        "ts": "2026-11-24T10:00:00.000000Z",
        "run_id": "run-1",
        "gate_mode": "on",
    }
    limit = UsageLimit(resets=None)
    kept = Halted(**envelope, reason="decomposition_failed", detail="usage_limit: the call ended")
    # Written byte for byte as before the limit was carried.
    assert "usage_limit" not in json.loads(kept.model_dump_json())
    Halted(
        **envelope,
        reason="decomposition_failed",
        detail="usage_limit: the call ended",
        usage_limit=limit,
    )
    with pytest.raises(ValueError, match="usage limit"):
        Halted(
            **envelope,
            reason="decomposition_failed",
            detail="api_error: the call ended",
            usage_limit=limit,
        )
