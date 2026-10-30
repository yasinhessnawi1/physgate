"""A dispute is one file, checked where it is written and recorded where it is read.

A role that disagrees with a value on a cross node writes its position, never the node:
``.physgate/disputes/<node id>.<quantity>.json``, holding ``{"value", "unit", "reason"}``, each key
once. The hook checks a Write or Edit of it before the file exists, with the one parser the change
check uses: the name, who may dispute (every role but the owners of the cross nodes and of
completion, found by what they own), what (a quantity an existing cross node holds, never an
interface's), and the body. A shell command that names the directory is refused unless it only
reads. The change check reads every dispute the attempt added or changed since the run branch,
from the commit it checks, and refuses a malformed one as the dispute's; another role's dispute is
a write outside its module. The loop records one line per dispute straight after an accepted
change check, sorted, and replay takes such a line nowhere else. No prompt names the channel yet.
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
from collections.abc import Sequence
from pathlib import Path
from typing import Any

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "hooks"))
from hook_helpers import bash, event, make_store, node, write_config  # noqa: E402
from loop_fakes import FakeChanges, Rig, plan  # noqa: E402

from physgate import roles  # noqa: E402
from physgate.hooks import graph  # noqa: E402
from physgate.hooks.config import HookInput, SessionConfig  # noqa: E402
from physgate.orchestrator import dispute  # noqa: E402
from physgate.orchestrator.apply import GitChangeChecker  # noqa: E402
from physgate.orchestrator.dispute import Dispute, DisputeError, parse  # noqa: E402
from physgate.orchestrator.events import (  # noqa: E402
    DisputeRecorded,
    Event,
    ProposalsChecked,
    StageEntered,
    read_events,
)
from physgate.orchestrator.exceptions import CorruptEventLogError  # noqa: E402
from physgate.orchestrator.merge import RunGit, commit_attempt  # noqa: E402
from physgate.orchestrator.protocols import QuantityRef  # noqa: E402
from physgate.orchestrator.record import PlanEntry  # noqa: E402
from physgate.orchestrator.replay import replay  # noqa: E402
from physgate.orchestrator.run_config import ModelStrings  # noqa: E402

PATH = ".physgate/disputes/sizing.bus.supply_voltage.json"
OTHER = ".physgate/disputes/sizing.bus.peak_current.json"
REASON = "the driver needs 24 V at the stall current"
PLANNED = {"s1": "modules/s1", "siz": "modules/siz", "integ": "modules/integ"}

_ENV = {
    "PATH": "/usr/bin:/bin",
    "HOME": os.devnull,
    "GIT_CONFIG_GLOBAL": os.devnull,
    "GIT_CONFIG_NOSYSTEM": "1",
    "GIT_AUTHOR_NAME": "t",
    "GIT_AUTHOR_EMAIL": "t@example.invalid",
    "GIT_COMMITTER_NAME": "t",
    "GIT_COMMITTER_EMAIL": "t@example.invalid",
}


def quantity(value: float, unit: str) -> dict[str, Any]:
    return {"value": value, "unit": unit, "source": "sizing", "written_by": "sizing"}


#: The graph: a cross node sizing wrote, an interface, and a node of a domain.
NODES = (
    node(
        "sizing.bus",
        "sizing",
        quantities={"supply_voltage": quantity(12, "V"), "peak_current": quantity(3, "A")},
    ),
    node("sizing.link", "sizing", kind="interface"),
    node("control.loop", "control"),
)


def body(value: object = 24, unit: object = "V", reason: object = REASON, **extra: object) -> bytes:
    return json.dumps({"value": value, "unit": unit, "reason": reason, **extra}).encode()


def nodes() -> dict[str, dict[str, Any]]:
    return {str(n["id"]): n for n in NODES}


@pytest.fixture(autouse=True)
def sizing_registered(monkeypatch: pytest.MonkeyPatch) -> None:
    """Sizing in the register, as a run that sizes has it: the owner of the cross nodes."""
    monkeypatch.setitem(roles.ROLES, roles.SIZING.name, roles.SIZING)


# --- the parser ---------------------------------------------------------------------------------

#: Each refused dispute, as (path, bytes, role), and the words its refusal is told in.
REFUSED: dict[str, tuple[str, bytes, str, str]] = {
    "a name with no quantity": (".physgate/disputes/sizing.json", body(), "control", dispute.NAMED),
    "a name not JSON": (PATH.replace(".json", ".txt"), body(), "control", dispute.NAMED),
    "a quantity of capitals": (PATH.replace("supply", "Supply"), body(), "control", dispute.NAMED),
    "a quantity past its bound": (
        f".physgate/disputes/sizing.bus.{'q' * 65}.json",
        body(),
        "control",
        dispute.NAMED,
    ),
    "one directory further in": (
        ".physgate/disputes/x/sizing.bus.supply_voltage.json",
        body(),
        "control",
        dispute.NAMED,
    ),
    "the owner of the cross nodes": (PATH, body(), "sizing", "writes the cross nodes' values"),
    "the owner of completion": (PATH, body(), "integration", "owns completion"),
    "no node": (
        ".physgate/disputes/sizing.motor.supply_voltage.json",
        body(),
        "control",
        "is no cross node",
    ),
    "a node of a domain": (
        ".physgate/disputes/control.loop.stall_current.json",
        body(),
        "control",
        "is no cross node",
    ),
    "an interface": (
        ".physgate/disputes/sizing.link.stall_current.json",
        body(),
        "control",
        "is no cross node",
    ),
    "a quantity the node lacks": (
        ".physgate/disputes/sizing.bus.mass.json",
        body(),
        "control",
        "holds no quantity mass",
    ),
    "past the size cap": (PATH, body(reason="r" * 400) + b" " * 2000, "control", "at most 2048"),
    "a carriage return": (PATH, body().replace(b", ", b",\r\n"), "control", dispute.LINE_ENDS),
    "not UTF-8": (PATH, body() + b"\xff", "control", dispute.NOT_UTF8),
    "not JSON": (PATH, b'{"value": 24', "control", dispute.NOT_JSON),
    "NaN": (PATH, b'{"value": NaN, "unit": "V", "reason": "r"}', "control", dispute.NOT_JSON),
    "not an object": (PATH, b"[24]", "control", dispute.SHAPE),
    "no reason": (PATH, b'{"value": 24, "unit": "V"}', "control", dispute.SHAPE),
    "another key": (PATH, body(source="me"), "control", dispute.SHAPE),
    "a key twice": (
        PATH,
        b'{"value": 24, "unit": "V", "reason": "r", "value": 5}',
        "control",
        dispute.SHAPE,
    ),
    "a quoted value": (PATH, body(value="24"), "control", dispute.VALUE),
    "a boolean value": (PATH, body(value=True), "control", dispute.VALUE),
    "an infinite value": (
        PATH,
        b'{"value": 1e400, "unit": "V", "reason": "r"}',
        "control",
        "finite",
    ),
    "an empty unit": (PATH, body(unit=""), "control", dispute.UNIT),
    "a unit past its bound": (PATH, body(unit="V" * 33), "control", dispute.UNIT),
    "a unit with a line break": (PATH, body(unit="V\n"), "control", dispute.UNIT),
    "a unit of a number": (PATH, body(unit=1), "control", dispute.UNIT),
    "an empty reason": (PATH, body(reason=""), "control", dispute.REASON),
    "a reason past its bound": (PATH, body(reason="r" * 501), "control", dispute.REASON),
    "a reason with a line break": (PATH, body(reason="one\ntwo"), "control", dispute.REASON),
    "a reason with an escape": (PATH, body(reason="red\x1b[0m"), "control", dispute.REASON),
}


@pytest.mark.parametrize("case", REFUSED)
def test_a_malformed_dispute_is_refused_by_the_parser(case: str) -> None:
    path, data, role, said = REFUSED[case]
    with pytest.raises(DisputeError) as refused:
        parse(path, data, role, nodes())
    assert said in str(refused.value)


@pytest.mark.parametrize(
    ("data", "value", "reason"),
    [
        (body(), 24, REASON),
        (body(value=23.5), 23.5, REASON),
        (body(value=-1, reason="r" * 500), -1, "r" * 500),
    ],
    ids=["an integer", "a float", "a negative value, the reason at its bound"],
)
def test_a_well_formed_dispute_is_its_position_and_its_reason(
    data: bytes, value: float, reason: str
) -> None:
    read = parse(PATH, data, "control", nodes())
    position = QuantityRef(node_id="sizing.bus", name="supply_voltage", value=value, unit="V")
    assert read == Dispute(position=position, reason=reason)


def test_with_no_owner_of_the_cross_nodes_registered_every_other_role_disputes(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # Who may not dispute is found by duty: sizing's name is nothing to the parser.
    monkeypatch.delitem(roles.ROLES, roles.SIZING.name)
    assert parse(PATH, body(), "sizing", nodes()).reason == REASON
    with pytest.raises(DisputeError, match="owns completion"):
        parse(PATH, body(), "integration", nodes())


# --- the hook -----------------------------------------------------------------------------------


def session(tmp_path: Path, role: str) -> SessionConfig:
    home = tmp_path / role
    home.mkdir(parents=True, exist_ok=True)
    config = write_config(home, role=role)[2]
    make_store(Path(str(config.store_root)), *NODES)
    return config


def through_hook(config: SessionConfig, tool: str, data: bytes, path: str = PATH) -> str:
    """The hook's answer to ``tool`` writing ``data`` at ``path`` in the worktree."""
    target = Path(config.worktree) / path
    text = data.decode("utf-8", "surrogateescape")
    if tool == "Write":
        tool_input: dict[str, object] = {"file_path": str(target), "content": text}
    elif tool == "Edit":
        tool_input = {"file_path": str(target), "old_string": "", "new_string": text}
    else:
        tool_input = {"notebook_path": str(target), "new_source": text}
    hook_input = HookInput.model_validate(
        event(tool_name=tool, cwd=config.worktree, tool_input=tool_input)
    )
    decision = graph.pre_tool_use(hook_input, config)
    return "allow" if decision.allow else str(decision.reason)


