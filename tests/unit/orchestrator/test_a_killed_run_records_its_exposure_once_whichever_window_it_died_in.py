"""A run killed between what showed held-out material and its record still records it, once.

A held-out read in a run on a tier version marks that version exposed, and a later reportable run
on it is refused: the exposure register finds the run's ``held_out_read`` incident in its event
log, beneath the role's run roots, and the run's held-out digests name the version. The record of
an exposure is written by the loop after the session or the review that showed it has ended, so a
process can die in between. Each row here runs the loop on a stand-in tier version built in a
temporary directory, kills the process in one such window, lets a fresh process take the run over,
and holds the register and the run's records to it: the exposure is there exactly once, the exposed
work is never merged, a later reportable run on the version is refused, and one more take-over adds
nothing. The windows:

- a role session the dispatcher has ended, before the loop has written any line of it;
- at the session's end line, just before it or just after it (its exposure is recorded before
  it: a process killed after it must not leave the run as if the session showed nothing);
- a resume that has stopped and read what an earlier process left running, before its record;
- a review that wrote its end on disk before the loop read what it showed;
- a review whose exposure reached the loop, as the loop writes that exposure or the review's tokens;
- a review killed in its repair resume, whose repair stream showed the material.

A run killed before anything showed held-out material records no exposure and leaves its version
open: the rows above do not pass by marking every killed run.

One window is not exactly once, and its row says so: a resume killed after a leftover's lone
incident and before the leftover is ended records that incident again when it is taken over. Two
register lines then stand for one session's exposure; the version is refused all the same, and
named once among the exposed versions.
"""

from __future__ import annotations

import json
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import pytest

EXPOSURE_TESTS = Path(__file__).resolve().parents[1] / "evaluation" / "exposure"
if str(EXPOSURE_TESTS) not in sys.path:
    sys.path.insert(0, str(EXPOSURE_TESTS))

from exposure_fixtures import (  # noqa: E402
    StandInStore,
    api,
    config,
    refusal,
    stand_in_store,
    with_run_root,
)
from left_session import INSTALL_BIN  # noqa: E402
from loop_fakes import KilledError, Rig, plan  # noqa: E402
from orch_helpers import make_config  # noqa: E402
from test_a_review_s_exposure_is_found_again_after_a_kill_past_its_end_record import (  # noqa: E402
    ENDED,
    STARTED,
    EndedReviewer,
    RealStop,
    _dies_at_the_review_s_tokens,
)
from test_a_session_end_s_findings_are_recorded_before_its_incidents_and_a_kill_writes_the_rest import (  # noqa: E402, E501
    dies_at,
    kinds,
    lines,
    outcome,
    taken_over,
)
from test_a_session_s_findings_are_on_the_record_before_it_is_ended import (  # noqa: E402
    EndedBySession,
    _session_dir,
)

from physgate.evaluation.tiers.heldout import tier_digest  # noqa: E402
from physgate.orchestrator.credentials import Credential  # noqa: E402
from physgate.orchestrator.dispatch import ClaudeDispatcher  # noqa: E402
from physgate.orchestrator.events import Event  # noqa: E402
from physgate.orchestrator.loop import Loop  # noqa: E402
from physgate.orchestrator.merge import RunGit  # noqa: E402
from physgate.orchestrator.run_config import RunConfig  # noqa: E402

EXPOSURE = "physgate.evaluation.tiers.exposure"
ROLE = "control"


def _tool_output(text: str) -> str:
    """One line of a session's stream: a tool's output, as the runtime writes it."""
    shown = {"type": "user", "message": {"content": [{"type": "tool_result", "content": text}]}}
    return json.dumps(shown) + "\n"


# --- the stand-in tier version, and a run on it beneath the role's run roots -------------------


@dataclass
class OnTier:
    """A stand-in tier version, its run roots, and where the killed run lives beneath them."""

    made: StandInStore
    runs: Path
    review_root: Path

    @property
    def run_dir(self) -> Path:
        return self.runs / "r1"

    @property
    def canary(self) -> str:
        """One of the version's held-out canaries, which the run looks for."""
        return self.made.canaries[-1]

    def shown(self) -> str:
        """A stream line that shows the canary."""
        return _tool_output(f"the task reads: <!-- {self.canary} -->")

    def held(self) -> dict[str, Any]:
        """What the run records of the version: the roots it withholds, their digests, canaries."""
        return {
            "held_out": self.made.held_out,
            "held_out_sha256": tuple(tier_digest(Path(root)) for root in self.made.held_out),
            "held_out_canaries": self.made.canaries,
        }

    def run_config(self) -> RunConfig:
        return make_config(os_layer_absent="allow", **self.held())

    def dispatcher(self) -> ClaudeDispatcher:
        """The real dispatcher of the run, whose stop and read a resume runs."""
        return ClaudeDispatcher(
            config=self.run_config(),
            run=RunGit(repo=self.run_dir, run_dir=self.run_dir, run_id="run-1"),
            store_root=self.run_dir / "store",
            install_bin=INSTALL_BIN,
            binary="/nonexistent/claude",
            base_url=None,
            credential=Credential("api_key", "sk-ant-test-dummy-not-a-credential"),
            review_root=self.review_root,
        )

    def rig(self, **ports: Any) -> Rig:  # noqa: ANN401 - the rig's own ports
        return Rig(self.run_dir, config_overrides=self.held(), **ports)


