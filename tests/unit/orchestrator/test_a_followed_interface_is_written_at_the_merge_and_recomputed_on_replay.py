"""The loop follows an interface only at sizing's opening pass, and replay recomputes it (M-195).

The change check is asked to derive a sizing-produced interface only for an attempt of sizing's
opening subtask, and only while no subtask of any other module directory has entered ``spawn``:
never at the closing pass, never once a domain has spawned, so never at a reopen after one. The
followed revision is written at the merge, after the attempt's proposals, behind an intent of its
own carrying its digest, and the merge rewrites the run branch's contract file. The record carries
the interface as it stood, every joined node's payload and the derived payload, so replay derives
the revision again and refuses one that is not that derivation, a joined node that is not what the
attempt wrote, an interface write no followed line explains, and a followed line where none is
due.
"""

from __future__ import annotations

import importlib
import json
import sys
from collections.abc import Mapping
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent))
from arbitration_runs import (  # noqa: E402
    ACT,
    PerAttempt,
    Streaming,
    entry,
    events_of,
    refusal,
    resequenced,
)
from loop_fakes import FakeChanges, FakeMerger, FakeReviewer, Rig  # noqa: E402
from test_a_queue_decision_acts_at_a_boundary import _layer  # noqa: E402

from physgate.orchestrator.events import (  # noqa: E402
    Event,
    Merged,
    ProposalsChecked,
    WriteIntended,
)
from physgate.orchestrator.ports import ChangeCheck  # noqa: E402
from physgate.orchestrator.record import DecompositionSummary, PlanEntry  # noqa: E402
from physgate.orchestrator.run_config import ModelStrings  # noqa: E402
from physgate.series.seal import SessionSeries  # noqa: E402
from physgate.state.store import JournalLine, payload_digest  # noqa: E402

IFACE = "drive.motor"
JOINED = "sizing.drive"


def need(module: str, name: str) -> Any:  # noqa: ANN401 - whatever the build names
    """``module.name``, or a failing assertion while the build has not made it."""
    try:
        found = getattr(importlib.import_module(module), name, None)
    except ImportError:
        found = None
    if found is None:
        pytest.fail(f"{module}.{name} is not built yet")
    return found


def q(value: float, unit: str, source: str) -> dict[str, Any]:
    return {"value": value, "unit": unit, "source": source, "written_by": "sizing"}


INTERFACE: dict[str, Any] = {
    "id": IFACE,
    "kind": "interface",
    "domain": "cross",
    "owner_role": "sizing",
    "quantities": {"stall_current": q(1.44, "A", "the plan"), "current_limit": q(1.8, "A", "plan")},
    "requirements": [],
    "constrains": [],
    "model": None,
    "geometry_hash": "none",
    "updated": "2026-11-03",
}
SIZED: dict[str, Any] = {
    "id": JOINED,
    "kind": "component",
    "domain": "cross",
    "owner_role": "sizing",
    "quantities": {"stall_current": q(1.35, "A", "fit"), "current_limit": q(1.8, "A", "sheet")},
    "requirements": [],
    "constrains": [IFACE],
    "model": None,
    "geometry_hash": "none",
    "updated": "2026-11-03",
}
#: Sizing's opening pass, a domain, and sizing's closing pass in the opening's directory.
PLAN = [entry("z0", "sizing"), entry("s1", "electrical"), entry("zc", "sizing", "modules/z0")]


@dataclass
class Journal:
    """A canonical journal the loop's graph port serves: the plan's interface at revision 1."""

    journal: list[JournalLine] = field(
        default_factory=lambda: [
            JournalLine(rev=1, op="create", node_id=IFACE, version=1, payload=INTERFACE)
        ]
    )
    writes: dict[str, list[dict[str, Any]]] = field(default_factory=lambda: {"z0": [SIZED]})
    admitted: list[frozenset[int]] = field(default_factory=list)
    root: Path = Path("store")

    def _append(self, payload: dict[str, Any]) -> int:
        node = payload["id"]
        version = 1 + max((ln.version for ln in self.journal if ln.node_id == node), default=0)
        rev = len(self.journal) + 1
        op = "create" if version == 1 else "write"
        self.journal.append(
            JournalLine(rev=rev, op=op, node_id=node, version=version, payload=payload)  # type: ignore[arg-type]
        )
        return rev

    def records_after(self, revision: int) -> list[Any]:
        return [line for line in self.journal if line.rev > revision]

    def hold(self) -> None:
        return None

    def commit(self, message: str) -> None:
        return None

    def proposals(self, subtask_id: str, attempt_commit: str, role: str) -> list[dict[str, Any]]:
        return [json.loads(json.dumps(p)) for p in self.writes.get(subtask_id, ())]

    def write(self, payload: dict[str, Any], role: str) -> int:
        return self._append(payload)

    def follow(self, payload: dict[str, Any], role: str, joined: tuple[str, ...]) -> int:
        return self._append(payload)

    def divergences(
        self, since: int, acting_role: str, admitted: frozenset[int] = frozenset()
    ) -> tuple[Any, ...]:
        self.admitted.append(admitted)
        return ()

    def reopen(self) -> tuple[int, tuple[str, ...]]:
        return 0, ()


