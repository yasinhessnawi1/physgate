"""The exposure register reads a decomposition's directory by what the decomposition wrote there.

A directory with no run configuration is a decomposition's only by its parameters record, read
and valid. At one, the walk passes over only what a decomposition puts there (its own folder, the
run branch's checkout and store, the review root and the target it was given), and walks every
other entry, so a run beneath is found. A record that does not read refuses, naming no path.

Which versions a decomposition's exposure marks: the ones its recorded held-out tiers name, and
none where it recorded that it named none. One made before that record marks every version of
the role, and only on evidence that something showed. A review stream that is gone is gone; one
that is there and cannot be read refuses by its kind, and a person who looks settles it by hand:
a line of its own, which marks no version.

The register's scan, the next command's and the live review's read the same unredacted bytes, a
review resumed for its repair is seen running, and a review that raised is scanned before its
record goes.
"""

from __future__ import annotations

import json
import subprocess
import sys
import time
from collections.abc import Callable, Iterator
from pathlib import Path
from typing import Any

import pytest

EXPOSURE_TESTS = Path(__file__).resolve().parents[1] / "evaluation" / "exposure"
if str(EXPOSURE_TESTS) not in sys.path:
    sys.path.insert(0, str(EXPOSURE_TESTS))

from exposure_fixtures import (  # noqa: E402
    api,
    config,
    harness_run,
    incident_in,
    refusal,
    second_version,
)
from test_a_decompose_killed_in_its_plan_review_records_the_exposure_on_its_tier_version import (  # noqa: E402
    CLEAN,
    EXPOSED_FILE,
    HELD_OUT_RECORD,
    JOURNAL,
    REVIEW_RECORD,
    OnTier,
    _killed_in_its_review_showing,
    _passed,
    _readable,
    _scan,
)
from test_a_review_session_a_killed_decompose_left_is_stopped_by_the_next_command import (  # noqa: E402
    OTHER_START,
    SESSION,
    Recording,
)
from test_decompose_reviews_the_plan_before_it_writes_anything import (  # noqa: E402
    Calls,
    StandIn,
    Stopped,
    _exit,
    _verdict,
    calls,
)

from physgate.evaluation.tiers.exposure import ExposureError  # noqa: E402
from physgate.evaluation.tiers.heldout import tier_digest  # noqa: E402
from physgate.orchestrator import dispatch, processes  # noqa: E402
from physgate.orchestrator.decomposition_review import stop_left_review  # noqa: E402
from physgate.orchestrator.exceptions import InvocationError  # noqa: E402
from physgate.orchestrator.review_root_record import record_review_root  # noqa: E402

__all__ = ["calls"]  # the fixture, used by name

EXPOSURE = "physgate.evaluation.tiers.exposure"
ROLE = "control"
SID = "22222222-3333-4444-8555-666666666666"
PARAMS = json.dumps({"params": "/nowhere/params.json"})
#: A whole stream line that is not UTF-8, and one whose JSON names a key twice: neither can be read.
UNREADABLE_LINES = (
    b'{"type":"user","message":{"content":"caf\xe9"}}\n',
    b'{"type":"user","type":"assistant","message":{"content":"x"}}\n',
)


@pytest.fixture
def tier(tmp_path: Path, calls: Calls) -> Iterator[OnTier]:
    yield OnTier(tmp_path)


def _refused(tier: OnTier) -> ExposureError:
    with pytest.raises(ExposureError) as refused:
        tier.exposed()
    assert refused.value.context.get("refused_because") == "register_unreadable"
    # Named by its kind of place: no path beneath the run roots is said.
    assert str(tier.runs) not in str(refused.value), str(refused.value)
    return refused.value


def _exposed_run(tier: OnTier, where: Path) -> Path:
    run = harness_run(where, tier.made.tasks["visible"][0], tier.made)
    incident_in(run)
    return run


def _recorded(tier: OnTier) -> list[str]:
    return [tier_digest(Path(root)) for root in tier.made.held_out]


def _by_hand(
    tier: OnTier,
    name: str,
    *,
    record: bool = True,
    held_out: list[str] | None = None,
    stream: str | bytes | None = CLEAN,
    canaries: list[str] | None = None,
) -> Path:
    """A run-less decomposition's directory as a kill leaves one, its review root inside it."""
    directory = tier.runs / name
    (directory / "decomposition").mkdir(parents=True)
    (directory / "params_source.json").write_text(PARAMS)
    record_review_root(directory, directory / "review")
    session = directory / "review" / SID / "session"
    if stream is not None:
        session.mkdir(parents=True)
        data = stream if isinstance(stream, bytes) else stream.encode()
        (session / "stdout.jsonl").write_bytes(data)
    if record:
        body = {
            "session_id": SID,
            "pid": 999_999,
            "started": OTHER_START,
            "spawns": 1,
            "session_dir": str(session),
            "held_out_canaries": list(tier.made.canaries if canaries is None else canaries),
        }
        (directory / REVIEW_RECORD).write_text(json.dumps(body))
    if held_out is not None:
        (directory / HELD_OUT_RECORD).write_text(json.dumps({"held_out_sha256": held_out}))
    return directory


