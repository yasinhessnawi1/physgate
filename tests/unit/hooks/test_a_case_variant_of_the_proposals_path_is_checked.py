"""A proposal written under a case variant of the proposals path is checked like any other.

On a volume that ignores case (macOS's default), ``.PHYSGATE/proposals/x.json`` is
the proposal ``.physgate/proposals/x.json``, and the orchestrator applies it. The
hook folds case when it decides whether a path is a proposal, so a variant is
checked by the file tools' rules and refused to the shell, on every volume.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from hook_helpers import bash, event, make_store, node, write_config

from physgate.hooks import graph
from physgate.hooks.config import HookInput, SessionConfig
from physgate.state.protocol import REJECT_MISSING_UNIT

VARIANTS = (".PHYSGATE/proposals", ".physgate/PROPOSALS", ".Physgate/Proposals")


@pytest.fixture
def config(tmp_path: Path) -> SessionConfig:
    make_store(tmp_path / "store", node("electrical.motor", "electrical"))
    _, _, cfg = write_config(tmp_path, role="electrical")
    return cfg


@pytest.mark.parametrize("variant", VARIANTS)
def test_a_write_under_a_case_variant_is_checked_as_a_proposal(
    config: SessionConfig, variant: str
) -> None:
    bare = {**node("electrical.driver"), "quantities": {"stall_current": 2.4}}
    target = Path(config.worktree) / variant / "electrical.driver.json"
    hook_input = HookInput.model_validate(
        event(
            tool_name="Write",
            cwd=config.worktree,
            tool_input={"file_path": str(target), "content": json.dumps(bare)},
        )
    )
    decision = graph.pre_tool_use(hook_input, config)
    assert not decision.allow and REJECT_MISSING_UNIT in decision.reason


@pytest.mark.parametrize("variant", VARIANTS)
def test_a_command_writing_under_a_case_variant_is_refused(
    config: SessionConfig, variant: str
) -> None:
    hook_input = HookInput.model_validate(
        bash(f"echo '{{}}' > {variant}/electrical.driver.json", cwd=config.worktree)
    )
    decision = graph.pre_tool_use(hook_input, config)
    assert not decision.allow and decision.reason == graph.SHELL_WRITE
