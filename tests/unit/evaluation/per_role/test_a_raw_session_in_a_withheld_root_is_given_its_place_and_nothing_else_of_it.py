"""A raw session working inside a withheld root is installed with that root withheld whole.

A protected trial's session works in a place of its own inside the store's work root, which
every run withholds. The installer is given the run's held-out roots that hold that place, whole,
and the place as the session's own (``--withheld-whole``, ``--own-place``): what is made beside
the place after the install is withheld by that rule, not by a list taken at the install. The
list of what lay beside the way down stays as a second measure. A session whose place lies in
no withheld root is installed with neither option.
"""

from __future__ import annotations

import dataclasses
from pathlib import Path

import pytest
from test_the_raw_arm_s_credential_is_handled_as_a_role_session_s import (
    _script,
    _setup,
    capture_installer,
)

from physgate.evaluation.per_role.arms import raw


def _given(argv: list[str], option: str) -> list[str]:
    return [argv[i + 1] for i, word in enumerate(argv) if word == option]


def _trial(tmp_path: Path) -> tuple[Path, Path, Path]:
    store = tmp_path.resolve() / "store"
    place = store / "control" / "work" / "baseline-r-0001-1" / "place"
    (place / "worktree").mkdir(parents=True)
    (place.parent / "harness").mkdir()
    (place / "session").mkdir()
    elsewhere = tmp_path.resolve() / "elsewhere"
    elsewhere.mkdir()
    return store, place, elsewhere


def test_a_protected_trial_s_session_gets_its_root_whole_but_its_own_place(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    store, place, elsewhere = _trial(tmp_path)
    setup = dataclasses.replace(
        _setup(tmp_path, _script(tmp_path / "claude", "true\n")),
        held_out=(str(store), str(elsewhere)),
        held_out_carved=str(place),
    )
    seen = capture_installer(monkeypatch)
    raw._install(setup, place / "worktree", place / "session", None)
    (argv,) = [a for a in seen if a[1:3] == ["hooks", "install"]]
    # The root that holds the place, whole; never the root that does not hold it.
    assert _given(argv, "--withheld-whole") == [str(store)], argv
    assert _given(argv, "--own-place") == [str(place)], argv
    # The list stays as the second measure: what lay beside the way down, and the other root.
    held = _given(argv, "--held-out")
    assert str(place.parent / "harness") in held and str(elsewhere) in held, held
    assert str(store) not in held, held


def test_a_session_whose_place_lies_in_no_withheld_root_gets_neither_option(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _store, place, elsewhere = _trial(tmp_path)
    setup = dataclasses.replace(
        _setup(tmp_path, _script(tmp_path / "claude", "true\n")), held_out=(str(elsewhere),)
    )
    seen = capture_installer(monkeypatch)
    raw._install(setup, place / "worktree", place / "session", None)
    (argv,) = [a for a in seen if a[1:3] == ["hooks", "install"]]
    assert "--withheld-whole" not in argv and "--own-place" not in argv, argv


def test_a_root_given_whole_by_the_caller_is_passed_whole_with_the_place(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """As the blind check's session is given the whole store but its own work."""
    store, place, _elsewhere = _trial(tmp_path)
    assert "withheld_whole" in {f.name for f in dataclasses.fields(raw.RawSetup)}, (
        "a raw session cannot be given a root withheld whole but for its own place"
    )
    setup = dataclasses.replace(
        _setup(tmp_path, _script(tmp_path / "claude", "true\n")),
        withheld_whole=(str(store),),
    )
    seen = capture_installer(monkeypatch)
    raw._install(setup, place / "worktree", place / "session", None)
    (argv,) = [a for a in seen if a[1:3] == ["hooks", "install"]]
    assert _given(argv, "--withheld-whole") == [str(store)], argv
    assert _given(argv, "--own-place") == [str(place)], argv
