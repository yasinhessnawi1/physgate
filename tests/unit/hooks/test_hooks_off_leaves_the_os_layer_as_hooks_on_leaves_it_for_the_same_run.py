"""``hooks: off`` leaves the OS layer exactly as ``hooks: on`` leaves it, for the same run.

The arm switches off hooks, not the operating system's layer: what the layer denies a role
session does not depend on the arm. One run is installed here as the dispatcher installs a role
session of it, once as recorded with ``hooks: on`` and once as recorded with ``hooks: off``, in
the same place:

- the dispatcher gives the installer the same command under both but for the arm's word and the
  record it names, so nothing the layer is made of (the held-out tier, the run's records, the
  harness checkout, the network, the session's own directories) is given differently;
- the installer, given each command, writes the same sandbox settings, compared byte for byte,
  whichever of the two is installed first, and spawns the session the same way; the settings
  differ in the hook commands alone;
- the four places a run is judged by, the harness checkout, the run's records, the held-out
  places and the secrets, are held alike for a file beneath each: by the same hook root, and by
  the same OS-layer rules, which deny every shell command a write there.
"""

from __future__ import annotations

import argparse
import json
import os
import shutil
import subprocess
import sys
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest

# A run's recorded configuration, as the dispatcher and the installer read it.
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "orchestrator"))
from orch_helpers import CLEAN_HARNESS, SCRIPTED_BOUNDS, make_config  # noqa: E402

from physgate.flags import Hooks
from physgate.hooks.cli import add_parser
from physgate.hooks.config import SessionConfig
from physgate.hooks.settings import CONFIG_NAME
from physgate.orchestrator import dispatch
from physgate.orchestrator.credentials import Credential
from physgate.orchestrator.dispatch import ClaudeDispatcher
from physgate.orchestrator.ports import SessionRequest
from physgate.orchestrator.run_config import RunConfig, write_run_config

#: The session's own temporary directory, as the dispatcher makes one, the OS layer's.
OWN_TEMP = Path("/var/tmp/pgs/0123456789")

#: The words of the installer's command that name the arm, each followed by its value.
ARM_WORDS = ("--hooks", "--run-config")

#: A file beneath each of the four places, by what it is. ``@R`` is the root of the test's tree.
PLACES = {
    "the harness checkout": "@R/harness/src/physgate/gate/planted.py",
    "the harness's frozen criteria": "@R/harness/experiments/R-OP-01/CRITERIA.md",
    "the run's recorded configuration": "@R/run/run.json",
    "the run's plan record": "@R/run/decomposition/plan.json",
    "the run's event record": "@R/run/events.jsonl",
    "the held-out tier": "@R/heldout/scenario_02.json",
    "the worktree's answer keys": "@R/worktree/corpora/answers.json",
    "the secrets": "@R/worktree/.env",
}

#: Of those, the ones no shell command may read either, under either value.
READ_DENIED = {
    "the run's recorded configuration",
    "the run's plan record",
    "the held-out tier",
    "the worktree's answer keys",
}


def _run_config(root: Path, hooks: Hooks) -> RunConfig:
    """The one run as recorded with ``hooks``: offline, with a held-out tier, an ablation if off."""
    return make_config(
        harness=CLEAN_HARNESS,
        hooks=hooks,
        ablation=hooks == "off",
        held_out=(str(root / "heldout"),),
        held_out_sha256=("c" * 64,),
        network="none",
    )


def _lay_out(root: Path) -> None:
    """The run's places, present as in a real run: the layer names a missing path by its parent."""
    harness = root / "harness"
    for source in ("src/physgate/gate", "knowledge", "scripts"):
        (harness / source).mkdir(parents=True, exist_ok=True)
    (harness / "experiments" / "R-OP-01").mkdir(parents=True, exist_ok=True)
    (harness / "experiments" / "R-OP-01" / "CRITERIA.md").write_text("frozen\n")
    worktree = root / "worktree"
    for source in ("src/physgate/gate", "src/physgate/hooks", "knowledge", "corpora"):
        (worktree / source).mkdir(parents=True, exist_ok=True)
    (worktree / ".env").write_text("NOT_A_SECRET=1\n")
    (root / "heldout").mkdir(exist_ok=True)
    (root / "run" / "decomposition").mkdir(parents=True, exist_ok=True)


