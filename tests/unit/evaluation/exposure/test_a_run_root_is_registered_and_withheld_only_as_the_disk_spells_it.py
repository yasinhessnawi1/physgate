"""A run root is registered, and withheld, only as its real path spelt as the disk spells it.

A measured run withholds its stores' run roots whole, as the register spells them. If a root were
spelt in another case than the disk's, on a volume that ignores case:
- the OS layer would still deny it;
- but the hooks, which match the spelling, would take every relative word of a session's commands
  for a word inside a protected root and refuse nearly every command.

A trial would then end with no answer, and be counted as the harness's fail. So a root is refused
at registration unless it is given as its real path, spelt as the disk spells each part:
- not in another case;
- not through a linked parent.

A root on the register that is not so spelt (one registered before the rule, or renamed since)
refuses every measured run naming its store when the run starts. So does a run directory typed in
another case beneath a root spelt as on disk: its sessions' worktrees would be spelt so. A
trailing slash names the same directory and is registered as the real path.
"""

from __future__ import annotations

import os
from pathlib import Path

import pytest
from exposure_fixtures import LAYER, StandInStore, config, stand_in_store

from physgate.evaluation import requirements
from physgate.evaluation.per_role.exceptions import PerRoleError
from physgate.evaluation.tiers import exposure
from physgate.evaluation.tiers.exposure import add_run_root, run_roots
from physgate.evaluation.tiers.store import withheld_root
from physgate.orchestrator.requirements import RunFacts


@pytest.fixture
def made(tmp_path: Path) -> StandInStore:
    return stand_in_store(tmp_path.resolve() / "s")


def _other_case(path: Path) -> Path:
    """``path`` with its last part in another case, skipping where the volume tells cases apart."""
    other = path.with_name(path.name.swapcase())
    if not other.exists():
        pytest.skip("this volume tells cases apart, so another case names no directory")
    return other


def _refused(made: StandInStore, root: Path) -> str:
    with pytest.raises(PerRoleError) as raised:
        add_run_root(made.store, "control", root)
    assert run_roots(made.store, "control") == [], "the root was registered all the same"
    return str(raised.value.context.get("refused_because"))


def test_a_root_given_in_another_case_is_refused_at_registration(
    made: StandInStore, tmp_path: Path
) -> None:
    (tmp_path.resolve() / "Runs").mkdir()
    other = _other_case(tmp_path.resolve() / "Runs")
    assert _refused(made, other) == "run_root_not_spelt_as_on_disk"


def test_a_root_given_through_a_linked_parent_is_refused_at_registration(
    made: StandInStore, tmp_path: Path
) -> None:
    base = tmp_path.resolve()
    (base / "real" / "runs").mkdir(parents=True)
    os.symlink(base / "real", base / "link")
    assert _refused(made, base / "link" / "runs") == "run_root_not_spelt_as_on_disk"


def test_a_root_given_with_a_trailing_slash_is_registered_as_its_real_path(
    made: StandInStore, tmp_path: Path
) -> None:
    runs = tmp_path.resolve() / "runs"
    runs.mkdir()
    assert add_run_root(made.store, "control", Path(f"{runs}/"))
    assert [str(r) for r in run_roots(made.store, "control")] == [str(runs)]


def _registered_before_the_rule(made: StandInStore, spelt: Path) -> None:
    """A register line as a writer before the rule could leave it, spelt as given."""
    exposure._append(  # noqa: SLF001
        withheld_root(made.store, "control"),
        exposure.RUN_ROOTS,
        [{"kind": "run_root", "path": str(spelt)}],
    )


def _ask(made: StandInStore, run_dir: Path) -> str | None:
    roots = [str(r) for r in run_roots(made.store, "control")]
    run = config(made.tasks["held_out"][0], made, withheld_whole=roots)
    facts = RunFacts(
        config=run,
        os_layer=LAYER,
        shell_sessions=True,
        new_run=True,
        run_dir=run_dir,
        review_root=run_dir / "review",
    )
    found: str | None = requirements.a_measured_run_withholds_every_run_root_whole(facts)
    return found


@pytest.mark.parametrize("how", ["in another case", "through a linked parent"])
def test_a_root_on_the_register_not_spelt_as_on_disk_refuses_a_measured_run(
    made: StandInStore, tmp_path: Path, how: str
) -> None:
    base = tmp_path.resolve()
    if how == "in another case":
        (base / "Runs").mkdir()
        spelt = _other_case(base / "Runs")
    else:
        (base / "real" / "runs").mkdir(parents=True)
        os.symlink(base / "real", base / "link")
        spelt = base / "link" / "runs"
    _registered_before_the_rule(made, spelt)
    why = _ask(made, spelt / "run-1")
    assert why is not None and "(run_root_not_spelt_as_on_disk)" in why, why
    assert str(base) not in why, why


def test_a_root_on_the_register_spelt_as_on_disk_lets_the_run_go_on(
    made: StandInStore, tmp_path: Path
) -> None:
    runs = tmp_path.resolve() / "runs"
    runs.mkdir()
    assert add_run_root(made.store, "control", runs)
    assert _ask(made, runs / "run-1") is None


def test_a_run_directory_typed_in_another_case_beneath_a_root_spelt_as_on_disk_is_refused(
    made: StandInStore, tmp_path: Path
) -> None:
    runs = tmp_path.resolve() / "runs"
    (runs / "run-1").mkdir(parents=True)
    assert add_run_root(made.store, "control", runs)
    typed = _other_case(runs / "run-1")
    why = _ask(made, typed.resolve())
    assert why is not None and "(run_dir_not_spelt_as_on_disk)" in why, why
    assert str(tmp_path.resolve()) not in why, why
    assert _ask(made, runs / "run-1") is None
