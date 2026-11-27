"""A ``decompose`` killed in its plan review still marks the tier version its review saw exposed.

A plan review whose stream showed held-out material makes the run's tier version exposed: through
to the opening, the run's event log holds the ``held_out_read`` incident, the exposure register
finds it beneath the role's run roots, and a later reportable run on the version is refused. A
``decompose`` killed during that review, or between the review's end and its round's end line, has
written no event log and no run configuration yet. The next command on its directory scans the
review's streams and records what it finds in a file of its own, and refuses the directory. The
version must then be exposed all the same: the register finds that exposure too, and a later
reportable run on the version is refused.
"""

from __future__ import annotations

import json
import sys
from collections.abc import Iterator
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
    second_version,
    stand_in_store,
    with_run_root,
)
from loop_fakes import usage  # noqa: E402
from test_a_review_session_a_killed_decompose_left_is_stopped_by_the_next_command import (  # noqa: E402
    OTHER_START,
    SESSION,
    Recording,
)
from test_decompose_reviews_the_plan_before_it_writes_anything import (  # noqa: E402
    REVIEWING,
    Calls,
    StandIn,
    Stopped,
    _args,
    _exit,
    _verdict,
    calls,
)

from physgate.evaluation.tiers.checks import CheckError  # noqa: E402
from physgate.evaluation.tiers.exposure import ExposureError  # noqa: E402
from physgate.evaluation.tiers.heldout import tier_digest  # noqa: E402
from physgate.knowledge.library import put_into as real_put_into  # noqa: E402
from physgate.orchestrator import design_rounds, processes  # noqa: E402
from physgate.orchestrator.decompose import start_run as real_start_run  # noqa: E402
from physgate.orchestrator.decomposition_review import (  # noqa: E402
    review_over as real_review_over,
)
from physgate.orchestrator.events import Incident  # noqa: E402
from physgate.orchestrator.exceptions import HeldOutExposedError  # noqa: E402
from physgate.orchestrator.protocols import MessageUsage  # noqa: E402
from physgate.orchestrator.record import RunRecord  # noqa: E402

__all__ = ["calls"]  # the fixture, used by name

EXPOSURE = "physgate.evaluation.tiers.exposure"
ROLE = "control"
EXPOSED_FILE = Path("decomposition", "review_exposed.json")
REVIEW_RECORD = Path("decomposition", "review_session.json")
HELD_OUT_RECORD = Path("decomposition", "held_out_tiers.json")
CLEAN = json.dumps({"type": "user", "message": {"content": "nothing held out here"}}) + "\n"


def _exposed_review() -> HeldOutExposedError:
    """What the plan reviewer raises when its session's stream showed held-out material."""
    spent = (MessageUsage(message_id="r1", usage=usage(5)),)
    msg = "held-out material"
    return HeldOutExposedError(
        msg, session_id=SESSION, reviewer_model="claude-opus-5-5", usage=spent
    )


class OnTier:
    """A stand-in tier version, its run roots, and a ``decompose`` on it beneath them."""

    def __init__(self, tmp_path: Path) -> None:
        self.made: StandInStore = stand_in_store(tmp_path / "s")
        self.runs = with_run_root(self.made, tmp_path / "runs")
        self.review_root = (tmp_path / "review-scratch").resolve()
        params = {
            **REVIEWING,
            "held_out": list(self.made.held_out),
            "held_out_sha256": [tier_digest(Path(root)) for root in self.made.held_out],
            "held_out_canaries": list(self.made.canaries),
        }
        self.args = _args(tmp_path, params)
        self.args[self.args.index("--run-dir") + 1] = str(self.run_dir)

    @property
    def run_dir(self) -> Path:
        return self.runs / "run"

    def withholding(self, made: StandInStore) -> None:
        """The ``decompose`` withholds every version ``made`` holds, as a run on the role must."""
        path = Path(self.args[self.args.index("--params") + 1])
        params = json.loads(path.read_text())
        params["held_out"] = list(made.held_out)
        params["held_out_sha256"] = [tier_digest(Path(root)) for root in made.held_out]
        params["held_out_canaries"] = list(made.canaries)
        path.write_text(json.dumps(params))

    def shown(self) -> str:
        """A stream line that shows one of the version's held-out canaries."""
        canary = self.made.canaries[-1]
        return json.dumps({"type": "user", "message": {"content": f"x <!-- {canary} -->"}}) + "\n"

    def later_refusal(self) -> str | None:
        """What a later reportable run on the version is told: ``None`` if it may start."""
        return refusal(config(self.made.tasks["visible"][0], self.made), self.runs / "r2")

    def exposed(self) -> frozenset[str]:
        found: frozenset[str] = api(f"{EXPOSURE}.exposed_versions")(self.made.store, ROLE)
        return found


