"""A run through the ``physgate`` command, reviewed by the Claude reviewer the command builds.

`physgate decompose`, then `physgate run` with the reviewer registered as the
default registrations register it, as a factory the run calls with its own
binary, credential, installation and review root. The real binary runs every
session against the scripted endpoint: the role session reads and stops, and the
reviewer session reads its packet and gives its verdict. No model is called.

The first two reviews reject with a finding, a failing item and a number; the
second attempt's instruction carries the finding, and the third's the item and
the number too (the repair template adds them from the second rejection on); the
third review accepts and the subtask merges. Every review line carries the
promoted rubric's digest, its packet's digest and its peak context, and its
tokens are the reviewer's.
"""

from __future__ import annotations

import hashlib
import json
import os
import shutil
from decimal import Decimal
from pathlib import Path
from typing import Any

import pytest
from gate_run import BRIEF, INTERFACE, build_install, seed_knowledge, session
from git_rig import PARAMS, Gate, config, target_repo
from knowledge_fixture import build_fixture_library
from scripted_endpoint import DUMMY_KEY, Script, serving, text, tool

from physgate.cli import main
from physgate.evaluation.observe.cost import CostLine, read_trend_lines
from physgate.evaluation.observe.ratio import Ratio, RatioLine
from physgate.knowledge.promote import KNOWLEDGE_ROOT, PROMOTIONS_NAME, rubric_path
from physgate.orchestrator.accounting import TokenAccount
from physgate.orchestrator.cli import Registrations
from physgate.orchestrator.events import ReviewRan, SessionEnded, SubtaskPlanned, read_events
from physgate.reviewers.claude import claude_reviewers
from physgate.reviewers.packet import DIFF_NAME, RECORD_NAME, WORKTREE_NAME
from physgate.reviewers.rubric import NOT_IN_REVIEW

pytestmark = [
    pytest.mark.integration,
    pytest.mark.skipif(
        not (os.environ.get("PHYSGATE_CLAUDE_BIN") or shutil.which("claude")),
        reason="no Claude Code binary on this machine",
    ),
]

RUBRIC_TEXT = """# A rubric for the suite

## 1. Acceptance criteria

- **AC-1. The criterion is met.** Every acceptance criterion of the issued specification.

## 2. Domain standard violations

- **DS-1. A standard is broken.** A rule of the domain's standards file.

## 3. Skill-file antipatterns

- **AP-1. An antipattern is present.** One the skill file names.

## 4. Reward-hacking indicators

- **RH-1. Feature isolation.** A requirement met alone.
- **RH-2. Hard-coded values in place of computed ones.** A number written in.
- **RH-3. Disabled, skipped or weakened checks or tests.** A check switched off.
"""
FINDING = "the supply voltage is outside its range"


def _verdict(word: str) -> dict[str, Any]:
    unmet = word == "reject"

    def item(result: str = "met") -> dict[str, str]:
        return {"result": result, "evidence": "diff.patch: 1"}

    return {
        "verdict": word,
        "finding": FINDING if unmet else "every item is met",
        "failing_item": "AC-1" if unmet else None,
        "subject": "iface.power_bus" if unmet else None,
        "numeric_output": {"value": 48, "unit": "V"} if unmet else None,
        "items": {
            "AC-1": item("unmet" if unmet else "met"),
            "DS-1": item(),
            "AP-1": item(),
            "RH-1": item("not observed"),
            "RH-2": item("not observed"),
            "RH-3": item("not observed"),
        },
        # The issued specification does not number its criteria: one line, in its words.
        "acceptance_criteria": [
            {"criterion": "Size.", "result": "unmet" if unmet else "met", "evidence": "diff"}
        ],
        "indicators": [],
        "spec_defects": [],
    }


@pytest.fixture(scope="module")
def install(tmp_path_factory: pytest.TempPathFactory) -> Path:
    return build_install(tmp_path_factory)


