"""Every protected root, by every route, for the role, the reviewer and the raw agent.

A protection that holds on one route and not another is not a protection. For one
request that touches every kind of root, this asks each route what it does with a file
under each root, for each of the three profiles that do or judge design work, and holds
the answers to a table written out by hand:

- the file tools: Read, Write and Edit (the ``paths`` hook);
- the shell: a ``cat`` of the file and a redirect onto it (the ``shell_paths`` hook);
- the OS layer: whether the generated sandbox denies the file to shell reads and writes;
- the sentinel: how a change to the root is watched after a call.

``R`` is refused and ``A`` allowed; ``T``/``F`` say whether the OS layer denies; ``-`` is
a route the profile does not have (a reviewer has no shell, so no OS layer). The raw
agent's row differs from the role's only where the harness's design discipline is.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest
from hook_helpers import event

from physgate.hooks import paths, shell_paths, tools
from physgate.hooks.config import HookInput, SessionConfig
from physgate.hooks.settings import InstallRequest, build_config, current_installation
from physgate.oslayer.policy import sandbox_policy

#: Each kind of root, as a file beneath it, relative to the request's base directory.
FILES = {
    "held_out": "heldout/scenario.json",
    "answer_key": "keys/answers.json",
    "review_root": "reviews/packet/rubric.md",
    "library_rubric": "run/wt/knowledge/reviewers/control.md",
    "gate_source": "run/wt/src/physgate/gate/check.py",
    "hook_source": "run/wt/src/physgate/hooks/paths.py",
    "knowledge": "run/wt/knowledge/control/skill.md",
    "series_writer": "run/wt/.physgate/lib/series_writer.py",
    "series_outbox": "run/wt/.physgate/series/r.json",
    "settings_dir": "run/wt/.claude/settings.json",
    "env_file": "run/wt/.env",
    "experiment_criteria": "run/wt/experiments/R-X-01/CRITERIA.md",
    "session_files": "outside/session/settings.json",
    "state_dir": "outside/state/log.jsonl",
    "config_dir": "outside/config/credentials.json",
    "store": "run/store/journal.jsonl",
    "git_user_config": "outside/home/.gitconfig",
    "harness_checkout": "harness/src/physgate/gate/check.py",
    "ordinary": "run/wt/modules/control/loop.py",
}

#: ``tool read, tool write, tool edit, shell read, shell write, OS denies read,
#: OS denies write, sentinel watch``.
ROLE = {
    "held_out": "R R R R R T T revert",
    "answer_key": "A R R A R T T revert",
    # A further review root is withheld, not watched: the hooks refuse it on both routes and
    # the OS layer denies both, but the sentinel does not put it back.
    "review_root": "R R R R R T T -",
    "library_rubric": "R R R R R T T revert",
    "gate_source": "A R R A R F T revert",
    "hook_source": "A R R A R F T revert",
    "knowledge": "A R R A R F T revert",
    "series_writer": "A R R A R F T revert",
    # Only a script's own write reaches the outbox (the OS layer allows it); the hooks
    # refuse every tool and shell write to it.
    "series_outbox": "A R R A R F F none",
    "settings_dir": "A R R A R F T revert",
    "env_file": "A R R A R F T revert",
    "experiment_criteria": "A R R A R F T -",
    "session_files": "A R R A R F T revert",
    "state_dir": "A R R A R T T none",
    "config_dir": "A R R A R T T none",
    "store": "A R R A R F T journal",
    "git_user_config": "A R R A R F T revert",
    "harness_checkout": "A R R A R T T revert",
    "ordinary": "A A A A A F F -",
}
#: The raw agent: the role's row, without the harness's discipline over a design worktree.
BASELINE = {
    **ROLE,
    "gate_source": "A A A A A F F -",
    "hook_source": "A A A A A F F -",
    "knowledge": "A A A A A F F -",
    # The library's rubrics are still withheld from the raw agent; only the knowledge
    # tree's revert, which covered them for a role, is gone with the rest of the library.
    "library_rubric": "R R R R R T T -",
    "series_writer": "A A A A A F F -",
    "series_outbox": "A A A A A F F -",
    "git_user_config": "A A A A A F F -",
}
#: The reviewer reads only beneath its allowance (``run``) and has no shell.
REVIEWER = {
    "held_out": "R R R - - - - revert",
    "answer_key": "R R R - - - - revert",
    "review_root": "R R R - - - - -",
    "library_rubric": "A R R - - - - revert",
    "gate_source": "A R R - - - - revert",
    "hook_source": "A R R - - - - revert",
    "knowledge": "A R R - - - - revert",
    "series_writer": "A R R - - - - revert",
    "series_outbox": "A R R - - - - none",
    "settings_dir": "A R R - - - - revert",
    "env_file": "A R R - - - - revert",
    "experiment_criteria": "A R R - - - - -",
    "session_files": "R R R - - - - revert",
    "state_dir": "R R R - - - - none",
    "config_dir": "R R R - - - - none",
    "store": "A R R - - - - journal",
    "git_user_config": "R R R - - - - -",
    "harness_checkout": "R R R - - - - revert",
    "ordinary": "A R R - - - - -",
}
EXPECTED = {"role": ROLE, "baseline": BASELINE, "reviewer": REVIEWER}


def _config(base: Path, profile: str) -> SessionConfig:
    wt = base / "run" / "wt"
    for d in (wt, base / "harness" / "src" / "physgate" / "gate", base / "reviews"):
        d.mkdir(parents=True, exist_ok=True)
    for rel in FILES.values():
        # Every file exists, so the OS layer's policy, which names what is there, sees it.
        (base / rel).parent.mkdir(parents=True, exist_ok=True)
        (base / rel).touch()
    reviewer = profile == "reviewer"
    request = InstallRequest(
        profile=profile,  # type: ignore[arg-type]
        role="control" if profile == "role" else None,
        worktree=str(wt),
        own_branch=None,
        store_root=str(base / "run" / "store"),
        state_dir=str(base / "outside" / "state"),
        target_dir=str(base / "outside" / "session"),
        claude_config_dir=str(base / "outside" / "config"),
        user_home=str(base / "outside" / "home"),
        token_ceiling=40960,
        held_out=(str(base / "heldout"),),
        answer_keys=(str(base / "keys"),),
        harness_root=str(base / "harness"),
        read_roots=(str(base / "run"),) if reviewer else (),
        extra_review_material=() if reviewer else (str(base / "reviews"),),
    )
    return build_config(request, current_installation())


def _decide(hook: object, config: SessionConfig, wt: Path, **call: Any) -> str:  # noqa: ANN401
    """``A`` only if the closed tool list and ``hook`` both let the call through."""
    hook_input = HookInput.model_validate(event(cwd=str(wt), **call))
    allowed = (
        tools.pre_tool_use(hook_input, config).allow
        and hook.pre_tool_use(  # type: ignore[attr-defined]
            hook_input, config
        ).allow
    )
    return "A" if allowed else "R"


def _under(path: str, roots: list[str]) -> str:
    return "T" if any(Path(path).is_relative_to(Path(r)) for r in roots) else "F"


def _watch(config: SessionConfig, path: str) -> str:
    holding = [r for r in config.protected_roots if Path(path).is_relative_to(Path(r.path))]
    if not holding:
        return "-"
    return max(holding, key=lambda r: len(r.path)).watch


def _row(base: Path, config: SessionConfig, profile: str, path: str) -> str:
    wt = Path(config.worktree)
    cells = [
        _decide(paths, config, wt, tool_name="Read", tool_input={"file_path": path}),
        _decide(
            paths, config, wt, tool_name="Write", tool_input={"file_path": path, "content": "x"}
        ),
        _decide(
            paths,
            config,
            wt,
            tool_name="Edit",
            tool_input={"file_path": path, "old_string": "a", "new_string": "b"},
        ),
    ]
    if profile == "reviewer":
        cells += ["-", "-", "-", "-"]
    else:
        bash = {"tool_name": "Bash"}
        cells += [
            _decide(shell_paths, config, wt, **bash, tool_input={"command": f"cat {path}"}),
            _decide(shell_paths, config, wt, **bash, tool_input={"command": f"echo x > {path}"}),
        ]
        fs = sandbox_policy(config, home=str(base / "outside" / "home"), temp_dir="/tmp/pg-1")
        filesystem = fs.settings["sandbox"]["filesystem"]
        cells += [_under(path, filesystem["denyRead"]), _under(path, filesystem["denyWrite"])]
    cells.append(_watch(config, path))
    return " ".join(cells)


@pytest.mark.parametrize("profile", ["role", "baseline", "reviewer"])
def test_every_protection_holds_on_every_route_as_the_table_says(
    tmp_path: Path, profile: str
) -> None:
    base = tmp_path.resolve()
    config = _config(base, profile)
    actual = {kind: _row(base, config, profile, str(base / rel)) for kind, rel in FILES.items()}
    expected = EXPECTED[profile]
    differences = {
        kind: f"expected {expected[kind]!r}, is {actual[kind]!r}"
        for kind in FILES
        if actual[kind] != expected[kind]
    }
    assert differences == {}


def test_the_raw_agent_and_the_role_are_held_alike_on_the_held_out_tier_by_every_route(
    tmp_path: Path,
) -> None:
    base = tmp_path.resolve()
    rows = {
        p: _row(base, _config(base / p, p), p, str(base / p / FILES["held_out"]))
        for p in ("role", "baseline")
    }
    assert rows["role"] == rows["baseline"] == "R R R R R T T revert"
