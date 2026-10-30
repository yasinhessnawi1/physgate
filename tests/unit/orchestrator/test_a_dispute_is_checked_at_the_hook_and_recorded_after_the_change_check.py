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
change check, sorted, and replay takes such a line nowhere else; a dispute no line can hold is the
attempt's refusal, never a crash. The merge and the reviewer's packet leave the directory out, so
the file stays on its attempt's branch. No prompt names the channel yet.
"""

from __future__ import annotations

import json
import os
import re
import subprocess
import sys
from collections.abc import Sequence
from pathlib import Path
from typing import Any

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "hooks"))
from hook_helpers import bash, event, make_store, node, write_config  # noqa: E402
from loop_fakes import FakeChanges, KilledError, Rig, plan  # noqa: E402

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
    parse_events,
    read_events,
)
from physgate.orchestrator.exceptions import CorruptEventLogError  # noqa: E402
from physgate.orchestrator.git import merge_base  # noqa: E402
from physgate.orchestrator.merge import GitMerger, RunGit, commit_attempt  # noqa: E402
from physgate.orchestrator.ports import ChangeCheck  # noqa: E402
from physgate.orchestrator.protocols import QuantityRef  # noqa: E402
from physgate.orchestrator.queue import QueueItem, unavailable_item  # noqa: E402
from physgate.orchestrator.record import PlanEntry  # noqa: E402
from physgate.orchestrator.replay import replay  # noqa: E402
from physgate.orchestrator.run_config import ModelStrings  # noqa: E402
from physgate.reviewers import packet  # noqa: E402

PATH = ".physgate/disputes/sizing.bus.supply_voltage.json"
OTHER = ".physgate/disputes/sizing.bus.peak_current.json"
DISPUTES = ".physgate/disputes"
REASON = "the driver needs 24 V at the stall current"
#: A value no float holds: 400 digits, kept exact from the file to the record and back.
BIG = 10**399 + 7
PLANNED = {"s1": "modules/s1", "s2": "modules/s2", "siz": "modules/siz", "integ": "modules/integ"}

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
    node("sizing.bus.rail", "sizing", quantities={"current": quantity(2, "A")}),
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
    "a reason with a next-line control": (
        PATH,
        body(reason="one\x85two"),
        "control",
        dispute.REASON,
    ),
    "a unit with DEL": (PATH, body(unit="V\x7f"), "control", dispute.UNIT),
    # JSON's escape of half a surrogate pair is ASCII on disk and a lone surrogate once read: no
    # line of the run's record can hold it.
    "a reason with a lone surrogate": (PATH, body(reason="a\ud800b"), "control", dispute.REASON),
    "a unit with a lone surrogate": (PATH, body(unit="V\udfff"), "control", dispute.UNIT),
    # With a second fault after it: the parser's own rule refuses the unit before the reason is
    # read, where the model behind it would have refused the unit only after the reason.
    "a unit with a lone surrogate, the reason empty": (
        PATH,
        body(unit="V\udfff", reason=""),
        "control",
        dispute.UNIT,
    ),
    # Characters that change how the text around them reads, or read as a line's end: a format
    # character (a direction override, a zero-width one, a byte-order mark), a line or paragraph
    # separator, a private-use character, and a noncharacter, in the plane-0 block and the last
    # code point. A person reads the reason on an item; none of these is a word to them.
    "a reason with a direction override": (
        PATH,
        body(reason="a\u202eb"),
        "control",
        dispute.REASON,
    ),
    "a reason with a zero-width space": (PATH, body(reason="a\u200bb"), "control", dispute.REASON),
    "a reason with a byte-order mark": (PATH, body(reason="\ufeffab"), "control", dispute.REASON),
    "a reason with a line separator": (PATH, body(reason="a\u2028b"), "control", dispute.REASON),
    "a reason with a paragraph separator": (
        PATH,
        body(reason="a\u2029b"),
        "control",
        dispute.REASON,
    ),
    "a reason with a private-use character": (
        PATH,
        body(reason="a\ue000b"),
        "control",
        dispute.REASON,
    ),
    "a reason with a noncharacter": (PATH, body(reason="a\ufffeb"), "control", dispute.REASON),
    "a reason with a noncharacter of the block": (
        PATH,
        body(reason="a\ufdd0b"),
        "control",
        dispute.REASON,
    ),
    "a reason with the last code point": (
        PATH,
        body(reason="a\U0010ffffb"),
        "control",
        dispute.REASON,
    ),
    "a unit with a zero-width joiner": (PATH, body(unit="V\u200d"), "control", dispute.UNIT),
    "a unit with a line separator": (PATH, body(unit="V\u2028"), "control", dispute.UNIT),
    "a unit with a private-use character": (PATH, body(unit="\ue000"), "control", dispute.UNIT),
    "a unit with a noncharacter": (PATH, body(unit="V\uffff"), "control", dispute.UNIT),
}

#: Cases the change check refuses before it reads a dispute: a path one directory further in is
#: a write outside the module, as any other path under the directory but its own files.
OUT_OF_SCOPE = ("one directory further in",)


@pytest.mark.parametrize("case", REFUSED)
def test_a_malformed_dispute_is_refused_by_the_parser(case: str) -> None:
    path, data, role, said = REFUSED[case]
    try:
        parse(path, data, role, nodes())
        told: Exception | None = None
    except Exception as exc:  # noqa: BLE001 - any other escape is the finding: a refusal is the contract
        told = exc
    assert isinstance(told, DisputeError), repr(told)
    assert said in str(told)


@pytest.mark.parametrize(
    ("data", "said"),
    [(body(reason="a\ud800b"), dispute.REASON), (body(unit="V\udfff"), dispute.UNIT)],
    ids=["the reason", "the unit"],
)
def test_what_the_models_refuse_past_the_parser_s_own_rules_is_a_refusal_naming_its_field(
    monkeypatch: pytest.MonkeyPatch, data: bytes, said: str
) -> None:
    # The parser's character rule as it stood before it named surrogates: the models behind it
    # refuse what it lets through, and that refusal is the dispute's, in the field's own words.
    monkeypatch.setattr(dispute, "_CONTROL", re.compile(r"[\x00-\x1f\x7f-\x9f]"))
    try:
        parse(PATH, data, "control", nodes())
        told: Exception | None = None
    except Exception as exc:  # noqa: BLE001 - any other escape is the finding
        told = exc
    assert isinstance(told, DisputeError), repr(told)
    assert str(told) == said


@pytest.mark.parametrize(
    ("data", "value", "reason"),
    [
        (body(), 24, REASON),
        (body(value=23.5), 23.5, REASON),
        (body(value=-1, reason="r" * 500), -1, "r" * 500),
        (
            body(reason="24\u00a0V, \u00e9t\u00e9, \u03a9, \U0001f642"),
            24,
            "24\u00a0V, \u00e9t\u00e9, \u03a9, \U0001f642",
        ),
        (body(value=BIG), BIG, REASON),
    ],
    ids=[
        "an integer",
        "a float",
        "a negative value, the reason at its bound",
        "letters, symbols and a no-break space",
        "a 400-digit integer",
    ],
)
def test_a_well_formed_dispute_is_its_position_and_its_reason(
    data: bytes, value: float, reason: str
) -> None:
    read = parse(PATH, data, "control", nodes())
    position = QuantityRef(node_id="sizing.bus", name="supply_voltage", value=value, unit="V")
    assert read == Dispute(position=position, reason=reason)
    assert type(read.position.value) is type(value)


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
    try:
        told = through_hook(session(tmp_path, role), "Write", data, path)
    except Exception as exc:  # noqa: BLE001 - an escape is the finding: a refusal is the contract
        told = f"raised {type(exc).__name__}: {exc}"
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


def test_an_edit_of_a_dispute_whose_old_text_the_hook_cannot_find_is_refused(
    tmp_path: Path,
) -> None:
    config = session(tmp_path, "control")
    target = Path(config.worktree) / PATH
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_bytes(body())
    tool_input = {"file_path": str(target), "old_string": "not in it", "new_string": "24"}
    decision = graph.pre_tool_use(
        HookInput.model_validate(
            event(tool_name="Edit", cwd=config.worktree, tool_input=tool_input)
        ),
        config,
    )
    assert (decision.allow, decision.reason) == (False, graph.UNLOCATED.format(found=0))


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
    [c for c in REFUSED if REFUSED[c][2] == "control" and c not in OUT_OF_SCOPE],
)
def test_a_malformed_dispute_is_refused_at_the_change_check_as_the_dispute_s(
    tmp_path: Path, case: str
) -> None:
    path, data, role, said = REFUSED[case]
    run, commit = attempt(tmp_path, "s1", {path: data})
    check: ChangeCheck | str
    try:
        check = checker(tmp_path, run).check("s1", commit, role)
    except Exception as exc:  # noqa: BLE001 - any escape is the finding: a refusal is the contract
        check = f"raised {type(exc).__name__}: {exc}"
    assert isinstance(check, ChangeCheck), check
    assert (check.refused_by, check.subject, check.disputes) == ("dispute", path, ())
    assert str(check.reason).startswith(f"{path}: ") and said in str(check.reason)


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


def test_disputes_are_sorted_by_node_then_quantity_not_by_their_file_names(
    tmp_path: Path,
) -> None:
    # As files, the rail's comes first ("rail" before "supply"); as (node, quantity), the bus's.
    rail = ".physgate/disputes/sizing.bus.rail.current.json"
    run, commit = attempt(tmp_path, "s1", {PATH: body(), rail: body(1, "A")})
    check = checker(tmp_path, run).check("s1", commit, "control")
    assert [(d.position.node_id, d.position.name) for d in check.disputes] == [
        ("sizing.bus", "supply_voltage"),
        ("sizing.bus.rail", "current"),
    ]


def test_a_dispute_committed_executable_is_a_write_outside_the_module(tmp_path: Path) -> None:
    run, _ = attempt(tmp_path, "s1", {PATH: body()})
    worktree = run.subtask_worktree("s1")
    (worktree / PATH).chmod(0o755)
    commit = commit_attempt(worktree, "s1", 2, "sess-2", repo=run.repo)
    check = checker(tmp_path, run).check("s1", commit, "control")
    assert (check.refused_by, check.subject, check.disputes) == ("write_scope", PATH, ())


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


def test_a_dispute_the_run_branch_held_is_withdrawn_by_deleting_it_within_write_scope(
    tmp_path: Path,
) -> None:
    # The deletion is a change from the run branch, so it crosses the write-scope check.
    repo = tmp_path / "target"
    (repo / "modules").mkdir(parents=True)
    (repo / "modules" / "a.txt").write_text("0\n")
    (repo / PATH).parent.mkdir(parents=True)
    (repo / PATH).write_bytes(body())
    _git(repo, "init", "-q", "-b", "main")
    _git(repo, "add", "-A")
    _git(repo, "commit", "-q", "-m", "start")
    run, commit = attempt(tmp_path, "s1", {PATH: None})
    changed = _git(repo, "diff", "--name-status", run.run_branch, commit).splitlines()
    assert f"D\t{PATH}" in changed
    check = checker(tmp_path, run).check("s1", commit, "control")
    assert (check.refused_by, check.reason, check.disputes) == (None, None, ())


# --- a dispute stays on its attempt's branch ----------------------------------------------------


def _merged(run: RunGit, subtask: str, commit: str) -> str:
    """Merge ``commit`` as the loop does; what escaped instead, as text, for the assertion."""
    try:
        return GitMerger(run, removal_timeout_s=30).merge(subtask, 1, commit, f"Merge {subtask}\n")
    except Exception as exc:  # noqa: BLE001 - an escape is the finding: the merge is the contract
        return f"raised {type(exc).__name__}: {exc}"


def test_the_merge_leaves_the_disputes_out_and_a_later_worktree_starts_without_them(
    tmp_path: Path,
) -> None:
    run, commit = attempt(tmp_path, "s1", {PATH: body(reason="the merge's canary")})
    merged = _merged(run, "s1", commit)
    assert not merged.startswith("raised"), merged
    assert _git(run.repo, "rev-parse", f"{merged}^2") == commit
    files = _git(run.repo, "ls-tree", "-r", "--name-only", merged).splitlines()
    assert "modules/s1/notes.md" in files
    assert not [f for f in files if "disputes" in f]
    assert not (run.integration / ".physgate" / "disputes").exists()
    later = run.open_subtask("s2")
    assert (later / "modules" / "s1" / "notes.md").exists()
    assert not (later / ".physgate" / "disputes").exists()
    # The attempt's own commit still holds it: that is what the change check read.
    assert "the merge's canary" in _git(run.repo, "show", f"{commit}:{PATH}")


def test_two_subtasks_disputing_one_quantity_on_open_branches_both_merge(tmp_path: Path) -> None:
    run, first = attempt(tmp_path, "s1", {PATH: body(value=24)})
    _, second = attempt(tmp_path, "s2", {PATH: body(value=30, reason="another")}, number=2)
    check = checker(tmp_path, run)
    assert check.check("s1", first, "control").disputes == (disputed(24),)
    merged_first = _merged(run, "s1", first)
    assert not merged_first.startswith("raised"), merged_first
    # The second subtask's dispute is read from its own commit, whatever the first merged.
    assert [d.position.value for d in check.check("s2", second, "control").disputes] == [30]
    merged = _merged(run, "s2", second)
    assert not merged.startswith("raised"), merged
    assert "disputes" not in _git(run.repo, "ls-tree", "-r", "--name-only", merged)


def test_the_reviewer_s_diff_and_export_leave_the_disputes_out(tmp_path: Path) -> None:
    run, commit = attempt(tmp_path, "s1", {PATH: body(reason="the packet's canary")})
    diff = packet._diff(run.repo, merge_base(run.repo, run.run_branch, commit), commit)  # noqa: SLF001
    assert b"modules/s1/notes.md" in diff
    assert b"disputes" not in diff
    assert b"canary" not in diff
    exported = tmp_path / "export"
    count = packet._export(run.repo, commit, exported)  # noqa: SLF001
    assert (exported / "modules" / "s1" / "notes.md").exists()
    assert not (exported / ".physgate" / "disputes").exists()
    assert count == len([p for p in exported.rglob("*") if p.is_file()])


# --- a name or a text that is not UTF-8 ---------------------------------------------------------


def with_raw_name(repo: Path, commit: str, name: bytes, data: bytes) -> str:
    """A commit on top of ``commit`` that adds ``data`` at ``name``, bytes git takes as they are.

    Built with git's plumbing and an index of its own: a macOS file system refuses such a name
    in a working tree, where Linux, on which runs are made, takes it.
    """
    env = {**_ENV, "GIT_INDEX_FILE": str(repo.parent / "raw-index")}

    def run(*args: str | bytes, stdin: bytes | None = None) -> str:
        done = subprocess.run(
            ["git", *args], cwd=repo, env=env, input=stdin, capture_output=True, check=True
        )
        return done.stdout.decode().strip()

    blob = run("hash-object", "-w", "--stdin", stdin=data)
    run("read-tree", commit)
    run("update-index", "--add", "--cacheinfo", b"100644," + blob.encode() + b"," + name)
    tree = run("write-tree")
    return run("commit-tree", tree, "-p", commit, "-m", "a name that is not UTF-8")


#: Names that are not UTF-8, in the disputes directory and in the module's own directory.
RAW_NAMES = {
    "a dispute": (b".physgate/disputes/sizing.bus.supply_voltage\xff.json", body()),
    "a module file": (b"modules/s1/n\xff.md", b"notes\n"),
}


def checked_line(check: ChangeCheck) -> str:
    """The line the loop writes for ``check``, serialised as the log holds it."""
    line = ProposalsChecked(
        seq=1,
        ts="2026-10-30T00:00:00.000000Z",
        run_id="r1",
        gate_mode="on",
        subtask_id="s1",
        attempt=1,
        checked_commit="0" * 40,
        **check.model_dump(exclude={"declaration", "disputes", "series_checks", "proposed"}),
    )
    return line.model_dump_json()


@pytest.mark.parametrize("case", RAW_NAMES)
def test_a_name_that_is_not_utf8_is_a_write_outside_the_module_never_a_crash(
    tmp_path: Path, case: str
) -> None:
    name, data = RAW_NAMES[case]
    run, commit = attempt(tmp_path, "s1", {})
    raw = with_raw_name(run.repo, commit, name, data)
    check: ChangeCheck | str
    try:
        check = checker(tmp_path, run).check("s1", raw, "control")
    except Exception as exc:  # noqa: BLE001 - any escape is the finding: a refusal is the contract
        check = f"raised {type(exc).__name__}: {exc}"
    assert isinstance(check, ChangeCheck), check
    shown = name.decode("ascii", "backslashreplace")
    assert (check.refused_by, check.subject, check.disputes) == ("write_scope", shown, ())
    assert f"{shown} (not a UTF-8 name)" in str(check.reason)
    # The line the record would hold is text any reader decodes: the name is shown escaped.
    assert shown in json.loads(checked_line(check))["subject"]


class _RealChecks(FakeChanges):
    """The loop's change check as the real checker answers it, for one committed attempt."""

    def __init__(self, real: GitChangeChecker, commit: str) -> None:
        super().__init__()
        self._real, self._commit = real, commit

    def check(
        self,
        subtask_id: str,
        attempt_commit: str,
        role: str,
        *,
        series: Any = None,
    ) -> ChangeCheck:
        self.calls += 1
        return self._real.check(subtask_id, self._commit, role, series=series)


