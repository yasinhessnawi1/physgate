"""A rerun of a run that reviewed its plan decomposes it as the run was decomposed.

``decompose`` refuses a run that reviews its plan unless it names the hooks' installation and the
place its review runs under, so the rerun's driver passes both to ``decompose`` whenever the
recorded ``design_review`` is not ``off``; a run that never reviewed its plan is decomposed with
the arguments it always had.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "orchestrator"))

from test_decompose_reviews_the_plan_before_it_writes_anything import (  # noqa: E402
    REVIEWING,
    StandIn,
    _args,
    _verdict,
    calls,  # noqa: F401 - the fixture
)

import physgate.cli  # noqa: E402
import physgate.orchestrator.cli as orchestrator_cli  # noqa: E402
from physgate.evaluation.observe.exceptions import RerunError  # noqa: E402
from physgate.evaluation.observe.rerun import through_the_command  # noqa: E402


def _plan(tmp_path: Path, mode: str) -> Any:  # noqa: ANN401 - the driver's plan, stood in
    args = _args(tmp_path, {**REVIEWING, "design_review": mode}, places=True)
    params = json.loads(Path(args[args.index("--params") + 1]).read_text())
    return SimpleNamespace(
        recorded=SimpleNamespace(claude_version="2.1.272", seed=7),
        params=lambda: params,
        brief=Path(args[1]),
        run_id="run-1",
        target=Path(args[args.index("--target") + 1]),
        run_dir=tmp_path / "rerun",
        install=Path(args[args.index("--install") + 1]),
        review_root=Path(args[args.index("--review-root") + 1]),
    )


@pytest.mark.parametrize("mode", ["off", "observe", "on"])
def test_the_rerun_names_the_installation_and_review_root_to_decompose_when_it_reviews(
    tmp_path: Path,
    calls: Any,  # noqa: ANN401, F811 - the fixture
    monkeypatch: pytest.MonkeyPatch,
    mode: str,
) -> None:
    plan = _plan(tmp_path, mode)
    asked: list[list[str]] = []

    def main(argv: list[str], registrations: Any = None) -> int:  # noqa: ANN401
        asked.append(list(argv))
        return 0

    monkeypatch.setattr(physgate.cli, "main", main)
    through_the_command()(plan)
    decompose = next(argv for argv in asked if argv[0] == "decompose")
    places = ["--install", str(plan.install), "--review-root", str(plan.review_root)]
    if mode == "off":
        assert "--install" not in decompose and "--review-root" not in decompose
    else:
        assert decompose[-4:] == places, decompose


@pytest.mark.parametrize("mode", ["observe", "on"])
def test_a_rerun_of_a_reviewed_run_is_decomposed_not_refused(
    tmp_path: Path,
    calls: Any,  # noqa: ANN401, F811 - the fixture
    monkeypatch: pytest.MonkeyPatch,
    mode: str,
) -> None:
    plan = _plan(tmp_path, mode)
    real = physgate.cli.main
    codes: dict[str, int] = {}

    def main(argv: list[str], registrations: Any = None) -> int:  # noqa: ANN401
        if argv[0] != "decompose":
            return 0  # the run itself is not this row's: only that decompose takes the rerun
        codes["decompose"] = real(argv, registrations)
        return codes["decompose"]

    monkeypatch.setattr(physgate.cli, "main", main)
    registrations = orchestrator_cli.Registrations(
        plan_reviewer_factory=StandIn(_verdict("pass")).factory
    )
    found: Exception | None = None
    try:
        through_the_command(registrations)(plan)
    except RerunError as exc:
        found = exc
    assert found is None, (found, getattr(found, "context", None))
    assert codes == {"decompose": 0}