def test_a_dispute_is_schema_checked_at_the_hook(tmp_path: Path) -> None:
    config = session(tmp_path, "control")
    assert through_hook(config, "Write", body()) == "allow"
    assert through_hook(config, "Edit", body()) == "allow"
    refusal = graph.DISPUTE_REFUSED.format(detail="")
    for data in (body(value="24"), b"not json", body(reason="")):
        assert through_hook(config, "Write", data).startswith(refusal), data
    assert dispute.VALUE in through_hook(config, "Write", body(value="24"))
    assert dispute.NAMED in through_hook(config, "NotebookEdit", body())


@pytest.mark.parametrize(
    "case", [c for c in REFUSED if c not in ("not UTF-8", "a carriage return", "past the size cap")]
)
def test_a_malformed_dispute_is_refused_at_the_hook(tmp_path: Path, case: str) -> None:
    path, data, role, said = REFUSED[case]
    told = through_hook(session(tmp_path, role), "Write", data, path)
    assert told.startswith(graph.DISPUTE_REFUSED.format(detail="")), told
    assert said in told


@pytest.mark.parametrize(
    ("text", "said"),
    [
        ("\r\n".join(['{"value": 24,', '"unit": "V", "reason": "r"}']), dispute.LINE_ENDS),
        ('{"value": 24, "unit": "V", "reason": "\udcff"}', dispute.NOT_UTF8),
        (body(reason="r" * 400).decode() + " " * 2000, "at most 2048"),
    ],
    ids=["a carriage return", "a lone surrogate", "past the size cap"],
)
def test_a_dispute_s_bytes_are_held_at_the_hook_as_the_commit_will_hold_them(
    tmp_path: Path, text: str, said: str
) -> None:
    config = session(tmp_path, "control")
    target = Path(config.worktree) / PATH
    hook_input = HookInput.model_validate(
        event(
            tool_name="Write",
            cwd=config.worktree,
            tool_input={"file_path": str(target), "content": text},
        )
    )
    decision = graph.pre_tool_use(hook_input, config)
    assert not decision.allow and said in str(decision.reason)


