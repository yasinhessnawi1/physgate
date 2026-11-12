"""On 2.1.322 each session's flag cache is recorded and its changes counted; none halts a run.

Sessions on 2.1.322 fetch the remote feature flags, and the binary keeps them in its
configuration directory. Measured against the real API (12.11.2026): the cache is there after
the first session in a fresh directory, and it differs between two sessions minutes apart with
nothing of the run's changed. A run halted on that would never finish. So each session's cache is
recorded as a count and a digest, never a flag's name or value; the run's record counts how
often it changed from one reading to the next; and no change in it halts anything.

What still halts a run is what it halted on before: another served-catalog state than the run
began with, and other policy limits than the decomposition call received.

Sessions on the earlier pins fetch no flags and leave no cache: nothing is read, and their
records are written byte for byte as before.
"""

from __future__ import annotations

import hashlib
import json
import stat
import sys
from pathlib import Path

import pytest
from loop_fakes import FakeDispatcher, Rig, plan, usage
from orch_helpers import SCRIPTED_BOUNDS, make_config

import physgate.orchestrator.decompose as decompose
from physgate.orchestrator.credentials import Credential
from physgate.orchestrator.events import (
    Halted,
    Incident,
    Merged,
    ReviewRan,
    SessionEnded,
    flag_cache_readings,
    read_events,
)
from physgate.orchestrator.managed import (
    FlagCache,
    FlagDrift,
    ObservedTraffic,
    SessionManaged,
    flag_cache,
    flag_drift,
)
from physgate.orchestrator.protocols import MessageUsage, ReviewResult
from physgate.orchestrator.record import DecompositionSummary

FLAGS = {"tengu_b": {"value": True, "source": "remote"}, "tengu_a": 3, "tengu_c": [1, "x"]}


def _digest(flags: object) -> str:
    """As the measurement took it: the cache as JSON, its keys sorted."""
    return hashlib.sha256(json.dumps(flags, sort_keys=True).encode()).hexdigest()


def _left(config: Path, state: object) -> Path:
    config.mkdir(parents=True, exist_ok=True)
    (config / ".claude.json").write_text(json.dumps(state))
    return config


def test_the_cache_is_read_as_a_count_and_the_digest_of_its_sorted_json(tmp_path: Path) -> None:
    config = _left(tmp_path / "c", {"cachedGrowthBookFeatures": FLAGS, "userID": "u-1"})
    assert flag_cache(config) == FlagCache(entries=3, sha256=_digest(FLAGS))


def test_the_order_the_binary_wrote_the_flags_in_is_no_difference(tmp_path: Path) -> None:
    turned = dict(reversed(list(FLAGS.items())))
    assert list(turned) != list(FLAGS)
    first = flag_cache(_left(tmp_path / "a", {"cachedGrowthBookFeatures": FLAGS}))
    second = flag_cache(_left(tmp_path / "b", {"cachedGrowthBookFeatures": turned}))
    assert first is not None and first == second


@pytest.mark.parametrize(
    "other",
    [
        {**FLAGS, "tengu_a": 4},
        {**FLAGS, "tengu_d": False},
        {k: v for k, v in FLAGS.items() if k != "tengu_c"},
        {**FLAGS, "tengu_b": {"value": True, "source": "cache"}},
    ],
    ids=["a value", "a flag more", "a flag fewer", "a value inside a flag"],
)
def test_any_difference_in_the_flags_is_another_digest(tmp_path: Path, other: object) -> None:
    first = flag_cache(_left(tmp_path / "a", {"cachedGrowthBookFeatures": FLAGS}))
    second = flag_cache(_left(tmp_path / "b", {"cachedGrowthBookFeatures": other}))
    assert first is not None and second is not None
    assert first.sha256 != second.sha256


def test_nothing_else_of_the_file_reaches_the_reading(tmp_path: Path) -> None:
    state = {"cachedGrowthBookFeatures": FLAGS, "oauthAccount": {"emailAddress": "a@b.example"}}
    plain = flag_cache(_left(tmp_path / "a", {"cachedGrowthBookFeatures": FLAGS}))
    beside = flag_cache(_left(tmp_path / "b", state))
    assert plain is not None and plain == beside
    assert set(FlagCache.model_fields) == {"entries", "sha256"}
    assert "tengu" not in plain.model_dump_json()


