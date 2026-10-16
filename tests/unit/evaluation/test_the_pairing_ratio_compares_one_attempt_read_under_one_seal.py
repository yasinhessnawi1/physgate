"""Paired over generalist is read from two review lines, and only of one attempt under one seal.

The figures are exact: the reviewer model's list prices from the recorded sheet,
and known tokens on each review. A ratio between reviews of different attempts,
different seals, different commits or different models is refused, never printed.
"""

from __future__ import annotations

import json
from decimal import Decimal
from pathlib import Path
from typing import Any, Literal

import pytest
from observe_rig import config, target_repo

from physgate.evaluation.observe.cost import load_price_sheet
from physgate.evaluation.observe.exceptions import ManifestError, PriceSheetError
from physgate.evaluation.observe.generalist import review_ratio
from physgate.orchestrator.protocols import Artefact, MessageUsage, ReviewResult, Usage
from physgate.orchestrator.run_config import write_run_config
from physgate.orchestrator.trajectory import Seal
from physgate.reviewers.packet import Packet

MODEL = "claude-sonnet-5"
#: The sheet that prices each call's cache writes by the cache its result names.
NEW = "2026-10-16"
SEAL = Seal(sha256="a" * 64, length=100)


def _artefact(**overrides: Any) -> Artefact:  # noqa: ANN401
    fields: dict[str, Any] = {
        "subtask_id": "s1",
        "attempt": 1,
        "assigned_role": "control",
        "attempt_commit": "c" * 40,
        "worktree": "/w",
        "graph_root": "/w/g",
        "trajectory": "/t/stdout.jsonl",
        "trajectory_sha256": SEAL.sha256,
        "trajectory_length": SEAL.length,
        "scopes": ("subtask",),
        "base_revision": 0,
        "base_commit": "b" * 40,
    }
    fields.update(overrides)
    return Artefact(**fields)


def _packet(seal: Seal = SEAL, **artefact: Any) -> Packet:  # noqa: ANN401
    return Packet(
        read_root="/r/read",
        trajectory_seal=seal,
        transcript_sha256="1" * 64,
        transcript_nonce=None,
        diff_sha256="2" * 64,
        spec_as_issued_sha256=None,
        rubric_sha256="3" * 64,
        knowledge_sha256={},
        worktree_files=1,
        indicators=(),
        required_reading=("/r/read/transcript.md", "/r/read/rubric.md"),
        artefact=_artefact(**artefact),
    )


def _review(
    kind: Literal["paired", "generalist"], input_tokens: int, model: str = MODEL
) -> ReviewResult:
    usage = Usage(
        input_tokens=input_tokens,
        output_tokens=0,
        cache_read_input_tokens=0,
        cache_creation_input_tokens=0,
    )
    return ReviewResult(
        verdict="pass",
        finding="every item is met",
        reviewer_model=model,
        session_id=f"{kind}-1",
        usage=(MessageUsage(message_id=f"m-{kind}", usage=usage),),
        rubric_kind=kind,
        peak_context_tokens=input_tokens,
    )


def test_the_ratio_is_paired_over_generalist_tokens_and_cost() -> None:
    sheet = load_price_sheet("2026-09-27")
    paired = (_review("paired", 2_000_000), _packet())
    ratio = review_ratio(paired, (_review("generalist", 1_000_000), _packet()), sheet)
    assert ratio.token_ratio == Decimal(2) and ratio.usd_ratio == Decimal(2)
    assert ratio.paired.usd == Decimal(4)  # two million input tokens at 2 USD per million
    assert ratio.paired.nok == Decimal(4) * sheet.sheet.exchange.usd_to_nok
    assert (ratio.trajectory_seal, ratio.attempt_commit, ratio.n) == (SEAL, "c" * 40, 1)


@pytest.mark.parametrize(
    ("generalist_packet", "model", "why"),
    [
        (_packet(Seal(sha256="f" * 64, length=100)), MODEL, "different seals"),
        (_packet(attempt_commit="d" * 40), MODEL, "same attempt at the same commit"),
        (_packet(attempt=2), MODEL, "same attempt at the same commit"),
        (_packet(), "claude-opus-5-5", "different models"),
    ],
    ids=["seal", "commit", "attempt", "model"],
)
def test_a_ratio_across_two_readings_is_refused(
    generalist_packet: Packet, model: str, why: str
) -> None:
    sheet = load_price_sheet("2026-09-27")
    with pytest.raises(ManifestError, match=why):
        review_ratio(
            (_review("paired", 2), _packet()),
            (_review("generalist", 1, model), generalist_packet),
            sheet,
        )


def test_the_two_reviews_must_be_one_of_each_kind() -> None:
    sheet = load_price_sheet("2026-09-27")
    with pytest.raises(ManifestError, match="one paired review over one generalist"):
        review_ratio((_review("paired", 2), _packet()), (_review("paired", 1), _packet()), sheet)


def test_a_sheet_that_prices_each_call_s_writes_is_refused_for_a_ratio() -> None:
    """A review line does not say which cache a write went to, so the sheet could not apply.

    Priced anyway, every write would be at the five-minute rate without the ratio saying
    so; the ratio is refused instead, and its command refuses before any review runs.
    """
    paired = (_review("paired", 2_000_000), _packet())
    with pytest.raises(PriceSheetError, match="each call's writes") as refused:
        review_ratio(paired, (_review("generalist", 1_000_000), _packet()), load_price_sheet(NEW))
    assert refused.value.context == {"date": NEW}


def test_the_generalist_command_refuses_that_sheet_before_any_review(
    tmp_path: Path, capsys: pytest.CaptureFixture[str], monkeypatch: pytest.MonkeyPatch
) -> None:
    from physgate.cli import main
    from physgate.evaluation.observe import generalist

    run_dir = tmp_path / "run"
    run_dir.mkdir()
    write_run_config(run_dir / "run.json", config("r", target_repo(tmp_path), endpoint="default"))
    monkeypatch.delenv("ANTHROPIC_BASE_URL", raising=False)

    def never(**_: object) -> None:
        raise AssertionError("a review ran at a sheet the ratio refuses")

    monkeypatch.setattr(generalist, "run_generalist", never)
    args = ["generalist", "--run-dir", str(run_dir), "--subtask", "s1", "--attempt", "1"]
    args += ["--target", str(tmp_path), "--install", str(tmp_path), "--review-root", "/nowhere"]
    args += ["--out", str(tmp_path / "out"), "--run-id", "g-1", "--prices", NEW]
    assert main(args) == 2
    assert "each call's writes" in json.loads(capsys.readouterr().err)["error"]
