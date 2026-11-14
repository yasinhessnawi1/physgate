"""What a hook after a shell command is handed of a long output, on each pin.

The survivor reaper's last word is the last line of a command's output, and the hook that reads
it gets only what the binary hands a hook: after a success the first part of the output and, past
the binary's cap, the path of a file holding all of it; after a failure the first and the last
part with a mark between them. The hook's reading of the end rests on those shapes, so they are
measured on each pin, through the real tool path, by putting a command that keeps its input where
the generated commands of the two events stand. Each size is one the hook treats differently:
under the cap, and over it.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest
from fake_messages_api import Script, text, tool
from hook_session import pinned_version, run_session

from physgate.hooks.settings import Installed
from physgate.hooks.survivors import KEPT_CAP, TRUNCATED

pytestmark = pytest.mark.integration

START, END = "START-OF-OUTPUT-5d2e", "END-OF-OUTPUT-b81f"
UNDER, OVER = 20_000, 50_000

#: After a success. Under the cap the hook has the whole output; over it, the head and a file
#: holding all of it inside the session's configuration directory, whose end is the output's.
_SUCCESS = {
    "under the cap": {"head": True, "end": True, "kept at a path": False},
    "over the cap": {
        "head": True,
        "end": False,
        "kept at a path": True,
        "path inside the configuration directory": True,
        "end at the path": True,
    },
}
#: After a failure. Under the cap the part after the mark is the output's real end; over it the
#: end is lost, and what was kept and what was cut come to the cap or more.
_FAILURE = {
    "under the cap": {
        "head": True,
        "end": True,
        "marked": True,
        "kept and cut reach the cap": False,
    },
    "over the cap": {
        "head": True,
        "end": False,
        "marked": True,
        "kept and cut reach the cap": True,
    },
}
#: Measured per pin. 2.1.301's values are the ones the hook was built on.
HANDED: dict[str, dict[str, Any]] = {
    "2.1.301": {"success": _SUCCESS, "failure": _FAILURE},
    "2.1.322": {"success": _SUCCESS, "failure": _FAILURE},
}


def _keeping(kept: Path) -> Any:  # noqa: ANN401 - the harness's settings hook
    def replace(installed: Installed, given: dict[str, Any]) -> None:
        settings = json.loads(json.dumps(given))
        for event in ("PostToolUse", "PostToolUseFailure"):
            for group in settings["hooks"][event]:
                for hook in group["hooks"]:
                    hook["command"] = f"sh -c 'cat > {kept}/{event}.json'"
        installed.settings_path.write_text(json.dumps(settings))

    return replace


def _handed(root: Path, size: int, *, fails: bool) -> dict[str, Any]:
    kept = root / "kept"
    kept.mkdir(parents=True)
    command = (
        f"printf '%s\\n' {START}; head -c {size} /dev/zero | tr '\\0' a; printf '\\n%s\\n' {END}"
        + ("; exit 1" if fails else "")
    )
    run_session(
        root / "session",
        Script(main=[tool("Bash", command=command, description="x"), text("end")]),
        check_installed=_keeping(kept),
    )
    event = "PostToolUseFailure" if fails else "PostToolUse"
    path = kept / f"{event}.json"
    assert path.exists(), f"no {event} hook was handed anything: {sorted(kept.iterdir())}"
    handed: dict[str, Any] = json.loads(path.read_text())
    return handed


def _success(root: Path, size: int) -> tuple[dict[str, Any], dict[str, Any]]:
    handed = _handed(root, size, fails=False)
    response = handed.get("tool_response")
    assert isinstance(response, dict), handed.keys()
    out = str(response.get("stdout") or "") + str(response.get("stderr") or "")
    measured: dict[str, Any] = {"head": START in out, "end": END in out}
    persisted = response.get("persistedOutputPath")
    measured["kept at a path"] = bool(persisted)
    shown: dict[str, Any] = {"keys": sorted(response), "chars": len(out)}
    if persisted:
        config = (root / "session" / "outside" / "claude-config").resolve()
        where = Path(persisted).resolve()
        measured["path inside the configuration directory"] = config in where.parents
        measured["end at the path"] = where.exists() and END in where.read_text()[-200:]
        shown["path"] = str(where.relative_to(config)) if config in where.parents else str(where)
    return measured, shown


def _failure(root: Path, size: int) -> tuple[dict[str, Any], dict[str, Any]]:
    handed = _handed(root, size, fails=True)
    error = str(handed.get("error") or "")
    marks = list(TRUNCATED.finditer(error))
    measured: dict[str, Any] = {
        "head": START in error,
        "end": END in (error[marks[-1].end() :] if marks else error),
        "marked": bool(marks),
    }
    whole = (
        marks[-1].start() + int(marks[-1].group(1)) + len(error) - marks[-1].end()
        if marks
        else len(error)
    )
    measured["kept and cut reach the cap"] = whole >= KEPT_CAP
    shown = {"keys": sorted(handed), "chars": len(error), "kept and cut": whole}
    return measured, shown


def test_what_a_hook_is_handed_after_a_long_output_that_succeeded(tmp_path: Path) -> None:
    under, shown_under = _success(tmp_path / "under", UNDER)
    over, shown_over = _success(tmp_path / "over", OVER)
    measured = {"under the cap": under, "over the cap": over}
    expected = HANDED[pinned_version()]["success"]
    assert measured == expected, json.dumps([measured, shown_under, shown_over])


def test_what_a_hook_is_handed_after_a_long_output_that_failed(tmp_path: Path) -> None:
    under, shown_under = _failure(tmp_path / "under", UNDER)
    over, shown_over = _failure(tmp_path / "over", OVER)
    measured = {"under the cap": under, "over the cap": over}
    expected = HANDED[pinned_version()]["failure"]
    assert measured == expected, json.dumps([measured, shown_under, shown_over])