def _end_line(session: str | None = SID, *, cause: bool = True, mark: bool = True) -> bytes:
    """A round's end line of an exposed review, as the rounds write it, or with fields left out."""
    line: dict[str, Any] = {"kind": "round_ended"}
    if cause:
        line["ending"] = {"review_cause": "held_out_exposed"}
    review: dict[str, Any] = {}
    if mark:
        review["exposed"] = True
    if session is not None:
        review["session_id"] = session
    if review:
        line["review"] = review
    return (json.dumps(line) + "\n").encode()


def _settle(tier: OnTier, directory: Path) -> None:
    api(f"{EXPOSURE}.settle_directory")(
        tier.made.store,
        ROLE,
        directory,
        by="a person",
        reason="looked at the directory and found nothing it may have shown",
    )


def _mark(tier: OnTier, version: str) -> None:
    api(f"{EXPOSURE}.mark_exposed")(
        tier.made.store,
        ROLE,
        version,
        by="a person",
        reason="looked at the directory and marked what it may have shown",
    )


#: What a refusal a settle passes over names: the command that settles a directory.
SETTLE = "physgate tiers settle"


# --- the walk: a decomposition's directory is one by its parameters record, read --------------


def _folder(tier: OnTier, where: str) -> Path:
    return tier.runs if where == "root" else tier.runs / "round-1"


def test_a_parameters_record_that_does_not_read_refuses_and_names_no_path(tier: OnTier) -> None:
    folder = _folder(tier, "folder")
    _exposed_run(tier, folder / "a")
    (folder / "params_source.json").write_text("")
    _refused(tier)


@pytest.mark.parametrize("marker", ["", PARAMS], ids=["one that does not read", "one that reads"])
def test_a_run_root_is_never_a_decomposition_s_directory(tier: OnTier, marker: str) -> None:
    _exposed_run(tier, tier.runs / "decomposition")
    _exposed_run(tier, tier.runs / "x" / "y")
    (tier.runs / "params_source.json").write_text(marker)
    assert _readable(tier) == frozenset({tier.made.version})


@pytest.mark.parametrize("where", ["root", "folder"], ids=["at the run root", "in a folder"])
def test_a_parameters_record_that_reads_hides_no_run_beneath_its_directory(
    tier: OnTier, where: str
) -> None:
    folder = _folder(tier, where)
    _exposed_run(tier, folder / "a")
    _exposed_run(tier, folder / "x" / "y")
    (folder / "params_source.json").write_text(PARAMS)
    assert _readable(tier) == frozenset({tier.made.version})


@pytest.mark.parametrize("where", ["root", "folder"], ids=["at the run root", "in a folder"])
def test_a_bare_decomposition_directory_is_no_decomposition_s_and_hides_no_run(
    tier: OnTier, where: str
) -> None:
    folder = _folder(tier, where)
    _exposed_run(tier, folder / "a")
    (folder / "decomposition").mkdir(parents=True)
    assert _readable(tier) == frozenset({tier.made.version})


def test_a_raw_record_beside_a_parameters_record_is_read(tier: OnTier) -> None:
    trial = tier.runs / "raw-trial"
    trial.mkdir(parents=True)
    (trial / "raw.json").write_text(json.dumps({"held_out_seen": True, "held_out_sha256": []}))
    (trial / "params_source.json").write_text(PARAMS)
    assert _readable(tier) == frozenset({tier.made.version})


def test_an_exposed_run_beneath_a_killed_decomposition_s_directory_is_found(tier: OnTier) -> None:
    _killed_in_its_review_showing(tier, CLEAN)
    _exposed_run(tier, tier.run_dir / "later")
    assert _readable(tier) == frozenset({tier.made.version})


def test_the_review_root_inside_a_decomposition_s_directory_is_passed_over_and_a_run_beside_found(
    tier: OnTier,
) -> None:
    directory = _by_hand(tier, "measured", held_out=_recorded(tier))
    # Deeper than the walk's bound: walked into, it would refuse every reader.
    (directory / "review" / "a" / "b" / "c" / "d" / "e" / "f" / "g" / "h").mkdir(parents=True)
    assert _readable(tier) == frozenset()
    _exposed_run(tier, directory / "beside")
    assert _readable(tier) == frozenset({tier.made.version})


def test_a_measured_run_inside_a_decomposition_s_directory_is_refused_as_inside_a_run(
    tier: OnTier,
) -> None:
    _killed_in_its_review_showing(tier, CLEAN)
    told = refusal(config(tier.made.tasks["visible"][0], tier.made), tier.run_dir / "again")
    assert told is not None and "(run_inside_a_run)" in told, told