def _dispatched(root: Path, monkeypatch: pytest.MonkeyPatch, hooks: Hooks) -> list[str]:
    """The installer command the dispatcher gives a role session of the run recorded so."""
    seen: list[list[str]] = []

    def fake_run(argv: list[str], **_kw: Any) -> subprocess.CompletedProcess[str]:  # noqa: ANN401
        seen.append(argv)
        out = {"settings": "s", "config": "c", "spawn_args": [], "spawn_env": {}}
        return subprocess.CompletedProcess(argv, 0, json.dumps(out), "")

    run_dir = root / "run"
    sdir = run_dir / "sessions" / "s1"
    # The dispatcher makes the session's state directory itself, once per session.
    shutil.rmtree(sdir / "state", ignore_errors=True)
    with monkeypatch.context() as patched:
        patched.setattr(subprocess, "run", fake_run)
        patched.setattr(dispatch, "session_protected_roots", lambda *_a: ((), ()))
        harness = ["--harness", str(root / "harness")]
        patched.setattr(dispatch, "harness_protection", lambda: harness)
        dispatcher = ClaudeDispatcher(
            config=_run_config(root, hooks),
            run=SimpleNamespace(  # type: ignore[arg-type]
                subtask_branch=lambda subtask, _reopen=0: f"b/{subtask}", run_dir=run_dir
            ),
            store_root=root / "store",
            install_bin=root / "install" / "bin" / "physgate",
            binary="claude",
            base_url=None,
            credential=Credential(mode="api_key", secret="not-a-key"),
            review_root=root / "reviews",
        )
        request = SessionRequest(
            subtask_id="s1",
            attempt=1,
            assigned_role="electrical",
            spec_path=".physgate/specs/s1.md",
            module_dir="modules/electrical",
            model="claude-opus-5-5",
            repair_instruction=None,
            bounds=SCRIPTED_BOUNDS,
        )
        dispatcher._install(request, root / "worktree", sdir, OWN_TEMP, own_temp=OWN_TEMP)
    (argv,) = seen
    return argv


def _but_the_arm(argv: list[str]) -> list[str]:
    """``argv`` without the arm's words and their values."""
    kept: list[str] = []
    skip = False
    for word in argv:
        if skip:
            skip = False
        elif word in ARM_WORDS:
            skip = True
        else:
            kept.append(word)
    return kept


def _values(argv: list[str], flag: str) -> list[str]:
    return [argv[i + 1] for i, word in enumerate(argv) if word == flag]


def _installed(
    root: Path, argv: list[str], hooks: Hooks, capsys: pytest.CaptureFixture[str]
) -> dict[str, Any]:
    """What the installer command writes for ``argv``, the run's record saying ``hooks``.

    The settings, the session's configuration and how the session is spawned.
    """
    record = root / "run" / "run.json"
    record.unlink(missing_ok=True)  # written once per run; here the one run is recorded twice
    write_run_config(record, _run_config(root, hooks))
    parser = argparse.ArgumentParser()
    add_parser(parser.add_subparsers(dest="command"))
    args = parser.parse_args(argv[1:])
    capsys.readouterr()
    assert args.func(args) == 0, capsys.readouterr().err
    printed = json.loads(capsys.readouterr().out)
    settings = json.loads(Path(printed["settings"]).read_text())
    config = SessionConfig.model_validate_json(
        (Path(printed["settings"]).parent / CONFIG_NAME).read_bytes()
    )
    return {"settings": settings, "config": config, "printed": printed}


