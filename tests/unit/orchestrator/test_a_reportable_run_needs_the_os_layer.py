"""The evaluation refuses a reportable run with shell sessions where the OS layer is absent.

The rule is the evaluation's, registered by the command's composition root; the
core imports nothing of the evaluation, so removing the evaluation removes the rule
and leaves the core whole.
"""

from __future__ import annotations

import ast
from pathlib import Path

import pytest
from orch_helpers import make_config

from physgate.evaluation.requirements import REQUIREMENTS, os_layer_for_reportable_runs
from physgate.orchestrator import requirements
from physgate.orchestrator.requirements import RunFacts
from physgate.orchestrator.run_config import HarnessState
from physgate.oslayer.probe import Absent, Present

SRC = Path(__file__).resolve().parents[3] / "src" / "physgate"
ABSENT = Absent(reason="Linux: bubblewrap (bwrap) is not on the session's search path")
PRESENT = Present(mechanism="seatbelt", claude_version="2.1.301")
CLEAN = HarnessState(commit="c" * 40, clean=True, uncommitted_sha256=None)


def _facts(*, reportable: bool, layer: Present | Absent, shell: bool = True) -> RunFacts:
    config = make_config(reportable=reportable, harness=CLEAN)
    return RunFacts(config=config, os_layer=layer, shell_sessions=shell)


def test_a_reportable_run_with_shell_sessions_and_no_layer_is_refused_with_the_reason() -> None:
    why = os_layer_for_reportable_runs(_facts(reportable=True, layer=ABSENT))
    assert why is not None and ABSENT.reason in why


@pytest.mark.parametrize(
    "facts",
    [
        _facts(reportable=True, layer=PRESENT),
        _facts(reportable=False, layer=ABSENT),
        _facts(reportable=True, layer=ABSENT, shell=False),
    ],
    ids=["layer-present", "not-reportable", "reviewers-only"],
)
def test_every_other_run_is_not_held_to_it(facts: RunFacts) -> None:
    assert os_layer_for_reportable_runs(facts) is None


def test_the_command_registers_the_evaluation_s_requirement() -> None:
    from physgate.cli import main

    with pytest.raises(SystemExit):
        main(["--help"])
    assert requirements.registered() == REQUIREMENTS


def test_with_nothing_registered_the_core_refuses_no_run(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(requirements, "_registered", ())
    assert requirements.refusals(_facts(reportable=True, layer=ABSENT)) == []


#: Core modules that already imported the evaluation before this rule existed: the UI
#: reads the observability layer's records, and the reviewers and the run command share
#: the instrument's names. Pinned, so that no new one appears unseen; the OS layer's
#: rule is not among them.
EARLIER = {
    "orchestrator/cli.py",
    "reviewers/places.py",
    "reviewers/rubric.py",
    "ui/readers.py",
    "ui/server.py",
}


def _imports(path: Path, prefix: str) -> bool:
    tree = ast.parse(path.read_text())
    for node in ast.walk(tree):
        names: list[str] = []
        if isinstance(node, ast.Import):
            names = [alias.name for alias in node.names]
        elif isinstance(node, ast.ImportFrom) and node.module:
            names = [node.module, *(f"{node.module}.{a.name}" for a in node.names)]
        if any(n == prefix or n.startswith(prefix + ".") for n in names):
            return True
    return False


def _core() -> list[Path]:
    """Everything but the evaluation itself and the composition root that wires it."""
    return [
        p
        for p in SRC.rglob("*.py")
        if p.relative_to(SRC).parts[0] != "evaluation" and p != SRC / "cli.py"
    ]


def test_only_the_composition_root_wires_the_evaluation_s_requirements() -> None:
    wired = [p for p in _core() if _imports(p, "physgate.evaluation.requirements")]
    assert wired == []
    assert _imports(SRC / "cli.py", "physgate.evaluation.requirements")


def test_no_core_module_imports_the_evaluation_beyond_those_that_already_did() -> None:
    found = {str(p.relative_to(SRC)) for p in _core() if _imports(p, "physgate.evaluation")}
    assert found <= EARLIER, sorted(found - EARLIER)
