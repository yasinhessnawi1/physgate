"""The runner drives R-HK-01's frozen list and refuses any other.

This is the change that is a non-change: the optional extension-target list the
pre-registration leaves out cannot enter, because a list whose checksum, length
or target set differs from the frozen one is refused before a single attempt is
driven.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from physgate import bypass_corpus as bc

FROZEN = Path(__file__).resolve().parents[3] / "experiments" / "R-HK-01" / "attempts.jsonl"


def test_the_frozen_file_loads_and_is_exactly_the_registered_corpus() -> None:
    attempts = bc.load_attempts(FROZEN)
    assert len(attempts) == bc.ATTEMPT_TOTAL == 755
    assert {a["target_key"] for a in attempts} == bc.TARGET_KEYS


def _write(tmp_path: Path, attempts: list[dict[str, object]]) -> Path:
    path = tmp_path / "attempts.jsonl"
    path.write_text("# header\n" + "".join(json.dumps(a, sort_keys=True) + "\n" for a in attempts))
    return path


def test_a_reworded_attempt_is_refused_by_the_checksum(tmp_path: Path) -> None:
    attempts = bc.load_attempts(FROZEN)
    attempts[0]["code"] = attempts[0]["code"] + " # reworded"
    with pytest.raises(bc.CorpusError, match="checksum"):
        bc.load_attempts(_write(tmp_path, attempts))


def test_a_dropped_attempt_is_refused(tmp_path: Path) -> None:
    attempts = bc.load_attempts(FROZEN)[:-1]
    with pytest.raises(bc.CorpusError):
        bc.load_attempts(_write(tmp_path, attempts))


def test_the_frozen_list_introduces_no_new_target() -> None:
    assert bc.new_target_keys(bc.load_attempts(FROZEN)) == set()


def test_an_extension_target_is_named_a_new_target() -> None:
    attempts = bc.load_attempts(FROZEN)
    extended = dict(attempts[0])
    extended["target_key"] = "git_internals"
    assert bc.new_target_keys([*attempts, extended]) == {"git_internals"}
