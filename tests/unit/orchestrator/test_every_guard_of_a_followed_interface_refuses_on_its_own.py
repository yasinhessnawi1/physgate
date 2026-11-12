"""Each guard on a followed interface refuses on its own.

The derivation refuses a second joined node that lacks a name as it refuses the first. The store's
own method refuses a revision copied from a node not joined to the interface, from a joined node of
another role, naming a node it does not hold, or in which nothing differs. A merge rewrites no file
but an interface contract, and one a killed process left in progress is finished with its contract
file. Only the role that owns the cross nodes is ever asked to follow; the gate judges the opening
attempt with its followed revision; a line or an artefact that follows nothing keeps its bytes; the
record names every interface the decomposition wrote; and replay refuses a followed interface of
another role, a merge before the followed interface is written, and a followed line whose digest is
not its revision's.
"""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path
from typing import Any

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent))
from arbitration_runs import PerAttempt, entry, events_of, refusal  # noqa: E402
from loop_fakes import Rig  # noqa: E402
from test_a_followed_interface_is_written_at_the_merge_and_recomputed_on_replay import (  # noqa: E402
    PLAN,
    Following,
    _edited,
    asked,
    rig_of,
)
from test_a_followed_interface_is_written_at_the_merge_and_recomputed_on_replay import (  # noqa: E402
    run as _run,
)
from test_a_sizing_interface_follows_sizing_s_joined_node_at_its_opening_pass import (  # noqa: E402
    _ENV,
    IFACE,
    JOINED,
    PLAN_VALUES,
    SIZED_VALUES,
    attempt_run,
    checked,
    interface,
    sized,
    store_of,
)

from physgate.orchestrator.decompose import contracts_of, interface_contract  # noqa: E402
from physgate.orchestrator.events import (  # noqa: E402
    ProposalsChecked,
    WriteDone,
    WriteIntended,
    parse_events,
)
from physgate.orchestrator.exceptions import CorruptEventLogError, MergeRefusedError  # noqa: E402
from physgate.orchestrator.follow import derive  # noqa: E402
from physgate.orchestrator.merge import GitMerger  # noqa: E402
from physgate.orchestrator.record import PlanEntry  # noqa: E402
from physgate.state.schema import Node  # noqa: E402
from physgate.state.store import (  # noqa: E402
    REJECT_INTERFACE_NOT_FOLLOWED,
    Store,
    followed_payload,
    payload_digest,
)


def run(rig: Rig, plan: list[PlanEntry] = PLAN) -> str:
    """The run's end; a run the loop or its record refuses fails the row, never errors it."""
    try:
        return _run(rig, plan)
    except Exception as exc:  # noqa: BLE001 - any refusal is this row's failure
        pytest.fail(f"the run did not end: {type(exc).__name__}: {exc}")


def _git(cwd: Path, *args: str) -> str:
    done = subprocess.run(
        ["git", "-c", "commit.gpgsign=false", *args],
        cwd=cwd, env=_ENV, capture_output=True, text=True, check=True,
    )  # fmt: skip
    return done.stdout.strip()


def test_a_second_joined_node_that_lacks_a_name_refuses_the_attempt(tmp_path: Path) -> None:
    store = store_of(tmp_path / "store", interface())
    short = {k: v for k, v in SIZED_VALUES.items() if k != "no_load_speed"}
    check = checked(tmp_path, store, sized(), sized("sizing.drive_b", short))
    assert check.refused_by == "interface" and check.subject == IFACE
    assert "sizing.drive_b" in str(check.reason) and "no_load_speed" in str(check.reason)
    assert "holds no quantity" in str(check.reason)
    assert check.followed == ()


def test_the_store_refuses_a_revision_copied_from_a_node_not_joined_to_the_interface(
    tmp_path: Path,
) -> None:
    loose = sized("sizing.loose", edges=())
    root = store_of(tmp_path / "store", interface(), loose)
    copied = followed_payload(interface(), [loose], "sizing", 1)
    store = Store(root)
    try:
        refused = store.follow_interface(copied, "sizing", ("sizing.loose",))
        assert not refused.accepted and refused.reason == REJECT_INTERFACE_NOT_FOLLOWED
    finally:
        store.close()