def test_decompose_refuses_a_run_directory_that_holds_what_is_not_its_own(tier: OnTier) -> None:
    _exposed_run(tier, tier.run_dir / "earlier")
    assert _exit(tier.args, _passed()) == 2
    assert not (tier.run_dir / "params_source.json").exists()
    assert not (tier.run_dir / "run.json").exists()
    assert _readable(tier) == frozenset({tier.made.version})


def _trial(tier: OnTier, tmp_path: Path) -> tuple[Path, list[str]]:
    """The round driver's layout: the target's clone and the review root made before decompose."""
    trial = tier.runs / "round-a" / "0001-0"
    trial.mkdir(parents=True)
    given = Path(tier.args[tier.args.index("--target") + 1])
    target = trial / "target"
    subprocess.run(
        ["git", "clone", "--quiet", "--no-hardlinks", "--", str(given), str(target)], check=True
    )
    # Deeper than the walk's bound, as a real clone's history can be.
    (target / ".git" / "deep" / "a" / "b" / "c" / "d" / "e").mkdir(parents=True)
    (trial / "review").mkdir()
    args = list(tier.args)
    args[args.index("--target") + 1] = str(target)
    args[args.index("--run-dir") + 1] = str(trial)
    args[args.index("--review-root") + 1] = str(trial / "review")
    return trial, args


def test_a_trial_prepared_with_its_target_s_clone_is_read_without_walking_the_clone(
    tier: OnTier, tmp_path: Path
) -> None:
    trial, args = _trial(tier, tmp_path)
    reviewer = Recording(
        Stopped(), (SESSION, 4242, OTHER_START), stream=CLEAN, root=(trial / "review").resolve()
    )
    with pytest.raises(Stopped):
        _exit(args, reviewer)
    assert (trial / "params_source.json").is_file()
    # The clone is the decomposition's own, named by the record it wrote first: not walked.
    assert _readable(tier) == frozenset()
    # And a run lying beside it is found.
    _exposed_run(tier, trial / "beside")
    assert _readable(tier) == frozenset({tier.made.version})


def test_decompose_takes_a_trial_directory_holding_only_its_target_and_review_root(
    tier: OnTier, tmp_path: Path
) -> None:
    trial, args = _trial(tier, tmp_path)
    assert _exit(args, _passed()) == 0
    assert (trial / "run.json").is_file()


# --- which versions a decomposition's exposure marks ---------------------------------------------


def test_a_decompose_that_named_no_held_out_tier_marks_nothing_whatever_its_stream(
    tier: OnTier,
) -> None:
    second_version(tier.made)
    directory = _by_hand(tier, "development", held_out=[], stream=None, canaries=[])
    (directory / EXPOSED_FILE).write_text(json.dumps({"session_id": SID}))
    assert _readable(tier) == frozenset()


def test_a_decomposition_whose_recorded_tiers_name_no_version_of_the_role_marks_nothing(
    tier: OnTier,
) -> None:
    directory = _by_hand(tier, "other-role", held_out=["f" * 64])
    (directory / EXPOSED_FILE).write_text(json.dumps({"session_id": SID}))
    assert _readable(tier) == frozenset()


def test_a_decomposition_s_gone_stream_marks_only_the_versions_it_recorded(tier: OnTier) -> None:
    later = second_version(tier.made)
    _by_hand(tier, "recorded", held_out=_recorded(tier), stream=None)
    assert _readable(tier) == frozenset({tier.made.version})
    assert later.version != tier.made.version


@pytest.mark.parametrize("evidence", ["stream", "file", "journal"])
def test_a_decomposition_from_before_the_held_out_record_marks_every_version_on_evidence(
    tier: OnTier, evidence: str
) -> None:
    later = second_version(tier.made)
    shown = tier.shown() if evidence == "stream" else CLEAN
    directory = _by_hand(tier, "old", stream=shown)
    if evidence == "file":
        (directory / EXPOSED_FILE).write_text(json.dumps({"session_id": SID}))
    if evidence == "journal":
        (directory / JOURNAL).write_bytes(_end_line())
    assert _readable(tier) == frozenset({tier.made.version, later.version})


def test_a_clean_decomposition_from_before_the_held_out_record_marks_nothing(
    tier: OnTier,
) -> None:
    _by_hand(tier, "old")
    assert _readable(tier) == frozenset()


def test_a_stream_gone_where_no_held_out_tiers_were_recorded_refuses_by_its_kind(
    tier: OnTier,
) -> None:
    second_version(tier.made)
    _by_hand(tier, "old", stream=None)
    assert "gone" in str(_refused(tier))


