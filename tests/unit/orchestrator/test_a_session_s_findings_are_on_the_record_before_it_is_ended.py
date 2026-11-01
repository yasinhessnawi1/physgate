"""What a session's end shows is on the record before anything says the session ended.

A session's end can show things a person must look at. The line that records them (the findings
line, or the lone incident) is written as soon as the dispatcher hands the report over: before the
session's tokens and before its end line. A process killed after it leaves a halt owed, so the run
fails closed. One killed before it, after the dispatcher ended the session, leaves a session the
record spawned and never ended: the next process reads its stream again as a leftover's, unless the
record already holds what it showed. A session the record ended is never read twice.

The leftovers a resume finds are stopped and read first, and ended only once their findings are on
the record: a process killed in between finds them again.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import pytest
from left_session import INSTALL_BIN, sentinel_installed
from loop_fakes import FakeDispatcher, KilledError, Rig, plan
from test_a_session_end_s_findings_are_recorded_before_its_incidents_and_a_kill_writes_the_rest import (  # noqa: E501
    ENDS,
    _renumbered,
    dies_at,
    kinds,
    lines,
    outcome,
    refusal,
    taken_over,
)

from physgate.orchestrator.credentials import Credential
from physgate.orchestrator.dispatch import ClaudeDispatcher, EndFindings, write_record
from physgate.orchestrator.merge import RunGit
from physgate.orchestrator.ports import Leftover, SessionReport, SessionRequest, SpawnHook

CANARY = "c" * 32
STARTED = "Mon Jan  1 00:00:00 2001"
#: A session end with one finding, beside those with several.
LONE_END: dict[str, tuple[dict[str, Any], list[str], str]] = {
    "exposure alone": ({"held_out": {1: CANARY}}, ["held_out_read"], "held_out_read"),
}
SHAPES = {**ENDS, **LONE_END}


def _real(run_dir: Path) -> ClaudeDispatcher:
    from orch_helpers import make_config

    return ClaudeDispatcher(
        config=make_config(held_out_canaries=(CANARY,)),
        run=RunGit(repo=run_dir, run_dir=run_dir, run_id="run-1"),
        store_root=run_dir / "store",
        install_bin=INSTALL_BIN,
        binary="/nonexistent/claude",
        base_url=None,
        credential=Credential("api_key", "sk-ant-test-dummy-not-a-credential"),
        review_root=run_dir.parent / "no-review-root",
    )


def _session_dir(run_dir: Path, sid: str, text: str) -> Path:
    """A role session's directory as a real run leaves it: its record, its sentinel, its stream."""
    sdir = run_dir / "sessions" / sid
    sdir.mkdir(parents=True)
    (sdir / "process.json").write_text(
        json.dumps({"pid": 999_999, "started": STARTED, "session_id": sid})
    )
    sentinel_installed(sdir, run_dir / "guarded")
    tool_output = {
        "type": "user",
        "message": {"content": [{"type": "tool_result", "content": text}]},
    }
    (sdir / "stdout.jsonl").write_text(json.dumps(tool_output) + "\n")
    return sdir


@dataclass
class EndedBySession(FakeDispatcher):
    """The fake's sessions, with the first one's directory on disk as the real dispatcher leaves it.

    Its spawn is recorded through the loop's hook and its ``ended.json`` written before the report
    is handed over, as the real dispatcher does; the resume's stop and read are the real ones.
    """

    real_dir: Path | None = None
    #: What the first session's stream shows.
    stream: str = f"the task reads: <!-- {CANARY} -->"

    def _dispatcher(self) -> ClaudeDispatcher:
        assert self.real_dir is not None
        return _real(self.real_dir)

    def run(self, request: SessionRequest, on_spawn: SpawnHook | None = None) -> SessionReport:
        if not self.requests and self.real_dir is not None:
            sdir = _session_dir(self.real_dir, "sess-1", self.stream)
            assert on_spawn is not None
            on_spawn("sess-1", 999_999, STARTED)
            report = super().run(request, on_spawn)
            # The sweep's record, as the real dispatcher writes it under the OS layer.
            (sdir / "sandbox_placeholders.json").write_text('{"removed": [], "refused": []}')
            write_record(sdir.parent, sdir.name, ended_record(report), "ended.json")
            return report
        return super().run(request, on_spawn)

    def stop_leftovers(self) -> list[Leftover]:
        self._held = self._dispatcher()
        return self._held.stop_leftovers()

    def end_leftovers(self) -> None:
        self._held.end_leftovers()


