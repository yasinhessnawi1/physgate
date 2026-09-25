"""The session configuration is validated whole, and only the spawner's bytes are accepted.

The hooks read it with the standard-library validator; the schema refuses the same
files, which the equivalence test proves across thousands of variants.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest
from hook_helpers import config_dict, write_config
from pydantic import ValidationError

from physgate.hooks.config import SessionConfig, digest
from physgate.hooks.exceptions import SessionConfigMismatchError
from physgate.hooks.lean import LeanValidationError, load_config


def test_the_spawners_file_loads(tmp_path: Path) -> None:
    path, sha, expected = write_config(tmp_path)
    loaded = load_config(str(path), sha)
    assert (loaded.profile, loaded.role, loaded.worktree, loaded.token_ceiling) == (
        expected.profile,
        expected.role,
        expected.worktree,
        expected.token_ceiling,
    )
    assert [r.path for r in loaded.protected_roots] == [r.path for r in expected.protected_roots]


def test_one_changed_byte_is_refused(tmp_path: Path) -> None:
    path, sha, _ = write_config(tmp_path)
    data = bytearray(path.read_bytes())
    data[-2] = ord(" ")
    path.write_bytes(bytes(data))
    with pytest.raises(SessionConfigMismatchError):
        load_config(str(path), sha)


@pytest.mark.parametrize(
    ("override", "why"),
    [
        ({"role": None}, "a role session without a role"),
        ({"watchdog_seconds": 25}, "a watchdog within the margin of Claude Code's timeout"),
        ({"worktree": "relative/path"}, "a relative path"),
        ({"token_ceiling": 0}, "a ceiling of zero"),
        ({"profile": "developer"}, "an unknown profile"),
        ({"surprise": 1}, "an unknown field"),
        ({"token_ceiling": "1000"}, "a number written as a string"),
    ],
)
def test_an_incoherent_configuration_is_refused(
    tmp_path: Path, override: dict[str, Any], why: str
) -> None:
    data = json.dumps(config_dict(tmp_path, **override)).encode()
    with pytest.raises(ValidationError):
        SessionConfig.model_validate_json(data)
    path = tmp_path / "c.json"
    path.write_bytes(data)
    with pytest.raises(LeanValidationError):
        load_config(str(path), digest(data))