def _not_plain(directory: Path, how: str, monkeypatch: pytest.MonkeyPatch) -> str:
    """Make the review's stream one that is there and cannot be read; the kind the words name."""
    session = directory / "review" / SID / "session"
    stream = session / "stdout.jsonl"
    elsewhere = directory.parent.parent / f"elsewhere-{directory.name}"
    elsewhere.mkdir()
    if how == "link":
        (elsewhere / "stdout.jsonl").write_text(CLEAN)
        stream.unlink()
        stream.symlink_to(elsewhere / "stdout.jsonl")
        return "a link or not a plain file"
    if how == "directory":
        stream.unlink()
        stream.mkdir()
        return "a link or not a plain file"
    if how == "linked directory":
        (elsewhere / "stdout.jsonl").write_text(CLEAN)
        stream.unlink()
        session.rmdir()
        session.symlink_to(elsewhere)
        return "a directory on its way"
    monkeypatch.setattr(dispatch, "MAX_SESSION_FILE_BYTES", 10)
    return "over the size bound"


@pytest.mark.parametrize("recorded", [True, False], ids=["tiers recorded", "none recorded"])
@pytest.mark.parametrize("how", ["link", "directory", "linked directory", "too large"])
def test_a_review_stream_that_is_there_and_cannot_be_read_refuses_by_its_kind(
    tier: OnTier, monkeypatch: pytest.MonkeyPatch, how: str, recorded: bool
) -> None:
    directory = _by_hand(tier, "old", held_out=_recorded(tier) if recorded else None)
    kind = _not_plain(directory, how, monkeypatch)
    assert kind in str(_refused(tier))


# --- a person settles a directory that refuses -------------------------------------------------


def _unreadable_params(tier: OnTier, directory: Path) -> None:
    (directory / "params_source.json").write_text("{")


def _unreadable_review(tier: OnTier, directory: Path) -> None:
    (directory / REVIEW_RECORD).write_text('{"session_id": "s", "pid"')


def _unreadable_held_out(tier: OnTier, directory: Path) -> None:
    (directory / HELD_OUT_RECORD).write_text("{")


def _unreadable_journal(tier: OnTier, directory: Path) -> None:
    (directory / JOURNAL).write_bytes(b"{not a line\n")


def _linked_stream(tier: OnTier, directory: Path) -> None:
    stream = directory / "review" / SID / "session" / "stdout.jsonl"
    stream.unlink()
    stream.symlink_to(directory / "params_source.json")


def _gone_stream(tier: OnTier, directory: Path) -> None:
    (directory / "review" / SID / "session" / "stdout.jsonl").unlink()


SETTLED: dict[str, Callable[[OnTier, Path], None]] = {
    "a parameters record": _unreadable_params,
    "a review record": _unreadable_review,
    "a held-out record": _unreadable_held_out,
    "a journal line": _unreadable_journal,
    "a stream that is a link": _linked_stream,
    "a stream gone with no tiers recorded": _gone_stream,
}


@pytest.mark.parametrize("broken", list(SETTLED), ids=list(SETTLED))
def test_a_person_who_settles_a_refusing_directory_by_hand_makes_the_store_usable_again(
    tier: OnTier, broken: str
) -> None:
    directory = _by_hand(tier, "old")
    SETTLED[broken](tier, directory)
    said = str(_refused(tier))
    # The words say what a person does.
    assert SETTLE in said, said
    later = tier.later_refusal()
    assert later is not None and "(register_unreadable)" in later, later
    _settle(tier, directory)
    # The settle marks no version: the store reads, and nothing is exposed until a person marks.
    assert _readable(tier) == frozenset()
    assert _scan(tier) == (0, 0)
    later = tier.later_refusal()
    assert later is None or "(register_unreadable)" not in later, later
    _mark(tier, tier.made.version)
    later = tier.later_refusal()
    assert later is not None and "(version_exposed)" in later, later


def test_a_run_whose_journal_does_not_read_is_settled_by_hand_too(tier: OnTier) -> None:
    run = harness_run(tier.runs / "a", tier.made.tasks["visible"][0], tier.made)
    (run / "decomposition").mkdir()
    (run / JOURNAL).write_bytes(b"{not a line\n")
    assert SETTLE in str(_refused(tier))
    _settle(tier, run)
    assert _readable(tier) == frozenset()


def test_a_settle_names_its_path_only_where_a_person_reads_it(tier: OnTier) -> None:
    directory = _by_hand(tier, "old")
    _unreadable_review(tier, directory)
    _settle(tier, directory)
    register = (tier.made.store / ROLE / "withheld" / "register.jsonl").read_text()
    (line,) = [json.loads(text) for text in register.splitlines()]
    # Said for a person, beside the key; the rest of the line, its key among it, names no path.
    said = {line.pop("given_path"), line.pop("resolved_path")}
    assert said == {str(directory), str(directory.resolve())}, said
    rest = json.dumps(line)
    assert str(tier.runs) not in rest
    assert directory.name not in rest


def test_a_process_table_that_cannot_be_read_refuses_until_it_answers(
    tier: OnTier, monkeypatch: pytest.MonkeyPatch
) -> None:
    _killed_in_its_review_showing(tier, CLEAN)

    def unreadable(*_: Any) -> bool:  # noqa: ANN401
        msg = "ps could not be run"
        raise processes.ProcessTableError(msg)

    monkeypatch.setattr(processes, "is_session", unreadable)
    assert "process table" in str(_refused(tier))
    monkeypatch.setattr(processes, "is_session", lambda *_: False)
    assert _readable(tier) == frozenset()