@pytest.fixture
def tier(tmp_path: Path) -> OnTier:
    made = stand_in_store(tmp_path / "s")
    runs = with_run_root(made, tmp_path / "runs")
    (runs / "r1").mkdir()
    review_root = tmp_path / "reviews"
    review_root.mkdir()
    return OnTier(made, runs, review_root)


@dataclass
class SessionOnTier(EndedBySession):
    """The first session's directory on disk as the real dispatcher leaves it, ended or not.

    Its stream shows what ``stream`` says; with ``dies_inside`` the process is killed while the
    session runs, before its end is written. A resume's stop and read are the real dispatcher's.
    """

    on: OnTier | None = None
    dies_inside: bool = False

    def _dispatcher(self) -> ClaudeDispatcher:
        assert self.on is not None
        return self.on.dispatcher()

    def run(self, request: Any, on_spawn: Any = None) -> Any:  # noqa: ANN401 - the port's own
        if self.dies_inside and not self.requests:
            assert self.real_dir is not None and on_spawn is not None
            _session_dir(self.real_dir, "sess-1", self.stream)
            on_spawn("sess-1", 999_999, STARTED)
            self.requests.append(request)
            raise KilledError
        return super().run(request, on_spawn)


@dataclass
class ReviewOnTier(RealStop):
    """The fakes' sessions, with the real dispatcher's stop over the run's review root."""

    on: OnTier | None = None

    def stop_leftovers(self) -> Any:  # noqa: ANN401 - the port's own
        assert self.on is not None
        self.held = self.on.dispatcher()
        return self.held.stop_leftovers()


@dataclass
class RepairedReviewer(EndedReviewer):
    """Its first review runs clean, is spawned again to repair its verdict, and the process dies.

    The first invocation's end stays on disk; the repair stream shows what ``stream`` says.
    """

    def review(self, artefact: Any) -> Any:  # noqa: ANN401
        if self.seen:
            return super().review(artefact)
        self.seen.append(artefact)
        assert self.hook is not None and self.review_root is not None
        sid = "rev-sess-1"
        sdir = self.review_root / sid / "session"
        sdir.mkdir(parents=True)
        (sdir / "owner.json").write_text(json.dumps({"run_id": "run-1"}))
        record = {"pid": 999_999, "started": STARTED, "session_id": sid, "kind": "reviewer"}
        (sdir / "process.json").write_text(json.dumps(record))
        self.hook(sid, 999_999, STARTED)
        (sdir / "stdout.jsonl").write_text(_tool_output("the plan reads well"))
        (sdir / "ended.json").write_text(json.dumps(ENDED))
        self.hook(sid, 999_998, STARTED)
        (sdir / "stdout-repair-1.jsonl").write_text(self.stream)
        raise KilledError


# --- what each row holds the run and the register to -------------------------------------------


