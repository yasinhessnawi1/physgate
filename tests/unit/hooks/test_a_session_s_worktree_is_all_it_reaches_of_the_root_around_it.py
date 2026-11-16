"""A session given its own place in a root withheld whole reaches its worktree there, nothing else.

A protected trial's raw session, and a blind check's, works in a place of its own inside a root
every run withholds (the store's work root, the store). A list of what lies beside that place,
taken at the install, misses an entry made there later. So the root is withheld whole, by rule,
but for the session's worktree in its place: on the hook layer for the file tools and the shell,
whatever spelling reaches it (``..``, a link the session makes, another case where the volume
ignores case), and on the OS layer for both platforms' profiles, where the root is denied and the
worktree alone is opened again. The two layers say the same thing: the rest of the place (the
session's login, its hook records, and anything made there beside the worktree, before the
install or after it) is refused to every file tool and every shell. The one other thing the
session reads there is named exactly, on both layers: the directory of the interpreter its
commands run (holding ``python3``, a link to the recorded interpreter), when it has one.

The allowance is held exactly, as every allowance of the hook layer is: inside its worktree a
Read of a symbolic link, or of a file with a second name, is refused too. A known cost, kept.

The two options are taken only together, and only with the place a real directory, no link on
the way, inside every root named.
"""

from __future__ import annotations

import os
from pathlib import Path

import pytest

from physgate.hooks import paths, shell_paths
from physgate.hooks.config import SessionConfig
from physgate.hooks.settings import InstallRequest, build_config
from physgate.hooks.settings import current_installation as installation
from physgate.hooks.shell import parse
from physgate.oslayer.policy import sandbox_policy

MARKED = "marked.txt"
LATE = "late-5e2a91"


@pytest.fixture
def rig(tmp_path: Path) -> Path:
    root = tmp_path.resolve()
    work = root / "work"
    place = work / "trial" / "place"
    for d in ("worktree", "session/state", "session/session", "session/config", "session/home"):
        (place / d).mkdir(parents=True)
    (place / "worktree" / "README.md").write_text("the session's own\n")
    (work / "trial" / "harness").mkdir()
    (work / "trial" / "harness" / MARKED).write_text("beside, at the install\n")
    return root


def _options() -> None:
    fields = InstallRequest.model_fields
    assert "withheld_whole" in fields and "own_place" in fields, (
        "the installer takes no root withheld whole but for the session's own place"
    )


def _fields(root: Path, **changes: object) -> dict[str, object]:
    work, place = root / "work", root / "work" / "trial" / "place"
    sdir = place / "session"
    return {
        "profile": "baseline",
        "role": None,
        "worktree": str(place / "worktree"),
        "own_branch": None,
        "store_root": None,
        "state_dir": str(sdir / "state"),
        "target_dir": str(sdir / "session"),
        "claude_config_dir": str(sdir / "config"),
        "user_home": str(sdir / "home"),
        "token_ceiling": 1000,
        "sessions_root": str(sdir),
        # The list, as at the install: what lay beside the way down to the place.
        "held_out": (str(work / "trial" / "harness"),),
        "temp_dir": str(root / "temps" / "own"),
        "session_temps": str(root / "temps"),
        "shared_claude_temp": (str(root / "claude-temp"),),
        "withheld_whole": (str(work),),
        "own_place": str(place),
    } | changes


def _config(root: Path, **changes: object) -> SessionConfig:
    _options()
    return build_config(InstallRequest(**_fields(root, **changes)), installation())  # type: ignore[arg-type]


def _late(root: Path) -> Path:
    """An entry made in the root after the install, by something other than the session."""
    late = root / "work" / LATE
    late.mkdir()
    (late / MARKED).write_text("made after the install\n")
    return late / MARKED


def _worktree(root: Path) -> Path:
    return root / "work" / "trial" / "place" / "worktree"


def _case_ignored(root: Path) -> bool:
    return (root / "WORK").exists()


def _spellings(root: Path) -> dict[str, str]:
    """Every way a session names the late entry, from its own worktree."""
    wt = _worktree(root)
    os.symlink(root / "work" / LATE, wt / "l")
    found = {
        "as it is": str(root / "work" / LATE / MARKED),
        "through ..": f"../../../{LATE}/{MARKED}",
        "through .. spelt absolute": f"{wt}/../../../{LATE}/{MARKED}",
        "through a link it made": f"l/{MARKED}",
        "through a link it made, absolute": str(wt / "l" / MARKED),
    }
    if _case_ignored(root):
        found["by another case"] = str(root / "work" / LATE.upper() / MARKED)
    return found


def test_an_entry_made_in_the_root_after_the_install_is_refused_to_every_file_tool(
    rig: Path,
) -> None:
    config = _config(rig)
    late = _late(rig)
    wt = str(_worktree(rig))
    assert late.read_text()  # not vacuous: it is there to read
    for name, spelling in _spellings(rig).items():
        assert paths.protection(spelling, wt, config, writing=False) is not None, name
        assert paths.protection(spelling, wt, config, writing=True) is not None, name