# --- the same bytes, read alike --------------------------------------------------------------


@pytest.mark.parametrize("line", UNREADABLE_LINES, ids=["not UTF-8", "a key twice"])
def test_what_the_register_counts_in_a_left_review_the_next_command_counts_too(
    tier: OnTier, line: bytes
) -> None:
    _killed_in_its_review_showing(tier, CLEAN)
    stream = tier.review_root / SESSION / "session" / "stdout.jsonl"
    stream.write_bytes(CLEAN.encode() + line)
    assert _readable(tier) == frozenset({tier.made.version})
    # Every real command holds a credential, and redacts the stream: after its own scan.
    left = stop_left_review(tier.run_dir, secrets=("some-credential",))
    assert left.exposed is True
    assert (tier.run_dir / EXPOSED_FILE).is_file()
    assert _readable(tier) == frozenset({tier.made.version})


def _napping(flag: str, session: str) -> subprocess.Popen[bytes]:
    nap = "import time; time.sleep(30)"
    return subprocess.Popen([sys.executable, "-c", nap, "--model", "m", flag, session])


def test_a_review_session_resumed_for_its_repair_is_seen_running() -> None:
    first, again = _napping("--session-id", SID), _napping("--resume", SID)
    try:
        time.sleep(0.3)
        for one in (first, again):
            assert processes.is_session(one.pid, processes.started_at(one.pid), SID) is True
        # Another session's id is not this one.
        assert processes.is_session(again.pid, processes.started_at(again.pid), SESSION) is False
    finally:
        for one in (first, again):
            one.kill()
            one.wait()


def test_a_live_repair_resume_s_unfinished_line_is_read_once_whole(tier: OnTier) -> None:
    resumed = _napping("--resume", SID)
    try:
        time.sleep(0.3)
        directory = _by_hand(tier, "live", held_out=_recorded(tier))
        record = json.loads((directory / REVIEW_RECORD).read_text())
        record.update(pid=resumed.pid, started=processes.started_at(resumed.pid), spawns=2)
        (directory / REVIEW_RECORD).write_text(json.dumps(record))
        repair = directory / "review" / SID / "session" / "stdout-repair-1.jsonl"
        repair.write_bytes(CLEAN.encode() + "é".encode()[:1])
        assert _readable(tier) == frozenset()
    finally:
        resumed.kill()
        resumed.wait()
    # Ended, its cut last line is final: it cannot be read, so it counts as the canary.
    assert _readable(tier) == frozenset({tier.made.version})


# --- a review that raised is scanned before its record goes ------------------------------------


def test_a_review_that_showed_the_canary_and_then_raised_is_found_and_refuses_the_next_command(
    tier: OnTier,
) -> None:
    raised = InvocationError("the review's end could not be read", session_id=SESSION)
    reviewer = Recording(
        raised, (SESSION, 4242, OTHER_START), stream=tier.shown(), root=tier.review_root
    )
    _exit(tier.args, reviewer)
    assert "invocation_error" in (tier.run_dir / JOURNAL).read_text()
    assert (tier.run_dir / EXPOSED_FILE).is_file()
    assert _readable(tier) == frozenset({tier.made.version})
    assert _exit(tier.args, StandIn(_verdict())) == 2
    assert _readable(tier) == frozenset({tier.made.version})


def test_a_review_that_raised_with_its_stream_gone_keeps_its_record_and_is_counted(
    tier: OnTier,
) -> None:
    raised = InvocationError("the stream of the review is gone", session_id=SESSION)
    reviewer = Recording(raised, (SESSION, 4242, OTHER_START), stream=None, root=tier.review_root)
    _exit(tier.args, reviewer)
    assert (tier.run_dir / REVIEW_RECORD).is_file()
    assert _readable(tier) == frozenset({tier.made.version})


def test_a_review_that_raised_with_a_clean_stream_leaves_nothing_behind(tier: OnTier) -> None:
    raised = InvocationError("the review's end could not be read", session_id=SESSION)
    reviewer = Recording(raised, (SESSION, 4242, OTHER_START), stream=CLEAN, root=tier.review_root)
    _exit(tier.args, reviewer)
    assert not (tier.run_dir / REVIEW_RECORD).exists()
    assert not (tier.run_dir / EXPOSED_FILE).exists()
    assert _readable(tier) == frozenset()


# --- the journal, the exposure file and the keys -----------------------------------------------


def test_an_exposure_file_whose_session_cannot_be_read_is_still_an_exposure(tier: OnTier) -> None:
    directory = _by_hand(tier, "old", held_out=_recorded(tier))
    (directory / EXPOSED_FILE).write_text(json.dumps({"not": "a session"}))
    assert _readable(tier) == frozenset({tier.made.version})


