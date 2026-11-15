"""A whole-run role, answer form and scorer are one more value of each, handled as a role is.

``whole_run`` is a role like ``control`` and ``firmware`` as far as the store, the canaries,
the withheld roots and the baseline's scope go: nothing a role is refused is handed to it by
default. It has no author brief and no requirements source yet, so a tier set cannot be
written for it and a manifest naming it is stale.
"""

from __future__ import annotations

import json
import os
from pathlib import Path
from types import SimpleNamespace
from typing import Any, get_args

import pytest

from physgate.evaluation.baseline.runner import BaselineError, _require_withheld
from physgate.evaluation.tierset_cli import status
from physgate.evaluation.tiers import store as store_module
from physgate.evaluation.tiers.authoring import AuthoringError, author_brief
from physgate.evaluation.tiers.canaries import store_canaries
from physgate.evaluation.tiers.manifest import TierSet, requirements_source, staleness
from physgate.evaluation.tiers.store import is_visible_tier, role_roots
from physgate.evaluation.tiers.task import AnswerForm, Role, ScorerId

VERSION = "a" * 64
CANARY = "b" * 32
WHOLE: Any = "whole_run"


def _version(store: Path, role: str, canary: str | None = None) -> Path:
    root = store / role
    for part in ("withheld", "work"):
        (root / part).mkdir(parents=True, exist_ok=True)
    for tier in ("visible", "validation", "held_out"):
        (root / VERSION / tier).mkdir(parents=True, exist_ok=True)
    if canary is not None:
        tier = root / VERSION / "held_out"
        (tier / "t-1").mkdir()
        (tier / "t-1" / "task.json").write_text("{}")
        (tier / "canaries.json").write_text(json.dumps([canary]))
    return root


def test_the_three_literals_are_values_of_their_types() -> None:
    assert "whole_run" in get_args(Role)
    assert "whole_run" in get_args(AnswerForm)
    assert "whole_design" in get_args(ScorerId)
    assert get_args(Role)[:2] == ("control", "firmware")


def test_a_whole_run_version_s_visible_tier_is_known_by_its_place(tmp_path: Path) -> None:
    store = tmp_path.resolve() / "store"
    assert is_visible_tier(store / "whole_run" / VERSION / "visible")
    assert not is_visible_tier(store / "whole_run" / VERSION / "held_out")


@pytest.mark.parametrize("spelt", ["whole_run", "Whole_Run", "WHOLE_RUN"])
def test_a_run_naming_a_whole_run_root_names_that_role_in_any_case(
    tmp_path: Path, spelt: str
) -> None:
    base = tmp_path.resolve()
    _version(base / "store", "whole_run")
    for entry in (
        base / "store" / spelt / VERSION / "held_out",
        base / "store" / spelt / "withheld",
    ):
        assert role_roots((str(entry),)) == [(base / "store", "whole_run")]
    assert store_module._role(spelt) == "whole_run"


def test_a_store_that_cannot_be_listed_is_taken_as_holding_every_role_s_root(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    store = tmp_path.resolve() / "store"
    store.mkdir()
    real = os.listdir

    def listing(path: Any = ".") -> list[str]:  # noqa: ANN401
        if str(path) == str(store):
            raise PermissionError(13, "denied", str(store))
        return real(path)

    monkeypatch.setattr(store_module.os, "listdir", listing)
    assert {role for _, role in role_roots((str(store),))} == set(get_args(Role))
    assert "whole_run" in {role for _, role in role_roots((str(store),))}


def test_a_whole_run_root_s_canaries_are_looked_for_with_every_other_role_s(
    tmp_path: Path,
) -> None:
    store = tmp_path.resolve() / "store"
    _version(store, "whole_run", CANARY)
    assert CANARY in store_canaries(store)


def test_the_status_command_reads_a_whole_run_root_as_it_reads_every_role_s(
    tmp_path: Path,
) -> None:
    store = tmp_path.resolve() / "store"
    _version(store, "whole_run")
    rows = status(store)["versions"]
    assert [(r["role"], r["version"]) for r in rows] == [("whole_run", VERSION)]
    assert rows[0]["state"] == "refused"


def _config(*entries: Path) -> Any:  # noqa: ANN401
    return SimpleNamespace(held_out=tuple(str(e) for e in entries), held_out_canaries=())


def _control_alone(store: Path) -> list[Path]:
    root = store / "control"
    return [
        root / "withheld",
        root / "work",
        root / VERSION / "validation",
        root / VERSION / "held_out",
    ]


def test_a_run_withholding_a_control_root_alone_is_refused_when_a_whole_run_root_is_there(
    tmp_path: Path,
) -> None:
    store = tmp_path.resolve() / "store"
    _version(store, "control")
    _version(store, "whole_run")
    with pytest.raises(BaselineError, match="does not withhold the store as every run on it must"):
        _require_withheld(store, "control", _config(*_control_alone(store)), set(), {})


def test_a_run_withholding_every_root_in_the_store_passes(tmp_path: Path) -> None:
    store = tmp_path.resolve() / "store"
    _version(store, "control")
    _version(store, "whole_run")
    whole = store / "whole_run"
    held = [
        *_control_alone(store),
        whole / "withheld",
        whole / "work",
        whole / VERSION / "validation",
        whole / VERSION / "held_out",
    ]
    _require_withheld(store, "control", _config(*held), set(), {})


def test_a_store_with_no_whole_run_root_asks_nothing_for_it(tmp_path: Path) -> None:
    store = tmp_path.resolve() / "store"
    _version(store, "control")
    _require_withheld(store, "control", _config(*_control_alone(store)), set(), {})


def test_no_author_brief_or_requirements_source_exists_for_a_whole_run_yet() -> None:
    with pytest.raises(AuthoringError, match="no scorer exists yet"):
        author_brief(WHOLE)
    with pytest.raises(AuthoringError, match="no scorer exists yet"):
        requirements_source(WHOLE)


def test_a_manifest_naming_a_whole_run_is_stale_for_want_of_a_current_brief() -> None:
    manifest = TierSet.model_construct(role=WHOLE)
    found = staleness(manifest)
    assert found.because == ("no_current_brief",)
    assert found.tiers == ("visible", "validation", "held_out")
