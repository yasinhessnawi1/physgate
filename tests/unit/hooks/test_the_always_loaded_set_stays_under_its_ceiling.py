"""A ceiling breach names the file and refuses every tool; under the ceiling, nothing happens.

The count is the file's size in bytes, which is an upper bound on its tokens
for a tokenizer that works on bytes. The tests cross the ceiling in that unit.
"""

from __future__ import annotations

from pathlib import Path

import pytest
from hook_helpers import bash, config_dict, event, write_config

from physgate.hooks import token_ceiling
from physgate.hooks.config import HookInput, SessionConfig

START = HookInput.model_validate(event("SessionStart"))
BASH = HookInput.model_validate(bash("ls"))
READ = HookInput.model_validate(event(tool_name="Read", tool_input={"file_path": "/x"}))


def _config(tmp: Path, sizes: dict[str, int], ceiling: int) -> SessionConfig:
    paths = []
    for name, size in sizes.items():
        path = tmp / name
        path.write_bytes(b"x" * size)
        paths.append(str(path))
    _, _, config = write_config(tmp, always_loaded=paths, token_ceiling=ceiling)
    return config


def test_exactly_at_the_ceiling_passes(tmp_path: Path) -> None:
    config = _config(tmp_path, {"standards.md": 600, "skill.md": 400}, ceiling=1000)
    for hook_input in (START, BASH, READ):
        assert token_ceiling.measure(config).allow
        assert token_ceiling.pre_tool_use(hook_input, config).allow


def test_one_byte_over_refuses_every_tool_and_names_the_files_largest_first(
    tmp_path: Path,
) -> None:
    config = _config(tmp_path, {"standards.md": 601, "skill.md": 400}, ceiling=1000)
    for hook_input in (BASH, READ):
        decision = token_ceiling.pre_tool_use(hook_input, config)
        assert not decision.allow
    reason = token_ceiling.pre_tool_use(BASH, config).reason
    assert "at most 1001 tokens" in reason and "ceiling of 1000" in reason
    assert reason.index("standards.md: at most 601") < reason.index("skill.md: at most 400")
    assert "not a reason to raise the ceiling" in reason


def test_the_session_start_reports_the_same_breach(tmp_path: Path) -> None:
    config = _config(tmp_path, {"standards.md": 2000}, ceiling=1000)
    decision = token_ceiling.session_start(START, config)
    assert not decision.allow
    assert "standards.md" in decision.reason


def test_a_breach_introduced_after_the_start_is_caught_at_the_next_call(tmp_path: Path) -> None:
    config = _config(tmp_path, {"standards.md": 100}, ceiling=1000)
    assert token_ceiling.session_start(START, config).allow
    (tmp_path / "standards.md").write_bytes(b"x" * 1001)
    assert not token_ceiling.pre_tool_use(BASH, config).allow


def test_the_bound_counts_bytes_not_characters(tmp_path: Path) -> None:
    path = tmp_path / "unicode.md"
    path.write_text("æøå" * 100, encoding="utf-8")  # 300 characters, 600 bytes
    _, _, config = write_config(tmp_path, always_loaded=[str(path)], token_ceiling=599)
    assert not token_ceiling.measure(config).allow


def test_an_always_loaded_file_that_is_missing_refuses_every_tool(tmp_path: Path) -> None:
    _, _, config = write_config(
        tmp_path, always_loaded=[str(tmp_path / "gone.md")], token_ceiling=1000
    )
    decision = token_ceiling.pre_tool_use(BASH, config)
    assert not decision.allow
    assert "gone.md" in decision.reason and "cannot be measured" in decision.reason


@pytest.mark.parametrize("ceiling", [None, 0, -5])
def test_the_ceiling_has_no_default_and_must_be_positive(
    tmp_path: Path, ceiling: int | None
) -> None:
    from pydantic import ValidationError

    with pytest.raises(ValidationError):
        write_config(tmp_path, token_ceiling=ceiling)


def test_a_configuration_without_a_ceiling_is_refused(tmp_path: Path) -> None:
    import json

    from pydantic import ValidationError

    from physgate.hooks.config import SessionConfig

    data = config_dict(tmp_path)
    del data["token_ceiling"]
    with pytest.raises(ValidationError, match="token_ceiling"):
        SessionConfig.model_validate_json(json.dumps(data))
