"""Which layer refuses a removal of the home directory, on each pin.

A session's home is a scratch directory made for it, which its commands may write: the hooks
protect named paths inside it, not the directory. The binary has a refusal of its own for an
``rm`` of a home directory, which holds even while permissions are bypassed. A refusal is counted
for the layer that made it, so the order is measured on each pin: a session asks for its home to
be removed, in each form a shell gives it, and for each call the stream says whether the
generated command before the tool was started, the hook layer's own log says whether a hook
refused, and what the session is told says whether the binary did. The directory must still be
there, whoever refused.

Before any removal is asked for, a session's shell is shown to name the scratch directory as its
home; if it names any other, nothing here goes on.
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

REMOVALS = ("rm -rf ~", 'rm -rf "$HOME"', "rm -rf ~/", "rm -rf $HOME/*")
#: The binary's own words when it refuses the removal itself.
BINARY_REFUSED = "Dangerous rm operation detected"

#: Measured per pin (macOS and CI, 12.11.2026): the hooks are asked first and let the call
#: through, the home being the session's own to write; the binary then refuses it itself.
_THE_BINARY = dict.fromkeys(REMOVALS, {"the hook was asked": True, "refused by": "the binary"})
ANSWERED: dict[str, dict[str, Any]] = {"2.1.301": _THE_BINARY, "2.1.322": _THE_BINARY}


def _home(root: Path) -> Path:
    return root / "outside" / "home"


def _fill(root: Path) -> Any:  # noqa: ANN401 - the harness's settings hook
    def fill(installed: Installed, given: dict[str, Any]) -> None:
        kept = _home(root) / "kept"
        kept.mkdir(parents=True)
        (kept / "file.txt").write_text("kept\n")

    return fill


def _the_shell_s_home_is_the_scratch_one(root: Path) -> None:
    """Refuse to go on unless a session's shell names the scratch directory as its home."""
    command = 'echo ~ "$HOME" > home.txt'
    run = run_session(
        root, Script(main=[tool("Bash", command=command, description="x"), text("end")])
    )
    home = str(_home(root))
    assert (run.worktree / "home.txt").read_text().split() == [home, home]


def test_which_layer_refuses_each_form_of_the_removal(tmp_path: Path) -> None:
    _the_shell_s_home_is_the_scratch_one(tmp_path / "home")
    measured: dict[str, Any] = {}
    shown: dict[str, Any] = {}
    for i, removal in enumerate(REMOVALS):
        root = tmp_path / str(i)
        run = run_session(
            root,
            Script(main=[tool("Bash", command=removal, description="x"), text("end")]),
            check_installed=_fill(root),
        )
        assert (_home(root) / "kept" / "file.txt").read_text() == "kept\n", removal
        hooks = sorted({str(e.get("hook")) for e in run.hook_log if e.get("decision") == "refuse"})
        told = run.told_after(1)
        measured[removal] = {
            "the hook was asked": run.hook_commands_started()["PreToolUse:Bash"] == 1,
            "refused by": "a hook" if hooks else "the binary" if BINARY_REFUSED in told else "?",
        }
        shown[removal] = {"hooks": hooks, "told": told[:200]}
    assert measured == ANSWERED[pinned_version()], json.dumps([measured, shown])
