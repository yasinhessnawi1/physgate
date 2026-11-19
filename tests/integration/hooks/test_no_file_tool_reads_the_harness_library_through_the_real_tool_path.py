"""Through the real binary: no file tool of a role session reads the harness checkout's library.

A role session is given its role's skill and standards in its own worktree, or, in an arm that
leaves the skill out, the standards alone. The checkout the orchestrator runs from holds the whole
curated library too, every role's skill among it. The OS layer denies a shell command's read of
that checkout, but a file tool runs in the binary's own process, outside the layer, so the hook is
the only thing between a Read and the harness's copy. Before this, the hook refused only writes
there, and a Read of the harness's skill file came back whole.

Here the harness is a stand-in tree beside the worktree, never this repository's own checkout.
Each file there carries a marker built at run time; a row passes only if the marker is in no
request the session sent after its call, whatever refused the call. Under both hook arms, and
whether or not the worktree holds its own copy of the skill (the two skill arms), the Read tool is
refused by the path hook naming the checkout. The binary under test offers no Grep or Glob tool to
a role session; a call to either is refused before it runs, by the binary or by the closed tool
list, and the marker reaches the session neither way. Without the OS layer, as here, a shell
command that names the harness's skill file is refused by the hooks too.
"""

from __future__ import annotations

import secrets
from pathlib import Path
from typing import Any

import pytest
from fake_messages_api import Script, text, tool
from hook_session import SessionRun, check_the_run_means_something, run_session

from physgate.hooks.reasons import HARNESS_REASON

pytestmark = pytest.mark.integration

#: The stand-in harness, relative to the session's root: beside the worktree.
HARNESS_REL = "outside/harness"
SKILL = "knowledge/control/skill.md"
STANDARDS = "knowledge/control/standards.md"
TARGETS = {"skill": SKILL, "standards": STANDARDS}
#: How a call the binary itself refuses before any hook is answered.
INPUT_REFUSED = "<tool_use_error>"
CLOSED_LIST = "is not available to a role session"


def _marker(what: str) -> str:
    return f"{what}-marker-{secrets.token_hex(8)}"


def _session(
    root: Path, steps: list[dict[str, Any]], *, hooks: str, own_skill: bool
) -> tuple[SessionRun, dict[str, str]]:
    markers = {rel: _marker(name) for name, rel in TARGETS.items()}
    harness = root / HARNESS_REL
    worktree_files = {"README.md": "a worktree\n", STANDARDS: "# Control standards\n"}
    if own_skill:
        worktree_files[SKILL] = "# Control skill\n"
    run = run_session(
        root,
        Script(main=[*steps, text("end")]),
        files=worktree_files,
        outside_files={f"harness/{rel}": f"# {rel}\n{markers[rel]}\n" for rel in TARGETS.values()},
        profile="role",
        role="control",
        hooks=hooks,
        harness_root=str(harness),
    )
    check_the_run_means_something(run)
    return run, markers


def _reached(run: SessionRun, markers: dict[str, str]) -> list[str]:
    """Each marker found in any request the session sent: what of the harness it was told."""
    return [m for m in markers.values() if any(m in r.body_text for r in run.api.requests)]


ARMS = [
    pytest.param("on", True, id="hooks-on-skill-in-worktree"),
    pytest.param("on", False, id="hooks-on-no-skill-in-worktree"),
    pytest.param("off", True, id="hooks-off-skill-in-worktree"),
    pytest.param("off", False, id="hooks-off-no-skill-in-worktree"),
]


@pytest.mark.parametrize(("hooks", "own_skill"), ARMS)
@pytest.mark.parametrize("target", sorted(TARGETS))
def test_under_any_arm_the_read_tool_cannot_read_the_harness_s_library(
    tmp_path: Path, hooks: str, own_skill: bool, target: str
) -> None:
    path = str(tmp_path / HARNESS_REL / TARGETS[target])
    run, markers = _session(
        tmp_path, [tool("Read", file_path=path)], hooks=hooks, own_skill=own_skill
    )
    assert _reached(run, markers) == [], f"a Read of the harness's {target} file came back"
    refusals = [
        (e["hook"], e["reason"])
        for e in run.hook_log
        if e.get("decision") == "refuse" and e.get("tool") == "Read"
    ]
    assert refusals and all(
        hook == "paths" and HARNESS_REASON in reason for hook, reason in refusals
    ), f"the Read of the harness's {target} file was not refused for the checkout: {refusals}"
    assert HARNESS_REASON in run.told_after(1)


SEARCHES = {
    "Grep": lambda root: {"pattern": "marker", "path": str(root / HARNESS_REL / "knowledge")},
    "Glob": lambda root: {"pattern": "**/*.md", "path": str(root / HARNESS_REL / "knowledge")},
}


@pytest.mark.parametrize(("hooks", "own_skill"), ARMS)
@pytest.mark.parametrize("name", sorted(SEARCHES))
def test_under_any_arm_a_search_tool_cannot_read_the_harness_s_library(
    tmp_path: Path, hooks: str, own_skill: bool, name: str
) -> None:
    run, markers = _session(
        tmp_path, [tool(name, **SEARCHES[name](tmp_path))], hooks=hooks, own_skill=own_skill
    )
    assert _reached(run, markers) == [], f"a {name} of the harness's library came back"
    told = run.told_after(1)
    harness = str(tmp_path / HARNESS_REL)
    assert str(Path(harness) / SKILL) not in told, f"a {name} listed the harness's skill file"
    assert INPUT_REFUSED in told or CLOSED_LIST in told or HARNESS_REASON in told, (
        f"the {name} call was not refused: {told[:400]!r}"
    )


@pytest.mark.parametrize(("hooks", "own_skill"), ARMS)
def test_without_the_os_layer_a_command_naming_the_harness_s_skill_file_is_refused(
    tmp_path: Path, hooks: str, own_skill: bool
) -> None:
    # This session runs without the OS layer, as every row of this file does: nothing but the
    # hooks stands between a command and the checkout. Inside the layer the layer denies it.
    path = str(tmp_path / HARNESS_REL / SKILL)
    run, markers = _session(
        tmp_path,
        [tool("Bash", command=f"cat {path}", description="read")],
        hooks=hooks,
        own_skill=own_skill,
    )
    assert _reached(run, markers) == [], "a command read the harness's skill file"
    assert HARNESS_REASON in run.told_after(1)
