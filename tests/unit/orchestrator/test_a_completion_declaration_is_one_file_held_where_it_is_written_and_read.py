"""Integration's completion declaration is one file, held where it is written and where it is read.

The role that owns completion declares which modules are complete in one file of its worktree,
``.physgate/completion/declaration.json``: ``{"complete": [<subtask id>, ...]}``, each module named
by the subtask that planned it. It is held as a node proposal is. The hook checks a Write or Edit of
it before the file exists (its shape, since the hook has no plan) and refuses it from every other
role; a shell command that names the directory is refused unless it only reads; and the change
check reads it from the commit it checks with the one parser, which holds every entry to the plan
and records the digest of the committed bytes. Write scope admits the path for the completion
owner's attempt alone, so another role's declaration is a write outside its module. The owner is
found in the register by what it owns, and a register patched to two owners admits no declaration
anywhere. Integration's prompt, and no other, says where and how to declare.
"""

from __future__ import annotations

import hashlib
import json
import os
import subprocess
import sys
from collections.abc import Callable
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "hooks"))
from hook_helpers import bash, event, make_store, node, write_config  # noqa: E402
from orch_helpers import SCRIPTED_BOUNDS  # noqa: E402

from physgate import roles  # noqa: E402
from physgate.hooks import graph  # noqa: E402
from physgate.hooks.config import HookInput, SessionConfig  # noqa: E402
from physgate.orchestrator import declaration  # noqa: E402
from physgate.orchestrator.apply import GitChangeChecker  # noqa: E402
from physgate.orchestrator.declaration import (  # noqa: E402
    DECLARATION_PATH,
    MAX_BYTES,
    Declaration,
    DeclarationError,
    parse,
    read_shape,
)
from physgate.orchestrator.dispatch import role_prompt  # noqa: E402
from physgate.orchestrator.merge import RunGit, commit_attempt  # noqa: E402
from physgate.orchestrator.ports import ChangeCheck, SessionRequest  # noqa: E402
from physgate.roles import CrossCuttingRole  # noqa: E402

#: A second owner of completion, which only a register patched in a process can hold.
CLOSER = CrossCuttingRole(name="closer", architecture="ARCH-051", owns="completion")
#: The plan: two modules, sizing's closing pass over the first, and integration.
PLANNED = {"s1": "modules/s1", "s2": "modules/s2", "s1c": "modules/s1", "integ": "modules/integ"}

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


def body(*names: object, **extra: object) -> bytes:
    return json.dumps({"complete": list(names), **extra}).encode()


# --- the parser ---------------------------------------------------------------------------------

#: Each refused form, and the words its refusal is told in.
REFUSED: dict[str, tuple[bytes, str]] = {
    "not JSON": (b'{"complete": [', "is JSON, and this one is not"),
    "not an object": (b'["s1"]', "one JSON object with one key"),
    "another key": (body("s1", modules=["s2"]), "one JSON object with one key"),
    "no key": (b"{}", "one JSON object with one key"),
    "not a list": (b'{"complete": "s1"}', "one JSON object with one key"),
    "a number": (body(1), "is not a subtask id"),
    "a name past the id's bound": (body("s" * 65), "is not a subtask id"),
    "a name of other characters": (body("S1"), "is not a subtask id"),
    "a name with a line break after it": (body("s1\n"), "is not a subtask id"),
    "a module twice": (body("s1", "s2", "s1"), "names a module twice"),
    "an unplanned module": (body("s3"), "no subtask of the plan"),
    "the closing pass": (body("s1c"), "a later pass over"),
    "the declaring subtask": (body("integ"), "the declaring subtask"),
    "past the size cap": (body("s1") + b" " * (MAX_BYTES - len(body("s1")) + 1), "at most 4096"),
    "a carriage return": (body("s1").replace(b" ", b"\r\n"), "line feed alone"),
    "a lone carriage return": (body("s1").replace(b" ", b"\r", 1), "line feed alone"),
    "the key twice": (b'{"complete": ["s1"], "complete": ["s2"]}', "one JSON object with one key"),
}


@pytest.mark.parametrize("case", REFUSED)
def test_a_declaration_is_read_as_the_modules_it_names_complete_and_nothing_else(
    case: str,
) -> None:
    data, said = REFUSED[case]
    with pytest.raises(DeclarationError) as refused:
        parse(data, PLANNED, "integ")
    assert said in str(refused.value)


@pytest.mark.parametrize(
    ("data", "modules"),
    [
        (body("s2", "s1"), ("s1", "s2")),  # any order in the file, plan order read
        (body("s2"), ("s2",)),  # a module left out is not declared complete
        (body(), ()),
        # Exactly at the cap.
        (body("s1") + b" " * (MAX_BYTES - len(body("s1"))), ("s1",)),
    ],
    ids=["out of order", "one of two", "none", "at the cap"],
)
def test_a_well_formed_declaration_names_its_modules_in_plan_order_with_its_digest(
    data: bytes, modules: tuple[str, ...]
) -> None:
    read = parse(data, PLANNED, "integ")
    assert read == Declaration(modules=modules, sha256=hashlib.sha256(data).hexdigest())
    assert len(data) <= MAX_BYTES


