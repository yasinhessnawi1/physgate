"""A refuse-only root inside the worktree is held against every form a review has raised.

A root that is refused and never put back has one layer only, so every way a shell command
could name it has a case here: each redirection form, compound commands and subshells,
writers naming it, path spellings, globs, an assigned path, links, case variants, brace
patterns, ANSI-C quoting, a relative path after a ``cd``, and a call whose working directory
is not absolute. The root is ``.physgate/series`` in a temporary worktree, given to the
session as a refuse-only root; every write is an inert ``{}`` into a marker file.

Two forms stay out of this layer's reach on purpose: a path built from a value known only
at run time and a relative write after ``cd $(…)``. Refusing every word that cannot be
resolved would refuse ordinary commands. A path built from literal assignments in the same
call is resolved exactly, and refused. They are strict expected
failures, so the day a layer closes them the test says so.
"""

from __future__ import annotations

import os
import sys
from pathlib import Path

import pytest
from hook_helpers import bash, event

from physgate.hooks import paths, shell_paths
from physgate.hooks.config import HookInput, SessionConfig
from physgate.hooks.reasons import series_outbox_reason
from physgate.hooks.settings import InstallRequest, build_config, current_installation

OUTBOX = ".physgate/series"
#: The fixture installs without the OS layer, so its reason claims nothing of it.
REASON = series_outbox_reason(sys.platform, os_layer=False)


@pytest.fixture
def config(tmp_path: Path) -> SessionConfig:
    worktree = Path(os.path.realpath(tmp_path)) / "wt"
    (worktree / OUTBOX).mkdir(parents=True)
    (worktree / OUTBOX / "earlier.json").write_text("{}\n")
    (worktree / "modules" / "control").mkdir(parents=True)
    (worktree / "results.json").write_text("{}\n")
    request = InstallRequest(
        profile="role",
        role="control",
        worktree=str(worktree),
        own_branch="b",
        store_root=None,
        state_dir=str(tmp_path / "state"),
        target_dir=str(tmp_path / "target"),
        claude_config_dir=str(tmp_path / "config"),
        user_home=str(tmp_path / "home"),
        token_ceiling=40960,
        extra_protected_refuse_only=(str(worktree / OUTBOX),),
    )
    return build_config(request, current_installation())


def _tool(config: SessionConfig, tool: str, path: str) -> str:
    key = "notebook_path" if tool == "NotebookEdit" else "file_path"
    hook_input = HookInput.model_validate(
        event(
            tool_name=tool,
            cwd=config.worktree,
            tool_input={key: path, "content": "{}", "old_string": "a", "new_string": "b"},
        )
    )
    decision = paths.pre_tool_use(hook_input, config)
    return "allow" if decision.allow else decision.reason


def _bash(config: SessionConfig, command: str, cwd: str | None = None) -> str:
    hook_input = HookInput.model_validate(bash(command, cwd=cwd or config.worktree))
    decision = shell_paths.pre_tool_use(hook_input, config)
    return "allow" if decision.allow else decision.reason


def test_the_outbox_is_a_root_refused_and_never_put_back(config: SessionConfig) -> None:
    roots = {r.path: r for r in config.protected_roots}
    outbox = roots[str(Path(config.worktree) / OUTBOX)]
    assert outbox.watch == "none"
    # The settings name the series outbox themselves, with its own reason, ahead of a root the
    # request adds; before they did, it was the generic reason for a root written at run time.
    assert outbox.reason == REASON


@pytest.mark.parametrize("tool", ["Write", "Edit", "NotebookEdit"])
@pytest.mark.parametrize(
    "path",
    [
        "{w}/.physgate/series/step.json",
        "{w}/.physgate/series",
        "{w}/./.physgate//series/../series/step.json",
        "{w}/.physgate/series/",
        "{w}/modules/../.physgate/series/step.json",
    ],
)
def test_no_tool_writes_into_the_outbox(config: SessionConfig, tool: str, path: str) -> None:
    assert _tool(config, tool, path.format(w=config.worktree)) != "allow"


def test_a_tool_may_write_the_module(config: SessionConfig) -> None:
    target = os.path.join(config.worktree, "modules/control/sim.py")
    assert _tool(config, "Write", target) == "allow"


REFUSED = [
    # every output redirection form
    "echo '{}' > .physgate/series/step.json",
    "echo '{}' >> .physgate/series/step.json",
    "echo '{}' >| .physgate/series/step.json",
    "echo '{}' &> .physgate/series/step.json",
    "echo '{}' &>> .physgate/series/step.json",
    "echo '{}' 2> .physgate/series/step.json",
    "cat 1<> .physgate/series/step.json",
    "cat <<< '{}' > .physgate/series/step.json",
    "cat > .physgate/series/step.json <<'EOF'\n{}\nEOF\n",
    "exec 3> .physgate/series/step.json",
    "echo '{}' | tee >(cat > .physgate/series/step.json)",
    # compound commands and subshells
    "(echo '{}' > .physgate/series/step.json)",
    "{ echo '{}'; } > .physgate/series/step.json",
    "if true; then echo '{}' > .physgate/series/step.json; fi",
    "for x in 1; do echo '{}' > .physgate/series/step.json; done",
    # writers naming it
    "cp results.json .physgate/series/step.json",
    "mv results.json .physgate/series/",
    "echo '{}' | tee .physgate/series/step.json",
    "touch .physgate/series/step.json",
    "ln -s /tmp/elsewhere .physgate/series/link.json",
    "rm -rf .physgate/series",
    "python3 -c \"open('.physgate/series/step.json','w').write('{}')\"",
    "dd if=results.json of=.physgate/series/step.json",
    # spellings and expansions
    "echo '{}' > ./.physgate//series/../series/step.json",
    "echo '{}' > .physgate/series/",
    "echo '{}' > .phys*/series/step.json",
    "echo '{}' > .physgate/series/*.json",
    "d=.physgate/series; echo '{}' > $d/step.json",
    "cd modules/control && echo '{}' > ../../.physgate/series/step.json",
    "cd .physgate && echo '{}' > series/step.json",
]