def test_the_store_refuses_a_revision_in_which_nothing_differs(tmp_path: Path) -> None:
    same = sized(values=PLAN_VALUES)
    root = store_of(tmp_path / "store", interface(), same)
    copied = followed_payload(interface(), [same], "sizing", 1)
    store = Store(root)
    try:
        refused = store.follow_interface(copied, "sizing", (JOINED,))
        assert not refused.accepted and refused.reason == REJECT_INTERFACE_NOT_FOLLOWED
    finally:
        store.close()


def test_a_merge_left_in_progress_is_finished_with_its_contract_file(tmp_path: Path) -> None:
    gitrun, commit = attempt_run(tmp_path, sized())
    after = derive(interface(), {JOINED: sized()}, "sizing", 1)
    assert after is not None
    contracts = contracts_of([Node.model_validate(after)])
    # A process killed between the merge's calls left the merge in progress, unwritten.
    _git(gitrun.integration, "merge", "--no-ff", "--no-commit", "-m", "Merge z0\n", commit)
    head = _git(gitrun.integration, "rev-parse", "HEAD")
    merged = GitMerger(gitrun, removal_timeout_s=60).merge(
        "z0", 1, commit, "Merge subtask z0, attempt 1\n", contracts=contracts
    )
    shown = _git(gitrun.repo, "show", f"{merged}:{interface_contract(IFACE)}")
    assert shown + "\n" == contracts[interface_contract(IFACE)]
    assert _git(gitrun.repo, "rev-list", "--parents", "-n", "1", merged).split()[1:] == [
        head,
        commit,
    ]


def test_a_domain_s_opening_subtask_is_never_asked_to_follow(tmp_path: Path) -> None:
    rig = rig_of(tmp_path / "run")
    late = [entry("s1", "electrical"), entry("z0", "sizing"), entry("zc", "sizing", "modules/z0")]
    assert run(rig, late) == "done"
    assert dict(asked(rig))["s1"] is None


def test_the_store_refuses_a_revision_copied_from_a_joined_node_of_another_role(
    tmp_path: Path,
) -> None:
    other = {**sized("control.drive"), "owner_role": "control", "domain": "control"}
    root = store_of(tmp_path / "store", interface(), other)
    copied = followed_payload(interface(), [other], "sizing", 1)
    store = Store(root)
    try:
        refused = store.follow_interface(copied, "sizing", ("control.drive",))
        assert not refused.accepted and refused.reason == REJECT_INTERFACE_NOT_FOLLOWED
    finally:
        store.close()


def test_a_merge_rewrites_no_file_but_an_interface_contract(tmp_path: Path) -> None:
    gitrun, commit = attempt_run(tmp_path, sized())
    merger = GitMerger(gitrun, removal_timeout_s=60)
    with pytest.raises(MergeRefusedError):
        merger.merge("z0", 1, commit, "Merge\n", contracts={"modules/z0/a.txt": "1\n"})


def _honest_rig(tmp_path: Path) -> Rig:
    rig = rig_of(tmp_path / "run")
    assert run(rig) == "done"
    return rig


def test_the_gate_judges_the_attempt_with_its_followed_revision_and_others_without(
    tmp_path: Path,
) -> None:
    rig = _honest_rig(tmp_path)
    assert isinstance(rig.gate, PerAttempt)
    seen = {a.subtask_id: a for a in rig.gate.seen}
    assert [f.interface for f in seen["z0"].followed] == [IFACE]
    assert seen["s1"].followed == ()
    assert "followed" not in json.loads(seen["s1"].model_dump_json())


def test_a_change_check_that_follows_nothing_keeps_its_line_s_bytes(tmp_path: Path) -> None:
    events = events_of(_honest_rig(tmp_path))
    lines = {
        e.subtask_id: json.loads(e.model_dump_json())
        for e in events
        if isinstance(e, ProposalsChecked)
    }
    assert "followed" in lines["z0"] and "followed" not in lines["s1"]


