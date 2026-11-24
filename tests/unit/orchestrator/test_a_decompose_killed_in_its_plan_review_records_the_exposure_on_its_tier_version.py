"""A ``decompose`` killed in its plan review still marks the tier version its review saw exposed.

A plan review whose stream showed held-out material makes the run's tier version exposed: through
to the opening, the run's event log holds the ``held_out_read`` incident, the exposure register
finds it beneath the role's run roots, and a later reportable run on the version is refused. A
``decompose`` killed during that review, or between the review's end and its round's end line, has
written no event log and no run configuration yet. The next command on its directory scans the
review's streams and records what it finds in a file of its own, and refuses the directory. The
version must then be exposed all the same: the register finds that exposure too, and a later
reportable run on the version is refused.
"""

from __future__ import annotations

import json
import sys
from collections.abc import Iterator
from pathlib import Path
from typing import Any

import pytest

EXPOSURE_TESTS = Path(__file__).resolve().parents[1] / "evaluation" / "exposure"
if str(EXPOSURE_TESTS) not in sys.path:
    sys.path.insert(0, str(EXPOSURE_TESTS))

from exposure_fixtures import (  # noqa: E402
    StandInStore,
    api,
    config,
    refusal,
    stand_in_store,
    with_run_root,
)
from loop_fakes import usage  # noqa: E402
from test_a_review_session_a_killed_decompose_left_is_stopped_by_the_next_command import (  # noqa: E402
    OTHER_START,
    SESSION,
    Recording,
)
from test_decompose_reviews_the_plan_before_it_writes_anything import (  # noqa: E402
    REVIEWING,
    Calls,
    StandIn,
    Stopped,
    _args,
    _exit,
    _verdict,
    calls,
)

from physgate.evaluation.tiers.heldout import tier_digest  # noqa: E402
from physgate.orchestrator import design_rounds  # noqa: E402
from physgate.orchestrator.exceptions import HeldOutExposedError  # noqa: E402
from physgate.orchestrator.protocols import MessageUsage  # noqa: E402

__all__ = ["calls"]  # the fixture, used by name

EXPOSURE = "physgate.evaluation.tiers.exposure"
ROLE = "control"
EXPOSED_FILE = Path("decomposition", "review_exposed.json")


def _exposed_review() -> HeldOutExposedError:
    """What the plan reviewer raises when its session's stream showed held-out material."""
    spent = (MessageUsage(message_id="r1", usage=usage(5)),)
    msg = "held-out material"
    return HeldOutExposedError(
        msg, session_id=SESSION, reviewer_model="claude-opus-5-5", usage=spent
    )


class OnTier:
    """A stand-in tier version, its run roots, and a ``decompose`` on it beneath them."""

    def __init__(self, tmp_path: Path) -> None:
        self.made: StandInStore = stand_in_store(tmp_path / "s")
        self.runs = with_run_root(self.made, tmp_path / "runs")
        self.review_root = (tmp_path / "review-scratch").resolve()
        params = {
            **REVIEWING,
            "held_out": list(self.made.held_out),
            "held_out_sha256": [tier_digest(Path(root)) for root in self.made.held_out],
            "held_out_canaries": list(self.made.canaries),
        }
        self.args = _args(tmp_path, params)
        self.args[self.args.index("--run-dir") + 1] = str(self.run_dir)

    @property
    def run_dir(self) -> Path:
        return self.runs / "run"

    def shown(self) -> str:
        """A stream line that shows one of the version's held-out canaries."""
        canary = self.made.canaries[-1]
        return json.dumps({"type": "user", "message": {"content": f"x <!-- {canary} -->"}}) + "\n"

    def later_refusal(self) -> str | None:
        """What a later reportable run on the version is told: ``None`` if it may start."""
        return refusal(config(self.made.tasks["visible"][0], self.made), self.runs / "r2")

    def exposed(self) -> frozenset[str]:
        found: frozenset[str] = api(f"{EXPOSURE}.exposed_versions")(self.made.store, ROLE)
        return found


@pytest.fixture
def tier(tmp_path: Path, calls: Calls) -> Iterator[OnTier]:
    yield OnTier(tmp_path)


def test_a_decompose_whose_plan_review_showed_held_out_material_marks_its_version_exposed(
    tier: OnTier,
) -> None:
    assert _exit(tier.args, StandIn(_exposed_review())) == 1
    assert (tier.run_dir / "run.json").exists()
    assert tier.exposed() == frozenset({tier.made.version})
    later = tier.later_refusal()
    assert later is not None and "(version_exposed)" in later, later


def _killed_during_the_review(tier: OnTier, monkeypatch: pytest.MonkeyPatch) -> None:
    reviewer = Recording(
        Stopped(), (SESSION, 4242, OTHER_START), stream=tier.shown(), root=tier.review_root
    )
    with pytest.raises(BaseException) as stopped:  # noqa: PT011 - the stop is the point
        _exit(tier.args, reviewer)
    assert stopped.type is Stopped


def _killed_before_the_round_s_end_line(tier: OnTier, monkeypatch: pytest.MonkeyPatch) -> None:
    append = design_rounds._append  # noqa: SLF001 - the journal's own writer

    def dies_at_the_round_s_end(journal: Path, line: Any) -> None:  # noqa: ANN401
        if isinstance(line, design_rounds.RoundEnded):
            raise Stopped
        append(journal, line)

    monkeypatch.setattr(design_rounds, "_append", dies_at_the_round_s_end)
    reviewer = Recording(
        _exposed_review(), (SESSION, 4242, OTHER_START), stream=tier.shown(), root=tier.review_root
    )
    with pytest.raises(BaseException) as stopped:  # noqa: PT011 - the stop is the point
        _exit(tier.args, reviewer)
    assert stopped.type is Stopped
    monkeypatch.setattr(design_rounds, "_append", append)


@pytest.mark.parametrize(
    "kill",
    [_killed_during_the_review, _killed_before_the_round_s_end_line],
    ids=["during its review", "between the review's end and its round's end line"],
)
def test_a_decompose_killed_in_its_plan_review_marks_its_version_exposed_once_found(
    tier: OnTier, monkeypatch: pytest.MonkeyPatch, kill: Any
) -> None:
    kill(tier, monkeypatch)
    assert not (tier.run_dir / "run.json").exists()
    assert not (tier.run_dir / "events.jsonl").exists()
    # The next command on the directory finds the exposure, records it and refuses.
    assert _exit(tier.args, StandIn(_verdict())) == 2
    assert (tier.run_dir / EXPOSED_FILE).is_file()
    assert tier.exposed() == frozenset({tier.made.version}), (
        "the register does not hold the exposure a killed decompose's plan review showed"
    )
    later = tier.later_refusal()
    assert later is not None, "a later reportable run on the exposed version was not refused"
    assert "(version_exposed)" in later, later