def test_the_hook_s_shape_check_is_the_parser_s_without_the_plan() -> None:
    # The shape alone: a name of the right form passes, whatever the plan holds.
    assert read_shape(body("s3", "integ")) == ("s3", "integ")
    with pytest.raises(DeclarationError, match="names a module twice"):
        read_shape(body("s3", "s3"))


# --- the hook -----------------------------------------------------------------------------------


def session(tmp_path: Path, role: str) -> SessionConfig:
    home = tmp_path / role
    home.mkdir(parents=True, exist_ok=True)
    return write_config(home, role=role)[2]


def through_hook(
    config: SessionConfig, tool: str, data: str, name: str = "declaration.json"
) -> str:
    """The hook's answer to ``tool`` writing ``data`` into the completion directory."""
    target = Path(config.worktree) / graph.COMPLETION_DIR / name
    if tool == "Write":
        tool_input: dict[str, object] = {"file_path": str(target), "content": data}
    elif tool == "Edit":
        tool_input = {"file_path": str(target), "old_string": "", "new_string": data}
    else:
        tool_input = {"notebook_path": str(target), "new_source": data}
    hook_input = HookInput.model_validate(
        event(tool_name=tool, cwd=config.worktree, tool_input=tool_input)
    )
    decision = graph.pre_tool_use(hook_input, config)
    return "allow" if decision.allow else str(decision.reason)


def through_shell(config: SessionConfig, command: str) -> str:
    decision = graph.pre_tool_use(
        HookInput.model_validate(bash(command, cwd=config.worktree)), config
    )
    return "allow" if decision.allow else str(decision.reason)


WELL_FORMED = body("s1", "s2").decode()


def test_integrations_declaration_is_checked_at_the_hook_before_it_exists(tmp_path: Path) -> None:
    config = session(tmp_path, "integration")
    assert through_hook(config, "Write", WELL_FORMED) == "allow"
    assert through_hook(config, "Edit", WELL_FORMED) == "allow"
    refusal = graph.DECLARATION_REFUSED.format(detail="")
    for data in ('{"complete": "s1"}', "not json", json.dumps({"complete": ["S1"]})):
        said = through_hook(config, "Write", data)
        assert said.startswith(refusal), data
    assert declaration.SHAPE in through_hook(config, "Write", '{"complete": "s1"}')
    # Another file in the directory, and a notebook, are no declaration.
    one_file = f"the one file in {graph.COMPLETION_DIR} is {graph.DECLARATION_NAME}"
    assert one_file in through_hook(config, "Write", WELL_FORMED, "other.json")
    assert one_file in through_hook(config, "NotebookEdit", WELL_FORMED)
    # Nor is the same name one directory further in.
    assert one_file in through_hook(config, "Write", WELL_FORMED, "sub/declaration.json")
    # A key named twice says two things: refused, though JSON would keep the last.
    twice = '{"complete": ["s1"], "complete": ["s2"]}'
    assert declaration.SHAPE in through_hook(config, "Write", twice)
    # A file elsewhere is not this rule's business.
    outside = HookInput.model_validate(
        event(
            tool_name="Write",
            cwd=config.worktree,
            tool_input={"file_path": str(Path(config.worktree) / "x.json"), "content": "{"},
        )
    )
    assert graph.pre_tool_use(outside, config).allow


@pytest.mark.parametrize(
    "command",
    [
        "cat > .physgate/completion/declaration.json <<'EOF'\n" + WELL_FORMED + "\nEOF",
        "echo '" + WELL_FORMED + "' > .physgate/completion/declaration.json",
        "python3 -c \"open('.physgate/completion/declaration.json','w').write('{}')\"",
        "cp /tmp/d.json .physgate/completion/declaration.json",
        "cd .physgate/completion && echo '{}' > declaration.json",
    ],
    ids=["heredoc", "redirect", "in-language write", "copy", "cd and redirect"],
)
def test_a_command_naming_the_completion_directory_is_refused_unless_it_only_reads(
    tmp_path: Path, command: str
) -> None:
    config = session(tmp_path, "integration")
    assert through_shell(config, command) == graph.DECLARATION_SHELL


@pytest.mark.parametrize(
    "command", ["cat .physgate/completion/declaration.json", "ls .physgate/completion", "ls"]
)
def test_a_command_that_only_reads_the_declaration_is_allowed(tmp_path: Path, command: str) -> None:
    assert through_shell(session(tmp_path, "integration"), command) == "allow"


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


