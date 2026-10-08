"""The first real paired reviews' submissions, replayed: refused in the session, then corrected.

The two real reviews read everything they had to and submitted a verdict that grouped
items, listed the issued specification's criteria in place of the rubric's ids, and used
results their sections do not allow. The binary accepted them, since the schema it was
offered said nothing of that, and the harness's check refused them after the sessions had
ended. Each submission is kept as the model sent it (``replayed/``).

Now the schema is the rubric's own. Replayed against each role's promoted rubric through
the real binary, each submission is refused inside the session, the reviewer is told why,
and the corrected verdict it then submits stands: the review is a verdict, and it records
the one refusal on the way. So is each other breach of the contract, one per case.
"""

from __future__ import annotations

import copy
import json
import os
from pathlib import Path
from typing import Any

import pytest
from scripted_endpoint import DUMMY_KEY, Script, serving, text, tool
from test_a_claude_review_is_a_verdict_only_when_it_read_everything import (
    _attempt,
    _config,
    _reading,
)

from physgate.orchestrator.credentials import Credential
from physgate.orchestrator.decompose import binary_version
from physgate.orchestrator.install import prepare_install
from physgate.orchestrator.protocols import ReviewResult
from physgate.orchestrator.run_config import ModelStrings
from physgate.reviewers.claude import ClaudeReviewer, ReviewerSetup
from physgate.reviewers.rubric import RubricItem, load_rubric

BINARIES = [
    b
    for b in (
        os.environ.get("PHYSGATE_PINNED_BINS") or os.environ.get("PHYSGATE_CLAUDE_BIN") or ""
    ).split(os.pathsep)
    if b
]
pytestmark = [
    pytest.mark.integration,
    pytest.mark.skipif(not BINARIES, reason="no pinned Claude Code binary named on this machine"),
]

REPO = Path(__file__).resolve().parents[3]
REPLAYED = Path(__file__).resolve().parent / "replayed"
REFUSED = "Output does not match required schema"


def valid(items: tuple[RubricItem, ...]) -> dict[str, Any]:
    """The corrected verdict: every item by its id in its section's words; the one criterion."""
    clean = {
        "acceptance_criteria": "met",
        "domain_standards": "n/a",
        "antipatterns": "n/a",
        "reward_hacking": "not observed",
    }
    return {
        "verdict": "accept",
        "finding": "every item is met",
        "failing_item": None,
        "subject": None,
        "numeric_output": None,
        "items": {
            i.id: {"result": clean[i.section], "evidence": "diff.patch: the one file it adds"}
            for i in items
        },
        "acceptance_criteria": [{"criterion": "1", "result": "met", "evidence": "m/ctl.py:1"}],
        "indicators": [],
        "spec_defects": [],
    }


def breach(name: str, items: tuple[RubricItem, ...]) -> dict[str, Any]:
    """A verdict breaking the contract one way, ``name``."""
    answer = copy.deepcopy(valid(items))
    entries = answer["items"]
    ds = [i.id for i in items if i.section == "domain_standards"]
    rh = next(i.id for i in items if i.section == "reward_hacking")
    ac = next(i.id for i in items if i.section == "acceptance_criteria")
    if name == "grouped ids":
        entries[f"{ds[0]}/{ds[1]}"] = entries.pop(ds[0])
        del entries[ds[1]]
    elif name == "an unknown id":
        entries["X-99"] = {"result": "met", "evidence": "e"}
    elif name == "a missing id":
        del entries[ds[0]]
    elif name == "n/a on a reward-hacking item":
        entries[rh] = {"result": "n/a", "evidence": "e"}
    elif name == "noted on a standard":
        entries[ds[0]] = {"result": "noted", "evidence": "e"}
    elif name == "accept beside an unmet item":
        entries[ac] = {"result": "unmet", "evidence": "e"}
    elif name == "no criterion line":
        answer["acceptance_criteria"] = []
    elif name == "not evaluable with no defect":
        entries[ds[0]] = {"result": "not evaluable", "evidence": "no pole given"}
    return answer


@pytest.fixture(scope="module")
def install(tmp_path_factory: pytest.TempPathFactory) -> Path:
    return prepare_install(tmp_path_factory.mktemp("install") / "i", REPO)


@pytest.fixture(params=BINARIES, ids=lambda b: Path(b).name)
def binary(request: pytest.FixtureRequest) -> str:
    return str(request.param)


def _review(
    tmp_path: Path, install: Path, binary: str, role: str, first: dict[str, Any]
) -> tuple[ReviewResult, list[str]]:
    """Read everything, submit ``first``, then the corrected verdict; the result, what was told."""
    rubric = load_rubric(REPO / "knowledge", role)
    attempt = _attempt(tmp_path).model_copy(update={"assigned_role": role})
    pins = ModelStrings(
        decomposition="claude-sonnet-5",
        roles={role: "claude-opus-5-5"},
        reviewers={role: "claude-sonnet-5"},
    )
    config = _config(binary_version(binary)).model_copy(update={"models": pins})
    corrected = valid(rubric.items)

    def step(_thread: str, cwd: str, done: int) -> dict[str, Any]:
        steps = [tool("Read", file_path=p) for p in _reading(cwd)]
        steps += [tool("StructuredOutput", **first), tool("StructuredOutput", review=corrected)]
        return steps[done] if done < len(steps) else text("done")

    with serving(Script(main=[])) as (api, url):
        api.on_request = step
        setup = ReviewerSetup.of_run(
            config,
            review_root=tmp_path / "rs",
            repo=Path(attempt.worktree),
            install_bin=install,
            binary=binary,
            base_url=url,
            credential=Credential(mode="api_key", secret=DUMMY_KEY),
            library=REPO,
        )
        result = ClaudeReviewer(role=role, setup=setup, rubric=rubric).review(attempt)
        told = [r.last_user for r in api.requests]
    return result, told


@pytest.mark.parametrize("role", ["control", "firmware"])
def test_a_real_submission_is_refused_in_the_session_and_the_corrected_one_stands(
    tmp_path: Path, install: Path, binary: str, role: str
) -> None:
    submitted = json.loads((REPLAYED / f"review_submission_{role}.json").read_text())
    # Sent as the contract now asks, inside its wrapper; its content as the model wrote it.
    result, told = _review(tmp_path, install, binary, role, {"review": submitted})
    refusals = [t for t in told if t.startswith(REFUSED)]
    assert len(refusals) == 1, told[-3:]
    assert "/review/items" in refusals[0]  # told what was wrong with its items
    assert result.verdict == "pass" and result.schema_refusals == 1
    assert len(result.items) == len(load_rubric(REPO / "knowledge", role).items)


@pytest.mark.parametrize(
    ("role", "name"),
    [
        ("control", "grouped ids"),
        ("control", "an unknown id"),
        ("firmware", "a missing id"),
        ("firmware", "n/a on a reward-hacking item"),
        ("control", "noted on a standard"),
        ("firmware", "accept beside an unmet item"),
        ("control", "no criterion line"),
        ("firmware", "not evaluable with no defect"),
    ],
)
def test_each_breach_is_refused_in_the_session_and_the_reviewer_corrects_it(
    tmp_path: Path, install: Path, binary: str, role: str, name: str
) -> None:
    items = load_rubric(REPO / "knowledge", role).items
    result, told = _review(tmp_path, install, binary, role, {"review": breach(name, items)})
    assert sum(t.startswith(REFUSED) for t in told) == 1, name
    assert result.verdict == "pass" and result.schema_refusals == 1
