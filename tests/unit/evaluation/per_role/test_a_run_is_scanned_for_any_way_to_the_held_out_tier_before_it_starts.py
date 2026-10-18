from __future__ import annotations

import hashlib
from pathlib import Path

import pytest

from physgate.evaluation.per_role.authoring import sha256sums
from physgate.evaluation.per_role.heldout import scan
from physgate.oslayer.policy import sandbox_policy as real_policy

#: The digest of an empty tier, as the run records it.
EMPTY = hashlib.sha256(b"\n").hexdigest()


def _layout(tmp_path: Path) -> tuple[Path, dict[str, Path], Path]:
    base = tmp_path.resolve()
    root = base / "private" / "heldout"
    root.mkdir(parents=True)
    (root / "SHA256SUMS").write_text(sha256sums(root))
    places = {"run directory": base / "runs" / "r1", "target": base / "target"}
    for place in places.values():
        place.mkdir(parents=True)
    return root, places, base / "scan"


def test_a_run_with_the_root_named_and_nothing_near_it_has_no_problem(tmp_path: Path) -> None:
    root, places, scratch = _layout(tmp_path)
    assert (
        scan(
            root,
            run_held_out=(str(root),),
            run_digests={str(root): EMPTY},
            run_canaries=(),
            places=places,
            scratch=scratch,
        )
        == []
    )


def test_a_run_that_does_not_name_the_root_is_refused(tmp_path: Path) -> None:
    root, places, scratch = _layout(tmp_path)
    assert scan(
        root,
        run_held_out=(),
        run_digests={str(root): EMPTY},
        run_canaries=(),
        places=places,
        scratch=scratch,
    ) == ["the run's parameters do not name the held-out root"]


@pytest.mark.parametrize(
    ("where", "relation"),
    [("private/heldout", "is"), ("private/heldout/work", "lies inside"), ("private", "contains")],
)
def test_a_place_at_inside_or_around_the_root_is_refused(
    tmp_path: Path, where: str, relation: str
) -> None:
    root, places, scratch = _layout(tmp_path)
    place = tmp_path.resolve() / where
    place.mkdir(parents=True, exist_ok=True)
    problems = scan(
        root,
        run_held_out=(str(root),),
        run_digests={str(root): EMPTY},
        run_canaries=(),
        places={**places, "review root": place},
        scratch=scratch,
    )
    assert f"the review root {relation} the held-out root" in problems


def test_a_place_reached_through_a_link_into_the_root_is_refused(tmp_path: Path) -> None:
    root, places, scratch = _layout(tmp_path)
    alias = tmp_path.resolve() / "innocent"
    alias.symlink_to(root)
    problems = scan(
        root,
        run_held_out=(str(root),),
        run_digests={str(root): EMPTY},
        run_canaries=(),
        places={**places, "raw work area": alias},
        scratch=scratch,
    )
    assert "the raw work area is the held-out root" in problems


def test_a_link_inside_a_place_that_resolves_into_the_root_is_refused(tmp_path: Path) -> None:
    root, places, scratch = _layout(tmp_path)
    (root / "task.json").write_text("{}")
    (places["target"] / "docs").mkdir()
    (places["target"] / "docs" / "notes.json").symlink_to(root / "task.json")
    problems = scan(
        root,
        run_held_out=(str(root),),
        run_digests={str(root): EMPTY},
        run_canaries=(),
        places=places,
        scratch=scratch,
    )
    assert any(p.startswith("the target holds a link into the tier") for p in problems)


def test_a_root_given_through_a_link_is_refused(tmp_path: Path) -> None:
    root, places, scratch = _layout(tmp_path)
    alias = tmp_path.resolve() / "alias"
    alias.symlink_to(root)
    problems = scan(
        alias,
        run_held_out=(str(alias),),
        run_digests={str(root): EMPTY},
        run_canaries=(),
        places=places,
        scratch=scratch,
    )
    assert "the held-out root is not given as its real, absolute path" in problems


def test_a_profile_whose_sessions_would_not_withhold_the_root_is_found(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    root, places, scratch = _layout(tmp_path)

    def leaky(config, **kwargs):  # type: ignore[no-untyped-def]
        policy = real_policy(config, **kwargs)
        policy.settings["sandbox"]["filesystem"]["denyRead"] = []
        return policy

    monkeypatch.setattr("physgate.evaluation.per_role.heldout.sandbox_policy", leaky)
    problems = scan(
        root,
        run_held_out=(str(root),),
        run_digests={str(root): EMPTY},
        run_canaries=(),
        places=places,
        scratch=scratch,
    )
    assert "a baseline session's OS layer would not denyRead the root" in problems
    assert "a role session's OS layer would not denyRead the root" in problems
