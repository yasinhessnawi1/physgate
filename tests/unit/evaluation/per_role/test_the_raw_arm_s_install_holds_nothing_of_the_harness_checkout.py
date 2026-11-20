"""The raw arm is installed with nothing to read under the harness checkout, and the checkout kept.

The raw arm is measured without the harness: its session is given no curated reading, and the
checkout the orchestrator runs from (the library, the rubrics, the gate's source) is kept from it
like any role session's. Installed here by the real installer from the raw arm's own arguments:
nothing it is given to read, and none of its own places, lies under the checkout, and a file
tool's read of the checkout's skill file is refused naming the checkout.
"""

from __future__ import annotations

import shutil
from pathlib import Path

import pytest
from test_the_raw_arm_s_credential_is_handled_as_a_role_session_s import (
    _script,
    _setup,
    capture_installer,
)

from physgate.evaluation.per_role.arms import raw
from physgate.hooks import cli
from physgate.hooks.config import SessionConfig
from physgate.hooks.paths import protection
from physgate.hooks.reasons import HARNESS_REASON
from physgate.hooks.settings import CONFIG_NAME
from physgate.knowledge import loader
from physgate.orchestrator.run_config import harness_root
from physgate.oslayer.session_temp import make_session_temp


def test_the_raw_arm_s_install_names_nothing_under_the_checkout_and_keeps_it_out(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    harness = harness_root()
    assert harness is not None, "the tests run from a source checkout, which is the harness"
    setup = _setup(tmp_path, _script(tmp_path / "claude", "true\n"))
    worktree = tmp_path / "trial" / "worktree"
    worktree.mkdir(parents=True)
    sdir = tmp_path / "trial" / "session"
    seen = capture_installer(monkeypatch)
    temp = make_session_temp()
    try:
        raw._install(setup, worktree, sdir, None, own_temp=temp)  # noqa: SLF001 - under test
        monkeypatch.undo()
        (argv,) = [a for a in seen if a[1:3] == ["hooks", "install"]]
        assert "--harness" in argv, "the raw arm is installed without the checkout protected"
        # The raw arm's own arguments, handed to the real installer.
        assert cli.main(argv[1:]) == 0
    finally:
        shutil.rmtree(temp, ignore_errors=True)
    written = SessionConfig.model_validate_json((sdir / "session" / CONFIG_NAME).read_bytes())
    assert written.profile == "baseline"
    given = sorted({*written.required_reading, *written.always_loaded})
    places = [written.worktree, written.state_dir, *given]
    under = [p for p in places if Path(p).resolve().is_relative_to(harness.resolve())]
    assert under == [], f"the raw arm is given a place under the harness checkout: {under}"
    own = str(harness / loader.DEFAULT_ROOT / "control" / loader.SKILL_NAME)
    assert protection(own, str(worktree), written, writing=False) == HARNESS_REASON