@pytest.fixture
def tier(tmp_path: Path, calls: Calls) -> Iterator[OnTier]:
    yield OnTier(tmp_path)


def test_a_decompose_whose_plan_review_showed_held_out_material_marks_its_version_exposed(
    tier: OnTier,
) -> None:
    assert _exit(tier.args, StandIn(_exposed_review())) == 1
    assert (tier.run_dir / "run.json").exists()
    assert tier.exposed() == frozenset({tier.made.version})
    later = tier.later_refusal()
    assert later is not None and "(version_exposed)" in later, later


def _killed_during_the_review(tier: OnTier, monkeypatch: pytest.MonkeyPatch) -> None:
    reviewer = Recording(
        Stopped(), (SESSION, 4242, OTHER_START), stream=tier.shown(), root=tier.review_root
    )
    with pytest.raises(BaseException) as stopped:  # noqa: PT011 - the stop is the point
        _exit(tier.args, reviewer)
    assert stopped.type is Stopped


def _killed_before_the_round_s_end_line(tier: OnTier, monkeypatch: pytest.MonkeyPatch) -> None:
    append = design_rounds._append  # noqa: SLF001 - the journal's own writer

    def dies_at_the_round_s_end(journal: Path, line: Any) -> None:  # noqa: ANN401
        if isinstance(line, design_rounds.RoundEnded):
            raise Stopped
        append(journal, line)

    monkeypatch.setattr(design_rounds, "_append", dies_at_the_round_s_end)
    reviewer = Recording(
        _exposed_review(), (SESSION, 4242, OTHER_START), stream=tier.shown(), root=tier.review_root
    )
    with pytest.raises(BaseException) as stopped:  # noqa: PT011 - the stop is the point
        _exit(tier.args, reviewer)
    assert stopped.type is Stopped
    monkeypatch.setattr(design_rounds, "_append", append)


@pytest.mark.parametrize(
    "kill",
    [_killed_during_the_review, _killed_before_the_round_s_end_line],
    ids=["during its review", "between the review's end and its round's end line"],
)
def test_a_decompose_killed_in_its_plan_review_marks_its_version_exposed_once_found(
    tier: OnTier, monkeypatch: pytest.MonkeyPatch, kill: Any
) -> None:
    kill(tier, monkeypatch)
    assert not (tier.run_dir / "run.json").exists()
    assert not (tier.run_dir / "events.jsonl").exists()
    # The next command on the directory finds the exposure, records it and refuses.
    assert _exit(tier.args, StandIn(_verdict())) == 2
    assert (tier.run_dir / EXPOSED_FILE).is_file()
    assert tier.exposed() == frozenset({tier.made.version}), (
        "the register does not hold the exposure a killed decompose's plan review showed"
    )
    later = tier.later_refusal()
    assert later is not None, "a later reportable run on the exposed version was not refused"
    assert "(version_exposed)" in later, later