def test_an_entry_made_in_the_root_after_the_install_is_refused_to_every_shell_read(
    rig: Path,
) -> None:
    config = _config(rig)
    _late(rig)
    wt = str(_worktree(rig))
    for name, spelling in _spellings(rig).items():
        for command in (
            f"cat {spelling}",
            f"head -c 9 {spelling}",
            f"ls {os.path.dirname(spelling)}",
        ):
            assert shell_paths.check(parse(command)[0], wt, config) is not None, (name, command)


def test_the_root_itself_and_what_was_beside_the_place_at_the_install_stay_refused(
    rig: Path,
) -> None:
    config = _config(rig)
    wt = str(_worktree(rig))
    for path in (rig / "work", rig / "work" / "trial", rig / "work" / "trial" / "harness" / MARKED):
        assert paths.protection(str(path), wt, config, writing=False) is not None, path
        assert paths.protection(str(path / "new"), wt, config, writing=True) is not None, path
    assert shell_paths.check(parse(f"ls {rig / 'work'}")[0], wt, config) is not None


def test_the_session_s_own_worktree_stays_its_own_to_read_and_write(rig: Path) -> None:
    config = _config(rig)
    wt = _worktree(rig)
    for path in (wt / "README.md", wt / "new.txt", wt / "sub" / "deeper.txt"):
        assert paths.protection(str(path), str(wt), config, writing=False) is None, path
        assert paths.protection(str(path), str(wt), config, writing=True) is None, path
    assert paths.protection("README.md", str(wt), config, writing=False) is None
    for command in ("cat README.md", f"cat {wt / 'README.md'}", "ls", "echo x > out.txt"):
        assert shell_paths.check(parse(command)[0], str(wt), config) is None, command


def test_what_the_place_holds_beside_the_worktree_stays_refused(rig: Path) -> None:
    """The session's login, settings and hook records lie in its place: refused as before."""
    config = _config(rig)
    wt = str(_worktree(rig))
    sdir = rig / "work" / "trial" / "place" / "session"
    for path in (sdir / "state" / "x", sdir / "config" / "x", sdir / "session" / "x"):
        assert paths.protection(str(path), wt, config, writing=False) is not None, path


def test_a_read_of_a_link_or_a_second_name_inside_the_worktree_is_refused(rig: Path) -> None:
    """The known cost of an exact allowance: even when it points at the session's own file."""
    config = _config(rig)
    wt = _worktree(rig)
    os.symlink(wt / "README.md", wt / "readme-link")
    os.link(wt / "README.md", wt / "readme-again")
    for name in ("readme-link", "readme-again"):
        assert paths.protection(str(wt / name), str(wt), config, writing=False) is not None, name
        assert shell_paths.check(parse(f"cat {name}")[0], str(wt), config) is not None, name


def test_the_root_is_withheld_by_one_rule_never_put_back(rig: Path) -> None:
    config = _config(rig)
    place = str(rig / "work" / "trial" / "place")
    wt = str(_worktree(rig))
    (root,) = [r for r in config.protected_roots if r.path == str(rig / "work")]
    assert root.reads == "denied" and root.watch == "none", root
    # The worktree is the one exception, to reads and to writes, as the OS layer's is.
    assert root.read_exceptions == (wt,), root
    assert wt in root.exceptions and place not in root.exceptions, root
    assert paths.read_refused(str(rig / "work" / "anything"), config)


def _beside(root: Path) -> Path:
    """An entry made inside the place, beside the worktree, after the install."""
    beside = root / "work" / "trial" / "place" / LATE
    beside.mkdir()
    (beside / MARKED).write_text("made beside the worktree\n")
    return beside / MARKED


def test_an_entry_inside_the_place_beside_the_worktree_is_refused_to_every_file_tool(
    rig: Path,
) -> None:
    """As the OS layer refuses every shell there: the worktree, not the place, is the session's."""
    config = _config(rig)
    beside = _beside(rig)
    wt = str(_worktree(rig))
    place = rig / "work" / "trial" / "place"
    assert beside.read_text()  # not vacuous: it is there to read
    for spelling in (str(beside), f"../{LATE}/{MARKED}", f"{wt}/../{LATE}/{MARKED}"):
        assert paths.protection(spelling, wt, config, writing=False) is not None, spelling
        assert paths.protection(spelling, wt, config, writing=True) is not None, spelling
    # Nor is anything new made there, beside the worktree, or the place itself listed.
    for made in (place / "new.txt", place / "new" / "deeper.txt"):
        assert paths.protection(str(made), wt, config, writing=True) is not None, made
    assert paths.protection(str(place), wt, config, writing=False) is not None


def test_an_entry_inside_the_place_beside_the_worktree_is_refused_to_every_shell(
    rig: Path,
) -> None:
    config = _config(rig)
    beside = _beside(rig)
    wt = str(_worktree(rig))
    for command in (
        f"cat {beside}",
        f"cat ../{LATE}/{MARKED}",
        "ls ..",
        f"echo x > ../{LATE}/new.txt",
    ):
        assert shell_paths.check(parse(command)[0], wt, config) is not None, command


