"""A left review's credential goes first, and no refusal of a review stream hides an exposure.

- The next command removes a left review's credential files once nothing of it runs, whatever its
  scan comes to: a stream that cannot be read keeps the record, never the credential, and the
  words say what was removed. Only the stream's redaction waits for the scan.
- Every stream's refusal is kept: a stream that is gone where tiers were recorded is an exposure,
  whichever other stream of the same review was refused first, and for whatever.
- What the live review's scan showed is on the review's record before its stream is redacted, so
  a line the redaction replaces, counted as the canary, is still counted by every later reader.
- A settle is a line of its own that marks no version, refused for a directory outside every run
  root and for one the register refuses nothing in; a register written when a hand mark settled
  a directory reads as it did.
- The walk passes over only the target and the review root a decomposition's records name in its
  own directory, and a run at the top of a place it passes over is still found.
- ``decompose`` looks into a review root and a target given inside its run directory.
- A round that ended void scans its review before the record goes.
"""

from __future__ import annotations

import contextlib
import json
import sys
from collections.abc import Callable, Iterator
from pathlib import Path

import pytest

EXPOSURE_TESTS = Path(__file__).resolve().parents[1] / "evaluation" / "exposure"
if str(EXPOSURE_TESTS) not in sys.path:
    sys.path.insert(0, str(EXPOSURE_TESTS))

from exposure_fixtures import harness_run, incident_in, second_version  # noqa: E402
from test_a_decompose_killed_in_its_plan_review_records_the_exposure_on_its_tier_version import (  # noqa: E402
    CLEAN,
    EXPOSED_FILE,
    JOURNAL,
    REVIEW_RECORD,
    OnTier,
    _passed,
    _readable,
)
from test_a_review_session_a_killed_decompose_left_is_stopped_by_the_next_command import (  # noqa: E402
    OTHER_START,
    SESSION,
    Recording,
)
from test_decompose_reviews_the_plan_before_it_writes_anything import (  # noqa: E402
    Calls,
    Stopped,
    _exit,
    calls,
)
from test_the_exposure_register_reads_a_decomposition_s_directory_by_what_it_wrote import (  # noqa: E402
    PARAMS,
    SETTLE,
    SID,
    UNREADABLE_LINES,
    _by_hand,
    _mark,
    _recorded,
    _refused,
    _settle,
    _trial,
)

from physgate.evaluation.tiers import exposure  # noqa: E402
from physgate.evaluation.tiers.exposure import ExposureError  # noqa: E402
from physgate.orchestrator import decomposition_review, dispatch  # noqa: E402
from physgate.orchestrator.decomposition_review import stop_left_review  # noqa: E402
from physgate.orchestrator.exceptions import RunStateError  # noqa: E402

__all__ = ["calls"]  # the fixture, used by name

ROLE = "control"


@pytest.fixture
def tier(tmp_path: Path, calls: Calls) -> Iterator[OnTier]:
    yield OnTier(tmp_path)


def _exposed_run(tier: OnTier, where: Path) -> Path:
    run = harness_run(where, tier.made.tasks["visible"][0], tier.made)
    incident_in(run)
    return run


def _stream(directory: Path, name: str = "stdout.jsonl") -> Path:
    return directory / "review" / SID / "session" / name


def _found(tier: OnTier) -> set[str]:
    return {v for f in exposure.found_exposures(tier.made.store, ROLE) for v in f.versions}


def _settle_refused(tier: OnTier, directory: Path) -> str:
    with pytest.raises(ExposureError) as refused:
        _settle(tier, directory)
    return str(refused.value.context.get("refused_because"))


def _lines(tier: OnTier) -> list[object]:
    return list(exposure.register_lines(tier.made.store, ROLE))


# --- the credential of a left review goes first -------------------------------------------------


def _left_with_a_credential(tier: OnTier, *, stream: str = CLEAN) -> tuple[Path, Path]:
    directory = _by_hand(tier, "cut", held_out=_recorded(tier), stream=stream)
    session = _stream(directory).parent
    (session / "state").mkdir()
    (session / "state" / "key").write_text("sk-a-credential")
    return directory, session


def test_a_left_review_whose_stream_reads_has_its_credential_removed_and_its_record_go(
    tier: OnTier,
) -> None:
    directory, session = _left_with_a_credential(tier)
    left = stop_left_review(directory)
    assert not (session / "state" / "key").exists()
    assert not (directory / REVIEW_RECORD).exists()
    assert left.said is not None and "credential files were removed" in left.said, left.said


