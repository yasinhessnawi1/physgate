"""A series record reaches the outbox only by running a script: the outbox is a refuse-only root.

There is no rule of its own for the outbox. It is a protected root of the hook layer, watched
``none``: the path hook refuses every tool's write into it, and the shell-path hook refuses
every command that names it other than to read it and every redirection into it, with the
normalisation, case folding and link resolution every protected root gets. The sentinel does
not put it back, because a script's own write, which no hook sees, is the one way a record
arrives; the orchestrator admits a record from it only through the collector.

The cases below are every form the reviews of an earlier, separate rule raised: each
redirection form, compound commands, brace expansion, ANSI-C quoting, globs, variables, path
spellings, links, case variants, a relative path after a ``cd`` and an unknown working
directory. They run against the hook layer itself.
"""

from __future__ import annotations

import os
from pathlib import Path

import pytest
from hook_helpers import bash, event

from physgate.hooks import paths, shell_paths
from physgate.hooks.config import HookInput, SessionConfig
from physgate.hooks.settings import InstallRequest, build_config, current_installation

OUTBOX = ".physgate/series"


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
    assert "series outbox" in outbox.reason
    writer = roots[str(Path(config.worktree) / ".physgate" / "lib")]
    assert writer.watch == "revert"


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


#: Why the forms below still reach the outbox, until the hook layer refuses when in doubt. Its
#: other protected roots are put back by the sentinel after such a write; a refuse-only root is
#: not, so the shell layer must refuse what it cannot resolve. The change that does is the hook
#: layer's own, made separately; each case turns this test red the day it lands.
AWAITING_THE_HOOK_LAYER = (
    "the shell layer does not yet refuse a write it cannot resolve into a refuse-only root "
    "(brace expansion, ANSI-C quoting, a path built from variables, an unknown working directory)"
)

AWAITING = [
    "echo '{}' > .physgate/{series,x}/step.json",
    "echo '{}' > .phys{gate,x}/series/step.json",
    "echo '{}' > $'.physgate/series/step.json'",
    "a=.phys; b=gate; echo '{}' > $a$b/series/step.json",
    "cd $(printf .physgate) && echo '{}' > series/step.json",
]


@pytest.mark.xfail(strict=True, reason=AWAITING_THE_HOOK_LAYER)
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


@pytest.mark.xfail(strict=True, reason=AWAITING_THE_HOOK_LAYER)
def test_a_call_whose_working_directory_is_unknown_is_refused(config: SessionConfig) -> None:
    assert _bash(config, "echo '{}' > series/step.json", cwd="relative/somewhere") != "allow"


@pytest.mark.parametrize(
    "command",
    [
        "python3 modules/control/sim.py",
        "cd modules/control && python3 sim.py",
        "cat .physgate/series/earlier.json",
        "cat .physgate/lib/series_writer.py",
        "ls -la .physgate/series",
        "grep -c x .physgate/series/earlier.json",
        "python3 -c 'print(1)' > modules/control/out.txt",
    ],
)
def test_running_a_script_and_reading_the_outbox_are_allowed(
    config: SessionConfig, command: str
) -> None:
    assert _bash(config, command) == "allow", command


def test_the_writer_whose_opening_lines_the_skill_points_to_can_be_read(
    config: SessionConfig,
) -> None:
    writer = f"{config.worktree}/.physgate/lib/series_writer.py"
    assert _tool(config, "Read", writer) == "allow"
    assert _tool(config, "Write", writer) != "allow"
