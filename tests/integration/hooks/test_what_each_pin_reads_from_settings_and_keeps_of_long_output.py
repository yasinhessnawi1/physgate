"""What each pin reads from the generated settings file, and what it keeps of a long command output.

Two measurements per pin, each held to the value measured on that pin:

- **Settings keys.** A session reads its settings from the generated file alone. Whether the
  file's ``effortLevel`` and ``advisorModel`` keys reach the request decides whether the advisor
  and the effort could ever be set there instead of by flag (the harness passes both by flag).
- **Long output.** The survivor reaper's last word is the last line of a command's output, and
  the hook reads it from what the binary keeps. A command printing more than the binary keeps
  shows what is cut: its head or its tail, and how much is left.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest
from fake_messages_api import Script, text, tool
from hook_session import pinned_version, run_session

from physgate.hooks.settings import Installed

pytestmark = pytest.mark.integration

#: Measured per pin: the request's effort and whether an advisor reached it, without and with
#: the two keys in the generated settings file.
SETTINGS_KEYS: dict[str, dict[str, Any]] = {"2.1.301": {}, "2.1.322": {}}

#: Measured per pin: what a role session is told of a 50,000-character output.
LONG_OUTPUT: dict[str, dict[str, Any]] = {"2.1.301": {}, "2.1.322": {}}

START, END = "START-OF-OUTPUT-3e1b", "END-OF-OUTPUT-9a7c"


def _with_keys(installed: Installed, given: dict[str, Any]) -> None:
    settings = dict(given)
    settings.update({"effortLevel": "low", "advisorModel": "claude-fable-5-2"})
    installed.settings_path.write_text(json.dumps(settings))


def _read(tmp_path: Path, *, keys: bool) -> dict[str, Any]:
    run = run_session(
        tmp_path, Script(main=[text("end")]), check_installed=_with_keys if keys else None
    )
    assert run.exit_code == 0, run.stderr
    first = run.api.requests[0]
    effort = first.output_config.get("effort") if isinstance(first.output_config, dict) else None
    advisor = sorted(
        {n for n in first.tool_schemas if "advisor" in n.lower()}
        | {b for b in first.anthropic_beta if "advisor" in b.lower()}
    )
    return {"effort": effort, "advisor": advisor}


def test_what_the_settings_file_s_effort_and_advisor_keys_do_on_each_pin(tmp_path: Path) -> None:
    measured = {
        "without": _read(tmp_path / "without", keys=False),
        "with": _read(tmp_path / "with", keys=True),
    }
    assert measured == SETTINGS_KEYS[pinned_version()], measured


def test_what_a_role_session_is_told_of_a_long_output_on_each_pin(tmp_path: Path) -> None:
    command = f"printf '%s' {START}; head -c 50000 /dev/zero | tr '\\0' a; printf '\\n%s\\n' {END}"
    run = run_session(
        tmp_path, Script(main=[tool("Bash", command=command, description="x"), text("end")])
    )
    assert run.exit_code == 0, run.stderr
    told = run.told_after(1)
    measured = {
        "head kept": START in told,
        "tail kept": END in told,
        "under 31,000 characters": len(told) < 31_000,
    }
    assert measured == LONG_OUTPUT[pinned_version()], (measured, len(told), told[-300:])
