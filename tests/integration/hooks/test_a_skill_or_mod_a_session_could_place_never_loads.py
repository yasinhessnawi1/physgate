"""A skill or mod a session could place never loads, on either pin.

Since 2.1.321 a mod Claude writes turns on without asking in bypass mode, and a headless session
reloads the mods in ``.claude/skills`` when their files change; a mod runs inside the Claude Code
process. A role session must never load one. Two routes are tried on each pin: a skill already
in the worktree when the session starts (as an earlier attempt could have left it), and a skill
the session writes itself, by the file tool and by the shell. Neither may reach anything the
session is given, which is read from every request the binary sends.
"""

from __future__ import annotations

from pathlib import Path

import pytest
from fake_messages_api import Script, text, tool
from hook_session import run_session

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
