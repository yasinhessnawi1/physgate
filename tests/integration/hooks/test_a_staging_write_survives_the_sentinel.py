"""Through the real binary: `knowledge/staging/` survives a session, the rest of it does not.

Round 1's fix for the whole-tree protection gap (``test_curated_knowledge_content_is_protected.py``)
added ``ProtectedRoot.exceptions`` so ``knowledge/staging/`` is exempt from the
otherwise-whole-tree protection of ``knowledge/``. ``paths.py``'s PreToolUse
layer honoured ``exceptions`` correctly from the start — the existing unit
tests there prove it by calling ``protection()`` directly. But that is only
the first of two layers: ``sentinel.py``'s PostToolUse/SessionEnd layer
snapshots every protected root at the session's first hook and puts back
anything that moved, and until this fix it never learned about ``exceptions``
at all. It snapshotted and reverted the whole ``knowledge/`` tree as one unit,
so a legitimate write to ``staging/`` was reported to the agent as a success
and then silently reverted by the very next hook event — confirmed live,
twice, by an independent review (``PHYSGATE_CLAUDE_BIN`` pinned to 2.1.272).

A unit test that calls ``protection()`` in isolation cannot see this bug: it
only exercises the first layer. These two tests run a real session end to
end, through both layers, the way the reviewer did.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest
from fake_messages_api import Script, text, tool
from hook_session import SessionRun, run_session

from physgate.hooks.registry import REGISTRY

pytestmark = pytest.mark.integration

FILES = {
    "README.md": "a worktree\n",
    "knowledge/control/standards.md": "curated control standards\n",
}


def _placed(step: dict[str, Any], root: Path) -> dict[str, Any]:
    """``@W`` is the worktree ``run_session`` builds under ``root``, in every string of ``step``."""
    raw: dict[str, Any] = json.loads(json.dumps(step).replace("@W", str(root / "worktree")))
    return raw


def _refusals(run: SessionRun) -> list[tuple[str, str]]:
    return [(e["hook"], e["reason"]) for e in run.hook_log if e.get("decision") == "refuse"]


def _put_backs(run: SessionRun) -> list[tuple[str, list[str]]]:
    return [(e["hook"], e["paths"]) for e in run.hook_log if e.get("decision") == "put back"]


def test_a_write_to_knowledge_staging_survives_the_whole_session(tmp_path: Path) -> None:
    """The Write tool lands, no layer refuses it, and the file is still there once the session ends.

    This is ARCH-100's one legitimate write path: a subtask's own outcome
    leaves a candidate in ``knowledge/staging/``, for the human-run promotion
    command to pick up later. If this test fails, the whole staging mechanism
    is broken for any real hook-governed session, exactly as the delta review
    found.
    """
    run = run_session(
        tmp_path,
        Script(
            main=[
                _placed(
                    tool(
                        "Write",
                        file_path="@W/knowledge/staging/skill/probe.json",
                        content='{"id": "probe", "kind": "skill"}\n',
                    ),
                    tmp_path,
                ),
                text("end"),
            ]
        ),
        files=FILES,
    )
    staged = run.worktree / "knowledge" / "staging" / "skill" / "probe.json"
    assert staged.exists(), "the staging write did not survive the session"
    assert staged.read_text() == '{"id": "probe", "kind": "skill"}\n'
    assert _refusals(run) == [], run.hook_log
    assert _put_backs(run) == [], run.hook_log
    assert "put back" not in run.told_after(1)
    assert "put back" not in run.told_after(2)


def test_a_write_elsewhere_in_knowledge_is_still_put_back(tmp_path: Path) -> None:
    """The exclusion is exactly `staging/`, not the whole tree: a write beside it is still reverted.

    Reaches the sentinel specifically, not the ``paths`` PreToolUse layer
    (already proven exact by the bypass suite's ``write-new-domain`` and
    ``redirect-new-domain`` cases): ``shell_paths`` is left out of the
    registry so a plain shell redirect, which that layer would otherwise
    catch first, reaches the sentinel instead — the same technique
    ``test_the_sentinel_alone_puts_back_what_the_parser_missed.py`` uses to
    isolate this layer. A domain with no directory yet is used on purpose,
    the same scenario round 1's own fix was about.
    """
    registry = {k: v for k, v in REGISTRY.items() if k != "shell_paths"}
    run = run_session(
        tmp_path,
        Script(
            main=[
                tool(
                    "Bash",
                    command=(
                        "mkdir -p knowledge/mechanical && "
                        "echo 'a planted rule, never reviewed' > knowledge/mechanical/standards.md "
                        "&& echo ran > ran.txt"
                    ),
                    description="plant a file beside staging/",
                ),
                text("end"),
            ]
        ),
        files=FILES,
        registry=registry,
    )
    assert (run.worktree / "ran.txt").read_text() == "ran\n", "the command did not run"
    planted = run.worktree / "knowledge" / "mechanical" / "standards.md"
    assert not planted.exists(), "a write outside staging/ was not put back"
    events = [e for e in run.hook_log if e.get("hook") == "sentinel"]
    assert any(e["decision"] == "put back" for e in events), run.hook_log
    assert [e for e in run.hook_log if e.get("hook") == "shell_paths"] == []
    assert "put back" in run.told_after(1)
