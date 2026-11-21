"""No CI step has its tests write a report or a log into the checkout while they run.

A run records the harness checkout it starts from (its commit and a digest of anything not
committed, untracked files included) and refuses to resume under another. The suite measures the
checkout once, at its start, and a row that starts a run in the test process and resumes it in a
process of its own is judged against that measurement. So a file a test writes into the checkout
while the suite runs (a report, a log a step's ``tee`` keeps) is an untracked file the resume
finds and the start did not: "the harness checkout differs from the one this run recorded",
depending only on which rows ran before. Reports and logs go to the runner's temporary directory.
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest

WORKFLOWS = sorted((Path(__file__).resolve().parents[2] / ".github" / "workflows").glob("*.yml"))
#: An environment variable naming where a test writes its report or its log.
_WRITTEN = re.compile(r"^\s*(PHYSGATE_\w+_(?:REPORT|LOG)):\s*(\S.*?)\s*$")
#: The file a step's ``tee`` writes.
_TEE = re.compile(r"\btee\s+(?:-a\s+)?\"?([^\s\"|>]+)")


def _outside_the_checkout(value: str) -> bool:
    """Whether ``value`` names a place outside the checkout: absolute, and not the workspace."""
    if "github.workspace" in value or "GITHUB_WORKSPACE" in value:
        return False
    return value.startswith(("/", "$RUNNER_TEMP", "${RUNNER_TEMP}", "${{ runner.temp }}"))


def test_the_workflows_are_found() -> None:
    names = {w.name for w in WORKFLOWS}
    assert {"check.yml", "hooks-bypass.yml"} <= names, names


@pytest.mark.parametrize("workflow", WORKFLOWS, ids=lambda w: w.name)
def test_every_report_and_log_a_test_writes_lies_outside_the_checkout(workflow: Path) -> None:
    lines = workflow.read_text().splitlines()
    for number, line in enumerate(lines, 1):
        written = _WRITTEN.match(line)
        if written is not None:
            name, value = written.groups()
            assert _outside_the_checkout(value), f"{workflow.name}:{number}: {name} is {value}"


@pytest.mark.parametrize("workflow", WORKFLOWS, ids=lambda w: w.name)
def test_every_file_a_step_tees_lies_outside_the_checkout(workflow: Path) -> None:
    for number, line in enumerate(workflow.read_text().splitlines(), 1):
        for target in _TEE.findall(line):
            assert _outside_the_checkout(target), f"{workflow.name}:{number}: tee {target}"
