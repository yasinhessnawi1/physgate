"""The injected-error instrument reviews artefacts of roles the role register does not hold.

A run refuses, at its start, any role outside the register, because dispatching a role
session needs that role's sign-off. The instrument dispatches no role session: it
reviews a written revision, so its electrical and mechanical artefacts are reviewed
while those roles stay unregistered. The suite's ``conftest`` registers both stand-ins
for every test, which would hide the instrument being held to the register; these tests
take them out first and check that they are out.
"""

from __future__ import annotations

from pathlib import Path

import pytest
from instrument_corpus import SeededFakeReviewer, write_corpus

from physgate import roles
from physgate.cli import main
from physgate.evaluation.inject.corpus import load_corpus
from physgate.evaluation.inject.runner import run_instrument
from physgate.orchestrator.cli import Registrations


@pytest.fixture
def shipped(monkeypatch: pytest.MonkeyPatch) -> None:
    """The register as it ships: the suite's stand-in roles taken out."""
    for name in ("electrical", "mechanical"):
        monkeypatch.delitem(roles.ROLES, name, raising=False)
    assert "electrical" not in roles.ROLES


def test_the_instrument_reviews_an_unregistered_role_s_artefacts(
    shipped: None, tmp_path: Path
) -> None:
    corpus = load_corpus(write_corpus(tmp_path / "c"))
    assert {a.assigned_role for a in corpus.artefacts} == {"electrical"}
    rows = run_instrument(
        corpus,
        {"electrical": SeededFakeReviewer(seed=1)},
        run_dir=tmp_path / "run",
        scratch=tmp_path / "s",
        run_id="x",
        seed=1,
    )
    assert len(rows) == len(corpus.artefacts) == 2


def test_the_command_starts_for_an_unregistered_role(
    shipped: None, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    import physgate.evaluation.inject.cli as inject_cli

    # The fixture corpus is smaller than a measurement's, which the command refuses.
    monkeypatch.setattr(inject_cli, "require_complete", lambda corpus, per_class: None)
    argv = [
        "inject",
        "--corpus",
        str(write_corpus(tmp_path / "c")),
        "--run-dir",
        str(tmp_path / "run"),
        "--scratch",
        str(tmp_path / "s"),
        "--run-id",
        "x",
        "--seed",
        "1",
    ]
    registered = Registrations(reviewers={"electrical": SeededFakeReviewer(seed=1)})
    assert main(argv, registered) == 0
    assert (tmp_path / "run" / "events.jsonl").is_file()
