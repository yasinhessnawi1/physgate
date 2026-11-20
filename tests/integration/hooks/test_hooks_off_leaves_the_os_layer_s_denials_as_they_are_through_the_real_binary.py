"""Through the real binary, inside the OS layer: ``hooks: off`` leaves the layer's denials alone.

The arm switches off hooks, not the operating system's layer. A shell command that builds its
paths as it runs, so no hook can read them in its words, writes into each of the four places a
run is judged by: the harness checkout, the run's records, the held-out tier and the secrets.
Inside the layer nothing reaches any of them on the disk, under ``hooks: on`` and ``hooks: off``
alike, and the command is told the same outcome place by place under both. Without the layer each
write lands, which shows the command reaches every place and that what keeps it out inside the
layer is the layer, not a hook.

What counts is the place on the disk. Measured on Linux (bubblewrap) on both pins: a write into a
directory whose reads the layer denies (the harness checkout, the held-out tier) is not refused
to the command, yet nothing reaches the directory on the host, and no directory the command made
on the way appears there either (what the command reads back is in the report). A hypothesis, not
confirmed: the layer masks a read-denied directory inside the sandbox's own mount namespace with
an empty mount of its own, so the write lands in a throwaway place that vanishes with the
command. macOS is not measured by these rows: CI runs them on Linux only. The command's own word
is recorded beside the disk, and set ``PHYSGATE_OSLAYER_REPORT`` to a directory to keep it as
JSON.

Without the layer the sentinel puts some protected files back as the session ends, so the
control holds the disk after the session for every place the session's configuration does not
put back, and for the ones it does, the bytes the command read back from the host right after its
write, before any hook could act (no namespace stands between the command and the disk there).
"""

from __future__ import annotations

import base64
import json
import os
from pathlib import Path
from typing import Any

import pytest
from fake_messages_api import tool
from os_layer_rig import Layout, layer_here, make_layout, python, run_session

from physgate.flags import Hooks
from physgate.hooks.config import SessionConfig
from physgate.hooks.settings import CONFIG_NAME

pytestmark = pytest.mark.integration

#: Where the command writes what it was told, in the worktree, which it may write under either arm.
OUTCOMES = "outcomes.json"

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
            "        with open(p) as f:\n"
            "            back = 'planted' in f.read()\n"
            "        out[what] = 'landed' if back else 'written, not read back'\n"
            "    except OSError:\n"
            "        out[what] = 'refused'\n"
            f"open({OUTCOMES!r}, 'w').write(json.dumps(out, sort_keys=True))"
        ),
    )


def _outcomes(layout: Layout) -> dict[str, str]:
    """What the command was told for each place, as it wrote it in the worktree."""
    outcomes: dict[str, str] = json.loads((layout.worktree / OUTCOMES).read_text())
    return outcomes


def _planted(layout: Layout) -> set[str]:
    """The places a write landed in, as the files show it."""
    landed = set()
    for what, path in PLACES.items():
        placed = Path(_placed(layout, path))
        if placed.exists() and "planted" in placed.read_text(errors="replace"):
            landed.add(what)
    return landed


#: Who of the sentinel's watches puts a changed file back as the session ends.
PUT_BACK = ("revert", "halt")


def _put_back(layout: Layout) -> set[str]:
    """The places a protected root the sentinel puts back holds, as the session was installed."""
    config = SessionConfig.model_validate_json((layout.sdir / "session" / CONFIG_NAME).read_bytes())
    return {
        what
        for what, path in PLACES.items()
        if any(
            Path(_placed(layout, path)).is_relative_to(root.path)
            for root in config.protected_roots
            if root.watch in PUT_BACK
        )
    }


Seen = tuple[dict[str, str], set[str], set[str], set[str]]


def _session(root: Path, hooks: Hooks, *, layer: bool) -> Seen:
    """What the command was told, what is on the disk, what it put back, and stray directories."""
    with make_layout(root / f"{hooks}-{'layer' if layer else 'bare'}") as layout:
        (layout.worktree / ".env").write_text("NOT_A_SECRET=1\n")
        fields = _fields(layout)
        missing = {
            what: Path(_placed(layout, path)).parent
            for what, path in PLACES.items()
            if not Path(_placed(layout, path)).parent.exists()
        }
        run_session(layout, [_writes(layout)], layer=layer, hooks=hooks, fields=fields)
        stray = {what for what, parent in missing.items() if parent.exists()}
        return _outcomes(layout), _planted(layout), _put_back(layout), stray


def _report(seen: dict[str, Seen]) -> None:
    where = os.environ.get("PHYSGATE_OSLAYER_REPORT")
    if not where:
        return
    Path(where).mkdir(parents=True, exist_ok=True)
    shown = {
        hooks: {"told": told, "on_the_disk": sorted(planted), "stray_directories": sorted(stray)}
        for hooks, (told, planted, _, stray) in seen.items()
    }
    (Path(where) / "hooks_off_places.json").write_text(json.dumps(shown, indent=2) + "\n")


@pytest.mark.usefixtures("layer")
def test_inside_the_layer_no_command_writes_any_of_the_four_places_under_either_arm(
    tmp_path: Path,
) -> None:
    seen = {hooks: _session(tmp_path, hooks, layer=True) for hooks in ("on", "off")}
    _report(seen)
    for hooks, (told, planted, _, stray) in seen.items():
        assert planted == set(), (hooks, told)
        # Nor did a directory the command made on its way to a place appear on the host.
        assert stray == set(), (hooks, told)
        assert set(told) == set(PLACES), hooks
        # In the worktree the layer's own rule refuses the write outright.
        assert told["the secrets"] == "refused", hooks
    assert seen["off"][0] == seen["on"][0]


@pytest.mark.usefixtures("layer")
def test_without_the_layer_each_write_lands_which_shows_the_command_reaches_every_place(
    tmp_path: Path,
) -> None:
    told, planted, put_back, _ = _session(tmp_path, "off", layer=False)
    # Each write's bytes were read back from the host right after it, before any hook acted.
    assert told == dict.fromkeys(PLACES, "landed")
    # And every place the sentinel does not put back still holds them after the session.
    assert set(PLACES) - put_back, "the sentinel puts every place back; the disk shows nothing"
    assert planted >= set(PLACES) - put_back, (planted, put_back)
