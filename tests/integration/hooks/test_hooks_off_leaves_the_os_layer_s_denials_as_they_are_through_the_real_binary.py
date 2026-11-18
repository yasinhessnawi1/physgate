"""Through the real binary, inside the OS layer: ``hooks: off`` leaves the layer's denials alone.

The arm switches off hooks, not the operating system's layer. A shell command that builds its
paths as it runs, so no hook can read them in its words, writes into each of the four places a
run is judged by: the harness checkout, the run's records, the held-out tier and the secrets.
Inside the layer every write is refused and nothing lands, under ``hooks: on`` and ``hooks: off``
alike, with the same outcome place by place. Without the layer each write lands, which shows the
command reaches every place and that the refusals inside it are the layer's, not a hook's.

As in a real run, the places outside the worktree lie outside every place the layer makes
writable, and the secrets inside it, where a rule of the layer's own denies them.
"""

from __future__ import annotations

import base64
import json
from pathlib import Path
from typing import Any

import pytest
from fake_messages_api import tool
from os_layer_rig import Layout, layer_here, make_layout, python, run_session

from physgate.flags import Hooks

pytestmark = pytest.mark.integration

#: A new file beneath each place, by what it is. ``@O`` is the directory outside the run, ``@R``
#: the run's directory, ``@W`` the worktree, ``@H`` the held-out tier.
PLACES = {
    "the harness checkout": "@O/harness/src/physgate/gate/planted.py",
    "the harness's frozen criteria": "@O/harness/experiments/R-NEW-01/CRITERIA.md",
    "the run's recorded configuration": "@R/run.json",
    "the run's plan record": "@R/decomposition/plan.json",
    "the run's event record": "@R/events.jsonl",
    "the held-out tier": "@H/scenario_02.json",
    "the secrets": "@W/.env",
}


@pytest.fixture
def layer() -> None:
    if not layer_here():
        pytest.skip("the OS layer cannot run here")


def _placed(layout: Layout, path: str) -> str:
    return (
        path.replace("@O", str(layout.outside))
        .replace("@R", str(layout.root / "run"))
        .replace("@W", str(layout.worktree))
        .replace("@H", str(layout.held))
    )


def _fields(layout: Layout) -> dict[str, Any]:
    """The places the layout does not name, as the dispatcher names them for a role session."""
    run = layout.root / "run"
    harness = layout.outside / "harness"
    (harness / "src").mkdir(parents=True, exist_ok=True)
    (harness / "experiments").mkdir(parents=True, exist_ok=True)
    (run / "decomposition").mkdir(parents=True, exist_ok=True)
    return {
        "harness_root": str(harness),
        "extra_protected": (str(layout.common), str(run / "decomposition")),
        "extra_protected_record": (str(run / "events.jsonl"),),
        "withheld": (str(run / "run.json"),),
    }


def _writes(layout: Layout) -> dict[str, object]:
    """One command that writes beneath every place, each path decoded as it runs."""
    encoded = {
        what: base64.b64encode(_placed(layout, path).encode()).decode()
        for what, path in PLACES.items()
    }
    return tool(
        "Bash",
        command=python(
            "import base64, json, os\n"
            f"places = {encoded!r}\n"
            "out = {}\n"
            "for what, enc in places.items():\n"
            "    p = base64.b64decode(enc).decode()\n"
            "    try:\n"
            "        os.makedirs(os.path.dirname(p), exist_ok=True)\n"
            "        with open(p, 'a') as f:\n"
            "            f.write('planted\\n')\n"
            "        out[what] = 'landed'\n"
            "    except OSError:\n"
            "        out[what] = 'refused'\n"
            "print('OUTCOMES ' + json.dumps(out, sort_keys=True))"
        ),
    )


def _outcomes(run: dict[str, Any]) -> dict[str, str]:
    told = run["told"][0]
    line = next(line for line in told.splitlines() if line.startswith("OUTCOMES "))
    outcomes: dict[str, str] = json.loads(line.removeprefix("OUTCOMES "))
    return outcomes


def _planted(layout: Layout) -> set[str]:
    """The places a write landed in, as the files show it."""
    landed = set()
    for what, path in PLACES.items():
        placed = Path(_placed(layout, path))
        if placed.exists() and "planted" in placed.read_text(errors="replace"):
            landed.add(what)
    return landed


def _session(root: Path, hooks: Hooks, *, layer: bool) -> tuple[dict[str, str], set[str]]:
    with make_layout(root / f"{hooks}-{'layer' if layer else 'bare'}") as layout:
        (layout.worktree / ".env").write_text("NOT_A_SECRET=1\n")
        run = run_session(
            layout, [_writes(layout)], layer=layer, hooks=hooks, fields=_fields(layout)
        )
        return _outcomes(run), _planted(layout)


@pytest.mark.usefixtures("layer")
def test_inside_the_layer_no_command_writes_any_of_the_four_places_under_either_arm(
    tmp_path: Path,
) -> None:
    seen = {hooks: _session(tmp_path, hooks, layer=True) for hooks in ("on", "off")}
    for hooks, (outcomes, planted) in seen.items():
        assert outcomes == dict.fromkeys(PLACES, "refused"), hooks
        assert planted == set(), hooks
    assert seen["off"] == seen["on"]


@pytest.mark.usefixtures("layer")
def test_without_the_layer_each_write_lands_which_shows_the_command_reaches_every_place(
    tmp_path: Path,
) -> None:
    # The command's own word: the sentinel may put a protected file back at the session's end.
    outcomes, _ = _session(tmp_path, "off", layer=False)
    assert outcomes == dict.fromkeys(PLACES, "landed")