@pytest.mark.parametrize(
    "left",
    [
        None,
        "not json {",
        json.dumps(["a", "list"]),
        json.dumps({"userID": "u-1"}),
        json.dumps({"cachedGrowthBookFeatures": ["not", "a", "table"]}),
        json.dumps({"cachedGrowthBookFeatures": None}),
    ],
    ids=["no file", "not json", "not a table", "no such key", "a list", "null"],
)
def test_a_directory_with_no_flag_table_reads_as_none(tmp_path: Path, left: str | None) -> None:
    tmp_path.mkdir(exist_ok=True)
    if left is not None:
        (tmp_path / ".claude.json").write_text(left)
    assert flag_cache(tmp_path) is None


def test_an_empty_table_is_a_reading_of_its_own(tmp_path: Path) -> None:
    reading = flag_cache(_left(tmp_path / "c", {"cachedGrowthBookFeatures": {}}))
    assert reading == FlagCache(entries=0, sha256=_digest({}))


A = FlagCache(entries=1256, sha256="8c" * 32)
B = FlagCache(entries=1256, sha256="ca" * 32)


@pytest.mark.parametrize(
    ("readings", "counted"),
    [
        ((), None),
        ((None, None), None),
        ((A,), FlagDrift(readings=1, changes=0)),
        ((A, A, A), FlagDrift(readings=3, changes=0)),
        ((A, B), FlagDrift(readings=2, changes=1)),
        ((A, B, A), FlagDrift(readings=3, changes=2)),  # back again is a change too
        ((A, None, B, B), FlagDrift(readings=3, changes=1)),  # a session with none is skipped
    ],
)
def test_changes_are_counted_from_each_reading_to_the_next(
    readings: tuple[FlagCache | None, ...], counted: FlagDrift | None
) -> None:
    assert flag_drift(readings) == counted


SEEN = ObservedTraffic(
    served_catalog="off", served_catalog_reason="not_first_party", feature_flags="not reported off"
)
SERVED = SEEN.model_copy(
    update={"served_catalog": "not reported off", "served_catalog_reason": None}
)


def _start(rig: Rig, first: FlagCache | None, *subtasks: str, policy: str | None = None) -> None:
    loop = rig.open()
    loop.record.start(
        plan(*subtasks),
        decomposed=DecompositionSummary(
            session_id="d1",
            model="claude-sonnet-5",
            num_turns=1,
            subtasks=len(subtasks),
            interface_nodes=("iface.bus",),
            spec_commit="a" * 40,
            head_revision=1,
            observed_traffic=SEEN,
            policy_limits_sha256=policy,
            flag_cache=first,
        ),
    )
    loop.close()


def _run(rig: Rig) -> str:
    loop = rig.open()
    kind = loop.run().kind
    loop.close()
    return kind


def test_a_run_whose_flag_cache_changed_completes_and_its_record_counts_the_changes(
    tmp_path: Path,
) -> None:
    dispatcher = FakeDispatcher(traffic={1: SEEN, 2: SEEN}, flag_caches={1: B, 2: A})
    rig = Rig(tmp_path, dispatcher=dispatcher)
    _start(rig, A, "s1", "s2")
    assert _run(rig) == "done"
    events = read_events(tmp_path / "events.jsonl")
    assert [e.flag_cache for e in events if isinstance(e, SessionEnded)] == [B, A]
    assert not any(isinstance(e, (Incident, Halted)) for e in events)
    assert len([e for e in events if isinstance(e, Merged)]) == 2
    # The decomposition call's reading, then each session's: A, B, A.
    assert flag_cache_readings(events) == (A, B, A)
    assert flag_drift(flag_cache_readings(events)) == FlagDrift(readings=3, changes=2)


def test_a_review_whose_flag_cache_changed_is_taken_and_its_readings_are_counted(
    tmp_path: Path,
) -> None:
    rig = Rig(tmp_path, dispatcher=FakeDispatcher(traffic={1: SEEN}, flag_caches={1: A}))
    same = SessionManaged(observed_traffic=SEEN, managed_drift=None, policy_limits_sha256=None)
    rig.reviewer.results[1] = ReviewResult(
        verdict="pass",
        finding="the change is sound",
        reviewer_model=rig.reviewer.model,
        session_id="rev-1",
        usage=(MessageUsage(message_id="r1", usage=usage(7)),),
        # The review's session, and its resume to repair the verdict.
        managed=(
            same.model_copy(update={"flag_cache": B}),
            same.model_copy(update={"flag_cache": A}),
        ),
    )
    _start(rig, A, "s1")
    assert _run(rig) == "done"
    events = read_events(tmp_path / "events.jsonl")
    (ran,) = [e for e in events if isinstance(e, ReviewRan)]
    assert [m.flag_cache for m in ran.result.managed] == [B, A]
    assert not any(isinstance(e, (Incident, Halted)) for e in events)
    assert flag_cache_readings(events) == (A, A, B, A)
    assert flag_drift(flag_cache_readings(events)) == FlagDrift(readings=4, changes=2)


