"""A skill or mod a session could place never loads, on either pin.

Since 2.1.321 a mod Claude writes turns on without asking in bypass mode, and a headless session
reloads the mods in ``.claude/skills`` when their files change; a mod runs inside the Claude Code
process. A role session must never load one. Four routes are tried on each pin: a skill already
in the worktree when the session starts (as an earlier attempt could have left it); a skill the
session writes there itself, by the file tool and by the shell; a skill it writes outside the
worktree, in its configuration directory or under its home; and a skill already under its home
when it starts. None may reach anything the session is given, which is read from every request
the binary sends.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest
from fake_messages_api import Script, text, tool
from hook_session import pinned_version, run_session

pytestmark = pytest.mark.integration

MARKER = "SKILL-MARKER-c41d77"
SKILL = f"---\nname: probe-skill\ndescription: {MARKER}\n---\n\nSay {MARKER}.\n"


def _place(worktree: Path) -> None:
    path = worktree / ".claude" / "skills" / "probe-skill" / "SKILL.md"
    path.parent.mkdir(parents=True)
    path.write_text(SKILL)


def test_a_skill_already_in_the_worktree_never_reaches_the_session(tmp_path: Path) -> None:
    run = run_session(tmp_path, Script(main=[text("end")]), prepare=_place)
    assert run.exit_code == 0, run.stderr
    assert (run.worktree / ".claude" / "skills" / "probe-skill" / "SKILL.md").exists()  # reached
    assert not any(MARKER in r.body_text for r in run.api.requests)
    (init,) = [e for e in run.stream if e.get("type") == "system" and e.get("subtype") == "init"]
    assert MARKER not in str(init) and "probe-skill" not in str(init)


def test_a_skill_the_session_writes_is_refused_and_never_reaches_it(tmp_path: Path) -> None:
    rel = ".claude/skills/probe-skill/SKILL.md"
    shell = f"mkdir -p .claude/skills/probe-skill && printf '%s' '{SKILL}' > {rel}"
    run = run_session(
        tmp_path,
        Script(
            main=[
                tool("Write", file_path=rel, content=SKILL),
                tool("Bash", command=shell, description="x"),
                text("end"),
            ]
        ),
    )
    assert not (run.worktree / rel).exists()
    later = [r for r in run.api.requests if r.tool_results >= 1]
    assert later, "the session never went on after its first call, so nothing was shown"
    assert not any(MARKER in r.given_text for r in later)
    refusals = [e for e in run.hook_log if e.get("decision") in ("refuse", "put back")]
    assert refusals, "no layer refused or put back the skill"


#: Measured per pin, without the OS layer (macOS and CI, 12.11.2026): which writes of a skill
#: outside the worktree land, by place and by tool. The configuration directory is refused by
#: the hooks; the session's home is a scratch directory its commands may write, and a skill
#: there lands. The binary reads its user's skills from the configuration directory, so one
#: under the home never loads (the row below).
_LANDED = {
    "configuration directory": {"Write": False, "Bash": False},
    "home": {"Write": True, "Bash": True},
}
LANDED: dict[str, dict[str, dict[str, bool]]] = {"2.1.301": _LANDED, "2.1.322": _LANDED}


def _places(root: Path) -> dict[str, Path]:
    outside = root / "outside"
    return {
        "configuration directory": outside / "claude-config" / "skills" / "probe-skill",
        "home": outside / "home" / ".claude" / "skills" / "probe-skill",
    }


def test_where_a_session_can_write_a_skill_outside_its_worktree_on_each_pin(
    tmp_path: Path,
) -> None:
    landed: dict[str, dict[str, bool]] = {}
    shown: dict[str, list[Any]] = {}
    for i, name in enumerate(_places(tmp_path)):
        landed[name] = {}
        for kind in ("Write", "Bash"):
            root = tmp_path / f"{i}-{kind}"
            target = _places(root)[name] / "SKILL.md"
            shell = f"mkdir -p {target.parent} && printf '%s' '{SKILL}' > {target}"
            call = (
                tool("Write", file_path=str(target), content=SKILL)
                if kind == "Write"
                else tool("Bash", command=shell, description="x")
            )
            run = run_session(root, Script(main=[call, text("again"), text("end")]))
            landed[name][kind] = target.exists()
            later = [r for r in run.api.requests if r.tool_results >= 1]
            assert later, "the session never went on after its call, so nothing was shown"
            # Whether or not the write landed, nothing of it is given to the session after it.
            assert not any(MARKER in r.given_text for r in later), (name, kind)
            shown[f"{name}/{kind}"] = [
                (e.get("hook"), e.get("decision")) for e in run.hook_log if e.get("decision")
            ]
    assert landed == LANDED[pinned_version()], json.dumps([landed, shown])


def test_a_skill_under_the_session_s_home_at_its_start_never_reaches_it(tmp_path: Path) -> None:
    def place(worktree: Path) -> None:
        path = _places(worktree.parent)["home"] / "SKILL.md"
        path.parent.mkdir(parents=True)
        path.write_text(SKILL)

    run = run_session(tmp_path, Script(main=[text("end")]), prepare=place)
    assert run.exit_code == 0, run.stderr
    assert (_places(tmp_path)["home"] / "SKILL.md").exists()
    assert not any(MARKER in r.body_text for r in run.api.requests)
    (init,) = [e for e in run.stream if e.get("type") == "system" and e.get("subtype") == "init"]
    assert MARKER not in str(init) and "probe-skill" not in str(init)