@pytest.mark.parametrize(
    "command",
    [
        f"cat > {PATH} <<'EOF'\n{body().decode()}\nEOF",
        f"echo '{body().decode()}' > {PATH}",
        f"python3 -c \"open('{PATH}','w').write('{{}}')\"",
        f"cp /tmp/d.json {PATH}",
        "cd .physgate/disputes && echo '{}' > sizing.bus.supply_voltage.json",
        f"rm {PATH}",
    ],
    ids=["heredoc", "redirect", "in-language write", "copy", "cd and redirect", "remove"],
)
def test_a_command_naming_the_disputes_directory_is_refused_unless_it_only_reads(
    tmp_path: Path, command: str
) -> None:
    config = session(tmp_path, "control")
    decision = graph.pre_tool_use(
        HookInput.model_validate(bash(command, cwd=config.worktree)), config
    )
    assert str(decision.reason) == graph.DISPUTE_SHELL


@pytest.mark.parametrize("command", [f"cat {PATH}", "ls .physgate/disputes", "ls"])
def test_a_command_that_only_reads_a_dispute_is_allowed(tmp_path: Path, command: str) -> None:
    config = session(tmp_path, "control")
    decision = graph.pre_tool_use(
        HookInput.model_validate(bash(command, cwd=config.worktree)), config
    )
    assert decision.allow