def attempt(tmp_path: Path, subtask: str, files: dict[str, bytes]) -> tuple[RunGit, str]:
    """A run whose ``subtask`` committed ``files`` (paths in the worktree) in one attempt."""
    repo = tmp_path / "target"
    (repo / "modules").mkdir(parents=True)
    (repo / "modules" / "a.txt").write_text("0\n")
    _git(repo, "init", "-q", "-b", "main")
    _git(repo, "add", "-A")
    _git(repo, "commit", "-q", "-m", "start")
    run = RunGit(repo=repo, run_dir=tmp_path / "run", run_id="r1")
    run.open_run_branch(_git(repo, "rev-parse", "HEAD"))
    worktree = run.open_subtask(subtask)
    for path, data in files.items():
        (worktree / path).parent.mkdir(parents=True, exist_ok=True)
        (worktree / path).write_bytes(data)
    return run, commit_attempt(worktree, subtask, 1, "sess-1", repo=run.repo)


def checker(tmp_path: Path, run: RunGit) -> GitChangeChecker:
    store = tmp_path / "store"
    make_store(store, node("control.loop", "control"))
    return GitChangeChecker(run, store, dict(PLANNED))


def test_integrations_declaration_is_read_from_its_checked_commit(tmp_path: Path) -> None:
    committed = body("s2", "s1") + b"\n"
    run, commit = attempt(
        tmp_path, "integ", {DECLARATION_PATH: committed, "modules/integ/notes.md": b"x\n"}
    )
    # The working tree moves on after the commit: what is read is what the commit holds.
    (run.subtask_worktree("integ") / DECLARATION_PATH).write_bytes(body("s1"))
    check = checker(tmp_path, run).check("integ", commit, "integration")
    assert (check.refused_by, check.reason) == (None, None)
    expected = Declaration(modules=("s1", "s2"), sha256=hashlib.sha256(committed).hexdigest())
    assert check.declaration == expected
    # And read again, from any commit, by the same reader.
    assert checker(tmp_path / "again", run).declaration_at(commit, "integ") == expected


def test_an_attempt_of_integration_without_a_declaration_declares_nothing(tmp_path: Path) -> None:
    run, commit = attempt(tmp_path, "integ", {"modules/integ/notes.md": b"x\n"})
    check = checker(tmp_path, run).check("integ", commit, "integration")
    assert (check.refused_by, check.declaration) == (None, None)


@pytest.mark.parametrize(
    ("data", "said"),
    [
        (body("s1c"), "a later pass over"),
        (b"not json", "is JSON, and this one is not"),
        (body("s1").replace(b" ", b"\r\n"), "line feed alone"),
        (b'{"complete": ["s1"], "complete": ["s2"]}', "one JSON object with one key"),
        (body("s1") + b"\xff", declaration.NOT_UTF8),
        (b'{"complete": ["s\xe91"]}', declaration.NOT_UTF8),
    ],
    ids=[
        "the closing pass",
        "not JSON",
        "carriage returns",
        "the key twice",
        "a byte after",
        "a byte in a name",
    ],
)
def test_a_malformed_declaration_is_refused_at_the_change_check_as_the_declaration_s(
    tmp_path: Path, data: bytes, said: str
) -> None:
    run, commit = attempt(tmp_path, "integ", {DECLARATION_PATH: data})
    check = refused_or_raised(lambda: checker(tmp_path, run).check("integ", commit, "integration"))
    assert isinstance(check, ChangeCheck), check
    assert (check.refused_by, check.subject, check.declaration) == (
        "declaration",
        DECLARATION_PATH,
        None,
    )
    assert said in str(check.reason)


def refused_or_raised[T](read: Callable[[], T]) -> T | str:
    """What ``read`` gives, or the name of what it raised: a refusal is the contract."""
    try:
        return read()
    except Exception as exc:  # noqa: BLE001 - any escape is the finding
        return f"raised {type(exc).__name__}"


def test_a_declaration_that_is_not_utf8_is_refused_where_it_is_read_again(tmp_path: Path) -> None:
    run, commit = attempt(tmp_path, "integ", {DECLARATION_PATH: body("s1") + b"\xff"})
    again = checker(tmp_path, run)

    def read() -> str:
        try:
            again.declaration_at(commit, "integ")
        except DeclarationError as exc:
            return str(exc)
        return "read"

    assert refused_or_raised(read) == declaration.NOT_UTF8


@pytest.mark.parametrize(
    "path",
    [".physgate/completion/Declaration.json", ".physgate/Completion/declaration.json"],
    ids=["the name", "the directory"],
)
def test_a_case_variant_of_the_declaration_is_a_write_outside_the_module(
    tmp_path: Path, path: str
) -> None:
    # Write scope admits the one path exactly: a variant would merge as a file nothing reads.
    run, commit = attempt(tmp_path, "integ", {path: body("s1")})
    check = checker(tmp_path, run).check("integ", commit, "integration")
    assert (check.refused_by, check.subject, check.declaration) == ("write_scope", path, None)


