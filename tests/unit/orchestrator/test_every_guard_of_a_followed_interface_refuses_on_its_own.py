"""Each guard on a followed interface refuses on its own (M-195, D-A2-37).

The derivation refuses a second joined node that lacks a name as it refuses the first; the store's
own method refuses a revision copied from a node of the owner that is not joined to the interface,
and one in which nothing differs; a merge that a killed process left in progress writes the
contract file when it is finished; and only the role that owns the cross nodes is ever asked to
follow, even where a domain's module is the first to run.
"""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from arbitration_runs import entry  # noqa: E402
from test_a_followed_interface_is_written_at_the_merge_and_recomputed_on_replay import (  # noqa: E402
    asked,
    rig_of,
    run,
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
from physgate.orchestrator.follow import derive  # noqa: E402
from physgate.orchestrator.merge import GitMerger  # noqa: E402
from physgate.state.schema import Node  # noqa: E402
from physgate.state.store import (  # noqa: E402
    REJECT_INTERFACE_NOT_FOLLOWED,
    Store,
    followed_payload,
)


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
