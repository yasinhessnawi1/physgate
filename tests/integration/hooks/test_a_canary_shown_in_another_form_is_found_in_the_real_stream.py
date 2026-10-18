"""Through the real binary: a canary a command shows in another form is found in its stream.

The scan reads the stream as the runtime writes it, so this checks it against that very
writing: each command shows a marked file in one form (base64, hex as ``xxd -p`` wraps
it, reversed, upper case, in two halves), the canary is never in the stream verbatim,
and the scan the dispatcher runs finds it. The file is an ordinary one in the worktree,
since what is under test is the scan, not the hooks' refusal of a read.
"""

from __future__ import annotations

from pathlib import Path

import pytest
from fake_messages_api import Script, text, tool
from hook_session import run_session

from physgate.orchestrator.canaries import canary_seen

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