@pytest.mark.parametrize("how", ["gone", "link"])
def test_a_left_review_whose_stream_cannot_be_read_has_its_credential_removed_all_the_same(
    tier: OnTier, how: str
) -> None:
    directory, session = _left_with_a_credential(tier)
    stream = _stream(directory)
    stream.unlink()
    if how == "link":
        stream.symlink_to(directory / "params_source.json")
    left = stop_left_review(directory)
    # Removed at this command, before the scan; the record is kept for what cannot be read.
    assert not (session / "state" / "key").exists(), "the credential stays on disk"
    assert (directory / REVIEW_RECORD).is_file()
    assert left.said is not None, left
    assert "credential files were removed" in left.said and "the record is kept" in left.said
    # And every later command says the same and finds nothing more on disk.
    again = stop_left_review(directory)
    assert again.said is not None and "credential files were removed" in again.said


def test_a_left_review_whose_credential_cannot_be_removed_is_still_scanned_and_kept(
    tier: OnTier,
) -> None:
    directory, session = _left_with_a_credential(tier, stream=tier.shown())
    # Its state directory is a link: nothing is removed through it, and the scan still runs.
    (session / "state" / "key").unlink()
    (session / "state").rmdir()
    elsewhere = directory.parent.parent / "elsewhere-state"
    elsewhere.mkdir()
    (elsewhere / "key").write_text("not the session's")
    (session / "state").symlink_to(elsewhere)
    left = stop_left_review(directory)
    assert left.exposed is True and (directory / EXPOSED_FILE).is_file()
    assert (directory / REVIEW_RECORD).is_file()
    assert (elsewhere / "key").read_text() == "not the session's"
    assert left.said is not None and "could not all be removed" in left.said, left.said


# --- every stream's refusal is kept --------------------------------------------------------------


def _two_streams(tier: OnTier, *, recorded: bool = True) -> tuple[Path, Path, Path]:
    directory = _by_hand(tier, "two", held_out=_recorded(tier) if recorded else None)
    record = json.loads((directory / REVIEW_RECORD).read_text())
    record["spawns"] = 2
    (directory / REVIEW_RECORD).write_text(json.dumps(record))
    first, second = _stream(directory), _stream(directory, "stdout-repair-1.jsonl")
    second.write_text(CLEAN)
    return directory, first, second


@pytest.mark.parametrize("order", ["gone after a link", "gone before a link"])
def test_a_gone_stream_is_an_exposure_whatever_another_stream_of_its_review_was_refused_for(
    tier: OnTier, order: str
) -> None:
    directory, first, second = _two_streams(tier)
    linked, gone = (first, second) if order == "gone after a link" else (second, first)
    gone.unlink()
    linked.unlink()
    linked.symlink_to(directory / "params_source.json")
    assert _readable(tier) == frozenset({tier.made.version})
    # Found, so nothing is left for a settle to pass over: it is refused, and the exposure stays.
    assert _settle_refused(tier, directory) == "settle_refuses_nothing"
    assert _found(tier) == {tier.made.version}


def test_a_review_whose_streams_are_refused_for_two_kinds_names_both(tier: OnTier) -> None:
    second_version(tier.made)
    directory, first, second = _two_streams(tier, recorded=False)
    second.unlink()
    first.unlink()
    first.symlink_to(directory / "params_source.json")
    said = str(_refused(tier))
    assert "a link or not a plain file" in said and "gone" in said, said


# --- what the live review's scan showed is on its record before its redaction ------------------


@pytest.mark.parametrize("line", UNREADABLE_LINES, ids=["not UTF-8", "a key twice"])
def test_a_line_the_live_review_counted_as_the_canary_stays_counted_once_its_stream_is_redacted(
    tier: OnTier, line: bytes
) -> None:
    directory = _by_hand(tier, "cut", held_out=_recorded(tier), stream=CLEAN.encode() + line)
    # The live review's own order: scanned, what it showed said on the record, then redacted;
    # killed before its round's end line.
    showed = getattr(decomposition_review, "review_showed", None)
    if showed is not None:
        showed(directory)(SID)
    dispatch.redact(_stream(directory), "sk-secret-not-there")
    assert line not in _stream(directory).read_bytes(), "the redaction kept the line"
    assert _readable(tier) == frozenset({tier.made.version})
    left = stop_left_review(directory, secrets=("sk-secret-not-there",))
    assert left.exposed is True and (directory / EXPOSED_FILE).is_file()
    assert _readable(tier) == frozenset({tier.made.version})