#: Why the forms below still reach the root: their values exist only at run time (a path
#: built from a substitution, the directory after cd $(...)), and this layer does not refuse a
#: word it cannot resolve. A path built from literal assignments is resolved, and refused.
#: Each case turns this test red the day a layer refuses it.
RESIDUAL = (
    "a word known only at run time (a path built from a substitution, the directory after "
    "cd $(...)) is not resolved by the shell layer, and not refused"
)

RESOLVED = [
    "echo '{}' > .physgate/{series,x}/step.json",
    "echo '{}' > .phys{gate,x}/series/step.json",
    "echo '{}' > $'.physgate/series/step.json'",
    "a=.phys; b=gate; echo '{}' > $a$b/series/step.json",
]

AWAITING = [
    "a=$(printf .phys); b=gate; echo '{}' > $a$b/series/step.json",
    "cd $(printf .physgate) && echo '{}' > series/step.json",
]


@pytest.mark.parametrize("command", RESOLVED)
def test_a_write_the_shell_layer_can_resolve_is_refused(
    config: SessionConfig, command: str
) -> None:
    assert _bash(config, command) != "allow", command


@pytest.mark.xfail(strict=True, reason=RESIDUAL)
@pytest.mark.parametrize("command", AWAITING)
def test_a_write_the_shell_layer_cannot_resolve_is_refused(
    config: SessionConfig, command: str
) -> None:
    assert _bash(config, command) != "allow", command


@pytest.mark.parametrize("command", REFUSED)
def test_a_command_that_writes_into_the_outbox_is_refused(
    config: SessionConfig, command: str
) -> None:
    assert _bash(config, command) != "allow", command


def test_a_link_into_the_outbox_is_judged_as_the_outbox(config: SessionConfig) -> None:
    os.symlink(Path(config.worktree) / OUTBOX, Path(config.worktree) / "out")
    assert _bash(config, "echo '{}' > out/step.json") != "allow"


def test_a_case_variant_names_the_outbox_on_a_case_insensitive_volume(
    config: SessionConfig,
) -> None:
    assert _bash(config, "echo '{}' > .PHYSGATE/SERIES/step.json") != "allow"
    variant = os.path.join(config.worktree, ".PHYSGATE/SERIES/s.json")
    assert _tool(config, "Write", variant) != "allow"


def test_a_call_whose_working_directory_is_unknown_is_refused(config: SessionConfig) -> None:
    assert _bash(config, "echo '{}' > series/step.json", cwd="relative/somewhere") != "allow"


@pytest.mark.parametrize(
    "command",
    [
        "python3 modules/control/sim.py",
        "cd modules/control && python3 sim.py",
        "python3 -c 'print(1)' > modules/control/out.txt",
    ],
)
def test_running_a_script_and_reading_the_writer_are_allowed(
    config: SessionConfig, command: str
) -> None:
    assert _bash(config, command) == "allow", command


@pytest.mark.parametrize(
    "command",
    [
        "cat .physgate/series/earlier.json",
        "ls -la .physgate/series",
        "grep -c x .physgate/series/earlier.json",
    ],
)
def test_reading_the_outbox_back_is_refused(config: SessionConfig, command: str) -> None:
    # A record goes in blind: what a script wrote there is the collector's to judge.
    refused = _bash(config, command)
    assert refused != "allow", command
    assert REASON in refused, command


def test_no_file_tool_reads_the_outbox(config: SessionConfig) -> None:
    record = os.path.join(config.worktree, OUTBOX, "earlier.json")
    assert _tool(config, "Read", record) != "allow"
    writer_dir = os.path.join(config.worktree, ".physgate", "lib", "x.py")
    assert _tool(config, "Read", writer_dir) == "allow"


@pytest.mark.parametrize(
    ("platform", "os_layer", "claims", "never"),
    [
        ("darwin", True, "no command can read it back", "earlier command"),
        ("linux", True, "no command can read back a record an earlier command wrote", "it back"),
        ("darwin", False, "nothing but this refusal", "no command can read"),
        ("linux", False, "nothing but this refusal", "no command can read"),
    ],
)
def test_the_outbox_s_reason_claims_only_what_holds_where_the_session_runs(
    platform: str, os_layer: bool, claims: str, never: str
) -> None:
    # On Linux a command reads back what it wrote itself, so the reason given there may not
    # say that no command can read the outbox; without the OS layer it may say neither.
    reason = series_outbox_reason(platform, os_layer=os_layer)
    assert claims in reason
    assert never not in reason
