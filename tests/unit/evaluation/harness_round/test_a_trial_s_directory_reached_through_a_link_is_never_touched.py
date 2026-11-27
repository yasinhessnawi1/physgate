"""A trial's directory reached through a link is never touched by the round.

The round reaches a trial's directory by the run root it recorded, the round's directory and the
trial's. Where any part of that path has been made a link since (at the round's directory or at
the trial's own), the restart is refused before it stops a review, removes a credential, writes
an exposure, decomposes or drives there, and the directory the link names is left as it was.
"""

from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
from typing import Any

import pytest
from round_rig import SCORED, Rig, make_rig

from physgate.evaluation.harness_round import HARNESS_ROUNDS, ROUND_RECORD, RoundError, run_round
from physgate.evaluation.tiers.store import withheld_root


def _score(_task: Any, _answer: Path) -> dict[str, Any]:  # noqa: ANN401
    return dict(SCORED)


def _waiting(rig: Rig) -> Path:
    """A round stopped waiting for the limit at its first trial; that trial's directory."""
    status, _ = run_round(
        rig.inputs(trials=1), driver=rig.driver(limited={1}), scorer=_score, sleep=lambda _: None
    )
    assert status == "waiting_for_limit"
    summary = json.loads((rig.root / "out" / ROUND_RECORD).read_bytes())
    return rig.run_root / str(summary["round"]) / "0000-1"


def _digest(root: Path) -> str:
    seen = hashlib.sha256()
    for here, dirs, files in sorted(os.walk(root)):
        dirs.sort()
        for name in sorted(files):
            path = Path(here) / name
            seen.update(str(path.relative_to(root)).encode())
            if not path.is_symlink():
                seen.update(path.read_bytes())
    return seen.hexdigest()


@pytest.mark.parametrize("where", ["the round's directory", "the trial's directory"])
def test_a_link_on_the_way_to_a_trial_s_directory_refuses_the_restart_and_touches_nothing(
    tmp_path: Path, where: str
) -> None:
    rig = make_rig(tmp_path)
    run_dir = _waiting(rig)
    moved = run_dir.parent if where == "the round's directory" else run_dir
    foreign = tmp_path / "elsewhere" / moved.name
    foreign.parent.mkdir()
    moved.rename(foreign)
    moved.symlink_to(foreign, target_is_directory=True)
    place = next((withheld_root(rig.made.store, "control") / HARNESS_ROUNDS).iterdir())
    ledger = (place / "ledger.jsonl").read_bytes()
    before = _digest(foreign)
    driver = rig.driver()
    with pytest.raises(RoundError) as raised:
        run_round(
            rig.inputs(trials=1),
            driver=driver,
            scorer=_score,
            resume=True,
            limit_reset=True,
            sleep=lambda _: None,
        )
    assert raised.value.context["refused_because"] == "run_dir_linked"
    assert driver.drives == [] and driver.decomposed == []
    assert _digest(foreign) == before
    assert (place / "ledger.jsonl").read_bytes() == ledger


def test_a_restart_reads_nothing_through_a_link_not_even_the_run_s_record(tmp_path: Path) -> None:
    # Reading a run's record cuts a torn last line, as the core does: through a link, the
    # restart's first reading of where the round stands would write in another's directory.
    rig = make_rig(tmp_path)
    run_dir = _waiting(rig)
    foreign = tmp_path / "elsewhere" / run_dir.name
    foreign.parent.mkdir()
    run_dir.rename(foreign)
    with (foreign / "events.jsonl").open("ab") as log:
        log.write(b'{"torn": ')
    run_dir.symlink_to(foreign, target_is_directory=True)
    before = _digest(foreign)
    with pytest.raises(RoundError) as raised:
        run_round(
            rig.inputs(trials=1), driver=rig.driver(), scorer=_score, resume=True, set_aside=0
        )
    assert raised.value.context["refused_because"] == "run_dir_linked"
    assert _digest(foreign) == before


def test_a_later_trial_s_directory_made_a_link_is_refused_when_the_round_reaches_it(
    tmp_path: Path,
) -> None:
    rig = make_rig(tmp_path)
    status, _ = run_round(
        rig.inputs(trials=2), driver=rig.driver(limited={1}), scorer=_score, sleep=lambda _: None
    )
    assert status == "waiting_for_limit"
    summary = json.loads((rig.root / "out" / ROUND_RECORD).read_bytes())
    later = rig.run_root / str(summary["round"]) / "0001-1"
    foreign = tmp_path / "elsewhere"
    foreign.mkdir()
    (foreign / "kept").write_text("another's\n")
    later.symlink_to(foreign, target_is_directory=True)
    before = _digest(foreign)
    with pytest.raises(RoundError) as raised:
        run_round(
            rig.inputs(trials=2),
            driver=rig.driver(),
            scorer=_score,
            resume=True,
            limit_reset=True,
            sleep=lambda _: None,
        )
    assert raised.value.context["refused_because"] == "run_dir_linked"
    assert raised.value.context["index"] == "1"
    assert _digest(foreign) == before