# --- the change check, over real git ------------------------------------------------------------


def _git(cwd: Path, *args: str) -> str:
    done = subprocess.run(
        ["git", "-c", "commit.gpgsign=false", *args],
        cwd=cwd,
        env=_ENV,
        capture_output=True,
        text=True,
        check=True,
    )
    return done.stdout.strip()


def attempt(
    tmp_path: Path, subtask: str, files: dict[str, bytes | None], number: int = 1
) -> tuple[RunGit, str]:
    """A run whose ``subtask`` committed ``files`` (``None`` deletes) in attempt ``number``."""
    repo = tmp_path / "target"
    if not repo.exists():
        (repo / "modules").mkdir(parents=True)
        (repo / "modules" / "a.txt").write_text("0\n")
        _git(repo, "init", "-q", "-b", "main")
        _git(repo, "add", "-A")
        _git(repo, "commit", "-q", "-m", "start")
    run = RunGit(repo=repo, run_dir=tmp_path / "run", run_id="r1")
    if number == 1:
        run.open_run_branch(_git(repo, "rev-parse", "HEAD"))
    worktree = run.open_subtask(subtask)
    for path, data in files.items():
        if data is None:
            (worktree / path).unlink()
            continue
        (worktree / path).parent.mkdir(parents=True, exist_ok=True)
        (worktree / path).write_bytes(data)
    (worktree / "modules" / subtask).mkdir(parents=True, exist_ok=True)
    (worktree / "modules" / subtask / "notes.md").write_text(f"attempt {number}\n")
    return run, commit_attempt(worktree, subtask, number, f"sess-{number}", repo=run.repo)


def checker(tmp_path: Path, run: RunGit) -> GitChangeChecker:
    store = tmp_path / "store"
    if not store.exists():
        make_store(store, *NODES)
    return GitChangeChecker(run, store, dict(PLANNED))


def disputed(value: float, name: str = "supply_voltage", unit: str = "V") -> Dispute:
    position = QuantityRef(node_id="sizing.bus", name=name, value=value, unit=unit)
    return Dispute(position=position, reason=REASON)


def test_a_dispute_is_read_from_the_checked_commit_each_once_sorted(tmp_path: Path) -> None:
    run, commit = attempt(tmp_path, "s1", {PATH: body(), OTHER: body(5, "A")})
    # The working tree moves on after the commit: what is read is what the commit holds.
    (run.subtask_worktree("s1") / PATH).write_bytes(body(value=99))
    check = checker(tmp_path, run).check("s1", commit, "control")
    assert (check.refused_by, check.reason) == (None, None)
    assert check.disputes == (disputed(5, "peak_current", "A"), disputed(24))


def test_an_attempt_without_a_dispute_disputes_nothing(tmp_path: Path) -> None:
    run, commit = attempt(tmp_path, "s1", {})
    assert checker(tmp_path, run).check("s1", commit, "control").disputes == ()


