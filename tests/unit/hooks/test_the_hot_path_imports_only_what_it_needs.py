"""An ordinary hook call imports no validation library, no state package, and no heavy stdlib.

Every agent tool call starts a hook process, and a hook has 200 ms. Importing
the validation library and the state package's models cost more than that
budget on the development machine before any check ran, so the hot path holds
to the standard library, and not even all of that. They load only where they
are needed: when a node proposal is written, and when the sentinel checks the
node files after the store changed.

The audit reads the interpreter's own import log (``-X importtime``) from the
generated hook command run as a real process, so it sees every module loaded
from interpreter start to exit, whichever file imported it.
"""

from __future__ import annotations

from pathlib import Path

import pytest
from hook_process import InstalledSession, hot_path_calls, proposal

#: Modules the hot path must not load, by top-level name, and packages by prefix.
KEPT_OFF = (
    *("pydantic", "pydantic_core", "annotated_types", "typing_extensions"),
    *("dataclasses", "pathlib", "shutil"),
)
STATE_PACKAGE = "physgate.state"


def _imported(result_stderr: str) -> set[str]:
    names = set()
    for line in result_stderr.splitlines():
        if line.startswith("import time:") and line.count("|") == 2:
            name = line.rsplit("|", 1)[1].strip()
            if name != "imported package":
                names.add(name)
    return names


def _kept_off(names: set[str]) -> list[str]:
    return sorted(
        n
        for n in names
        if n.split(".")[0] in KEPT_OFF or n == STATE_PACKAGE or n.startswith(STATE_PACKAGE + ".")
    )


@pytest.fixture(scope="module")
def session(tmp_path_factory: pytest.TempPathFactory) -> InstalledSession:
    s = InstalledSession(tmp_path_factory.mktemp("audit"))
    first = s.run("SessionStart", s.event("SessionStart", source="startup"))
    assert first.returncode == 0, first.stderr
    s.read_everything()
    return s


def test_the_session_start_that_takes_the_record_stays_off_them(tmp_path: Path) -> None:
    fresh = InstalledSession(tmp_path)
    done = fresh.run(
        "SessionStart", fresh.event("SessionStart", source="startup"), flags=("-X", "importtime")
    )
    assert done.returncode == 0, done.stderr
    names = _imported(done.stderr)
    assert "physgate.hooks.sentinel" in names
    assert _kept_off(names) == []


def test_every_ordinary_call_stays_off_them(session: InstalledSession) -> None:
    calls = hot_path_calls(session)
    assert len(calls) >= 8
    for label, event, stdin in calls:
        done = session.run(event, stdin, flags=("-X", "importtime"))
        assert done.returncode == 0, (label, done.stderr[-2000:])
        names = _imported(done.stderr)
        # The log was read: the hook package itself is in it.
        assert "physgate.hooks.runtime" in names, label
        assert _kept_off(names) == [], label


def test_a_node_proposal_loads_the_schema_and_nothing_else_does(session: InstalledSession) -> None:
    # The other side of the audit: the one path that needs the schema loads it,
    # so an audit that saw nothing would fail here rather than pass above.
    done = session.run("PreToolUse", proposal(session), flags=("-X", "importtime"))
    assert done.returncode == 0, done.stderr[-2000:]
    names = _imported(done.stderr)
    assert "pydantic" in names
    assert STATE_PACKAGE + ".schema" in names


def test_the_node_check_loads_the_state_package_only_after_the_store_changed(
    session: InstalledSession,
) -> None:
    ordinary = hot_path_calls(session)[0]
    before = session.run(ordinary[1], ordinary[2], flags=("-X", "importtime"))
    assert before.returncode == 0
    assert _kept_off(_imported(before.stderr)) == []
    session.orchestrator_writes_a_node()
    after = session.run(ordinary[1], ordinary[2], flags=("-X", "importtime"))
    assert after.returncode == 0, after.stderr[-2000:]
    assert STATE_PACKAGE in _imported(after.stderr)
    # And once that change has been checked, the next call is back on the lean path.
    settled = session.run(ordinary[1], ordinary[2], flags=("-X", "importtime"))
    assert settled.returncode == 0
    assert _kept_off(_imported(settled.stderr)) == []
