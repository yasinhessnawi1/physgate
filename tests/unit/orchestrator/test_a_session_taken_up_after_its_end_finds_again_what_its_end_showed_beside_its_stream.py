"""A session taken up after its own end finds again what that end showed beside its stream.

A process killed after the dispatcher ended a session and before the loop's first line about it
leaves a session the record spawned and never ended: the next process reads it again. Its stream
is scanned as a leftover's is. What its end showed outside the stream is read again too, from what
the session's directory keeps: a possible abort from the stream, the unverified reaping from the
hook layer's log, a refused placeholder from the sweep's record and the policy limits from the
configuration directory, against the run's first. A possible abort counts only where the record
shows the session ran under the OS layer, never where the machine has it at the resume: without
the layer a ``bwrap:`` line is the session's own output. These findings come last in the order a
resume's halt is named by.

A session left running, which its own run never ended, gains none of them.
"""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any

import pytest
from loop_fakes import KilledError, Rig, plan
from test_a_session_end_s_findings_are_recorded_before_its_incidents_and_a_kill_writes_the_rest import (  # noqa: E501
    kinds,
    lines,
    outcome,
    taken_over,
)
from test_a_session_s_findings_are_on_the_record_before_it_is_ended import (
    CANARY,
    STARTED,
    EndedBySession,
    _session_dir,
)

from physgate.orchestrator.events import OsLayerChecked
from physgate.orchestrator.loop import Loop
from physgate.oslayer.probe import Absent, Present

PRESENT = Present(mechanism="bubblewrap", claude_version="2.1.301")
ABSENT = Absent(reason="no sandbox here")
#: A tool result bubblewrap's own failure ended: a possible abort.
ABORTED = {
    "type": "user",
    "message": {
        "content": [
            {
                "type": "tool_result",
                "tool_use_id": "toolu_a",
                "is_error": True,
                "content": "bwrap: Can't find source path /tmp/gone: No such file or directory",
            }
        ]
    },
}
#: The hook layer's line for a command whose survivor reaper was not heard from.
UNHEARD = {"decision": "reaper_unverified", "tool_input": {"command": "make all"}}
REFUSED = [["modules/s1/.claude", "a link stands where the sandbox's placeholder was"]]
LIMITS = b'{"restrictions": {"allow_remote_sessions": false}}'


def _layer(loop: Loop, state: Present | Absent) -> None:
    """This process's line about the OS layer, as the command writes it before it drives."""
    loop.record.emit(OsLayerChecked(**loop.record.envelope(), state=state, as_recorded=None))


def _left_on_disk(sdir: Path, shown: set[str], *, exposed: bool = False) -> None:
    """What the session's directory keeps of its end, beside the stream it already holds."""
    if "abort" in shown or exposed:
        tool = {"type": "tool_result", "content": f"the task reads: <!-- {CANARY} -->"}
        exposure = {"type": "user", "message": {"content": [tool]}}
        stream = [ABORTED] if "abort" in shown else []
        stream += [exposure] if exposed else []
        (sdir / "stdout.jsonl").write_text("".join(json.dumps(e) + "\n" for e in stream))
    if "reaping" in shown:
        with (sdir / "state" / "hooks.log.jsonl").open("a") as log:
            log.write(json.dumps({"session": sdir.name, **UNHEARD}) + "\n")
    if "placeholder" in shown:
        (sdir / "sandbox_placeholders.json").write_text(
            json.dumps({"removed": [], "refused": REFUSED})
        )
    if "limits" in shown:
        (sdir / "config").mkdir(exist_ok=True)
        (sdir / "config" / "policy-limits.json").write_bytes(LIMITS)


class LeftOnDisk(EndedBySession):
    """The first session's directory also keeps what ``shown`` names, as its end left it."""

    def __init__(self, shown: set[str], *, exposed: bool, **given: Any) -> None:  # noqa: ANN401
        super().__init__(**given)
        self.shown, self.exposed = shown, exposed

    def run(self, request: Any, on_spawn: Any = None) -> Any:  # noqa: ANN401 - the port's own
        first = not self.requests
        report = super().run(request, on_spawn)
        if first and self.real_dir is not None:
            _left_on_disk(self.real_dir / "sessions" / "sess-1", self.shown, exposed=self.exposed)
        return report


#: What each shape's session showed, as its own end reports it to the loop.
REPORTED: dict[str, dict[int, Any]] = {
    "abort": {"aborted": {1: ("toolu_a",)}},
    "reaping": {"unverified": {1: (json.dumps(UNHEARD["tool_input"]),)}},
    "placeholder": {"placeholders": {1: f"{REFUSED[0][0]}: {REFUSED[0][1]}"}},
    "limits": {"policy": {1: hashlib.sha256(LIMITS).hexdigest()}},
}