@dataclass
class Following(FakeChanges):
    """Records what each check was asked to follow, and follows as the real check does."""

    asked: list[tuple[str, int | None]] = field(default_factory=list)
    graph: Journal = field(default_factory=Journal)

    def check(
        self,
        subtask_id: str,
        attempt_commit: str,
        role: str,
        *,
        series: SessionSeries | None = None,
        follows: int | None = None,
    ) -> ChangeCheck:
        self.asked.append((subtask_id, follows))
        found = super().check(subtask_id, attempt_commit, role, series=series)
        if follows is None:
            return found
        follow = need("physgate.orchestrator.follow", "follow")
        heads = {line.node_id: line.payload for line in self.graph.journal}
        nodes = {p["id"]: p for p in self.graph.proposals(subtask_id, attempt_commit, role)}
        entry = follow(heads[IFACE], nodes, role, follows)
        return found.model_copy(update={"followed": (entry,) if entry is not None else ()})


@dataclass
class Merging(FakeMerger):
    contracts: list[Mapping[str, str] | None] = field(default_factory=list)

    def merge(
        self,
        subtask_id: str,
        attempt: int,
        attempt_commit: str,
        message: str,
        reopen: int = 0,
        contracts: Mapping[str, str] | None = None,
    ) -> str:
        self.contracts.append(contracts)
        return super().merge(subtask_id, attempt, attempt_commit, message, reopen)


def rig_of(run_dir: Path) -> Rig:
    run_dir.mkdir(parents=True, exist_ok=True)
    roles = {"electrical": "claude-sonnet-5", "sizing": "claude-sonnet-5"}
    models = ModelStrings(
        decomposition="claude-sonnet-5",
        roles=roles,
        reviewers=dict.fromkeys(roles, "claude-opus-5-5"),
    )
    graph = Journal()
    return Rig(
        run_dir,
        gate=PerAttempt(verdicts=[]),
        reviewer=FakeReviewer(verdicts=[]),
        dispatcher=Streaming(trajectories=run_dir / "sessions"),
        changes=Following(graph=graph),
        merger=Merging(),
        diff=graph,  # type: ignore[arg-type]
        config_overrides={"models": models, **ACT},
    )


def run(rig: Rig, plan: list[PlanEntry] = PLAN) -> str:
    loop = rig.open()
    summary = DecompositionSummary(
        session_id="decomp-1",
        model="claude-sonnet-5",
        num_turns=1,
        subtasks=len(plan),
        interface_nodes=(IFACE,),
        spec_commit="a" * 40,
        head_revision=1,
    )
    loop.record.start(plan, decomposed=summary)
    _layer(loop)
    kind = loop.run().kind
    loop.close()
    return kind


def asked(rig: Rig) -> list[tuple[str, int | None]]:
    assert isinstance(rig.changes, Following)
    return rig.changes.asked


def test_only_the_opening_pass_before_any_other_module_spawned_is_asked_to_follow(
    tmp_path: Path,
) -> None:
    rig = rig_of(tmp_path / "run")
    assert run(rig) == "done"
    assert asked(rig) == [("z0", 1), ("s1", None), ("zc", None)]


def test_an_opening_pass_after_another_module_spawned_is_never_asked(tmp_path: Path) -> None:
    rig = rig_of(tmp_path / "run")
    late = [entry("s1", "electrical"), entry("z0", "sizing"), entry("zc", "sizing", "modules/z0")]
    assert run(rig, late) == "done"
    assert dict(asked(rig))["z0"] is None
    # Once a domain has spawned, no later attempt of the opening pass, a reopen included, is due.
    state = rig.open().state
    due = getattr(state, "follows", None)
    if due is None:
        pytest.fail("RunState.follows is not built yet")
    assert due("z0") is None


def test_the_followed_revision_is_written_after_the_proposals_and_its_contract_rewritten(
    tmp_path: Path,
) -> None:
    rig = rig_of(tmp_path / "run")
    assert run(rig) == "done"
    events = events_of(rig)
    (checked,) = [e for e in events if isinstance(e, ProposalsChecked) and e.subtask_id == "z0"]
    followed: tuple[Any, ...] = getattr(checked, "followed", ())
    assert [f.interface for f in followed] == [IFACE]
    intents = [e for e in events if isinstance(e, WriteIntended) and e.subtask_id == "z0"]
    assert [e.node_id for e in intents] == [JOINED, IFACE]
    assert (
        intents[1].payload_sha256 == followed[0].payload_sha256 == payload_digest(followed[0].after)
    )
    assert isinstance(rig.diff, Journal)
    revisions = [line for line in rig.diff.journal if line.node_id == IFACE]
    assert [line.rev for line in revisions] == [1, 3]
    assert revisions[-1].payload == followed[0].after
    assert isinstance(rig.merger, Merging)
    (contracts, *_) = rig.merger.contracts
    assert contracts is not None and f".physgate/interfaces/{IFACE}.json" in contracts
    assert 3 in set().union(*rig.diff.admitted)
    assert refusal(events) is None