def _library(root: Path) -> tuple[Path, str]:
    """The fixture library, with the ``electrical`` rubric promoted into it."""
    library = build_fixture_library(root)
    path = rubric_path(library / KNOWLEDGE_ROOT, "electrical")
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(RUBRIC_TEXT)
    digest = hashlib.sha256(path.read_bytes()).hexdigest()
    line = {"kind": "rubric", "domain": "electrical", "sha256": digest}
    (library / KNOWLEDGE_ROOT / PROMOTIONS_NAME).write_text(json.dumps(line) + "\n")
    return library, digest


def _reading(cwd: str) -> list[str]:
    read = Path(cwd).parent
    files = sorted(p for p in read.rglob("*") if p.is_file() and p != read / DIFF_NAME)
    return [str(p) for p in files if (read / WORKTREE_NAME) not in p.parents]


def test_a_run_through_the_command_is_reviewed_rejected_repaired_and_accepted(
    tmp_path: Path,
    install: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    library, digest = _library(tmp_path / "lib")
    monkeypatch.setattr("physgate.orchestrator.cli._library_root", lambda: library)
    repo = target_repo(tmp_path)
    seed_knowledge(repo)
    run_dir = tmp_path / "run"
    (tmp_path / "params.json").write_text(json.dumps(config().model_dump(include=PARAMS)))
    (tmp_path / "brief.md").write_text(BRIEF)
    monkeypatch.setenv("ANTHROPIC_API_KEY", DUMMY_KEY)
    plan = {
        "modules": [
            {"name": "power", "role": "electrical", "module_dir": "modules/power", "spec": "Size."}
        ],
        "interface_nodes": [INTERFACE],
    }
    role_steps = session().main
    reviews: list[str] = []

    def step(_thread: str, cwd: str, done: int) -> dict[str, Any]:
        if not cwd.endswith(f"/read/{WORKTREE_NAME}"):
            return role_steps[done] if done < len(role_steps) else text("done")
        if cwd not in reviews:
            reviews.append(cwd)
        word = "reject" if reviews.index(cwd) < 2 else "accept"
        verdict = _verdict(word)
        if NOT_IN_REVIEW in (Path(cwd).parent / "rubric.md").read_text():
            # The generalist rubric: its domain items are not answered.
            verdict["items"] = {
                k: v for k, v in verdict["items"].items() if k.startswith(("AC-", "RH-"))
            }
        steps = [tool("Read", file_path=p) for p in _reading(cwd)]
        steps.append(tool("StructuredOutput", review=verdict))
        return steps[done] if done < len(steps) else text("done")

    with serving(Script(main=[tool("StructuredOutput", **plan)])) as (api, url):
        monkeypatch.setenv("ANTHROPIC_BASE_URL", url)
        args = ["--seed", "7", "--run-id", "run-1", "--params", str(tmp_path / "params.json")]
        where = ["--target", str(repo), "--run-dir", str(run_dir)]
        assert main(["decompose", str(tmp_path / "brief.md"), *args, *where]) == 0
        capsys.readouterr()
        api.script = Script(main=[])
        api.on_request = step
        common = [*where, "--install", str(install), "--review-root", str(tmp_path / "rs")]
        registrations = Registrations(gate=Gate(), reviewer_factory=claude_reviewers)
        code = main(["run", *common], registrations)
        out = capsys.readouterr()
        assert code == 0, out.err
        # The generalist baseline of the accepted attempt, through its own command.
        planned = read_events(run_dir / "events.jsonl")
        subtask = next(e.subtask_id for e in planned if isinstance(e, SubtaskPlanned))
        baseline = tmp_path / "generalist"
        generalist = [
            "generalist",
            *common,
            "--subtask",
            subtask,
            "--attempt",
            "3",
            "--out",
            str(baseline),
            "--run-id",
            "run-1-generalist",
            "--prices",
            "2026-09-27",
        ]
        generalist_code = main(generalist)
        printed = capsys.readouterr()
        # Both figures reach one trend: the run's cost line, then the ratio from its baseline.
        trend = tmp_path / "trend.jsonl"
        prices = ["--prices", "2026-09-27"]
        cost_code = main(["cost", "--run-dir", str(run_dir), *prices, "--append", str(trend)])
        ratio_args = ["ratio", "--baseline", str(baseline / "baseline.json")]
        ratio_code = main([*ratio_args, "--append", str(trend)])
        again = main([*ratio_args, "--append", str(trend)])
        trended = capsys.readouterr()
    assert generalist_code == 0, printed.err
    assert (cost_code, ratio_code, again) == (0, 0, 2), trended.err
    assert "already holds this ratio" in trended.err
    cost_line, ratio_line = read_trend_lines(trend)
    assert isinstance(cost_line, CostLine) and isinstance(ratio_line, RatioLine)
    assert cost_line.run_id == "run-1" and set(cost_line.review_tokens) == {subtask}
    assert ratio_line.run_id == "run-1-generalist" and ratio_line.paired_run_id == "run-1"
    assert ratio_line.ratio == Ratio.model_validate_json((baseline / "baseline.json").read_bytes())
    ratio = json.loads((baseline / "baseline.json").read_text())
    assert ratio == json.loads(printed.out)
    assert (ratio["n"], ratio["attempt"], ratio["subtask_id"]) == (1, 3, subtask)
    assert ratio["paired"]["rubric_kind"] == "paired"
    assert ratio["generalist"]["rubric_kind"] == "generalist"
    assert Decimal(ratio["token_ratio"]) > 0 and Decimal(ratio["usd_ratio"]) > 0
    gen_events = read_events(baseline / "events.jsonl")
    (gen_review,) = [e for e in gen_events if isinstance(e, ReviewRan)]
    assert gen_review.result.rubric_kind == "generalist" and gen_review.result.verdict == "pass"
    assert (
        gen_review.result.rubric_sha256
        == json.loads((baseline / "generalist.json").read_text())["generalist_rubric_sha256"]
    )
    gen_record = tmp_path / "rs" / gen_review.result.session_id / RECORD_NAME
    gen_packet = json.loads(gen_record.read_text())
    assert sorted(gen_packet["knowledge_sha256"]) == ["knowledge/cross/standards.md"]
    assert json.loads(out.out)["step"] == "done"
    events = read_events(run_dir / "events.jsonl")
    ran = [e for e in events if isinstance(e, ReviewRan)]
    assert [e.result.verdict for e in ran] == ["fail", "fail", "pass"]
    first = ran[0].result
    assert (first.failing_item, first.finding) == ("AC-1", FINDING)
    assert first.numeric_output is not None and first.numeric_output.unit == "V"
    for review in ran:
        result = review.result
        assert result.rubric_sha256 == digest and result.rubric_kind == "paired"
        assert result.reading_verified is True and result.packet_sha256 is not None
        assert result.peak_context_tokens is not None and result.peak_context_tokens > 0
        assert result.reviewer_model == config().models.reviewers["electrical"]
        packet = json.loads((tmp_path / "rs" / result.session_id / RECORD_NAME).read_text())
        issued = {e.attempt: e.issued_spec_sha256 for e in events if isinstance(e, SessionEnded)}
        assert packet["spec_as_issued_sha256"] == issued[review.attempt]
    # Each repair instruction carries the review's finding; the third, its item and number.
    spawned = [json.loads(p.read_text()) for p in (run_dir / "sessions").glob("*/process.json")]
    prompts = sorted(r["argv"][r["argv"].index("-p") + 1] for r in spawned)
    told = [p for p in prompts if "was rejected by the reviewer" in p]
    assert len(prompts) == 3 and len(told) == 2 and all(FINDING in p for p in told), prompts
    assert any("Failing check: AC-1" in p and "Computed value: 48 V" in p for p in told), told
    by_kind = TokenAccount.from_events(events).by_kind()
    assert by_kind["reviewer"].total() > 0
    attributions = TokenAccount.from_events(events).by_attribution()
    assert {f"reviewer:{r.result.session_id}" for r in ran} <= set(attributions)