@pytest.mark.parametrize(
    ("cause", "mark"), [(True, False), (False, True)], ids=["its cause alone", "its mark alone"]
)
def test_an_end_line_saying_exposed_either_way_is_an_exposure(
    tier: OnTier, cause: bool, mark: bool
) -> None:
    directory = _by_hand(tier, "old", held_out=_recorded(tier))
    (directory / JOURNAL).write_bytes(_end_line(cause=cause, mark=mark))
    assert _readable(tier) == frozenset({tier.made.version})


def test_an_end_line_naming_no_session_is_an_exposure(tier: OnTier) -> None:
    directory = _by_hand(tier, "old", held_out=_recorded(tier), record=False)
    (directory / JOURNAL).write_bytes(_end_line(None))
    assert _readable(tier) == frozenset({tier.made.version})


def test_two_exposed_reviews_of_one_decomposition_are_two_exposures(tier: OnTier) -> None:
    directory = _by_hand(tier, "old", held_out=_recorded(tier), record=False)
    (directory / JOURNAL).write_bytes(_end_line("a") + _end_line("b"))
    assert _scan(tier) == (2, 0)


def test_a_started_run_s_journal_exposure_marks_only_the_versions_it_recorded(
    tier: OnTier,
) -> None:
    run = harness_run(tier.runs / "a", tier.made.tasks["visible"][0], tier.made)
    later = second_version(tier.made)
    (run / "decomposition").mkdir()
    (run / JOURNAL).write_bytes(_end_line())
    assert _readable(tier) == frozenset({tier.made.version})
    assert later.version not in _readable(tier)


def test_a_started_run_s_incident_is_its_one_exposure_whatever_its_journal_says(
    tier: OnTier,
) -> None:
    run = _exposed_run(tier, tier.runs / "a")
    (run / "decomposition").mkdir()
    (run / JOURNAL).write_bytes(_end_line())
    (run / "params_source.json").write_text(PARAMS)
    (run / EXPOSED_FILE).write_text(json.dumps({"session_id": SID}))
    assert _scan(tier) == (1, 0)


# --- a finished review's stream is scanned once ------------------------------------------------


def test_a_finished_review_s_stream_is_scanned_once_and_its_result_kept(
    tier: OnTier, monkeypatch: pytest.MonkeyPatch
) -> None:
    from physgate.orchestrator import decomposition_review  # noqa: PLC0415

    _by_hand(tier, "clean", held_out=_recorded(tier))
    shown = _by_hand(tier, "shown", held_out=_recorded(tier), stream=tier.shown())
    real = decomposition_review.shown_in
    scans: list[int] = []

    def counted(*args: Any, **kwargs: Any) -> bool:  # noqa: ANN401
        scans.append(1)
        return bool(real(*args, **kwargs))

    monkeypatch.setattr(decomposition_review, "shown_in", counted)
    assert _readable(tier) == frozenset({tier.made.version})
    assert len(scans) == 2
    assert _readable(tier) == frozenset({tier.made.version})
    assert len(scans) == 2, "a finished review's stream was scanned again"
    # A stream whose bytes change is scanned again.
    (shown / "review" / SID / "session" / "stdout.jsonl").write_text(CLEAN * 2)
    assert _readable(tier) == frozenset()
    assert len(scans) == 3


def test_the_register_s_kept_scans_lie_beside_it_and_a_bad_one_is_scanned_again(
    tier: OnTier,
) -> None:
    _by_hand(tier, "shown", held_out=_recorded(tier), stream=tier.shown())
    assert _readable(tier) == frozenset({tier.made.version})
    kept = tier.made.store / ROLE / "withheld" / "scans"
    entries = sorted(kept.iterdir())
    assert len(entries) == 1
    entries[0].write_text("clean, says someone\n")
    assert _readable(tier) == frozenset({tier.made.version})


def test_the_kept_scan_is_not_written_where_the_check_says_nothing_is(
    tier: OnTier, monkeypatch: pytest.MonkeyPatch
) -> None:
    from physgate.evaluation.tiers import exposure  # noqa: PLC0415

    monkeypatch.setattr(exposure, "KEEP_SCANS", False)
    _by_hand(tier, "shown", held_out=_recorded(tier), stream=tier.shown())
    assert _readable(tier) == frozenset({tier.made.version})
    assert not (tier.made.store / ROLE / "withheld" / "scans").exists()


def test_a_decomposition_s_folder_this_user_cannot_search_refuses_by_its_kind(tier: OnTier) -> None:
    directory = _by_hand(tier, "old", held_out=_recorded(tier))
    (directory / "decomposition").chmod(0o000)
    try:
        assert "cannot be read" in str(_refused(tier))
        _settle(tier, directory)
        assert _readable(tier) == frozenset()
    finally:
        (directory / "decomposition").chmod(0o700)