@pytest.mark.parametrize(
    "case",
    [c for c in REFUSED if REFUSED[c][2] == "control"],
)
def test_a_malformed_dispute_is_refused_at_the_change_check_as_the_dispute_s(
    tmp_path: Path, case: str
) -> None:
    path, data, role, said = REFUSED[case]
    run, commit = attempt(tmp_path, "s1", {path: data})
    try:
        check = checker(tmp_path, run).check("s1", commit, role)
    except Exception as exc:  # noqa: BLE001 - any escape is the finding: a refusal is the contract
        pytest.fail(f"raised {type(exc).__name__}: {exc}")
    assert (check.refused_by, check.subject, check.disputes) == ("dispute", path, ())
    assert said in str(check.reason)


@pytest.mark.parametrize(
    ("subtask", "role"), [("integ", "integration"), ("siz", "sizing")], ids=["completion", "cross"]
)
def test_another_role_s_dispute_is_refused_at_the_hook_and_at_the_change_check_as_its_scope(
    tmp_path: Path, subtask: str, role: str
) -> None:
    told = through_hook(session(tmp_path / "hook", role), "Write", body())
    assert told.startswith(graph.DISPUTE_REFUSED.format(detail=""))
    run, commit = attempt(tmp_path / "apply", subtask, {PATH: body()})
    check = checker(tmp_path / "apply", run).check(subtask, commit, role)
    assert (check.refused_by, check.subject, check.disputes) == ("write_scope", PATH, ())


def test_a_case_variant_of_the_disputes_directory_is_a_write_outside_the_module(
    tmp_path: Path,
) -> None:
    path = PATH.replace("disputes", "Disputes")
    run, commit = attempt(tmp_path, "s1", {path: body()})
    check = checker(tmp_path, run).check("s1", commit, "control")
    assert (check.refused_by, check.subject) == ("write_scope", path)


def test_a_dispute_that_is_a_link_is_refused(tmp_path: Path) -> None:
    run, commit = attempt(tmp_path, "s1", {"modules/s1/d.json": body()})
    worktree = run.subtask_worktree("s1")
    (worktree / PATH).parent.mkdir(parents=True, exist_ok=True)
    os.symlink("../../modules/s1/d.json", worktree / PATH)
    commit = commit_attempt(worktree, "s1", 2, "sess-2", repo=run.repo)
    check = checker(tmp_path, run).check("s1", commit, "control")
    assert check.refused_by is not None and check.disputes == ()


def test_a_dispute_left_in_place_disputes_again_and_a_deleted_one_is_withdrawn(
    tmp_path: Path,
) -> None:
    run, first = attempt(tmp_path, "s1", {PATH: body()})
    check = checker(tmp_path, run)
    assert check.check("s1", first, "control").disputes == (disputed(24),)
    # The repair attempt continues in the same worktree: the file is still there.
    _, second = attempt(tmp_path, "s1", {OTHER: body(5, "A")}, number=2)
    assert check.check("s1", second, "control").disputes == (
        disputed(5, "peak_current", "A"),
        disputed(24),
    )
    _, third = attempt(tmp_path, "s1", {PATH: None, OTHER: None}, number=3)
    assert check.check("s1", third, "control").disputes == ()


# --- the line, after the change check -----------------------------------------------------------

INTEGRATION = PlanEntry(
    subtask_id="integ",
    spec_path="specs/integ.md",
    assigned_role="integration",
    module_dir="modules/integration",
)


def driven(
    tmp_path: Path, disputes: dict[str, tuple[Dispute, ...]], *, refuse: bool = False
) -> list[Event]:
    """A run of ``s1`` and integration whose checks read ``disputes``; its lines."""
    models = ModelStrings(
        decomposition="claude-sonnet-5",
        roles=dict.fromkeys(("electrical", "integration"), "claude-sonnet-5"),
        reviewers=dict.fromkeys(("electrical", "integration"), "claude-opus-5-5"),
    )
    changes = FakeChanges(refuse={1: ("proposal", "refused")} if refuse else {})
    changes.disputes.update(disputes)
    rig = Rig(tmp_path, changes=changes, config_overrides={"models": models})
    loop = rig.open()
    loop.start([*plan("s1"), INTEGRATION])
    loop.run()
    loop.close()
    return read_events(tmp_path / "events.jsonl")


