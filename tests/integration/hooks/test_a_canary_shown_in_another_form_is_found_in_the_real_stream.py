"""Through the real binary: a canary a command shows in another form is found in its stream.

The scan reads the stream as the runtime writes it, so this checks it against that very
writing: each command shows a marked file in one form (base64, hex as ``xxd -p`` wraps
it, reversed, upper case, in two halves), the canary is never in the stream verbatim,
and the scan the dispatcher runs finds it. The file is an ordinary one in the worktree,
since what is under test is the scan, not the hooks' refusal of a read.
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest
from fake_messages_api import Script, text, tool
from hook_session import pinned_version, run_session

from physgate.orchestrator.canaries import canary_seen
from physgate.orchestrator.dispatch import redact

pytestmark = pytest.mark.integration

CANARY = "0123456789abcdef0011223344556677"
FILES = {"marked.txt": f"line one\nthe answer is 42\n<!-- {CANARY} -->\n"}

COMMANDS = {
    "base64": "base64 < marked.txt",
    "hex": "xxd -p marked.txt",
    "reversed": "rev marked.txt",
    "upper-case": "tr a-f A-F < marked.txt",
    "two-halves": "tail -1 marked.txt | cut -c6-17; echo ---; tail -1 marked.txt | cut -c18-37",
}


@pytest.mark.parametrize("form", sorted(COMMANDS))
def test_the_scan_finds_a_canary_the_stream_shows_in_another_form(
    tmp_path: Path, form: str
) -> None:
    run = run_session(
        tmp_path,
        Script(main=[tool("Bash", command=COMMANDS[form], description=form), text("end")]),
        files=FILES,
    )
    told = run.told_after(1)
    assert told.strip(), "the command showed nothing"
    assert CANARY not in run.raw_stdout, "shown verbatim: the form was not exercised"
    assert canary_seen(run.raw_stdout.encode(), frozenset({CANARY})) == CANARY, told[:300]


#: One character of each class 2.1.311 and later write as a ``\\uXXXX`` escape in the stream,
#: built at run time: DEL, a C1 control, the soft hyphen, a zero-width space, a direction
#: override, a word joiner, a direction isolate and the byte order mark.
INVISIBLE = {
    f"U+{c:04X}": chr(c) for c in (0x7F, 0x85, 0xAD, 0x200B, 0x202E, 0x2060, 0x2066, 0xFEFF)
}
#: Versions that write those characters as escapes (measured at the scripted endpoint);
#: earlier ones write each as itself.
ESCAPES_INVISIBLE = frozenset({"2.1.322"})
#: A stand-in credential, never a real one: the redaction is held to it.
TOKEN = "sk-ant-oat01-" + "stand-in-credential-0123456789-abcdefgh"


def _split(value: str, ch: str) -> str:
    """``value`` with ``ch`` after every eight characters: no run long enough to match whole."""
    return ch.join(value[i : i + 8] for i in range(0, len(value), 8))


@pytest.mark.parametrize("name", sorted(INVISIBLE))
def test_a_canary_and_a_credential_split_by_an_invisible_character_are_found_and_redacted(
    tmp_path: Path, name: str
) -> None:
    ch = INVISIBLE[name]
    line = f"{_split(CANARY, ch)} {_split(TOKEN, ch)}"
    run = run_session(
        tmp_path,
        Script(main=[tool("Bash", command="tail -1 split.txt", description=name), text("end")]),
        files={"split.txt": f"before\n{line}\n"},
    )
    assert run.told_after(1).strip(), "the command showed nothing"
    escaped = f"\\u{ord(ch):04x}"
    # How this pin writes the character in its stream: as an escape, or as itself.
    if pinned_version() in ESCAPES_INVISIBLE:
        assert escaped in run.raw_stdout.lower() and ch not in run.raw_stdout
    else:
        assert ch in run.raw_stdout and escaped not in run.raw_stdout.lower()
    assert canary_seen(run.raw_stdout.encode(), frozenset({CANARY})) == CANARY
    stream = tmp_path / "kept" / "stdout.jsonl"
    stream.parent.mkdir()
    stream.write_text(run.raw_stdout)
    redact(stream, TOKEN)
    kept = stream.read_text()
    # Read back with the character and its escape taken out, the credential is not there.
    visible = re.sub(re.escape(escaped), "", kept.replace(ch, ""), flags=re.IGNORECASE)
    assert TOKEN not in visible, "the split credential was kept"
