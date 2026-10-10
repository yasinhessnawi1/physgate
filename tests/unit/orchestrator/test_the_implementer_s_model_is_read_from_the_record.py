"""The review stage reads the implementer's model from the run's record, not from its caller.

ARCH-060's acceptance test: dispatch refuses a reviewer on the implementer's model
string. The string compared is the one the run recorded: the subtask's role from
its ledger line, read back from disk, and that role's model from the run's
configuration file, held to the digest on the log's first line. A loop handed a
configuration object that names another implementer still refuses.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from loop_fakes import FakeReviewer, Rig, plan
from orch_helpers import make_config

from physgate.orchestrator.events import Merged, ReviewRan, read_events
from physgate.orchestrator.exceptions import (
    MergePreconditionError,
    ModelSeparationError,
    RunConfigError,
)
from physgate.orchestrator.replay import recorded_implementer
from physgate.orchestrator.run_config import ModelStrings

#: The implementer the record names (``make_config``'s electrical role).
RECORDED = "claude-sonnet-5"
OTHER = "claude-haiku-4-5-20251001"


def test_a_reviewer_on_the_recorded_implementer_s_string_is_refused_whatever_the_caller_holds(
    tmp_path: Path,
) -> None:
    rig = Rig(tmp_path)
    loop = rig.open()
    loop.start(plan("s1"))
    # The caller now holds a configuration naming another implementer, and the
    # reviewer has moved onto the string the record names.
    loop.config = make_config(
        models=ModelStrings(
            decomposition=RECORDED,
            roles={"electrical": OTHER},
            reviewers={"electrical": RECORDED},
        )
    )
    rig.reviewer.model = RECORDED
    with pytest.raises(ModelSeparationError) as raised:
        loop.run()
    loop.close()
    assert raised.value.context == {"implementer": RECORDED, "reviewer": RECORDED}
    assert rig.reviewer.seen == []
    assert not [e for e in read_events(tmp_path / "events.jsonl") if isinstance(e, ReviewRan)]


def test_a_reviewer_on_a_different_string_proceeds(tmp_path: Path) -> None:
    rig = Rig(tmp_path, reviewer=FakeReviewer(model="claude-opus-5-5"))
    loop = rig.open()
    loop.start(plan("s1"))
    step = loop.run()
    loop.close()
    assert step.kind == "done"
    assert len(rig.reviewer.seen) == 1
    assert [e for e in read_events(tmp_path / "events.jsonl") if isinstance(e, Merged)]


def _started(tmp_path: Path) -> Path:
    rig = Rig(tmp_path)
    loop = rig.open()
    loop.start(plan("s1"))
    loop.close()
    return tmp_path


def test_the_recorded_implementer_is_the_role_s_model_in_the_record(tmp_path: Path) -> None:
    assert recorded_implementer(_started(tmp_path), "s1") == RECORDED


def test_a_subtask_with_no_ledger_line_has_no_recorded_implementer(tmp_path: Path) -> None:
    with pytest.raises(MergePreconditionError, match="no ledger line"):
        recorded_implementer(_started(tmp_path), "s9")


def test_a_configuration_file_changed_after_the_start_is_refused(tmp_path: Path) -> None:
    run_dir = _started(tmp_path)
    recorded = json.loads((run_dir / "run.json").read_text())
    recorded["models"]["roles"]["electrical"] = OTHER
    (run_dir / "run.json").write_text(json.dumps(recorded))
    with pytest.raises(RunConfigError, match="first event line"):
        recorded_implementer(run_dir, "s1")


def test_a_log_whose_first_line_is_not_the_start_is_refused(tmp_path: Path) -> None:
    run_dir = _started(tmp_path)
    lines = (run_dir / "events.jsonl").read_bytes().splitlines(keepends=True)
    (run_dir / "events.jsonl").write_bytes(b"".join(lines[1:]))
    with pytest.raises(RunConfigError, match="first event line"):
        recorded_implementer(run_dir, "s1")
