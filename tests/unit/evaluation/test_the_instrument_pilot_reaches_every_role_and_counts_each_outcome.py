"""The instrument's pilot reaches every role and counts each review's outcome, by role and kind.

The pilot (``real_instrument_pilot.py``) runs real reviewers through ``physgate inject`` on a
four-role test corpus. It is launched by hand, on the pinned binary, so here it is held
without a model and without a binary: its corpus is one the instrument runs as it stands,
one artefact per role with a clean twin the gate passes and an artefact the gate catches;
its report, read from a run with fake reviewers, counts every review once, ``blocked`` and
``review_unavailable`` per role for the artefacts and for the twins; its record of request
defaults sets each field beside the version's measured role-session defaults; it refuses
any binary but the pinned one before it writes anything; a dry run never reads the env
file's token; and a dollar cap stops it before a session that would go past the cap.
"""

from __future__ import annotations

import os
import sys
from decimal import Decimal
from pathlib import Path

import pilot_corpus
import pytest
from instrument_corpus import SeededFakeReviewer

from physgate.evaluation.inject.corpus import Corpus, load_corpus
from physgate.evaluation.inject.runner import control_id, review_id, run_instrument
from physgate.evaluation.observe.cost import load_price_sheet
from physgate.evaluation.observe.manifest import BINARY_DEFAULTS
from physgate.knowledge.promote import KNOWLEDGE_ROOT
from physgate.orchestrator.exceptions import ReviewUnavailableError
from physgate.orchestrator.protocols import Artefact, ReviewResult, SpecDefect
from physgate.reviewers.rubric import load_rubric

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "integration" / "orchestrator"))
import real_instrument_pilot as pilot  # noqa: E402
from scripted_endpoint import DUMMY_OAUTH_TOKEN  # noqa: E402

REPOSITORY = Path(__file__).resolve().parents[3]


@pytest.fixture
def corpus(tmp_path: Path) -> Corpus:
    return load_corpus(pilot_corpus.write_pilot_corpus(tmp_path / "corpus"))


def _run(corpus: Corpus, root: Path, reviewers: dict[str, object]) -> Path:
    run_instrument(
        corpus,
        reviewers,  # type: ignore[arg-type]
        run_dir=root / "run",
        scratch=root / "rs",
        run_id="pilot-test",
        seed=pilot.SEED,
        review_clean_twins=True,
    )
    return root / "run"


def test_the_corpus_has_one_artefact_per_role_on_the_evaluation_s_pins(corpus: Corpus) -> None:
    assert sorted(a.assigned_role for a in corpus.artefacts) == sorted(pilot_corpus.ROLES)
    assert corpus.manifest.author_model == pilot_corpus.AUTHOR != pilot_corpus.REVIEWER
    assert set(pilot.PARAMS["reviewers"]) == set(pilot_corpus.ROLES)
    # Every role's reviewer has a promoted rubric to judge with.
    for role in pilot_corpus.ROLES:
        load_rubric(REPOSITORY / KNOWLEDGE_ROOT, role)


def test_with_fakes_every_role_is_reported_and_the_gate_behaves(
    corpus: Corpus, tmp_path: Path
) -> None:
    fakes = {r: SeededFakeReviewer(model=pilot_corpus.REVIEWER) for r in pilot_corpus.ROLES}
    run_dir = _run(corpus, tmp_path, dict(fakes))
    report = pilot.summary(run_dir, tmp_path / "rs", load_price_sheet(pilot.PRICES))
    assert report["every_role_reviewed"] is True
    assert len(report["sessions"]) == 2 * len(pilot_corpus.ROLES)
    assert {(s["role"], s["kind"]) for s in report["sessions"]} == {
        (r, k) for r in pilot_corpus.ROLES for k in ("artefact", "twin")
    }
    assert set(report["verdict_forms_observed"]) <= {"pass", "fail"}
    for kinds in report["blocked_and_unavailable_per_role"].values():
        assert kinds == {k: {"blocked": 0, "review_unavailable": 0} for k in ("artefact", "twin")}
    # The apparatus: every twin passes the gate and every artefact is caught.
    assert set(report["gate_apparatus"]) == {"c1", "e1", "f1", "k1"}
    assert all(g == {"artefact": "fail", "twin": "pass"} for g in report["gate_apparatus"].values())


class _Scripted:
    """A fake reviewer that blocks one review and gives no verdict on another."""

    def __init__(self, blocks: str, gives_none: str) -> None:
        self.model = pilot_corpus.REVIEWER
        self.blocks, self.gives_none = blocks, gives_none
        self.fallback = SeededFakeReviewer(model=pilot_corpus.REVIEWER)

    def review(self, artefact: Artefact) -> ReviewResult:
        if artefact.subtask_id == self.gives_none:
            msg = "the session ended with no structured verdict"
            raise ReviewUnavailableError(msg, cause="no_verdict", reviewer_model=self.model)
        if artefact.subtask_id == self.blocks:
            return ReviewResult(
                verdict="blocked",
                finding="the design lacks the input a safety check needs",
                reviewer_model=self.model,
                session_id="fake-blocked",
                usage=(),
                spec_defects=(SpecDefect(finding="no input", blocking=True),),
            )
        return self.fallback.review(artefact)


