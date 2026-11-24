"""Over random plans with reopens, retries, fixes and kills a run never waits on nothing.

Each seed makes a plan of three to six modules, bends some nodes so that contract pairs fail, and
gives the reviews pass, fail, blocked and no-verdict results. A person decides every open item at
random after each stop: approve; reject, which orders a retry or a fix where the item allows one;
choose, which reopens a module on a failed contract; a sign-off's approve or reject. Half the seeds
are killed before a line some processes would write. A run under ``release_2`` never ends in a wait
with no item open, never raises (a choice that reopens a module whose last attempt never merged is
not offered), never halts on the backstop or the guard, never dispatches a builder before its
designer merged, ends ``done`` only with every module run to its end and ``unrun`` only naming
modules that did not, and its record replays. The same plans under ``release`` are the control:
they are expected to find the old wait with nothing to decide, which the rule removes.
"""

from __future__ import annotations

from pathlib import Path

import pytest
from accounted import forged_account_before_each_open  # noqa: F401 - the rig's forger
from test_a_choice_on_a_failed_contract_reopens_the_other_module import of
from wait_sweep_rig import check, play

from physgate import roles

#: The seeds the row runs; larger ranges are run by hand, one process at a time. The first forty
#: are an even spread. The rest are ones that fail on the code before the fixes they guard (each
#: found by running seeds 0 to 169 against it): 62, 64, 82, 100, 131 and 161 end in a wait with
#: no item open, or done with a module never run; 49 and 112 stop on a reopen the loop cannot
#: carry out.
SEEDS = (*range(40), 49, 62, 64, 82, 100, 112, 131, 161)


@pytest.fixture(autouse=True)
def _sizing_registered(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setitem(roles.ROLES, roles.SIZING.name, roles.SIZING)


@pytest.mark.parametrize("seed", SEEDS)
def test_a_random_run_under_release_2_never_waits_on_nothing(
    seed: int, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    played = play(seed, tmp_path, monkeypatch, "release_2")
    assert of(played.rows, "run_started")[0]["wait_cycle"] == "release_2"
    assert check(played, "release_2") == []
