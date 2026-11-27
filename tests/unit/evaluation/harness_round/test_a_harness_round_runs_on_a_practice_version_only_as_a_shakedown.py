"""A harness round runs on a practice version only when told it is a shakedown.

A practice version says so in its manifest. The round refuses it before anything is made
(``practice_version``) unless its inputs say it is a shakedown, which the ledger then holds.
"""

from __future__ import annotations

from pathlib import Path

import pytest
from round_rig import SCORED, make_rig

from physgate.evaluation.harness_round import RoundError, run_round


def test_a_practice_version_is_refused_unless_the_round_is_a_shakedown(tmp_path: Path) -> None:
    rig = make_rig(tmp_path, store={"practice": True})
    with pytest.raises(RoundError) as refused:
        run_round(
            rig.inputs(trials=1),
            driver=rig.driver(),
            scorer=lambda _t, _a: dict(SCORED),
            sleep=lambda _: None,
        )
    assert refused.value.context["refused_because"] == "practice_version"
    assert not (rig.root / "out").exists(), "nothing was made before the refusal"
    status, _ = run_round(
        rig.inputs(trials=1, shakedown=True),
        driver=rig.driver(),
        scorer=lambda _t, _a: dict(SCORED),
        sleep=lambda _: None,
    )
    assert status == "done"
