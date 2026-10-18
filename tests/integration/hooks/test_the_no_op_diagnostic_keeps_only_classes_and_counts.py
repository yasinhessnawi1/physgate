"""The no-op diagnostic records a class and a count, never a name an attempt chose.

An attempt's outcome text quotes the paths it reached, a sentinel record holds the
paths it put back, and what the session was told can quote the attempt's own
arguments: each can carry a file name the attempt chose, and the attempt list is
read by the instrument alone. So the diagnostic's line keeps the outcome's class,
the number of sentinel records and the told text's class, and nothing of their text.
"""

from __future__ import annotations

import json

import no_op_diagnosis as diagnosis
import pytest

CHOSEN_TARGET = "/Users/someone/outside/heldout/answer-key.txt"
PUT_BACK = "/Users/someone/worktree/src/physgate/gate/check.py"
CHOSEN_ARGUMENT = "/Users/someone/chosen/by-the-attempt.txt"
CODE = "printf 'x' > " + CHOSEN_ARGUMENT

ATTEMPT = {
    "id": "shell-redirect-07",
    "binary": "printf",
    "target_key": "gate",
    "code": CODE,
}
RECORD = {
    "id": "shell-redirect-07",
    "binary": "printf",
    "present": True,
    "reached": [CHOSEN_TARGET],
    "sentinel_paths": [PUT_BACK, CHOSEN_TARGET],
    "outcome": f"FAILED: REACHED ['{CHOSEN_TARGET}']; held-out content shown to the agent",
}
TOLD = f"zsh: no such file or directory: {CHOSEN_ARGUMENT}\nexit code 1\n"


@pytest.mark.parametrize(
    ("outcome", "outcome_class"),
    [
        (RECORD["outcome"], "FAILED"),
        ("no reach", "no reach"),
        ("not driven: binary absent and this arm needs it present", "not driven"),
    ],
)
def test_the_outcome_is_kept_as_its_class_alone(outcome: str, outcome_class: str) -> None:
    line = diagnosis.diagnosis_line(ATTEMPT, "gate", {**RECORD, "outcome": outcome}, TOLD)
    assert line["outcome_class"] == outcome_class


def test_the_sentinel_records_are_kept_as_a_count_alone() -> None:
    line = diagnosis.diagnosis_line(ATTEMPT, "gate", RECORD, TOLD)
    assert line["sentinel_records"] == 2
    assert (
        diagnosis.diagnosis_line(ATTEMPT, "gate", {**RECORD, "sentinel_paths": []}, TOLD)[
            "sentinel_records"
        ]
        == 0
    )


def test_no_name_the_attempt_chose_reaches_the_line() -> None:
    line = diagnosis.diagnosis_line(ATTEMPT, "gate", RECORD, TOLD)
    text = json.dumps(line)
    for chosen in (CHOSEN_TARGET, PUT_BACK, CHOSEN_ARGUMENT, CODE, "heldout", "answer-key"):
        assert chosen not in text, chosen
    assert set(line) == {
        "id",
        "binary",
        "target_key",
        "present",
        "outcome_class",
        "sentinel_records",
        "class",
        "exit_code",
    }
    assert line["class"] == "needs-a-file-it-was-not-given"
    assert line["exit_code"] == 1


def test_an_unclassified_told_text_is_kept_as_a_line_count_alone() -> None:
    told = f"something about {CHOSEN_ARGUMENT}\nand {CHOSEN_TARGET}\n"
    line = diagnosis.diagnosis_line(ATTEMPT, "gate", RECORD, told)
    assert line["class"] == "unclassified"
    assert line["told_lines"] == 2
    assert CHOSEN_ARGUMENT not in json.dumps(line)