def _exposures(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    return [r for r in rows if r["kind"] == "incident" and r["cause"] == "held_out_read"]


def _exposed_once(on: OnTier, rig: Rig) -> None:
    """The run and the register hold the exposure once, and a later measured run is refused."""
    rows = lines(rig)
    assert len(_exposures(rows)) == 1, f"the run records {len(_exposures(rows))} exposures, not 1"
    assert on.canary not in json.dumps(rows), "the canary itself is on the record"
    assert "merged" not in kinds(rows), "the exposed work merged"
    found = api(f"{EXPOSURE}.found_exposures")(on.made.store, ROLE)
    assert [(f.source, f.versions) for f in found] == [
        ("incident", frozenset({on.made.version}))
    ], "the register does not find the run's exposure exactly once"
    assert api(f"{EXPOSURE}.record_scan")(on.made.store, ROLE) == (1, 0)
    register = api(f"{EXPOSURE}.register_lines")(on.made.store, ROLE)
    assert [(x.kind, x.source, x.version) for x in register] == [
        ("exposure", "incident", on.made.version)
    ]
    later = refusal(config(on.made.tasks["visible"][0], on.made), on.runs / "r2")
    assert later is not None, "a later reportable run on the exposed version was not refused"
    assert "(version_exposed)" in later, later
    # One more process taking the run over finds nothing new to record.
    taken_over(rig)
    assert len(_exposures(lines(rig))) == 1, "a later take-over recorded the exposure again"
    assert api(f"{EXPOSURE}.record_scan")(on.made.store, ROLE) == (0, 1)


def _dies_at_the_first_line_after_the_session(loop: Loop, rig: Rig) -> None:
    """The process dies once the dispatcher has handed the session over, before any line of it."""
    emit = loop._emit  # noqa: SLF001 - the loop's own writer

    def dying(event: Event) -> None:
        if rig.dispatcher.requests and event.kind != "session_spawned":
            raise KilledError
        emit(event)

    loop._emit = dying  # type: ignore[method-assign]  # noqa: SLF001


def _dies_at_the_review_s_exposure(loop: Loop) -> None:
    """The process dies as it is about to write the exposure the review's end showed."""
    emit = loop._emit  # noqa: SLF001 - the loop's own writer

    def dying(event: Event) -> None:
        if event.kind == "incident":
            raise KilledError
        emit(event)

    loop._emit = dying  # type: ignore[method-assign]  # noqa: SLF001


def _killed(rig: Rig, arrange: Any = None) -> None:  # noqa: ANN401 - a kill point's set-up
    loop = rig.open()
    loop.start(plan("s1"))
    if arrange is not None:
        arrange(loop)
    assert outcome(loop.run) == "killed"
    loop.close()


# --- before anything showed: no exposure --------------------------------------------------------


@pytest.mark.parametrize("when", ["before its session started", "while its session ran clean"])
def test_a_run_killed_before_anything_showed_held_out_material_records_no_exposure(
    tier: OnTier, when: str
) -> None:
    if when == "before its session started":
        # No session directory and no spawn: the dispatcher is killed as it is asked for one.
        rig = tier.rig(dispatcher=SessionOnTier(real_dir=None, on=tier, kill_on=1))
    else:
        clean = _tool_output("nothing held out here")
        dispatcher = SessionOnTier(real_dir=tier.run_dir, on=tier, stream=clean, dies_inside=True)
        rig = tier.rig(dispatcher=dispatcher)
    _killed(rig)
    assert taken_over(rig) == "done"
    rows = lines(rig)
    assert _exposures(rows) == []
    assert "merged" in kinds(rows)
    assert api(f"{EXPOSURE}.found_exposures")(tier.made.store, ROLE) == []
    assert api(f"{EXPOSURE}.record_scan")(tier.made.store, ROLE) == (0, 0)
    later = refusal(config(tier.made.tasks["visible"][0], tier.made), tier.runs / "r2")
    assert later is None, f"a version nothing saw was refused: {later}"


# --- at a role session's end --------------------------------------------------------------------


def test_a_session_the_dispatcher_ended_before_the_loop_wrote_a_line_of_it_is_exposed_once(
    tier: OnTier,
) -> None:
    dispatcher = SessionOnTier(
        real_dir=tier.run_dir, on=tier, stream=tier.shown(), held_out={1: tier.canary}
    )
    rig = tier.rig(dispatcher=dispatcher)
    _killed(rig, lambda loop: _dies_at_the_first_line_after_the_session(loop, rig))
    assert (tier.run_dir / "sessions" / "sess-1" / "ended.json").exists()
    assert "session_ended" not in kinds(lines(rig))
    taken_over(rig)
    assert kinds(lines(rig))[-1] == "halted"
    _exposed_once(tier, rig)


def _dies_after_the_session_s_end_line(loop: Loop) -> None:
    """The process dies as it is about to write the line after the session's end line."""
    emit = loop._emit  # noqa: SLF001 - the loop's own writer
    ended = [False]

    def dying(event: Event) -> None:
        if ended[0]:
            raise KilledError
        ended[0] = event.kind == "session_ended"
        emit(event)

    loop._emit = dying  # type: ignore[method-assign]  # noqa: SLF001


@pytest.mark.parametrize("at", ["before its end line", "after its end line"])
def test_a_run_killed_at_its_session_s_end_line_holds_the_session_s_exposure_once(
    tier: OnTier, at: str
) -> None:
    dispatcher = SessionOnTier(
        real_dir=tier.run_dir, on=tier, stream=tier.shown(), held_out={1: tier.canary}
    )
    rig = tier.rig(dispatcher=dispatcher)
    if at == "before its end line":
        _killed(rig, lambda loop: dies_at(loop, 1, "session_ended"))
    else:
        _killed(rig, _dies_after_the_session_s_end_line)
    assert taken_over(rig) == "halted"
    assert "leftover_read" not in kinds(lines(rig)), "the session's stream was read again"
    _exposed_once(tier, rig)


# --- at a resume: what an earlier process left running ------------------------------------------


def test_a_resume_killed_after_it_read_a_leftover_s_exposure_and_before_its_record_holds_it_once(
    tier: OnTier,
) -> None:
    rig = tier.rig(dispatcher=SessionOnTier(real_dir=tier.run_dir, on=tier))
    loop = rig.open()
    loop.start(plan("s1"))
    loop._spawned("left-1", 999_999, STARTED)  # noqa: SLF001 - the loop's own record of a spawn
    loop.close()
    _session_dir(tier.run_dir, "left-1", tier.shown())
    loop = rig.open()
    dies_at(loop, 1, "incident")
    assert outcome(loop.run) == "killed"
    loop.close()
    assert _exposures(lines(rig)) == []
    assert taken_over(rig) == "halted"
    rows = lines(rig)
    assert kinds(rows).count("leftover_read") == 1
    assert "left-1" in _exposures(rows)[0]["detail"]
    _exposed_once(tier, rig)


def test_a_resume_killed_after_a_leftover_s_lone_incident_may_record_it_twice_and_refuses_it(
    tier: OnTier,
) -> None:
    """The known limit, pinned as it is: killed after the incident and before the leftover is ended.

    The take-over writes the owed halt, finds the leftover again and records its incident a
    second time: two register lines for one session's exposure. It fails closed: the version is
    refused, and the register names it once among the exposed versions.
    """
    rig = tier.rig(dispatcher=SessionOnTier(real_dir=tier.run_dir, on=tier))
    loop = rig.open()
    loop.start(plan("s1"))
    loop._spawned("left-1", 999_999, STARTED)  # noqa: SLF001 - the loop's own record of a spawn
    loop.close()
    _session_dir(tier.run_dir, "left-1", tier.shown())

    def dies_as_it_ends_them() -> None:
        raise KilledError

    rig.dispatcher.end_leftovers = dies_as_it_ends_them  # type: ignore[method-assign]
    loop = rig.open()
    assert outcome(loop.run) == "killed"
    loop.close()
    del rig.dispatcher.end_leftovers
    assert kinds(lines(rig))[-1] == "incident"
    assert len(_exposures(lines(rig))) == 1
    assert taken_over(rig) == "halted"
    rows = lines(rig)
    assert kinds(rows)[-5:] == ["incident", "halted", "incident", "leftover_read", "halted"]
    assert len(_exposures(rows)) == 2
    assert all("left-1" in row["detail"] for row in _exposures(rows))
    assert "merged" not in kinds(rows)
    assert api(f"{EXPOSURE}.record_scan")(tier.made.store, ROLE) == (2, 0)
    register = api(f"{EXPOSURE}.register_lines")(tier.made.store, ROLE)
    assert [(x.kind, x.version) for x in register] == [("exposure", tier.made.version)] * 2
    exposed = api(f"{EXPOSURE}.exposed_versions")(tier.made.store, ROLE)
    assert exposed == frozenset({tier.made.version})
    later = refusal(config(tier.made.tasks["visible"][0], tier.made), tier.runs / "r2")
    assert later is not None and "(version_exposed)" in later, later


# --- at a review --------------------------------------------------------------------------------


def _reviewed(on: OnTier, reviewer: EndedReviewer) -> Rig:
    reviewer.review_root = on.review_root
    return on.rig(reviewer=reviewer, dispatcher=ReviewOnTier(on=on))


def test_a_review_killed_after_its_end_record_and_before_the_loop_s_lines_is_exposed_once(
    tier: OnTier,
) -> None:
    rig = _reviewed(tier, EndedReviewer(stream=tier.shown()))
    _killed(rig)
    assert _exposures(lines(rig)) == []
    taken_over(rig)
    assert kinds(lines(rig))[-1] == "halted"
    _exposed_once(tier, rig)


@pytest.mark.parametrize("at", ["its exposure", "its tokens"])
def test_a_review_whose_exposure_reached_the_loop_killed_as_it_is_written_is_exposed_once(
    tier: OnTier, at: str
) -> None:
    rig = _reviewed(tier, EndedReviewer(stream=tier.shown(), mode="raises"))
    kill = _dies_at_the_review_s_exposure if at == "its exposure" else _dies_at_the_review_s_tokens
    _killed(rig, kill)
    taken_over(rig)
    assert kinds(lines(rig))[-1] == "halted"
    _exposed_once(tier, rig)


def test_a_review_killed_in_its_repair_resume_is_exposed_once_by_its_repair_stream(
    tier: OnTier,
) -> None:
    rig = _reviewed(tier, RepairedReviewer(stream=tier.shown()))
    _killed(rig)
    assert _exposures(lines(rig)) == []
    taken_over(rig)
    assert kinds(lines(rig))[-1] == "halted"
    _exposed_once(tier, rig)