def _killed_before_its_opening(tier: OnTier, monkeypatch: pytest.MonkeyPatch) -> None:
    def dies_before_the_opening(*args: Any, **kwargs: Any) -> None:  # noqa: ANN401
        raise Stopped

    monkeypatch.setattr(design_rounds, "start_run", dies_before_the_opening)
    reviewer = Recording(
        _exposed_review(), (SESSION, 4242, OTHER_START), stream=tier.shown(), root=tier.review_root
    )
    with pytest.raises(BaseException) as stopped:  # noqa: PT011 - the stop is the point
        _exit(tier.args, reviewer)
    assert stopped.type is Stopped
    # Put back by hand: undoing every patch would take the session's stand-in credential too.
    monkeypatch.setattr(design_rounds, "start_run", real_start_run)
    assert not (tier.run_dir / "run.json").exists()


def _killed_before_its_opening_s_exposure_line(
    tier: OnTier, monkeypatch: pytest.MonkeyPatch
) -> None:
    emit = RunRecord.emit

    def dies_at_the_exposure(self: RunRecord, line: Any) -> Any:  # noqa: ANN401
        if isinstance(line, Incident):
            raise Stopped
        return emit(self, line)

    monkeypatch.setattr(RunRecord, "emit", dies_at_the_exposure)
    reviewer = Recording(
        _exposed_review(), (SESSION, 4242, OTHER_START), stream=tier.shown(), root=tier.review_root
    )
    with pytest.raises(BaseException) as stopped:  # noqa: PT011 - the stop is the point
        _exit(tier.args, reviewer)
    assert stopped.type is Stopped
    monkeypatch.setattr(RunRecord, "emit", emit)
    assert (tier.run_dir / "run.json").exists()
    events = (tier.run_dir / "events.jsonl").read_text()
    assert "held_out_read" not in events


@pytest.mark.parametrize(
    "kill",
    [_killed_before_its_opening, _killed_before_its_opening_s_exposure_line],
    ids=["after its round's end line, before its opening", "in its opening, before the exposure"],
)
def test_a_decompose_killed_after_its_exposed_review_s_round_ended_marks_its_version_exposed(
    tier: OnTier, monkeypatch: pytest.MonkeyPatch, kill: Any
) -> None:
    kill(tier, monkeypatch)
    # The review's record went with its round's end line: no command finds anything to scan.
    assert not (tier.run_dir / "decomposition" / "review_session.json").exists()
    assert tier.exposed() == frozenset({tier.made.version}), (
        "the register does not hold the exposure an ended review of a killed decompose showed"
    )
    later = tier.later_refusal()
    assert later is not None and "(version_exposed)" in later, later


# --- a decompose killed in its review that no command ever touches again -------------------------


def _killed_in_its_review_showing(tier: OnTier, stream: str) -> None:
    reviewer = Recording(
        Stopped(), (SESSION, 4242, OTHER_START), stream=stream, root=tier.review_root
    )
    with pytest.raises(BaseException) as stopped:  # noqa: PT011 - the stop is the point
        _exit(tier.args, reviewer)
    assert stopped.type is Stopped
    assert (tier.run_dir / REVIEW_RECORD).is_file()
    assert not (tier.run_dir / EXPOSED_FILE).exists()


def _scan(tier: OnTier) -> tuple[int, int]:
    found: tuple[int, int] = api(f"{EXPOSURE}.record_scan")(tier.made.store, ROLE)
    return found


@pytest.mark.parametrize(
    "kill",
    [_killed_during_the_review, _killed_before_the_round_s_end_line],
    ids=["during its review", "between the review's end and its round's end line"],
)
def test_a_decompose_killed_in_its_review_and_never_touched_again_marks_its_version_exposed(
    tier: OnTier, monkeypatch: pytest.MonkeyPatch, kill: Any
) -> None:
    kill(tier, monkeypatch)
    # No command on the directory: the register scans the review's streams itself.
    assert (tier.run_dir / REVIEW_RECORD).is_file()
    assert not (tier.run_dir / EXPOSED_FILE).exists()
    assert tier.exposed() == frozenset({tier.made.version})
    later = tier.later_refusal()
    assert later is not None and "(version_exposed)" in later, later
    # The register only read: the review's record is where it was, nothing written beside it.
    assert (tier.run_dir / REVIEW_RECORD).is_file()
    assert not (tier.run_dir / EXPOSED_FILE).exists()


