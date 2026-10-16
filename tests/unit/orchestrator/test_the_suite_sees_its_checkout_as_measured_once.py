"""The suite's commands see its own checkout as measured once, and any other one live.

The orchestrator refuses to resume a run under a checkout other than the one it started
from. Measured live, an edit saved anywhere in this checkout while the suite ran made that
refusal fire in tests that never meant to move the harness. The shared fixtures pin the
measurement of this checkout for the whole process; these tests hold the pin to that and no
further.
"""

from __future__ import annotations

from collections.abc import Callable
from pathlib import Path
from types import ModuleType

from harness_pin import measured_harness

from physgate.evaluation.observe import rerun
from physgate.orchestrator import cli
from physgate.orchestrator.run_config import HarnessState


def _measure(module: ModuleType) -> Callable[[Path | None], HarnessState]:
    """The measurement the module's commands call, as they look it up when they run."""
    measure: Callable[[Path | None], HarnessState] = module.__dict__["harness_state"]
    return measure


def test_this_checkout_is_the_one_measurement_whenever_it_is_asked_for() -> None:
    real = cli._harness_root()
    assert real is not None, "the suite runs from a source checkout"
    # The same object, not an equal one: a live measurement builds a new record every call.
    assert _measure(cli)(real) is measured_harness()
    assert _measure(rerun)(real) is measured_harness()


def test_any_other_checkout_is_measured_live(tmp_path: Path) -> None:
    assert _measure(cli)(tmp_path) == HarnessState(
        commit=None, clean=False, uncommitted_sha256=None
    )
    assert _measure(cli)(None) == HarnessState(commit=None, clean=False, uncommitted_sha256=None)
