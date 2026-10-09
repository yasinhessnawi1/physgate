"""The allowlist is the only source of readable roots; the held-out tier is refused in every form.

Each test plants one form against one rule. The resolver resolves first, then checks the
allowlist, then the refused set; the symlink tests are the ones that tell "resolved first"
from "checked first", and each says so.
"""

from __future__ import annotations

import os
from pathlib import Path

import pytest

from physgate.ui.exceptions import PathRefusedError, StartupRefusedError
from physgate.ui.paths import Allowlist


@pytest.fixture
def layout(tmp_path: Path) -> dict[str, Path]:
    """A root holding a run, a held-out tier beside it, and a directory outside both."""
    root = tmp_path / "runs"
    (root / "run-1").mkdir(parents=True)
    (root / "run-1" / "events.jsonl").write_text("{}\n")
    held = tmp_path / "held"
    held.mkdir()
    (held / "scenario.json").write_text("{}\n")
    outside = tmp_path / "outside"
    outside.mkdir()
    (outside / "secret.txt").write_text("not for the UI\n")
    return {"root": root, "held": held, "outside": outside}


def _allow(layout: dict[str, Path]) -> Allowlist:
    return Allowlist.build(
        [str(layout["root"])], held_out=[str(layout["held"])], answer_keys=[], harness=None
    )


def test_a_file_beneath_a_root_resolves_to_its_real_path(layout: dict[str, Path]) -> None:
    path = layout["root"] / "run-1" / "events.jsonl"
    assert _allow(layout).resolve(path) == Path(os.path.realpath(path))


def test_an_absolute_path_outside_every_root_is_refused(layout: dict[str, Path]) -> None:
    with pytest.raises(PathRefusedError, match="outside every root"):
        _allow(layout).resolve(layout["outside"] / "secret.txt")


def test_a_relative_path_is_refused(layout: dict[str, Path]) -> None:
    with pytest.raises(PathRefusedError, match="relative"):
        _allow(layout).resolve("runs/run-1/events.jsonl")


def test_a_dot_dot_that_climbs_out_of_the_root_is_refused(layout: dict[str, Path]) -> None:
    climbing = f"{layout['root']}/run-1/../../outside/secret.txt"
    with pytest.raises(PathRefusedError, match="outside every root"):
        _allow(layout).resolve(climbing)


def test_a_dot_dot_into_the_held_out_tier_is_refused(layout: dict[str, Path]) -> None:
    climbing = f"{layout['root']}/../held/scenario.json"
    with pytest.raises(PathRefusedError):
        _allow(layout).resolve(climbing)


def test_a_symlink_inside_a_root_pointing_out_is_judged_where_it_lands(
    layout: dict[str, Path],
) -> None:
    """The case that tells resolving first from checking first.

    The link's own name lies beneath the root, so a check on the unresolved spelling passes it;
    only resolving before the check sees that it lands outside every root.
    """
    link = layout["root"] / "run-1" / "out"
    link.symlink_to(layout["outside"])
    with pytest.raises(PathRefusedError, match="outside every root"):
        _allow(layout).resolve(link / "secret.txt")


def test_a_chain_of_symlinks_out_of_the_root_is_refused(layout: dict[str, Path]) -> None:
    hop = layout["root"] / "run-1" / "hop"
    hop.symlink_to(layout["root"] / "run-1" / "hop2")
    (layout["root"] / "run-1" / "hop2").symlink_to(layout["outside"] / "secret.txt")
    with pytest.raises(PathRefusedError, match="outside every root"):
        _allow(layout).resolve(hop)


def test_a_symlink_inside_a_root_pointing_at_the_held_out_tier_is_refused(
    layout: dict[str, Path],
) -> None:
    link = layout["root"] / "run-1" / "tier"
    link.symlink_to(layout["held"])
    with pytest.raises(PathRefusedError):
        _allow(layout).resolve(link / "scenario.json")


def test_percent_encoded_and_double_encoded_spellings_are_literal_names_and_never_decoded(
    layout: dict[str, Path],
) -> None:
    """The resolver takes filesystem paths, never URLs: an encoded ``..`` is a file name.

    It names nothing that exists, so it resolves to a path beneath the root that the reader
    will not find; it never climbs. (The request-level forms are in the route tests.)
    """
    allow = _allow(layout)
    for spelling in ("%2e%2e/%2e%2e/outside/secret.txt", "%252e%252e/outside/secret.txt"):
        resolved = allow.resolve(f"{layout['root']}/run-1/{spelling}")
        assert str(resolved).startswith(os.path.realpath(layout["root"]))
        assert not resolved.exists()


def test_a_case_variant_of_the_held_out_tier_is_refused(layout: dict[str, Path]) -> None:
    variant = str(layout["held"]).replace("/held", "/HELD") + "/scenario.json"
    with pytest.raises(PathRefusedError):
        _allow(layout).resolve(variant)


def test_a_case_variant_of_a_root_is_allowed_only_where_the_volume_folds_case(
    layout: dict[str, Path],
) -> None:
    """A permit follows the filesystem: same directory by inode, or refused."""
    variant = Path(str(layout["root"]).replace("/runs", "/RUNS")) / "run-1" / "events.jsonl"
    allow = _allow(layout)
    if variant.exists():  # this volume folds case: it is the same file
        assert allow.resolve(variant).samefile(layout["root"] / "run-1" / "events.jsonl")
    else:
        with pytest.raises(PathRefusedError, match="outside every root"):
            allow.resolve(variant)


