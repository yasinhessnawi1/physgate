"""The validation tier is a protected tier, and no canary is put where a session reads.

The validation tier is kept from implementers exactly as the held-out tier is: its tasks are
marked ``validation``, each carries a canary, and the pre-run scan holds a root the run records
as validation to that label, as it holds a held-out root to its own.

A task's canary never appears in its brief, its inputs or its answer contract, the parts a
session is given: a canary in a brief would turn every measurement into an exposure.
"""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any

import pytest
from task_fixtures import controller, own_task, write_task_dir

from physgate.evaluation.per_role.exceptions import TaskFormatError
from physgate.evaluation.tiers.authoring import sha256sums
from physgate.evaluation.tiers.heldout import scan
from physgate.evaluation.tiers.task import parse_task

CANARY_A = "a" * 32
CANARY_B = "b" * 32


def _task(**change: Any) -> dict[str, Any]:
    return own_task(**change)


def _parses(task: dict[str, Any]) -> str | None:
    """Why ``task`` is refused, or ``None`` when it is a task."""
    try:
        parse_task(json.dumps(task).encode())
    except TaskFormatError as exc:
        return str(exc)
    return None


# ------------------------------------------------------------- the validation label


def test_a_validation_task_carrying_its_canary_is_a_task() -> None:
    refused = _parses(_task(tier="validation", canary=CANARY_A))
    assert refused is None, f"a validation task was refused: {refused}"


def test_a_validation_task_without_a_canary_is_refused() -> None:
    assert _parses(_task(tier="validation", canary=None)) is not None
    # Control: the label is known, so the refusal is of the missing canary.
    assert _parses(_task(tier="validation", canary=CANARY_A)) is None


def _tier(base: Path, label: str) -> Path:
    root = base / "private" / label
    for i, canary in enumerate((CANARY_A, CANARY_B)):
        write_task_dir(
            root / f"control.p{i}",
            own_task(id=f"control.p{i}", tier=label, canary=canary),
            {"good": (controller(), None), "bad_slow": (controller(), "settling")},
        )
    (root / "SHA256SUMS").write_text(sha256sums(root))
    (root / "canaries.json").write_text(json.dumps([CANARY_A, CANARY_B]))
    return root


def _scan(base: Path, root: Path, label: str | None) -> list[str]:
    (base / "runs").mkdir(exist_ok=True)
    kw: dict[str, Any] = {} if label is None else {"label": label}
    try:
        return scan(
            root,
            run_held_out=(str(root),),
            run_digests={str(root): hashlib.sha256(sha256sums(root).encode()).hexdigest()},
            run_canaries=(CANARY_A, CANARY_B),
            places={"run directory": base / "runs"},
            scratch=base / "scan",
            **kw,
        )
    except TypeError as exc:
        pytest.fail(f"the scan cannot be told a root is the validation tier: {exc}")


def test_a_root_the_run_records_as_validation_is_scanned_for_validation_tasks(
    tmp_path: Path,
) -> None:
    base = tmp_path.resolve()
    assert _scan(base, _tier(base, "validation"), "validation") == []


def test_a_validation_root_holding_held_out_tasks_refuses_the_run(tmp_path: Path) -> None:
    base = tmp_path.resolve()
    problems = _scan(base, _tier(base, "held_out"), "validation")
    assert any("not marked validation" in p for p in problems), problems


def test_a_held_out_root_holding_validation_tasks_refuses_the_run(tmp_path: Path) -> None:
    base = tmp_path.resolve()
    problems = _scan(base, _tier(base, "validation"), None)
    assert any("not marked held out" in p for p in problems), problems


# --------------------------------------------- no canary where a session reads it


@pytest.mark.parametrize("tier", ["held_out", "validation"])
@pytest.mark.parametrize(
    "where",
    ["the brief", "the brief in capitals", "an input's name", "the answer's path"],
)
def test_a_task_whose_canary_is_in_what_a_session_reads_is_refused(tier: str, where: str) -> None:
    canary = "c0ffee" + "1" * 26
    task = _task(tier=tier, canary=canary)
    if where == "the brief":
        task["brief"] += f" Ref {canary}."
    elif where == "the brief in capitals":
        task["brief"] += f" Ref {canary.upper()}."
    elif where == "an input's name":
        task["inputs"] = [{"name": canary, "value": 1.0, "unit": "1"}]
    else:
        task["answer"] = {"path": f"{canary}.json", "form": "lti_tf"}
    refused = _parses(task)
    assert refused is not None and "canary" in refused, (
        f"a {tier} task whose canary is in {where} was taken: {refused}"
    )


def test_a_canary_kept_out_of_what_a_session_reads_is_no_reason_to_refuse() -> None:
    # Control: only where a session reads it; the canary field itself is the task's own.
    assert _parses(_task(tier="held_out", canary="c0ffee" + "1" * 26)) is None