def at(events: Sequence[Event], kind: type[Any], subtask: str = "s1", nth: int = 0) -> int:
    found = [
        i
        for i, e in enumerate(events)
        if isinstance(e, kind) and getattr(e, "subtask_id", None) == subtask
    ]
    return found[nth]


TWO = (disputed(5, "peak_current", "A"), disputed(24))


def test_a_dispute_is_recorded_after_the_change_check(tmp_path: Path) -> None:
    events = driven(tmp_path, {"s1": TWO})
    checked = at(events, ProposalsChecked)
    lines = events[checked + 1 : checked + 3]
    assert [(e.position, e.reason) for e in lines if isinstance(e, DisputeRecorded)] == [
        (d.position, d.reason) for d in TWO
    ]
    assert [(e.subtask_id, e.attempt) for e in lines if isinstance(e, DisputeRecorded)] == [
        ("s1", 1),
        ("s1", 1),
    ]
    after = events[checked + 3]
    assert isinstance(after, StageEntered) and after.stage == "gate"
    assert sum(isinstance(e, DisputeRecorded) for e in events) == 2
    # The change check's own line is as it was: the disputes are on lines of their own.
    raw = (tmp_path / "events.jsonl").read_text().splitlines()[checked]
    assert '"proposals_checked"' in raw and "dispute" not in raw


def test_a_refused_change_check_records_no_dispute(tmp_path: Path) -> None:
    events = driven(tmp_path, {"s1": TWO}, refuse=True)
    first = at(events, ProposalsChecked)
    checked = events[first]
    assert isinstance(checked, ProposalsChecked) and checked.refused_by == "proposal"
    assert not isinstance(events[first + 1], DisputeRecorded)
    # The next attempt's accepted check reads them, and they follow it.
    second = at(events, ProposalsChecked, nth=1)
    assert [type(e) for e in events[second + 1 : second + 3]] == [DisputeRecorded] * 2
    assert {e.attempt for e in events if isinstance(e, DisputeRecorded)} == {2}


# --- replay -------------------------------------------------------------------------------------


def line(events: Sequence[Event], subtask: str = "s1", **fields: Any) -> DisputeRecorded:
    last = events[-1]
    values: dict[str, Any] = {"subtask_id": subtask, "attempt": 1, "reason": REASON}
    values |= {"position": disputed(24).position} | fields
    return DisputeRecorded(
        seq=len(events), ts=last.ts, run_id=last.run_id, gate_mode=last.gate_mode, **values
    )


def refused(events: Sequence[Event], extra: Event, reason: str) -> None:
    with pytest.raises(CorruptEventLogError) as caught:
        replay([*events, extra])
    assert reason in caught.value.context["reason"]


def test_replay_takes_the_honest_lines(tmp_path: Path) -> None:
    events = driven(tmp_path, {"s1": TWO})
    replay(events)
    checked = at(events, ProposalsChecked)
    replay(events[: checked + 3])


def test_replay_refuses_a_dispute_anywhere_but_after_an_accepted_change_check(
    tmp_path: Path,
) -> None:
    events = driven(tmp_path, {"s1": TWO})
    checked = at(events, ProposalsChecked)
    refused(events[:checked], line(events[:checked]), "a dispute")
    gate = checked + 3
    refused(events[: gate + 1], line(events[: gate + 1]), "a dispute")
    no = driven(tmp_path / "refused", {}, refuse=True)
    first = at(no, ProposalsChecked)
    refused(no[: first + 1], line(no[: first + 1]), "a dispute")


def test_replay_refuses_a_quantity_disputed_twice_or_out_of_order(tmp_path: Path) -> None:
    events = driven(tmp_path, {"s1": TWO})
    checked = at(events, ProposalsChecked)
    head = events[: checked + 2]  # the first of the two, peak_current
    said = "each quantity once, in order"
    refused(head, line(head, position=TWO[0].position), said)
    later = events[: checked + 3]
    refused(later, line(later, position=TWO[0].position), said)


def test_replay_refuses_a_dispute_from_the_completion_subtask(tmp_path: Path) -> None:
    events = driven(tmp_path, {})
    checked = at(events, ProposalsChecked, subtask="integ")
    head = events[: checked + 1]
    refused(head, line(head, subtask="integ"), "the completion owner's")