def test_blocked_and_no_verdict_are_counted_by_role_and_kind(
    corpus: Corpus, tmp_path: Path
) -> None:
    fakes = {r: SeededFakeReviewer(model=pilot_corpus.REVIEWER) for r in pilot_corpus.ROLES}
    reviewers: dict[str, object] = dict(fakes)
    reviewers["control"] = _Scripted(blocks=review_id(pilot.SEED, "c1"), gives_none="-")
    reviewers["firmware"] = _Scripted(blocks="-", gives_none=control_id(pilot.SEED, "f1"))
    report = pilot.summary(
        _run(corpus, tmp_path, reviewers), tmp_path / "rs", load_price_sheet(pilot.PRICES)
    )
    counted = report["blocked_and_unavailable_per_role"]
    assert counted["control"]["artefact"] == {"blocked": 1, "review_unavailable": 0}
    assert counted["control"]["twin"] == {"blocked": 0, "review_unavailable": 0}
    assert counted["firmware"]["twin"] == {"blocked": 0, "review_unavailable": 1}
    assert counted["firmware"]["artefact"] == {"blocked": 0, "review_unavailable": 0}
    assert {"blocked", "review_unavailable"} <= set(report["verdict_forms_observed"])
    (none,) = [s for s in report["sessions"] if s["outcome"] == "review_unavailable"]
    assert (none["role"], none["kind"], none["cause"]) == ("firmware", "twin", "no_verdict")


def test_request_settings_are_set_beside_the_version_s_role_session_defaults() -> None:
    known = BINARY_DEFAULTS["2.1.283"]
    same = {
        "model": pilot_corpus.REVIEWER,
        "max_tokens": 64000,
        "thinking": dict(known.thinking),
        "output_config": None,
        "context_management": known.context_management,
        "sampling": [],
        "anthropic_beta": sorted(known.anthropic_beta),
    }
    other = {**same, "anthropic_beta": [*sorted(known.anthropic_beta), "z-extra-2026-01-01"]}
    found = pilot.request_defaults([same, same, other], "2.1.283")
    assert found["requests"] == 3 and len(found["distinct"]) == 2
    assert found["compared_with_role_sessions"] == {
        "thinking_type_as_role_sessions": True,
        "context_management_as_role_sessions": True,
        "anthropic_beta_as_role_sessions": False,
    }
    assert pilot.request_defaults([same], "0.0.0")["compared_with_role_sessions"] is None


def test_any_binary_but_the_pinned_one_is_refused_before_anything_is_written(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    monkeypatch.setenv("PHYSGATE_CLAUDE_BIN", "/bin/sh")
    out = tmp_path / "out"
    assert pilot.main(["--dry-run", "--out", str(out)], binary_check=lambda: "2.1.283") == 2
    assert "pinned binary" in capsys.readouterr().out
    assert not out.exists()


def test_a_dry_run_never_reads_the_env_file(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    """A dry run's session gets the dummy token: a real one never enters its process."""
    monkeypatch.setenv("PHYSGATE_CLAUDE_BIN", "/bin/sh")
    env_file = tmp_path / "env"
    env_file.write_text(f"{pilot.VARIABLE}=not-a-real-token\n")

    def read(path: Path) -> str:
        msg = f"the dry run read the env file {path}"
        raise AssertionError(msg)

    seen: dict[str, object] = {}

    def ran(out: Path, **kwargs: object) -> dict[str, object]:
        seen.update(kwargs, token=os.environ.get(pilot.VARIABLE))
        return {}

    monkeypatch.setattr(pilot, "load_token", read)
    monkeypatch.setattr(pilot, "run", ran)
    out = tmp_path / "out"
    argv = ["--dry-run", "--out", str(out), "--env-file", str(env_file)]
    assert pilot.main(argv, binary_check=lambda: pilot.PILOT_VERSION) == 0
    assert seen["dry_run"] is True and seen["token"] == DUMMY_OAUTH_TOKEN
    assert os.environ.get(pilot.VARIABLE) is None  # not left behind either
    capsys.readouterr()


def test_the_dollar_cap_stops_the_run_before_a_session_that_would_pass_it(
    corpus: Corpus, tmp_path: Path
) -> None:
    """Each session costs 0.50 here; a cap of 1.60 admits three and stops before the fourth."""
    budget = pilot.Budget(
        cap_usd=Decimal("1.60"), floor_usd=Decimal("0.50"), cost_of=lambda *_: Decimal("0.50")
    )
    fakes = {r: SeededFakeReviewer(model=pilot_corpus.REVIEWER) for r in pilot_corpus.ROLES}
    capped = pilot.capped(budget, lambda _setup: fakes)(None)
    assert set(capped) == set(pilot_corpus.ROLES)
    with pytest.raises(pilot.BudgetStop, match="cap"):
        _run(corpus, tmp_path, dict(capped))
    assert sum(len(f.seen) for f in fakes.values()) == 3
    assert (budget.sessions, budget.spent) == (3, Decimal("1.50"))


def test_the_next_session_is_expected_to_cost_the_most_any_has_cost(
    corpus: Corpus, tmp_path: Path
) -> None:
    """After a dear session the estimate rises to it, so the cap stops one session sooner."""
    costs = iter([Decimal("1.00"), Decimal("0.10"), Decimal("0.10")])
    budget = pilot.Budget(
        cap_usd=Decimal("2.05"), floor_usd=Decimal("0.10"), cost_of=lambda *_: next(costs)
    )
    fakes = {r: SeededFakeReviewer(model=pilot_corpus.REVIEWER) for r in pilot_corpus.ROLES}
    with pytest.raises(pilot.BudgetStop):
        _run(corpus, tmp_path, dict(pilot.capped(budget, lambda _setup: fakes)(None)))
    # 1.00, then 0.10 (1.10 + 1.00 > 2.05 would stop the third), so two ran.
    assert budget.sessions == 2