def test_a_settled_directory_whose_parameters_record_does_not_read_is_not_walked(
    tier: OnTier,
) -> None:
    # The round driver's layout: the target's clone in the directory, its refs deeper than the
    # walk's bound beneath the run roots; and its parameters record cannot be read.
    directory = _by_hand(tier, "round-1/0000-1")
    (directory / "target" / ".git" / "refs" / "a" / "b" / "c" / "d" / "e" / "f").mkdir(parents=True)
    _unreadable_params(tier, directory)
    said = str(_refused(tier))
    assert SETTLE in said and "moved out of it" in said, said
    _settle(tier, directory)
    assert _readable(tier) == frozenset()
    later = tier.later_refusal()
    assert later is None or "(register_unreadable)" not in later, later


def test_a_settled_directory_whose_parameters_record_does_not_read_still_shows_what_it_showed(
    tier: OnTier,
) -> None:
    later = second_version(tier.made)
    directory = _by_hand(tier, "old", held_out=_recorded(tier))
    (directory / EXPOSED_FILE).write_text(json.dumps({"session_id": "an-earlier-review"}))
    _unreadable_params(tier, directory)
    _refused(tier)
    _settle(tier, directory)
    _mark(tier, later.version)
    assert _readable(tier) == frozenset({tier.made.version, later.version})


def test_a_decomposition_s_directory_that_cannot_be_searched_refuses_until_it_can_be(
    tier: OnTier, monkeypatch: pytest.MonkeyPatch
) -> None:
    from physgate.orchestrator import design_rounds  # noqa: PLC0415

    directory = _by_hand(tier, "old", held_out=_recorded(tier))
    real = design_rounds.exposed_reviews

    def refused(run_dir: Path) -> tuple[str, ...]:
        # A read the filesystem refuses in a way no step of the register's read expects.
        msg = "Input/output error"
        raise OSError(5, msg)

    monkeypatch.setattr(design_rounds, "exposed_reviews", refused)
    said = str(_refused(tier))
    assert "cannot be searched" in said and "readable to this user again" in said, said
    assert SETTLE not in said, said
    # A settle does not pass over it, as the words say: what the read found would be lost with
    # it. So the settle is refused, and nothing is written.
    with pytest.raises(ExposureError) as settling:
        _settle(tier, directory)
    assert settling.value.context.get("refused_because") == "settle_refuses_nothing"
    assert "cannot be searched" in str(_refused(tier))
    # The act its words name clears it: the directory reads again.
    monkeypatch.setattr(design_rounds, "exposed_reviews", real)
    assert _readable(tier) == frozenset()
    later = tier.later_refusal()
    assert later is None or "(register_unreadable)" not in later, later


def test_a_settled_directory_keeps_what_it_showed_when_a_later_step_cannot_be_read(
    tier: OnTier, monkeypatch: pytest.MonkeyPatch
) -> None:
    from physgate.orchestrator import decomposition_review  # noqa: PLC0415

    later = second_version(tier.made)
    directory = _by_hand(tier, "old", held_out=_recorded(tier))
    (directory / EXPOSED_FILE).write_text(json.dumps({"session_id": "an-earlier-review"}))

    def unreadable(run_dir: Path) -> None:
        msg = "Permission denied"
        raise PermissionError(13, msg)

    monkeypatch.setattr(decomposition_review, "review_record", unreadable)
    assert "cannot be read" in str(_refused(tier))
    # The person settles it and marks the later version; what it showed still marks its own.
    _settle(tier, directory)
    _mark(tier, later.version)
    assert _readable(tier) == frozenset({tier.made.version, later.version})


def test_a_canary_a_scan_showed_marks_its_version_where_its_result_cannot_be_kept(
    tier: OnTier,
) -> None:
    _by_hand(tier, "shown", held_out=_recorded(tier), stream=tier.shown())
    withheld = tier.made.store / ROLE / "withheld"
    withheld.chmod(0o500)
    try:
        assert _readable(tier) == frozenset({tier.made.version})
        assert not (withheld / "scans").exists()
    finally:
        withheld.chmod(0o700)


# --- a settle mark holds for what was settled, not for where it lay ---------------------------


def _moved_and_made_again(tier: OnTier, directory: Path) -> None:
    directory.rename(tier.runs.parent / "moved-out-of-the-run-roots")
    again = _by_hand(tier, directory.name)
    _unreadable_review(tier, again)


def _decomposed_afresh_in_place(tier: OnTier, directory: Path) -> None:
    # A later decomposition into the same directory writes its parameters record afresh, apart
    # and renamed into place, as every decomposition writes it: the same bytes, another file.
    fresh = directory / ".params_source.json.part"
    fresh.write_bytes((directory / "params_source.json").read_bytes())
    fresh.replace(directory / "params_source.json")


@pytest.mark.parametrize(
    "replaced",
    [_moved_and_made_again, _decomposed_afresh_in_place],
    ids=["moved away and another made there", "decomposed afresh in place"],
)
def test_a_settled_directory_replaced_at_its_path_by_another_refuses_again(
    tier: OnTier, replaced: Callable[[OnTier, Path], None]
) -> None:
    directory = _by_hand(tier, "old")
    _unreadable_review(tier, directory)
    _settle(tier, directory)
    assert _readable(tier) == frozenset()
    replaced(tier, directory)
    assert SETTLE in str(_refused(tier))


