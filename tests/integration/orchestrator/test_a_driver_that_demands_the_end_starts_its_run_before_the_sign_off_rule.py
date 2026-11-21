"""A driver that plans a control module and demands the run's end starts it before the rule table.

``real_domain_roles`` plans control and firmware and passes only a run that ends done with no
decision open. With the sign-off rule on, control owes a person's signature on its stability
margin, and a run that records decisions can never end done, while one that acts would wait for a
person the driver does not have. So the driver's run starts as one recorded before the rule table,
which owes none, as it did when it was written; and the setting is undone when the run is over, so
no later run in the process starts without the rule.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest
import real_domain_roles as base

from physgate.orchestrator import record


def test_the_run_starts_without_the_rule_and_the_rule_is_back_after_it(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    held = record.SIGN_OFF_RULES
    assert held is not None
    seen: list[str | None] = []

    def during(root: Path) -> dict[str, Any]:
        seen.append(record.SIGN_OFF_RULES)
        return {"ran": True}

    monkeypatch.setattr(base, "_run", during)
    assert base.one_run(tmp_path) == {"ran": True}
    assert seen == [None]
    assert held == record.SIGN_OFF_RULES


def test_the_rule_is_back_after_a_run_that_raises(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    held = record.SIGN_OFF_RULES

    def raising(root: Path) -> dict[str, Any]:
        raise RuntimeError

    monkeypatch.setattr(base, "_run", raising)
    with pytest.raises(RuntimeError):
        base.one_run(tmp_path)
    assert held == record.SIGN_OFF_RULES