def ended_record(report: SessionReport) -> dict[str, Any]:
    """The end record the real dispatcher writes, with what the session's end found."""
    found = EndFindings(
        os_layer_aborted=report.os_layer_aborted,
        reaper_unverified=report.reaper_unverified,
        placeholders_refused=report.placeholders_refused,
        policy_limits_sha256=report.policy_limits_sha256,
    )
    return {"exit": 0, "timed_out": False, "findings": found.model_dump(mode="json")}


def _rig(path: Path, **shown: Any) -> Rig:  # noqa: ANN401 - the fake's own fields
    path.mkdir(parents=True)
    return Rig(path, dispatcher=EndedBySession(real_dir=path, **shown))


# --- at a session end: the findings first --------------------------------------------------------


@pytest.mark.parametrize("shape", SHAPES)
def test_a_session_end_s_findings_come_before_its_tokens_and_its_end_line(
    tmp_path: Path, shape: str
) -> None:
    from test_a_session_end_s_findings_are_recorded_before_its_incidents_and_a_kill_writes_the_rest import (  # noqa: E501, PLC0415
        ended_session,
    )

    shown, incidents, halt = SHAPES[shape]
    rows = lines(ended_session(tmp_path, shown, kill=None))
    first = next(i for i, k in enumerate(kinds(rows)) if k in ("findings_recorded", "incident"))
    assert "session_ended" in kinds(rows)
    assert first < kinds(rows).index("session_ended"), kinds(rows)
    tokens = [i for i, k in enumerate(kinds(rows)) if k == "tokens_used"]
    assert tokens and first < min(tokens), kinds(rows)
    assert [r["cause"] for r in rows if r["kind"] == "incident"] == incidents
    assert kinds(rows).count("halted") == 1
    assert rows[kinds(rows).index("halted")]["detail"] == f"{halt} in s1"


@pytest.mark.parametrize("shape", SHAPES)
def test_a_kill_before_a_session_s_end_line_resumes_halted_with_every_finding(
    tmp_path: Path, shape: str
) -> None:
    from test_a_session_end_s_findings_are_recorded_before_its_incidents_and_a_kill_writes_the_rest import (  # noqa: E501, PLC0415
        ended_session,
    )

    shown, incidents, halt = SHAPES[shape]
    rig = ended_session(tmp_path, shown, kill=(1, "session_ended"))
    said = taken_over(rig)
    assert said == "halted", said
    rows = lines(rig)
    assert [r["cause"] for r in rows if r["kind"] == "incident"] == incidents
    (halted,) = [r for r in rows if r["kind"] == "halted"]
    assert halted["detail"] == f"{halt} in s1"
    assert "merged" not in kinds(rows)


def test_a_findings_line_after_its_session_s_end_line_is_refused(tmp_path: Path) -> None:
    from test_a_session_end_s_findings_are_recorded_before_its_incidents_and_a_kill_writes_the_rest import (  # noqa: E501, PLC0415
        ended_session,
    )

    shown, _, _ = ENDS["exposure, tampering and abort"]
    rows = lines(ended_session(tmp_path, shown, kill=None))
    assert "findings_recorded" in kinds(rows)
    record = rows.pop(kinds(rows).index("findings_recorded"))
    rows.insert(kinds(rows).index("session_ended") + 1, record)
    assert refusal(_renumbered(rows)) is not None


# --- a kill after the dispatcher ended the session, before the loop's first line ---------------


def test_a_kill_after_the_session_was_ended_and_before_any_line_resumes_halted_on_its_exposure(
    tmp_path: Path,
) -> None:
    rig = _rig(tmp_path / "run", held_out={1: CANARY})
    loop = rig.open()
    loop.start(plan("s1"))
    emit = loop._emit  # noqa: SLF001

    def dying(event: Any) -> None:  # noqa: ANN401 - any line the loop writes
        # Once the dispatcher has handed the report over: the loop's first line is never written.
        if rig.dispatcher.requests and event.kind != "session_spawned":
            raise KilledError
        emit(event)

    loop._emit = dying  # type: ignore[method-assign]  # noqa: SLF001
    assert outcome(loop.run) == "killed"
    loop.close()
    assert (tmp_path / "run" / "sessions" / "sess-1" / "ended.json").exists()
    assert "session_ended" not in kinds(lines(rig))
    taken_over(rig)  # a resume that halts on what it found says so by refusing to go on
    rows = lines(rig)
    assert kinds(rows)[-1] == "halted", kinds(rows)
    incidents = [r for r in rows if r["kind"] == "incident"]
    assert [r["cause"] for r in incidents] == ["held_out_read"]
    assert "sess-1" in incidents[0]["detail"]
    assert CANARY not in json.dumps(rows)
    assert "merged" not in kinds(rows)
    # The end the session's own run wrote is kept.
    ended = json.loads((tmp_path / "run" / "sessions" / "sess-1" / "ended.json").read_text())
    assert ended["exit"] == 0 and ended["timed_out"] is False
    assert ended["findings"]["reaper_unverified"] == []