def test_a_completion_declaration_from_another_role_is_refused_at_hook_and_apply(
    tmp_path: Path,
) -> None:
    config = session(tmp_path / "hook", "control")
    for tool in ("Write", "Edit"):
        said = through_hook(config, tool, WELL_FORMED)
        assert said.startswith(graph.DECLARATION_REFUSED.format(detail=""))
        assert "integration role" in said and "control role" in said
    # Committed past the hook, it is a write outside the attempt's module.
    run, commit = attempt(tmp_path / "apply", "s1", {DECLARATION_PATH: body("s1")})
    check = checker(tmp_path / "apply", run).check("s1", commit, "control")
    assert (check.refused_by, check.subject, check.declaration) == (
        "write_scope",
        DECLARATION_PATH,
        None,
    )


def test_a_declaration_that_is_a_link_is_refused(tmp_path: Path) -> None:
    run, commit = attempt(tmp_path, "integ", {"modules/integ/d.json": body("s1")})
    worktree = run.subtask_worktree("integ")
    (worktree / DECLARATION_PATH).parent.mkdir(parents=True, exist_ok=True)
    os.symlink("../../modules/integ/d.json", worktree / DECLARATION_PATH)
    commit = commit_attempt(worktree, "integ", 2, "sess-2", repo=run.repo)
    check = checker(tmp_path, run).check("integ", commit, "integration")
    assert check.refused_by is not None and check.declaration is None


@pytest.mark.parametrize("layer", ["hook", "change check"])
def test_the_completion_owner_lookup_refuses_two_owners(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, layer: str
) -> None:
    # Past the register's own check, as a patched register is: whose the declaration is cannot
    # be told, and no layer takes the first owner it finds. (The loop's case is with its tests.)
    monkeypatch.setitem(roles.ROLES, CLOSER.name, CLOSER)
    if layer == "hook":
        said = through_hook(session(tmp_path, "integration"), "Write", WELL_FORMED)
        assert said.startswith(graph.DECLARATION_REFUSED.format(detail=""))
        assert "more than one owner of completion" in said
        return
    run, commit = attempt(tmp_path, "integ", {DECLARATION_PATH: body("s1")})
    check = checker(tmp_path, run).check("integ", commit, "integration")
    assert (check.refused_by, check.subject, check.declaration) == (
        "write_scope",
        DECLARATION_PATH,
        None,
    )


@pytest.mark.parametrize("layer", ["hook", "change check"])
def test_a_register_that_names_no_owner_of_completion_admits_no_declaration(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, layer: str
) -> None:
    # Past the register's own check, as a patched register is: with no owner, no role declares.
    config = session(tmp_path, "integration")
    real = roles.owners_of
    monkeypatch.setattr(roles, "owners_of", lambda duty: () if duty == "completion" else real(duty))
    if layer == "hook":
        said = through_hook(config, "Write", WELL_FORMED)
        assert said.startswith(graph.DECLARATION_REFUSED.format(detail=""))
        assert "no registered role owns completion" in said
        return
    run, commit = attempt(tmp_path, "integ", {DECLARATION_PATH: body("s1")})
    check = checker(tmp_path, run).check("integ", commit, "integration")
    assert (check.refused_by, check.subject, check.declaration) == (
        "write_scope",
        DECLARATION_PATH,
        None,
    )


# --- the prompt ---------------------------------------------------------------------------------

REQUEST = SessionRequest(
    subtask_id="integ",
    attempt=1,
    assigned_role="integration",
    spec_path=".physgate/specs/integ.md",
    module_dir="modules/integration",
    model="claude-sonnet-5",
    repair_instruction=None,
    bounds=SCRIPTED_BOUNDS,
)
SENTENCE = (
    "To declare modules complete, write .physgate/completion/declaration.json whole with the "
    'Write tool as {"complete": [...]}, naming each module complete by the subtask id that '
    "planned it; a module it leaves out is not declared complete.\n"
)


def test_integrations_prompt_says_where_and_how_to_declare_and_every_other_prompt_keeps_its_bytes(
    tmp_path: Path,
) -> None:
    state = tmp_path / "issued" / "integration_state.md"
    told = role_prompt(REQUEST, state)
    assert told.endswith("store's id pattern. " + SENTENCE)
    assert told.count("declaration.json") == 1
    # A prompt with no issued state, every other role's, says nothing of a declaration.
    for request in (REQUEST, REQUEST.model_copy(update={"assigned_role": "electrical"})):
        assert "declar" not in role_prompt(request)