def test_a_trailing_slash_resolves_like_the_plain_path(layout: dict[str, Path]) -> None:
    allow = _allow(layout)
    assert allow.resolve(f"{layout['root']}/run-1/") == allow.resolve(layout["root"] / "run-1")
    with pytest.raises(PathRefusedError):
        allow.resolve(f"{layout['held']}/")


def test_a_nul_byte_is_refused(layout: dict[str, Path]) -> None:
    with pytest.raises(PathRefusedError, match="NUL"):
        _allow(layout).resolve(f"{layout['root']}/run-1/events.jsonl\x00.png")


def test_the_held_out_tier_itself_is_refused_even_when_it_is_named_exactly(
    layout: dict[str, Path],
) -> None:
    allow = Allowlist.build(
        [str(layout["root"]), str(layout["outside"])],
        held_out=[str(layout["held"])],
        answer_keys=[],
        harness=None,
    )
    with pytest.raises(PathRefusedError):
        allow.resolve(layout["held"] / "scenario.json")


def test_a_hard_link_to_a_file_is_refused_since_its_other_name_may_be_refused(
    layout: dict[str, Path],
) -> None:
    os.link(layout["held"] / "scenario.json", layout["root"] / "run-1" / "innocent.json")
    with pytest.raises(PathRefusedError, match="more than one name"):
        _allow(layout).resolve(layout["root"] / "run-1" / "innocent.json")


@pytest.mark.parametrize("name", [".credentials.json", "key", "key-helper.sh", ".env", ".ENV"])
def test_a_credential_or_environment_file_inside_a_root_is_refused(
    layout: dict[str, Path], name: str
) -> None:
    secret = layout["root"] / "run-1" / "sessions" / "s1" / "config" / name
    secret.parent.mkdir(parents=True)
    secret.write_text("token\n")
    with pytest.raises(PathRefusedError, match="credential"):
        _allow(layout).resolve(secret)


def test_anything_inside_a_corpus_directory_is_refused(layout: dict[str, Path]) -> None:
    corpus = layout["root"] / "run-1" / "worktrees" / "s1" / "Corpora"
    corpus.mkdir(parents=True)
    (corpus / "a.json").write_text("{}\n")
    with pytest.raises(PathRefusedError, match="corpus"):
        _allow(layout).resolve(corpus / "a.json")


# -- at start ---------------------------------------------------------------------------


def test_a_root_containing_the_held_out_tier_refuses_the_start(layout: dict[str, Path]) -> None:
    with pytest.raises(StartupRefusedError, match="overlaps"):
        Allowlist.build(
            [str(layout["root"].parent)],
            held_out=[str(layout["held"])],
            answer_keys=[],
            harness=None,
        )


def test_a_root_inside_the_held_out_tier_refuses_the_start(layout: dict[str, Path]) -> None:
    inner = layout["held"] / "inner"
    inner.mkdir()
    with pytest.raises(StartupRefusedError, match="overlaps"):
        Allowlist.build([str(inner)], held_out=[str(layout["held"])], answer_keys=[], harness=None)


def test_a_root_reaching_the_held_out_tier_through_a_symlink_refuses_the_start(
    layout: dict[str, Path],
) -> None:
    link = layout["outside"] / "looks-harmless"
    link.symlink_to(layout["held"])
    with pytest.raises(StartupRefusedError, match="overlaps"):
        Allowlist.build([str(link)], held_out=[str(layout["held"])], answer_keys=[], harness=None)


def test_an_answer_key_is_refused_like_the_held_out_tier(layout: dict[str, Path]) -> None:
    with pytest.raises(StartupRefusedError, match="overlaps"):
        Allowlist.build(
            [str(layout["root"].parent)],
            held_out=[],
            answer_keys=[str(layout["held"])],
            harness=None,
        )


def test_the_harness_checkout_s_corpora_is_always_refused(tmp_path: Path) -> None:
    checkout = tmp_path / "checkout"
    (checkout / "corpora").mkdir(parents=True)
    with pytest.raises(StartupRefusedError, match="overlaps"):
        Allowlist.build([str(checkout)], held_out=[], answer_keys=[], harness=checkout)


def test_a_relative_held_out_path_refuses_the_start(layout: dict[str, Path]) -> None:
    with pytest.raises(StartupRefusedError, match="absolute"):
        Allowlist.build([str(layout["root"])], held_out=["held"], answer_keys=[], harness=None)


@pytest.mark.parametrize("bad", ["", "does-not-exist", "file"])
def test_a_root_that_is_not_an_existing_directory_refuses_the_start(
    layout: dict[str, Path], bad: str
) -> None:
    (layout["outside"] / "file").write_text("x\n")
    given = str(layout["outside"] / bad) if bad else "\x00"
    with pytest.raises(StartupRefusedError):
        Allowlist.build([given], held_out=[], answer_keys=[], harness=None)


def test_no_root_refuses_the_start() -> None:
    with pytest.raises(StartupRefusedError, match="at least one root"):
        Allowlist.build([], held_out=[], answer_keys=[], harness=None)