class SaysWhatItShowed(Recording):
    """A plan reviewer that says its scan showed a canary, redacts its stream, and is killed."""

    def __init__(self, line: bytes, root: Path) -> None:
        super().__init__(Stopped(), (SESSION, 4242, OTHER_START), stream=None, root=root)
        self.line = line
        self.shown: Callable[[str], None] | None = None

    def record_shown(self, hook: Callable[[str], None]) -> None:
        self.shown = hook

    def review_plan(self, under: object) -> object:
        if self.hook is not None:
            self.hook(*self.spawned)
        stream = self.root / SESSION / "session" / "stdout.jsonl" if self.root else Path()
        stream.parent.mkdir(parents=True, exist_ok=True)
        stream.write_bytes(CLEAN.encode() + self.line)
        if self.shown is not None:
            self.shown(SESSION)
        dispatch.redact(stream, "sk-secret-not-there")
        raise Stopped


@pytest.mark.parametrize("line", UNREADABLE_LINES, ids=["not UTF-8", "a key twice"])
def test_a_decompose_killed_after_its_review_redacted_what_it_showed_leaves_it_on_the_record(
    tier: OnTier, line: bytes
) -> None:
    with pytest.raises(Stopped):
        _exit(tier.args, SaysWhatItShowed(line, tier.review_root))
    assert (tier.run_dir / REVIEW_RECORD).is_file()
    assert _readable(tier) == frozenset({tier.made.version})
    left = stop_left_review(tier.run_dir, secrets=("sk-secret-not-there",))
    assert left.exposed is True
    assert _readable(tier) == frozenset({tier.made.version})


def test_what_a_review_showed_is_kept_on_its_record_when_it_is_spawned_again(
    tier: OnTier,
) -> None:
    directory = _by_hand(tier, "cut", held_out=_recorded(tier), record=False)
    root = directory / "review"
    spawned = decomposition_review.review_spawned(
        directory, review_root=root, canaries=tier.made.canaries
    )
    spawned(SID, 999_999, OTHER_START)
    decomposition_review.review_showed(directory)(SID)
    spawned(SID, 999_999, OTHER_START)  # its repair resume
    record = decomposition_review.review_record(directory)
    assert record is not None and record.shown and record.spawns == 2


def test_a_review_another_directory_holds_writes_nothing_here(tier: OnTier) -> None:
    directory = _by_hand(tier, "cut", held_out=_recorded(tier), record=False)
    decomposition_review.review_showed(directory)(SID)
    assert not (directory / REVIEW_RECORD).exists() and not (directory / EXPOSED_FILE).exists()
    assert _readable(tier) == frozenset()


def test_a_shown_review_whose_record_cannot_be_read_writes_the_exposure_file(
    tier: OnTier,
) -> None:
    directory = _by_hand(tier, "cut", held_out=_recorded(tier))
    (directory / REVIEW_RECORD).write_text("{")
    decomposition_review.review_showed(directory)(SID)
    assert (directory / EXPOSED_FILE).is_file()


# --- a settle is its own line, and marks no version ----------------------------------------------


def test_a_settle_marks_no_version_and_is_a_line_of_its_own(tier: OnTier) -> None:
    directory = _by_hand(tier, "old")
    (directory / REVIEW_RECORD).write_text("{")
    _refused(tier)
    _settle(tier, directory)
    (line,) = _lines(tier)
    fields = getattr(line, "model_dump", dict)()
    assert fields.get("kind") == "settle" and fields.get("by") == "a person", fields
    assert "version" not in fields and fields.get("date"), fields
    assert exposure.exposure_sources(tier.made.store, ROLE) == {}
    # Settled once, it refuses nothing: a second settle is refused.
    assert _settle_refused(tier, directory) == "settle_refuses_nothing"


def test_a_settle_of_a_directory_outside_every_run_root_is_refused(
    tier: OnTier, tmp_path: Path
) -> None:
    elsewhere = tmp_path / "not-a-run-root"
    elsewhere.mkdir()
    (elsewhere / "params_source.json").write_text("{")
    for named in (elsewhere, tier.runs):
        assert _settle_refused(tier, named) == "settle_outside_the_run_roots"
    assert _lines(tier) == []
    assert _readable(tier) == frozenset()