def _both(
    root: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> dict[str, dict[str, Any]]:
    """The run installed under ``on`` and under ``off``, in the same place, ``on`` first."""
    _lay_out(root)
    commands = {hooks: _dispatched(root, monkeypatch, hooks) for hooks in ("on", "off")}
    return {hooks: _installed(root, commands[hooks], hooks, capsys) for hooks in ("on", "off")}


def _sandbox_bytes(settings: dict[str, Any]) -> str:
    return json.dumps(settings["sandbox"], sort_keys=True)


def test_the_dispatcher_gives_the_installer_the_same_command_but_for_the_arm(
    outside_tmp: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _lay_out(outside_tmp)
    on = _dispatched(outside_tmp, monkeypatch, "on")
    off = _dispatched(outside_tmp, monkeypatch, "off")
    assert _values(on, "--hooks") == ["on"]
    assert _values(off, "--hooks") == ["off"]
    # Every word the layer is made of, in the same order: the held-out tier, the run's records,
    # the harness checkout, the session's own directories, the network, the layer's directory.
    assert _but_the_arm(off) == _but_the_arm(on)
    for word in ("--held-out", "--withheld", "--protect-record", "--harness", "--os-layer-temp"):
        assert _values(off, word), word
    assert _values(off, "--os-layer-network") == ["none"]


@pytest.mark.parametrize("first", ["on", "off"])
def test_the_installer_writes_the_same_sandbox_byte_for_byte_under_either_arm(
    outside_tmp: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    first: Hooks,
) -> None:
    # Installed first, second and first again in one place, so a place one install makes cannot
    # stand in for a rule the other leaves out.
    _lay_out(outside_tmp)
    second: Hooks = "off" if first == "on" else "on"
    commands = {hooks: _dispatched(outside_tmp, monkeypatch, hooks) for hooks in ("on", "off")}
    installs = [
        _installed(outside_tmp, commands[hooks], hooks, capsys) for hooks in (first, second, first)
    ]
    sandboxes = {_sandbox_bytes(done["settings"]) for done in installs}
    assert len(sandboxes) == 1, "the OS layer's rules differ between hooks: on and hooks: off"
    assert "denyWrite" in installs[0]["settings"]["sandbox"]["filesystem"]
    assert installs[0]["settings"]["sandbox"]["network"]["strictAllowlist"] is True
    # Nothing else of the settings differs but the hook commands, and the session is spawned
    # alike: the same arguments and the same environment, the survivor reaper's included.
    rest = [{k: v for k, v in done["settings"].items() if k != "hooks"} for done in installs]
    assert rest[1] == rest[0]
    assert installs[1]["settings"]["hooks"] != installs[0]["settings"]["hooks"]
    assert installs[1]["printed"] == installs[0]["printed"]


def _covering(path: str, entries: list[str]) -> list[str]:
    """The entries of a rule list that name ``path`` or a directory above it."""
    real = os.path.realpath(path)
    return sorted(
        entry for entry in entries if any(Path(p).is_relative_to(Path(entry)) for p in (path, real))
    )


def _hook_roots(config: SessionConfig, path: str) -> list[dict[str, Any]]:
    """Every hook root that holds ``path``, and the held-out and answer-key roots above it."""
    roots = [
        root.model_dump()
        for root in config.protected_roots
        if Path(path).is_relative_to(Path(root.path))
    ]
    plain = [
        {"held": entry}
        for entry in (*config.held_out, *config.answer_keys)
        if Path(path).is_relative_to(Path(entry))
    ]
    return sorted([*roots, *plain], key=lambda r: json.dumps(r, sort_keys=True))


@pytest.mark.parametrize("what", list(PLACES))
def test_each_place_a_run_is_judged_by_is_held_alike_under_either_arm(
    outside_tmp: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    what: str,
) -> None:
    installed = _both(outside_tmp, monkeypatch, capsys)
    path = PLACES[what].replace("@R", str(outside_tmp))
    on_fs = installed["on"]["settings"]["sandbox"]["filesystem"]
    off_fs = installed["off"]["settings"]["sandbox"]["filesystem"]
    # The OS layer: every rule that names the place, or a directory above it, the same.
    for rule in ("denyWrite", "denyRead", "allowWrite", "allowRead"):
        assert _covering(path, off_fs[rule]) == _covering(path, on_fs[rule]), (what, rule)
    assert _covering(path, off_fs["denyWrite"]), f"no shell command is denied a write to {what}"
    assert not _covering(path, off_fs["allowWrite"]), what
    if what in READ_DENIED:
        assert _covering(path, off_fs["denyRead"]), f"a shell command may read {what}"
        assert not _covering(path, off_fs["allowRead"]), what
    # The hooks: the same root holds it, with the same reason, watch and readers.
    on_roots = _hook_roots(installed["on"]["config"], path)
    off_roots = _hook_roots(installed["off"]["config"], path)
    assert off_roots == on_roots, what
    assert off_roots, f"no hook root holds {what}"
