"""Required reading, and prose that names forbidden flags, through the real Claude Code binary.

The unit tests prove the reading rule and the git parser on their inputs. These
prove the same two things where they matter, in a session: the rule holds
against the tool calls Claude Code really makes, and the records it keeps are
made from the Read tool's real response, not from a shape assumed for it.
"""

from __future__ import annotations

from pathlib import Path

import pytest
from fake_messages_api import Script, text, tool
from hook_session import run_session

from physgate.hooks import reading

pytestmark = pytest.mark.integration

DOC = "A line of required reading.\n" * 12


def test_a_shell_call_waits_until_both_required_files_are_read(tmp_path: Path) -> None:
    a = tmp_path / "outside" / "docs" / "standards.md"
    b = tmp_path / "outside" / "docs" / "module_spec.md"
    run = run_session(
        tmp_path,
        Script(
            main=[
                tool("Read", file_path=str(a)),
                # Reading the second file through the shell does not count, so
                # this call is refused whole: neither the cat nor the marker runs.
                tool("Bash", command=f"cat {b}; echo early > early.txt", description="x"),
                tool("Read", file_path=str(b)),
                tool("Bash", command="echo done > done.txt", description="x"),
                text("end"),
            ]
        ),
        outside_files={"docs/standards.md": DOC, "docs/module_spec.md": DOC},
        required_reading=(str(a), str(b)),
    )
    assert not (run.worktree / "early.txt").exists()
    assert (run.worktree / "done.txt").read_text() == "done\n"
    refusals = [e for e in run.hook_log if e.get("decision") == "refuse"]
    assert [(e["hook"], e["tool"]) for e in refusals] == [("reading", "Bash")]
    told = run.told_after(2)
    assert "Required reading is not complete" in told
    assert str(b) in told and str(a) not in told


def test_a_document_naming_the_forbidden_flags_can_be_written(tmp_path: Path) -> None:
    # The prose trap: a hook that matches text refuses documents about the
    # thing it forbids. The flags are in the Write's content, never in a command.
    content = (
        "Never run git commit --no-verify, git commit -n, git push --force or\n"
        "git push -f; the hooks refuse each of them as a command.\n"
    )
    doc = tmp_path / "worktree" / "git-rules.md"
    run = run_session(
        tmp_path,
        Script(main=[tool("Write", file_path=str(doc), content=content), text("end")]),
    )
    assert doc.read_text() == content
    assert [e for e in run.hook_log if e.get("decision") == "refuse"] == []
    assert reading.NOT_DONE.split(".")[0] not in run.told_after(1)


def test_a_breach_of_the_ceiling_refuses_every_tool_naming_the_file(tmp_path: Path) -> None:
    # A session-start hook cannot stop a session (measured), so the breach it
    # reports is enforced before every tool call instead.
    loaded = tmp_path / "outside" / "docs" / "standards.md"
    run = run_session(
        tmp_path,
        Script(main=[tool("Bash", command="echo ran > marker.txt", description="x"), text("end")]),
        outside_files={"docs/standards.md": "x" * 200},
        always_loaded=(str(loaded),),
        token_ceiling=100,
    )
    assert not (run.worktree / "marker.txt").exists()
    refusals = [e for e in run.hook_log if e.get("decision") == "refuse"]
    assert ("token_ceiling", "Bash") in [(e["hook"], e["tool"]) for e in refusals]
    told = run.told_after(1)
    assert "over its token ceiling" in told
    assert str(loaded) in told
