"""The dispatcher's pieces that need no binary: prompt, argv, redaction, the hook log, stop."""

from __future__ import annotations

import json
import re
from pathlib import Path

from loop_fakes import FakeDispatcher, Rig, plan
from orch_helpers import SCRIPTED_BOUNDS

from physgate.orchestrator.dispatch import REDACTED, ClaudeDispatcher, redact, role_prompt
from physgate.orchestrator.events import EnvironmentRecorded, read_events
from physgate.orchestrator.install import InstallFacts, filesystem_of
from physgate.orchestrator.invocation import role_argv
from physgate.orchestrator.ports import SessionRequest, SpawnHook

REQUEST = SessionRequest(
    subtask_id="power-1a2b3c",
    attempt=2,
    assigned_role="electrical",
    spec_path=".physgate/specs/power-1a2b3c.md",
    module_dir="modules/power",
    model="claude-sonnet-5",
    repair_instruction="Attempt 1 of 3 was rejected by the physics gate.",
    bounds=SCRIPTED_BOUNDS,
)


def test_the_role_prompt_is_a_template_naming_the_spec_the_module_and_the_repair() -> None:
    text = role_prompt(REQUEST)
    assert "subtask power-1a2b3c in the electrical role" in text
    assert ".physgate/specs/power-1a2b3c.md" in text and "modules/power/" in text
    assert text.rstrip().endswith("Attempt 1 of 3 was rejected by the physics gate.")
    assert not re.search(r"spec_[A-Z][0-9]|\bD-[A-Z0-9]+-[0-9]|\.docs", text)
    first = role_prompt(REQUEST.model_copy(update={"repair_instruction": None}))
    assert "rejected" not in first


def test_integrations_prompt_names_its_issued_state_and_every_other_prompt_keeps_its_bytes() -> (
    None
):
    path = Path("/run/sessions/s/issued/integration_state.md")
    plain = role_prompt(REQUEST)
    told = role_prompt(REQUEST, path)
    assert role_prompt(REQUEST, None) == plain
    sentence = (
        f"\nYour issued state is {path}; read it in full first too. It is the run's record of "
        "the system-scope result, each module pair's contract results and the system "
        "requirements, written by the harness and by no session.\n"
    )
    # The one sentence, after the template and before any repair instruction.
    assert told == plain.replace("\nAttempt 1 of 3", sentence + "\nAttempt 1 of 3", 1)
    first = REQUEST.model_copy(update={"repair_instruction": None})
    assert role_prompt(first, path) == role_prompt(first) + sentence


def test_the_role_prompt_says_a_simulation_is_recorded_by_a_module_script_through_the_writer() -> (
    None
):
    text = role_prompt(REQUEST.model_copy(update={"repair_instruction": None}))
    sentence = next(line for line in text.split(". ") if "series_writer" in line)
    assert "a script under modules/power/" in sentence
    assert ".physgate/lib/series_writer.py" in sentence and ".physgate/series/" in sentence


def test_the_role_prompt_says_a_proposal_is_written_with_the_write_tool_and_no_script() -> None:
    # The OS layer denies the proposals to every command, so a session told only where to
    # write would find its script refused there.
    text = role_prompt(REQUEST.model_copy(update={"repair_instruction": None}))
    sentence = next(line for line in text.split("; ") if ".physgate/proposals/" in line)
    assert "with the Write tool" in sentence
    assert "no command or script can write there" in sentence


def test_a_role_session_is_never_the_binarys_own_resume() -> None:
    argv = role_argv(
        "/bin/claude",
        prompt="p",
        spawn_args=("--setting-sources", "", "--settings", "/s/settings.json"),
        model="claude-sonnet-5",
        session_id="abc",
        max_turns=20,
        effort="medium",
        thinking_display="summarized",
    )
    assert "--resume" not in argv and "--continue" not in argv
    assert argv[argv.index("--effort") + 1] == "medium"  # the run's level, not the catalog's
    assert argv[argv.index("--thinking-display") + 1] == "summarized"  # the run's, recorded
    assert argv[argv.index("--settings") + 1] == "/s/settings.json"
    assert argv[argv.index("--max-turns") + 1] == "20"
    assert argv[argv.index("--session-id") + 1] == "abc"
    assert "--verbose" in argv and "stream-json" in argv
    assert "--include-partial-messages" in argv  # each message's final usage


def test_the_key_is_redacted_from_the_captured_stream(tmp_path: Path) -> None:
    stream = tmp_path / "stdout.jsonl"
    stream.write_text('{"t": "the key is sk-ant-secret-1 and again sk-ant-secret-1"}\n')
    redact(stream, "sk-ant-secret-1")
    assert "sk-ant-secret-1" not in stream.read_text()
    assert stream.read_bytes().count(REDACTED) == 2