def _killed_after_its_end(
    path: Path, shown: set[str], layer: Present | Absent | None, *, exposed: bool = False
) -> Rig:
    """A run whose first session ended showing ``shown``, killed before the loop's first line."""
    reported: dict[str, Any] = {}
    for name in shown:
        reported |= REPORTED[name]
    if exposed:
        reported["held_out"] = {1: CANARY}
    path.mkdir(parents=True)
    dispatcher = LeftOnDisk(shown, exposed=exposed, real_dir=path, **reported)
    if not exposed and "abort" not in shown:
        dispatcher.stream = "nothing held out here"
    rig = Rig(path, dispatcher=dispatcher)
    loop = rig.open()
    loop.start(plan("s1"))
    if layer is not None:
        _layer(loop, layer)
    emit = loop._emit  # noqa: SLF001

    def dying(event: Any) -> None:  # noqa: ANN401 - any line the loop writes
        # Once the dispatcher has handed the report over: the loop's first line is never written.
        if rig.dispatcher.requests and event.kind != "session_spawned":
            raise KilledError
        emit(event)

    loop._emit = dying  # type: ignore[method-assign]  # noqa: SLF001
    said = outcome(loop.run)
    loop.close()
    assert said == "killed", said
    assert (path / "sessions" / "sess-1" / "ended.json").exists()
    assert "session_ended" not in kinds(lines(rig))
    return rig


def _halted_with(rig: Rig, causes: list[str], halt: str) -> list[dict[str, Any]]:
    """The take-up halts once, under ``halt``, after an incident for each of ``causes``."""
    taken_over(rig)  # a resume that halts on what it found says so by refusing to go on
    rows = lines(rig)
    assert kinds(rows)[-1] == "halted", kinds(rows)
    incidents = [r for r in rows if r["kind"] == "incident"]
    assert [r["cause"] for r in incidents] == causes
    assert all("sess-1" in r["detail"] for r in incidents), incidents
    (halted,) = [r for r in rows if r["kind"] == "halted"]
    assert halted["detail"] == halt
    assert "merged" not in kinds(rows)
    assert CANARY not in json.dumps(rows)
    return incidents


# --- a session taken up: what its end showed is found again ---------------------------------------


def test_a_kill_after_an_end_with_an_abort_and_unverified_reaping_resumes_halted_with_both(
    tmp_path: Path,
) -> None:
    rig = _killed_after_its_end(tmp_path / "run", {"abort", "reaping"}, PRESENT)
    abort, reaping = _halted_with(
        rig, ["os_layer_aborted", "reaper_unverified"], "os_layer_aborted"
    )
    assert "toolu_a" in abort["detail"] and "possible abort" in abort["detail"]
    assert "make all" in reaping["detail"]


def test_a_kill_after_an_end_with_a_refused_placeholder_resumes_halted_on_it(
    tmp_path: Path,
) -> None:
    rig = _killed_after_its_end(tmp_path / "run", {"placeholder"}, PRESENT)
    (refused,) = _halted_with(rig, ["placeholder_refused"], "placeholder_refused")
    assert REFUSED[0][0] in refused["detail"] and REFUSED[0][1] in refused["detail"]


def test_a_kill_after_an_end_under_other_policy_limits_resumes_halted_on_them(
    tmp_path: Path,
) -> None:
    rig = _killed_after_its_end(tmp_path / "run", {"limits"}, PRESENT)
    (changed,) = _halted_with(rig, ["managed_settings_changed"], "managed_settings_changed")
    assert hashlib.sha256(LIMITS).hexdigest() in changed["detail"]


def test_what_a_taken_up_end_showed_beside_its_stream_comes_last_in_the_halt_s_order(
    tmp_path: Path,
) -> None:
    rig = _killed_after_its_end(tmp_path / "run", {"abort"}, PRESENT, exposed=True)
    _halted_with(rig, ["held_out_read", "os_layer_aborted"], "held_out_read")


@pytest.mark.parametrize("record", ["absent", "none", "present after the spawn"])
def test_a_possible_abort_counts_only_where_the_record_shows_the_layer_at_the_spawn(
    tmp_path: Path, record: str
) -> None:
    layer = {"absent": ABSENT, "none": None, "present after the spawn": ABSENT}[record]
    rig = _killed_after_its_end(tmp_path / "run", {"abort"}, layer)
    if record == "present after the spawn":
        # The resume's own process runs where the layer is: that says nothing of the session.
        loop = rig.open()
        _layer(loop, PRESENT)
        loop.close()
    said = taken_over(rig)
    rows = lines(rig)
    assert [r["cause"] for r in rows if r["kind"] == "incident"] == []
    assert said == "done", said
    assert kinds(rows).count("leftover_read") == 1


# --- a session left running: its own run never ended it ------------------------------------------


@pytest.mark.parametrize("ended", ["never", "by a resume killed after it"])
def test_a_session_left_running_gains_none_of_what_an_end_shows_beside_its_stream(
    tmp_path: Path, ended: str
) -> None:
    run_dir = tmp_path / "run"
    run_dir.mkdir(parents=True)
    rig = Rig(run_dir, dispatcher=EndedBySession(real_dir=run_dir, stream="nothing held out"))
    loop = rig.open()
    loop.start(plan("s1"))
    _layer(loop, PRESENT)
    loop._spawned("left-1", 999_999, STARTED)  # noqa: SLF001
    loop.close()
    sdir = _session_dir(run_dir, "left-1", "nothing held out here")
    _left_on_disk(sdir, {"abort", "reaping", "placeholder", "limits"})
    if ended != "never":
        # The end a resume writes, once it has the leftover's findings on the record.
        (sdir / "ended.json").write_text(json.dumps({"not_running_at_resume": True}))
    loop = rig.open()
    said = outcome(loop.run)
    loop.close()
    rows = lines(rig)
    assert [r["cause"] for r in rows if r["kind"] == "incident"] == []
    assert said == "done", said
    assert kinds(rows).count("leftover_read") == 1