def test_a_settle_of_a_directory_the_register_refuses_nothing_in_is_refused(
    tier: OnTier,
) -> None:
    healthy = _by_hand(tier, "cut", held_out=_recorded(tier), stream=tier.shown())
    stream = _stream(healthy)
    stream.rename(healthy / "elsewhere.jsonl")
    stream.write_text(CLEAN)
    assert _settle_refused(tier, healthy) == "settle_refuses_nothing"
    # So a later stream that cannot be read, behind a link to the exposed bytes, still refuses.
    stream.unlink()
    stream.symlink_to(healthy / "elsewhere.jsonl")
    assert SETTLE in str(_refused(tier))
    assert _lines(tier) == []


def test_a_settle_of_a_link_or_of_what_is_no_directory_is_refused(tier: OnTier) -> None:
    directory = _by_hand(tier, "old")
    (directory / REVIEW_RECORD).write_text("{")
    (tier.runs / "linked").symlink_to(directory)
    (tier.runs / "a-file").write_text("x")
    for named in (tier.runs / "linked", tier.runs / "a-file", tier.runs / "missing"):
        assert _settle_refused(tier, named) == "settle_names_no_directory"
    assert _lines(tier) == []


def test_a_register_written_when_a_hand_mark_settled_a_directory_reads_as_it_did(
    tier: OnTier,
) -> None:
    directory = _by_hand(tier, "old")
    (directory / REVIEW_RECORD).write_text("{")
    _refused(tier)
    # The line a hand mark that settled a directory wrote: a hand exposure keyed by the
    # directory's identity.
    manifest = exposure.versions(tier.made.store, ROLE)[tier.made.version]
    old = {
        "kind": "exposure",
        "source": "hand",
        "key": exposure._settle_key(directory),  # noqa: SLF001 - the key the old line carries
        "by": "a person",
        "reason": "looked at the directory and marked what it may have shown",
        "date": "2026-11-20",
        "version": manifest.version,
        "held_out": manifest.held_out.sha256,
        "validation": manifest.validation.sha256,
    }
    exposure._append(exposure.withheld_root(tier.made.store, ROLE), "register", [old])  # noqa: SLF001
    # It still settles the directory, and still marks its version.
    assert _readable(tier) == frozenset({tier.made.version})


@pytest.mark.parametrize("second", ["a run", "a decomposition"])
def test_a_settle_of_one_directory_settles_no_other_that_refuses_alike(
    tier: OnTier, second: str
) -> None:
    def broken(name: str) -> Path:
        if second == "a decomposition":
            made = _by_hand(tier, name)
            (made / REVIEW_RECORD).write_text("{")
            return made
        run = harness_run(tier.runs / name, tier.made.tasks["visible"][0], tier.made)
        (run / "decomposition").mkdir()
        (run / JOURNAL).write_bytes(b"{not a line\n")
        return run

    one, other = broken("one"), broken("other")
    _settle(tier, one)
    assert SETTLE in str(_refused(tier))
    _settle(tier, other)
    assert _readable(tier) == frozenset()


# --- what the walk passes over is the decomposition's own, by place ------------------------------


@pytest.mark.parametrize("place", ["store", "worktrees", "review", "target"])
def test_a_run_at_the_top_of_a_place_a_decomposition_s_directory_passes_over_is_found(
    tier: OnTier, place: str
) -> None:
    directory = _by_hand(tier, "cut", held_out=_recorded(tier), stream=None, record=False)
    record = {"params": "/nowhere/params.json", "target": str(directory / "target")}
    (directory / "params_source.json").write_text(json.dumps(record))
    run = _exposed_run(tier, directory)
    assert _readable(tier) == frozenset({tier.made.version})
    # The place is the decomposition's own by its name or by its records; a run at its top is
    # still a run.
    run.rename(directory / place)
    assert _readable(tier) == frozenset({tier.made.version})