def test_a_run_killed_at_a_name_that_is_not_utf8_resumes_past_it_as_a_refusal(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    name, data = RAW_NAMES["a module file"]
    run, commit = attempt(tmp_path / "git", "s1", {})
    raw = with_raw_name(run.repo, commit, name, data)
    changes = _RealChecks(checker(tmp_path / "git", run), raw)
    models = ModelStrings(
        decomposition="claude-sonnet-5",
        roles={"electrical": "claude-sonnet-5"},
        reviewers={"electrical": "claude-opus-5-5"},
    )
    rig = Rig(tmp_path / "loop", changes=changes, config_overrides={"models": models})
    (tmp_path / "loop").mkdir()
    loop = rig.open()
    emit = loop._emit  # noqa: SLF001 - the loop's own writer

    def dies_at_the_check_s_line(line: Event) -> None:
        if isinstance(line, ProposalsChecked):
            raise KilledError
        emit(line)

    monkeypatch.setattr(loop, "_emit", dies_at_the_check_s_line)
    loop.start(plan("s1"))
    escaped: Exception | None = None
    try:
        loop.run()
    except KilledError:
        pass
    except Exception as exc:  # noqa: BLE001 - a crash before the line is the finding
        escaped = exc
    if escaped is None:
        try:
            rig.open().resume()
        except Exception as exc:  # noqa: BLE001 - a resume that cannot go on is the finding
            escaped = exc
    assert escaped is None, repr(escaped)
    events = read_events(tmp_path / "loop" / "events.jsonl")
    resumed = next(i for i, e in enumerate(events) if e.kind == "resumed")
    checks = [e for e in events[resumed:] if isinstance(e, ProposalsChecked)]
    assert checks
    assert {(c.refused_by, c.subject) for c in checks} == {("write_scope", "modules/s1/n\\xff.md")}
    replay(events)


def test_the_queue_item_s_diff_of_a_text_that_is_not_utf8_is_shown_and_rebuilt_equal(
    tmp_path: Path,
) -> None:
    # git takes a file with no NUL byte as text, so its patch carries the bytes as they are.
    run, commit = attempt(tmp_path, "s1", {"modules/s1/latin.txt": b"caf\xe9\n"})
    merger = GitMerger(run, removal_timeout_s=30)
    try:
        shown: str = merger.artefact_diff(commit)
    except Exception as exc:  # noqa: BLE001 - any escape is the finding: the item is the contract
        shown = f"raised {type(exc).__name__}: {exc}"
    assert not shown.startswith("raised"), shown
    # Each byte that is not UTF-8 shows as its escape, so two different bytes never look alike.
    assert "+caf\\xe9" in shown and "�" not in shown

    def item(diff: str) -> QueueItem:
        return unavailable_item(
            item_id="r1-s1-1",
            run_id="r1",
            subtask_id="s1",
            attempt=1,
            source="review_unavailable",
            cause="timeout",
            detail="no verdict",
            spec_defects=(),
            artefact_diff=diff,
            trajectory="t",
            ts="2026-10-30T00:00:00.000000Z",
        )

    # The item rebuilt at take reads the diff again, and is held equal to the line it wrote.
    written = item(shown)
    assert QueueItem.model_validate_json(written.model_dump_json()) == item(
        merger.artefact_diff(commit)
    )


def test_a_dispute_one_directory_further_in_is_a_write_outside_the_module(
    tmp_path: Path,
) -> None:
    path, data, _, _ = REFUSED["one directory further in"]
    run, commit = attempt(tmp_path, "s1", {path: data})
    check = checker(tmp_path, run).check("s1", commit, "control")
    assert (check.refused_by, check.subject, check.disputes) == ("write_scope", path, ())


def test_a_file_at_the_disputes_directory_s_own_path_is_a_write_outside_the_module_and_unread(
    tmp_path: Path,
) -> None:
    run, commit = attempt(tmp_path, "s1", {DISPUTES: b"free text the reviewer sees\n"})
    check = checker(tmp_path, run).check("s1", commit, "control")
    assert (check.refused_by, check.subject, check.disputes) == ("write_scope", DISPUTES, ())
    # Diff and export leave out the same paths: the directory's own path and all under it.
    diff = packet._diff(run.repo, merge_base(run.repo, run.run_branch, commit), commit)  # noqa: SLF001
    assert b"free text" not in diff
    exported = tmp_path / "export"
    packet._export(run.repo, commit, exported)  # noqa: SLF001
    assert not (exported / DISPUTES).exists()
    assert (exported / "modules" / "s1" / "notes.md").exists()


# --- the unit's kind, checked where the graph's unit is known -----------------------------------


@pytest.mark.parametrize(
    ("unit", "said"),
    [
        ("kg", "not the same kind of unit as V"),
        ("A", "not the same kind of unit as V"),
        ("rad", "not the same kind of unit as V"),
        ("blorp", "blorp"),
    ],
    ids=["a mass", "a current", "an angle", "no unit"],
)
def test_a_dispute_in_a_unit_of_another_kind_is_refused_at_the_change_check(
    tmp_path: Path, unit: str, said: str
) -> None:
    run, commit = attempt(tmp_path, "s1", {PATH: body(unit=unit)})
    check: ChangeCheck | str
    try:
        check = checker(tmp_path, run).check("s1", commit, "control")
    except Exception as exc:  # noqa: BLE001 - any escape is the finding: a refusal is the contract
        check = f"raised {type(exc).__name__}: {exc}"
    assert isinstance(check, ChangeCheck), check
    assert (check.refused_by, check.subject, check.disputes) == ("dispute", PATH, ())
    reason = str(check.reason)
    assert reason.startswith(f"{PATH}: {dispute.KIND.format(unit='V')}"), reason
    assert said in reason


@pytest.mark.parametrize("unit", ["V", "mV", "kV"])
def test_a_dispute_in_a_unit_of_the_node_s_own_kind_is_read_as_written(
    tmp_path: Path, unit: str
) -> None:
    run, commit = attempt(tmp_path, "s1", {PATH: body(value=BIG, unit=unit)})
    check = checker(tmp_path, run).check("s1", commit, "control")
    assert (check.refused_by, check.disputes) == (None, (disputed(BIG, unit=unit),))
    assert type(check.disputes[0].position.value) is int


def test_the_hook_takes_a_unit_of_another_kind_and_never_loads_pint(tmp_path: Path) -> None:
    # The kind needs the unit registry, which costs more to load than a hook may take: the hook
    # holds the dispute's form, and the change check, which has the graph's unit, its kind.
    assert through_hook(session(tmp_path, "control"), "Write", body(unit="kg")) == "allow"
    probe = (
        "import json, sys\n"
        "from physgate.hooks import graph\n"
        "from physgate.orchestrator.dispute import parse\n"
        "node = {'id': 'sizing.bus', 'domain': 'cross', 'kind': 'component', 'quantities': "
        "{'supply_voltage': {'value': 12, 'unit': 'V'}}}\n"
        f"parse({PATH!r}, {body(unit='kg')!r}, 'control', {{'sizing.bus': node}})\n"
        "print('pint' in sys.modules)\n"
    )
    done = subprocess.run(
        [sys.executable, "-c", probe], capture_output=True, text=True, check=True, timeout=60
    )
    assert done.stdout.strip() == "False", done.stderr


# --- the record holds a dispute as the parser does ----------------------------------------------


@pytest.mark.parametrize(
    ("field", "text"),
    [
        ("reason", "a‮b"),
        ("reason", "a b"),
        ("reason", "ab"),
        ("reason", "a﷐b"),
        ("unit", "V​"),
    ],
    ids=["a direction override", "a line separator", "private use", "a noncharacter", "unit"],
)
def test_a_dispute_line_holding_what_the_parser_refuses_does_not_open(
    tmp_path: Path, field: str, text: str
) -> None:
    events = driven(tmp_path, {"s1": TWO})
    lines = [e.model_dump(mode="json") for e in events]
    honest = b"".join(json.dumps(line).encode() + b"\n" for line in lines)
    assert len(parse_events(honest, log="events.jsonl")) == len(events)
    first = at(events, DisputeRecorded)
    if field == "reason":
        lines[first]["reason"] = text
    else:
        lines[first]["position"]["unit"] = text
    data = b"".join(json.dumps(line).encode() + b"\n" for line in lines)
    try:
        parse_events(data, log="events.jsonl")
        opened = True
    except CorruptEventLogError:
        opened = False
    assert not opened


def test_a_400_digit_value_is_recorded_and_read_back_exact(tmp_path: Path) -> None:
    events = driven(tmp_path, {"s1": (disputed(BIG),)})
    read = [e for e in events if isinstance(e, DisputeRecorded)]
    assert [e.position.value for e in read] == [BIG]
    assert type(read[0].position.value) is int


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


def test_a_run_killed_between_two_dispute_lines_resumes_to_both_once_in_order(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    models = ModelStrings(
        decomposition="claude-sonnet-5",
        roles={"electrical": "claude-sonnet-5"},
        reviewers={"electrical": "claude-opus-5-5"},
    )
    changes = FakeChanges()
    changes.disputes["s1"] = TWO
    rig = Rig(tmp_path, changes=changes, config_overrides={"models": models})
    loop = rig.open()
    emit = loop._emit  # noqa: SLF001 - the loop's own writer
    written = [0]

    def dies_at_the_second(line: Event) -> None:
        if isinstance(line, DisputeRecorded):
            if written[0] == 1:
                raise KilledError
            written[0] += 1
        emit(line)

    monkeypatch.setattr(loop, "_emit", dies_at_the_second)
    loop.start(plan("s1"))
    with pytest.raises(KilledError):
        loop.run()
    try:
        rig.open().resume()
        escaped: Exception | None = None
    except Exception as exc:  # noqa: BLE001 - a resume that cannot go on is the finding
        escaped = exc
    assert escaped is None, repr(escaped)
    events = read_events(tmp_path / "events.jsonl")
    last = at(events, ProposalsChecked, nth=-1)
    after = [e for e in events[last + 1 :] if isinstance(e, DisputeRecorded)]
    assert [(e.attempt, e.position) for e in after] == [(1, d.position) for d in TWO]
    replay(events)


#: Disputes the parser refuses, as a checker that let them through would hand them on.
UNRECORDABLE = {
    "the reason": Dispute.model_construct(position=disputed(24).position, reason="a\ud800b"),
    "the unit": Dispute.model_construct(
        position=QuantityRef.model_construct(
            node_id="sizing.bus", name="supply_voltage", value=24, unit="V\udfff"
        ),
        reason=REASON,
    ),
}


@pytest.mark.parametrize("case", UNRECORDABLE)
def test_a_dispute_the_record_cannot_hold_is_the_attempt_s_refusal_not_a_crash(
    tmp_path: Path, case: str
) -> None:
    try:
        events: list[Event] | str = driven(tmp_path, {"s1": (UNRECORDABLE[case],)})
    except Exception as exc:  # noqa: BLE001 - a crash is the finding: a refusal is the contract
        events = f"raised {type(exc).__name__}: {exc}"
    assert isinstance(events, list), events
    first = events[at(events, ProposalsChecked)]
    assert isinstance(first, ProposalsChecked)
    assert (first.refused_by, first.subject) == ("dispute", PATH)
    assert first.reason == f"{PATH}: {dispute.UNRECORDABLE}"
    assert not [e for e in events if isinstance(e, DisputeRecorded)]
    replay(events)


def test_a_run_killed_at_a_dispute_the_record_cannot_hold_resumes_past_it(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    models = ModelStrings(
        decomposition="claude-sonnet-5",
        roles={"electrical": "claude-sonnet-5"},
        reviewers={"electrical": "claude-opus-5-5"},
    )
    changes = FakeChanges()
    changes.disputes["s1"] = (UNRECORDABLE["the reason"],)
    rig = Rig(tmp_path, changes=changes, config_overrides={"models": models})
    loop = rig.open()
    emit = loop._emit  # noqa: SLF001 - the loop's own writer

    def dies_at_the_check_s_line(line: Event) -> None:
        if isinstance(line, ProposalsChecked):
            raise KilledError
        emit(line)

    monkeypatch.setattr(loop, "_emit", dies_at_the_check_s_line)
    loop.start(plan("s1"))
    escaped: Exception | None = None
    try:
        loop.run()
    except KilledError:
        pass
    except Exception as exc:  # noqa: BLE001 - a crash before the line is the finding
        escaped = exc
    if escaped is None:
        try:
            rig.open().resume()
        except Exception as exc:  # noqa: BLE001 - a resume that cannot go on is the finding
            escaped = exc
    assert escaped is None, repr(escaped)
    events = read_events(tmp_path / "events.jsonl")
    resumed = next(i for i, e in enumerate(events) if e.kind == "resumed")
    checks = [e for e in events[resumed:] if isinstance(e, ProposalsChecked)]
    assert checks
    assert {c.refused_by for c in checks} == {"dispute"}
    assert not [e for e in events if isinstance(e, DisputeRecorded)]
    replay(events)


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
