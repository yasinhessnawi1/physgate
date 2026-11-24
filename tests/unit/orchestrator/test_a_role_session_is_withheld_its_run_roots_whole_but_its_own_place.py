"""A role session is withheld the run's roots whole but its own place; a run naming none, as before.

A measured run on a tier-set store records the store's run roots among the roots it withholds
whole (``withheld_whole``): the earlier runs made there hold every canary of the store, the plans
written from their briefs and their answers. Every role session of the run is installed with
each root withheld whole; a root that holds the run's directory gives the session the run's
directory as its own place there, so it reaches its worktree, and what it is given to read in its
own session directory, and nothing else of the root. A root that is the run's directory or lies
in it would leave the session no place of its own: no session is installed, and the refusal says
so without naming a path.

A run that names no root withheld whole (every run that names no held-out tier, and every run
recorded before the field) records the same bytes as before it existed and installs every role
session with the same command line, held here to digests taken from the code before the change.
The installer's bytes for a command line without the whole-root options are held by their own
row (``test_a_session_without_the_whole_root_options_is_installed_as_before``).
"""

from __future__ import annotations

import hashlib
import json
import subprocess
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest
from orch_helpers import SCRIPTED_BOUNDS, make_config

from physgate.orchestrator import dispatch
from physgate.orchestrator.credentials import Credential
from physgate.orchestrator.dispatch import ClaudeDispatcher
from physgate.orchestrator.exceptions import InvocationError
from physgate.orchestrator.ports import SessionRequest
from physgate.orchestrator.run_config import HarnessState

#: A checkout fixed in the record, so its bytes do not follow the commit the suite runs from.
FIXED = HarnessState(commit="c" * 40, clean=True, uncommitted_sha256=None)

#: Taken from the code before the field existed: the recorded bytes of the helpers' plain run,
#: and the command line its role session's installer is given (the rig's and the checkout's
#: paths written as placeholders), with and without the OS layer.
BEFORE_RECORD = "b0036a95893a4cad9eb10d59d0fa3e65a7f43ddea04bf0a84c96efe5522fb4f1"
BEFORE_ARGV = {
    False: "3537b72edabc914fce37ea8cc1c7e6a42667322aec5e1c9dd1457fd74c31fe44",
    True: "9caca46734fd181a07527c7b4101cada5fbc685df26fbcb1af45971753fbb304",
}
RIG, CHECKOUT = "<rig>", "<checkout>"


def _argv(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, *, layer: bool, **config: Any
) -> list[str]:  # noqa: ANN401
    seen: list[list[str]] = []

    def fake_run(argv: list[str], **_kw: Any) -> subprocess.CompletedProcess[str]:  # noqa: ANN401
        seen.append(argv)
        out = {"settings": "s", "config": "c", "spawn_args": [], "spawn_env": {}}
        return subprocess.CompletedProcess(argv, 0, json.dumps(out), "")

    monkeypatch.setattr(subprocess, "run", fake_run)
    monkeypatch.setattr(dispatch, "session_protected_roots", lambda *_a: ((), ()))
    monkeypatch.setattr(dispatch, "harness_protection", lambda: [])
    root = tmp_path.resolve()
    run_dir = root / "runs" / "run"
    (run_dir / "worktrees" / "s1").mkdir(parents=True)
    dispatcher = ClaudeDispatcher(
        config=make_config(harness=FIXED, **config),
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
        assigned_role="control",
        spec_path=".physgate/specs/s1.md",
        module_dir="modules/control",
        model="claude-opus-5-5",
        repair_instruction=None,
        bounds=SCRIPTED_BOUNDS,
    )
    temp = root / "pgs" / "0123456789" if layer else None
    dispatcher._install(
        request,
        run_dir / "worktrees" / "s1",
        run_dir / "sessions" / "x",
        temp,
        own_temp=temp or root / "pgs" / "0123456789",
    )
    (argv,) = seen
    return argv


def _given(argv: list[str], option: str) -> list[str]:
    return [argv[i + 1] for i, word in enumerate(argv) if word == option]


def _spelt(argv: list[str], root: Path) -> str:
    checkout = str(Path(dispatch.__file__).resolve().parents[3])
    text = json.dumps(argv).replace(str(root.resolve()), RIG).replace(checkout, CHECKOUT)
    return text


def test_a_run_that_names_no_root_withheld_whole_records_the_bytes_it_did() -> None:
    plain = make_config(harness=FIXED)
    assert "withheld_whole" not in json.loads(plain.canonical_bytes())
    assert plain.sha256() == BEFORE_RECORD, (plain.sha256(), plain.canonical_bytes())


@pytest.mark.parametrize("layer", [False, True], ids=["without the layer", "inside the layer"])
def test_a_run_that_names_no_root_withheld_whole_installs_each_role_session_as_before(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, layer: bool
) -> None:
    argv = _argv(tmp_path, monkeypatch, layer=layer)
    assert "--withheld-whole" not in argv and "--own-place" not in argv, argv
    spelt = _spelt(argv, tmp_path)
    assert RIG in spelt  # not vacuous: the rig's paths are what was given
    digest = hashlib.sha256(spelt.encode()).hexdigest()
    assert digest == BEFORE_ARGV[layer], (digest, spelt)


def test_a_root_holding_the_run_is_withheld_whole_with_the_run_as_the_session_s_place(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    root = tmp_path.resolve()
    (root / "older").mkdir()
    roots = (str(root / "runs"), str(root / "older"))
    argv = _argv(tmp_path, monkeypatch, layer=True, withheld_whole=roots)
    assert _given(argv, "--withheld-whole") == list(roots), argv
    assert _given(argv, "--own-place") == [str(root / "runs" / "run")], argv
    # Never as a held-out root: no root withheld whole is put back or tripwired.
    assert not set(roots) & set(_given(argv, "--held-out")), argv


def test_a_root_holding_none_of_the_run_gives_the_session_no_place(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    root = tmp_path.resolve()
    (root / "older").mkdir()
    argv = _argv(tmp_path, monkeypatch, layer=True, withheld_whole=(str(root / "older"),))
    assert _given(argv, "--withheld-whole") == [str(root / "older")], argv
    assert "--own-place" not in argv, argv


@pytest.mark.parametrize("where", ["runs/run", "runs/run/worktrees"], ids=["is it", "lies in it"])
def test_a_root_that_is_the_run_s_directory_or_lies_in_it_installs_no_session(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, where: str
) -> None:
    root = tmp_path.resolve()
    with pytest.raises(InvocationError) as raised:
        _argv(tmp_path, monkeypatch, layer=True, withheld_whole=(str(root / where),))
    assert raised.value.context.get("refused_because") == "withheld_whole_holds_no_place"
    assert str(root) not in str(raised.value), raised.value