def test_a_decompose_killed_in_a_clean_review_and_never_touched_again_leaves_its_version_open(
    tier: OnTier,
) -> None:
    _killed_in_its_review_showing(tier, CLEAN)
    assert tier.exposed() == frozenset()
    later = tier.later_refusal()
    assert later is None or "(version_exposed)" not in later, later


def test_an_exposure_moving_from_the_review_s_record_to_the_next_command_s_file_is_recorded_once(
    tier: OnTier,
) -> None:
    _killed_in_its_review_showing(tier, tier.shown())
    assert _scan(tier) == (1, 0)
    assert _exit(tier.args, StandIn(_verdict())) == 2
    assert (tier.run_dir / EXPOSED_FILE).is_file()
    assert not (tier.run_dir / REVIEW_RECORD).exists()
    assert _scan(tier) == (0, 1)
    assert tier.exposed() == frozenset({tier.made.version})


def test_a_review_still_running_is_read_to_its_last_whole_line(
    tier: OnTier, monkeypatch: pytest.MonkeyPatch
) -> None:
    # A line cut inside a character reads as one that cannot be read, which counts as the canary:
    # while the session runs it is a line still being written, and is read once whole.
    cut = CLEAN.encode() + "\u00e9".encode()[:1]
    _killed_in_its_review_showing(tier, CLEAN)
    stream = tier.review_root / SESSION / "session" / "stdout.jsonl"
    stream.write_bytes(cut)
    monkeypatch.setattr(processes, "is_session", lambda *_: True)
    assert tier.exposed() == frozenset()
    monkeypatch.setattr(processes, "is_session", lambda *_: False)
    assert tier.exposed() == frozenset({tier.made.version})


# --- the version a decomposition was given, recorded before its review ---------------------------


def test_a_reviewed_decompose_records_its_held_out_tiers_before_its_review_runs(
    tier: OnTier,
) -> None:
    seen: list[bool] = []

    class Looks(Recording):
        def review_plan(self, under: Any) -> Any:  # noqa: ANN401
            seen.append((tier.run_dir / HELD_OUT_RECORD).is_file())
            return super().review_plan(under)

    with pytest.raises(Stopped):
        _exit(tier.args, Looks(Stopped(), (SESSION, 4242, OTHER_START), root=tier.review_root))
    assert seen == [True]
    recorded = json.loads((tier.run_dir / HELD_OUT_RECORD).read_text())
    assert recorded == {"held_out_sha256": [tier_digest(Path(root)) for root in tier.made.held_out]}


def test_a_killed_decompose_s_exposure_marks_the_version_it_recorded_and_no_later_one(
    tier: OnTier,
) -> None:
    _killed_in_its_review_showing(tier, tier.shown())
    try:
        # Its blind check is recorded as it is written, which an exposed version refuses.
        later = second_version(tier.made)
    except CheckError as exc:
        msg = "a version written after the killed decompose is marked exposed"
        raise AssertionError(msg) from exc
    assert tier.exposed() == frozenset({tier.made.version})
    told = refusal(config(later.tasks["visible"][0], later), tier.runs / "r3")
    assert told is None or "(version_exposed)" not in told, told


def test_a_killed_decompose_that_recorded_no_held_out_tiers_marks_every_version_of_the_role(
    tier: OnTier,
) -> None:
    # The second version is there first (once every version is exposed, none is checked again),
    # and the decompose withholds both, as a run on the role must.
    later = second_version(tier.made)
    tier.withholding(later)
    _killed_in_its_review_showing(tier, tier.shown())
    (tier.run_dir / HELD_OUT_RECORD).unlink()  # as a decomposition made before the record
    assert tier.exposed() == frozenset({tier.made.version, later.version})


# --- what cannot be read fails closed ------------------------------------------------------------