@pytest.mark.parametrize(
    "spelt", ["with dots", "naming the run root", "naming its parent", "naming /"]
)
def test_a_target_recorded_outside_the_directory_is_never_its_own(tier: OnTier, spelt: str) -> None:
    group = tier.runs / "round-1"
    _exposed_run(tier, group / "runs")
    target = {
        "with dots": str(group / "x" / ".." / "runs"),
        "naming the run root": str(tier.runs),
        "naming its parent": str(tier.runs.parent),
        "naming /": "/",
    }[spelt]
    record = {"params": "/nowhere/params.json", "target": target}
    (group / "params_source.json").write_text(json.dumps(record))
    assert _readable(tier) == frozenset({tier.made.version})


def test_a_review_root_recorded_outside_the_directory_is_never_its_own(
    tier: OnTier, tmp_path: Path
) -> None:
    group = tier.runs / "round-1"
    _exposed_run(tier, group / "review")
    (group / "params_source.json").write_text(PARAMS)
    (group / "review_root.json").write_text(
        json.dumps({"review_root": str(tmp_path / "elsewhere" / "review")})
    )
    assert _readable(tier) == frozenset({tier.made.version})


# --- decompose looks into a review root and a target given inside its run directory -------------


def _no_opening(trial: Path) -> None:
    assert not (trial / "params_source.json").exists(), "the command wrote its parameters"


def test_decompose_given_a_review_root_inside_its_directory_that_holds_a_run_is_refused(
    tier: OnTier, tmp_path: Path
) -> None:
    trial, args = _trial(tier, tmp_path)
    _exposed_run(tier, trial / "review")
    assert _exit(args, _passed()) == 2
    _no_opening(trial)


@pytest.mark.parametrize("record", ["run.json", "raw.json", "params_source.json"])
def test_decompose_given_a_target_inside_its_directory_that_holds_a_record_is_refused(
    tier: OnTier, tmp_path: Path, record: str
) -> None:
    trial, args = _trial(tier, tmp_path)
    # Where nothing checks the clone's work tree: beneath its git directory.
    (trial / "target" / ".git" / "old").mkdir(parents=True)
    (trial / "target" / ".git" / "old" / record).write_text("{}")
    assert _exit(args, _passed()) == 2
    _no_opening(trial)


def test_decompose_refuses_an_entry_named_as_an_input_that_lies_elsewhere(tier: OnTier) -> None:
    given = Path(tier.args[tier.args.index("--target") + 1])
    assert given.resolve().parent != tier.run_dir.resolve()
    _exposed_run(tier, tier.run_dir / given.name)
    assert _exit(tier.args, _passed()) == 2
    _no_opening(tier.run_dir)
    assert _readable(tier) == frozenset({tier.made.version})


def test_the_names_decompose_looks_for_are_the_ones_the_register_reads() -> None:
    from physgate.orchestrator.decompose import REGISTER_RECORDS

    named = {exposure.RUN_RECORD, exposure.RAW_RECORD, exposure.PARAMS_RECORD}
    assert named == REGISTER_RECORDS


def test_require_only_its_own_refuses_a_review_root_inside_that_holds_anything(
    tmp_path: Path,
) -> None:
    from physgate.orchestrator.decompose import require_only_its_own

    run_dir = tmp_path / "trial"
    (run_dir / "review" / "left").mkdir(parents=True)
    with pytest.raises(RunStateError):
        require_only_its_own(run_dir, given=[run_dir / "review"], review_root=run_dir / "review")
    (run_dir / "review" / "left").rmdir()
    require_only_its_own(run_dir, given=[run_dir / "review"], review_root=run_dir / "review")


# --- a void round's review is scanned before its record goes ------------------------------------


def test_a_review_that_ended_its_round_void_is_scanned_before_its_record_goes(
    tier: OnTier,
) -> None:
    raised = RunStateError("the review's place went away under it")
    reviewer = Recording(
        raised, (SESSION, 4242, OTHER_START), stream=tier.shown(), root=tier.review_root
    )
    with contextlib.suppress(RunStateError):  # how the command ends is not the point
        _exit(tier.args, reviewer)
    assert (tier.run_dir / EXPOSED_FILE).is_file()
    assert not (tier.run_dir / REVIEW_RECORD).exists()
    assert _readable(tier) == frozenset({tier.made.version})


def test_a_hand_mark_and_a_settle_together_mark_what_the_person_says(tier: OnTier) -> None:
    later = second_version(tier.made)
    directory = _by_hand(tier, "old")
    (directory / REVIEW_RECORD).write_text("{")
    _settle(tier, directory)
    _mark(tier, later.version)
    assert _readable(tier) == frozenset({later.version})
