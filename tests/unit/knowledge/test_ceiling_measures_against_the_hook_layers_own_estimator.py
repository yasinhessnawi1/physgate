"""``ceiling.fits``/``breach_reason`` (ARCH-023): the same call made at each real tool call.

These do not reimplement the estimator — they call
``physgate.hooks.token_ceiling.measure`` directly through a real
``SessionConfig``, so the two can never drift apart. That equivalence is
asserted here, not just assumed.
"""

from __future__ import annotations

from pathlib import Path

from physgate.hooks import token_ceiling
from physgate.hooks.config import Installation, SessionConfig
from physgate.knowledge import ceiling


def _real_config(paths: list[Path], limit: int) -> SessionConfig:
    """The hook layer's own shape, built the same way `ceiling.py`'s shim builds it."""
    return SessionConfig(
        profile="role",
        role="control",
        worktree="/x",
        own_branch=None,
        store_root=None,
        state_dir="/x-state",
        protected_roots=(),
        experiments=(),
        held_out=(),
        answer_keys=(),
        read_roots=(),
        review_material=(),
        required_reading=(),
        always_loaded=tuple(str(p) for p in paths),
        token_ceiling=limit,
        tools_allowed=(),
        installation=Installation(
            interpreter="/usr/bin/python3",
            package_dir="/usr/lib",
            environment_root="/usr",
            base_prefix="/usr",
        ),
        watchdog_seconds=5,
        hook_timeout_seconds=30,
    )


def test_a_set_exactly_at_the_ceiling_fits(tmp_path: Path) -> None:
    standards = tmp_path / "standards.md"
    standards.write_bytes(b"x" * 600)
    skill = tmp_path / "skill.md"
    skill.write_bytes(b"x" * 400)
    assert ceiling.fits([standards, skill], 1000)
    assert ceiling.breach_reason([standards, skill], 1000) is None


def test_one_byte_over_does_not_fit_and_names_the_largest_file_first(tmp_path: Path) -> None:
    standards = tmp_path / "standards.md"
    standards.write_bytes(b"x" * 601)
    skill = tmp_path / "skill.md"
    skill.write_bytes(b"x" * 400)
    assert not ceiling.fits([standards, skill], 1000)
    reason = ceiling.breach_reason([standards, skill], 1000)
    assert reason is not None
    assert reason.index("standards.md: at most 601") < reason.index("skill.md: at most 400")


def test_ceiling_py_agrees_with_h0s_own_measure_on_every_case(tmp_path: Path) -> None:
    standards = tmp_path / "standards.md"
    standards.write_bytes(b"y" * 250)
    for limit in (100, 249, 250, 251, 1000):
        mine = ceiling.fits([standards], limit)
        theirs = token_ceiling.measure(_real_config([standards], limit)).allow
        assert mine == theirs, limit


def test_a_missing_always_loaded_file_refuses_rather_than_measuring_zero(tmp_path: Path) -> None:
    assert not ceiling.fits([tmp_path / "gone.md"], 1000)
    reason = ceiling.breach_reason([tmp_path / "gone.md"], 1000)
    assert reason is not None and "cannot be measured" in reason