def test_a_settled_directory_stays_settled_when_an_unrelated_file_beside_it_changes(
    tier: OnTier,
) -> None:
    directory = _by_hand(tier, "old")
    _unreadable_review(tier, directory)
    _settle(tier, directory)
    (directory / "notes.txt").write_text("a note a person left")
    (tier.runs / "notes.txt").write_text("another")
    (directory / "decomposition" / "notes.txt").write_text("and one more")
    assert _readable(tier) == frozenset()


def test_a_settle_mark_keyed_by_the_directory_s_path_alone_is_not_honoured(
    tier: OnTier, monkeypatch: pytest.MonkeyPatch
) -> None:
    import hashlib  # noqa: PLC0415
    import os  # noqa: PLC0415

    from physgate.evaluation.tiers import exposure  # noqa: PLC0415

    directory = _by_hand(tier, "old")
    _unreadable_review(tier, directory)

    def by_path(where: Path) -> str:
        return hashlib.sha256(f"settled\0{os.path.realpath(where)}".encode()).hexdigest()

    # A mark made as a settle mark was first keyed: by the directory's real path alone.
    with monkeypatch.context() as patch:
        patch.setattr(exposure, "_settle_key", by_path)
        _settle(tier, directory)
    assert SETTLE in str(_refused(tier))


@pytest.mark.parametrize("record", ["run.json", "raw.json"])
def test_a_settle_never_passes_over_a_run_nested_in_a_directory_whose_parameters_record_is_torn(
    tier: OnTier, record: str
) -> None:
    # Settled, every entry of such a directory but one holding a run at its own top is passed
    # over: a run two levels down would be read by nobody afterwards.
    directory = _by_hand(tier, "torn", held_out=_recorded(tier))
    nested = directory / "kept" / "inner"
    if record == "run.json":
        nested = harness_run(nested, tier.made.tasks["visible"][0], tier.made)
        incident_in(nested)
    else:
        nested.mkdir(parents=True)
        (nested / "raw.json").write_text("{}\n")
    _unreadable_params(tier, directory)
    _refused(tier)
    with pytest.raises(ExposureError) as settling:
        _settle(tier, directory)
    assert settling.value.context.get("refused_because") == "settle_passes_over_a_run"
    named = str(nested.relative_to(directory) / record)
    assert named in str(settling.value), str(settling.value)
    # Nothing was written: the register refuses the directory as before.
    _refused(tier)


@pytest.mark.parametrize("at_its_name", ["a link", "a directory"])
def test_a_settle_looks_beneath_whatever_stands_at_the_run_record_s_name_but_a_run_s_own(
    tier: OnTier, at_its_name: str
) -> None:
    # The walk reads a directory as a run only where its configuration is a plain file, no link:
    # anything else at that name leaves the directory read by its torn parameters record.
    directory = _by_hand(tier, "torn", held_out=_recorded(tier))
    nested = harness_run(directory / "kept" / "inner", tier.made.tasks["visible"][0], tier.made)
    incident_in(nested)
    if at_its_name == "a link":
        (directory / "run.json").symlink_to(nested / "run.json")
    else:
        (directory / "run.json").mkdir()
    _unreadable_params(tier, directory)
    _refused(tier)
    with pytest.raises(ExposureError) as settling:
        _settle(tier, directory)
    assert settling.value.context.get("refused_because") == "settle_passes_over_a_run"
    # Named like a run's record, whatever its type: the thing at the top's name, the run beneath.
    said = str(settling.value)
    assert "run.json" in said and str(nested.relative_to(directory) / "run.json") in said, said


def test_a_settle_the_register_would_still_refuse_once_settled_is_never_recorded(
    tier: OnTier, monkeypatch: pytest.MonkeyPatch
) -> None:
    # Torn, it refuses by a kind a settle passes over; settled, it would still refuse, since a
    # place in it cannot be searched: no line is written that would settle nothing.
    from physgate.evaluation.tiers.exposure import register_lines  # noqa: PLC0415
    from physgate.orchestrator import design_rounds  # noqa: PLC0415

    directory = _by_hand(tier, "old", held_out=_recorded(tier))
    _unreadable_params(tier, directory)

    def refused(run_dir: Path) -> tuple[str, ...]:
        msg = "Input/output error"
        raise OSError(5, msg)

    monkeypatch.setattr(design_rounds, "exposed_reviews", refused)
    before = len(register_lines(tier.made.store, "control"))
    with pytest.raises(ExposureError) as settling:
        _settle(tier, directory)
    assert settling.value.context.get("refused_because") == "settle_refuses_nothing"
    assert "would still refuse" in str(settling.value), str(settling.value)
    assert len(register_lines(tier.made.store, "control")) == before
