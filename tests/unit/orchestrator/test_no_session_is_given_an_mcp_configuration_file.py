"""No session the harness starts is given an MCP configuration file, on any pin.

A file named to the binary with ``--mcp-config`` was one a sandboxed command could change
on 2.1.301 (fixed in a later version). The harness names none: a session's tools are the
binary's own, offered and refused by the hooks. Held here on the arguments of every kind
of session, so a later change that names one has to meet this row.

The tool layer gives every session ``--strict-mcp-config`` and its configuration inline, as the
argument's own text: with no tool server, the empty configuration. Inline text is no file a
command could change, so the row holds every MCP word to exactly that.
"""

from __future__ import annotations

from pathlib import Path

from physgate.orchestrator.invocation import (
    NO_TOOL_SERVER_ARGS,
    decomposition_argv,
    reviewer_argv,
    role_argv,
)

SPAWN_ARGS = ("--setting-sources", "", "--settings", "/s/settings.json")


def _every_argv(debug_file: Path | None) -> list[list[str]]:
    return [
        role_argv(
            "claude",
            prompt="p",
            spawn_args=SPAWN_ARGS,
            model="claude-opus-5-5",
            session_id="s",
            max_turns=3,
            effort="high",
            thinking_display="summarized",
            debug_file=debug_file,
        ),
        *(
            reviewer_argv(
                "claude",
                prompt="p",
                spawn_args=SPAWN_ARGS,
                schema="{}",
                model="claude-sonnet-5",
                session_id="s",
                max_turns=3,
                effort="high",
                resume=resume,
                debug_file=debug_file,
            )
            for resume in (False, True)
        ),
        decomposition_argv(
            "claude",
            schema="{}",
            model="claude-opus-5-5",
            session_id="s",
            settings=Path("/s/settings.json"),
            effort="high",
            debug_file=Path("/s/debug.log"),
        ),
    ]


def test_no_argument_of_any_session_names_an_mcp_configuration() -> None:
    # With and without the debug file a later pin's sessions carry.
    for debug_file in (None, Path("/s/config/debug.log")):
        for argv in _every_argv(debug_file):
            named = [word for word in argv if "mcp" in word.lower()]
            assert named == list(NO_TOOL_SERVER_ARGS), argv
            assert not [w for w in named if w.startswith(("/", ".", "~", "@"))], argv