def _honest(tmp_path: Path) -> list[Event]:
    rig = rig_of(tmp_path / "run")
    assert run(rig) == "done"
    events = events_of(rig)
    checked = next(e for e in events if isinstance(e, ProposalsChecked) and e.subtask_id == "z0")
    if not getattr(checked, "followed", ()):
        pytest.fail("the change check's line records no followed interface yet")
    return events


def _edited(events: list[Event], edit: Any) -> list[Event]:  # noqa: ANN401 - a line's own fields
    """``events`` with each line passed through ``edit`` as JSON, read back as lines."""
    from physgate.orchestrator.events import parse_events

    data = b"".join(
        json.dumps(edit(json.loads(e.model_dump_json()))).encode() + b"\n"
        for e in resequenced(events)
    )
    return list(parse_events(data, log="events.jsonl"))


def _forge_value(line: dict[str, Any]) -> dict[str, Any]:
    """The followed revision with a value changed by hand, its digests made to agree."""
    if line.get("kind") == "proposals_checked" and line.get("followed"):
        after = line["followed"][0]["after"]
        after["quantities"]["stall_current"]["value"] = 1.2
        line["followed"][0]["payload_sha256"] = payload_digest(after)
        _forge_value.digest = line["followed"][0]["payload_sha256"]  # type: ignore[attr-defined]
    if line.get("kind") == "write_intended" and line.get("node_id") == IFACE:
        line["payload_sha256"] = _forge_value.digest  # type: ignore[attr-defined]
    return line


def _forge_joined(line: dict[str, Any]) -> dict[str, Any]:
    """A joined node recorded with another value than the attempt wrote, and the revision too."""
    if line.get("kind") == "proposals_checked" and line.get("followed"):
        entry = line["followed"][0]
        entry["joined_payloads"][0]["quantities"]["stall_current"]["value"] = 1.2
        entry["after"]["quantities"]["stall_current"]["value"] = 1.2
        entry["payload_sha256"] = payload_digest(entry["after"])
        _forge_joined.digest = entry["payload_sha256"]  # type: ignore[attr-defined]
    if line.get("kind") == "write_intended" and line.get("node_id") == IFACE:
        line["payload_sha256"] = _forge_joined.digest  # type: ignore[attr-defined]
    return line


def _unexplained(line: dict[str, Any]) -> dict[str, Any]:
    """The interface write left, its followed line taken away."""
    if line.get("kind") == "proposals_checked":
        line.pop("followed", None)
    return line


def _intent_moved(line: dict[str, Any]) -> dict[str, Any]:
    """The interface's write intent carrying another digest than the followed revision's."""
    if line.get("kind") == "write_intended" and line.get("node_id") == IFACE:
        line["payload_sha256"] = "0" * 64
    return line


@pytest.mark.parametrize(
    ("edit", "said"),
    [
        pytest.param(_forge_value, "derivation", id="a-value-changed-by-hand"),
        pytest.param(_forge_joined, "joined", id="a-joined-node-not-what-the-attempt-wrote"),
        pytest.param(_unexplained, "interface", id="an-interface-write-no-line-explains"),
        pytest.param(_intent_moved, "interface", id="an-intent-with-another-digest"),
    ],
)
def test_replay_refuses_a_followed_revision_the_record_does_not_derive(
    tmp_path: Path,
    edit: Any,
    said: str,  # noqa: ANN401
) -> None:
    events = _edited(_honest(tmp_path), edit)
    why = refusal(events)
    assert why is not None and said in why


def test_replay_refuses_a_followed_line_where_none_is_due(tmp_path: Path) -> None:
    events = _honest(tmp_path)
    followed = next(
        e for e in events if isinstance(e, ProposalsChecked) and e.subtask_id == "z0"
    ).followed  # type: ignore[attr-defined]

    def moved(line: dict[str, Any]) -> dict[str, Any]:
        if line.get("kind") == "proposals_checked" and line.get("subtask_id") == "zc":
            line["followed"] = [json.loads(f.model_dump_json()) for f in followed]
        return line

    why = refusal(_edited(events, moved))
    assert why is not None and "follow" in why
    assert any(isinstance(e, Merged) and e.subtask_id == "zc" for e in events)