@pytest.mark.parametrize(
    "broken", [REVIEW_RECORD, HELD_OUT_RECORD], ids=["the review's record", "the held-out record"]
)
def test_a_killed_decompose_s_record_that_cannot_be_read_refuses_the_reportable_run(
    tier: OnTier, broken: Path
) -> None:
    _killed_in_its_review_showing(tier, tier.shown())
    (tier.run_dir / broken).write_text("{not json")
    later = tier.later_refusal()
    assert later is not None and "(register_unreadable)" in later, later
    with pytest.raises(ExposureError) as refused:
        tier.exposed()
    assert refused.value.context.get("refused_because") == "register_unreadable"
    # Named by its kind of place: neither the run directory nor the record's path is said.
    assert str(tier.runs) not in str(refused.value), str(refused.value)


def test_a_killed_decompose_whose_review_stream_is_gone_marks_its_version_exposed(
    tier: OnTier,
) -> None:
    _killed_in_its_review_showing(tier, CLEAN)
    (tier.review_root / SESSION / "session" / "stdout.jsonl").unlink()
    assert tier.exposed() == frozenset({tier.made.version})


# --- the round journal, as the register reads it ------------------------------------------------

JOURNAL = Path("decomposition", "rounds.jsonl")


def test_a_kill_between_the_round_s_end_line_and_the_review_s_record_going_records_it_once(
    tier: OnTier, monkeypatch: pytest.MonkeyPatch
) -> None:
    def dies_as_the_record_goes(run_dir: Path, **_: Any) -> None:  # noqa: ANN401
        raise Stopped

    monkeypatch.setattr(design_rounds, "review_over", dies_as_the_record_goes)
    reviewer = Recording(
        _exposed_review(), (SESSION, 4242, OTHER_START), stream=tier.shown(), root=tier.review_root
    )
    with pytest.raises(Stopped):
        _exit(tier.args, reviewer)
    # Put back by hand: undoing every patch would take the session's stand-in credential too.
    monkeypatch.setattr(design_rounds, "review_over", real_review_over)
    # The journal's end line and the review's record both show it: one exposure, one key.
    assert (tier.run_dir / REVIEW_RECORD).is_file()
    assert "held_out_exposed" in (tier.run_dir / JOURNAL).read_text()
    assert _scan(tier) == (1, 0)
    assert _exit(tier.args, StandIn(_verdict())) == 2
    assert (tier.run_dir / EXPOSED_FILE).is_file()
    assert _scan(tier) == (0, 1)
    assert tier.exposed() == frozenset({tier.made.version})


def test_a_whole_journal_line_that_cannot_be_read_refuses_and_names_no_path(tier: OnTier) -> None:
    _killed_in_its_review_showing(tier, CLEAN)
    with (tier.run_dir / JOURNAL).open("ab") as journal:
        journal.write(b"{not a line\n")
    with pytest.raises(ExposureError) as refused:
        tier.exposed()
    assert refused.value.context.get("refused_because") == "register_unreadable"
    assert str(tier.runs) not in str(refused.value), str(refused.value)
    later = tier.later_refusal()
    assert later is not None and "(register_unreadable)" in later, later


def test_a_journal_line_a_kill_cut_is_read_in_its_review_s_record(tier: OnTier) -> None:
    _killed_in_its_review_showing(tier, CLEAN)
    cut = b'{"kind": "round_ended", "ending": {"review_cause": "held_out_exposed"'
    with (tier.run_dir / JOURNAL).open("ab") as journal:
        journal.write(cut)
    # The record is read in its place, and its streams showed nothing.
    assert _readable(tier) == frozenset()


# --- a decomposition cut before its run's configuration is written -------------------------------