def test_the_hook_log_is_read_for_this_session_only(tmp_path: Path) -> None:
    records = [
        {"session": "mine", "decision": "journal append", "tool": "Bash", "bytes": [10, 90]},
        {"session": "mine", "decision": "node mismatch", "paths": ["n.json"]},
        {"session": "other", "decision": "journal append", "tool": "Bash", "bytes": [1, 2]},
    ]
    (tmp_path / "hooks.log.jsonl").write_text("".join(json.dumps(r) + "\n" for r in records))
    halted, appends = ClaudeDispatcher._hook_log(tmp_path, "mine")
    assert halted and len(appends) == 1 and appends[0].startswith("bytes [10, 90] after Bash")
    assert ClaudeDispatcher._hook_log(tmp_path, "nobody") == (False, ())
    assert ClaudeDispatcher._hook_log(tmp_path / "absent", "mine") == (False, ())


def test_the_reaper_s_unverified_commands_are_read_for_this_session_only(tmp_path: Path) -> None:
    records = [
        {"session": "mine", "decision": "reaper_unverified", "tool_input": {"command": "ls"}},
        {"session": "mine", "decision": "reaped", "tool_input": {"command": "x"}},
        {"session": "other", "decision": "reaper_unverified", "tool_input": {"command": "y"}},
    ]
    (tmp_path / "hooks.log.jsonl").write_text("".join(json.dumps(r) + "\n" for r in records))
    assert ClaudeDispatcher._reaper_unverified(tmp_path, "mine") == ('{"command": "ls"}',)
    assert ClaudeDispatcher._reaper_unverified(tmp_path, "nobody") == ()
    assert ClaudeDispatcher._reaper_unverified(tmp_path / "absent", "mine") == ()


def test_the_state_directory_filesystem_is_found_in_the_mount_table(tmp_path: Path) -> None:
    kind, local = filesystem_of(tmp_path)
    assert kind != "unknown" and isinstance(local, bool)


FACTS = InstallFacts(
    path="/i",
    interpreter="/i/bin/python",
    owner_is_session_user=True,
    files_with_write_bits=0,
    files_with_second_links=0,
    stdlib="/lib",
    stdlib_writable=True,
    state_filesystem="apfs",
    state_on_local_disk=True,
)


class _Recording(FakeDispatcher):
    def environment(self) -> InstallFacts:  # type: ignore[override]
        return FACTS


def test_every_process_that_drives_the_run_records_its_environment(tmp_path: Path) -> None:
    rig = Rig(tmp_path, dispatcher=_Recording())
    loop = rig.open()
    loop.start(plan("s1"))
    loop.run()
    loop.close()
    recorded = [
        e for e in read_events(tmp_path / "events.jsonl") if isinstance(e, EnvironmentRecorded)
    ]
    assert [e.facts for e in recorded] == [FACTS]


def test_a_foreign_journal_line_is_reported_with_what_the_hook_log_saw(tmp_path: Path) -> None:
    from dataclasses import dataclass as _dc
    from typing import Any

    from loop_fakes import FakeGraph

    from physgate.orchestrator.events import Incident
    from physgate.orchestrator.ports import SessionReport

    @_dc
    class Line:
        rev: int = 1
        op: str = "write"
        node_id: str = "electrical.motor"
        payload: Any = None

    class Appending(FakeDispatcher):
        def run(self, request: SessionRequest, on_spawn: SpawnHook | None = None) -> SessionReport:
            report = super().run(request)
            return report.model_copy(
                update={"hook_journal_appends": ("bytes [0, 80] after Bash: printf ...",)}
            )

    class Foreign(FakeGraph):
        def records_after(self, revision: int) -> list[Any]:
            return [Line()] if revision == 0 and self.reopened == 0 and seen else []

    seen: list[int] = []
    graph = Foreign()
    dispatcher = Appending()
    rig = Rig(tmp_path, dispatcher=dispatcher, diff=graph)
    loop = rig.open()
    loop.start(plan("s1"))
    original = dispatcher.run

    def mark(request: SessionRequest, on_spawn: SpawnHook | None = None) -> SessionReport:
        seen.append(1)
        return original(request, on_spawn)

    dispatcher.run = mark  # type: ignore[method-assign]
    assert loop.run().kind == "halted"
    loop.close()
    (incident,) = [e for e in read_events(tmp_path / "events.jsonl") if isinstance(e, Incident)]
    assert "the hook log recorded: bytes [0, 80] after Bash" in incident.detail


def test_an_installation_with_no_interpreter_is_a_domain_error(tmp_path: Path) -> None:
    import pytest

    from physgate.orchestrator.exceptions import InvocationError
    from physgate.orchestrator.install import install_facts

    (tmp_path / "broken" / "bin").mkdir(parents=True)
    with pytest.raises(InvocationError, match="no interpreter"):
        install_facts(tmp_path / "broken", tmp_path / "state")