def test_a_kill_after_a_session_s_finding_does_not_read_its_stream_again(tmp_path: Path) -> None:
    rig = _rig(tmp_path / "run", held_out={1: CANARY})
    loop = rig.open()
    loop.start(plan("s1"))
    dies_at(loop, 1, "session_ended")
    assert outcome(loop.run) == "killed"
    loop.close()
    said = taken_over(rig)
    assert said == "halted", said
    rows = lines(rig)
    assert [r["cause"] for r in rows if r["kind"] == "incident"] == ["held_out_read"]
    assert "leftover_read" not in kinds(rows)


def test_a_session_the_record_ended_is_never_read_again(tmp_path: Path) -> None:
    rig = _rig(tmp_path / "run")
    loop = rig.open()
    loop.start(plan("s1"))
    assert loop.run().kind == "done"
    loop.close()
    before = lines(rig)
    assert "session_ended" in kinds(before)
    again = rig.open()
    assert again.run().kind == "done"
    again.close()
    assert lines(rig) == before


def test_a_review_session_ended_on_disk_is_not_taken_up(tmp_path: Path) -> None:
    from left_session import spawn_logged  # noqa: PLC0415

    run_dir, root = tmp_path / "run", tmp_path / "rs"
    (run_dir / "sessions").mkdir(parents=True)
    review = "11111111-1111-4111-8111-111111111111"
    sdir = root / review / "session"
    sdir.mkdir(parents=True)
    (sdir / "owner.json").write_text(json.dumps({"run_id": "run-1"}))
    record = {"pid": 999_999, "started": STARTED, "session_id": review, "kind": "reviewer"}
    (sdir / "process.json").write_text(json.dumps(record))
    (sdir / "stdout.jsonl").write_text(f"the task reads: <!-- {CANARY} -->\n")
    (sdir / "ended.json").write_text("{}")
    spawn_logged(run_dir, [(review, 999_999, STARTED)])
    real = _real(run_dir)
    real._review_root = root  # noqa: SLF001 - the review root the run names
    assert real.stop_leftovers() == []


# --- the leftovers: stopped and read, then ended once their findings are on the record ---------


def test_the_stop_of_a_leftover_writes_no_end_and_its_end_is_written_after(
    tmp_path: Path,
) -> None:
    from left_session import spawn_logged  # noqa: PLC0415

    run_dir = tmp_path / "run"
    sdir = _session_dir(run_dir, "left-1", "nothing held out here")
    spawn_logged(run_dir, [("left-1", 999_999, STARTED)])
    real = _real(run_dir)
    (left,) = real.stop_leftovers()
    assert left.session_id == "left-1"
    assert not (sdir / "ended.json").exists(), "the stop ended the leftover"
    real.end_leftovers()
    assert (sdir / "ended.json").exists()


def test_a_kill_right_after_the_leftovers_are_read_finds_them_again(tmp_path: Path) -> None:
    run_dir = tmp_path / "run"
    rig = _rig(run_dir)
    loop = rig.open()
    loop.start(plan("s1"))
    loop._spawned("left-1", 999_999, STARTED)  # noqa: SLF001
    loop.close()
    _session_dir(run_dir, "left-1", f"the task reads: <!-- {CANARY} -->")
    loop = rig.open()
    dies_at(loop, 1, "incident")
    assert outcome(loop.run) == "killed"
    loop.close()
    said = taken_over(rig)
    assert said == "halted", said
    rows = lines(rig)
    incidents = [r for r in rows if r["kind"] == "incident"]
    assert [r["cause"] for r in incidents] == ["held_out_read"]
    assert "left-1" in incidents[0]["detail"]
    assert kinds(rows).count("leftover_read") == 1
    assert (run_dir / "sessions" / "left-1" / "ended.json").exists()