def _cut_before_run_json(
    tier: OnTier, monkeypatch: pytest.MonkeyPatch, how: str, review: Any
) -> None:  # noqa: ANN401
    """The start opens the run's record, then a kill or a refusal cuts it before ``run.json``.

    What it leaves: an empty event log, no run configuration, the decomposition's own records,
    and the run branch's checkout, here as deep as one goes.
    """
    from physgate.knowledge.library import LibraryError  # noqa: PLC0415
    from physgate.orchestrator import decompose  # noqa: PLC0415

    def cut(*args: Any, **kwargs: Any) -> None:  # noqa: ANN401
        if how == "killed":
            raise Stopped
        msg = "the library cannot be put into the run branch"
        raise LibraryError(msg)

    monkeypatch.setattr(decompose, "put_into", cut)
    if how == "killed":
        with pytest.raises(Stopped):
            _exit(tier.args, review)
    else:
        assert _exit(tier.args, review) == 2
    monkeypatch.setattr(decompose, "put_into", real_put_into)
    assert (tier.run_dir / "events.jsonl").read_bytes() == b""
    assert not (tier.run_dir / "run.json").exists()
    assert (tier.run_dir / "params_source.json").is_file()
    deep = tier.run_dir / "worktrees" / "integration" / ".git" / "a" / "b" / "c" / "d" / "e" / "f"
    deep.mkdir(parents=True)


def _readable(tier: OnTier) -> frozenset[str]:
    """The exposed versions, the register held to being readable: a refusal fails the row."""
    try:
        return tier.exposed()
    except ExposureError as exc:
        reason = exc.context.get("refused_because")
        msg = f"the register refuses every reader ({reason})"
        raise AssertionError(msg) from exc


def _passed() -> Any:  # noqa: ANN401
    return StandIn(_verdict("pass"))


def _exposed(tier: OnTier) -> Any:  # noqa: ANN401
    return Recording(
        _exposed_review(), (SESSION, 4242, OTHER_START), stream=tier.shown(), root=tier.review_root
    )


@pytest.mark.parametrize("how", ["killed", "raised"])
def test_a_decomposition_cut_before_its_run_json_after_a_clean_review_leaves_the_register_readable(
    tier: OnTier, monkeypatch: pytest.MonkeyPatch, how: str
) -> None:
    _cut_before_run_json(tier, monkeypatch, how, _passed())
    # Read as a run's directory: not walked into, and nothing in it is an exposure.
    assert _readable(tier) == frozenset()
    later = tier.later_refusal()
    assert later is None or "(register_unreadable)" not in later, later
    assert later is None or "(version_exposed)" not in later, later
    # The store still refuses a reportable run on a version exposed elsewhere.
    api(f"{EXPOSURE}.mark_exposed")(
        tier.made.store, ROLE, tier.made.version, by="a person", reason="opened the tier by hand"
    )
    later = tier.later_refusal()
    assert later is not None and "(version_exposed)" in later, later


@pytest.mark.parametrize("how", ["killed", "raised"])
def test_a_decomposition_cut_before_its_run_json_after_an_exposed_review_marks_its_version_exposed(
    tier: OnTier, monkeypatch: pytest.MonkeyPatch, how: str
) -> None:
    _cut_before_run_json(tier, monkeypatch, how, _exposed(tier))
    assert _readable(tier) == frozenset({tier.made.version})
    later = tier.later_refusal()
    assert later is not None and "(version_exposed)" in later, later


@pytest.mark.parametrize("how", ["killed", "raised"])
def test_a_decomposition_with_no_plan_review_cut_before_its_run_json_leaves_the_register_readable(
    tier: OnTier, monkeypatch: pytest.MonkeyPatch, how: str
) -> None:
    # No review, so no round journal and no review record: only the call's own place.
    path = Path(tier.args[tier.args.index("--params") + 1])
    path.write_text(json.dumps({**json.loads(path.read_text()), "design_review": "off"}))
    _cut_before_run_json(tier, monkeypatch, how, None)
    assert not (tier.run_dir / JOURNAL).exists()
    assert not (tier.run_dir / REVIEW_RECORD).exists()
    assert _readable(tier) == frozenset()
    later = tier.later_refusal()
    assert later is None or "(register_unreadable)" not in later, later