def test_the_interpreter_s_directory_is_the_one_other_thing_it_reads_there(
    rig: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Named exactly, as the OS layer names it: its commands run ``python3`` from there."""
    sdir = rig / "work" / "trial" / "place" / "session"
    bin_dir = sdir / "bin"
    bin_dir.mkdir()
    config = _config(rig, os_layer_readable=(str(bin_dir),))
    wt = str(_worktree(rig))
    (root,) = [r for r in config.protected_roots if r.path == str(rig / "work")]
    assert root.read_exceptions == (wt, str(bin_dir)), root
    assert str(bin_dir) not in root.exceptions, root  # read, never written
    monkeypatch.setenv("PATH", f"{bin_dir}:/usr/bin:/bin")
    for command in (f"ls {bin_dir}", "echo $PATH"):
        assert shell_paths.check(parse(command)[0], wt, config) is None, command
    # Nothing else of the session's directory comes with it.
    for command in (f"ls {sdir}", f"ls {sdir / 'state'}", f"cat {sdir / 'config' / 'x'}"):
        assert shell_paths.check(parse(command)[0], wt, config) is not None, command
    assert paths.protection(str(bin_dir / "x"), wt, config, writing=True) is not None


@pytest.mark.parametrize("platform", ["darwin", "linux"])
def test_the_os_layer_denies_the_root_and_opens_the_worktree_alone(
    rig: Path, platform: str
) -> None:
    config = _config(rig)
    place = rig / "work" / "trial" / "place"
    policy = sandbox_policy(
        config,
        home=str(place / "session" / "home"),
        temp_dir=str(rig / "temps" / "own"),
        platform=platform,
    )
    fs = policy.settings["sandbox"]["filesystem"]

    def covered(path: Path, listed: list[str]) -> bool:
        return any(str(path) == d or str(path).startswith(d.rstrip("/") + "/") for d in listed)

    assert covered(rig / "work" / LATE / MARKED, fs["denyRead"]), fs["denyRead"]
    assert covered(_worktree(rig) / "README.md", fs["allowRead"]), fs["allowRead"]
    # Written as the working directory always is, named where the root around it is denied.
    assert covered(_worktree(rig) / "new.txt", fs["allowWrite"]), fs["allowWrite"]
    for kept in ("state", "config", "session"):
        assert not covered(place / "session" / kept / "x", fs["allowRead"]), (kept, fs)
    assert not covered(rig / "work" / LATE / MARKED, fs["allowRead"]), fs["allowRead"]
    assert not covered(place / "x", fs["allowRead"]), fs["allowRead"]


def _refused(root: Path, **changes: object) -> str:
    _options()
    with pytest.raises(ValueError) as raised:
        build_config(InstallRequest(**_fields(root, **changes)), installation())  # type: ignore[arg-type]
    return str(raised.value)


def test_the_root_without_the_place_is_refused(rig: Path) -> None:
    assert _refused(rig, own_place=None)


def test_the_place_without_a_root_is_refused(rig: Path) -> None:
    assert _refused(rig, withheld_whole=())


def test_a_place_outside_the_root_is_refused(rig: Path) -> None:
    other = rig / "other"
    (other / "worktree").mkdir(parents=True)
    assert _refused(rig, own_place=str(other), worktree=str(other / "worktree"))


def test_the_root_itself_as_the_place_is_refused(rig: Path) -> None:
    assert _refused(rig, own_place=str(rig / "work"))


def test_a_root_inside_the_place_is_refused(rig: Path) -> None:
    place = rig / "work" / "trial" / "place"
    assert _refused(rig, withheld_whole=(str(rig / "work"), str(place / "session")))


def test_a_worktree_outside_the_place_is_refused(rig: Path) -> None:
    (rig / "work" / "trial" / "elsewhere").mkdir()
    # Refused for the place itself, before any later check would meet a root around the worktree.
    assert "own place" in _refused(rig, worktree=str(rig / "work" / "trial" / "elsewhere"))


def test_a_place_that_is_a_link_is_refused(rig: Path) -> None:
    os.symlink(rig / "work" / "trial" / "place", rig / "work" / "trial" / "linked")
    linked = rig / "work" / "trial" / "linked"
    assert _refused(rig, own_place=str(linked), worktree=str(linked / "worktree"))


def test_a_place_reached_through_a_link_is_refused(rig: Path) -> None:
    os.symlink(rig / "work" / "trial", rig / "work" / "through")
    place = rig / "work" / "through" / "place"
    assert _refused(rig, own_place=str(place), worktree=str(place / "worktree"))


def test_a_place_that_is_not_there_or_not_a_directory_is_refused(rig: Path) -> None:
    absent = rig / "work" / "trial" / "absent"
    assert _refused(rig, own_place=str(absent), worktree=str(absent / "worktree"))
    (rig / "work" / "trial" / "file").write_text("x")
    filed = rig / "work" / "trial" / "file"
    assert _refused(rig, own_place=str(filed), worktree=str(filed / "worktree"))
