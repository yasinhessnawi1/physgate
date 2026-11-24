"""The command shows every requirement the review root the run names, resolved.

A measured run reviews only inside its own run directory (the evaluation's requirement), so the
requirement must see where the reviews will run. It sees this before anything is written or spawned:
- at decompose, the root given there (none where the plan is not reviewed and none is given);
- at run and resume, the root those always name.
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

EXPOSURE_TESTS = Path(__file__).resolve().parents[1] / "evaluation" / "exposure"
if str(EXPOSURE_TESTS) not in sys.path:
    sys.path.insert(0, str(EXPOSURE_TESTS))

from test_a_role_session_runs_only_inside_the_os_layer_unless_allowed import (  # noqa: E402
    PRESENT,
    _recorded,
    _through_the_command,
)
from test_the_command_refuses_a_measured_run_on_an_exposed_tier_version import (  # noqa: E402
    _decompose,
    _seen,
)
from test_the_physgate_command_starts_and_decides import PARAMS  # noqa: E402

from physgate.cli import main  # noqa: E402


@pytest.mark.parametrize("given", [True, False], ids=["one given", "none given"])
def test_a_requirement_is_shown_the_review_root_given_at_decompose(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    given: bool,
) -> None:
    seen = _seen(monkeypatch)
    args = _decompose(tmp_path, monkeypatch, PARAMS)
    # Spelt with a step back through the run's own directory: shown as every reader takes it.
    spelt = tmp_path / "runs" / "run" / ".." / "run" / "review"
    assert main([*args, "--review-root", str(spelt)] if given else args) == 2
    assert len(seen) == 1, f"the requirements were not asked once: {capsys.readouterr().err}"
    (facts,) = seen
    shown = getattr(facts, "review_root", "never shown")
    assert shown == ((tmp_path / "runs" / "run" / "review").resolve() if given else None)


@pytest.mark.parametrize("command", ["run", "resume"])
def test_a_requirement_is_shown_the_review_root_at_run_and_resume(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, command: str
) -> None:
    seen = _seen(monkeypatch)
    _recorded(tmp_path, os_layer=PRESENT)
    code, spawned = _through_the_command(tmp_path, monkeypatch, command, PRESENT)
    assert code == 2 and spawned == []
    assert len(seen) == 1, "the requirements were not asked once"
    (facts,) = seen
    shown = getattr(facts, "review_root", "never shown")
    assert shown == (tmp_path / "review-scratch").resolve()