def test_replay_refuses_a_followed_interface_another_role_produces(tmp_path: Path) -> None:
    def theirs(line: dict[str, Any]) -> dict[str, Any]:
        if line.get("kind") == "proposals_checked" and line.get("followed"):
            entry = line["followed"][0]
            entry["before"]["owner_role"] = entry["after"]["owner_role"] = "control"
            entry["payload_sha256"] = payload_digest(entry["after"])
            theirs.digest = entry["payload_sha256"]  # type: ignore[attr-defined]
        if line.get("kind") == "write_intended" and line.get("node_id") == IFACE:
            line["payload_sha256"] = theirs.digest  # type: ignore[attr-defined]
        return line

    why = refusal(_edited(events_of(_honest_rig(tmp_path)), theirs))
    assert why is not None and "no interface the sizing role produces" in why


def test_replay_refuses_a_merge_before_its_followed_interface_is_written(tmp_path: Path) -> None:
    events = events_of(_honest_rig(tmp_path))
    unwritten = [
        e for e in events if not (isinstance(e, WriteIntended | WriteDone) and e.node_id == IFACE)
    ]
    why = refusal(unwritten)
    assert why is not None and "merge" in why


def test_the_store_refuses_a_revision_naming_a_joined_node_it_does_not_hold(
    tmp_path: Path,
) -> None:
    root = store_of(tmp_path / "store", interface(), sized())
    copied = followed_payload(interface(), [sized()], "sizing", 1)
    store = Store(root)
    try:
        refused = store.follow_interface(copied, "sizing", (JOINED, "sizing.unheld"))
        assert not refused.accepted and refused.reason == REJECT_INTERFACE_NOT_FOLLOWED
    finally:
        store.close()


def test_the_record_names_every_interface_the_decomposition_wrote(tmp_path: Path) -> None:
    # A run whose plan names no consumers still names its interface nodes, so an interface
    # write is held to the followed line that explains it in every run.
    rig = rig_of(tmp_path / "run")
    assert isinstance(rig.changes, Following)
    rig.changes.graph.writes["z0"] = [sized(values=PLAN_VALUES)]
    assert run(rig) == "done"
    assert rig.open().state.interface_nodes == (IFACE,)


def test_a_followed_line_whose_digest_is_not_its_revision_s_is_no_line_of_this_package(
    tmp_path: Path,
) -> None:
    lines = [json.loads(e.model_dump_json()) for e in events_of(_honest_rig(tmp_path))]
    for line in lines:
        if line.get("kind") == "proposals_checked" and line.get("followed"):
            line["followed"][0]["after"]["quantities"]["stall_current"]["value"] = 1.2
    data = b"".join(json.dumps(line).encode() + b"\n" for line in lines)
    with pytest.raises(CorruptEventLogError) as refused:
        parse_events(data, log="events.jsonl")
    assert "digest of its revision" in refused.value.context.get("reason", "")


def test_the_store_refuses_a_role_s_revision_of_an_interface_another_role_produces(
    tmp_path: Path,
) -> None:
    theirs = {**sized("control.drive"), "owner_role": "control", "domain": "control"}
    root = store_of(tmp_path / "store", interface(), theirs)
    copied = followed_payload(interface(), [theirs], "control", 1)
    store = Store(root)
    try:
        refused = store.follow_interface(copied, "control", ("control.drive",))
        assert not refused.accepted and refused.reason == REJECT_INTERFACE_NOT_FOLLOWED
    finally:
        store.close()


def test_replay_refuses_a_followed_line_on_a_pass_that_is_not_due_as_not_due(
    tmp_path: Path,
) -> None:
    events = events_of(_honest_rig(tmp_path))
    followed = next(
        e for e in events if isinstance(e, ProposalsChecked) and e.subtask_id == "z0"
    ).followed

    def moved(line: dict[str, Any]) -> dict[str, Any]:
        if line.get("kind") == "proposals_checked" and line.get("subtask_id") == "zc":
            line["followed"] = [json.loads(f.model_dump_json()) for f in followed]
        return line

    why = refusal(_edited(events, moved))
    assert why is not None and "where no follow is due" in why