def test_another_served_catalog_state_still_halts_whatever_the_flag_cache_did(
    tmp_path: Path,
) -> None:
    dispatcher = FakeDispatcher(traffic={1: SEEN, 2: SERVED}, flag_caches={1: B, 2: B})
    rig = Rig(tmp_path, dispatcher=dispatcher)
    _start(rig, A, "s1", "s2")
    assert _run(rig) == "halted"
    events = read_events(tmp_path / "events.jsonl")
    (incident,) = [e for e in events if isinstance(e, Incident)]
    assert incident.cause == "managed_settings_changed" and incident.subtask_id == "s2"
    assert "catalog" in incident.detail and "flag cache" not in incident.detail
    # The halted run's record still counts what it read: A, B, B.
    assert flag_drift(flag_cache_readings(events)) == FlagDrift(readings=3, changes=1)


def test_other_policy_limits_still_halt_whatever_the_flag_cache_did(tmp_path: Path) -> None:
    dispatcher = FakeDispatcher(traffic={1: SEEN}, flag_caches={1: A}, policy={1: "b" * 64})
    rig = Rig(tmp_path, dispatcher=dispatcher)
    _start(rig, A, "s1", policy="a" * 64)
    assert _run(rig) == "halted"
    events = read_events(tmp_path / "events.jsonl")
    (incident,) = [e for e in events if isinstance(e, Incident)]
    assert incident.cause == "managed_settings_changed"
    assert "policy limits" in incident.detail


def test_a_session_that_left_no_cache_is_recorded_byte_for_byte_as_before(tmp_path: Path) -> None:
    rig = Rig(tmp_path, dispatcher=FakeDispatcher())
    _start(rig, None, "s1")
    assert _run(rig) == "done"
    lines = (tmp_path / "events.jsonl").read_text().split("\n")
    assert not any("flag_cache" in line for line in lines)
    assert flag_drift(flag_cache_readings(read_events(tmp_path / "events.jsonl"))) is None


#: A stand-in binary for the decomposition call: it reports the version in its own name, writes
#: the log it is asked for, and leaves a state file with a table of flags as 2.1.322 does.
STANDIN = r"""
import json, os, sys
args = sys.argv[1:]
if args == ["--version"]:
    print(os.path.basename(sys.argv[0]).removeprefix("claude-") + " (Claude Code)")
    sys.exit(0)
with open(args[args.index("--debug-file") + 1], "w") as out:
    out.write("[servedCatalog] off (essential_traffic)\nGrowthBook is off for this session\n")
config = os.environ["CLAUDE_CONFIG_DIR"]
os.makedirs(config, exist_ok=True)
with open(os.path.join(config, ".claude.json"), "w") as out:
    json.dump({"cachedGrowthBookFeatures": {"tengu_b": 1, "tengu_a": 2}}, out)
sys.exit(0)
"""


@pytest.mark.parametrize(
    ("version", "read"),
    [
        ("2.1.322", FlagCache(entries=2, sha256=_digest({"tengu_a": 2, "tengu_b": 1}))),
        ("2.1.301", None),  # an earlier pin fetches no flags: nothing is read, whatever is there
    ],
)
def test_the_decomposition_call_s_flag_cache_is_the_run_s_first_reading_on_the_new_pin_only(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, version: str, read: FlagCache | None
) -> None:
    binary = tmp_path / "bin" / f"claude-{version}"
    binary.parent.mkdir()
    binary.write_text(f"#!{sys.executable}\n{STANDIN}")
    binary.chmod(binary.stat().st_mode | stat.S_IXUSR)
    monkeypatch.setenv("PHYSGATE_CLAUDE_BIN", str(binary))
    outcome = decompose.call(
        "brief",
        config=make_config(claude_version=version, bounds=SCRIPTED_BOUNDS),
        workdir=tmp_path / "w",
        base_url=None,
        credential=Credential("api_key", "not-a-key"),
    )
    assert (tmp_path / "w" / "config" / ".claude.json").is_file()
    assert outcome.flag_cache == read
