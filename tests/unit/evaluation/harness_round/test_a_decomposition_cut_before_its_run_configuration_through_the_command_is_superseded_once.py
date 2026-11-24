"""A decomposition the command itself left before its run's configuration is superseded once.

The round's other rows stand in for ``physgate decompose``. Here the round calls the command as it
calls it for a measured round (its own command driver, in this process), with the plan's review
on (``design_review: observe``) and the call and the review scripted as the usage limit's rows
script them. The decomposition is cut once its run's record is opened and its branch's checkout
made, before its configuration is recorded: by the core's own start raising (the target refusing
the library; the round's process then killed before it reads the directory), or by the process
killed where the start makes its first commit.

So the trial's directory holds the target's clone, with the run branch's deep refs, and no run
configuration. What the command itself recorded first (its parameters with the target) is what the
exposure register reads it by: the restart reads the register whole, supersedes the directory
once, naming its cause and its spend, and the trial goes on to a counted result in a fresh one.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import pytest
from round_rig import SCORED, Killed, Rig, make_rig
from test_a_decomposition_the_usage_limit_stopped_through_the_command_is_waited_for_and_made_again import (  # noqa: E501
    PLANNED,
    REVIEWED,
    ThroughTheCommand,
)

from physgate.evaluation.harness_round import (
    HARNESS_ROUNDS,
    LEDGER,
    ROUND_RECORD,
    Decompose,
    RoundError,
    run_round,
)
from physgate.evaluation.tiers.exposure import MOST_DEPTH, exposed_versions
from physgate.evaluation.tiers.store import withheld_root
from physgate.knowledge.library import LibraryError
from physgate.orchestrator import decompose as core_decompose

#: What the cut decomposition spent, on its round journal's end line: the call and the review.
SPENT = PLANNED.total() + REVIEWED.total()


@dataclass
class CutThroughTheCommand(ThroughTheCommand):
    """``physgate decompose`` as the round calls it, cut before its configuration where named.

    ``cut`` maps a decomposition's number across the row to how it is cut: ``raised`` (the core's
    start refuses to put the library into the target, once the run's record is opened, and the
    round's process is killed once the command has exited) or ``killed`` (the process killed at
    the start's first commit).
    """

    cut: dict[int, str] = field(default_factory=dict)

    def decompose(self, call: Decompose) -> int:
        how = self.cut.get(len(self.decomposed) + 1)
        with pytest.MonkeyPatch.context() as patch:
            if how == "raised":

                def refusing(*_a: Any, **_k: Any) -> Any:  # noqa: ANN401
                    msg = "the target holds other bytes where the library goes"
                    raise LibraryError(msg)

                patch.setattr(core_decompose, "put_into", refusing)
            elif how == "killed":

                def killed(*_a: Any, **_k: Any) -> Any:  # noqa: ANN401
                    raise Killed

                patch.setattr(core_decompose, "commit_all", killed)
            code = super().decompose(call)
        if how == "raised":
            # The command refused the void it ended on, and the round never read its directory.
            assert code == 2, code
            raise Killed
        return code


def _score(_task: Any, _answer: Path) -> dict[str, Any]:  # noqa: ANN401
    return dict(SCORED)


def _driver(rig: Rig, **how: Any) -> CutThroughTheCommand:  # noqa: ANN401
    return CutThroughTheCommand(library=rig.library, answer_name=rig.task().answer.path, **how)


def _go(rig: Rig, driver: CutThroughTheCommand, slept: list[float], *, resume: bool) -> str:
    try:
        status, _ = run_round(
            rig.inputs(trials=1), driver=driver, scorer=_score, resume=resume, sleep=slept.append
        )
    except RoundError as exc:
        return f"refused:{exc.context.get('refused_because')}: {exc}"
    return status


def _place(rig: Rig) -> Path:
    summary = json.loads((rig.root / "out" / ROUND_RECORD).read_bytes())
    return withheld_root(rig.made.store, "control") / HARNESS_ROUNDS / str(summary["round"])


def _ledger(rig: Rig, kind: str) -> list[dict[str, Any]]:
    lines = [json.loads(x) for x in (_place(rig) / LEDGER).read_bytes().splitlines()]
    return [x for x in lines if x["kind"] == kind]


def _outcomes(rig: Rig) -> list[str]:
    path = rig.root / "out" / "visible.trials.jsonl"
    return [json.loads(x)["outcome"] for x in path.read_text().splitlines()]


def _deepest(directory: Path, beneath: Path) -> int:
    """How deep the deepest directory in ``directory`` lies beneath ``beneath``."""
    return max(len(p.relative_to(beneath).parts) for p in directory.rglob("*") if p.is_dir())


@pytest.mark.parametrize("how", ["raised", "killed"])
def test_a_decomposition_the_command_left_without_its_configuration_is_superseded_once(
    tmp_path: Path, how: str
) -> None:
    rig, slept = make_rig(tmp_path, design_review="observe"), list[float]()
    with pytest.raises(Killed):
        _go(rig, _driver(rig, cut={1: how}), slept, resume=False)
    left = rig.run_root / _place(rig).name / "0000-1"
    # What the command left: its log opened, no configuration, and the target's clone with the
    # run branch's refs deeper than the register's walk goes.
    assert (left / "events.jsonl").is_file() and not (left / "run.json").exists()
    assert _deepest(left / "target", rig.run_root) > MOST_DEPTH
    # The restart reads the register whole: the clone is the decomposition's own, by the
    # parameters record the command wrote first, with the target.
    then = _driver(rig)
    assert _go(rig, then, slept, resume=True) == "done"
    recorded = json.loads((left / "params_source.json").read_bytes())
    assert recorded.get("target") == str((left / "target").resolve())
    assert exposed_versions(rig.made.store, "control") == frozenset()
    gone = [(x["attempt"], x["cause"], x["tokens"], x["by"]) for x in _ledger(rig, "superseded")]
    assert len(gone) == 1, gone
    ((attempt, cause, tokens, by),) = gone
    assert (attempt, tokens, by) == (1, SPENT, "rule")
    assert (cause == "killed") is (how == "killed"), cause
    assert [c.run_dir.name for c in then.decomposed] == ["0000-2"]
    assert slept == [7.0] and _outcomes(rig) == ["pass"]
    # Started again, the round reads the register whole once more and has nothing left to make.
    again = _driver(rig)
    assert _go(rig, again, slept, resume=True) == "done"
    assert again.decomposed == [] and again.drives == []
    assert exposed_versions(rig.made.store, "control") == frozenset()
